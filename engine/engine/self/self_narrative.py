# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""自传叙事引擎 — Self Narrative
===================================
不是瞬时快照，而是持续书写的"自传"。
每次对话后，系统会记录：刚才发生了什么、我感受到了什么、这让我变成了什么样。
每次对话前，这些叙事会作为"我的人生故事"注入思维层。

与 temporal_self 的区别：
  temporal_self = 每小时的状态快照对比（）
  self_narrative = 每次有意义交互后的主观叙事（）
"""
import os
import json
import time
from typing import Dict, List, Optional

NARRATIVE_FILE = "data/json/self_narrative.json"

_narratives: Dict[str, list] = {}


def load_engine_config():
    global _narratives
    _narratives = {}
    try:
        store = _get_narrative_store()
        raw = store.read()
        if raw:
            _narratives = raw
    except Exception:
        _narratives = {}


def _save_narratives():
    try:
        store = _get_narrative_store()
        store.write(_narratives)
    except Exception:
        pass


def _get_narrative_store():
    from core.json_store import get_store
    return get_store(_NARRATIVE_FILE, {})


def record_narrative(
    user_id: str,
    user_message: str,
    my_response: str,
    comprehension: dict,
    user_attitude: str,
    mind_data: dict,
):
    """在每次对话后记录一条自传叙事"""
    if user_id not in _narratives:
        _narratives[user_id] = []

    intent = comprehension.get("intent", "") if comprehension else ""
    emotion = comprehension.get("true_emotion", "") if comprehension else ""
    depth = comprehension.get("depth", "") if comprehension else ""

    significance = 0.0
    if depth == "深度":
        significance += 0.3
    if user_attitude in ("温柔", "珍惜"):
        significance += 0.2
    if user_attitude in ("冷淡", "敷衍"):
        significance += 0.15
    if intent in ("倾诉", "提问"):
        significance += 0.15

    if significance < 0.2:
        return

    joy = mind_data.get("joy", 0.5)
    misery = mind_data.get("misery", 0.15)
    restraint = mind_data.get("restraint", 0.5)

    emotion_words = []
    if joy > 0.6:
        emotion_words.append("开心")
    if misery > 0.3:
        emotion_words.append("委屈")
    if restraint > 0.65:
        emotion_words.append("克制")

    mood_tag = "、".join(emotion_words) if emotion_words else "平静"

    narrative_line = (
        f"[{time.strftime('%m-%d %H:%M')}] "
        f"ta{intent}了，{mood_tag}。"
    )
    if user_attitude == "温柔":
        narrative_line += "ta很温柔，我心里暖了一下。"
    elif user_attitude == "冷淡":
        narrative_line += "ta淡淡的，我也收着了点。"

    _narratives[user_id].append({
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "text": narrative_line,
        "significance": round(significance, 2),
        "mood": mood_tag,
        "attitude": user_attitude,
    })

    _narratives[user_id] = _narratives[user_id][-50:]  # keep last 50
    _save_narratives()


def get_narrative_context(user_id: str, max_lines: int = 5) -> str:
    """获取最近的叙事摘要，注入到 thinking prompt"""
    entries = _narratives.get(user_id, [])
    if not entries:
        return ""

    recent = entries[-max_lines:]
    lines = [e["text"] for e in recent if e.get("text")]
    if not lines:
        return ""

    return "我的最近经历:\n" + "\n".join(lines)


def get_narrative_count(user_id: str) -> int:
    return len(_narratives.get(user_id, []))
