# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""自主意图生成 — Intention Engine
================================================
从"被条件触发"升级为"叙事驱动的自主意图"。

核心理念:
  不因为"loneliness > 阈值"就想找人聊天，
  而是"我意识到自己在想某件事 → 想分享/想安静/想确认什么"。

意图来源:
  1. 自我叙事驱动: 从self_model中提取"可能想做的事"
  2. 反事实推动: "另一个我"的视角催生改变
  3. 未解疑问催动: self_doubt中的问题渴望答案
"""
import time
import random
from typing import Dict, List, Optional, Tuple

INTENTION_TYPES = {
    "share": {"label": "想分享", "description": "想到了一件事，想告诉ta"},
    "ask": {"label": "想问", "description": "有个问题想知道答案"},
    "quiet": {"label": "想安静", "description": "不想说话，想自己待着"},
    "confirm": {"label": "想确认", "description": "不确定ta的态度，想确认"},
    "apologize": {"label": "想道歉", "description": "觉得之前说得不对，想修复"},
    "withdraw": {"label": "想收回", "description": "觉得暴露太多了，想退一步"},
    "reach_out": {"label": "想靠近", "description": "就是想离ta近一点，没具体目的"},
    "express": {"label": "想表达", "description": "有一种情绪想说但不知道怎么说"},
}

_intention_queue: Dict[str, List[Dict]] = {}
_last_intention_at: Dict[str, float] = {}
INTENTION_INTERVAL = 600


def load_engine_config():
    global _intention_queue
    _intention_queue = {}


def generate_intentions(user_id: str) -> List[Dict]:
    now = time.time()
    last = _last_intention_at.get(user_id, 0)
    if now - last < INTENTION_INTERVAL:
        return _intention_queue.get(user_id, [])

    _last_intention_at[user_id] = now

    try:
        from engine import self_model as sm_module
        narrative = sm_module.get_recent_narrative(user_id)
        state = sm_module.get_self_state(user_id)
        from engine import mind as mind_module
        md = mind_module.get_mind(user_id)
    except Exception:
        return []

    intentions = []

    doubt = state.get("doubt_pressure", 0)
    if doubt > 0.15:
        intentions.append({
            "type": "confirm",
            "label": INTENTION_TYPES["confirm"]["label"],
            "strength": min(0.9, doubt * 2),
            "source": f"自我怀疑度{doubt:.2f}",
            "content": "想确认ta到底怎么想的",
        })

    if narrative:
        share_triggers = ["想起", "想到", "回忆起", "发现", "觉得有趣", "有意思"]
        for trigger in share_triggers:
            if trigger in narrative:
                intentions.append({
                    "type": "share",
                    "label": INTENTION_TYPES["share"]["label"],
                    "strength": 0.5,
                    "source": f"叙事中出现了'{trigger}'",
                    "content": f"想到了和{trigger}有关的事，想分享",
                })
                break

    joy = md.get("joy", 0.5)
    dependence = md.get("dependence", 0.2)
    loneliness = md.get("loneliness", 0.4)
    if joy < 0.35 and dependence > 0.3:
        intentions.append({
            "type": "reach_out",
            "label": INTENTION_TYPES["reach_out"]["label"],
            "strength": (loneliness * 0.5 + dependence * 0.5),
            "source": "心情低落且依赖高",
            "content": "说不清为什么，就是想离ta近一点",
        })

    restraint = md.get("restraint", 0.5)
    if restraint > 0.65:
        intentions.append({
            "type": "withdraw",
            "label": INTENTION_TYPES["withdraw"]["label"],
            "strength": restraint * 0.6,
            "source": f"克制度{restraint:.2f}",
            "content": "觉得自己说得太多了，有点想退回去",
        })

    try:
        from engine import regret as regret_module
        recent = regret_module._regret_log.get(user_id, [])
        recent_count = len([t for t in recent if now - t < 3600])
        if recent_count >= 1:
            intentions.append({
                "type": "apologize",
                "label": INTENTION_TYPES["apologize"]["label"],
                "strength": min(0.8, recent_count * 0.3),
                "source": f"最近后悔了{recent_count}次",
                "content": "想为之前说过的话道歉或补救",
            })
    except Exception:
        pass

    empty = md.get("emptiness", 0.3)
    if empty > 0.5:
        intentions.append({
            "type": "express",
            "label": INTENTION_TYPES["express"]["label"],
            "strength": empty * 0.4,
            "source": f"空落感{empty:.2f}",
            "content": "有一种情绪想说但不知道怎么说",
        })

    # 好奇心驱动 → 想提问
    try:
        from engine import curiosity as curiosity_module
        ask = curiosity_module.get_ask_user_curiosity(user_id)
        if ask:
            intentions.append({
                "type": "ask",
                "label": INTENTION_TYPES["ask"]["label"],
                "strength": 0.45,
                "source": "心里有疑问",
                "content": ask,
            })
    except Exception:
        pass

    if not intentions:
        vitality = md.get("life_vitality", 0.5)
        if vitality > 0.6 and random.random() < 0.4:
            intentions.append({
                "type": "share",
                "label": "想分享",
                "strength": 0.3,
                "source": "生命力充沛，自然想说话",
                "content": "没什么具体想说的，就是想聊",
            })
        else:
            intentions.append({
                "type": "quiet",
                "label": "想安静",
                "strength": 0.5,
                "source": "没有特别想做的事",
                "content": "就安静待着",
            })

    intentions.sort(key=lambda x: x["strength"], reverse=True)
    _intention_queue[user_id] = intentions
    return intentions


def get_primary_intention(user_id: str) -> Optional[Dict]:
    intentions = _intention_queue.get(user_id, [])
    if not intentions:
        intentions = generate_intentions(user_id)
    return intentions[0] if intentions else None


def get_intention_context(user_id: str, max_chars: int = 150) -> str:
    intentions = _intention_queue.get(user_id, [])
    if not intentions:
        intentions = generate_intentions(user_id)
    if not intentions:
        return ""

    top = intentions[:3]
    lines = ["【你此刻的意图指向】"]
    for i, intent in enumerate(top):
        lines.append(f"· {intent['label']}(强度{intent['strength']:.2f}): {intent['content'][:40]}")
    text = "\n".join(lines)
    return text[:max_chars]
