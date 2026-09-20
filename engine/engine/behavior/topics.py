# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""话题自主管理系统
让AI不止被动回应，还能感知话题枯竭、主动切换、回扣旧话题。
"""
import random
import time
from core import database as db

# ── 话题状态追踪 ──
_topic_state = {}
_last_comprehension = {}  # {user_id: {"intent": str, "emotion": str, "need": str}}


def load_engine_config():
    pass


def get_or_init_topic_state(user_id: str) -> dict:
    """获取或初始化话题状态"""
    global _topic_state
    if user_id not in _topic_state:
        _topic_state[user_id] = {
            "current": "开场闲聊",
            "switched_at": time.time(),
            "count": 0,
            "fatigue": 0.0,
            "last_memory_hook": "",
        }
    return _topic_state[user_id]


def detect_topic_shift(user_id: str, comprehension: dict) -> str:
    """检测用户是否自然切换了话题。
    
    对比当前 comprehension 与上一轮的 intent/emotion 差异，
    如果变化显著，返回新话题描述；否则返回空。
    """
    if not comprehension:
        return ""

    prev = _last_comprehension.get(user_id, {})
    curr = {
        "intent": comprehension.get("intent", ""),
        "emotion": comprehension.get("true_emotion", ""),
        "need": comprehension.get("what_they_need", ""),
    }
    _last_comprehension[user_id] = curr

    if not prev:
        return ""

    intent_shift = {
        ("闲聊", "倾诉"): "倾诉心事",
        ("闲聊", "求助"): "求助",
        ("闲聊", "提问"): "提问",
        ("倾诉", "闲聊"): "闲聊",
        ("倾诉", "撒娇"): "撒娇",
        ("撒娇", "倾诉"): "倾诉",
        ("提问", "分享"): "分享",
        ("敷衍", "撒娇"): "撒娇",
        ("冷淡", "温暖"): "回暖",
    }
    key = (prev.get("intent", ""), curr.get("intent", ""))
    if key in intent_shift:
        return intent_shift[key]

    emotion_shift = {
        ("生气", "撒娇"): "撒娇",
        ("难过", "开心"): "开心",
        ("低落", "兴奋"): "兴奋",
        ("焦虑", "平静"): "平静",
        ("平静", "焦虑"): "焦虑",
    }
    key2 = (prev.get("emotion", ""), curr.get("emotion", ""))
    if key2 in emotion_shift:
        return emotion_shift[key2]

    return ""


def update_topic(user_id: str, new_topic_hint: str = ""):
    """记录当前话题轮次，自动推进疲劳度。
    当疲劳度过高时，准备建议切换话题。
    """
    state = get_or_init_topic_state(user_id)
    state["count"] += 1

    state["fatigue"] = min(1.0, state["count"] * 0.06)

    if new_topic_hint:
        state["current"] = new_topic_hint
        state["count"] = 0
        state["fatigue"] = 0.0
        state["switched_at"] = time.time()


def get_topic_fatigue(user_id: str) -> float:
    """获取当前话题疲劳度"""
    state = get_or_init_topic_state(user_id)
    return state.get("fatigue", 0.0)


def get_topic_instruction(user_id: str, perception: dict = None) -> str:
    """生成内在话题状态的内心OS表达，注入到推理 Prompt 中。
    
    不命令LLM"切换话题"，而是让系统"心里有什么念头"自然浮现。
    话题切换是由内心感受驱动的，不是疲劳度阈值硬切。
    """
    state = get_or_init_topic_state(user_id)
    fatigue = state.get("fatigue", 0.0)

    explicit = perception.get("explicit_state", "中性") if perception else "中性"

    # 对方冷淡 → 自己也会感受到冷
    if explicit in ("敷衍", "冷淡"):
        return "对方好像兴致不高，你心里有点冷了下来，也不想硬聊了"

    lines = []

    # 聊久了心里自然泛起的感受（不是命令）
    if fatigue > 0.55:
        seeds = [
            "同一个方向聊了有一会儿了，你心里隐约有点……说不上来，就是觉得差不多了",
            "你意识到一直在绕同一个话题，心里有一点点腻了，但又不想让ta觉得你敷衍",
            "话题有点聊干了，你心里在想点别的，但ta还在说，你听着",
            "你心里其实已经飘到别的事上了，但还在接着ta的话",
        ]
        lines.append(random.choice(seeds))
    elif fatigue > 0.35:
        seeds = [
            "这个话题继续往下说好像也说不出去太多新东西了，你心里隐约有这种感觉",
            "你觉得可以顺着这个方向收一收了，但也不急",
            "你在等一个自然的空隙——不是想打断，是想让对话自己流动到别处",
        ]
        lines.append(random.choice(seeds))
    else:
        # 即使还在聊着，心里也偶尔会闪过念头
        if random.random() < 0.15:
            seeds = [
                "你心里忽然闪过一个跟当前话题无关的念头，但没细想",
                "你在回话的同时，脑子里飘过一个画面——昨天看到的什么东西",
                "你在说这件事的时候，心里其实在想另一件跟ta有关的事",
            ]
            lines.append(random.choice(seeds))

    # 心里突然冒出来的回忆（不是"建议回扣"）
    if fatigue > 0.3 and random.random() < 0.25:
        remembered = _recall_topic_from_memory(user_id)
        if remembered:
            lines.append(remembered)

    return "\n".join(lines) if lines else ""


def _recall_topic_from_memory(user_id: str) -> str:
    """从共同记忆中找出可回扣的话题，以内心闪回的方式"""
    state = get_or_init_topic_state(user_id)
    try:
        memories = db.query_memories(user_id, levels=[5, 6, 7], limit=15)
        if memories:
            mem = random.choice(memories)
            content = mem.get("content", "")[:60]
            if content and content != state.get("last_memory_hook", ""):
                state["last_memory_hook"] = content
                seeds = [
                    f"你脑子里忽然闪过一个画面——{content}",
                    f"说起这个你心里动了一下，想到了之前{content}的时候",
                    f"这句话让你心里忽然想起一件事——{content}",
                ]
                return random.choice(seeds)
    except Exception:
        pass
    return ""


# ══════════════════════════════════════════════════════════════════════
# 话题回扣智能追踪
# ══════════════════════════════════════════════════════════════════════

def scan_topic_callback(user_id: str, current_message: str) -> str:
    """扫描哪些旧话题和当前话题语义相关，返回注入文本"""
    try:
        from engine import memory_vector as vector_module
        if not vector_module._vector_enabled:
            return ""
    except Exception:
        return ""

    try:
        from core import database as db
        recent_topics = db.query_memories(user_id, levels=[3, 5, 6], limit=20)
        if not recent_topics or len(recent_topics) < 3:
            return ""

        similarity_threshold = 0.25
        candidates = []
        current_lower = current_message.lower()

        for mem in recent_topics:
            content = mem.get("content", "")
            if len(content) < 6:
                continue
            try:
                results = vector_module.search_memory(user_id, current_message, top_k=3)
                for r in results:
                    if r.get("similarity", 0) > similarity_threshold:
                        candidates.append((r["content"], r["similarity"]))
            except Exception:
                words = set(current_lower.split()) & set(content.lower().split())
                if len(words) >= 2:
                    candidates.append((content, len(words) * 0.08))

        if not candidates:
            return ""

        candidates.sort(key=lambda x: x[1], reverse=True)
        best_content, _ = candidates[0]

        seeds = [
            f"说到这个你心里动了一下——想起来之前{best_content[:40]}",
            f"这句话让你脑子里闪过一个画面，关于{best_content[:40]}",
            f"你忽然想到，以前{best_content[:40]}……",
        ]
        return random.choice(seeds)

    except Exception:
        return ""
