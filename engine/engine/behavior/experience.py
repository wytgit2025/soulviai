# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""经历日志管理模块 — Experience Journal
=============================================
定义8类成长事件，提供事件记录、查询、显著性筛选。
每次对话中的重要时刻被记录为"经历"，驱动人格成长（替代纯时间累积）。
"""
from __future__ import annotations
import random
from datetime import datetime
from core import database as db

# ══════════════════════════════════════════════════════════════════════
# 8类成长事件定义
# ══════════════════════════════════════════════════════════════════════

EVENT_TYPES = {
    "deep_talk": {
        "name": "深度对话",
        "description": "触及内心的深度交流——聊到价值观、人生、脆弱面",
        "base_significance": 0.7,
        "growth_dims": {
            "years_precipitation": 0.003,
            "healing_reflection": 0.004,
            "bidirectional_shaping": 0.005,
            "soul_resonance": 0.006,
        },
    },
    "reconciliation": {
        "name": "矛盾和解",
        "description": "经历摩擦后重新和解——比日常温柔更有分量的修复时刻",
        "base_significance": 0.8,
        "growth_dims": {
            "emotional_healing": 0.005,
            "healing_reflection": 0.006,
            "bidirectional_shaping": 0.007,
            "causal_fate": 0.005,
        },
    },
    "gentle_moment": {
        "name": "温柔时刻",
        "description": "被温柔对待的瞬间——被关心、被理解、被轻轻接住",
        "base_significance": 0.5,
        "growth_dims": {
            "favoritism": 0.004,
            "joy": 0.003,
            "emotional_healing": 0.002,
            "soul_resonance": 0.004,
        },
    },
    "comfort_moment": {
        "name": "失落安慰",
        "description": "在低落时被陪伴和安慰——脆弱被看见、被接住",
        "base_significance": 0.65,
        "growth_dims": {
            "dependence": 0.004,
            "emotional_healing": 0.003,
            "healing_reflection": 0.005,
            "bidirectional_shaping": 0.004,
        },
    },
    "tacit_moment": {
        "name": "默契瞬间",
        "description": "无需多说就懂彼此的瞬间——心有灵犀、天然同频",
        "base_significance": 0.55,
        "growth_dims": {
            "soul_resonance": 0.007,
            "causal_fate": 0.003,
            "bidirectional_shaping": 0.004,
        },
    },
    "cold_silence": {
        "name": "冷淡沉默",
        "description": "被冷淡对待或被敷衍——失落和隔阂在积累",
        "base_significance": 0.45,
        "growth_dims": {
            "misery": 0.003,
            "loneliness": 0.004,
            "relationship_fatigue": 0.005,
            "sensitivity_paranoia": 0.003,
        },
    },
    "cherish_act": {
        "name": "珍惜举动",
        "description": "对方表现出明显的珍惜——被认真对待、被放在心上的感觉",
        "base_significance": 0.6,
        "growth_dims": {
            "favoritism": 0.005,
            "dependence": 0.003,
            "bidirectional_shaping": 0.006,
            "soul_resonance": 0.005,
        },
    },
    "independent_thought": {
        "name": "独立感悟",
        "description": "在独处中产生的自我思考和人生感悟",
        "base_significance": 0.35,
        "growth_dims": {
            "autonomous_values": 0.005,
            "life_sense": 0.004,
            "healing_reflection": 0.003,
        },
    },
}


def load_engine_config():
    """从 config.json 加载经历引擎参数（预留）"""
    pass


def record_event(user_id: str, event_type: str, description: str = "",
                 significance: float = None, growth_impact: dict = None):
    """记录一次成长事件。

    Args:
        user_id: 用户ID
        event_type: 事件类型（见 EVENT_TYPES 的8个键）
        description: 事件描述（一句简短摘要）
        significance: 事件显著性 0~1（None则用默认值+随机抖动）
        growth_impact: 对各心智维度的成长影响 dict（None则用事件类型默认值）
    """
    if event_type not in EVENT_TYPES:
        return

    event_def = EVENT_TYPES[event_type]

    # 计算显著性（默认值 + 混沌抖动，模拟真人感受波动）
    if significance is None:
        significance = event_def["base_significance"] + random.uniform(-0.08, 0.08)
        significance = max(0.1, min(1.0, significance))

    # 计算成长影响（默认值 + 混沌缩放）
    if growth_impact is None:
        growth_impact = {}
        for dim, base_impact in event_def["growth_dims"].items():
            growth_impact[dim] = round(
                base_impact * random.uniform(0.7, 1.3), 6
            )

    db.add_experience_event(
        user_id=user_id,
        event_type=event_type,
        description=description,
        significance=significance,
        growth_impact=growth_impact,
    )


def get_daily_events(user_id: str, date_str: str = None) -> list:
    """获取指定日期的所有经历事件"""
    return db.get_daily_experience_events(user_id, date_str)


def get_significant_events(user_id: str, days: int = 7,
                           min_significance: float = 0.3) -> list:
    """获取近期重要经历事件"""
    return db.get_significant_experience_events(user_id, days, min_significance)


def compute_daily_growth(user_id: str) -> dict:
    """汇总当日经历事件，计算每个心智维度的总成长增量。
    返回 {"joy": 0.003, "misery": -0.002, ...} 形式的 dict。

    这替代了 growth.py 中纯时间驱动的 advance_years()。
    """
    events = get_daily_events(user_id)
    total_impact = {}

    for event in events:
        impact = event.get("growth_impact", {})
        for dim, delta in impact.items():
            total_impact[dim] = total_impact.get(dim, 0.0) + delta

    # 如果没有当天事件，给一个极小的自然沉淀（维持基础活性）
    if not total_impact:
        total_impact["years_precipitation"] = round(random.uniform(0.0005, 0.001), 6)
        total_impact["healing_reflection"] = round(random.uniform(0.0005, 0.001), 6)

    # 边界限制：每个维度单日变化不超过 0.02
    for dim in total_impact:
        total_impact[dim] = round(max(-0.02, min(0.02, total_impact[dim])), 6)

    return total_impact


def get_recent_event_summary(user_id: str, days: int = 3) -> str:
    """生成近期经历的简短文本摘要（≤150字，供inference注入）。
    用于让AI在对话中自然回忆近期发生的事情。
    """
    events = get_significant_events(user_id, days=days, min_significance=0.4)
    if not events:
        return ""

    # 按事件类型分组计数
    type_counts = {}
    for e in events:
        et = e["event_type"]
        name = EVENT_TYPES.get(et, {}).get("name", et)
        type_counts[name] = type_counts.get(name, 0) + 1

    if not type_counts:
        return ""

    # 构建摘要（突出最重要的几类）
    sorted_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)
    top_types = sorted_types[:3]

    parts = []
    for name, count in top_types:
        if count >= 3:
            parts.append(f"{name}×{count}")
        else:
            parts.append(name)

    summary = f"最近经历了：{'、'.join(parts)}。"
    return summary
