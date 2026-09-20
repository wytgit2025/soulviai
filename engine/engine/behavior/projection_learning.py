# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""行为投影学习引擎 — Behavior Projection Learning
==================================================
替代手动硬编码的 24维心智→12维行为 投影权重。

核心设计：
  1. 追踪每次交互的「心智状态 → 行为输出 → 用户反馈」三元组
  2. 从正反馈中学习哪些心智状态应该产生哪些行为
  3. 从负反馈中削弱错误的投影关联
  4. 提供运行时权重覆盖（叠加在手动权重之上）

数据驱动的工作流：
  每次对话:
    mind_state (24维) → behavior_decider → behavior_vector (12维) → LLM表达
    ↓                                                              ↓
    记录 (mind + behavior)                                   用户响应
                                                                ↓
                                                          正/负反馈信号
                                                                ↓
                                                          更新权重映射
"""
import json
import time
import random
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from core import database as db
from core.logging_utils import log_error

# ═══════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════

@dataclass
class ProjectionSample:
    """一次投影学习的训练样本"""
    user_id: str
    timestamp: float
    mind_state: Dict[str, float]       # 24维心智快照
    behavior_vector: Dict[str, float]   # 12维行为输出
    response_text: str                  # 实际生成的回复
    user_response: str                  # 用户的回复（反馈信号）
    sentiment: str                      # 用户情感 (positive/negative/neutral)
    outcome_score: float                # 综合评分 [-1, 1]


@dataclass
class ProjectionWeight:
    """一个心智维度→行为维度的投影权重"""
    mind_dim: str
    behavior_dim: str
    weight: float          # 当前权重 [-1, 1]
    confidence: float      # 置信度 [0, 1]
    sample_count: int      # 样本数
    positive_ratio: float  # 正反馈比例 [0, 1]


# ═══════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════

_CONFIG = {
    "enabled": True,
    "learning_rate": 0.05,           # 每次更新的学习率
    "min_samples_for_adjustment": 3, # 最少样本数才调整
    "confidence_decay": 0.95,        # 每次调整后的置信度衰减
    "max_weight_change_per_session": 0.08,  # 单次最大权重变化
    "history_size": 200,             # 保留最近样本数
    "auto_prune_interval": 50,       # 每N个样本自动修剪
}

# ── 学习到的投影权重覆盖 ──
_learned_weights: Dict[str, Dict[str, ProjectionWeight]] = {}
"""{mind_dim: {behavior_dim: ProjectionWeight}}"""

# ── 训练样本缓冲区 ──
_samples: Dict[str, List[ProjectionSample]] = {}
"""{user_id: [ProjectionSample, ...]}"""

# ── 持久化路径 ──
_WEIGHTS_FILE = "data/json/projection_weights.json"


def load_engine_config():
    """加载配置 + 恢复持久化的学习权重"""
    try:
        from core import config as cfg
        pc = cfg.get_section("projection_learning")
        if pc:
            _CONFIG.update({k: v for k, v in pc.items() if k in _CONFIG})
    except Exception:
        pass
    _load_weights()


def _load_weights():
    """从文件加载学习到的权重"""
    global _learned_weights
    try:
        store = _get_weight_store()
        raw = store.read()
        if not raw:
            _learned_weights = {}
            return
        for mind_dim, behavior_dict in raw.items():
            _learned_weights[mind_dim] = {}
            for bd, data in behavior_dict.items():
                _learned_weights[mind_dim][bd] = ProjectionWeight(
                    mind_dim=mind_dim,
                    behavior_dim=bd,
                    weight=data.get("weight", 0),
                    confidence=data.get("confidence", 0.5),
                    sample_count=data.get("sample_count", 0),
                    positive_ratio=data.get("positive_ratio", 0.5),
                )
        total = sum(len(bd) for bd in _learned_weights.values())
        if total > 0:
            print(f"[投影学习] 加载了 {total} 项历史权重")
    except Exception as _e:
        _learned_weights = {}


def _save_weights():
    """持久化学习到的权重"""
    try:
        serializable = {}
        for mind_dim, behavior_dict in _learned_weights.items():
            serializable[mind_dim] = {}
            for bd, pw in behavior_dict.items():
                serializable[mind_dim][bd] = {
                    "weight": round(pw.weight, 4),
                    "confidence": round(pw.confidence, 4),
                    "sample_count": pw.sample_count,
                    "positive_ratio": round(pw.positive_ratio, 4),
                }
        store = _get_weight_store()
        store.write(serializable)
    except Exception as _e:
        log_error("projection_learning.save_weights", str(_e))


def _get_weight_store():
    from core.json_store import get_store
    return get_store(_WEIGHTS_FILE, {})


# ═══════════════════════════════════════════════════════
# 样本记录
# ═══════════════════════════════════════════════════════

def record_interaction(
    user_id: str,
    mind_state: Dict[str, float],
    behavior_vector: Dict[str, float],
    response_text: str,
    user_response: str,
    sentiment: str = "neutral",
    outcome_score: float = 0.0,
):
    """记录一次完整的交互样本

    每次对话后调用，记录心智状态→行为→用户反馈的完整链路。
    """
    if not _CONFIG["enabled"]:
        return

    sample = ProjectionSample(
        user_id=user_id,
        timestamp=time.time(),
        mind_state=dict(mind_state),
        behavior_vector=dict(behavior_vector),
        response_text=response_text[:100],
        user_response=user_response[:100],
        sentiment=sentiment,
        outcome_score=outcome_score,
    )

    if user_id not in _samples:
        _samples[user_id] = []
    _samples[user_id].append(sample)

    # 修剪缓冲区
    max_size = _CONFIG["history_size"]
    if len(_samples[user_id]) > max_size:
        _samples[user_id] = _samples[user_id][-max_size:]

    # 如果用户反馈明显正/负，立即学习
    if abs(outcome_score) > 0.3:
        _learn_from_sample(sample)


def _detect_sentiment(user_response: str) -> Tuple[str, float]:
    """检测用户回复的情感倾向（快速启发式）"""
    positive_signals = [
        "喜欢", "开心", "好", "哈", "嘻嘻", "哈哈", "真好",
        "温暖", "感动", "贴心", "懂", "嗯嗯", "好呢",
        "乖", "抱抱", "贴贴", "可爱", "温柔",
    ]
    negative_signals = [
        "不", "没", "别", "烦", "无聊", "呵呵", "冷漠",
        "失望", "算了", "随便", "不想", "生气", "讨厌",
        "闭嘴", "走开", "滚",
    ]
    engagement_signals = ["？", "?", "？", "呢", "吗", "吧", "什么", "怎么"]

    pos_count = sum(1 for s in positive_signals if s in user_response)
    neg_count = sum(1 for s in negative_signals if s in user_response)
    eng_count = sum(1 for s in engagement_signals if s in user_response)

    if neg_count > pos_count and neg_count >= 2:
        return "negative", -0.5 - (neg_count * 0.1)
    if pos_count > neg_count and pos_count >= 2:
        return "positive", 0.5 + (pos_count * 0.1)
    if eng_count >= 2 and neg_count == 0:
        return "positive", 0.3
    if len(user_response.strip()) <= 2 and pos_count == 0:
        return "negative", -0.2

    return "neutral", 0.0


def learn_from_response(user_id: str, user_response: str):
    """根据用户回复自动学习

    在每次对话后调用，分析用户回复的情感倾向，更新投影权重。
    """
    if not _CONFIG["enabled"]:
        return

    samples = _samples.get(user_id, [])
    if not samples:
        return

    # 获取最近一次交互样本
    latest = samples[-1]
    if latest.outcome_score != 0.0:
        return  # 已经学习过

    sentiment, score = _detect_sentiment(user_response)
    latest.sentiment = sentiment
    latest.outcome_score = score
    latest.user_response = user_response[:100]

    if abs(score) > 0.3:
        _learn_from_sample(latest)

    # 自动修剪检查
    if len(samples) % _CONFIG["auto_prune_interval"] == 0:
        _prune_weights()


# ═══════════════════════════════════════════════════════
# 核心学习算法
# ═══════════════════════════════════════════════════════

def _learn_from_sample(sample: ProjectionSample):
    """从单一训练样本学习

    核心逻辑:
      1. 找出该次行为向量中权重最高的3个行为维度
      2. 找出该次心智状态中权重最高的3个心智维度
      3. 如果结果是正反馈 → 增强它们的投影关联
      4. 如果结果是负反馈 → 削弱它们的投影关联
    """
    if not sample.mind_state or not sample.behavior_vector:
        return

    lr = _CONFIG["learning_rate"]
    direction = 1.0 if sample.outcome_score > 0 else -1.0
    magnitude = abs(sample.outcome_score) * lr

    # 找出该次行为向量中最突出的3个维度
    top_behaviors = sorted(
        sample.behavior_vector.items(),
        key=lambda x: abs(x[1]),
        reverse=True,
    )[:3]

    # 找出该次心智状态中最突出的3个维度
    top_minds = sorted(
        sample.mind_state.items(),
        key=lambda x: abs(x[1] - 0.5),  # 偏离0.5越多越显著
        reverse=True,
    )[:5]

    for b_dim, b_val in top_behaviors:
        for m_dim, m_val in top_minds:
            # 计算心智维度偏离基线的程度
            deviation = m_val - 0.5

            # 只学习有意义的关联（心智偏离显著且行为偏离显著）
            if abs(deviation) < 0.05 or abs(b_val) < 0.05:
                continue

            # 获取或创建权重
            pw = _get_or_create_weight(m_dim, b_dim)

            # 计算权重变化:
            # - 正反馈: deviation 和 b_val 同号则增强，异号则削弱
            # - 负反馈: 反之
            weight_delta = direction * magnitude * deviation * abs(b_val)

            # 应用变化
            pw.weight += weight_delta
            pw.weight = max(-1.0, min(1.0, pw.weight))
            pw.sample_count += 1
            pw.confidence *= _CONFIG["confidence_decay"]
            pw.confidence = min(1.0, pw.confidence + 0.01)

            # 更新正反馈比例
            if sample.outcome_score > 0:
                pw.positive_ratio = (pw.positive_ratio * (pw.sample_count - 1) + 1) / pw.sample_count
            else:
                pw.positive_ratio = (pw.positive_ratio * (pw.sample_count - 1) + 0) / pw.sample_count

    _save_weights()


def _get_or_create_weight(mind_dim: str, behavior_dim: str) -> ProjectionWeight:
    """获取或创建投影权重"""
    if mind_dim not in _learned_weights:
        _learned_weights[mind_dim] = {}
    if behavior_dim not in _learned_weights[mind_dim]:
        _learned_weights[mind_dim][behavior_dim] = ProjectionWeight(
            mind_dim=mind_dim,
            behavior_dim=behavior_dim,
            weight=0.0,
            confidence=0.3,
            sample_count=0,
            positive_ratio=0.5,
        )
    return _learned_weights[mind_dim][behavior_dim]


# ═══════════════════════════════════════════════════════
# 权重检索
# ═══════════════════════════════════════════════════════

def get_learned_projection(mind_dim: str, behavior_dim: str) -> float:
    """获取学习到的投影权重

    Args:
        mind_dim: 心智维度名
        behavior_dim: 行为维度名

    Returns:
        学习到的权重值（叠加在手动权重之上）
    """
    if not _CONFIG["enabled"]:
        return 0.0

    pw = _learned_weights.get(mind_dim, {}).get(behavior_dim)
    if pw is None or pw.confidence < 0.2:
        return 0.0

    return pw.weight


def get_all_learned_projections() -> Dict[str, Dict[str, float]]:
    """获取所有学习到的投影权重

    Returns:
        {mind_dim: {behavior_dim: weight}}
    """
    result = {}
    for mind_dim, behavior_dict in _learned_weights.items():
        result[mind_dim] = {}
        for bd, pw in behavior_dict.items():
            if pw.confidence >= 0.2:
                result[mind_dim][bd] = round(pw.weight, 4)
    return result


def get_behavior_override_vector(
    mind_state: Dict[str, float],
) -> Dict[str, float]:
    """根据学习到的权重，计算行为向量的学习偏移

    叠加在 behavior_decider 的原始行为向量之上。

    Args:
        mind_state: 当前24维心智状态

    Returns:
        {behavior_dim: delta} — 行为向量的偏移量
    """
    if not _CONFIG["enabled"]:
        return {}

    overrides = defaultdict(float)

    for mind_dim, mind_val in mind_state.items():
        deviation = mind_val - 0.5
        if abs(deviation) < 0.05:
            continue

        behavior_dict = _learned_weights.get(mind_dim, {})
        for bd, pw in behavior_dict.items():
            if pw.confidence < 0.3 or abs(pw.weight) < 0.01:
                continue

            # 学习到的偏移 = 心智偏离 × 学习权重 × 置信度
            delta = deviation * pw.weight * pw.confidence
            overrides[bd] += delta

    # 大偏移剪裁
    result = {}
    for bd, delta in overrides.items():
        result[bd] = round(max(-0.15, min(0.15, delta)), 4)

    return result


# ═══════════════════════════════════════════════════════
# 权重维护
# ═══════════════════════════════════════════════════════

def _prune_weights():
    """修剪低置信度的权重，控制内存"""
    global _learned_weights
    to_delete = []

    for mind_dim, behavior_dict in _learned_weights.items():
        for bd, pw in list(behavior_dict.items()):
            if pw.sample_count < 3 and pw.confidence < 0.1:
                to_delete.append((mind_dim, bd))

    for md, bd in to_delete:
        del _learned_weights[md][bd]
        if not _learned_weights[md]:
            del _learned_weights[md]

    if to_delete:
        _save_weights()


def reset_learned_weights():
    """重置所有学习到的权重"""
    global _learned_weights
    _learned_weights = {}
    _save_weights()
    print("[投影学习] 已重置所有学习到的权重")


def get_learning_stats() -> Dict:
    """获取学习统计信息"""
    total_projections = sum(len(bd) for bd in _learned_weights.values())
    total_samples = sum(len(s) for s in _samples.values())
    high_confidence = sum(
        1 for bd in _learned_weights.values()
        for pw in bd.values()
        if pw.confidence > 0.5
    )
    return {
        "enabled": _CONFIG["enabled"],
        "total_projections": total_projections,
        "high_confidence_projections": high_confidence,
        "total_samples": total_samples,
        "active_users": len(_samples),
    }


def adjust_weight(user_id: str, dim_key: str, mind_dim: str,
                  user_reaction: str, context: str = ""):
    """根据单次交互的用户反馈调整投影权重"""
    if not _CONFIG["enabled"]:
        return

    if user_reaction not in ("positive", "negative"):
        return

    pw = _get_or_create_weight(mind_dim, dim_key)
    lr = _CONFIG["learning_rate"]
    direction = 1.0 if user_reaction == "positive" else -1.0

    pw.weight += direction * lr
    pw.weight = max(-1.0, min(1.0, pw.weight))
    pw.sample_count += 1
    pw.confidence = min(1.0, pw.confidence + 0.01)

    if user_reaction == "positive":
        pw.positive_ratio = (pw.positive_ratio * (pw.sample_count - 1) + 1) / pw.sample_count
    else:
        pw.positive_ratio = (pw.positive_ratio * (pw.sample_count - 1) + 0) / pw.sample_count

    _save_weights()
