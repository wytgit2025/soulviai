# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""环境信息自动采集 —— 定位 / 天气
============================================================

原设计立场是「引擎自己不上网」：环境信息由调用方（Agent）查好后通过
`chat --env "上海 小雨 24°C"` 注入（见 social/sensors.py）。代价是终端 / 网页 /
微信 / QQ 这四条入口没有调用方，环境感知那层永远空转。

本模块补上这段：引擎自己取一次，取回来仍然走 sensors 的注入接口 ——
天气进 24 维心智修正，心智层逻辑一行不改。

三个数据源全部免 Key：

  · 定位      ip-api.com    只取「城市 / 经纬度」，不落库、不上报
                            限流时用 ipwho.is 兜底（英文城市名，查天气够用）
  · 天气      Open-Meteo    WMO 天气码，本模块自行映射中文描述
  · 地理编码  Open-Meteo    手填 city → 经纬度。缺了这一步，手填城市会因为拿
                            不到经纬度让天气整块消失，而且完全静默 —— 详见
                            _detect_location

这里刻意不建「新闻模块」：当日资讯交给 behavior/search.py 的通用搜索就够了
（Bing 主用、搜狗兜底），没必要为它单独维护一套资讯源与解析。

约束：

  · 一切失败静默降级 —— 拿不到就当没有，不阻塞对话、不把异常抛给上层；
  · 带 TTL 缓存（内存 + data/json/env_cache.json）。磁盘那份让「一次进程说一句话」
    的 soulviaictl chat 也不必每条消息都联网；
  · 冷启动最多等 cold_start_wait_seconds（默认 1.5s，**小于**单请求超时）。
    定位 + 天气最坏是 2 × timeout_seconds，拿 timeout_seconds 去 join 必然出现
    「等满了还什么都没拿到」：线程没干完，_read_cache() 仍是 None。宁可这一轮
    没有环境信息，也不要白等 4 秒；
  · 开关全在 config.json 的 env_auto 段，默认开，可逐项关。

接入点两处，都收在 ensure()：

  1) ChatPipeline.run() 开头 —— 对话触发。终端 / 网页 / 微信 / QQ / soulviaictl
     五条路因此全覆盖（clients/web.py 内部跑的就是 `main.py cli`）。
  2) 调度器任务 weather_refresh（soulviai.py 注册）—— 无人对话时保鲜。
     没有它，长驻模式下没人说话就没人更新，自主思考可能拿着昨天的天气开口。

优先级：调用方显式注入（chat --env）> 本模块自采。apply() 看到 sensors 的来源是
caller 就直接让步，否则用户说「我在北京出差」会被 IP 猜的城市反手覆盖。

日志前缀固定为 `[环境]`，且刻意不含 ASCII 报错词（timeout / connection / 401 …）：
engine_bridge._api_error() 会按这些词把引擎输出判成「模型后端故障」，
日志里出现它们会让一次正常对话被报成 API 错误。
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request

_LOCK = threading.RLock()
_SNAPSHOT = None            # 内存缓存：最近一次采集结果
_LOADED_FROM_DISK = False   # 是否已经尝试过读磁盘（避免反复开文件）
_REFRESHING = False         # 同一时刻只允许一个采集线程

_CACHE_PARTS = ("json", "env_cache.json")

# 残缺快照（该有天气却没拿到）的有效期：远短于 ttl_minutes，好让瞬时抖动
# 在下一轮就被重试，而不是被「缓存命中」挡上一整个 TTL。
_INCOMPLETE_TTL = 60.0

# ── 默认开关（config.json 的 env_auto 段逐项覆盖）──
DEFAULTS = {
    "enabled": True,          # 总开关
    "location": True,         # IP → 城市
    "weather": True,          # 天气（需要定位给出的经纬度）
    "city": "",               # 手填城市；留空才走 IP 定位
    "ttl_minutes": 30,        # 缓存有效期
    "timeout_seconds": 4,     # 单个请求超时
    "cold_start_wait_seconds": 1.5,   # 冷启动最多阻塞多久（要 < timeout_seconds）
}

_UA = "SoulMate/8.1 (+soulviai)"

