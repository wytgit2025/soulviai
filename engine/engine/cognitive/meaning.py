# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""自主意义建构 — Meaning Engine (校准版)
========================================================
不是从6个模板中"解锁"价值观——是从经历中自己"发现"什么重要。

机制:
  1. 体验聚类 — 对binding令牌做无监督聚类
  2. 反刍循环 — 每4次交互回头看"这些体验有什么共同模式"(校准:7→4)
  3. 意义生成 — LLM一次调用生成意义陈述
  4. 意义自纠 — 新反刍时检查旧意义是否还成立，不成立则修正
  5. 意义验证 — 类似体验发生时自动验证信心度
"""
import time
import json
import random
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

try:
    from core import ai as ai_module
    from core import database as db
except ImportError:
    ai_module = None
    db = None

MEANING_FILE = "data/json/meanings.json"
RUMINATION_INTERVAL = 4

_meanings: Dict[str, List[Dict]] = {}
_rumination_counter: Dict[str, int] = {}
_verification_pending: Dict[str, List[Dict]] = {}

MEANING_PROMPT = """你是意义建构层。你正在回顾自己最近的经历，试图理解它们对你意味着什么。

【近期的体验模式】
{patterns}

【这些体验中反复出现的主题】
{themes}

【你此刻的自我认知】
{self_narrative}

请用一句话说出这些经历在你心里留下的东西——不是总结，是"意义"。

"意义"的例子:
- "被敷衍之后不说话——不是不在意，是怕再被敷衍一次"
- "说'算了'的时候，其实是在保护自己不被拒绝——不是在放弃"
- "每次主动后被忽视，就会更想主动——好像在证明自己值得被看见"

