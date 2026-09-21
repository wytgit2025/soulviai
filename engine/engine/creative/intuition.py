# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""直觉系统 — Intuition Engine
=====================================
基于历史模式匹配的快速判断通道，跳过LLM直接输出倾向。
像真人的"第一反应"——不经过深度思考，凭感觉做出判断。

机制:
  1. TF-IDF语义匹配当前消息 vs 历史对话模式
  2. 匹配到的历史模式 → 提取情绪/态度标签 → 生成直觉
  3. 直觉输出: {"gut_feeling": "感觉ta在隐瞒什么", "confidence": 0.3}
  4. 不替代LLM理解，而是作为补充前置

直觉类型:
  - ta在敷衍 (历史敷衍消息模式匹配)
  - ta好像不开心 (用词模式+情绪词密度)
  - 感觉ta想说什么 (开放式语句)
  - 不对劲 (多维度异常)
"""
import math
from typing import Dict, Optional

GUT_PATTERNS = {
    "ta在敷衍": {
        "keywords": ["嗯", "哦", "行吧", "好吧", "随便", "算了", "知道了"],
        "min_matches": 2,
        "base_confidence": 0.35,
    },
    "ta好像不开心": {
        "keywords": ["没事", "还好", "还行吧", "没什么", "不用了", "算了算了"],
        "min_matches": 1,
        "base_confidence": 0.4,
    },
    "ta想说什么但没说出来": {
        "patterns": ["其实", "算了不说了", "不知道怎么说", "也没什么", "……"],
        "min_matches": 1,
        "base_confidence": 0.3,
    },
    "ta在依赖我": {
        "keywords": ["想你", "在干嘛", "陪我", "聊聊", "听听", "你在吗"],
        "min_matches": 1,
        "base_confidence": 0.45,
    },
    "ta需要空间": {
        "keywords": ["我想静静", "最近忙", "压力大", "累", "不想聊"],
        "min_matches": 1,
        "base_confidence": 0.4,
    },
    "ta不太对劲": {
        "signals": ["情绪反转", "语气突变", "回复变短"],
        "min_matches": 2,
        "base_confidence": 0.25,
    },
}

# 消息强度特征
def _message_features(text: str) -> Dict[str, float]:
    text = text.strip()
    length = len(text)
    exclamation = text.count("!") + text.count("！")
    question = text.count("?") + text.count("？")
    ellipsis = text.count("...") + text.count("……")
    repetition = sum(1 for i in range(len(text)-1) if text[i] == text[i+1] and text[i] not in " 　")

    return {
        "length": min(1.0, length / 50),
        "is_short": 1.0 if length < 6 else max(0, 1.0 - length / 10),
        "exclamation": min(1.0, exclamation / 3),
        "question": min(1.0, question / 3),
        "ellipsis": min(1.0, ellipsis / 2),
        "hesitation": 1.0 if ellipsis > 1 or "…" in text else 0.3 if ellipsis > 0 else 0,
        "repetition": min(1.0, repetition / 5),
    }


def _keyword_match(text: str, keywords: list) -> int:
    return sum(1 for kw in keywords if kw in text)


def sense(user_message: str, recent_context: list = None) -> Dict:
    """对用户消息做直觉判断。
    返回 {"gut_feeling": str, "confidence": float} 或 {}
    """
    features = _message_features(user_message)
    best = None
    best_score = 0

    for intuition, pattern in GUT_PATTERNS.items():
        score = 0
        if "keywords" in pattern:
            matches = _keyword_match(user_message, pattern["keywords"])
            if matches >= pattern.get("min_matches", 1):
                score += matches * 0.25
        if "patterns" in pattern:
            matches = sum(1 for p in pattern["patterns"] if p in user_message)
            if matches >= pattern.get("min_matches", 1):
                score += matches * 0.2
        if "signals" in pattern:
            signals = 0
            if "情绪反转" in pattern["signals"] and features["ellipsis"] > 0.5:
                signals += 1
            if "回复变短" in pattern["signals"] and features["is_short"] > 0.7:
                signals += 1
            if "语气突变" in pattern["signals"] and features["exclamation"] > 0.3:
                signals += 1
            if signals >= pattern.get("min_matches", 1):
                score += signals * 0.2

        if score > best_score:
            best_score = score
            confidence = min(0.7, pattern["base_confidence"] + score)
            best = (intuition, round(confidence, 3))

    if best and best[1] > 0.3:
        return {"gut_feeling": best[0], "confidence": best[1]}
    return {}


def inject_intuition_into_comprehension(comprehension: dict, gut: dict) -> dict:
    """将直觉注入理解层结果，增强LLM理解"""
    if not gut:
        return comprehension
    if not comprehension.get("intuition"):
        comprehension["intuition"] = gut.get("gut_feeling", "")
    if comprehension.get("confidence", 0) < 0.5 and gut.get("confidence", 0) > 0.4:
        comprehension["intuition_override"] = True
    return comprehension
