# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""防御机制引擎 — Defense Mechanisms
============================================
弗洛伊德式自我防御机制：痛苦记忆被压低、否认情绪、投射归因、合理化回避。

四种机制:
  1. 压抑 (repression): sensitivity高时痛苦记忆被压低重要性
  2. 否认 (denial): misery极高时认知中出现"我没事"
  3. 投射 (projection): jealousy高时把"ta不在意我"归因给对方冷淡
  4. 合理化 (rationalization): restraint高时用逻辑解释情绪回避

作用方式:
  - 在理解层输出时自动渗透
  - 在记忆检索时过滤高情绪记忆
  - 在回复生成时注入防御性表达
"""
from typing import Dict, List, Optional


DEFENSE_MECHANISMS = {
    "repression": {
        "name": "压抑",
        "trigger": {"sensitivity_paranoia": 0.55},
        "effect": "将痛苦记忆在检索时降低权重，不让它浮现",
        "memory_filter_strength": 0.4,
    },
    "denial": {
        "name": "否认",
        "trigger": {"misery": 0.55},
        "effect": "认知中告诉自己'我没事'，但底层情绪仍在",
        "self_narrative": ["我没事", "没什么大不了的", "不重要"],
    },
    "projection": {
        "name": "投射",
        "trigger": {"jealousy": 0.35},
        "effect": "把自己'在意'的感觉投射为'ta对我冷淡'",
        "interpretation_bias": "ta好像不太在意我",
    },
    "rationalization": {
        "name": "合理化",
        "trigger": {"restraint": 0.6, "emotional_volatility": 0.45},
        "effect": "用理性解释掩盖真实情绪",
        "self_narrative": ["其实想想也没什么", "理性点看的话", "也不是什么大事"],
    },
}


def detect_active_defenses(mind_data: dict) -> List[Dict]:
    """检测当前被激活的防御机制"""
    active = []
    for def_key, def_info in DEFENSE_MECHANISMS.items():
        triggers = def_info.get("trigger", {})
        if not triggers:
            continue
        all_triggered = True
        activation = 0
        for dim, threshold in triggers.items():
            val = mind_data.get(dim, 0)
            if val < threshold:
                all_triggered = False
            else:
                activation += (val - threshold) / (1.0 - threshold) if threshold < 1.0 else 1.0
        if all_triggered:
            activation = min(1.0, activation / len(triggers))
            active.append({
                "key": def_key,
                "name": def_info["name"],
                "effect": def_info["effect"],
                "activation": round(activation, 3),
            })
    return active


def get_defense_narrative(mind_data: dict) -> str:
    """获取当前防御机制的自我叙事文本"""
    active = detect_active_defenses(mind_data)
    if not active:
        return ""

    narratives = []
    for d in active:
        mech = DEFENSE_MECHANISMS.get(d["key"], {})
        parts = mech.get("self_narrative", [])
        if parts:
            import random
            narratives.append(random.choice(parts))

    return "。".join(narratives) if narratives else ""


def get_memory_filter(user_id: str, mind_data: dict) -> Dict[str, float]:
    """获取记忆检索的防御性过滤参数。
    返回 {memory_level: suppression_factor}
    suppression_factor > 1.0 表示该层记忆被压低权重。
    """
    active = detect_active_defenses(mind_data)
    filter_map = {}

    for d in active:
        if d["key"] == "repression":
            factor = 1.0 + d["activation"] * 0.6
            filter_map[4] = factor
            filter_map[5] = factor * 1.2
            filter_map[6] = factor * 1.0

    return filter_map


def get_projection_bias(mind_data: dict) -> str:
    """获取投射偏误的描述文本（影响理解层）"""
    active = detect_active_defenses(mind_data)
    for d in active:
        if d["key"] == "projection" and d["activation"] > 0.3:
            return DEFENSE_MECHANISMS["projection"]["interpretation_bias"]
    return ""


def inject_defense_to_comprehension(comprehension: dict, mind_data: dict) -> dict:
    """将防御机制注入理解层"""
    bias = get_projection_bias(mind_data)
    if bias and comprehension.get("confidence", 0) > 0.5:
        comprehension["defense_bias"] = bias

    narrative = get_defense_narrative(mind_data)
    if narrative:
        comprehension["defense_narrative"] = narrative

    return comprehension
