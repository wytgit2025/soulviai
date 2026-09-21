# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""投递策略记忆引擎 — Delivery Memory Engine
==========================================================
记录每次投递决策（回复/延迟/沉默）及其后果，学习最优投递策略。

核心能力:
  1. 策略记忆：记录每次投递决策及用户反应
  2. 模式学习：识别在特定心智状态下哪种策略最有效
  3. 长期优化：基于历史数据优化未来投递决策
  4. 流失预警：检测用户流失风险并提前干预

架构:
  投递决策 → 记录到记忆 → 用户反应 → 效果评估 → 策略优化
"""
import json
import random
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

try:
    from core import database as db
except ImportError:
    db = None

# ══════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════

_CONFIG = {
    "enabled": True,
    "memory_file": "data/json/delivery_memory.json",
    "max_memory_per_user": 200,       # 每个用户最多保留 200 条记录
    "learning_rate": 0.05,            # 学习率
    "similarity_threshold": 0.7,      # 心智状态相似度阈值
    "min_memory_for_learning": 10,    # 最少需要多少条记录才开始学习
    "engagement_decay_days": 7,       # 用户参与度衰减周期（天）
}

# 缓存
_user_memory_cache: Dict[str, List[Dict]] = {}


@dataclass
class DeliveryRecord:
    """一次投递记录"""
    timestamp: datetime
    user_id: str
    
    # 投递决策
    should_reply: bool                # 是否回复
    skip_type: str = ""               # 沉默类型 (如果有)
    delay_seconds: float = 0.0        # 延迟秒数
    delay_mode: str = "instant"       # 延迟模式
    
    # 当时的心智状态（精简）
    mind_snapshot: Dict[str, float] = field(default_factory=dict)
    
    # 用户反应
    user_response: Optional[str] = None
    user_response_time: float = 0.0   # 用户回复间隔（秒）
    user_sentiment: str = "neutral"   # "positive" / "neutral" / "negative"
    user_engagement: float = 0.5      # 用户参与度 0~1
    
    # 效果评估
    effectiveness_score: float = 0.5  # 综合效果评分
    
    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "user_id": self.user_id,
            "should_reply": self.should_reply,
            "skip_type": self.skip_type,
            "delay_seconds": self.delay_seconds,
            "delay_mode": self.delay_mode,
            "mind_snapshot": self.mind_snapshot,
            "user_response": self.user_response,
            "user_response_time": self.user_response_time,
            "user_sentiment": self.user_sentiment,
            "user_engagement": self.user_engagement,
            "effectiveness_score": self.effectiveness_score,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'DeliveryRecord':
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            user_id=data["user_id"],
            should_reply=data["should_reply"],
            skip_type=data.get("skip_type", ""),
            delay_seconds=data.get("delay_seconds", 0.0),
            delay_mode=data.get("delay_mode", "instant"),
            mind_snapshot=data.get("mind_snapshot", {}),
            user_response=data.get("user_response"),
            user_response_time=data.get("user_response_time", 0.0),
            user_sentiment=data.get("user_sentiment", "neutral"),
            user_engagement=data.get("user_engagement", 0.5),
            effectiveness_score=data.get("effectiveness_score", 0.5),
        )


class DeliveryMemory:
    """投递策略记忆引擎"""
    
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.memory: List[DeliveryRecord] = []
        self._load()
    
    def _load(self):
        """从磁盘加载用户记忆"""
        global _user_memory_cache
        
        if self.user_id in _user_memory_cache:
            self.memory = _user_memory_cache[self.user_id]
            return
        
        try:
            store = _get_delivery_memory_store()
            all_memory = store.read()
            
            if self.user_id in all_memory:
                records = [
                    DeliveryRecord.from_dict(d) 
                    for d in all_memory[self.user_id]
                ]
                self.memory = records
                _user_memory_cache[self.user_id] = self.memory
        except FileNotFoundError:
            self.memory = []
        except Exception:
            self.memory = []
    
    def _save(self):
        """持久化记忆到磁盘"""
        global _user_memory_cache
        
        try:
            import os
            os.makedirs(os.path.dirname(_CONFIG["memory_file"]), exist_ok=True)
            
            store = _get_delivery_memory_store()
            all_memory = store.read()
            if not isinstance(all_memory, dict):
                all_memory = {}
            
            all_memory[self.user_id] = [
                r.to_dict() for r in self.memory[-_CONFIG["max_memory_per_user"]:]
            ]
            
            store.write(all_memory)
            
            _user_memory_cache[self.user_id] = self.memory
        except Exception:
            pass

    def record(self, decision: Dict, mind_data: Dict,
               user_response: Optional[str] = None,
               user_response_time: float = 0.0):
        if not _CONFIG["enabled"]:
            return
        user_sentiment = self._analyze_sentiment(user_response)
        user_engagement = self._compute_engagement(user_response, user_response_time)
        record = DeliveryRecord(
            timestamp=datetime.now(),
            user_id=self.user_id,
            should_reply=decision.get("should_reply", True),
            skip_type=decision.get("skip_type", ""),
            delay_seconds=decision.get("delay_seconds", 0.0),
            delay_mode=decision.get("delay_mode", "instant"),
            mind_snapshot={
                "joy": mind_data.get("joy", 0.5),
                "misery": mind_data.get("misery", 0.15),
                "fatigue": mind_data.get("fatigue", 0.25),
                "restraint": mind_data.get("restraint", 0.6),
                "emotional_volatility": mind_data.get("emotional_volatility", 0.3),
            },
            user_response=user_response,
            user_response_time=user_response_time,
            user_sentiment=user_sentiment,
            user_engagement=user_engagement,
        )
        record.effectiveness_score = self._compute_effectiveness(record)
        self.memory.append(record)
        if len(self.memory) % 5 == 0:
            self._save()

    def _analyze_sentiment(self, text: Optional[str]) -> str:
        if not text:
            return "neutral"
        positive_words = ["开心", "高兴", "喜欢", "爱", "好", "哈哈", "嘻嘻", "温暖", "感动"]
        negative_words = ["生气", "难过", "不喜欢", "讨厌", "烦", "无聊", "呵呵", "冷漠", "失望"]
        text_lower = text.lower()
        pos_count = sum(1 for w in positive_words if w in text_lower)
        neg_count = sum(1 for w in negative_words if w in text_lower)
        if pos_count > neg_count:
            return "positive"
        elif neg_count > pos_count:
            return "negative"
        return "neutral"

    def _compute_engagement(self, text: Optional[str], response_time: float) -> float:
        if not text:
            return 0.2
        length_score = min(1.0, len(text) / 50)
        if response_time > 0:
            time_score = 1.0 / (1.0 + math.log10(response_time / 60 + 1))
        else:
            time_score = 0.5
        return round((length_score * 0.6 + time_score * 0.4), 3)

    def _compute_effectiveness(self, record: DeliveryRecord) -> float:
        sentiment_weights = {"positive": 1.0, "neutral": 0.6, "negative": 0.2}
        base_score = sentiment_weights.get(record.user_sentiment, 0.5)
        engagement_bonus = record.user_engagement * 0.3
        if record.user_response and record.user_response_time < 300:
            engagement_bonus += 0.1
        return round(min(1.0, base_score + engagement_bonus), 3)

    def get_optimal_strategy(self, current_mind: Dict) -> Dict:
        if len(self.memory) < _CONFIG["min_memory_for_learning"]:
            return {"should_reply": True, "delay_seconds": 0.0, "delay_mode": "instant"}
        similar_records = []
        for record in self.memory[-100:]:
            similarity = self._mind_similarity(record.mind_snapshot, current_mind)
            if similarity >= _CONFIG["similarity_threshold"]:
                similar_records.append((similarity, record))
        if not similar_records:
            similar_records = [(1.0, r) for r in self.memory[-50:]]
        similar_records.sort(key=lambda x: x[1].effectiveness_score, reverse=True)
        top_k = similar_records[:5]
        total_weight = sum(sim for sim, _ in top_k)
        avg_delay = sum(sim * r.delay_seconds for sim, r in top_k) / total_weight if total_weight > 0 else 0
        avg_engagement = sum(sim * r.user_engagement for sim, r in top_k) / total_weight if total_weight > 0 else 0
        if avg_engagement > 0.7:
            return {"should_reply": True, "delay_seconds": max(0, avg_delay - 10), "delay_mode": "fast"}
        elif avg_engagement < 0.4:
            return {"should_reply": True, "delay_seconds": avg_delay + 30, "delay_mode": "normal"}
        return {"should_reply": True, "delay_seconds": avg_delay, "delay_mode": "normal"}

    def _mind_similarity(self, mind1: Dict, mind2: Dict) -> float:
        common_dims = set(mind1.keys()) & set(mind2.keys())
        if not common_dims:
            return 0.0
        v1 = [mind1[d] for d in common_dims]
        v2 = [mind2[d] for d in common_dims]
        dot = sum(a * b for a, b in zip(v1, v2))
        norm1 = math.sqrt(sum(a * a for a in v1))
        norm2 = math.sqrt(sum(b * b for b in v2))
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)

    def get_churn_risk(self) -> float:
        if len(self.memory) < 5:
            return 0.5
        recent = self.memory[-10:]
        recent_engagement = [r.user_engagement for r in recent]
        recent_effectiveness = [r.effectiveness_score for r in recent]
        engagement_trend = self._compute_trend(recent_engagement)
        effectiveness_trend = self._compute_trend(recent_effectiveness)
        avg_engagement = sum(recent_engagement) / len(recent_engagement)
        avg_effectiveness = sum(recent_effectiveness) / len(recent_effectiveness)
        risk = 0.0
        if avg_engagement < 0.4:
            risk += 0.3
        if effectiveness_trend < -0.05:
            risk += 0.2
        if engagement_trend < -0.05:
            risk += 0.2
        negative_count = sum(1 for r in recent if r.user_sentiment == "negative")
        if negative_count >= 3:
            risk += 0.3
        return min(1.0, risk)

    def _compute_trend(self, values: List[float]) -> float:
        if len(values) < 2:
            return 0.0
        n = len(values)
        x_mean = (n - 1) / 2
        y_mean = sum(values) / n
        numerator = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        if denominator == 0:
            return 0.0
        return numerator / denominator

    def get_stats(self) -> Dict:
        if not self.memory:
            return {"total_records": 0}
        recent = self.memory[-20:]
        return {
            "total_records": len(self.memory),
            "recent_avg_engagement": sum(r.user_engagement for r in recent) / len(recent),
            "recent_avg_effectiveness": sum(r.effectiveness_score for r in recent) / len(recent),
            "churn_risk": self.get_churn_risk(),
            "positive_ratio": sum(1 for r in self.memory if r.user_sentiment == "positive") / len(self.memory),
            "negative_ratio": sum(1 for r in self.memory if r.user_sentiment == "negative") / len(self.memory),
        }


def _get_delivery_memory_store():
    from core.json_store import get_store
    return get_store(_CONFIG.get("memory_file", "data/json/delivery_memory.json"), {})


# ══════════════════════════════════════════════════════════════════════
# 全局 API
# ══════════════════════════════════════════════════════════════════════

_memories: Dict[str, DeliveryMemory] = {}


def get_memory(user_id: str) -> DeliveryMemory:
    """获取用户的投递记忆"""
    if user_id not in _memories:
        _memories[user_id] = DeliveryMemory(user_id)
    return _memories[user_id]


def record_delivery(user_id: str, decision: Dict, mind_data: Dict,
                    user_response: Optional[str] = None,
                    user_response_time: float = 0.0):
    """记录投递决策的便捷函数"""
    memory = get_memory(user_id)
    memory.record(decision, mind_data, user_response, user_response_time)


def get_optimal_delivery_strategy(user_id: str, mind_data: Dict) -> Dict:
    """获取最优投递策略的便捷函数"""
    memory = get_memory(user_id)
    return memory.get_optimal_strategy(mind_data)


def get_churn_risk(user_id: str) -> float:
    """获取流失风险的便捷函数"""
    memory = get_memory(user_id)
    return memory.get_churn_risk()


def load_engine_config():
    """加载配置"""
    global _CONFIG
    try:
        from core import config as cfg
        dm_cfg = cfg.get_section("delivery_memory")
        if dm_cfg:
            _CONFIG.update(dm_cfg)
    except Exception:
        pass
