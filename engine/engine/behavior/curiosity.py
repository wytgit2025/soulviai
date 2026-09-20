# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""好奇心驱动引擎 — Curiosity Engine
==============================================
当系统在对话中遇到"不理解但很重要"的实体或概念时，
产生内部好奇张力，驱动系统主动搜索或向用户提问。

核心流程:
  对话中遇到陌生实体 → 计算好奇值 → 超过阈值 →
    选择: {联网搜索 / 向用户提问 / 存入待了解}

与 autonomous.py 的区别:
  autonomous → 情绪驱动的"忍不住想说话"
  curiosity  → 认知驱动的"我想知道这个"

设计原则:
  - 好奇值自然衰减（模拟注意力漂移）
  - 同实体不重复好奇（模拟"我记得我问过"）
  - 仅对白名单类型产生好奇（避免对所有生词好奇）
"""
import time
import random
import math
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

try:
    from core import ai as ai_module
except ImportError:
    ai_module = None

# 好奇值参数
_BASE_CURIOSITY = 0.15
_DECAY_PER_SEC = 0.00003
_EXPLORED_TTL = 86400
_MAX_CURIOSITY = 0.85

# 实体类型白名单 — 只对"值得了解"的类型产生好奇
CURIOSITY_WHITELIST = {
    "person": 1.0,
    "interest": 0.8,
    "place": 0.6,
    "feeling": 0.5,
    "event": 0.5,
    "object": 0.4,
    "concept": 0.3,
}

# 内部状态
_curiosity_state: Dict[str, Dict[str, float]] = {}
_explored_set: Dict[str, Dict[str, float]] = {}
_last_tick: Dict[str, float] = {}


def load_engine_config():
    global _curiosity_state, _explored_set
    _curiosity_state = {}
    _explored_set = {}


def on_unknown_entity(user_id: str, entity: str, entity_type: str = "concept",
                       context_importance: float = 0.5):
    """在对话中遇到不理解的实体时，积累好奇值。

    Args:
        user_id: 用户 ID
        entity: 实体名称（如"冰美式""三体""加班"）
        entity_type: 实体类型（person/interest/place/feeling/event/concept）
        context_importance: 上下文重要性 0~1（话题越重要，好奇越强）
    """
    # 已探索过的实体不再好奇
    explored = _explored_set.get(user_id, {})
    if entity in explored:
        return

    # 类型权重
    type_weight = CURIOSITY_WHITELIST.get(entity_type, 0.2)
    if type_weight < 0.3:
        return

    # 计算好奇值增量
    delta = _BASE_CURIOSITY * type_weight * context_importance * random.uniform(0.7, 1.3)

    if user_id not in _curiosity_state:
        _curiosity_state[user_id] = {}
    _curiosity_state[user_id][entity] = _curiosity_state[user_id].get(entity, 0) + delta
    _curiosity_state[user_id][entity] = min(_MAX_CURIOSITY, _curiosity_state[user_id][entity])


def tick_curiosity(user_id: str) -> Optional[Dict]:
    """后台 tick — 好奇值自然衰减 + 溢出触发探索行为。

    Returns:
        探索行为字典（如 {"action": "ask_user", ...}），或 None。
    """
    now = time.time()

    # 好奇值自然衰减（注意力漂移）
    state = _curiosity_state.get(user_id, {})
    if not state:
        return None

    # 衰减
    for entity in list(state.keys()):
        state[entity] *= math.exp(-_DECAY_PER_SEC * (now - _last_tick.get(user_id, now)))
        if state[entity] < 0.02:
            del state[entity]

    _last_tick[user_id] = now

    # 查找超过阈值的实体
    top = _get_top_curiosity(user_id, threshold=0.35)
    if not top:
        return None

    entity, curiosity_value = top[0]
    return _decide_action(user_id, entity, curiosity_value)


def get_top_curiosity(user_id: str, threshold: float = 0.3) -> List[Tuple[str, float]]:
    """获取超过好奇阈值的实体列表（降序）。"""
    return _get_top_curiosity(user_id, threshold)


def _get_top_curiosity(user_id: str, threshold: float) -> List[Tuple[str, float]]:
    state = _curiosity_state.get(user_id, {})
    sorted_items = sorted(
        [(e, v) for e, v in state.items() if v > threshold],
        key=lambda x: -x[1]
    )
    return sorted_items


def _decide_action(user_id: str, entity: str, curiosity_value: float) -> Optional[Dict]:
    """根据好奇值和当前场景，选择最佳满足方式。"""
    # 方式1: 如果可以搜索，用后台搜索（低成本）
    if _can_search():
        return {
            "action": "background_search",
            "entity": entity,
            "curiosity": curiosity_value,
            "query": entity,
        }

    # 方式2: 存入待了解（下次对话时自然提及）
    return {
        "action": "defer",
        "entity": entity,
        "curiosity": curiosity_value,
    }


def _can_search() -> bool:
    """检查当前是否可以进行联网搜索。"""
    try:
        from engine import search as search_module
        return hasattr(search_module, 'background_search') or hasattr(search_module, 'search_web')
    except Exception:
        return False


def mark_explored(user_id: str, entity: str):
    """标记一个实体已被探索（避免重复好奇）。"""
    if user_id not in _explored_set:
        _explored_set[user_id] = {}
    _explored_set[user_id][entity] = time.time()

    # 从好奇状态中移除
    state = _curiosity_state.get(user_id, {})
    if entity in state:
        del state[entity]


def get_curiosity_context(user_id: str, max_items: int = 3) -> str:
    """获取当前好奇实体列表（供 prompt 注入）。
    让 AI 知道"我有哪些事想弄明白"。
    """
    top = _get_top_curiosity(user_id, threshold=0.2)
    if not top:
        return ""

    lines = ["【心里有些问题还没弄明白】"]
    for entity, value in top[:max_items]:
        lines.append(f"· {entity}（好奇值{value:.2f}）")

    return "\n".join(lines)


def get_ask_user_curiosity(user_id: str) -> Optional[str]:
    """获取一个适合直接向用户提问的好奇内容。
    返回自然语言问句，或 None。
    """
    top = _get_top_curiosity(user_id, threshold=0.4)
    if not top:
        return None

    entity, value = top[0]

    PROMPTS = [
        f"说起来，你之前提到的{entity}——我有点好奇",
        f"我一直在想，你那个{entity}到底是怎么一回事",
        f"对了，你上次说的{entity}，能再多说一点吗",
        f"突然想到，你之前说的{entity}我还不太懂",
    ]

    return random.choice(PROMPTS)


def get_search_curiosity(user_id: str) -> Optional[str]:
    """获取一个值得后台搜索的好奇内容。
    返回搜索关键词，或 None。
    """
    top = _get_top_curiosity(user_id, threshold=0.5)
    if not top:
        return None
    entity, value = top[0]
    return entity