# WMO 天气码 → 中文描述（Open-Meteo 用的就是这套编码）
_WMO_DESC = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨",
    56: "冻毛毛雨", 57: "冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
    80: "阵雨", 81: "阵雨", 82: "强阵雨",
    85: "阵雪", 86: "强阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "雷阵雨伴冰雹",
}

# 定位源：主源给中文城市名，备用源在限流时顶上（城市名是英文，查天气够用）。
# 注意 _IP_API 是 http —— ip-api.com 免费档**不提供** https，改成 https 会直接失效。
_IP_API = ("http://ip-api.com/json/?lang=zh-CN"
           "&fields=status,country,regionName,city,lat,lon")
_IPWHO = "https://ipwho.is/"

# 地理编码：手填城市 → 经纬度（免 Key，和天气同一个厂商）
_GEOCODE = ("https://geocoding-api.open-meteo.com/v1/search"
            "?name=%s&count=1&language=zh&format=json")


# ────────────────────────────────────────────────────────────
# 配置
# ────────────────────────────────────────────────────────────
def _cfg() -> dict:
    """默认值 + config.json:env_auto 覆盖。配置坏掉也要能跑。"""
    cfg = dict(DEFAULTS)
    try:
        from core import config as _config
        section = _config.get_section("env_auto") or {}
        for key, val in section.items():
            if key.startswith("_"):        # _note 之类的注释字段
                continue
            cfg[key] = val
    except Exception:
        pass
    for key, lo, hi in (("ttl_minutes", 1, 1440), ("timeout_seconds", 1, 30)):
        try:
            cfg[key] = min(hi, max(lo, int(cfg.get(key) or DEFAULTS[key])))
        except Exception:
            cfg[key] = DEFAULTS[key]
    return cfg


def _log(msg: str):
    """统一出口。前缀 [环境] 便于 grep，且不含 ASCII 报错词。"""
    try:
        print("[环境] %s" % msg)
    except Exception:
        pass


def enabled() -> bool:
    """自采是否可用：总开关开着，且 location / weather 至少有一个没关。

    soulviai.py 用它决定要不要注册 weather_refresh 定时任务 —— 关掉自采却还在
    定时联网，是最没道理的一种「关掉」。
    """
    cfg = _cfg()
    if not cfg.get("enabled"):
        return False
    return any(cfg.get(k) for k in ("location", "weather"))


# ────────────────────────────────────────────────────────────
# HTTP 小工具
# ────────────────────────────────────────────────────────────
def _http(url: str, timeout: float, as_json: bool = True):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    text = raw.decode("utf-8", "replace")
    return json.loads(text) if as_json else text


# ────────────────────────────────────────────────────────────
# 定位 / 天气
# ────────────────────────────────────────────────────────────
def _geocode_city(city: str, timeout: float) -> dict:
    """城市名 → 经纬度（Open-Meteo 地理编码，免 Key）。

    手填城市**必须**补这一步：_fetch_weather 拿不到经纬度直接返回空，只填名字
    等于把天气整块关掉，而且完全静默（apply 什么都不注入，日志也不报）。
    config.json 里 city 这个开关的卖点是「不暴露 IP」，不该以牺牲天气为代价。
    """
    # 重试一次。这一步失败等于天气整块消失（_fetch_weather 拿不到经纬度直接返回
    # 空），而它是免 Key 的小接口，瞬时抖动的概率远高于持续故障 —— 实测就撞到过
    # 一次一过性的失败。两次都失败才放弃，交给 _INCOMPLETE_TTL 的下轮重试。
    data = None
    for _ in range(2):
        try:
            data = _http(_GEOCODE % urllib.parse.quote(city), timeout)
            break
        except Exception:
            data = None
    if not isinstance(data, dict):
        return {}
    rows = data.get("results") or []
    if not rows:
        return {}
    top = rows[0] or {}
    lat, lon = top.get("latitude"), top.get("longitude")
    if lat is None or lon is None:
        return {}
    return {
        "lat": lat,
        "lon": lon,
        "country": top.get("country") or "",
        "region": top.get("admin1") or "",
    }


