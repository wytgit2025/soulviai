# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""行为模式沙盒（Behavior Pattern Sandbox）
=============================================
自创行为模式 → 试用评估 → 淘汰/转正

核心流程:
  1. 每晚从昨天对话中挖掘新模式（LLM 从 user_feedback 和 context 中提取）
  2. 新模式放入沙盒，设置初始置信度
  3. 每次对话时，沙盒中模式参与行为决策投票
  4. 根据用户正/负反馈调整置信度
  5. 置信度超阈值 → 转正（固化到 behavior_decider）
  6. 置信度低阈值 → 淘汰
"""
import json
import os
import random
import time
from typing import Dict, List, Optional, Tuple

# ── 沙盒存储 ──
_sandbox: Dict[str, List[dict]] = {}  # user_id → [pattern, ...]
# 相对 cwd（core.paths.chdir_home() 切到数据家目录），不要用 __file__ 拼
_SANDBOX_FILE = os.path.join("data", "behavior_sandbox.json")
_MAX_PATTERNS_PER_USER = 8


# ══════════════════════════════════════════════════════════════════════
# 内部工具
# ══════════════════════════════════════════════════════════════════════

def _load_sandbox():
    """从文件加载沙盒数据"""
    global _sandbox
    try:
        if os.path.exists(_SANDBOX_FILE):
            with open(_SANDBOX_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                _sandbox = data if isinstance(data, dict) else {}
        else:
            _sandbox = {}
    except Exception:
        _sandbox = {}


def _save_sandbox():
    """保存沙盒数据到文件"""
    try:
        os.makedirs(os.path.dirname(_SANDBOX_FILE), exist_ok=True)
        with open(_SANDBOX_FILE, "w", encoding="utf-8") as f:
            json.dump(_sandbox, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
# 公开 API
# ══════════════════════════════════════════════════════════════════════

def ensure_loaded():
    """确保沙盒数据已加载（由 SoulEngine 初始化时调用）"""
    _load_sandbox()


def get_sandbox_patterns(user_id: str) -> List[dict]:
    """获取用户的沙盒模式列表"""
    return _sandbox.get(user_id, [])


def set_sandbox_patterns(user_id: str, patterns: List[dict]):
    """设置用户的沙盒模式列表"""
    _sandbox[user_id] = patterns[-_MAX_PATTERNS_PER_USER:]
    _save_sandbox()


def create_new_patterns(user_id: str, recent_contexts: List[str],
                         user_feedback: float = 0.0) -> List[dict]:
    """LLM 从最近对话中挖掘新模式（夜间复盘时调用）"""
    _load_sandbox()
    if user_id not in _sandbox:
        _sandbox[user_id] = []

    existing_count = len(_sandbox[user_id])
    if existing_count >= _MAX_PATTERNS_PER_USER:
        return []

    max_new = max(1, _MAX_PATTERNS_PER_USER - existing_count)
    contexts_str = "\n".join(f"- {c[:60]}" for c in recent_contexts[-10:])

    try:
        from core import ai as ai_module

        prompt = (
            f"根据以下对话记录，挖掘用户希望的行为模式。"
            f"模式 = 在特定场景下，对方希望我表现出的某种态度/语气。"
            f"返回JSON数组，每项格式: {{'name':'模式名(2-4字)','condition':'触发条件','behavior_offset':{{'维度名':调整量}},'why':'为什么这个模式有用'}}\n"
            f"可用维度: approach,verbosity,warmth,playfulness,seriousness,honesty,tsundere,sulkiness,initiative,clinginess,emotional_display\n"
            f"调整量范围: -0.15 到 0.15\n"
            f"最近对话:\n{contexts_str[:300]}"
        )
        result = ai_module.background_chat(prompt, temperature=0.7, max_tokens=300)
        if not result:
            return []

        import re
        cleaned = re.sub(r'```(?:json)?\s*', '', result).strip().rstrip('`').strip()
        start = cleaned.find('[')
        end = cleaned.rfind(']')
        if start == -1 or end == -1:
            return []

        new_patterns = json.loads(cleaned[start:end+1])
        if not isinstance(new_patterns, list):
            return []

        created = []
        for p in new_patterns[:max_new]:
            if not isinstance(p, dict) or "name" not in p or "behavior_offset" not in p:
                continue
            bo = p["behavior_offset"]
            if not isinstance(bo, dict):
                continue
            bo = {k: max(-0.15, min(0.15, float(v))) for k, v in bo.items()}
            if not bo:
                continue

            pattern = {
                "name": p["name"][:6],
                "condition": p.get("condition", "")[:80],
                "why": p.get("why", "")[:60],
                "behavior_offset": bo,
                "confidence": 0.3,
                "trial_count": 0,
                "hit_count": 0,
                "feedback_sum": 0.0,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            _sandbox[user_id].append(pattern)
            created.append(pattern)

        # 不超出上限
        if len(_sandbox[user_id]) > _MAX_PATTERNS_PER_USER:
            _sandbox[user_id] = _sandbox[user_id][-_MAX_PATTERNS_PER_USER:]

        _save_sandbox()
        return created
    except Exception:
        return []


def apply_sandbox_to_behavior(base_vector: Dict[str, float],
                               user_id: str, context: str = "") -> Dict[str, float]:
    """沙盒模式参与行为决策——对匹配的模式进行投票加权

    返回值: 应用沙盒偏移后的行为向量
    """
    patterns = _sandbox.get(user_id, [])
    if not patterns:
        return base_vector

    result = dict(base_vector)

    for pattern in patterns:
        confidence = pattern.get("confidence", 0.3)
        if confidence < 0.2:
            continue

        condition = pattern.get("condition", "")
        if condition and context and condition not in context:
            # 上下文不匹配则降低偏移幅度
            multiplier = 0.3
        else:
            multiplier = min(1.0, confidence * 2.0)

        offset = pattern.get("behavior_offset", {})
        for dim, delta in offset.items():
            if dim in result:
                result[dim] = max(0.0, min(1.0, result[dim] + delta * multiplier))

    return result


def record_feedback(user_id: str, pattern_name: str,
                     feedback: float, context: str = ""):
    """记录用户对某个模式的反馈（正/负）

    Args:
        user_id: 用户ID
        pattern_name: 模式名称
        feedback: -1.0（差）到 1.0（好）
        context: 当时的对话上下文
    """
    patterns = _sandbox.get(user_id, [])
    for p in patterns:
        if p["name"] == pattern_name:
            p["trial_count"] = p.get("trial_count", 0) + 1
            p["feedback_sum"] = p.get("feedback_sum", 0.0) + feedback

            trial_count = p["trial_count"]
            avg_feedback = p["feedback_sum"] / max(1, trial_count)

            # 置信度更新：新反馈占 30%，历史平均占 70%
            if trial_count == 1:
                p["confidence"] = max(0.05, min(0.95, 0.3 + feedback * 0.4))
            else:
                old_conf = p.get("confidence", 0.3)
                p["confidence"] = old_conf * 0.7 + (0.5 + avg_feedback * 0.4) * 0.3
                p["confidence"] = max(0.05, min(0.95, p["confidence"]))

            if feedback > 0:
                p["hit_count"] = p.get("hit_count", 0) + 1

            _save_sandbox()
            return

    # 没找到同名模式 — 置信度高的模式可能触发了反馈
    if feedback > 0.5 and patterns:
        best = max(patterns, key=lambda p: p.get("confidence", 0))
        if best["confidence"] > 0.5:
            best["trial_count"] = best.get("trial_count", 0) + 1
            best["hit_count"] = best.get("hit_count", 0) + 1
            best["feedback_sum"] = best.get("feedback_sum", 0.0) + feedback * 0.5
            _save_sandbox()


def promote_pattern(user_id: str, pattern_name: str) -> bool:
    """将沙盒模式转正——固化到 behavior_decider 中

    Returns: 是否成功转正
    """
    patterns = _sandbox.get(user_id, [])
    target = None
    for p in patterns:
        if p["name"] == pattern_name:
            target = p
            break

    if not target or target.get("confidence", 0) < 0.65:
        return False

    try:
        from engine.behavior import behavior_decider as bd_module
        # 固化到 projection_learning 的已知模式
        from engine.behavior import projection_learning as pl_module
        pl_module.record_learned_pattern(
            user_id=user_id,
            pattern_name=target["name"],
            behavior_offset=target["behavior_offset"],
            condition=target["condition"],
        )
        # 从沙盒移除
        _sandbox[user_id] = [p for p in patterns if p["name"] != pattern_name]
        _save_sandbox()
        print(f"[行为沙盒] 模式'{pattern_name}'已转正固化!")
        return True
    except Exception:
        return False


def eliminate_pattern(user_id: str, pattern_name: str) -> bool:
    """淘汰低置信度模式"""
    patterns = _sandbox.get(user_id, [])
    before = len(patterns)
    _sandbox[user_id] = [p for p in patterns if p["name"] != pattern_name]
    if len(_sandbox[user_id]) < before:
        _save_sandbox()
        return True
    return False


def night_sandbox_review(user_id: str, recent_contexts: List[str],
                          recent_feedbacks: List[float] = None):
    """夜间沙盒复盘——创建新模式+淘汰低效模式+尝试转正

    在 life.py 的 night_review 中调用
    """
    _load_sandbox()
    if user_id not in _sandbox:
        _sandbox[user_id] = []

    # 1. 淘汰低置信度模式
    eliminated = []
    remaining = []
    for p in _sandbox[user_id]:
        trial_count = p.get("trial_count", 0)
        confidence = p.get("confidence", 0.3)
        if trial_count >= 3 and confidence < 0.2:
            eliminated.append(p["name"])
        else:
            remaining.append(p)
    _sandbox[user_id] = remaining

    # 2. 尝试转正高置信度模式
    promoted = []
    for p in _sandbox[user_id]:
        trial_count = p.get("trial_count", 0)
        confidence = p.get("confidence", 0.3)
        if trial_count >= 5 and confidence >= 0.65:
            if promote_pattern(user_id, p["name"]):
                promoted.append(p["name"])

    # 3. 创建新候选模式
    created = []
    if len(_sandbox[user_id]) < _MAX_PATTERNS_PER_USER - 1:
        created = create_new_patterns(user_id, recent_contexts)

    if eliminated:
        print(f"   🧪 沙盒淘汰: {', '.join(eliminated)}")
    if promoted:
        print(f"   🏆 沙盒转正: {', '.join(promoted)}")
    if created:
        print(f"   🆕 沙盒新模式: {', '.join(c['name'] for c in created)}")

    _save_sandbox()
    return {"eliminated": eliminated, "promoted": promoted, "created": created}


def get_sandbox_summary(user_id: str) -> str:
    """获取沙盒状态摘要（供 soulviai.py 状态显示）"""
    patterns = _sandbox.get(user_id, [])
    if not patterns:
        return ""
    lines = []
    for p in patterns:
        name = p.get("name", "?")
        conf = p.get("confidence", 0)
        trials = p.get("trial_count", 0)
        lines.append(f"{name}({conf:.0%}/{trials}次)")
    return "沙盒: " + ", ".join(lines)
