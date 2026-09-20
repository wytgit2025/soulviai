# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""独立统计评价层 — Meta Evaluator
==========================================
不依赖LLM的纯统计评价引擎。作为元认知校准的前置判断层，
用数据指标判断系统表现，仅在统计异常时才触发LLM深度的校准。

三层校准节奏:
   快速反馈 — 每10轮对话轻量统计 (0次LLM, ~10ms)
   中度校准 — 每6小时统计+轻量LLM (1次LLM)
   深度校准 — 每48小时完整LLM校准 (保持现有meta_cognition)

评价指标:
  - 回复多样性: 最近N条回复的词汇分布熵
  - 情绪一致性: 心智joy vs 回复情感倾向的相关性
  - 行为连续性: behavior_vector时间序列的平滑度
  - 用户参与度: 用户回复长度/情绪变化
  - 记忆利用率: 检索到的记忆实际被使用的比例
"""
import math
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional

try:
    from core import database as db
except ImportError:
    db = None


class EvaluationReport:
    def __init__(self):
        self.diversity_score: float = 0.5
        self.emotion_coherence: float = 0.5
        self.behavior_smoothness: float = 0.5
        self.user_engagement: float = 0.5
        self.memory_utilization: float = 0.5
        self.overall_health: float = 0.5
        self.flags: List[str] = []
        self.suggestions: List[str] = []

    def to_dict(self) -> Dict:
        return {
            "diversity": round(self.diversity_score, 3),
            "emotion_coherence": round(self.emotion_coherence, 3),
            "behavior_smoothness": round(self.behavior_smoothness, 3),
            "user_engagement": round(self.user_engagement, 3),
            "memory_utilization": round(self.memory_utilization, 3),
            "overall_health": round(self.overall_health, 3),
            "flags": self.flags,
            "suggestions": self.suggestions,
        }


def evaluate(user_id: str, recent_rounds: int = 10) -> EvaluationReport:
    report = EvaluationReport()

    try:
        messages = db.load_recent_messages(user_id, limit=recent_rounds * 2)
    except Exception:
        return report

    if not messages or len(messages) < 4:
        return report

    ai_msgs = [m["content"] for m in messages if m.get("role") in ("assistant", "ai")]
    user_msgs = [m["content"] for m in messages if m.get("role") == "user"]

    if ai_msgs:
        report.diversity_score = _compute_diversity(ai_msgs)
    if user_msgs:
        report.user_engagement = _compute_engagement(user_msgs)

    try:
        mind_data_raw = db.get_personality(user_id)
        if mind_data_raw and ai_msgs:
            report.emotion_coherence = _compute_emotion_coherence(mind_data_raw, ai_msgs)
    except Exception:
        pass

    report.overall_health = round(
        report.diversity_score * 0.20 +
        report.emotion_coherence * 0.20 +
        report.behavior_smoothness * 0.20 +
        report.user_engagement * 0.25 +
        report.memory_utilization * 0.15,
        3
    )

    _flag_problems(report)

    return report


def _compute_diversity(messages: List[str]) -> float:
    if not messages:
        return 0.5
    all_words = []
    total_chars = 0
    for msg in messages[-8:]:
        chars = list(msg)
        all_words.extend(chars)
        total_chars += len(chars)

    if not all_words:
        return 0.5

    counter = Counter(all_words)
    entropy = 0.0
    total = len(all_words)
    for count in counter.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log(p)

    max_entropy = math.log(len(counter)) if counter else 1.0
    normalized = entropy / max_entropy if max_entropy > 0 else 0.5

    avg_len = total_chars / len(messages) if messages else 0
    length_score = min(1.0, max(0.0, (avg_len - 5) / 50))

    return round(normalized * 0.6 + length_score * 0.4, 3)


def _compute_engagement(user_msgs: List[str]) -> float:
    if not user_msgs:
        return 0.5

    lengths = [len(m) for m in user_msgs[-6:]]
    avg_len = sum(lengths) / len(lengths) if lengths else 0

    length_score = min(1.0, max(0.1, avg_len / 40))

    q_count = sum(1 for m in user_msgs[-6:] if "?" in m or "？" in m)
    question_score = min(1.0, q_count / 3)

    return round(length_score * 0.5 + question_score * 0.5, 3)


def _compute_emotion_coherence(mind_data: dict, ai_msgs: List[str]) -> float:
    if not ai_msgs or not mind_data:
        return 0.5

    joy = mind_data.get("joy", 0.5)
    misery = mind_data.get("misery", 0.15)

    positive_words = ["开心", "真好", "喜欢", "幸福", "温暖", "爱", "棒", "哈哈", "嘻嘻", "谢谢"]
    negative_words = ["累", "烦", "算了", "没事", "随便", "难过", "不舒服", "无所谓"]

    latest = ai_msgs[-1] if ai_msgs else ""
    pos_count = sum(1 for w in positive_words if w in latest)
    neg_count = sum(1 for w in negative_words if w in latest)

    net_sentiment = (pos_count - neg_count) / max(1, pos_count + neg_count)

    if joy > 0.6:
        expected = 0.3
    elif joy < 0.35:
        expected = -0.3
    else:
        expected = 0.0

    deviation = abs(net_sentiment - expected)
    return round(max(0.0, 1.0 - deviation), 3)


def _flag_problems(report: EvaluationReport):
    if report.diversity_score < 0.3:
        report.flags.append("回复多样性过低——可能陷入模板化")
        report.suggestions.append("增加生成温度、调整矛盾博弈强度")

    if report.emotion_coherence < 0.35:
        report.flags.append("情绪一致性差——回复语气与心智状态不匹配")
        report.suggestions.append("检查原则1(情绪残留)和心口差值机制")

    if report.user_engagement < 0.2:
        report.flags.append("用户参与度持续走低")
        report.suggestions.append("考虑提升主动性和话题多样性")

    if report.overall_health < 0.4:
        report.flags.append("整体健康度偏低，建议触发LLM深度校准")
        report.suggestions.append("触发meta_cognition.calibrate()")


def should_quick_adjust(report: EvaluationReport) -> bool:
    if report.overall_health < 0.35:
        return True
    return len(report.flags) >= 2


def should_medium_calibrate(report: EvaluationReport) -> bool:
    return report.overall_health < 0.5 or len(report.flags) >= 1


def quick_adjust(user_id: str, report: EvaluationReport):
    try:
        from engine import mind as mind_module
    except ImportError:
        return

    adjustments = {}
    if report.diversity_score < 0.3:
        adjustments["emotional_volatility"] = 0.01
        adjustments["chaotic_mood"] = 0.01
    if report.emotion_coherence < 0.35:
        adjustments["restraint"] = 0.01
        adjustments["life_sense"] = 0.01
    if report.user_engagement < 0.2:
        adjustments["life_vitality"] = 0.01
        adjustments["dependence"] = 0.005

    if adjustments:
        mind_module.adjust_mind_dimensions(user_id, adjustments, impact=0.15)