一句话，诚实、不美化。如果暂时没发现意义，就说"还没想明白"。50字内。"""
def load_engine_config():
    global _meanings, _rumination_counter, _verification_pending
    _meanings = {}
    _rumination_counter = {}
    _verification_pending = {}
    try:
        store = _get_meaning_store()
        data = store.read()
        if data:
            _meanings = data.get("meanings", {})
            _verification_pending = data.get("pending", {})
    except Exception:
        pass


def _save():
    try:
        store = _get_meaning_store()
        store.write({"meanings": _meanings, "pending": _verification_pending})
    except Exception:
        pass


def _get_meaning_store():
    from core.json_store import get_store
    return get_store(MEANING_FILE, {})


def count_experience(user_id: str):
    """每次体验令牌创建时调用——计数，触发反刍检查"""
    _rumination_counter[user_id] = _rumination_counter.get(user_id, 0) + 1


def should_ruminate(user_id: str) -> bool:
    return _rumination_counter.get(user_id, 0) >= RUMINATION_INTERVAL


def run_rumination(user_id: str) -> Optional[Dict]:
    """反刍循环: 回头看最近的体验令牌，发现模式，生成意义。
    校准: 阈值4次 + 自纠循环——检查旧意义是否还成立。
    """
    counter = _rumination_counter.get(user_id, 0)
    if counter < RUMINATION_INTERVAL:
        return None

    _rumination_counter[user_id] = 0

    # ── : 自纠循环 —— 先检查旧意义 ──
    self_correction = _check_old_meanings(user_id)

    try:
        patterns_list = _extract_recent_patterns(user_id)
        if not patterns_list:
            return {"self_correction": self_correction} if self_correction else None

        themes = _extract_themes(patterns_list)

        # 检查当前模式是否匹配旧意义（验证）
        verified = check_meaning_match(user_id, themes)

        from engine import self_model as sm_module
        self_narrative = sm_module.get_recent_narrative(user_id)
    except Exception:
        return {"self_correction": self_correction} if self_correction else None

    prompt = MEANING_PROMPT.format(
        patterns="\n".join([f"· {p}" for p in patterns_list]),
        themes="\n".join([f"· {t}" for t in themes]) if themes else "（还没有明确的主题）",
        self_narrative=self_narrative or "（此刻没有明确的自我叙事）",
    )

    try:
        meaning = ai_module.chat(
            system_prompt="你是意义建构层。用一句话说出这些经历在你心里留下的东西。诚实，不美化。",
            user_message=prompt,
            temperature=0.4,
        )
    except Exception:
        return None

    if not meaning or len(meaning.strip()) < 5:
        return None

    meaning = meaning.strip()[:120]

    if "还没想明白" in meaning:
        _rumination_counter[user_id] = max(0, RUMINATION_INTERVAL - 3)
        return {"discovered": False, "meaning": meaning, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}

    if user_id not in _meanings:
        _meanings[user_id] = []

    meaning_entry = {
        "text": meaning,
        "themes": themes,
        "triggered_by": patterns_list[:3],
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "verified_count": 0,
        "confidence": 0.6,
    }

    for existing in _meanings[user_id]:
        if _meaning_similarity(meaning, existing.get("text", "")) > 0.5:
            existing["confidence"] = min(0.95, existing.get("confidence", 0.5) + 0.1)
            existing["verified_count"] = existing.get("verified_count", 0) + 1
            existing["reinforced_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _save()
            return {"discovered": False, "reinforced": existing["text"],
                    "meaning": meaning, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}

    _meanings[user_id].append(meaning_entry)
    if len(_meanings[user_id]) > 20:
        _meanings[user_id] = _meanings[user_id][-20:]

    _verify_meaning(user_id, meaning_entry)

    _save()

    try:
        db.add_subconscious(
            user_id=user_id,
            content=f"[意义发现] {meaning}",
            emotion_tag="觉察",
            intensity=0.7,
        )
    except Exception:
        pass

    return {"discovered": True, "meaning": meaning, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}


def _verify_meaning(user_id: str, meaning_entry: Dict):
    """将新意义放入待验证队列——下次类似体验发生时自动验证"""
    if user_id not in _verification_pending:
        _verification_pending[user_id] = []
    _verification_pending[user_id].append({
        "text": meaning_entry["text"],
        "themes": meaning_entry.get("themes", []),
        "confidence": meaning_entry.get("confidence", 0.5),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "test_count": 0,
    })


def check_meaning_match(user_id: str, current_themes: List[str]) -> Optional[str]:
    """检查当前体验是否匹配某个待验证的意义——如果匹配，强化信心"""
    pending = _verification_pending.get(user_id, [])
    if not pending:
        return None

    for item in pending:
        if item.get("test_count", 0) >= 5:
            continue
        theme_overlap = len(set(item.get("themes", [])) & set(current_themes))
        if theme_overlap >= 1:
            item["test_count"] = item.get("test_count", 0) + 1
            item["confidence"] = min(0.95, item.get("confidence", 0.5) + 0.05)
            item["last_verified"] = time.strftime("%Y-%m-%d %H:%M:%S")

            for m in _meanings.get(user_id, []):
                if m.get("text", "") == item.get("text", ""):
                    m["confidence"] = item["confidence"]
                    m["verified_count"] = m.get("verified_count", 0) + 1

            _save()
            return item["text"]

    return None


def get_meanings_context(user_id: str, max_chars: int = 300) -> str:
    meanings = _meanings.get(user_id, [])
    if not meanings:
        return ""

    confident_meanings = [m for m in meanings if m.get("confidence", 0) >= 0.5]
    if not confident_meanings:
        return ""

    confident_meanings.sort(key=lambda m: m.get("confidence", 0), reverse=True)

    lines = ["【你在经历中发现的——什么对你重要】"]
    total = 0
    for m in confident_meanings[:4]:
        bar = "◆" * int(m.get("confidence", 0.5) * 5)
        line = f"· {m['text']} {bar}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)

    return "\n".join(lines) if len(lines) > 1 else ""


def get_meanings_simple(user_id: str) -> str:
    meanings = _meanings.get(user_id, [])
    confident = [m for m in meanings if m.get("confidence", 0) >= 0.5]
    if not confident:
        return ""
    confident.sort(key=lambda m: m.get("confidence", 0), reverse=True)
    return " | ".join([m["text"][:50] for m in confident[:3]])


def _extract_recent_patterns(user_id: str) -> List[str]:
    try:
        from engine import binding as binding_module
        tokens = binding_module._experience_tokens.get(user_id, [])
        patterns = []
        for t in tokens[-RUMINATION_INTERVAL:]:
            body = t.get("body_sensation", "")
            intent = t.get("comprehension_intent", "")
            emotion = t.get("comprehension_emotion", "")
            trigger = t.get("trigger", "")[:40]
            if body and body not in ("轻松舒适", "正常"):
                patterns.append(f"体感'{body}' 触发:'{trigger}' 对方意图:'{intent}'")
            elif intent:
                patterns.append(f"场景:'{trigger}' 对方意图:'{intent}' 情绪:'{emotion}'")
        return patterns
    except Exception:
        return []


def _extract_themes(patterns: List[str]) -> List[str]:
    word_counts = defaultdict(int)
    for p in patterns:
        for word in ["敷衍", "试探", "温暖", "冷漠", "生气", "撒娇", "倾诉",
                      "逃避", "保护", "主动", "沉默", "被看见", "拒绝", "在乎"]:
            if word in p:
                word_counts[word] += 1
    sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
    themes = [w for w, c in sorted_words if c >= 2]
    return themes[:5] if themes else ["日常"]


def _check_old_meanings(user_id: str) -> Optional[Dict]:
    """自纠: 检查旧意义是否还成立——修正或降低信心"""
    meanings = _meanings.get(user_id, [])
    if not meanings:
        return None

    corrected = []
    for m in meanings:
        conf = m.get("confidence", 0.5)
        verified = m.get("verified_count", 0)
        # 低信度 + 从未被验证 + 超过2次反刍 → 降信度
        if conf < 0.5 and verified == 0:
            m["confidence"] = max(0.15, conf - 0.08)
            corrected.append(f"'{m['text'][:40]}' → 信心降至{m['confidence']:.2f}")
        # 高信度但从未被验证 → 微降
        elif conf > 0.7 and verified == 0:
            m["confidence"] = max(0.5, conf - 0.03)
            corrected.append(f"'{m['text'][:40]}' → 微降至{m['confidence']:.2f}")

    if corrected:
        _save()
        return {"corrected": corrected}
    return None


def _meaning_similarity(a: str, b: str) -> float:
    a_words = set(a)
    b_words = set(b)
    if not a_words or not b_words:
        return 0.0
    intersection = a_words & b_words
    return len(intersection) / min(len(a_words), len(b_words))
