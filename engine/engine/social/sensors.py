# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""环境感知引擎 — 外部上下文注入 + 天气→心智映射

设计原则：**引擎自己不上网**。

技能运行在 Agent（OpenClaw / CodeBuddy 等）之下，Agent 本身能联网、也掌握
对话里出现的位置信息。因此环境信息由调用方查好后注入：

    python3 scripts/soulctl.py chat --text "..." --env "上海 小雨 24°C"

好处：
  - 不需要任何天气 API Key
  - 不把用户 IP 发给第三方定位服务
  - 沙箱内同样可用（纯参数传递）
  - Agent 掌握对话上下文，比按 IP 猜城市更准

注入的文本会被：
  1) 原样作为【环境感知】注入推理 prompt（get_weather_context）
  2) 关键词推导出晴雨/温度，驱动 24 维心智修正（apply_weather_to_mind）
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


def _store(text, flags):
    """写入环境上下文与推导状态（内部）。"""
    global _external_context, _external_flags, _updated_at
    text = (text or "").strip()
    with _lock:
        _external_context = text
        _external_flags = dict(flags or {})
        _updated_at = time.time() if text else 0.0
    if text:
        safe_print("[Sensors] 已注入外部环境上下文: %s" % text)
    return bool(text)


def set_external_context(text: str) -> bool:
    """注入外部环境上下文（自由文本）。

    中英文都可以，例如「上海 小雨 24°C」或「Shanghai light rain 24C」：
      1) 原样作为【环境感知】注入推理 prompt；
      2) 关键词推导出天气状态，驱动 24 维心智修正。
    传空字符串等于清除。返回 True 表示成功注入。
    """
    text = (text or "").strip()
    return _store(text, _parse_env_flags(text) if text else {})


def set_external_context_json(data: dict) -> bool:
    """结构化注入环境上下文（推荐，比自由文本更稳）。

    支持字段（都可选，缺的会自动推导）：
      city / location              城市名
      description / weather        天气描述（中英文均可）
      temperature                  温度（摄氏；华氏请自行换算）
      weather_code                 WMO 天气码
      is_raining / is_snowing / is_extreme   直接指定状态

    返回 True 表示成功注入。
    """
    if not isinstance(data, dict) or not data:
        return False

    city = str(data.get("city") or data.get("location") or "").strip()
    desc = str(data.get("description") or data.get("weather")
               or data.get("desc") or "").strip()

    flags = {}
    code = data.get("weather_code")
    if code is not None:
        try:
            flags["weather_code"] = int(code)
        except (TypeError, ValueError):
            pass

    temp = data.get("temperature")
    if temp is not None:
        try:
            flags["temperature"] = float(temp)
        except (TypeError, ValueError):
            pass

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

    # 组装给 prompt 看的展示文本
    parts = [p for p in (city, desc) if p]
    if flags.get("temperature") is not None:
        parts.append("%g°C" % flags["temperature"])

    flags = {k: v for k, v in flags.items() if v is not None}
    return _store(" ".join(parts), flags)


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


def load_engine_config():
    """保留此接口以兼容启动流程。

    环境信息改由调用方注入，这里不再读取任何配置项，
    因此函数体为空。
    """
    return


def init():
    """初始化钩子（保留以兼容 SoulEngine 启动流程）。"""
    safe_print("[Sensors] 环境感知就绪：等待调用方通过 chat --env 注入"
               "（引擎不自行联网查天气）")


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
    """位置信息。引擎不再做 IP 定位，恒返回空字典（保留接口兼容）。"""
    return {}


def apply_weather_to_mind(user_id: str) -> dict:
    """天气影响 24 维心智，返回实际应用的修正量。

    数据来源是 set_external_context() 推导出的状态；未注入时返回空字典。
    """
    with _lock:
        flags = dict(_external_flags)

    if not flags:
        return {}

    temp = flags.get("temperature")
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
    if temp is not None and temp > 30:
        conditions.append("hot")
    if temp is not None and temp < 5:
        conditions.append("cold")

    # 多云/阴天
    if code in (2, 3):
        conditions.append("cloudy")

    # 晴天
    if code == 0 and not conditions:
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