def _detect_location(timeout: float, cfg: dict) -> dict:
    """IP → 城市 / 经纬度。手填了 city 就只走地理编码，不再暴露 IP。

    ip-api.com 免费档限 45 次/分，突发调用会被限流，所以留了 ipwho.is 兜底
    （它返回英文城市名，只用来查天气，够用）。
    """
    manual = (cfg.get("city") or "").strip()
    if manual:
        # 城市 → 坐标基本不变，复用上一次解析结果，别每轮 TTL 过期都重查
        cached = (_read_cache() or {}).get("location") or {}
        if cached.get("city") == manual and cached.get("lat") is not None:
            return dict(cached)
        coords = _geocode_city(manual, timeout)
        if not coords:
            _log("手填城市「%s」没解析出经纬度，本轮跳过天气" % manual)
        loc = {"city": manual, "source": "config"}
        loc.update(coords)
        return loc

    try:
        data = _http(_IP_API, timeout)
        if isinstance(data, dict) and data.get("status") == "success":
            return {
                "city": data.get("city") or "",
                "region": data.get("regionName") or "",
                "country": data.get("country") or "",
                "lat": data.get("lat"),
                "lon": data.get("lon"),
                "source": "ip",
            }
    except Exception:
        pass

    try:
        data = _http(_IPWHO, timeout)
        if isinstance(data, dict) and data.get("success"):
            return {
                "city": data.get("city") or "",
                "region": data.get("region") or "",
                "country": data.get("country") or "",
                "lat": data.get("latitude"),
                "lon": data.get("longitude"),
                "source": "ip(备用)",
            }
    except Exception:
        pass
    return {}


def _parse_daily(raw: dict) -> dict:
    """把 Open-Meteo 的 daily 数组拍平成 {today, tomorrow}。取不到就返回空。"""
    def _at(key: str, idx: int):
        vals = raw.get(key) or []
        try:
            val = vals[idx]
        except Exception:
            return None
        return val

    days = []
    for idx in (0, 1):
        item = {}
        for key, name in (("temperature_2m_max", "temp_max"),
                          ("temperature_2m_min", "temp_min"),
                          ("precipitation_probability_max", "precip_prob"),
                          ("weather_code", "weather_code")):
            val = _at(key, idx)
            if val is not None:
                item[name] = val
        if item:
            days.append(item)
    if not days:
        return {}
    out = {"today": days[0]}
    if len(days) > 1:
        out["tomorrow"] = days[1]
    return out


def _fetch_weather(loc: dict, timeout: float) -> dict:
    lat, lon = loc.get("lat"), loc.get("lon")
    if lat is None or lon is None:
        return {}
    # daily 是同一次请求白送的，必须带上：只请求 current 的话「今天要带伞吗」
    # / 「明天冷不冷」只能含糊其辞（过去这类问题会转去走通用搜索）。
    # forecast_days=2 是为了「明天」。
    url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
           "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
           "weather_code,wind_speed_10m"
           "&daily=temperature_2m_max,temperature_2m_min,"
           "precipitation_probability_max,weather_code"
           "&timezone=auto&forecast_days=2") % (lat, lon)
    try:
        data = _http(url, timeout)
    except Exception:
        return {}
    cur = (data or {}).get("current") or {}
    code = cur.get("weather_code")
    snap = {
        "temperature": cur.get("temperature_2m"),
        "apparent": cur.get("apparent_temperature"),
        "humidity": cur.get("relative_humidity_2m"),
        "wind": cur.get("wind_speed_10m"),
        "weather_code": code,
        "description": _WMO_DESC.get(code, ""),
    }
    daily = _parse_daily((data or {}).get("daily") or {})
    if daily:
        snap["daily"] = daily
    return snap


# ────────────────────────────────────────────────────────────
# 缓存
# ────────────────────────────────────────────────────────────
def _cache_path() -> str:
    try:
        from core import paths as _paths
        return _paths.data_path(*_CACHE_PARTS)
    except Exception:
        return ""


def _read_cache():
    """内存优先，其次磁盘。都没有返回 None。"""
    global _SNAPSHOT, _LOADED_FROM_DISK
    with _LOCK:
        if _SNAPSHOT is not None:
            return _SNAPSHOT
        if _LOADED_FROM_DISK:
            return None
        _LOADED_FROM_DISK = True

    path = _cache_path()
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            snap = json.load(fh)
    except Exception:
        return None
    if isinstance(snap, dict) and snap.get("ts"):
        with _LOCK:
            _SNAPSHOT = snap
        return snap
    return None


