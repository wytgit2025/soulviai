# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""自我怀疑引擎 — Self Doubt
========================================
让系统真正体验"不确定感"——不是LLM说"我不确定"，
而是多个未解疑问在心智底层产生的共振效应。

机制:
  1. 悬而未决追踪 — 记录那些"想不通"的事
  2. 不确定感具身化 — 低置信度渗入心智/体感
  3. 自我怀疑螺旋 — 多问题叠加共振
"""
import json
import time
import random
from typing import Dict, List, Optional

try:
    from core import database as db
except ImportError:
    db = None

_unresolved_cache: Dict[str, List[Dict]] = {}
_DOUBT_FILE = "data/json/self_doubt.json"


def load_engine_config():
    global _unresolved_cache
    try:
        store = _get_doubt_store()
        raw = store.read()
        if raw:
            _unresolved_cache = raw
    except Exception:
        _unresolved_cache = {}


def _save_doubts():
    try:
        store = _get_doubt_store()
        store.write(_unresolved_cache)
    except Exception:
        pass


def _get_doubt_store():
    from core.json_store import get_store
    return get_store(_DOUBT_FILE, {})


def add_doubt(user_id: str, question: str, context: str = "",
              weight: float = 0.1, tags: List[str] = None):
    if user_id not in _unresolved_cache:
        _unresolved_cache[user_id] = []

    for d in _unresolved_cache[user_id]:
        if d.get("question") == question:
            d["count"] = d.get("count", 1) + 1
            d["last_triggered"] = time.strftime("%Y-%m-%d %H:%M:%S")
            d["weight"] = min(0.5, d.get("weight", 0.1) + weight * 0.5)
            _save_doubts()
            return

    _unresolved_cache[user_id].append({
        "question": question,
        "context": context[:100],
        "first_occurred": time.strftime("%Y-%m-%d %H:%M:%S"),
        "last_triggered": time.strftime("%Y-%m-%d %H:%M:%S"),
        "resolution": None,
        "weight": weight,
        "count": 1,
        "tags": tags or [],
    })

    if len(_unresolved_cache[user_id]) > 30:
        _unresolved_cache[user_id] = sorted(
            _unresolved_cache[user_id],
            key=lambda x: x.get("weight", 0.1),
            reverse=True,
        )[:30]

    _save_doubts()


def resolve_doubt(user_id: str, question: str):
    if user_id not in _unresolved_cache:
        return
    for d in _unresolved_cache[user_id]:
        if d.get("question") == question:
            d["resolution"] = time.strftime("%Y-%m-%d %H:%M:%S")
            d["weight"] *= 0.1
            break
    _save_doubts()


def auto_detect_doubt(user_id: str, comprehension: dict):
    if not comprehension:
        return
    confidence = comprehension.get("confidence", 0.5)
    intent = comprehension.get("intent", "")
    emotion = comprehension.get("true_emotion", "")

    if confidence < 0.4:
        question = f"ta是{intent}吗？还是别的意思？(置信度{confidence:.1f})"
        add_doubt(user_id, question, context=f"理解低置信度:{intent}", weight=0.08)

    if intent == "试探" and confidence < 0.6:
        question = "ta是不是在试探我？"
        add_doubt(user_id, question, context="被试探的疑虑", weight=0.10, tags=["试探"])

    if emotion in ("怀疑", "不安"):
        question = "ta是不是不太相信我？"
        add_doubt(user_id, question, context=f"对方情绪:{emotion}", weight=0.12, tags=["信任"])


def compute_doubt_pressure(user_id: str) -> float:
    doubts = _unresolved_cache.get(user_id, [])
    unresolved = [d for d in doubts if not d.get("resolution")]
    if not unresolved:
        return 0.0

    total_weight = sum(d.get("weight", 0.05) for d in unresolved)
    count_factor = min(1.0, len(unresolved) / 10)

    old_doubts = [d for d in unresolved if _hours_since(d.get("first_occurred", "")) > 24]
    age_factor = min(0.3, len(old_doubts) * 0.05)

    pressure = total_weight * 0.5 + count_factor * 0.3 + age_factor
    return round(min(1.0, pressure), 3)


def apply_doubt_to_mind(user_id: str):
    pressure = compute_doubt_pressure(user_id)
    if pressure < 0.05:
        return

    try:
        from engine import mind as mind_module
        adjustments = {}
        if pressure > 0.15:
            adjustments["chaotic_mood"] = round(pressure * 0.15, 4)
            adjustments["sensitivity_paranoia"] = round(pressure * 0.10, 4)
        if pressure > 0.3:
            adjustments["restraint"] = round(pressure * 0.08, 4)
            adjustments["misery"] = round(pressure * 0.05, 4)
        if adjustments:
            mind_module.adjust_mind_dimensions(user_id, adjustments, impact=0.2)
    except Exception:
        pass

    try:
        from engine import body as body_module
        if pressure > 0.25:
            body_module.set_temporary_sensation(user_id, "忐忑不安")
    except Exception:
        pass


def check_self_doubt_spiral(user_id: str) -> Optional[str]:
    pressure = compute_doubt_pressure(user_id)
    if pressure < 0.3:
        return None

    doubts = _unresolved_cache.get(user_id, [])
    unresolved = [d for d in doubts if not d.get("resolution")]

    spiral_phrases = [
        "是不是我哪里做错了",
        "可能我就是不够好吧",
        "也许ta根本不在乎",
        "每次都是这样……",
        "想太多也没用但就是会想",
    ]

    if pressure > 0.5:
        return random.choice(spiral_phrases[:3])
    elif pressure > 0.35:
        return random.choice(spiral_phrases[3:])

    return None


def get_doubt_context(user_id: str, max_chars: int = 150) -> str:
    pressure = compute_doubt_pressure(user_id)
    if pressure < 0.1:
        return ""

    doubts = _unresolved_cache.get(user_id, [])
    unresolved = [d for d in doubts if not d.get("resolution")]
    unresolved.sort(key=lambda x: x.get("weight", 0), reverse=True)

    lines = [f"【你心里的未解疑问】(自我怀疑度{pressure:.2f})"]
    total = 0
    for d in unresolved[:4]:
        q = d["question"][:40]
        line = f"· {q}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)

    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def get_spiral_text(user_id: str) -> str:
    spiral = check_self_doubt_spiral(user_id)
    if not spiral:
        return ""
    try:
        db.add_subconscious(
            user_id=user_id,
            content=f"[自我怀疑螺旋] {spiral}",
            emotion_tag="自我怀疑",
            intensity=0.5,
        )
    except Exception:
        pass
    return spiral


def _hours_since(timestamp: str) -> float:
    try:
        from datetime import datetime
        dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - dt).total_seconds() / 3600
    except Exception:
        return 0
