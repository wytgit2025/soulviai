# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""环境感知引擎 — 外部上下文注入 + 天气→心智映射

本模块只负责**接收与注入**，自己不上网。环境信息有两条来源：

  1) 调用方注入（显式，优先）
     python3 scripts/soulviaictl.py chat --text "..." --env "上海 小雨 24°C"
     好处：Agent 掌握对话上下文，比按 IP 猜城市更准；沙箱内纯参数传递也能用。

  2) 引擎自采（social/env_source.py，开关见 config.json 的 env_auto 段）
     没等到注入时自己查一次 IP 定位 + Open-Meteo 天气，两个源都免 Key。
     取不到就静默降级 —— 宁可没有环境信息，也不要阻塞对话。

优先级：**当轮显式注入 > 引擎自采**。engine_bridge.run_chat 在每轮开头把来源
重置为「引擎可写」，调用方一旦注入就标成 caller，env_source.apply() 看到
caller 会让步 —— 否则用户说了「我在北京出差」，会被 IP 猜的城市反手覆盖。

注入的内容会被：
  1) 原样作为【环境感知】注入推理 prompt（get_weather_context）
  2) 关键词/天气码推导出晴雨、温度、体感，驱动 24 维心智修正（apply_weather_to_mind）
"""
import re
import time
import threading

from core import config as cfg


def safe_print(*args, **kwargs):
    """安全打印，Windows GBK 终端下自动降级过滤 emoji"""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        text = " ".join(str(a) for a in args)
        text_clean = text.encode('ascii', 'replace').decode('ascii')
        print(text_clean, **kwargs)


# ── 外部环境上下文（唯一的环境信息来源）──
_external_context = ""
_external_flags: dict = {}
_external_origin = "engine"   # "caller"（调用方显式注入）| "engine"（引擎自采）
_updated_at = 0.0
_lock = threading.Lock()

# 关键词 → 天气状态（驱动 24 维心智修正）
# 中文 + 英文双语匹配：--env 传什么都尽量认得出。匹配前英文统一转小写。
_RAIN_WORDS = ("雨", "雷", "毛毛雨", "降水",
               "rain", "drizzle", "shower", "thunder", "storm", "precip")
_SNOW_WORDS = ("雪", "霰", "snow", "sleet", "blizzard")
_EXTREME_WORDS = ("暴雨", "大暴雨", "特大暴雨", "暴雪", "雷暴", "雷阵雨",
                  "台风", "飓风", "冰雹", "沙尘暴", "极端",
                  "thunderstorm", "typhoon", "hurricane", "tornado",
                  "hail", "extreme")
_SUNNY_WORDS = ("晴", "sunny", "clear")
_CLOUDY_WORDS = ("多云", "partly", "cloudy")
_OVERCAST_WORDS = ("阴", "overcast")
_FOG_WORDS = ("雾", "霾", "fog", "haze", "smog", "mist")

# WMO 天气码分类（用于从 weather_code 反推状态）
_WMO_RAIN = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
_WMO_SNOW = {71, 73, 75, 77, 85, 86}
_WMO_EXTREME = {65, 75, 82, 86, 95, 96, 99}

# 温度提取：24 / 24°C / 24℃ / 24度 / 24C / 24 celsius 都认；华氏自动换算
_CELSIUS_RE = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*(?:°|º)?\s*(?:c\b|℃|度|celsius\b)", re.I)
_FAHREN_RE = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*(?:°|º)?\s*(?:f\b|℉|fahrenheit\b)", re.I)

# ── 天气 → 心智修正映射 ──
_WEATHER_MIND_MODIFIERS = {
    # (维度, 修正值, 概率)
    "rain": [
        ("chaotic_mood", 0.008, 0.6),     # 下雨容易感性
        ("emptiness", 0.004, 0.5),         # 雨天容易觉得空落
        ("obsession", 0.005, 0.45),        # 雨天容易多想
        ("life_vitality", -0.003, 0.4),   # 活力略微下降
    ],
    "snow": [
        ("joy", 0.005, 0.5),               # 下雪有时开心
        ("emptiness", 0.003, 0.4),
        ("healing_reflection", 0.004, 0.5),# 雪天容易反思
    ],
    "cloudy": [
        ("chaotic_mood", 0.004, 0.4),      # 阴天略压抑
        ("life_vitality", -0.002, 0.35),
    ],
    "extreme": [
        ("chaotic_mood", 0.012, 0.7),      # 极端天气情绪扰动
        ("emotional_volatility", 0.01, 0.6),
        ("restraint", -0.005, 0.5),        # 没那么克制
    ],
    "hot": [                                # 温度 > 30°C
        ("fatigue", 0.008, 0.5),            # 热天容易累
        ("life_vitality", -0.003, 0.4),
    ],
    "cold": [                               # 温度 < 5°C
        ("dependence", 0.005, 0.45),        # 冷天想要陪伴
        ("loneliness", 0.004, 0.4),
    ],
    "clear": [
        ("joy", 0.005, 0.4),               # 晴天心情好
        ("life_vitality", 0.003, 0.4),
    ],
}


# ────────────────────────────────────────────────────────────
# 外部环境上下文注入
# ────────────────────────────────────────────────────────────
def _flags_from_code(code):
    """由 WMO 天气码反推 (is_raining, is_snowing, is_extreme)。"""
    if code is None:
        return False, False, False
    return (code in _WMO_RAIN, code in _WMO_SNOW, code in _WMO_EXTREME)


def _parse_env_flags(text: str) -> dict:
    """从自由文本里推导天气状态（中英双语，英文忽略大小写）。"""
    flags = {}
    if not text:
        return flags
    low = text.lower()

    def hit(words):
        """中文直接匹配；英文按小写匹配，避免大小写差异漏判。"""
        return any((w in text) if not w.isascii() else (w in low) for w in words)

    if hit(_SNOW_WORDS):
        flags["is_snowing"] = True
    if hit(_RAIN_WORDS):
        flags["is_raining"] = True
    if hit(_EXTREME_WORDS):
        flags["is_extreme"] = True

    # 温度：优先摄氏；只有华氏时自动换算
    m = _CELSIUS_RE.search(text)
    if m:
        try:
            flags["temperature"] = float(m.group(1))
        except ValueError:
            pass
    else:
        m = _FAHREN_RE.search(text)
        if m:
            try:
                flags["temperature"] = round((float(m.group(1)) - 32) * 5 / 9, 1)
            except ValueError:
                pass

    # 天气码
    if hit(_SUNNY_WORDS):
        flags["weather_code"] = 0
    elif hit(_CLOUDY_WORDS):
        flags["weather_code"] = 2
    elif hit(_OVERCAST_WORDS):
        flags["weather_code"] = 3
    elif hit(_FOG_WORDS):
        flags["weather_code"] = 45
    if flags.get("is_raining"):
        flags["weather_code"] = 61
    elif flags.get("is_snowing"):
        flags["weather_code"] = 71

    return flags


def _store(text, flags, origin="caller"):
    """写入环境上下文与推导状态（内部）。

    origin: "caller" 表示调用方显式注入，env_source.apply() 会让步于它。
    """
    global _external_context, _external_flags, _external_origin, _updated_at
    text = (text or "").strip()
    with _lock:
        _external_context = text
        _external_flags = dict(flags or {})
        _external_origin = origin or "caller"
        _updated_at = time.time() if text else 0.0
    if text:
        safe_print("[Sensors] 已注入外部环境上下文: %s" % text)
    return bool(text)


def set_external_context(text: str, origin: str = "caller") -> bool:
    """注入外部环境上下文（自由文本）。

    中英文都可以，例如「上海 小雨 24°C」或「Shanghai light rain 24C」：
      1) 原样作为【环境感知】注入推理 prompt；
      2) 关键词推导出天气状态，驱动 24 维心智修正。
    传空字符串等于清除。返回 True 表示成功注入。
    """
    text = (text or "").strip()
    return _store(text, _parse_env_flags(text) if text else {}, origin)


def set_external_context_json(data: dict, origin: str = "caller") -> bool:
    """结构化注入环境上下文（推荐，比自由文本更稳）。

    支持字段（都可选，缺的会自动推导）：
      city / location              城市名（用于关键词判定）
      place                        地名，给模型看的显示名，可含省/国家
                                   （缺省时用 city；env_source 自采会传
                                   「中国 浙江 杭州」，city 仍是「杭州」）
      description / weather        天气描述（中英文均可）
      temperature                  温度（摄氏；华氏请自行换算）
      apparent / feels_like        体感温度（摄氏）
      humidity                     相对湿度（%）
      weather_code                 WMO 天气码
      temp_max / temp_min          今天最高/最低温（摄氏）
      precip_prob                  降水概率（%）
      is_raining / is_snowing / is_extreme   直接指定状态

    返回 True 表示成功注入。
    """
    if not isinstance(data, dict) or not data:
        return False

    city = str(data.get("city") or data.get("location") or "").strip()
    # 显示名与判定名分开：place 可能带省/国家（自采走 IP 时是「中国 浙江 杭州」），
    # 而 city 保持裸城市名 —— 下面 _parse_env_flags 拿它推导天气关键词，
    # 掺进「浙江省」之类只会白白扩大误判面。
    place = str(data.get("place") or "").strip() or city
    desc = str(data.get("description") or data.get("weather")
               or data.get("desc") or "").strip()

    flags = {}
    code = data.get("weather_code")
    if code is not None:
        try:
            flags["weather_code"] = int(code)
        except (TypeError, ValueError):
            pass

    # 数值字段：温度/体感/湿度/今天最高最低/降水概率
    for key, aliases in (("temperature", ("temperature", "temp")),
                         ("apparent", ("apparent", "feels_like")),
                         ("humidity", ("humidity",)),
                         ("temp_max", ("temp_max", "temperature_max")),
                         ("temp_min", ("temp_min", "temperature_min")),
                         ("precip_prob", ("precip_prob", "precipitation_probability"))):
        for name in aliases:
            val = data.get(name)
            if val is None:
                continue
            try:
                flags[key] = round(float(val), 1)
                break
            except (TypeError, ValueError):
                continue

    # 文本推导：用于补齐 weather_code 与布尔状态
    from_text = _parse_env_flags("%s %s" % (city, desc)) if (city or desc) else {}

    # weather_code：显式给的优先，否则用文本推导
    if "weather_code" not in flags:
        flags["weather_code"] = from_text.get("weather_code")

    # 布尔状态优先级：显式字段 > 文本判定 > 由天气码推导
    code_flags = _flags_from_code(flags.get("weather_code"))
    for key, code_val in zip(("is_raining", "is_snowing", "is_extreme"), code_flags):
        if key in data:
            flags[key] = bool(data[key])
        elif from_text.get(key):
            flags[key] = True
        else:
            flags[key] = code_val

    # 组装给 prompt 看的展示文本。体感/湿度过去只进了 `soulviact env` 的展示
    # （env_source.text()），没进这里 —— 采集了却不给模型看，等于白采。
    # 城市用 place（带省/国家）而不是裸 city，原因相同：IP 定位的
    # 「浙江」「中国」采到了就该让模型看见。
    parts = [p for p in (place, desc) if p]
    if flags.get("temperature") is not None:
        parts.append("%g°C" % flags["temperature"])
    if flags.get("apparent") is not None:
        parts.append("体感 %g°C" % flags["apparent"])
    if flags.get("humidity") is not None:
        parts.append("湿度 %g%%" % flags["humidity"])
    if flags.get("temp_min") is not None and flags.get("temp_max") is not None:
        parts.append("今天 %g~%g°C" % (flags["temp_min"], flags["temp_max"]))
    if flags.get("precip_prob") is not None:
        parts.append("降水概率 %g%%" % flags["precip_prob"])

    flags = {k: v for k, v in flags.items() if v is not None}
    return _store(" ".join(parts), flags, origin)


def get_external_context() -> str:
    """返回当前注入的外部环境上下文（未注入时为空字符串）。"""
    with _lock:
        return _external_context


def get_external_flags() -> dict:
    """返回当前环境状态（语言中立的结构化数据）。

    如 {'temperature': 24.0, 'weather_code': 61, 'is_raining': True, ...}
    供调用方用任意语言渲染。
    """
    with _lock:
        return dict(_external_flags)


def external_origin() -> str:
    """当前环境上下文的来源："caller"（调用方显式注入）或 "engine"（引擎自采）。"""
    with _lock:
        return _external_origin


def has_caller_context() -> bool:
    """当前上下文是不是调用方显式注入的（是的话引擎自采应该让步）。"""
    with _lock:
        return _external_origin == "caller" and bool(_external_context)


def reset_origin(origin: str = "engine"):
    """把来源重置为「引擎可写」。engine_bridge.run_chat 在每轮开头调用。

    不重置的话会有个隐性锁死：某一轮调用方注入过环境，来源就一直停在 caller，
    env_source.apply() 之后永远让步，引擎自采的天气再也进不来。
    """
    global _external_origin
    with _lock:
        _external_origin = origin or "engine"


def load_engine_config():
    """保留此接口以兼容启动流程。

    环境信息改由调用方注入或 env_source 自采（config.json 的 env_auto 段），
    这里不再读取任何配置项，因此函数体为空。
    """
    return


def init():
    """初始化钩子（保留以兼容 SoulEngine 启动流程）。"""
    safe_print("[Sensors] 环境感知就绪：优先采用 chat --env 注入，"
               "未注入时由 env_source 自采")


# ────────────────────────────────────────────────────────────
# 对外读取接口
# ────────────────────────────────────────────────────────────
def get_weather_context() -> str:
    """生成环境感知文本，用于注入推理 prompt。空字符串表示无环境信息。"""
    with _lock:
        ext = _external_context
        updated = _updated_at
    if not ext:
        return ""

    ctx = "【环境感知】\n" + ext
    if updated > 0:
        mins = int((time.time() - updated) / 60)
        if mins >= 1:
            ctx += "\n（%d 分钟前由调用方提供）" % mins
    return ctx


def get_current_weather() -> str:
    """返回当前环境的一句话描述（供自主思考取素材）。空字符串表示未注入。"""
    with _lock:
        return _external_context


def get_weather_summary() -> str:
    """人类可读摘要（debug / 状态查询用）。"""
    with _lock:
        ext = _external_context
    if not ext:
        return "[Sensors] 环境感知：未注入（调用方可用 chat --env 提供）"
    return "[Sensors] 📍 %s" % ext


def get_location_info() -> dict:
    """当前位置（城市 / 经纬度 / 来源）。没启用自采、或取不到时返回空字典。

    惰性 import：env_source 反过来依赖本模块，模块顶层互相导入会成环。
    """
    try:
        from . import env_source
        snap = env_source.snapshot()
    except Exception:
        return {}
    loc = (snap or {}).get("location") or {}
    return dict(loc)


def apply_weather_to_mind(user_id: str) -> dict:
    """天气影响 24 维心智，返回实际应用的修正量。

    数据来源是 set_external_context() 推导出的状态；未注入时返回空字典。
    """
    with _lock:
        flags = dict(_external_flags)

    if not flags:
        return {}

    temp = flags.get("temperature")
    # 冷热判定优先用体感：气温 28 / 体感 32 的那种闷热，只看气温判不出来
    feels = flags.get("apparent")
    if feels is None:
        feels = temp
    code = flags.get("weather_code")
    is_raining = flags.get("is_raining", False)
    is_snowing = flags.get("is_snowing", False)
    is_extreme = flags.get("is_extreme", False)

    # 场景判定
    conditions = []
    if is_raining:
        conditions.append("rain")
    if is_snowing:
        conditions.append("snow")
    if is_extreme:
        conditions.append("extreme")
    if feels is not None and feels > 30:
        conditions.append("hot")
    if feels is not None and feels < 5:
        conditions.append("cold")

    # 多云/阴天
    if code in (2, 3):
        conditions.append("cloudy")

    # 晴天。这里只排除「雨中带晴」这种自相矛盾的情形，**不再被温度条件挡掉** ——
    # 原来的 `and not conditions` 会让「晴 31°C」既拿到 hot 又永远拿不到 clear，
    # 天空状态和温度状态本来就不是互斥的。
    if code == 0 and not (is_raining or is_snowing or is_extreme):
        conditions.append("clear")

    import random as _r
    applied = {}
    for cond in conditions:
        modifiers = _WEATHER_MIND_MODIFIERS.get(cond, [])
        for dim, delta, prob in modifiers:
            if _r.random() < prob:
                # 累积同维度修正
                if dim in applied:
                    applied[dim] = round(applied[dim] + delta, 6)
                else:
                    applied[dim] = round(delta, 6)

    # 写入潜意识日志（极端天气 / 下雨）
    if is_extreme and "extreme" in conditions:
        _add_subconscious(user_id, "外面天气很极端，心里也跟着有点不安", 0.5)
    elif is_raining and "rain" in conditions:
        _add_subconscious(user_id, "外面在下雨，滴滴答答的声音听着有点安静", 0.3)

    # 应用心智修正
    if applied:
        try:
            from engine import mind as mind_module
            mind_module.adjust_mind_dimensions(user_id, applied, impact=0.003)
        except Exception:
            pass

    return applied


def _add_subconscious(user_id: str, content: str, intensity: float):
    """写一条环境触发的潜意识记录（失败静默）。"""
    try:
        from core import database as db
        db.add_subconscious(user_id=user_id,
                            content="[环境感知]%s" % content,
                            emotion_tag="环境触动",
                            intensity=intensity)
    except Exception:
        pass
