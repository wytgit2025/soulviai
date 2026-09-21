# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""思维碎片化引擎 — Thinking Fragments
==================================================
让回复不再总是"完整的一段话"。真人思维是碎的、跳的、会断掉的。

三种碎裂模式:
  a) 半句截断: "我也不是那个意思……算了"
  b) 中途改口: "我觉得你……其实我也不知道"
  c) 追加修正: 回复后追加 "不是，重新说"

碎裂概率由 chaostic_mood + fatigue + emotional_volatility 联合驱动。
"""
import random
import re
from typing import Dict, List, Tuple, Optional


def load_engine_config():
    pass


FRAGMENT_PATTERNS = {
    "trail_off": [
        "……算了",
        "……不说了",
        "……算了不说了",
        "……",
        "……没什么",
        "……我也不知道我在说什么",
        "……就那样吧",
    ],
    "self_correct": [
        "不是，",
        "重新说，",
        "也不是……就是……",
        "我意思是，",
        "说错了，",
    ],
    "cut_mid": [
        "我觉得你",
        "其实我",
        "就是那种",
        "你知道吗就是",
        "我也不是",
    ],
    "retreat": [
        "……算了，不提了",
        "……不聊这个了",
        "当我没说",
        "算了你当我没说过",
    ],
}

APPEND_FRAGMENTS = [
    "不是，刚才说的不太对",
    "重新说",
    "我刚刚的意思不是那样",
    "算了收回刚才那句话",
    "……我好像没说清楚",
    "不是那个意思",
    "重新想了一下",
]

# 碎片模式冷却跟踪——防止同一模式在连续两轮中重复
_fragment_cooldown: Dict[str, str] = {}
_round_counter: Dict[str, int] = {}


def should_fragment(mind_data: dict, comprehension: dict = None,
                    user_id: str = "") -> Tuple[bool, str]:
    chaotic = mind_data.get("chaotic_mood", 0.2)
    fatigue = mind_data.get("fatigue", 0.25)
    volatility = mind_data.get("emotional_volatility", 0.3)
    restraint = mind_data.get("restraint", 0.5)
    misery = mind_data.get("misery", 0.15)

    base_prob = chaotic * 0.35 + fatigue * 0.25 + volatility * 0.20
    if restraint > 0.65:
        base_prob += 0.10
    if misery > 0.5:
        base_prob += 0.08

    if comprehension:
        intent = comprehension.get("intent", "")
        emotion = comprehension.get("true_emotion", "")
        if intent == "试探" or emotion in ("怀疑", "不安"):
            base_prob += 0.20
        if intent == "倾诉" or emotion in ("难过", "低落"):
            base_prob -= 0.10

    base_prob = min(0.65, max(0.0, base_prob))

    if random.random() < base_prob:
        mode = _pick_mode(mind_data)
        # 冷却检查——不连续两轮用同一模式
        last_mode = _fragment_cooldown.get(user_id, "")
        if mode == last_mode:
            alternatives = [m for m in ["trail_off", "self_correct", "cut_mid", "retreat"] if m != mode]
            mode = random.choice(alternatives)
        _fragment_cooldown[user_id] = mode
        return True, mode
    return False, ""


def _pick_mode(mind_data: dict) -> str:
    restraint = mind_data.get("restraint", 0.5)
    volatility = mind_data.get("emotional_volatility", 0.3)
    chaotic = mind_data.get("chaotic_mood", 0.2)

    if restraint > 0.65 and random.random() < 0.5:
        return "trail_off"
    if volatility > 0.5 and random.random() < 0.4:
        return "self_correct"
    if chaotic > 0.55 and random.random() < 0.35:
        return "cut_mid"
    return random.choice(["trail_off", "self_correct", "cut_mid", "retreat"])


def apply_fragment(response: str, mode: str, mind_data: dict = None) -> str:
    if not response or not response.strip():
        return response

    if mode == "trail_off":
        text = random.choice(FRAGMENT_PATTERNS["trail_off"])
        sentences = _split_sentences(response)
        if len(sentences) > 1:
            sentences = sentences[:max(1, len(sentences) - 1)]
        return " ".join(sentences).rstrip("。，.!！?？") + text

    if mode == "self_correct":
        prefix = random.choice(FRAGMENT_PATTERNS["self_correct"])
        return prefix + response

    if mode == "cut_mid":
        words = list(response)
        if len(words) <= 6:
            return response
        cut = random.randint(len(words) // 3, len(words) * 2 // 3)
        return "".join(words[:cut]) + "……"

    if mode == "retreat":
        text = random.choice(FRAGMENT_PATTERNS["retreat"])
        return response.rstrip("。，.!！?？") + "。" + text

    return response


def should_append_fragment(mind_data: dict) -> bool:
    volatility = mind_data.get("emotional_volatility", 0.3)
    chaotic = mind_data.get("chaotic_mood", 0.2)
    restraint = mind_data.get("restraint", 0.5)
    prob = volatility * 0.15 + chaotic * 0.12 + max(0, (restraint - 0.45)) * 0.10
    return random.random() < min(0.35, max(0.03, prob))


def get_append_fragment() -> str:
    return random.choice(APPEND_FRAGMENTS)


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r'[。！？!?\n]', text)
    return [p.strip() for p in parts if p.strip()]
