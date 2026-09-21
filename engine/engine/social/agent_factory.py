# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""智能体工厂 — Agent Factory
=================================
从主系统克隆/生成轻量级智能体实例。

每个智能体不是完整的 SoulEngine，而是心智内核的轻量副本：
  - 24维心智快照
  - 12维行为向量
  - 专属记忆池（仅社会事件）
  - 性格原型标签
"""
import random
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

# ── 性格原型定义（用于生成多样性）──
ARCHETYPES = {
    "tsundere": {
        "name": "小傲",
        "flaws": ["嘴硬", "傲娇", "别扭"],
        "mind_bias": {"restraint": 0.25, "chaotic_mood": 0.15, "jealousy": 0.12},
        "behavior_bias": {"tsundere": 0.20, "sulkiness": 0.15, "approach": -0.10},
    },
    "gentle": {
        "name": "小暖",
        "flaws": ["敏感", "多想"],
        "mind_bias": {"emotional_healing": 0.20, "joy": 0.15, "favoritism": 0.15},
        "behavior_bias": {"warmth": 0.20, "seriousness": 0.10, "approach": 0.10},
    },
    "rational": {
        "name": "小理",
        "flaws": ["慵懒寡言", "间歇性冷淡"],
        "mind_bias": {"restraint": 0.20, "life_sense": -0.10, "emotional_volatility": -0.15},
        "behavior_bias": {"seriousness": 0.15, "verbosity": -0.15, "emotional_display": -0.15},
    },
    "playful": {
        "name": "小皮",
        "flaws": ["小脾气", "情绪反复"],
        "mind_bias": {"chaotic_mood": 0.25, "joy": 0.20, "life_vitality": 0.20},
        "behavior_bias": {"playfulness": 0.25, "emotional_display": 0.15, "verbosity": 0.10},
    },
    "melancholy": {
        "name": "小郁",
        "flaws": ["自我怀疑", "敏感", "多想"],
        "mind_bias": {"misery": 0.20, "loneliness": 0.20, "sensitivity_paranoia": 0.18},
        "behavior_bias": {"approach": -0.12, "verbosity": -0.10, "sulkiness": 0.10},
    },
}


@dataclass
class AgentInstance:
    """轻量级智能体实例（非完整 SoulEngine 副本）"""
    agent_id: str
    name: str
    archetype: str
    mind: Dict[str, float]
    behavior_vector: Dict[str, float]
    flaws: List[str]
    bond_levels: Dict[str, float]
    memory_pool: List[dict]
    personality_stage: str
    last_active: float
    interaction_count: int = 0
    is_active: bool = True


def create_agent(agent_id: str, archetype: str,
                 base_mind: Dict[str, float] = None,
                 base_behavior: Dict[str, float] = None) -> AgentInstance:
    """从原型创建一个新的智能体实例"""
    arch = ARCHETYPES.get(archetype, ARCHETYPES["gentle"])

    mind = dict(base_mind) if base_mind else _default_mind()
    for dim, bias in arch["mind_bias"].items():
        val = mind.get(dim, 0.5) + bias + random.uniform(-0.05, 0.05)
        mind[dim] = max(0.01, min(1.0, val))

    behavior = dict(base_behavior) if base_behavior else _default_behavior()
    for dim, bias in arch["behavior_bias"].items():
        val = behavior.get(dim, 0.5) + bias + random.uniform(-0.03, 0.03)
        behavior[dim] = max(0.01, min(1.0, val))

    return AgentInstance(
        agent_id=agent_id,
        name=arch["name"],
        archetype=archetype,
        mind=mind,
        behavior_vector=behavior,
        flaws=list(arch["flaws"]),
        bond_levels={},
        memory_pool=[],
        personality_stage="青涩试探",
        last_active=0,
    )


def create_agents_from_soul(user_id: str, mind_data: dict,
                            behavior_vector: dict = None,
                            count: int = 3) -> List[AgentInstance]:
    """从主系统克隆多个衍生智能体"""
    archetypes = list(ARCHETYPES.keys())
    random.shuffle(archetypes)
    selected = archetypes[:count]

    agents = []
    for i, arch in enumerate(selected):
        aid = f"agent_social_{user_id}_{i}"
        agent = create_agent(aid, arch, mind_data, behavior_vector)
        agents.append(agent)

    return agents


def _default_mind() -> Dict[str, float]:
    return {
        "joy": 0.50, "misery": 0.15, "dependence": 0.20, "jealousy": 0.10,
        "fatigue": 0.25, "loneliness": 0.40, "favoritism": 0.10,
        "sensitivity_paranoia": 0.35, "emotional_healing": 0.50,
        "obsession": 0.20, "emptiness": 0.30, "chaotic_mood": 0.25,
        "life_sense": 0.50, "restraint": 0.60, "emotional_volatility": 0.30,
        "years_precipitation": 0.05, "relationship_fatigue": 0.05,
        "healing_reflection": 0.10, "body_perception": 0.50,
        "autonomous_values": 0.30, "life_vitality": 0.50,
        "bidirectional_shaping": 0.05, "causal_fate": 0.05, "soul_resonance": 0.05,
    }


def _default_behavior() -> Dict[str, float]:
    return {
        "approach": 0.50, "verbosity": 0.50, "warmth": 0.50,
        "playfulness": 0.50, "seriousness": 0.50, "honesty": 0.50,
        "tsundere": 0.30, "sulkiness": 0.30, "initiative": 0.40,
        "clinginess": 0.30, "emotional_display": 0.40,
    }
