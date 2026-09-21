# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""情绪传染引擎 — Emotional Contagion
=============================================
对方难过→你也真的开始低落（不只是理解，是感染）。
对方兴奋→你的愉悦感被带动。

这是心理学上极其真实的机制：共情不只是认知层面的"我知道你难过"，
而是情绪层面的"我也开始难过了"。

机制:
  1. 理解层检测到对方强烈情绪 → 计算传染强度
  2. 对方情绪 → 调整对应心智维度（微量但真实）
  3. 传染受 current mindset + bond_level 影响（越亲近越容易被感染）
"""
from engine import mind as mind_module
from engine import bond as bond_module


CONTAGION_MAP = {
    "开心": {"joy": 0.015, "life_vitality": 0.01},
    "兴奋": {"joy": 0.02, "chaotic_mood": 0.01, "life_vitality": 0.015},
    "难过": {"misery": 0.02, "joy": -0.005},
    "低落": {"misery": 0.015, "emptiness": 0.01},
    "焦虑": {"emotional_volatility": 0.015, "sensitivity_paranoia": 0.01},
    "生气": {"misery": 0.01, "emotional_volatility": 0.02, "restraint": -0.01},
    "温柔": {"joy": 0.01, "favoritism": 0.01, "emotional_healing": 0.005},
    "感动": {"joy": 0.015, "emotional_healing": 0.01, "soul_resonance": 0.005},
}


def compute_contagion(user_id: str, user_emotion: str,
                      confidence: float = 0.5) -> dict:
    """计算情绪传染效果。
    返回心智维度微调量（传给 mind.adjust_mind_dimensions）。
    """
    if user_emotion not in CONTAGION_MAP:
        return {}

    base = dict(CONTAGION_MAP[user_emotion])

    try:
        mind_data = mind_module.get_mind(user_id)
        bond_level = bond_module.compute_bond_level(mind_data)
    except Exception:
        mind_data = {}
        bond_level = 0.3

    empathy = mind_data.get("emotional_healing", 0.5)
    sensitivity = mind_data.get("sensitivity_paranoia", 0.35)

    contagion_multiplier = (
        confidence * 0.5 +
        empathy * 0.3 +
        bond_level * 0.2
    ) * (0.5 + sensitivity * 0.5)

    contagion_multiplier = min(2.0, max(0.1, contagion_multiplier))

    modulated = {}
    for dim, delta in base.items():
        modulated[dim] = round(delta * contagion_multiplier, 6)

    # 如果对方在难过且你很在意ta，额外加成
    if user_emotion in ("难过", "低落") and bond_level > 0.5:
        modulated["emotional_healing"] = round(
            modulated.get("emotional_healing", 0) + 0.01 * bond_level, 6
        )

    return modulated


def apply_contagion(user_id: str, comprehension: dict):
    """直接将情绪传染应用到心智维度"""
    emotion = comprehension.get("true_emotion", "")
    confidence = comprehension.get("confidence", 0.5)

    if not emotion or confidence < 0.3:
        return

    adjustments = compute_contagion(user_id, emotion, confidence)
    if adjustments:
        try:
            mind_module.adjust_mind_dimensions(user_id, adjustments, impact=0.5)
        except Exception:
            pass
