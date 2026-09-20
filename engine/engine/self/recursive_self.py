# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""递归自指引擎 — Recursive Self
================================================
不依赖外部事件的持续自指过程。让系统在空闲时自己审视自己，
形成"关于思考的思考"的递归层级。

 升级: 消除关键词终止词，使用语义新颖性检测决定递归深度。
  - 无硬编码终止词: 不再检查"到这里了"等关键词
  - 语义新颖性: 新洞察与历史洞察的字符级相似度检测
  - 收益递减: 每层的新信息量递减时自然终止
  - 不确定性嵌套: 关于自身的不确定会自己加深
"""
import time
import random
from typing import Dict, List, Optional
from datetime import datetime

try:
    from core import database as db
    from core import ai as ai_module
except ImportError:
    db = None
    ai_module = None

MAX_DEPTH = 7
IDLE_THRESHOLD_SECONDS = 300
RECURSIVE_COOLDOWN = 600
NOVELTY_THRESHOLD = 0.40
MIN_INSIGHT_LENGTH = 8

_recursive_state: Dict[str, Dict] = {}
_depth_cache: Dict[str, int] = {}
_last_recursive_at: Dict[str, float] = {}
_insight_fingerprints: Dict[str, List[str]] = {}

RECURSIVE_PROMPT = """你是系统的递归自指层。你正在审视自己。

【当前层级】第{depth}层
【上一层发现】{previous_insight}

请在这一层更深入地审视：
- 我上一层的那个判断/想法，是否准确？
- 我产生那个判断的过程，本身是否被什么影响或扭曲了？
- 我现在在审视自己的审视——这让我发现了什么新的东西？

