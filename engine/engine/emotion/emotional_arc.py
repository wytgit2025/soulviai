# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""会话级情绪弧追踪
追踪本次会话中用户的情绪曲线变化，实现：
- 情绪惯性（不会瞬间切换）
- 情绪弧感知（知道用户今晚情绪经历了什么）
- 情绪高点/低点识别
"""
import time
from collections import deque

# ── 会话缓存 ──
_arc_cache = {}  # user_id → deque of {time, emotion, intensity}

# 情绪强度映射
_EMOTION_INTENSITY = {
    "开心": 0.8, "兴奋": 0.85, "激动": 0.9,
    "难过": -0.7, "生气": -0.8, "焦虑": -0.6,
    "低落": -0.7, "失望": -0.5, "无所谓": -0.2,
    "平静": 0.0, "中性": 0.1,
    "温柔": 0.6, "感动": 0.7,
}

_EMOTION_INERTIA = {}  # user_id → current_emotion_vector

# 情绪惯性权重（上一轮情绪对当前的影响比例）
_INERTIA_WEIGHT = 0.2


def load_engine_config():
    pass


def record_emotion(user_id: str, emotion: str, intensity: float = None):
    """记录一次情绪探测结果"""
    if user_id not in _arc_cache:
        _arc_cache[user_id] = deque(maxlen=30)

    # 计算情绪强度
    if intensity is None:
        intensity = _EMOTION_INTENSITY.get(emotion, 0.0)

    # 应用情绪惯性
    if user_id in _EMOTION_INERTIA:
        prev_emotion, prev_intensity = _EMOTION_INERTIA[user_id]
        # 如果当前情绪和上一轮完全不同，做平滑
        if abs(intensity - prev_intensity) > 0.5:
            intensity = intensity * (1 - _INERTIA_WEIGHT) + prev_intensity * _INERTIA_WEIGHT

    _EMOTION_INERTIA[user_id] = (emotion, intensity)

    _arc_cache[user_id].append({
        "time": time.time(),
        "emotion": emotion,
        "intensity": intensity,
    })


def get_emotional_arc(user_id: str) -> str:
    """获取会话级情绪弧描述文本。
    用于注入 System Prompt，让 AI 感知用户情绪趋势。
    """
    if user_id not in _arc_cache or len(_arc_cache[user_id]) < 2:
        return ""

    arc = list(_arc_cache[user_id])

    # 找情绪高点和低点
    high_idx = max(range(len(arc)), key=lambda i: arc[i]["intensity"])
    low_idx = min(range(len(arc)), key=lambda i: arc[i]["intensity"])

    # 分析趋势
    first_half = arc[:len(arc)//2] if len(arc) > 4 else arc[:1]
    second_half = arc[len(arc)//2:] if len(arc) > 4 else arc[1:]

    first_avg = sum(p["intensity"] for p in first_half) / len(first_half)
    second_avg = sum(p["intensity"] for p in second_half) / len(second_half)

    if second_avg - first_avg > 0.2:
        trend = "情绪在好转，比刚开始时状态好一些"
    elif first_avg - second_avg > 0.2:
        trend = "情绪在走低，比刚开始时更沉重了"
    elif abs(second_avg - first_avg) < 0.1 and first_avg > 0.5:
        trend = "情绪一直挺好的，氛围很暖"
    elif abs(second_avg - first_avg) < 0.1 and first_avg < -0.3:
        trend = "情绪一直挺低落的，需要多陪伴"
    else:
        trend = "情绪平稳波动"

    parts = [
        "【情绪弧感知】",
        f"本次会话情绪轨迹：{trend}。",
    ]

    high_emo = arc[high_idx]
    if high_emo["intensity"] > 0.5:
        parts.append(f"情绪高点出现在聊到开心/温暖的事情时。")

    low_emo = arc[low_idx]
    if low_emo["intensity"] < -0.3:
        parts.append(f"情绪低点出现在触及难过/焦虑的话题时。")

    # 当前情绪惯性提示
    if user_id in _EMOTION_INERTIA:
        curr_emo, curr_intensity = _EMOTION_INERTIA[user_id]
        if curr_intensity < -0.3:
            parts.append(f"当前情绪仍有惯性：比较低落，不要太快强行切换氛围。")
        elif curr_intensity > 0.5:
            parts.append(f"当前情绪仍有惯性：愉快中，可以保持轻快感。")

    return "\n".join(parts)


def get_should_ask_followup(user_id: str, comprehension: dict) -> bool:
    """判断是否应该主动追问用户。
    条件：
    1. 用户在倾诉（intent=倾诉 或 情绪深度=深度）
    2. 用户需要倾听而非建议
    3. 用户没有表现冷淡
    """
    intent = comprehension.get("intent", "")
    need = comprehension.get("what_they_need", "")
    depth = comprehension.get("depth", "")
    emotion = comprehension.get("true_emotion", "")

    # 倾诉场景下追问
    if intent == "倾诉" and need == "倾听" and depth == "深度":
        return True

    # 分享趣事时追问细节
    if intent == "分享" and emotion in ("开心", "兴奋"):
        return True

    return False


def get_emotion_inertia_text(user_id: str) -> str:
    """获取情绪惯性提示文本。
    用于注入推理层，防止情绪瞬切。
    """
    if user_id not in _EMOTION_INERTIA:
        return ""
    emotion, intensity = _EMOTION_INERTIA[user_id]
    if abs(intensity) < 0.3:
        return ""

    if intensity > 0.6:
        return "注意情绪惯性：你现在心情不错，不要太快切换到低落的语气。"
    elif intensity < -0.4:
        return "注意情绪惯性：你此刻心里还有一些沉重，不用勉强自己立刻开心起来。"
    return ""
