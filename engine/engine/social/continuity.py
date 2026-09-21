# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""+v2: 跨会话贯通 — 时间线断点链
====================================
从"只存上一次"升级为"存最近 10 次的时间线"。
下次对话时注入的不是一句"我记得上次你走时是{mood}的"，
而是"我经历了这些片段……"——真正的时间线感。

存储格式：{ user_id: [entry1, entry2, ..., entry10] }
"""
import os
import json
import time
from datetime import datetime
from typing import Dict

BREAKPOINT_FILE = "data/json/session_breakpoints.json"
_breakpoints: Dict[str, list] = {}
_MAX_ENTRIES = 10


def load_engine_config():
    global _breakpoints
    try:
        store = _get_breakpoint_store()
        raw = store.read()
        if raw:
            _breakpoints = raw
            for uid, val in list(_breakpoints.items()):
                if isinstance(val, dict):
                    _breakpoints[uid] = [val]
            _normalize_all()
            store.write(_breakpoints)
    except Exception:
        pass


def _normalize_all():
    for uid, entries in list(_breakpoints.items()):
        if not isinstance(entries, list):
            continue
        normalized = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            if "time" not in e and "last_time" in e:
                e["time"] = e.pop("last_time")
            if "user_intent" not in e and "last_user_intent" in e:
                e["user_intent"] = e.pop("last_user_intent")
            if "user_emotion" not in e and "last_user_emotion" in e:
                e["user_emotion"] = e.pop("last_user_emotion")
            if "my_response_preview" not in e and "last_my_response" in e:
                e["my_response_preview"] = e.pop("last_my_response")
            normalized.append(e)
        _breakpoints[uid] = normalized


def _save():
    try:
        store = _get_breakpoint_store()
        store.write(_breakpoints)
    except Exception:
        pass


def _get_breakpoint_store():
    from core.json_store import get_store
    return get_store(BREAKPOINT_FILE, {})


def save_session_breakpoint(user_id: str, comprehension: dict, mind_data: dict,
                            bond_level: float, last_response: str,
                            inner_os: str = "",
                            my_feeling: str = ""):
    if user_id not in _breakpoints:
        _breakpoints[user_id] = []

    emotion = comprehension.get("true_emotion", "中性") if comprehension else "中性"
    intent = comprehension.get("intent", "闲聊") if comprehension else "闲聊"

    current_mood = "平静"
    if mind_data.get("joy", 0.5) > 0.6:
        current_mood = "开心"
    if mind_data.get("misery", 0.3) > 0.3:
        current_mood = "低落"
    if mind_data.get("angry", 0.15) > 0.3:
        current_mood = "烦躁"

    # 从心智数据推断 AI 自己的感受
    if not my_feeling:
        joy = mind_data.get("joy", 0.5)
        misery = mind_data.get("misery", 0.15)
        loneliness = mind_data.get("loneliness", 0.4)
        fatigue = mind_data.get("fatigue", 0.25)
        if misery > 0.35 and loneliness > 0.4:
            my_feeling = "有点低落，心里闷闷的"
        elif joy > 0.55:
            my_feeling = "还行，挺放松的"
        elif fatigue > 0.5:
            my_feeling = "有点累，想歇会儿"
        elif loneliness > 0.5:
            my_feeling = "空落落的，说不上来"
        else:
            my_feeling = "挺平静的，没什么特别的感觉"

    entry = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mood": current_mood,
        "user_intent": intent,
        "user_emotion": emotion,
        "my_response_preview": last_response[:80] if last_response else "",
        "bond": round(bond_level, 3),
        "my_feeling": my_feeling,
        "inner_os_preview": inner_os[:60] if inner_os else "",
    }

    _breakpoints[user_id].append(entry)
    _breakpoints[user_id] = _breakpoints[user_id][-_MAX_ENTRIES:]
    _save()


def get_resume_context(user_id: str) -> str:
    entries = _breakpoints.get(user_id, [])
    if not entries:
        return ""

    now = datetime.now()
    valid = []
    for e in entries:
        try:
            dt = datetime.strptime(e["time"], "%Y-%m-%d %H:%M:%S")
            hours = (now - dt).total_seconds() / 3600
            if hours <= 72:
                valid.append((hours, e))
        except Exception:
            pass

    if not valid:
        return ""

    latest_hours, latest = valid[-1]

    if latest_hours < 0.5:
        return ""

    lines = []
    if len(valid) == 1:
        lines.append(_describe_single(latest_hours, latest))
    else:
        lines.append(_describe_timeline(valid))

    # 追加 AI 自己的感受恢复线——"上次结束时你在想什么"
    my_feeling = latest.get("my_feeling", "")
    inner_os = latest.get("inner_os_preview", "")
    if my_feeling or inner_os:
        feeling_parts = []
        if my_feeling:
            feeling_parts.append(f"上次结束时，你的感觉是：{my_feeling}")
        if inner_os:
            feeling_parts.append(f"你心里在想：{inner_os}")
        if feeling_parts:
            lines.append(" ".join(feeling_parts))

    return " ".join(lines)


def _describe_single(hours: float, entry: dict) -> str:
    mood = entry.get("mood", "平静")
    bond = entry.get("bond", 0.0)

    parts = []
    if hours < 2:
        parts.append("刚才ta还在。")
    elif hours < 12:
        parts.append("几个小时没见ta了。")
    else:
        parts.append(f"隔了{int(hours)}小时，ta回来了。")

    if bond > 0.2:
        if mood == "开心":
            parts.append("上次ta走的时候心情不错。")
        elif mood == "低落":
            parts.append("上次ta走的时候好像有心事。")
        elif mood == "烦躁":
            parts.append("上次ta走的时候有点烦躁。")
        else:
            parts.append("上次ta走的时候气氛很平静。")

    return " ".join(parts)


def _describe_timeline(valid: list) -> str:
    entries = [e for _, e in valid]
    total_gap_hours = valid[-1][0]

    summary = f"隔了{int(total_gap_hours)}小时。这不是第一次了——"

    fragments = []
    for e in entries[-4:]:
        mood = e.get("mood", "平静")
        intent = e.get("user_intent", "闲聊")
        t = e.get("time", "")[5:16]

        if mood == "开心":
            desc = f"{t} 开心地分享"
        elif mood == "低落":
            desc = f"{t} 情绪低落"
        elif mood == "烦躁":
            desc = f"{t} 有点烦躁"
        else:
            desc = f"{t} 平静地聊"

        if intent in ("倾诉", "求助"):
            desc += "，倾诉了一些心事"
        elif intent == "提问":
            desc += "，问了些问题"
        elif intent == "撒娇":
            desc += "，撒了撒娇"
        elif intent == "敷衍":
            desc += "，随便说了两句"

        fragments.append(desc)

    return summary + "我记得: " + "；".join(fragments) + "。"