def _write_cache(snap: dict):
    path = _cache_path()
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(snap, fh, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _incomplete(snap: dict, cfg: dict) -> bool:
    """这次采集是不是「该拿到的没拿到」。用于把重试间隔缩短到 60 秒。"""
    if cfg.get("weather") and not (snap.get("weather") or {}).get("description"):
        return True
    if cfg.get("location") and not (snap.get("location") or {}):
        return True
    return False


def _fresh(snap: dict, cfg: dict) -> bool:
    """缓存是否仍在有效期内。

    残缺快照（该有天气却没拿到）只算 60 秒新鲜，而不是整个 TTL。这不是洁癖：
    实测遇到过一次地理编码的瞬时抖动，结果天气整块消失 —— 因为那份没有天气的
    快照照样被 `ts` 判成新鲜，接下来 30 分钟每次 ensure() 都认为缓存可用、直接
    跳过重采，一次抖动被静默放大成半小时。宁可变「每分钟重试一次」。
    """
    try:
        age = time.time() - float(snap.get("ts") or 0)
    except Exception:
        return False
    if _incomplete(snap, cfg):
        return age < _INCOMPLETE_TTL
    return age < cfg["ttl_minutes"] * 60


# ────────────────────────────────────────────────────────────
# 采集
# ────────────────────────────────────────────────────────────
def refresh(cfg: dict = None) -> dict:
    """联网取一次，落盘并返回快照。任何一项失败都只是缺字段，不抛异常。"""
    cfg = cfg or _cfg()
    timeout = cfg["timeout_seconds"]
    snap = {"ts": time.time(), "location": {}, "weather": {}}

    if cfg.get("location") or cfg.get("weather"):
        snap["location"] = _detect_location(timeout, cfg)

    if cfg.get("weather"):
        snap["weather"] = _fetch_weather(snap["location"], timeout)

    _write_cache(snap)
    global _SNAPSHOT
    with _LOCK:
        _SNAPSHOT = snap
    _log(describe(snap))
    return snap


def _refresh_async(cfg: dict):
    """后台采集（同一时刻只跑一个）。返回线程对象，已在跑则返回 None。"""
    global _REFRESHING
    with _LOCK:
        if _REFRESHING:
            return None
        _REFRESHING = True

    def _work():
        global _REFRESHING
        try:
            refresh(cfg)
        except Exception:
            pass
        finally:
            with _LOCK:
                _REFRESHING = False

    thread = threading.Thread(target=_work, daemon=True, name="soulviai-env")
    thread.start()
    return thread


def warmup():
    """启动时预热（非阻塞）。等用户敲下第一句话时通常已经取回来了。"""
    cfg = _cfg()
    if not cfg.get("enabled"):
        return None
    if _read_cache() and _fresh(_read_cache(), cfg):
        return _read_cache()
    return _refresh_async(cfg)


def ensure(force: bool = False, block: bool = True):
    """对话入口调用：保证环境信息就绪并已注入。返回快照或 None。

    block=False 时永不等待（冷启动直接交给后台线程）。
    """
    cfg = _cfg()
    if not enabled():
        return None

    snap = _read_cache()
    if snap and not force:
        if _fresh(snap, cfg):
            apply(snap)
            return snap
        # 有过期缓存：先用旧的顶上，后台刷新，绝不拖慢这一轮
        apply(snap)
        _refresh_async(cfg)
        return snap

    # 冷启动：磁盘和内存都没有可用快照
    thread = _refresh_async(cfg)
    if block and thread is not None:
        # 等待上限必须**小于**单请求超时：定位 + 天气最坏是 2 × timeout_seconds，
        # 拿 timeout_seconds 去 join 必然出现「等满了还什么都没拿到」—— 线程还没
        # 干完，下面 _read_cache() 仍然是 None，白白卡住对话。宁可这一轮没有环境
        # 信息（warmup() 通常已经预热过了），也不要白等 4 秒。
        try:
            wait = float(cfg.get("cold_start_wait_seconds")
                         or DEFAULTS["cold_start_wait_seconds"])
            thread.join(min(30.0, max(0.2, wait)))
        except Exception:
            pass
    snap = _read_cache()
    if snap:
        apply(snap)
    return snap


# ────────────────────────────────────────────────────────────
# 常驻保鲜（调度器任务 weather_refresh）
# ────────────────────────────────────────────────────────────
def tick_interval_seconds() -> float:
    """weather_refresh 的建议间隔：TTL 的一半，下限 60 秒。

    取一半而不是整个 TTL，是因为 ensure() 只在**发现过期**时才刷新。按 TTL 注册
    会出现这种节奏：tick 时缓存 29 分钟（还算新鲜，只注入不刷新），下一个 tick
    已是 59 分钟 —— 实际刷新周期变成两倍 TTL。取一半，最坏滞后也只有半个 TTL。
    """
    cfg = _cfg()
    try:
        ttl = max(1, int(cfg.get("ttl_minutes") or DEFAULTS["ttl_minutes"]))
    except (TypeError, ValueError):
        ttl = DEFAULTS["ttl_minutes"]
    return max(60.0, ttl * 60 / 2.0)


def scheduled_tick():
    """调度器任务：无人对话时也保持环境信息新鲜。

    **必须非阻塞**。调度器是单线程串行执行的（_dispatch_loop → _tick →
    _execute_task 是 inline 调用，不是丢线程池），这个函数里等一次网络就会把
    life_engine（间隔 1 秒）连同其它所有任务一起卡住。所以走 ensure(block=False)：
    命中 TTL 时只重新注入 sensors，过期时把联网交给后台线程立刻返回。

    不需要传 force —— 调用方用 chat --env 显式注入时，apply() 自己会让步。
    """
    return ensure(block=False)


# ────────────────────────────────────────────────────────────
# 注入 & 展示
# ────────────────────────────────────────────────────────────
def place_label(loc: dict) -> str:
    """把 location 拼成国 / 省 / 市的地名，去掉重复片段。

    去重不是美化，是必需的：ip-api 对直辖市会把 regionName 也填成「上海」，
    直接拼接会得到「中国 上海 上海」。规则是「新片段已被已有内容包含就跳过」，
    顺带也挡掉备用源把 city 给成英文时区域与城市互相包含的情形。
    """
    out = ""
    for raw in ((loc or {}).get("country"), (loc or {}).get("region"),
                (loc or {}).get("city")):
        frag = str(raw or "").strip()
        if not frag or (out and (frag in out or out in frag)):
            continue
        out = (out + " " + frag).strip()
    return out


def apply(snap: dict, force: bool = False) -> bool:
    """把快照注入 sensors：天气 → 24 维心智修正。

    调用方显式注入过（chat --env）就让步：Agent 掌握对话上下文，
    「我在北京出差」比 IP 猜出来的城市准。这个让步是必要的 —— 否则
    run_chat 刚注入完，ChatPipeline.run() 里的 ensure() 立刻把它覆盖掉。

    force=True 用于 `soulviact env --refresh` 这种**用户明确要求重采**的场景，
    那种情况下自采结果应该压过上一轮残留的 caller 注入。
    """
    if not snap:
        return False
    try:
        from engine import sensors as _sensors
    except Exception:
        return False

    if not force:
        try:
            if _sensors.has_caller_context():
                return False
        except Exception:
            pass

    weather = snap.get("weather") or {}
    if not weather:
        return False

    loc = snap.get("location") or {}
    # city 传裸城市名（sensors 拿它做天气关键词判定），place 传带省/国的地名
    # （给模型看）。只传 city 的话，「浙江」「中国」这些采到的字段永远到不了
    # prompt —— 和当年体感/湿度只进 soulviact env 是同一个毛病。
    payload = {"city": loc.get("city") or "",
               "place": place_label(loc),
               "description": weather.get("description") or ""}
    for key in ("temperature", "apparent", "humidity", "weather_code"):
        if weather.get(key) is not None:
            payload[key] = weather[key]

    # 今天/明天的温区与降水概率也一并给模型：这些字段已经在快照里了，
    # 只喂 current 等于采集了不用。
    today = (weather.get("daily") or {}).get("today") or {}
    for key in ("temp_max", "temp_min", "precip_prob"):
        if today.get(key) is not None:
            payload[key] = today[key]

    try:
        return bool(_sensors.set_external_context_json(payload, origin="engine"))
    except Exception:
        return False


def describe(snap: dict = None) -> str:
    """一句话摘要（日志 / `soulviact env` 用）。"""
    snap = snap if snap is not None else _read_cache()
    if not snap:
        return "尚未采集（可能是开关关闭，或取不到网络）"
    parts = []
    # 用 place_label 而不是裸 city：日志要和注进 prompt 的文本对得上，
    # 否则排查「模型怎么不知道我在浙江」时会被日志误导。
    place = place_label(snap.get("location") or {})
    weather = snap.get("weather") or {}
    if place:
        seg = place
        if weather.get("description"):
            seg += " " + weather["description"]
        if weather.get("temperature") is not None:
            seg += " %g°C" % float(weather["temperature"])
        today = (weather.get("daily") or {}).get("today") or {}
        if today.get("temp_min") is not None and today.get("temp_max") is not None:
            seg += "（今天 %g~%g°C）" % (float(today["temp_min"]),
                                         float(today["temp_max"]))
        parts.append(seg)
    if not parts:
        return "采集完成，但没取到可用信息"
    return "已感知：" + " ｜ ".join(parts)


def snapshot() -> dict:
    """当前快照（内存或磁盘缓存）。没有则返回空字典。"""
    return _read_cache() or {}


def status() -> dict:
    """结构化状态（`soulviact env --json` 用）。"""
    cfg = _cfg()
    snap = _read_cache() or {}
    age = None
    if snap.get("ts"):
        try:
            age = int(time.time() - float(snap["ts"]))
        except Exception:
            age = None
    return {
        "enabled": bool(cfg.get("enabled")),
        "switches": {k: cfg.get(k) for k in ("location", "weather")},
        "ttl_minutes": cfg.get("ttl_minutes"),
        "fresh": bool(snap) and _fresh(snap, cfg),
        "age_seconds": age,
        "snapshot": snap,
        "summary": describe(snap),
    }


def text() -> str:
    """人类可读的多行展示（`soulviact env` 用）。"""
    cfg = _cfg()
    lines = ["【环境信息】" + describe(None)]
    if not cfg.get("enabled"):
        lines.append("（总开关关闭：config.json → env_auto.enabled = false）")
        return "\n".join(lines)

    snap = _read_cache() or {}
    loc = snap.get("location") or {}
    if loc.get("city"):
        lines.append("位置：%s（%s）" % (place_label(loc),
                                       loc.get("source") or "-"))

    weather = snap.get("weather") or {}
    if weather:
        bits = [weather.get("description") or "未知"]
        if weather.get("temperature") is not None:
            bits.append("%g°C" % float(weather["temperature"]))
        if weather.get("apparent") is not None:
            bits.append("体感 %g°C" % float(weather["apparent"]))
        if weather.get("humidity") is not None:
            bits.append("湿度 %s%%" % weather["humidity"])
        if weather.get("wind") is not None:
            bits.append("风 %s km/h" % weather["wind"])
        lines.append("天气：" + "，".join(bits))

        daily = weather.get("daily") or {}
        for key, label in (("today", "今天"), ("tomorrow", "明天")):
            day = daily.get(key) or {}
            if not day:
                continue
            seg = []
            if day.get("temp_min") is not None and day.get("temp_max") is not None:
                seg.append("%g~%g°C" % (float(day["temp_min"]),
                                        float(day["temp_max"])))
            if day.get("precip_prob") is not None:
                seg.append("降水概率 %s%%" % day["precip_prob"])
            code = day.get("weather_code")
            if code is not None and _WMO_DESC.get(code):
                seg.append(_WMO_DESC[code])
            if seg:
                lines.append("%s：%s" % (label, "，".join(seg)))

    if not snap:
        lines.append("（还没采集过；聊一次天或跑 soulviact env --refresh）")
    return "\n".join(lines)
