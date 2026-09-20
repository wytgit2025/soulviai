# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""推理记忆缓存 — Reasoning Memory
=========================================
缓存推理链条，供后续相似场景复用和对照。

存储结构:
  (state_fingerprint, user_intent, reasoning_path, final_response, user_feedback)

能力:
  1. 相似场景识别 — 根据心智状态指纹+用户意图匹配历史推理
  2. 推理复用 — 历史通过的推理路径可直接参考
  3. 反馈学习 — 用户反馈好的推理链强化权重
"""
import json
import hashlib
import time
from typing import Dict, List, Optional, Tuple

try:
    from core import database as db
except ImportError:
    db = None

MEMORY_CACHE: List[Dict] = []
MAX_CACHED_CHAINS = 50
_last_persist = 0
PERSIST_INTERVAL = 300


def load_engine_config():
    global MEMORY_CACHE
    MEMORY_CACHE = []
    try:
        rows = db.get_reasoning_chains(max_count=MAX_CACHED_CHAINS)
        for r in rows:
            MEMORY_CACHE.append({
                "id": r.get("id", 0),
                "state_fingerprint": r.get("state_fingerprint", ""),
                "user_intent": r.get("user_intent", ""),
                "user_emotion": r.get("user_emotion", ""),
                "reasoning_summary": r.get("reasoning_summary", ""),
                "final_response": r.get("final_response", "")[:100],
                "quality_score": r.get("quality_score", 0.5),
                "feedback_score": r.get("feedback_score", 0),
                "timestamp": r.get("created_at", ""),
            })
    except Exception:
        pass


def _compute_state_fingerprint(mind_data: dict) -> str:
    if not mind_data:
        return "default"
    key_dims = ["joy", "misery", "dependence", "loneliness", "fatigue",
                "restraint", "emotional_volatility", "obsession"]
    parts = []
    for d in key_dims:
        val = mind_data.get(d, 0.5)
        bucket = round(val * 10) / 10
        parts.append(f"{d}:{bucket:.1f}")
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:12]


def store_reasoning_chain(
    user_id: str,
    mind_data: dict,
    comprehension: dict,
    reasoning_path: str,
    final_response: str,
    quality_score: float = 0.5,
):
    fingerprint = _compute_state_fingerprint(mind_data)
    intent = comprehension.get("intent", "") if comprehension else ""
    emotion = comprehension.get("true_emotion", "") if comprehension else ""

    entry = {
        "id": len(MEMORY_CACHE),
        "state_fingerprint": fingerprint,
        "user_intent": intent,
        "user_emotion": emotion,
        "reasoning_summary": reasoning_path[:200],
        "final_response": final_response[:100],
        "quality_score": quality_score,
        "feedback_score": 0,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    MEMORY_CACHE.append(entry)
    if len(MEMORY_CACHE) > MAX_CACHED_CHAINS:
        MEMORY_CACHE.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
        del MEMORY_CACHE[MAX_CACHED_CHAINS:]

    global _last_persist
    if time.time() - _last_persist > PERSIST_INTERVAL:
        _persist_all(user_id)
        _last_persist = time.time()


def _persist_all(user_id: str):
    try:
        for entry in MEMORY_CACHE[-10:]:
            db.save_reasoning_chain(
                user_id=user_id,
                state_fingerprint=entry["state_fingerprint"],
                user_intent=entry["user_intent"],
                user_emotion=entry["user_emotion"],
                reasoning_summary=entry["reasoning_summary"],
                final_response=entry["final_response"],
                quality_score=entry["quality_score"],
            )
    except Exception:
        pass


def find_similar_reasoning(
    mind_data: dict,
    comprehension: dict,
    max_results: int = 3,
) -> List[Dict]:
    if not MEMORY_CACHE:
        return []

    fingerprint = _compute_state_fingerprint(mind_data)
    intent = comprehension.get("intent", "") if comprehension else ""

    candidates = []
    for entry in MEMORY_CACHE:
        score = 0.0
        if entry["state_fingerprint"] == fingerprint:
            score += 0.4
        else:
            common = sum(1 for a, b in zip(fingerprint, entry["state_fingerprint"]) if a == b)
            score += 0.2 * (common / max(len(fingerprint), 1))

        if entry["user_intent"] == intent and intent:
            score += 0.35

        if entry.get("feedback_score", 0) > 0:
            score += 0.1 * entry["feedback_score"]

        score += entry.get("quality_score", 0.5) * 0.15

        if score > 0.3:
            candidates.append({**entry, "match_score": round(score, 3)})

    candidates.sort(key=lambda x: x["match_score"], reverse=True)
    return candidates[:max_results]


def record_feedback(chain_id: int, score: float):
    for entry in MEMORY_CACHE:
        if entry["id"] == chain_id:
            entry["feedback_score"] = max(0, min(1.0, (entry.get("feedback_score", 0) + score) / 2))
            break


def get_reasoning_context(mind_data: dict, comprehension: dict, max_chars: int = 200) -> str:
    similar = find_similar_reasoning(mind_data, comprehension, max_results=2)
    if not similar:
        return ""

    lines = ["【历史推理参考】"]
    total = 0
    for s in similar:
        line = f"· 类似场景(匹配{s['match_score']:.0%}): {s['reasoning_summary'][:50]}"
        if s.get("feedback_score", 0) > 0:
            line += f" (用户正面反馈)"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)

    if len(lines) > 1:
        return "\n".join(lines)
    return ""
