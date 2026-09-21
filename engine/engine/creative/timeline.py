# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""时间线感知引擎（融合 Chronos 精准时钟 + Sensors 天气感知）
让AI拥有完整的时间认知：星期、日期、季节、时段、节律、天气。
时间影响情绪、语气、话题选择；天气影响环境感知。
"""
from datetime import datetime


def load_engine_config():
    pass


def get_time_context() -> dict:
    """获取完整的时间上下文（优先使用 Chronos 精准时钟）。
    """
    try:
        from engine import chronos
        return chronos.get_time_context()
    except Exception:
        pass

    # 回退：使用系统时间
    return _fallback_time_context()


def _fallback_time_context() -> dict:
    """系统时间回退方案"""
    now = datetime.now()
    weekday_idx = now.weekday()
    _WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    _SEASONS = {
        3: ("初春", ""), 4: ("春天", ""), 5: ("春末", ""),
        6: ("初夏", ""), 7: ("盛夏", ""), 8: ("夏末", ""),
        9: ("初秋", ""), 10: ("秋天", ""), 11: ("深秋", ""),
        12: ("初冬", ""), 1: ("深冬", ""), 2: ("冬末", ""),
    }
    return {
        "now": now,
        "weekday_name": _WEEKDAY_CN[weekday_idx] if 0 <= weekday_idx < 7 else "未知",
        "weekday_idx": weekday_idx,
        "is_weekend": weekday_idx >= 5,
        "hour": now.hour,
        "period_name": "未知",
        "period_mood": "",
        "is_late_night": now.hour >= 22 or now.hour < 6,
        "month": now.month,
        "season_name": _SEASONS.get(now.month, ("未知", ""))[0],
        "season_desc": "",
        "time_str": now.strftime("%Y年%m月%d日 %H:%M"),
        "date_str": now.strftime("%Y-%m-%d"),
    }


def get_timeline_instruction(user_id: str = None) -> str:
    """生成时间线注入指令，融合天气感知。
    """
    ctx = get_time_context()
    lines = []

    # 1. 基本时间信息
    lines.append(
        f"现在是 {ctx['time_str']}，{ctx['weekday_name']}。"
    )

    # 2. 时段氛围
    if ctx["is_late_night"]:
        lines.append(
            f"{ctx['period_name']}了——{ctx['period_mood']}。"
            f"深夜对话通常更坦诚、更感性，语气可以更柔软一些。"
        )
    elif ctx["period_name"]:
        lines.append(
            f"此刻是{ctx['period_name']}，{ctx['period_mood']}。"
        )

    # 3. 周末 vs 工作日
    if ctx["is_weekend"]:
        lines.append(
            f"今天是{ctx['weekday_name']}，周末的自己更松弛、更随意。"
        )
    else:
        lines.append(
            f"今天是{ctx['weekday_name']}。"
        )

    # 4. 季节
    if ctx["season_desc"]:
        lines.append(
            f"现在是{ctx['season_name']}——{ctx['season_desc']}。"
        )

    # 5.  天气融合
    try:
        from engine import sensors
        weather_ctx = sensors.get_weather_context()
        if weather_ctx:
            # 移除"【环境感知】"前缀，直接融入时间线
            weather_text = weather_ctx.replace("【环境感知】\n", "")
            lines.append(weather_text)
    except Exception:
        pass

    return "【时间线感知】\n" + "\n".join(lines)


def get_time_based_mood_modifier() -> dict:
    """根据时间返回心情修正值（优先使用 Chronos 版本）。
    """
    try:
        from engine import chronos
        return chronos.get_time_based_mood_modifier()
    except Exception:
        pass

    # 回退方案
    ctx = get_time_context()
    modifiers = {}
    if ctx["is_weekend"]:
        modifiers["joy"] = 0.01
        modifiers["life_vitality"] = 0.01
        modifiers["restraint"] = -0.01
    if ctx["is_late_night"]:
        modifiers["chaotic_mood"] = 0.01
        modifiers["loneliness"] = 0.01
        modifiers["emptiness"] = 0.005
        modifiers["emotional_volatility"] = 0.01
    return modifiers
