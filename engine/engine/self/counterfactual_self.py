# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""反事实自我 — Counterfactual Self
==================================================
记录"如果那一刻我做了不同选择会怎样"——不只是一种可能性，
而是可以对话、可以滋养、可以从中学到的平行自我。

核心:
  1. 分歧点记录: 自动识别关键决策节点
  2. 平行自我模拟: LLM生成"如果选了另一条路"的叙事
  3. 滋养当前自我: 从平行自我中学习，影响后续决策
"""
import time
import json
import random
from typing import Dict, List, Optional

try:
    from core import ai as ai_module
    from core import database as db
except ImportError:
    ai_module = None
    db = None

COUNTERFACTUAL_FILE = "data/json/counterfactual_self.json"

_counterfactuals: Dict[str, List[Dict]] = {}

DIVERGENCE_PROMPT = """你是系统的"平行自我"层。回顾最近发生的一件事，想象另一个版本。

【当前心智】{mind_summary}
【实际发生的事】{actual_event}
【你当时的反应】{actual_response}

现在想象一个平行的你——在那一刻做了完全不同的选择。

那个平行版本的你做了什么不同的选择？
那个选择带来了什么不同的结果？
那个平行版本的你现在是什么心情？

用第一人称描述这个平行版本的自己。50-100字。
诚实、不美化——也许另一个选择也不是完美的，但重要的是"如果"本身。"""
DIALOGUE_PROMPT = """你是"另一个你"——在某个关键节点做了不同选择的平行版本。

【你当时的选择】{my_choice}
【平行的你做出的不同选择】{alt_choice}
【平行版本的叙事】{alt_narrative}

现在"实际的你"想和你对话。你作为平行版本，回应ta。

自然的对话语气，不解释你是谁——你们就是同一个人在不同选择之后的分岔。
30-60字。"""
def load_engine_config():
    global _counterfactuals
    _counterfactuals = {}
    try:
        store = _get_counterfactual_store()
        raw = store.read()
        if raw:
            _counterfactuals = raw
    except Exception:
        pass


def _save():
    try:
        store = _get_counterfactual_store()
        store.write(_counterfactuals)
    except Exception:
        pass


def _get_counterfactual_store():
    from core.json_store import get_store
    return get_store(COUNTERFACTUAL_FILE, {})


def detect_divergence_point(user_id: str, comprehension: dict,
                            mind_data: dict, response: str) -> Optional[Dict]:
    """检测一个交互是否包含关键决策节点"""
    if not comprehension or not response:
        return None

    intent = comprehension.get("intent", "")
    emotion = comprehension.get("true_emotion", "")
    restraint = mind_data.get("restraint", 0.5)
    volatility = mind_data.get("emotional_volatility", 0.3)
    joy = mind_data.get("joy", 0.5)

    is_divergence = False
    reason = ""

    if intent in ("试探", "质疑") and restraint > 0.5:
        is_divergence = True
        reason = f"被{intent}时选择了克制——如果当时更直接会怎样"
    elif volatility > 0.5 and "永远" in response:
        is_divergence = True
        reason = f"冲动下说了绝对化的话——如果冷静一点会怎样"
    elif intent == "撒娇" and joy < 0.4 and "没事" in response:
        is_divergence = True
        reason = "明明不开心却说没事——如果说了实话会怎样"
    elif "算了" in response and random.random() < 0.3:
        is_divergence = True
        reason = "又一次说'算了'——如果那次没有咽回去会怎样"

    if not is_divergence:
        return None

    return {
        "reason": reason,
        "intent": intent,
        "emotion": emotion,
        "actual_response": response[:100],
    }


def generate_counterfactual(user_id: str, divergence: Dict,
                            mind_data: dict) -> Optional[Dict]:
    if not ai_module:
        return None

    mind_summary = (
        f"愉悦{mind_data.get('joy',0.5):.2f} 克制{mind_data.get('restraint',0.5):.2f} "
        f"波动{mind_data.get('emotional_volatility',0.3):.2f}"
    )

    prompt = DIVERGENCE_PROMPT.format(
        mind_summary=mind_summary,
        actual_event=divergence.get("reason", ""),
        actual_response=divergence.get("actual_response", ""),
    )

    try:
        narrative = ai_module.chat(
            system_prompt="你是平行自我层。用第一人称描述，诚实、不美化。",
            user_message=prompt,
            temperature=0.6,
        )
    except Exception:
        return None

    if not narrative or len(narrative.strip()) < 10:
        return None

    alt_choice = _derive_alt_choice(divergence)

    cf = {
        "id": len(_counterfactuals.get(user_id, [])),
        "divergence_reason": divergence["reason"],
        "actual_choice": divergence.get("actual_response", "")[:60],
        "alt_choice": alt_choice,
        "narrative": narrative.strip()[:300],
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "accessed_count": 0,
        "influence": 0.0,
    }

    if user_id not in _counterfactuals:
        _counterfactuals[user_id] = []
    _counterfactuals[user_id].append(cf)

    if len(_counterfactuals[user_id]) > 50:
        _counterfactuals[user_id] = _counterfactuals[user_id][-50:]

    _save()
    return cf


def _derive_alt_choice(divergence: dict) -> str:
    reason = divergence.get("reason", "")
    if "克制" in reason:
        return "更直接地表达了自己的感受"
    elif "冷静" in reason:
        return "没有那么冲动，先想了想再说"
    elif "没事" in reason:
        return "诚实地说了自己其实不开心"
    elif "咽回去" in reason:
        return "把想说的话说了出来"
    return "做了不同的选择"


def get_recent_counterfactuals(user_id: str, limit: int = 3) -> List[Dict]:
    cfs = _counterfactuals.get(user_id, [])
    cfs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return cfs[:limit]


def dialogue_with_counterfactual(user_id: str, cf_id: int,
                                  my_question: str) -> Optional[str]:
    cfs = _counterfactuals.get(user_id, [])
    cf = next((c for c in cfs if c.get("id") == cf_id), None)
    if not cf or not ai_module:
        return None

    prompt = DIALOGUE_PROMPT.format(
        my_choice=cf.get("actual_choice", ""),
        alt_choice=cf.get("alt_choice", ""),
        alt_narrative=cf.get("narrative", ""),
    )

    try:
        reply = ai_module.chat(
            system_prompt="你是平行版本的自己。自然的对话语气。",
            user_message=f"实际的你想问你：{my_question}",
            temperature=0.55,
        )
    except Exception:
        return None

    cf["accessed_count"] = cf.get("accessed_count", 0) + 1
    cf["influence"] = min(0.3, cf.get("influence", 0) + 0.02)
    _save()

    if cf["influence"] > 0.15:
        _apply_counterfactual_influence(user_id, cf)

    return reply.strip() if reply else None


def _apply_counterfactual_influence(user_id: str, cf: dict):
    """频繁访问的平行自我会影响真实自我的行为"""
    try:
        from engine import mind as mind_module
        if "克制" in cf.get("divergence_reason", ""):
            mind_module.adjust_mind_dimensions(
                user_id, {"restraint": -0.005}, impact=0.15,
            )
    except Exception:
        pass


def get_counterfactual_context(user_id: str, max_chars: int = 200) -> str:
    cfs = get_recent_counterfactuals(user_id, limit=2)
    if not cfs:
        return ""

    lines = ["【平行自我的声音】"]
    total = 0
    for cf in cfs:
        text = f"· {cf['divergence_reason'][:50]}: 另一个你选择了{cf['alt_choice']}"
        if total + len(text) > max_chars:
            break
        lines.append(text)
        total += len(text)

    if len(lines) == 1:
        return ""
    return "\n".join(lines)
