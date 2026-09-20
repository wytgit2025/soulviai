# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""后悔与修正引擎 — Regret Engine
=============================================
真人在社交中经常"发完就后悔"——不是系统规划的修改，
而是冲动→后悔→补救的真实过程。

机制:
  1. 回复后审视 — 发出后以更高温度重新审视自己的话
  2. 三种后悔行为: 追加修正(追加到原回复后) / 沉默后悔 / 过度补偿
  3. 后悔学习效应 — 每次后悔让下次更谨慎
"""
import random
import time
from typing import Dict, Optional, Tuple

try:
    from core import database as db
except ImportError:
    db = None

_regret_log: Dict[str, list] = {}
_regret_texts: Dict[str, list] = {}
_last_regret_text: Dict[str, str] = {}
REGRET_COOLDOWN = 120


def load_engine_config():
    global _regret_log, _regret_texts
    _regret_log = {}
    _regret_texts = {}


def detect_regret(response: str, mind_data: dict, comprehension: dict = None) -> Tuple[bool, str]:
    if not response or len(response) < 10:
        return False, ""

    volatility = mind_data.get("emotional_volatility", 0.3)
    restraint = mind_data.get("restraint", 0.5)
    chaotic = mind_data.get("chaotic_mood", 0.2)
    misery = mind_data.get("misery", 0.15)

    base_prob = volatility * 0.30 + (1.0 - restraint) * 0.20 + chaotic * 0.15
    if misery > 0.4:
        base_prob += 0.08

    if len(response) > 80:
        base_prob += 0.06

    high_emotion_words = ["永远", "从来", "绝对", "一直", "真的", "最"]
    hit_count = sum(1 for w in high_emotion_words if w in response)
    if hit_count >= 2:
        base_prob += 0.10

    if len(response) > 150:
        base_prob += 0.05

    base_prob = min(0.45, max(0.0, base_prob))

    if random.random() < base_prob:
        mode = _pick_regret_mode(mind_data)
        return True, mode

    return False, ""


def _pick_regret_mode(mind_data: dict) -> str:
    volatility = mind_data.get("emotional_volatility", 0.3)
    restraint = mind_data.get("restraint", 0.5)
    dependence = mind_data.get("dependence", 0.2)
    favoritism = mind_data.get("favoritism", 0.1)

    if dependence > 0.35 and favoritism > 0.25 and random.random() < 0.5:
        return "over_compensate"
    if restraint > 0.55 and random.random() < 0.5:
        return "silent_regret"
    if volatility > 0.45 and random.random() < 0.4:
        return "append_fix"
    return random.choice(["append_fix", "silent_regret", "over_compensate"])


def execute_regret(user_id: str, mode: str, response: str,
                   mind_data: dict) -> Optional[str]:
    if mode == "append_fix":
        return _append_fix_message(response, user_id)

    if mode == "over_compensate":
        return _over_compensate_message(response, mind_data, user_id)

    if mode == "silent_regret":
        _silent_regret_effect(user_id, mind_data)
        return None

    return None


def _append_fix_message(original: str, user_id: str = "") -> str:
    fixes = [
        "不是……刚才说的不太对",
        "重新说",
        "我刚刚的意思不是那样",
        "算了收回刚才那句话",
        "……我好像没说清楚",
        "不是那个意思",
        "重新想了一下……其实不是那样的",
    ]
    if user_id:
        last = _last_regret_text.get(user_id, "")
        available = [f for f in fixes if f != last]
        if not available:
            available = fixes
        chosen = random.choice(available)
        _last_regret_text[user_id] = chosen
        prefix = chosen
    else:
        prefix = random.choice(fixes)
    # 追加到原始回复后面，保留完整回答
    original_trimmed = original[:150]
    return f"{original_trimmed}\n\n（{prefix}）"


def _over_compensate_message(original: str, mind_data: dict, user_id: str = "") -> str:
    softeners = [
        "……我刚刚是不是说太重了",
        "不是，我其实就是想说",
        "你当我刚才胡说八道吧",
        "其实不是那个意思……我是想说",
    ]
    if user_id:
        last = _last_regret_text.get(user_id, "")
        available = [s for s in softeners if s != last]
        if not available:
            available = softeners
        chosen = random.choice(available)
        _last_regret_text[user_id] = chosen
        prefix = chosen
    else:
        prefix = random.choice(softeners)
    # 追加到原始回复后面，保留完整回答
    original_trimmed = original[:150]
    return f"{prefix}\n{original_trimmed}"


def _silent_regret_effect(user_id: str, mind_data: dict):
    try:
        from engine import mind as mind_module
        adjustments = {
            "misery": 0.008,
            "restraint": 0.010,
            "emotional_volatility": 0.005,
        }
        mind_module.adjust_mind_dimensions(user_id, adjustments, impact=0.3)
    except Exception:
        pass


def apply_regret_learning(user_id: str, regret_text: str = ""):
    now = time.time()
    key = user_id
    if key not in _regret_log:
        _regret_log[key] = []
    if key not in _regret_texts:
        _regret_texts[key] = []

    _regret_log[key] = [t for t in _regret_log[key] if now - t < 86400]
    _regret_log[key].append(now)

    if regret_text:
        _regret_texts[key].append({"text": regret_text, "timestamp": now})
        _regret_texts[key] = [r for r in _regret_texts[key] if now - r["timestamp"] < 86400 * 3]

    recent_count = len(_regret_log[key])
    if recent_count >= 3:
        try:
            from engine import mind as mind_module
            mind_module.adjust_mind_dimensions(
                user_id,
                {"restraint": 0.003 * min(recent_count, 10)},
                impact=0.15,
            )
        except Exception:
            pass


def should_show_regret(user_id: str) -> bool:
    key = user_id
    if key not in _regret_log:
        return False
    now = time.time()
    recent = [t for t in _regret_log[key] if now - t < REGRET_COOLDOWN]
    return len(recent) == 0


def get_recent_regret_text(user_id: str) -> str:
    """获取最近一次遗憾的文本描述,用于注入thinking prompt"""
    key = user_id
    if key not in _regret_texts or not _regret_texts[key]:
        return ""
    last = _regret_texts[key][-1]
    now = time.time()
    if now - last["timestamp"] > 86400 * 3:
        return ""
    return f"之前说错了一句话,到现在还没释怀——{last['text']}"
