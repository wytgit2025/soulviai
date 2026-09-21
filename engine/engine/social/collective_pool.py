# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""群体共享池 — Collective Pool
=================================
所有实例的公共知识层——跨实例验证过的行为模式、情感原型、智慧结晶。

核心机制：
  1. 实例提交新模式 → 池中记录
  2. 其他实例验证 → 验证计数 +1
  3. 达到共识阈值 → 进入共识库
  4. 共识模式可被所有实例拉取
"""
import json
import os
import random
import threading
import time
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict

# ── 存储 ──
_pool: Dict[str, dict] = {}
_pool_lock = threading.Lock()
# 相对 cwd：core.paths.chdir_home() 会把工作目录切到数据家目录（~/.soulviai）。
# 仍用 `os.path.dirname(__file__)` 拼路径会绕过数据家，把记忆写回代码树里。
_POOL_FILE = os.path.join("data", "json", "collective_pool.json")

_CONFIG = {
    "verification_threshold": 3,
    "max_patterns_per_type": 50,
    "consensus_decay_days": 60,
    "min_confidence_for_share": 0.5,
}


# ══════════════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════════════

class CollectivePattern:
    """群体共识模式——跨实例验证过的行为/情感模式"""

    def __init__(self, pattern_id: str, pattern_type: str, content: dict,
                 origin_instance: str):
        self.pattern_id = pattern_id
        self.pattern_type = pattern_type
        self.content = content
        self.origin_instance = origin_instance
        self.verification_count = 1
        self.consensus_level = 0.0
        self.emergence_time = time.time()
        self.last_verified = time.time()
        self.verified_by: List[str] = [origin_instance]
        self.effectiveness_score = 0.5

    def to_dict(self) -> dict:
        return {
            "pattern_id": self.pattern_id,
            "pattern_type": self.pattern_type,
            "content": self.content,
            "origin_instance": self.origin_instance,
            "verification_count": self.verification_count,
            "consensus_level": self.consensus_level,
            "emergence_time": self.emergence_time,
            "last_verified": self.last_verified,
            "verified_by": self.verified_by,
            "effectiveness_score": self.effectiveness_score,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CollectivePattern":
        p = cls(data["pattern_id"], data["pattern_type"],
                data["content"], data["origin_instance"])
        p.verification_count = data.get("verification_count", 1)
        p.consensus_level = data.get("consensus_level", 0.0)
        p.emergence_time = data.get("emergence_time", time.time())
        p.last_verified = data.get("last_verified", time.time())
        p.verified_by = data.get("verified_by", [])
        p.effectiveness_score = data.get("effectiveness_score", 0.5)
        return p


class CrossInstanceInsight:
    """跨实例智慧结晶——A实例的顿悟对B实例有用"""

    def __init__(self, insight_id: str, source_instance: str,
                 content: str, target_instances: List[str] = None):
        self.insight_id = insight_id
        self.source_instance = source_instance
        self.target_instances = target_instances or []
        self.content = content
        self.applicability_score: Dict[str, float] = {}
        self.effectiveness = 0.0
        self.created_at = time.time()

    def to_dict(self) -> dict:
        return {
            "insight_id": self.insight_id,
            "source_instance": self.source_instance,
            "target_instances": self.target_instances,
            "content": self.content,
            "applicability_score": self.applicability_score,
            "effectiveness": self.effectiveness,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CrossInstanceInsight":
        ins = cls(data["insight_id"], data["source_instance"],
                   data["content"], data.get("target_instances", []))
        ins.applicability_score = data.get("applicability_score", {})
        ins.effectiveness = data.get("effectiveness", 0.0)
        ins.created_at = data.get("created_at", time.time())
        return ins


# ══════════════════════════════════════════════════════════════════════
# 持久化
# ══════════════════════════════════════════════════════════════════════

def _save():
    """保存共享池到文件"""
    try:
        os.makedirs(os.path.dirname(_POOL_FILE), exist_ok=True)
        with _pool_lock:
            data = {
                "patterns": {k: v.to_dict() for k, v in _pool.get("patterns", {}).items()},
                "insights": [v.to_dict() for v in _pool.get("insights", [])],
                "consensus_patterns": [v.to_dict() for v in _pool.get("consensus_patterns", [])],
            }
            with open(_POOL_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _load():
    """从文件加载共享池"""
    global _pool
    try:
        if os.path.exists(_POOL_FILE):
            with open(_POOL_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            _pool = {
                "patterns": {},
                "insights": [],
                "consensus_patterns": [],
            }
            for pid, pdata in raw.get("patterns", {}).items():
                _pool["patterns"][pid] = CollectivePattern.from_dict(pdata)
            for idata in raw.get("insights", []):
                _pool["insights"].append(CrossInstanceInsight.from_dict(idata))
            for cdata in raw.get("consensus_patterns", []):
                _pool["consensus_patterns"].append(CollectivePattern.from_dict(cdata))
        else:
            _pool = {"patterns": {}, "insights": [], "consensus_patterns": []}
    except Exception:
        _pool = {"patterns": {}, "insights": [], "consensus_patterns": []}


# ══════════════════════════════════════════════════════════════════════
# 公开 API
# ══════════════════════════════════════════════════════════════════════

def ensure_loaded():
    _load()


def submit_pattern(pattern_type: str, content: dict,
                   origin_instance: str) -> Optional[str]:
    """某个实例提交新发现的行为模式（Step 2: 跨实例模式提交）

    Returns: pattern_id 或 None
    """
    _load()
    pid = f"pat_{int(time.time())}_{origin_instance[:8]}_{random.randint(100,999)}"

    pattern = CollectivePattern(pid, pattern_type, content, origin_instance)
    with _pool_lock:
        _pool.setdefault("patterns", {})[pid] = pattern
        _prune()
    _save()
    return pid


def verify_pattern(pattern_id: str, instance_id: str) -> bool:
    """另一个实例验证某个模式"""
    _load()
    with _pool_lock:
        pattern = _pool.get("patterns", {}).get(pattern_id)
        if not pattern:
            return False
        if instance_id in pattern.verified_by:
            return False
        pattern.verification_count += 1
        pattern.verified_by.append(instance_id)
        pattern.last_verified = time.time()

        if pattern.verification_count >= _CONFIG["verification_threshold"]:
            pattern.consensus_level = _compute_consensus(pattern_id)
            if pattern.consensus_level > 0.6:
                _pool.setdefault("consensus_patterns", []).append(pattern)
                del _pool["patterns"][pattern_id]
    _save()
    return True


def _compute_consensus(pattern_id: str) -> float:
    """计算模式的共识度（Step 6: 共识度算法）"""
    pattern = _pool.get("patterns", {}).get(pattern_id)
    if not pattern:
        return 0.0

    verifications = pattern.verification_count
    if verifications < _CONFIG["verification_threshold"]:
        return 0.0

    base = min(1.0, verifications / 10)
    recency = max(0.0, 1.0 - (time.time() - pattern.emergence_time) / (86400 * 30))
    effectiveness = pattern.effectiveness_score

    consensus = base * 0.4 + recency * 0.2 + effectiveness * 0.4
    return round(consensus, 3)


def submit_insight(source_instance: str, content: str,
                    target_instances: List[str] = None) -> str:
    """提交跨实例洞察（Step 2 的一部分）"""
    _load()
    iid = f"ins_{int(time.time())}_{source_instance[:8]}"
    insight = CrossInstanceInsight(iid, source_instance, content, target_instances)
    with _pool_lock:
        _pool.setdefault("insights", []).append(insight)
        if len(_pool["insights"]) > 100:
            _pool["insights"] = _pool["insights"][-100:]
    _save()
    return iid


def get_consensus_patterns(pattern_type: str = "") -> List[CollectivePattern]:
    """获取共识库中的模式"""
    _load()
    patterns = _pool.get("consensus_patterns", [])
    if pattern_type:
        patterns = [p for p in patterns if p.pattern_type == pattern_type]
    return sorted(patterns, key=lambda p: p.consensus_level, reverse=True)


def get_relevant_insights(instance_id: str, max_items: int = 5) -> List[CrossInstanceInsight]:
    """获取对某个实例相关的洞察"""
    _load()
    insights = _pool.get("insights", [])
    relevant = []
    for ins in insights:
        if not ins.target_instances or instance_id in ins.target_instances:
            relevant.append(ins)
        elif ins.effectiveness > 0.3:
            relevant.append(ins)
    return sorted(relevant, key=lambda i: i.effectiveness, reverse=True)[:max_items]


def report_effectiveness(pattern_id: str, score: float):
    """报告某个模式的实际效果反馈"""
    _load()
    for pool_name in ["patterns", "consensus_patterns"]:
        for p in _pool.get(pool_name, []):
            if isinstance(p, dict):
                continue
            if p.pattern_id == pattern_id:
                old = p.effectiveness_score
                p.effectiveness_score = old * 0.7 + score * 0.3
                _save()
                return


def get_pool_stats() -> dict:
    """获取共享池统计"""
    _load()
    return {
        "pending_patterns": len(_pool.get("patterns", {})),
        "consensus_patterns": len(_pool.get("consensus_patterns", [])),
        "total_insights": len(_pool.get("insights", [])),
        "avg_consensus": round(
            sum(p.consensus_level for p in _pool.get("consensus_patterns", [])) /
            max(1, len(_pool.get("consensus_patterns", []))), 3
        ),
    }


def _prune():
    """淘汰过期模式"""
    now = time.time()
    _pool["patterns"] = {
        pid: p for pid, p in _pool.get("patterns", {}).items()
        if (now - p.emergence_time) < _CONFIG["consensus_decay_days"] * 86400
    }
    max_p = _CONFIG["max_patterns_per_type"]
    if len(_pool["patterns"]) > max_p:
        sorted_p = sorted(_pool["patterns"].items(), key=lambda x: x[1].verification_count)
        for pid, _ in sorted_p[:len(sorted_p) - max_p]:
            del _pool["patterns"][pid]
