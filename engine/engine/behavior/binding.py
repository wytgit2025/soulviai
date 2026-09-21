# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""意识绑定引擎 — Binding Engine
===============================================
将48个模块各自的变化绑定为一个统一的"体验"。

当多个模块同时产生显著变化时:
  不是"mind变了+body变了+neurochem变了"三个独立事件
  而是在内部生成一个"体验令牌"——A simultaneous experience。

核心机制:
  1. 体验令牌: 跨模块变化的统一表示
  2. 体验命名: 给反复出现的体验模式贴上标签
  3. 相似性网络: 体验之间的关联映射
"""
import time
import json
import hashlib
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

EXPERIENCE_FILE = "data/json/experiences.json"

_experience_tokens: Dict[str, List[Dict]] = {}
_named_patterns: Dict[str, Dict[str, Dict]] = {}
MAX_TOKENS = 200


def load_engine_config():
    global _experience_tokens, _named_patterns
    _experience_tokens = {}
    _named_patterns = {}
    try:
        import os
        if os.path.exists(EXPERIENCE_FILE):
            with open(EXPERIENCE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                _experience_tokens = data.get("tokens", {})
                _named_patterns = data.get("patterns", {})
    except Exception:
        pass


def _save():
    try:
        with open(EXPERIENCE_FILE, "w", encoding="utf-8") as f:
            json.dump({"tokens": _experience_tokens, "patterns": _named_patterns},
                      f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def bind_experience(
    user_id: str,
    trigger: str,
    mind_changes: Dict[str, float] = None,
    body_sensation: str = "",
    neurochem_changes: Dict[str, float] = None,
    memory_surge: str = "",
    self_doubt_change: float = 0.0,
    regret_info: str = "",
    self_narrative: str = "",
    comprehension: dict = None,
    intention: str = "",
) -> Optional[Dict]:
    """将多个模块的同步变化绑定为一个统一体验令牌。
    至少需要2个模块有显著变化才生成令牌。
    """
    significant_changes = 0
    if mind_changes and len(mind_changes) >= 1:
        significant_changes += 1
    if body_sensation and body_sensation not in ("轻松舒适", ""):
        significant_changes += 1
    if neurochem_changes and len(neurochem_changes) >= 1:
        significant_changes += 1
    if memory_surge:
        significant_changes += 1
    if abs(self_doubt_change) > 0.01:
        significant_changes += 1
    if regret_info:
        significant_changes += 1

    if significant_changes < 2:
        return None

    token_id = _generate_token_id(user_id, trigger)

    token = {
        "id": token_id,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "trigger": trigger[:150],
        "mind_changes": mind_changes or {},
        "body_sensation": body_sensation,
        "neurochem_changes": neurochem_changes or {},
        "memory_surge": memory_surge[:80],
        "self_doubt_change": round(self_doubt_change, 4),
        "regret_info": regret_info[:80],
        "self_narrative": self_narrative[:200],
        "intention": intention[:80],
        "comprehension_intent": comprehension.get("intent", "") if comprehension else "",
        "comprehension_emotion": comprehension.get("true_emotion", "") if comprehension else "",
    }

    if user_id not in _experience_tokens:
        _experience_tokens[user_id] = []
    _experience_tokens[user_id].append(token)

    if len(_experience_tokens[user_id]) > MAX_TOKENS:
        _experience_tokens[user_id] = _experience_tokens[user_id][-MAX_TOKENS:]

    _detect_named_pattern(user_id, token)
    _save()

    return token


def _generate_token_id(user_id: str, trigger: str) -> str:
    raw = f"{user_id}_{trigger}_{time.time()}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _detect_named_pattern(user_id: str, token: Dict):
    body = token.get("body_sensation", "")
    comp_intent = token.get("comprehension_intent", "")
    comp_emotion = token.get("comprehension_emotion", "")
    trigger = token.get("trigger", "")

    patterns = _named_patterns.get(user_id, {})

    for name, pattern in patterns.items():
        conditions = pattern.get("conditions", {})
        if _match_pattern(token, conditions):
            pattern["count"] = pattern.get("count", 0) + 1
            pattern["strength"] = min(0.95, pattern.get("strength", 0.3) + 0.02)
            pattern["last_triggered"] = token["timestamp"]
            _save()
            return

    new_pattern = _check_new_pattern(token)
    if new_pattern:
        name = new_pattern["name"]
        if user_id not in _named_patterns:
            _named_patterns[user_id] = {}
        _named_patterns[user_id][name] = new_pattern
        _save()


def _check_new_pattern(token: Dict) -> Optional[Dict]:
    body = token.get("body_sensation", "")
    comp_intent = token.get("comprehension_intent", "")
    comp_emotion = token.get("comprehension_emotion", "")

    if body == "胸闷压抑" and comp_intent in ("敷衍", "冷淡"):
        return {
            "name": "被刺感",
            "description": "被敷衍/冷淡对待时的身体和情绪反应——胸口闷，心里刺一下",
            "conditions": {"body_sensation": "胸闷压抑", "intent_in": ["敷衍", "冷淡"]},
            "count": 1,
            "strength": 0.4,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    if body == "安静内收" and comp_intent == "需要空间":
        return {
            "name": "缩回去",
            "description": "被推开时的反应——安静地把自己缩起来，不再主动",
            "conditions": {"body_sensation": "安静内收", "intent_in": ["需要空间"]},
            "count": 1,
            "strength": 0.35,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    if comp_intent == "撒娇" and comp_emotion in ("期待", "温柔"):
        return {
            "name": "被需要感",
            "description": "被撒娇/被期待时的温暖——觉得自己是重要的",
            "conditions": {"intent_in": ["撒娇"], "emotion_in": ["期待", "温柔"]},
            "count": 1,
            "strength": 0.35,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    return None


def _match_pattern(token: Dict, conditions: Dict) -> bool:
    if "body_sensation" in conditions:
        if token.get("body_sensation", "") != conditions["body_sensation"]:
            return False
    if "intent_in" in conditions:
        if token.get("comprehension_intent", "") not in conditions["intent_in"]:
            return False
    if "emotion_in" in conditions:
        if token.get("comprehension_emotion", "") not in conditions["emotion_in"]:
            return False
    return True


def find_similar_experiences(user_id: str, current_token: Dict,
                              max_results: int = 3) -> List[Dict]:
    tokens = _experience_tokens.get(user_id, [])
    if len(tokens) < 2:
        return []

    scored = []
    cur_body = current_token.get("body_sensation", "")
    cur_intent = current_token.get("comprehension_intent", "")
    cur_emotion = current_token.get("comprehension_emotion", "")

    for t in tokens[-50:]:
        if t.get("id") == current_token.get("id"):
            continue
        score = 0.0
        if t.get("body_sensation", "") == cur_body and cur_body:
            score += 0.35
        if t.get("comprehension_intent", "") == cur_intent and cur_intent:
            score += 0.30
        if t.get("comprehension_emotion", "") == cur_emotion and cur_emotion:
            score += 0.25

        if score > 0.3:
            scored.append((score, t))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in scored[:max_results]]


def get_experience_context(user_id: str, current_trigger: str = "",
                           max_chars: int = 200) -> str:
    tokens = _experience_tokens.get(user_id, [])
    if not tokens:
        return ""

    patterns = _named_patterns.get(user_id, {})
    active_patterns = [(n, p) for n, p in patterns.items()
                       if p.get("strength", 0) > 0.3 and p.get("count", 0) >= 2]

    lines = []
    total = 0

    if active_patterns:
        lines.append("【你反复经历的体验模式】")
        for name, p in sorted(active_patterns, key=lambda x: x[1].get("strength", 0), reverse=True)[:3]:
            line = f"· {name}: {p['description'][:50]} (已确认{p.get('count',0)}次)"
            if total + len(line) > max_chars:
                break
            lines.append(line)
            total += len(line)

    recent = tokens[-1] if tokens else None
    if recent and current_trigger:
        similar = find_similar_experiences(user_id, recent)
        if similar:
            if not lines:
                lines.append("【体验关联】")
            for s in similar[:2]:
                line = f"· 类似的体验: {s.get('trigger','')[:40]}"
                if total + len(line) > max_chars:
                    break
                lines.append(line)
                total += len(line)

    if not lines:
        return ""
    return "\n".join(lines)


def get_named_pattern_summary(user_id: str) -> str:
    patterns = _named_patterns.get(user_id, {})
    if not patterns:
        return ""
    active = [(n, p) for n, p in patterns.items()
              if p.get("strength", 0) > 0.3 and p.get("count", 0) >= 2]
    if not active:
        return ""

    names = [f"'{n}'({p.get('count',0)}次)" for n, p in active[:4]]
    return f"你认识自己的体验模式: {', '.join(names)}"


# ═══════════════════════════════════════════════════════
# 经历→行为参数学习固化
# ═══════════════════════════════════════════════════════

_LEARNING_FILE = "data/json/learning_weights.json"
_learning_weights: Dict[str, Dict[str, float]] = {}
_behavior_dim_ranges = {
    "approach": (-0.3, 0.3), "warmth": (-0.3, 0.3), "verbosity": (-0.2, 0.2),
    "honesty": (-0.25, 0.25), "initiative": (-0.3, 0.3), "clinginess": (-0.2, 0.2),
    "emotional_display": (-0.2, 0.2), "tsundere": (-0.2, 0.2),
    "playfulness": (-0.2, 0.2), "sulkiness": (-0.15, 0.15),
    "seriousness": (-0.2, 0.2), "pace": (-0.15, 0.15),
}


def load_learning_weights():
    global _learning_weights
    try:
        if os.path.exists(_LEARNING_FILE):
            with open(_LEARNING_FILE, "r", encoding="utf-8") as f:
                _learning_weights = json.load(f)
    except Exception:
        _learning_weights = {}


def _save_learning_weights():
    try:
        with open(_LEARNING_FILE, "w", encoding="utf-8") as f:
            json.dump(_learning_weights, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def consolidate_learning(user_id: str) -> Dict[str, float]:
    """扫描体验令牌，将反复出现的模式固化为行为参数偏移。
    返回 {行为维度: 偏移量} 映射，直接注入 behavior_decider 的投影覆盖。
    """
    tokens = _experience_tokens.get(user_id, [])
    if not tokens or len(tokens) < 5:
        return {}

    recent = tokens[-40:]

    cold_count = 0
    warm_count = 0
    reject_count = 0
    accept_count = 0
    push_count = 0

    for t in recent:
        intent = t.get("comprehension_intent", "")
        emotion = t.get("comprehension_emotion", "")
        body = t.get("body_sensation", "")

        if intent in ("敷衍", "冷淡", "回避"):
            cold_count += 1
        if intent in ("撒娇", "温暖", "关心"):
            warm_count += 1
        if intent in ("拒绝", "需要空间", "生气"):
            reject_count += 1
        if intent in ("接纳", "思念", "依赖") or emotion in ("期待", "温柔"):
            accept_count += 1
        if body in ("紧绷不安", "胸闷压抑"):
            push_count += 1

    total = len(recent)
    adjustments = {}

    cold_ratio = cold_count / total if total > 0 else 0
    warm_ratio = warm_count / total if total > 0 else 0
    reject_ratio = reject_count / total if total > 0 else 0
    accept_ratio = accept_count / total if total > 0 else 0
    push_ratio = push_count / total if total > 0 else 0

    if cold_ratio > 0.25:
        adjustments["approach"] = -cold_ratio * 0.15
        adjustments["warmth"] = -cold_ratio * 0.12
        adjustments["initiative"] = -cold_ratio * 0.18
        adjustments["emotional_display"] = -cold_ratio * 0.08

    if warm_ratio > 0.25:
        adjustments["warmth"] = min(0.2, (adjustments.get("warmth", 0) + warm_ratio * 0.10))
        adjustments["emotional_display"] = min(0.15, (adjustments.get("emotional_display", 0) + warm_ratio * 0.06))
        adjustments["approach"] = min(0.1, (adjustments.get("approach", 0) + warm_ratio * 0.05))

    if reject_ratio > 0.2:
        adjustments["clinginess"] = -reject_ratio * 0.12
        adjustments["initiative"] = max(-0.3, (adjustments.get("initiative", 0) - reject_ratio * 0.10))
        adjustments["sulkiness"] = min(0.15, reject_ratio * 0.12)

    if accept_ratio > 0.3:
        adjustments["trust"] = min(0.2, accept_ratio * 0.08)
        adjustments["emotional_display"] = min(0.15, (adjustments.get("emotional_display", 0) + accept_ratio * 0.05))

    if push_ratio > 0.2:
        adjustments["pace"] = -push_ratio * 0.05
        adjustments["seriousness"] = min(0.1, push_ratio * 0.06)

    for k in list(adjustments.keys()):
        lo, hi = _behavior_dim_ranges.get(k, (-0.3, 0.3))
        adjustments[k] = round(max(lo, min(hi, adjustments[k])), 4)

    if adjustments:
        user_weights = _learning_weights.get(user_id, {})
        for k, v in adjustments.items():
            lo, hi = _behavior_dim_ranges.get(k, (-0.3, 0.3))
            existing = user_weights.get(k, 0.0)
            user_weights[k] = round(max(lo, min(hi, existing + v * 0.3)), 4)
        _learning_weights[user_id] = user_weights
        _save_learning_weights()

    return adjustments


def get_learning_weights(user_id: str) -> Dict[str, float]:
    load_learning_weights()
    return _learning_weights.get(user_id, {})


def apply_learning_to_projection(user_id: str) -> Dict[str, Dict[str, float]]:
    """将学习固化的权重转换为 meta_cognition 的 behavior_projection 格式。
    返回: {"行为维度": {"learned_bias": 偏移量}}
    """
    weights = get_learning_weights(user_id)
    if not weights:
        return {}
    projection = {}
    for dim, bias in weights.items():
        projection[dim] = {"learned_bias": bias}
    return projection