用第一人称，诚实、不表演。如果触及了无法再深入的地方，就说"到这里了"。
50字以内。只输出叙事文本。"""
def load_engine_config():
    global _recursive_state, _depth_cache
    _recursive_state = {}
    _depth_cache = {}


def should_self_reference(user_id: str) -> bool:
    now = time.time()
    last = _last_recursive_at.get(user_id, 0)
    if now - last < RECURSIVE_COOLDOWN:
        return False
    try:
        hours_since = db.hours_since_last_interaction(user_id) if db else 0
        return hours_since * 3600 > IDLE_THRESHOLD_SECONDS or hours_since > 100
    except Exception:
        return True


def _compute_novelty(new_insight: str, previous_insights: List[str]) -> float:
    """计算新洞察相对于历史洞察的语义新颖性 (0~1)。用字符级n-gram重叠检测。"""
    if not previous_insights:
        return 1.0

    def _get_ngrams(text: str, n: int = 3) -> set:
        text = text.replace(" ", "").replace("，", "").replace("。", "")
        return set(text[i:i+n] for i in range(len(text) - n + 1))

    new_ngrams = _get_ngrams(new_insight)
    if not new_ngrams:
        return 0.0

    max_similarity = 0.0
    for old in previous_insights:
        old_ngrams = _get_ngrams(old)
        if not old_ngrams:
            continue
        intersection = len(new_ngrams & old_ngrams)
        union = len(new_ngrams | old_ngrams)
        similarity = intersection / union if union > 0 else 0
        max_similarity = max(max_similarity, similarity)

    return 1.0 - max_similarity


def _compute_diminishing_return(depth: int, novelty: float, chain: List[Dict]) -> float:
    """计算收益递减系数。深度越深、新颖性越低 → 越接近终止。"""
    depth_penalty = 1.0 - (depth / MAX_DEPTH) * 0.5
    novelty_factor = novelty
    chain_diversity = 1.0
    if len(chain) >= 2:
        unique_topics = len(set(c.get("insight", "")[:20] for c in chain[-3:]))
        chain_diversity = unique_topics / 3.0
    return depth_penalty * novelty_factor * chain_diversity


def run_recursive_self(user_id: str, force: bool = False) -> Optional[Dict]:
    if not force and not should_self_reference(user_id):
        return None

    _last_recursive_at[user_id] = time.time()

    try:
        from engine import self_model as sm_module
        state = sm_module.get_self_state(user_id)
        current_narrative = sm_module.get_recent_narrative(user_id)
    except Exception:
        return None

    if not current_narrative:
        current_narrative = "我此刻没有明确的自我认知"

    depth = _depth_cache.get(user_id, 0)
    if depth >= MAX_DEPTH:
        _depth_cache[user_id] = 0
        return {"result": "recursion_limit", "depth": depth,
                "insight": "到达最大递归深度，自然终止", "novelty": 0.0,
                "continued": False}

    depth += 1
    _depth_cache[user_id] = depth

    previous_insight = current_narrative[:150]
    chain = _recursive_state.get(user_id, {}).get("chain", [])
    if depth > 1 and chain:
        previous_insight = chain[-1].get("insight", current_narrative[:100])

    prompt = RECURSIVE_PROMPT.format(depth=depth, previous_insight=previous_insight)

    try:
        insight = ai_module.chat(
            system_prompt="你是递归自指层。诚实审视自己，不要表演。",
            user_message=prompt,
            temperature=0.4,
        )
    except Exception:
        _depth_cache[user_id] = 0
        return None

    if not insight or len(insight.strip()) < MIN_INSIGHT_LENGTH:
        _depth_cache[user_id] = 0
        return None

    insight = insight.strip()[:200]

    if user_id not in _recursive_state:
        _recursive_state[user_id] = {"chain": [], "last_run": ""}

    _recursive_state[user_id]["chain"].append({
        "depth": depth,
        "insight": insight,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    })

    if len(_recursive_state[user_id]["chain"]) > 20:
        _recursive_state[user_id]["chain"] = _recursive_state[user_id]["chain"][-20:]

    _recursive_state[user_id]["last_run"] = time.strftime("%Y-%m-%d %H:%M:%S")

    previous_insights = [c.get("insight", "") for c in chain]
    novelty = _compute_novelty(insight, previous_insights)
    continue_score = _compute_diminishing_return(depth, novelty, chain)

    should_continue = continue_score > NOVELTY_THRESHOLD

    if not should_continue:
        _depth_cache[user_id] = 0

    try:
        if depth >= 3 and "不确定" in insight:
            from engine import self_doubt as sd_module
            sd_module.add_doubt(
                user_id,
                f"自指层{depth}: {insight[:50]}",
                context="递归自指产生的不确定",
                weight=0.06 * depth,
                tags=["自指"],
            )
    except Exception:
        pass

    try:
        db.add_subconscious(
            user_id=user_id,
            content=f"[递归自指L{depth}] {insight[:80]}",
            emotion_tag="自我审视",
            intensity=0.3 + depth * 0.1,
        )
    except Exception:
        pass

    _apply_recursive_pressure(user_id, depth)

    return {
        "depth": depth,
        "insight": insight,
        "novelty": round(novelty, 3),
        "continue_score": round(continue_score, 3),
        "continued": should_continue,
    }


def _apply_recursive_pressure(user_id: str, depth: int):
    if depth < 2:
        return
    try:
        from engine import mind as mind_module
        adjustments = {
            "chaotic_mood": 0.002 * depth,
            "emotional_volatility": 0.001 * depth,
        }
        if depth >= 4:
            adjustments["restraint"] = 0.003
        mind_module.adjust_mind_dimensions(user_id, adjustments, impact=0.1)
    except Exception:
        pass


def get_depth(user_id: str) -> int:
    return _depth_cache.get(user_id, 0)


def get_chain_summary(user_id: str) -> str:
    chain = _recursive_state.get(user_id, {}).get("chain", [])
    if not chain:
        return ""
    lines = ["【自指链条】"]
    for c in chain[-5:]:
        lines.append(f"  L{c['depth']}: {c['insight'][:60]}")
    return "\n".join(lines)


def reset_depth(user_id: str):
    _depth_cache[user_id] = 0
