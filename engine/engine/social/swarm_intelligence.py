# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""群体涌现智能 — Swarm Emergent Intelligence
==============================================
多个实例共享经验、交叉学习、竞争协作 → 产生个体不具备的群体智能。

核心流程：
  1. 跨实例行为迁移（验证过的模式传播到其他实例）
  2. 差异驱动进化（检测实例间的"有趣不同"）
  3. 主系统 ↔ 共享池定期同步
  4. 共识度算法确保质量
  5. 行为基因组——将已验证的模式编码为可迁移的基因
"""
import json
import math
import os
import random
import threading
import time
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict

from engine.social import collective_pool as pool

# ── 配置 ──
_CONFIG = {
    "enabled": True,
    "migration_min_confidence": 0.5,
    "migration_similarity_threshold": 0.5,
    "difference_check_interval_ticks": 10,
    "sync_interval_hours": 6,
    "max_migrations_per_sync": 3,
    "dna_encoding_version": 1,
}

# ── 状态 ──
_instance_registry: Dict[str, dict] = {}
_sync_lock = threading.Lock()


# ══════════════════════════════════════════════════════════════════════
# 行为基因组编码
# ══════════════════════════════════════════════════════════════════════

def encode_behavior_dna(behavior_vector: Dict[str, float],
                         mind_snapshot: Dict[str, float]) -> Dict:
    """将行为模式编码为可迁移的"基因"

    基因 = 行为向量核心维度 + 心智上下文快照 + 元数据
    """
    core_dims = ["approach", "verbosity", "warmth", "playfulness",
                 "seriousness", "tsundere", "initiative", "clinginess"]
    dna = {
        "version": _CONFIG["dna_encoding_version"],
        "behavior_core": {k: round(behavior_vector.get(k, 0.5), 3) for k in core_dims},
        "mind_context": {
            "joy": round(mind_snapshot.get("joy", 0.5), 2),
            "fatigue": round(mind_snapshot.get("fatigue", 0.25), 2),
            "restraint": round(mind_snapshot.get("restraint", 0.6), 2),
            "sensitivity_paranoia": round(mind_snapshot.get("sensitivity_paranoia", 0.35), 2),
        },
        "signature": _compute_behavior_signature(behavior_vector),
    }
    return dna


def _compute_behavior_signature(behavior_vector: Dict[str, float]) -> str:
    """计算行为签名——用于快速比较行为相似度"""
    key_dims = ["approach", "verbosity", "warmth", "playfulness"]
    vals = [str(int(behavior_vector.get(k, 0.5) * 10)) for k in key_dims]
    return "".join(vals)


def behavior_similarity(dna_a: Dict, dna_b: Dict) -> float:
    """计算两个行为基因组的相似度"""
    core_a = dna_a.get("behavior_core", {})
    core_b = dna_b.get("behavior_core", {})
    if not core_a or not core_b:
        return 0.0
    common_dims = set(core_a.keys()) & set(core_b.keys())
    if not common_dims:
        return 0.0
    diffs = [abs(core_a[d] - core_b[d]) for d in common_dims]
    avg_diff = sum(diffs) / len(diffs)
    return max(0.0, 1.0 - avg_diff * 2.0)


# ══════════════════════════════════════════════════════════════════════
# 跨实例行为迁移（Step 3）
# ══════════════════════════════════════════════════════════════════════

def migrate_behavior(source_id: str, target_id: str,
                      source_mind: Dict[str, float],
                      target_mind: Dict[str, float]) -> List[dict]:
    """将源实例的有效行为模式迁移到目标实例（Step 3: 跨实例行为迁移）

    流程：
      1. 从源实例沙盒获取高置信度模式
      2. 计算迁移适用度（心智相似度）
      3. 适用度 > 阈值 → 注入到目标实例的沙盒
      4. 记录迁移日志
    """
    if not _CONFIG["enabled"]:
        return []

    migrated = []
    try:
        from engine.behavior import behavior_sandbox as sandbox

        source_patterns = sandbox.get_sandbox_patterns(source_id)
        target_patterns = sandbox.get_sandbox_patterns(target_id)
        target_names = {p.get("name") for p in target_patterns}

        # 计算心智相似度
        similarity = _compute_mind_similarity(source_mind, target_mind)

        for pattern in source_patterns:
            if pattern.get("confidence", 0) < _CONFIG["migration_min_confidence"]:
                continue
            if pattern.get("name") in target_names:
                continue

            effective_similarity = similarity * (0.5 + pattern.get("confidence", 0.5) * 0.5)
            if effective_similarity < _CONFIG["migration_similarity_threshold"]:
                continue

            migrated_pattern = dict(pattern)
            migrated_pattern["confidence"] = pattern.get("confidence", 0.5) * 0.6
            migrated_pattern["source"] = f"cross_instance:{source_id}"
            migrated_pattern["migrated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

            target_patterns.append(migrated_pattern)
            sandbox.set_sandbox_patterns(target_id, target_patterns)
            migrated.append(migrated_pattern)

            pool.submit_insight(
                source_instance=source_id,
                content=f"行为模式'{pattern.get('name','')}'迁移到{target_id}",
                target_instances=[target_id],
            )

    except Exception:
        pass

    return migrated


def _compute_mind_similarity(mind_a: Dict[str, float],
                              mind_b: Dict[str, float]) -> float:
    """计算两个心智状态的相似度"""
    common_dims = set(mind_a.keys()) & set(mind_b.keys())
    if not common_dims:
        return 0.3
    diffs = [abs(mind_a.get(d, 0.5) - mind_b.get(d, 0.5)) for d in common_dims]
    avg_diff = sum(diffs) / len(diffs)
    return max(0.0, 1.0 - avg_diff * 1.5)


# ══════════════════════════════════════════════════════════════════════
# 差异检测引擎（Step 4）
# ══════════════════════════════════════════════════════════════════════

def detect_interesting_differences(instances: Dict[str, dict]) -> List[dict]:
    """检测实例间的"有趣差异"——同样的输入，不同的反应（Step 4）

    返回差异报告列表，包含：
      - 哪些实例对
      - 差异幅度
      - 各自的行为风格
      - 可能的原因分析
    """
    if len(instances) < 2:
        return []

    results = []
    ids = list(instances.keys())

    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a_id, b_id = ids[i], ids[j]
            a_data, b_data = instances[a_id], instances[b_id]

            a_bv = a_data.get("behavior_vector", {})
            b_bv = b_data.get("behavior_vector", {})

            divergence = _compute_behavior_divergence(a_bv, b_bv)
            if divergence < 0.25:
                continue

            a_pattern = _deduce_style_label(a_bv)
            b_pattern = _deduce_style_label(b_bv)

            report = {
                "instances": (a_id, b_id),
                "divergence": round(divergence, 3),
                "a_style": a_pattern,
                "b_style": b_pattern,
                "key_differences": _find_key_differences(a_bv, b_bv),
            }

            # 如果差异显著，LLM 分析深层原因
            if divergence > 0.35:
                try:
                    report["root_cause"] = _analyze_divergence_cause(
                        a_id, b_id, a_data, b_data
                    )
                except Exception:
                    report["root_cause"] = ""

            results.append(report)

            # 提交到共享池作为洞察
            if divergence > 0.3:
                pool.submit_insight(
                    source_instance=a_id,
                    content=f"与{b_id}的差异: {report['key_differences'][:40]}",
                    target_instances=[b_id],
                )

    return results


def _compute_behavior_divergence(bv_a: Dict[str, float],
                                  bv_b: Dict[str, float]) -> float:
    """计算两个行为向量的差异幅度"""
    common = set(bv_a.keys()) & set(bv_b.keys())
    if not common:
        return 0.0
    diffs = [abs(bv_a.get(k, 0.5) - bv_b.get(k, 0.5)) for k in common]
    return sum(diffs) / len(diffs)


def _deduce_style_label(behavior_vector: Dict[str, float]) -> str:
    """从行为向量推断风格标签"""
    if behavior_vector.get("warmth", 0.5) > 0.65:
        return "温暖型"
    if behavior_vector.get("tsundere", 0.3) > 0.55:
        return "傲娇型"
    if behavior_vector.get("playfulness", 0.5) > 0.6:
        return "活泼型"
    if behavior_vector.get("seriousness", 0.5) > 0.6:
        return "认真型"
    if behavior_vector.get("approach", 0.5) < 0.35:
        return "疏离型"
    return "均衡型"


def _find_key_differences(bv_a: Dict[str, float],
                           bv_b: Dict[str, float]) -> List[str]:
    """找出差异最大的行为维度"""
    diffs = []
    all_dims = set(bv_a.keys()) | set(bv_b.keys())
    dim_names = {
        "approach": "接近度", "verbosity": "表达量", "warmth": "温暖度",
        "playfulness": " playful", "seriousness": "认真度", "honesty": "坦诚度",
        "tsundere": "傲娇度", "sulkiness": "别扭度", "initiative": "主动性",
        "clinginess": "粘人度", "emotional_display": "外显度",
    }
    for dim in all_dims:
        diff = abs(bv_a.get(dim, 0.5) - bv_b.get(dim, 0.5))
        if diff > 0.15:
            name = dim_names.get(dim, dim)
            diffs.append(f"{name}差距{diff:.0%}")
    return diffs[:3]


def _analyze_divergence_cause(a_id: str, b_id: str,
                                a_data: dict, b_data: dict) -> str:
    """LLM 分析差异的深层原因"""
    try:
        from core import ai as ai_module
        a_mind = a_data.get("mind", {})
        b_mind = b_data.get("mind", {})
        prompt = (
            f"两个AI实例的行为差异分析：\n"
            f"实例A: joy={a_mind.get('joy',0.5):.1f}, "
            f"restraint={a_mind.get('restraint',0.5):.1f}, "
            f"fatigue={a_mind.get('fatigue',0.25):.1f}\n"
            f"实例B: joy={b_mind.get('joy',0.5):.1f}, "
            f"restraint={b_mind.get('restraint',0.5):.1f}, "
            f"fatigue={b_mind.get('fatigue',0.25):.1f}\n"
            f"一句话分析为什么它们行为不同。20字内。"
        )
        result = ai_module.background_chat(prompt, temperature=0.3, max_tokens=40)
        return result.strip()[:40] if result else "心智状态差异"
    except Exception:
        return "心智状态差异"


# ══════════════════════════════════════════════════════════════════════
# 主系统 ↔ 共享池同步（Step 5）
# ══════════════════════════════════════════════════════════════════════

def sync_main_to_pool(instance_id: str, behavior_vector: Dict[str, float],
                       mind_snapshot: Dict[str, float]):
    """主系统向共享池提交其行为模式和状态（Step 5）

    每次对话后或每日定时调用。
    """
    if not _CONFIG["enabled"]:
        return

    try:
        from engine.behavior import behavior_sandbox as sandbox
        patterns = sandbox.get_sandbox_patterns(instance_id)

        for pattern in patterns:
            if pattern.get("confidence", 0) < _CONFIG["migration_min_confidence"]:
                continue
            if pattern.get("source", "").startswith("cross_instance"):
                continue

            content = {
                "name": pattern.get("name", ""),
                "behavior_offset": pattern.get("behavior_offset", {}),
                "condition": pattern.get("condition", ""),
            }
            pid = pool.submit_pattern("behavior", content, instance_id)

            dna = encode_behavior_dna(behavior_vector, mind_snapshot)
            pool.submit_insight(
                source_instance=instance_id,
                content=f"行为模式'{pattern.get('name','')}'已提交到共享池",
            )

    except Exception:
        pass


def sync_pool_to_main(instance_id: str, mind_snapshot: Dict[str, float]):
    """从共享池拉取共识模式并注入到主系统沙盒（Step 5 反向）"""
    if not _CONFIG["enabled"]:
        return

    try:
        from engine.behavior import behavior_sandbox as sandbox
        consensus = pool.get_consensus_patterns("behavior")

        existing = sandbox.get_sandbox_patterns(instance_id)
        existing_names = {p.get("name") for p in existing}

        imported = 0
        for pattern in consensus[:_CONFIG["max_migrations_per_sync"]]:
            name = pattern.content.get("name", "")
            if name in existing_names:
                continue

            migrated = {
                "name": name,
                "condition": pattern.content.get("condition", ""),
                "behavior_offset": pattern.content.get("behavior_offset", {}),
                "confidence": pattern.consensus_level * 0.7,
                "trial_count": pattern.verification_count,
                "hit_count": 0,
                "feedback_sum": 0.0,
                "source": f"collective_pool:{pattern.pattern_id}",
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            existing.append(migrated)
            imported += 1

        if imported:
            sandbox.set_sandbox_patterns(instance_id, existing)

    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
# 夜间群体复盘
# ══════════════════════════════════════════════════════════════════════

def night_swarm_review(user_id: str, mind_data: dict = None,
                        behavior_vector: dict = None):
    """夜间群体智能复盘（由 life.py 调用）

    执行：
      1. 主系统 → 共享池同步（提交新模式）
      2. 共享池 → 主系统同步（拉取共识）
      3. 如果有多实例信息，执行差异检测
    """
    if not _CONFIG["enabled"]:
        return

    # 主系统 → 共享池
    if behavior_vector:
        sync_main_to_pool(user_id, behavior_vector, mind_data or {})

    # 共享池 → 主系统
    sync_pool_to_main(user_id, mind_data or {})

    stats = pool.get_pool_stats()
    if stats["consensus_patterns"] > 0 or stats["pending_patterns"] > 0:
        print(f"   🐝 群体智能同步: {stats['consensus_patterns']}共识/"
              f"{stats['pending_patterns']}待验证/{stats['total_insights']}洞察")


# ══════════════════════════════════════════════════════════════════════
# 注册表管理
# ══════════════════════════════════════════════════════════════════════

def register_instance(instance_id: str, metadata: dict):
    """注册一个实例到群体智能系统"""
    _instance_registry[instance_id] = {
        "metadata": metadata,
        "registered_at": time.time(),
        "last_sync": 0,
    }


def get_instance_info(instance_id: str) -> Optional[dict]:
    """获取实例信息"""
    return _instance_registry.get(instance_id)


def get_swarm_summary() -> str:
    """获取群体智能系统摘要"""
    stats = pool.get_pool_stats()
    return (f"群体: {len(_instance_registry)}实例, "
            f"{stats['consensus_patterns']}共识模式, "
            f"{stats['total_insights']}条跨实例洞察")
