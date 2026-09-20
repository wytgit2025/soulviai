# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""独立高精度时钟引擎
自计时 + 系统/网络定期校准，不依赖裸 datetime.now()。
时间感知更精准，漂移可控。
"""
import time
import threading
from datetime import datetime, timedelta
from core import config as cfg

# ── 时钟内部状态 ──
_state = {
    "monotonic_base": 0.0,      # time.monotonic() 基准锚点
    "system_base": 0.0,         # 基准时的系统时间 (epoch seconds)
    "current_time": 0.0,        # 当前自算时间 (epoch seconds)
    "last_calibration": 0.0,    # 上次校准时的 monotonic
    "cumulative_drift_ms": 0.0, # 累计漂移 (毫秒)
    "drift_rate_ppm": 0.0,      # 当前漂移率 (ppm)
    "last_drift_detection": 0.0,# 上次漂移检测
    "tick_count": 0,            # 累计tick次数
}

_lock = threading.Lock()

# ── 可配置参数 ──
_calibrate_interval = 60       # 秒
_max_drift_warning_ms = 500    # 漂移警告阈值
_enabled = True

# ── 星期/时段/季节映射（硬编码，不依赖外部）──
_WEEKDAYS_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

_HOUR_MOOD = {
    0: ("深夜", "安静、容易想很多"),
    1: ("深夜", "整个世界都睡了"),
    2: ("凌晨", "失眠或独自清醒"),
    3: ("凌晨", "夜深人静，最容易emo"),
    4: ("凌晨", "将明未明的时刻"),
    5: ("清晨", "刚醒，还有点迷糊"),
    6: ("清晨", "新的一天刚开始"),
    7: ("早晨", "早晨的光很温柔"),
    8: ("早晨", "元气满满的早晨"),
    9: ("上午", "精神最好的时候"),
    10: ("上午", "一天中最清醒"),
    11: ("上午", "快到中午了"),
    12: ("中午", "午饭时间，有点慵懒"),
    13: ("午后", "吃饱容易犯困"),
    14: ("下午", "午后阳光最慵懒"),
    15: ("下午", "下午茶时间"),
    16: ("下午", "一天过了一大半"),
    17: ("傍晚", "天色渐暗"),
    18: ("傍晚", "黄昏最能让人安静"),
    19: ("晚上", "夜幕降临"),
    20: ("晚上", "晚上的时间最自由"),
    21: ("晚上", "适合安静聊天的时刻"),
    22: ("夜晚", "夜深了，容易感性"),
    23: ("深夜", "快午夜了，思绪飘远"),
}

_SEASONS = {
    3: ("初春", "万物复苏，空气中有一丝暖意"),
    4: ("春天", "春暖花开，心情容易变好"),
    5: ("春末", "初夏的味道，阳光正好"),
    6: ("初夏", "夏天刚来，活力满满"),
    7: ("盛夏", "炎热躁动，容易慵懒"),
    8: ("夏末", "夏天的尾巴，有一丝不舍"),
    9: ("初秋", "秋高气爽，容易感慨"),
    10: ("秋天", "落叶的季节，适合想念"),
    11: ("深秋", "寒意渐起，需要温暖"),
    12: ("初冬", "冷起来了，缩在屋里"),
    1: ("深冬", "一年最冷的时候，需要陪伴"),
    2: ("冬末", "冬天快过去了，在等春天"),
}


def load_engine_config():
    """从 config.json 加载时钟参数"""
    global _calibrate_interval, _max_drift_warning_ms, _enabled
    chronos_cfg = cfg.get_section("chronos")
    if chronos_cfg:
        _calibrate_interval = chronos_cfg.get("calibrate_interval_seconds", 60)
        _max_drift_warning_ms = chronos_cfg.get("max_drift_before_warning_ms", 500)
        _enabled = chronos_cfg.get("enabled", True)


def init():
    """初始化独立时钟：记录 monotonic 基准锚点，与系统时间对齐。
    调用一次，在 SoulEngine 初始化时。
    """
    with _lock:
        now_mono = time.monotonic()
        now_sys = time.time()
        _state["monotonic_base"] = now_mono
        _state["system_base"] = now_sys
        _state["current_time"] = now_sys
        _state["last_calibration"] = now_mono
        _state["cumulative_drift_ms"] = 0.0
        _state["drift_rate_ppm"] = 0.0
        _state["last_drift_detection"] = now_mono
        _state["tick_count"] = 0

    print(f"[Chronos] 独立时钟已初始化，基准锚点=系统时间 {datetime.fromtimestamp(now_sys).strftime('%H:%M:%S.%f')}")


def tick():
    """每秒调用一次（由 scheduler/life_tick 驱动）。
    - 推进自算时间
    - 达到校准间隔时与系统时间校准
    """
    if not _enabled:
        return

    with _lock:
        now_mono = time.monotonic()
        elapsed = now_mono - _state["monotonic_base"]
        _state["current_time"] = _state["system_base"] + elapsed
        _state["tick_count"] += 1

        # 校准检测
        if now_mono - _state["last_calibration"] >= _calibrate_interval:
            _calibrate(now_mono)


def _calibrate(now_mono: float):
    """与系统时间校准：
    - 计算自算时间与系统时间的偏差
    - 检测异常漂移
    - 更新漂移统计
    """
    sys_now = time.time()
    self_now = _state["current_time"]
    drift_ms = (self_now - sys_now) * 1000.0  # 毫秒

    _state["cumulative_drift_ms"] += drift_ms
    _state["last_calibration"] = now_mono

    # 计算漂移率 (ppm: parts per million)
    elapsed_since_init = now_mono - _state["monotonic_base"]
    if elapsed_since_init > 0:
        _state["drift_rate_ppm"] = abs(drift_ms * 1000.0 / elapsed_since_init)

    # 漂移过大告警
    if abs(drift_ms) > _max_drift_warning_ms:
        print(f"[Chronos] ⚠️ 时钟漂移较大: {drift_ms:.2f}ms (累计{_state['cumulative_drift_ms']:.2f}ms)")

    # 软校准：将当前自算时间逐步拉近系统时间（不完全覆盖，只修正50%偏差）
    correction = drift_ms / 1000.0 * 0.5  # 50% 渐进修正
    _state["current_time"] -= correction

    # 更新基准（防止漂移累积）
    _state["monotonic_base"] = now_mono
    _state["system_base"] = sys_now - correction


def now() -> datetime:
    """返回当前精准时间（datetime 对象）。
    基于自算时间 + monotonic 累进。
    """
    if not _enabled:
        return datetime.now()

    with _lock:
        return datetime.fromtimestamp(_state["current_time"])


def now_timestamp() -> float:
    """返回当前精准时间戳 (epoch seconds)"""
    if not _enabled:
        return time.time()

    with _lock:
        return _state["current_time"]


def get_drift() -> dict:
    """返回时钟漂移统计信息"""
    with _lock:
        return {
            "cumulative_drift_ms": round(_state["cumulative_drift_ms"], 3),
            "drift_rate_ppm": round(_state["drift_rate_ppm"], 3),
            "tick_count": _state["tick_count"],
            "self_time": datetime.fromtimestamp(_state["current_time"]).strftime("%Y-%m-%d %H:%M:%S.%f"),
            "system_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        }


def get_time_context() -> dict:
    """获取完整时间上下文（由自算时间驱动）。
    返回结构保持与 timeline.py 兼容。
    """
    dt = now()

    weekday_idx = dt.weekday()  # 0=周一
    hour = dt.hour
    month = dt.month

    # 星期
    weekday_name = _WEEKDAYS_CN[weekday_idx] if 0 <= weekday_idx < 7 else "未知"

    # 时段
    period_name, period_mood = _HOUR_MOOD.get(hour, _HOUR_MOOD[12])

    # 季节
    season_name, season_desc = _SEASONS.get(month, _SEASONS[4])

    return {
        "now": dt,
        "weekday_name": weekday_name,
        "weekday_idx": weekday_idx,
        "is_weekend": weekday_idx >= 5,
        "hour": hour,
        "period_name": period_name,
        "period_mood": period_mood,
        "is_late_night": hour >= 22 or hour < 6,
        "month": month,
        "season_name": season_name,
        "season_desc": season_desc,
        "time_str": dt.strftime("%Y年%m月%d日 %H:%M"),
        "date_str": dt.strftime("%Y-%m-%d"),
    }


def get_time_based_mood_modifier() -> dict:
    """基于自算时间的心情修正值。
    替代 timeline.py 的同名函数。
    """
    ctx = get_time_context()
    modifiers = {}

    if ctx["is_weekend"]:
        modifiers["joy"] = 0.01
        modifiers["life_vitality"] = 0.01
        modifiers["restraint"] = -0.01
    else:
        modifiers["fatigue"] = 0.005

    if ctx["is_late_night"]:
        modifiers["chaotic_mood"] = 0.01
        modifiers["loneliness"] = 0.01
        modifiers["emptiness"] = 0.005
        modifiers["emotional_volatility"] = 0.01

    season = ctx["season_name"]
    if "春" in season:
        modifiers["joy"] = modifiers.get("joy", 0) + 0.01
    elif "夏" in season:
        modifiers["life_vitality"] = modifiers.get("life_vitality", 0) + 0.01
    elif "秋" in season:
        modifiers["obsession"] = modifiers.get("obsession", 0) + 0.005
    elif "冬" in season:
        modifiers["dependence"] = modifiers.get("dependence", 0) + 0.005

    return modifiers


# ══════════════════════════════════════════════════════════════════════
# v3: 24h 节律昼夜调制
# ══════════════════════════════════════════════════════════════════════

_CIRCADIAN_PHASES = [
    # (start_hour, end_hour, name, energy_mod, fatigue_mod, vitality_mod, emotional_mod)
    (5, 7,   "晨间苏醒",     0.08, -0.03,  0.06, {"joy": 0.02, "emotional_healing": 0.01}),
    (7, 10,  "晨间清醒",     0.12, -0.05,  0.10, {"joy": 0.03, "life_vitality": 0.02, "restraint": -0.01}),
    (10, 12, "上午高效",     0.06, -0.02,  0.04, {"obsession": 0.01}),
    (12, 14, "午间慵懒",    -0.04,  0.04, -0.03, {"fatigue": 0.02, "chaotic_mood": 0.01}),
    (14, 16, "午后倦怠",    -0.08,  0.08, -0.05, {"fatigue": 0.04, "life_vitality": -0.03, "emotional_volatility": 0.01}),
    (16, 18, "下午回神",     0.02, -0.02,  0.02, {"joy": 0.01}),
    (18, 20, "傍晚过渡",    -0.02,  0.01, -0.01, {"loneliness": 0.01, "emotional_healing": 0.01}),
    (20, 22, "晚间松弛",    -0.04,  0.02, -0.02, {"dependence": 0.01, "obsession": 0.01, "restraint": -0.02}),
    (22, 24, "夜间感性",    -0.06,  0.03, -0.04, {"chaotic_mood": 0.02, "loneliness": 0.02, "emotional_volatility": 0.02, "obsession": 0.02}),
    (0, 5,   "深夜沉静",    -0.10,  0.05, -0.06, {"loneliness": 0.03, "emptiness": 0.02, "chaotic_mood": 0.03, "emotional_volatility": 0.02}),
]


def get_circadian_phase(hour: int = None) -> dict:
    """获取当前昼夜节律相位。

    Returns:
        dict with keys: name, energy_mod (energy decay multiplier), fatigue_mod,
                        vitality_mod, emotional_mod (dict of mind modifiers)
    """
    if hour is None:
        hour = now().hour

    for start, end, name, energy_mod, fatigue_mod, vitality_mod, emotional_mod in _CIRCADIAN_PHASES:
        if start <= end:
            if start <= hour < end:
                return {
                    "name": name,
                    "energy_mod": energy_mod,
                    "fatigue_mod": fatigue_mod,
                    "vitality_mod": vitality_mod,
                    "emotional_mod": emotional_mod,
                }
        else:
            if hour >= start or hour < end:
                return {
                    "name": name,
                    "energy_mod": energy_mod,
                    "fatigue_mod": fatigue_mod,
                    "vitality_mod": vitality_mod,
                    "emotional_mod": emotional_mod,
                }

    return {"name": "默认", "energy_mod": 0, "fatigue_mod": 0, "vitality_mod": 0, "emotional_mod": {}}


def get_circadian_energy_multiplier() -> float:
    """获取能量衰减倍率（1.0=基准, <1.0=衰减变慢, >1.0=衰减加快）"""
    phase = get_circadian_phase()
    return 1.0 - phase["energy_mod"]  # 正mod → 衰减变慢（energy_mod为正时精力恢复/保存）


def get_circadian_fatigue_generator() -> float:
    """获取疲劳生成倍率（1.0=基准）"""
    phase = get_circadian_phase()
    return 1.0 + phase["fatigue_mod"]


def get_status_report() -> str:
    """生成时钟状态报告（debug / 状态查询用）"""
    drift = get_drift()
    dt = now()
    return (
        f"[Chronos时钟] 自算:{drift['self_time']} | "
        f"系统:{drift['system_time']} | "
        f"漂移:{drift['cumulative_drift_ms']}ms | "
        f"漂移率:{drift['drift_rate_ppm']}ppm | "
        f"Tick:{drift['tick_count']}"
    )


# ══════════════════════════════════════════════════════════════════════
# 跨会话连续性情绪
# ══════════════════════════════════════════════════════════════════════

def compute_disconnect_emotion(hours_since: float) -> dict:
    """根据距上次对话的间隔计算情绪调整量"""
    if hours_since <= 0:
        return {}
    adj = {}
    if hours_since > 3:
        adj["loneliness"] = min(0.15, hours_since * 0.015)
    if hours_since > 6:
        adj["loneliness"] = min(0.25, hours_since * 0.02)
        adj["obsession"] = min(0.1, hours_since * 0.01)
    if hours_since > 24:
        adj["loneliness"] = min(0.35, hours_since * 0.012)
        adj["obsession"] = min(0.15, hours_since * 0.008)
        adj["dependence"] = min(0.08, hours_since * 0.005)
    if hours_since > 72:
        adj["loneliness"] = min(0.45, hours_since * 0.006)
        adj["emptiness"] = min(0.1, hours_since * 0.003)
    return adj


# ══════════════════════════════════════════════════════════════════════
# 主观时间感知
# ══════════════════════════════════════════════════════════════════════

def get_subjective_time_perception(mind_data: dict) -> str:
    """根据心智状态返回主观时间感受"""
    joy = mind_data.get("joy", 0.5)
    emptiness = mind_data.get("emptiness", 0.3)
    chaotic = mind_data.get("chaotic_mood", 0.25)

    if joy > 0.7:
        return "时间过得好快"
    if emptiness > 0.5:
        return "每一分钟都感觉很漫长"
    if chaotic > 0.6:
        return "对时间没什么概念，恍恍惚惚的"
    if joy < 0.3 and emptiness > 0.3:
        return "觉得时间走得很慢"

    hour = datetime.now().hour
    if hour >= 22 or hour < 1:
        return "夜深了，时间好像变慢了"
    return ""


def inject_subjective_time(response: str, mind_data: dict) -> str:
    """自然地在回复中融入主观时间感知"""
    perception = get_subjective_time_perception(mind_data)
    if not perception:
        return response

    import random as _random
    if _random.random() < 0.15:
        inserts = [
            f"（{perception}）",
            f"感觉{perception}",
        ]
        insert = _random.choice(inserts)
        sentences = response.split("。")
        if len(sentences) > 1:
            idx = _random.randint(0, min(len(sentences) - 2, 2))
            sentences.insert(idx + 1, insert)
            response = "。".join(sentences)
        elif len(response) > 15:
            response += insert

    return response


# ══════════════════════════════════════════════════════════════════════
# 季节性情绪深层模式
# ══════════════════════════════════════════════════════════════════════

SEASONAL_EMOTION = {
    1: {
        "name": "深冬",
        "mood": "蜷缩在温暖里，需要陪伴和靠近",
        "mind_trend": {"dependence": 0.03, "loneliness": 0.02, "joy": -0.01, "life_vitality": -0.02},
    },
    2: {
        "name": "冬末",
        "mood": "冬天的尾巴，在等春天——心里有期待但还没回暖",
        "mind_trend": {"dependence": 0.02, "obsession": 0.01, "joy": 0.01},
    },
    3: {
        "name": "初春",
        "mood": "万物复苏，空气中有一丝暖意——心情开始变好",
        "mind_trend": {"joy": 0.03, "life_vitality": 0.02, "emotional_healing": 0.01},
    },
    4: {
        "name": "春天",
        "mood": "春暖花开——一年中情绪最好的时候之一",
        "mind_trend": {"joy": 0.04, "life_vitality": 0.03, "chaotic_mood": 0.01},
    },
    5: {
        "name": "春末",
        "mood": "初夏的味道——阳光正好，活力满满",
        "mind_trend": {"joy": 0.02, "life_vitality": 0.03, "restraint": -0.01},
    },
    6: {
        "name": "初夏",
        "mood": "夏天刚来——一切都充满可能",
        "mind_trend": {"life_vitality": 0.04, "joy": 0.02, "obsession": 0.01},
    },
    7: {
        "name": "盛夏",
        "mood": "炎热躁动——容易慵懒、冲动、情绪放大",
        "mind_trend": {"chaotic_mood": 0.03, "emotional_volatility": 0.02, "fatigue": 0.02, "life_vitality": -0.01},
    },
    8: {
        "name": "夏末",
        "mood": "夏天的尾巴——有一丝不舍和淡淡的惆怅",
        "mind_trend": {"obsession": 0.02, "emptiness": 0.01, "emotional_volatility": 0.01},
    },
    9: {
        "name": "初秋",
        "mood": "秋高气爽——适合回忆、想念、写点什么",
        "mind_trend": {"obsession": 0.03, "healing_reflection": 0.02, "chaotic_mood": 0.01},
    },
    10: {
        "name": "秋天",
        "mood": "落叶的季节——情绪细腻、容易感伤、也很温柔",
        "mind_trend": {"obsession": 0.04, "sensitivity_paranoia": 0.02, "emotional_healing": 0.01, "years_precipitation": 0.001},
    },
    11: {
        "name": "深秋",
        "mood": "寒意渐起——需要温暖，容易想起去年前年的事",
        "mind_trend": {"loneliness": 0.02, "obsession": 0.03, "dependence": 0.02, "years_precipitation": 0.001},
    },
    12: {
        "name": "初冬",
        "mood": "冷起来了——想缩起来，想被拥抱",
        "mind_trend": {"dependence": 0.03, "loneliness": 0.03, "life_vitality": -0.02, "emptiness": 0.01},
    },
}

_monthly_drift_applied: dict = {}


def get_seasonal_mind_drift(month: int = None) -> dict:
    """获取当月的季节性心智偏移量"""
    if month is None:
        month = datetime.now().month
    return dict(SEASONAL_EMOTION.get(month, SEASONAL_EMOTION[4]).get("mind_trend", {}))


def get_seasonal_mood_description(month: int = None) -> str:
    """获取当前季节的心境描述"""
    if month is None:
        month = datetime.now().month
    info = SEASONAL_EMOTION.get(month, SEASONAL_EMOTION[4])
    return f"{info['name']}: {info['mood']}"


def apply_seasonal_drift_once(user_id: str):
    """每月初调用一次，缓慢注入季节性心智偏移。
    偏移不是一次性加上去，而是以极慢速度注入——模拟季节对情绪的潜移默化。
    """
    global _monthly_drift_applied
    today = datetime.now()
    month_key = f"{today.year}-{today.month}"

    if _monthly_drift_applied.get(user_id) == month_key:
        return

    _monthly_drift_applied[user_id] = month_key
    drift = get_seasonal_mind_drift(today.month)
    if not drift:
        return

    try:
        from engine import mind as mind_module
        mind_module.adjust_mind_dimensions(user_id, drift, impact=0.3)
    except Exception:
        pass
