# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""真实语塞引擎 — Genuine Hesitation
===============================================
当认知冲突过大时，系统真正"处理不过来"——不是演的语塞，
而是多个矛盾声音、意外刺激、或自我怀疑导致的真实处理延迟。

三种语塞:
  a) 认知过载: contradiction_engine entropy > 0.85 → 多个声音打架
  b) 情感冲击: 对方消息与历史模式偏差过大 → 短暂"脑子空白"
  c) 被质疑: 自我认知受到挑战 → 需要时间消化

语塞不是 prompt 技巧——是通过 delivery 模块施加真实延迟。
"""
import random
import time
from typing import Dict, List, Optional, Tuple


def load_engine_config():
    pass


def detect_hesitation(
    mind_data: dict,
    comprehension: dict = None,
    contradiction_entropy: float = 0.5,
    message_text: str = "",
    message_history: List[str] = None,
) -> Tuple[bool, str, float]:
    """检测是否需要语塞。

    Returns:
        (should_hesitate, reason, extra_delay_seconds)
    """
    reasons = []
    extra_delay = 0.0

    if contradiction_entropy > 0.85:
        reasons.append("cognitive_overload")
        extra_delay += (contradiction_entropy - 0.85) * 60

    if comprehension:
        confidence = comprehension.get("confidence", 0.5)
        intent = comprehension.get("intent", "")
        emotion = comprehension.get("true_emotion", "")

        if intent == "试探" and emotion in ("怀疑", "不安") and confidence < 0.7:
            reasons.append("being_tested")
            extra_delay += random.uniform(3, 12)

        surface = comprehension.get("surface_emotion", "")
        if surface != emotion and abs(_emotion_distance(surface, emotion)) > 0.5:
            reasons.append("surface_true_mismatch")
            extra_delay += random.uniform(2, 8)

    if message_history and message_text:
        deviation = _compute_message_deviation(message_text, message_history)
        if deviation > 0.6:
            reasons.append("emotional_shock")
            extra_delay += deviation * random.uniform(5, 20)

    sensitivity = mind_data.get("sensitivity_paranoia", 0.15)
    if sensitivity > 0.55:
        restraint = mind_data.get("restraint", 0.5)
        if restraint > 0.5:
            reasons.append("overthinking")
            extra_delay += (sensitivity - 0.5) * random.uniform(3, 10)

    if reasons:
        reason_text = "+".join(reasons)
        extra_delay = min(30.0, max(1.0, extra_delay))
        return True, reason_text, round(extra_delay, 1)

    return False, "", 0.0


def inject_hesitation_markers(
    response: str,
    mind_data: dict,
    hesitation_reason: str = "",
) -> str:
    """在回复文本中注入语塞标记（非语言停顿）。
    只在确实需要时使用。
    """
    if not response or not response.strip():
        return response

    chaotic = mind_data.get("chaotic_mood", 0.2)
    restraint = mind_data.get("restraint", 0.5)

    markers = []

    if "cognitive_overload" in hesitation_reason or chaotic > 0.55:
        markers.append("嗯……")

    if "being_tested" in hesitation_reason or "overthinking" in hesitation_reason:
        if random.random() < 0.5:
            markers.append("怎么说呢……")

    if "emotional_shock" in hesitation_reason:
        markers.append("……")

    if not markers:
        return response

    marker = random.choice(markers)
    if marker == "……":
        return marker + response
    else:
        return marker + response


def _emotion_distance(e1: str, e2: str) -> float:
    valence = {
        "开心": 1.0, "兴奋": 1.0, "感动": 0.9, "温柔": 0.7, "平静": 0.3,
        "中性": 0.0, "无所谓": -0.2, "焦虑": -0.5, "难过": -0.7,
        "低落": -0.7, "生气": -0.8, "失望": -0.6,
    }
    return abs(valence.get(e1, 0) - valence.get(e2, 0))


def _compute_message_deviation(text: str, history: List[str]) -> float:
    if not history or len(history) < 3:
        return 0.0
    recent_lengths = [len(m) for m in history[-5:]]
    if not recent_lengths:
        return 0.0
    avg_len = sum(recent_lengths) / len(recent_lengths)
    if avg_len < 1:
        return 0.0
    current_len = len(text)
    deviation = abs(current_len - avg_len) / avg_len

    emotional_words = {"永远": 0.05, "从来": 0.05, "绝对": 0.05,
                       "讨厌": 0.08, "烦": 0.06, "爱": 0.04}
    extra = 0.0
    for word, weight in emotional_words.items():
        if word in text:
            in_history = sum(1 for m in history[-5:] if word in m)
            if in_history == 0:
                extra += weight

    return min(1.0, deviation * 0.7 + extra)
