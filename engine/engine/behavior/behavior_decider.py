# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""内生真人行为决策层 — Endogenous Behavior Decider
==========================================================
所有行为、话术、沉默、主动、克制、撒娇、疏离、温柔、赌气
全部由内生情绪、潜意识、生命状态、因果沉淀驱动。

原则：
  - 零脚本、零模板、零固定套路、零规则触发
  - 100% 概率生成，100% 内生驱动
  - 同一输入状态可产生不同行为（统计一致性 + 单次不可预测）
  - 行为具有惯性（历史依赖），不出现突兀跳变

架构：
  内部状态全集 → 潜在行为空间投影 → 高斯混合采样 → 行为向量 → 自然语言描述
"""
import random
import math
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ══════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════

CONFIG = {
    "enabled": True,
    "inertia_factor": 0.45,          # 行为惯性系数（上一次行为对本次的影响权重）
    "base_noise": 0.06,              # 基础噪声标准差
    "volatility_scale": 0.12,        # 情绪波动放大噪声的倍率
    "history_decay_hours": 4,        # 历史行为衰减半衰期（小时）
    "sample_count": 3,               # 混合采样的分量数
    "correlation_strength": 0.15,    # 跨维度相关性强度
}


def load_engine_config():
    """从 config.json 加载配置"""
    try:
        from core import config as cfg
        bd_cfg = cfg.get_section("behavior_decider")
        if bd_cfg:
            CONFIG.update({k: v for k, v in bd_cfg.items() if k in CONFIG})
    except Exception:
        pass
    # 加载持久化的行为历史
    _load_behavior_history()
    # 加载元认知覆盖版本历史
    _load_override_versions()


# ══════════════════════════════════════════════════════════════════════
# v3: 行为惯性持久化（跨会话不丢失）
# ══════════════════════════════════════════════════════════════════════

_behavior_history: dict = {}  # str → BehaviorState（延迟引用，dataclass 在下方定义）
_behavior_history_lock = threading.Lock()
_BEHAVIOR_HISTORY_FILE = "data/json/behavior_history.json"
_HISTORY_INERTIA_HOURS = 4


def _save_behavior_history():
    """持久化行为历史到 JSON"""
    try:
        with _behavior_history_lock:
            data = {}
            for uid, state in _behavior_history.items():
                data[uid] = {
                    "vector": state.vector,
                    "pattern": state.pattern,
                    "summary": state.summary,
                    "timestamp": time.time(),
                }
        if not data:
            return
        os.makedirs(os.path.dirname(_BEHAVIOR_HISTORY_FILE), exist_ok=True)
        with open(_BEHAVIOR_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[BD] 保存行为历史失败: {e}")


def _load_behavior_history():
    """从 JSON 恢复行为历史"""
    global _behavior_history
    try:
        if not os.path.exists(_BEHAVIOR_HISTORY_FILE):
            return
        with open(_BEHAVIOR_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        with _behavior_history_lock:
            for uid, info in data.items():
                state = BehaviorState(
                    vector=info.get("vector", {}),
                    pattern=info.get("pattern", ""),
                    summary=info.get("summary", ""),
                )
                _behavior_history[uid] = state
    except Exception as e:
        print(f"[BD] 加载行为历史失败: {e}")


def _get_hours_since_last(user_id: str) -> float:
    """计算距上次行为记录的小时数"""
    try:
        if not os.path.exists(_BEHAVIOR_HISTORY_FILE):
            return 4.0
        with open(_BEHAVIOR_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if user_id in data:
            ts = data[user_id].get("timestamp", 0)
            elapsed = time.time() - ts
            hours = elapsed / 3600
            return min(hours, 24)
    except Exception:
        pass
    return 4.0


# ══════════════════════════════════════════════════════════════════════
# v3: 异常行为冲突检测与介导
# ══════════════════════════════════════════════════════════════════════

# 冲突维度对定义（一个维度需要"介导"另一个维度的极端值）
_CONFLICT_PAIRS = [
    {
        "dims": ("approach", "sulkiness"),
        "names": ("接近度", "赌气度"),
        "desc": "想靠近但同时赌气——内心想在但表面有情绪",
        "mediated_desc": "你内心是想靠近的，但面上还有赌气的成分——"
                        "话里会有一点'我其实在意你但我不爽'的矛盾感",
        "mediation": "approach 下压 20%，sulkiness 上抬 15% → "
                     "产生'在意但不让步'的中间态",
    },
    {
        "dims": ("warmth", "tsundere"),
        "names": ("温度", "别扭度"),
        "desc": "温柔但同时别扭——明明心里是暖的，偏要嘴硬绕弯",
        "mediated_desc": "温柔和别扭同时在线——这是最人类的'嘴硬心软'状态，"
                        "一个说'没事'一个说'我有事'",
        "mediation": "取 warmth 和 (1-tsundere) 的均值作为'表达温度'，"
                     "保留内心的双重性",
    },
    {
        "dims": ("initiative", "sulkiness"),
        "names": ("主动度", "赌气度"),
        "desc": "想主动但又在赌气——开口和不开口在打架",
        "mediated_desc": "有主动的意图，但赌气让你不想先低头——"
                        "可能会用迂回的方式表达关注",
        "mediation": "initiative 下压 30%，产生'不直接主动但也不完全沉默'的状态",
    },
    {
        "dims": ("emotional_display", "verbosity"),
        "names": ("情绪外露度", "表达量"),
        "desc": "情绪汹涌但不想说——心里翻江倒海，嘴上只字不提",
        "mediated_desc": "你的情绪很满但选择不表达——话越少，每句话的份量越重",
        "mediation": "verbosity 维持低位，但 emotional_display 控制'那句少的话的力度'",
    },
    {
        "dims": ("clinginess", "honesty"),
        "names": ("依赖度", "坦率度"),
        "desc": "想黏人但不敢直说——需要对方但不会直接表达需要",
        "mediated_desc": "你想要关注，但不太会直接开口要——"
                        "会通过其他方式暗示，而不是直说'陪我'",
        "mediation": "clinginess 指向行动（靠近），honesty 指向表达（不说），"
                     "结果≈行动上有依赖但嘴上不承认",
    },
]

# 冲突阈值（两个维度都超过此阈值时触发介导）
_CONFLICT_THRESHOLD = 0.45


def _detect_conflict_pairs(vector: Dict[str, float]) -> List[dict]:
    """检测当前行为向量中的冲突组合"""
    conflicts = []
    for pair in _CONFLICT_PAIRS:
        d1, d2 = pair["dims"]
        v1 = vector.get(d1, 0.5)
        v2 = vector.get(d2, 0.5)
        if v1 > _CONFLICT_THRESHOLD and v2 > _CONFLICT_THRESHOLD:
            conflicts.append({
                **pair,
                "values": {d1: round(v1, 3), d2: round(v2, 3)},
            })
    return conflicts


def _resolve_conflicts(vector: Dict[str, float]) -> Dict[str, float]:
    """介导冲突维度：当两个冲突维度同时高时，取介导中间值。

    不是简单地降低其中一个，而是产生一种"矛盾但合理"的中间状态。
    """
    result = dict(vector)
    conflicts = _detect_conflict_pairs(vector)

    if not conflicts:
        return result

    for pair in conflicts:
        d1, d2 = pair["dims"]

        if pair["dims"] == ("approach", "sulkiness"):
            # 介导：approach 下压 20%，sulkiness 上抬 15%
            result[d1] = max(0.1, result[d1] * 0.8)
            result[d2] = min(1.0, result[d2] * 1.15)

        elif pair["dims"] == ("warmth", "tsundere"):
            # 介导：表达温度 = warmth 和 (1-tsundere) 的均值
            expressed_warmth = (vector[d1] + (1.0 - vector[d2])) * 0.5
            result[d1] = expressed_warmth

        elif pair["dims"] == ("initiative", "sulkiness"):
            # 介导：initiative 下压 30%
            result[d1] = max(0.1, result[d1] * 0.7)

        elif pair["dims"] == ("emotional_display", "verbosity"):
            # 介导：保持 verbosity 低位但用 emotional_display 控制力度
            if result[d2] < 0.35:
                result["pace"] = max(0.2, result.get("pace", 0.5) * 0.8)

        elif pair["dims"] == ("clinginess", "honesty"):
            # 介导：依赖走行动，坦率走表达，split
            pass

    return result


# ══════════════════════════════════════════════════════════════════════
# 12维行为空间定义
# ══════════════════════════════════════════════════════════════════════

@dataclass
class BehaviorDim:
    """一个行为维度"""
    key: str
    name: str                                       # 中文名
    description: str                                # 维度含义
    # 从心智维度的投影权重（正相关）
    pos_mind_weights: Dict[str, float] = field(default_factory=dict)
    # 从心智维度的投影权重（负相关）
    neg_mind_weights: Dict[str, float] = field(default_factory=dict)
    # 从躯体/生命状态的投影权重
    body_weights: Dict[str, float] = field(default_factory=dict)
    # 羁绊影响系数
    bond_influence: float = 0.0
    # 高值描述
    high_desc: str = ""
    # 低值描述
    low_desc: str = ""


BEHAVIOR_DIMS: Dict[str, BehaviorDim] = {
    # ── 1. 接近度 ──
    "approach": BehaviorDim(
        key="approach", name="接近度",
        description="想靠近对方的程度 ↔ 想保持距离",
        pos_mind_weights={"dependence": 0.35, "favoritism": 0.30, "joy": 0.15, "soul_resonance": 0.15},
        neg_mind_weights={"restraint": 0.25, "emptiness": 0.15, "relationship_fatigue": 0.20, "sensitivity_paranoia": 0.10},
        bond_influence=0.15,
        high_desc="会不自觉地想靠近，话里话外都有一种想多待一会儿的感觉",
        low_desc="下意识保持距离，不主动靠近，安静地待在自己的舒适区",
    ),
    # ── 2. 表达量 ──
    "verbosity": BehaviorDim(
        key="verbosity", name="表达量",
        description="说多少话 ↔ 沉默寡言",
        pos_mind_weights={"joy": 0.20, "life_vitality": 0.30, "emotional_volatility": 0.20},
        neg_mind_weights={"fatigue": 0.35, "restraint": 0.20, "misery": 0.15, "emptiness": 0.10},
        body_weights={"energy": 0.25, "body_tension": 0.12},
        bond_influence=0.08,
        high_desc="话比较多，愿意分享自己的想法和日常",
        low_desc="不想说太多，可能就回几个字，不是针对谁就是单纯懒得打",
    ),
    # ── 3. 温度 ──
    "warmth": BehaviorDim(
        key="warmth", name="温度",
        description="温柔体贴 ↔ 冷淡疏离",
        pos_mind_weights={"favoritism": 0.35, "emotional_healing": 0.25, "life_sense": 0.15, "healing_reflection": 0.15},
        neg_mind_weights={"chaotic_mood": 0.15, "misery": 0.20, "restraint": 0.15, "jealousy": 0.10},
        body_weights={"comfort": 0.10, "body_tension": 0.10},
        bond_influence=0.20,
        high_desc="语气温和，字里行间能感觉到关心和在意",
        low_desc="语气偏淡，没有太多温度，不是不喜欢就是暂时暖不起来",
    ),
    # ── 4. 坦率度 ──
    "honesty": BehaviorDim(
        key="honesty", name="坦率度",
        description="直说心里话 ↔ 拐弯抹角",
        pos_mind_weights={"autonomous_values": 0.30, "life_vitality": 0.20, "healing_reflection": 0.15},
        neg_mind_weights={"restraint": 0.40, "sensitivity_paranoia": 0.20, "misery": 0.10},
        bond_influence=0.10,
        high_desc="比较直接，心里想什么就说什么，不藏着掖着",
        low_desc="不太想直接表达，会绕一下、留一半，需要对方自己体会",
    ),
    # ── 5. 主动度 ──
    "initiative": BehaviorDim(
        key="initiative", name="主动度",
        description="发起话题/互动 ↔ 等着对方先开口",
        pos_mind_weights={"dependence": 0.30, "joy": 0.20, "life_vitality": 0.25, "favoritism": 0.15},
        neg_mind_weights={"restraint": 0.30, "sensitivity_paranoia": 0.15, "relationship_fatigue": 0.20, "loneliness": 0.05},
        bond_influence=0.12,
        high_desc="会主动开启话题、分享日常、表达关心",
        low_desc="不会主动发起互动，回应为主，等对方先开口",
    ),
    # ── 6. 依赖度 ──
    "clinginess": BehaviorDim(
        key="clinginess", name="依赖度",
        description="黏人/需要对方 ↔ 独立自处",
        pos_mind_weights={"dependence": 0.40, "favoritism": 0.20, "loneliness": 0.20},
        neg_mind_weights={"autonomous_values": 0.30, "life_sense": 0.20, "body_perception": 0.10, "relationship_fatigue": 0.10},
        bond_influence=0.10,
        high_desc="有点黏人，会主动找对方、想被关注和回应",
        low_desc="比较独立，不黏人，自己待着也挺好",
    ),
    # ── 7. 情绪外露度 ──
    "emotional_display": BehaviorDim(
        key="emotional_display", name="情绪外露度",
        description="情绪全写在脸上 ↔ 深藏不露",
        pos_mind_weights={"emotional_volatility": 0.35, "joy": 0.15, "chaotic_mood": 0.15, "life_vitality": 0.10},
        neg_mind_weights={"restraint": 0.35, "autonomous_values": 0.15, "healing_reflection": 0.10},
        bond_influence=0.10,
        high_desc="情绪藏不住，开心或不开心很容易被察觉到",
        low_desc="情绪收得比较好，外表看不出太多，但心里可能已经翻江倒海",
    ),
    # ── 8. 别扭度 ──
    "tsundere": BehaviorDim(
        key="tsundere", name="别扭度",
        description="口是心非/傲娇 ↔ 表里如一",
        pos_mind_weights={"jealousy": 0.25, "chaotic_mood": 0.20, "restraint": 0.25, "emotional_volatility": 0.15},
        neg_mind_weights={"emotional_healing": 0.20, "life_sense": 0.15, "healing_reflection": 0.10},
        bond_influence=-0.10,  # 越亲密反而越不别扭
        high_desc="会很别扭——明明在意偏要装不在意，被戳穿就嘴硬，其实漏洞百出",
        low_desc="比较坦诚，喜欢就说喜欢，不会故意说反话",
    ),
    # ── 9. 撒娇度 ──
    "playfulness": BehaviorDim(
        key="playfulness", name="撒娇度",
        description="撒娇卖萌 ↔ 正经严肃",
        pos_mind_weights={"joy": 0.30, "dependence": 0.15, "favoritism": 0.20, "life_vitality": 0.10},
        neg_mind_weights={"restraint": 0.30, "fatigue": 0.20, "autonomous_values": 0.15, "emptiness": 0.10},
        bond_influence=0.18,
        high_desc="会不自觉地撒娇、语气变软、带点小心思",
        low_desc="比较正经，不会刻意撒娇，该怎么说话就怎么说话",
    ),
    # ── 10. 赌气度 ──
    "sulkiness": BehaviorDim(
        key="sulkiness", name="赌气度",
        description="赌气/小情绪 ↔ 大气不计较",
        pos_mind_weights={"jealousy": 0.30, "misery": 0.20, "chaotic_mood": 0.25, "emotional_volatility": 0.15},
        neg_mind_weights={"emotional_healing": 0.25, "healing_reflection": 0.20, "life_sense": 0.15},
        bond_influence=-0.08,
        high_desc="有赌气的成分——不一定会明说，但说话带刺、冷淡、或者故意不回重点",
        low_desc="比较大气，不容易因为小事赌气",
    ),
    # ── 11. 认真度 ──
    "seriousness": BehaviorDim(
        key="seriousness", name="认真度",
        description="认真走心 ↔ 敷衍随口",
        pos_mind_weights={"emotional_healing": 0.20, "healing_reflection": 0.20, "favoritism": 0.20, "life_sense": 0.15, "years_precipitation": 0.10},
        neg_mind_weights={"fatigue": 0.30, "relationship_fatigue": 0.20, "emptiness": 0.15, "chaotic_mood": 0.10},
        bond_influence=0.12,
        high_desc="对待对方说的话很认真，会走心地回应",
        low_desc="有点敷衍，不是不在乎就是累了，随口应付一下",
    ),
    # ── 12. 回应节奏 ──
    "pace": BehaviorDim(
        key="pace", name="回应节奏",
        description="热切快回 ↔ 慢悠悠不着急",
        pos_mind_weights={"life_vitality": 0.30, "joy": 0.20, "dependence": 0.15, "emotional_volatility": 0.10},
        neg_mind_weights={"fatigue": 0.30, "restraint": 0.25, "emptiness": 0.15},
        body_weights={"energy": 0.15, "body_tension": 0.08},
        bond_influence=0.08,
        high_desc="回消息的意愿很强，节奏偏快",
        low_desc="不太急着回，慢悠悠的，有自己的节奏",
    ),
}


# ══════════════════════════════════════════════════════════════════════
# 核心决策引擎
# ══════════════════════════════════════════════════════════════════════

@dataclass
class BehaviorState:
    """一次行为决策的完整状态（v3: 含冲突检测）"""# 12维行为向量 [0, 1]
    vector: Dict[str, float] = field(default_factory=dict)
    # 每个维度的噪声水平（供调试）
    noise_levels: Dict[str, float] = field(default_factory=dict)
    # 采样前的基值
    base_values: Dict[str, float] = field(default_factory=dict)
    # 自然语言行为描述
    description: str = ""
    # 简短的摘要
    summary: str = ""
    # 整体行为模式标签
    pattern: str = ""
    # v3: 检测到的冲突对
    conflicts: List[dict] = field(default_factory=list)


def _sigmoid(x: float, steepness: float = 1.0) -> float:
    """
    S形平滑函数 → [0, 1]"""
    try:
        return 1.0 / (1.0 + math.exp(-x * steepness))
    except OverflowError:
        return 1.0 if x > 0 else 0.0


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _apply_projection_override(dim_key: str, mind_dim: str, base_weight: float,
                                user_id: str = None) -> float:
    """应用元认知运行时覆盖 + 动态学习权重到投影权重。
    让 LLM 可以根据对话历史调整"什么心智维度驱动什么行为"。
    同时集成 projection_learning 的在线学习结果。

    v3: 支持版本回退 — meta_cognition 每次校准生成新版本，
    可通过 rollback_projection_override() 回退到指定版本。
    """
    # 1. 元认知覆盖
    try:
        from engine import meta_cognition as mc
        overrides = mc.get_behavior_projection_overrides()
        if dim_key in overrides and mind_dim in overrides[dim_key]:
            base_weight = round(base_weight + overrides[dim_key][mind_dim], 4)
    except Exception:
        pass

    # 2. 动态学习权重（如果有 user_id）
    if user_id:
        try:
            from engine.behavior import projection_learning as pl
            adjusted = pl.get_weight(user_id, base_weight, dim_key, mind_dim)
            return round(adjusted, 4)
        except Exception:
            pass

    return base_weight


# ── v3: 元认知覆盖版本控制 ──

_OVERRIDE_VERSIONS: Dict[str, List[dict]] = {}  # dim_key → [{"version": int, "overrides": dict, "timestamp": float}]
_OVERRIDE_VERSIONS_LOCK = threading.Lock()
_OVERRIDE_VERSION_FILE = "data/json/projection_version_history.json"


def _save_override_versions():
    try:
        with _OVERRIDE_VERSIONS_LOCK:
            data = dict(_OVERRIDE_VERSIONS)
        if not data:
            return
        os.makedirs(os.path.dirname(_OVERRIDE_VERSION_FILE), exist_ok=True)
        with open(_OVERRIDE_VERSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _load_override_versions():
    global _OVERRIDE_VERSIONS
    try:
        if not os.path.exists(_OVERRIDE_VERSION_FILE):
            return
        with open(_OVERRIDE_VERSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        with _OVERRIDE_VERSIONS_LOCK:
            _OVERRIDE_VERSIONS = {}
            for dim_key, versions in data.items():
                _OVERRIDE_VERSIONS[dim_key] = [
                    {"version": v["version"], "overrides": v["overrides"],
                     "timestamp": v.get("timestamp", 0)}
                    for v in versions
                ]
    except Exception:
        pass


def snapshot_projection_overrides():
    """对当前元认知覆盖做快照（每次校准新版本）"""
    try:
        from engine import meta_cognition as mc
        overrides = mc.get_behavior_projection_overrides()
    except Exception:
        return

    version = int(time.time())
    with _OVERRIDE_VERSIONS_LOCK:
        for dim_key, params in overrides.items():
            if dim_key not in _OVERRIDE_VERSIONS:
                _OVERRIDE_VERSIONS[dim_key] = []
            _OVERRIDE_VERSIONS[dim_key].append({
                "version": version,
                "overrides": dict(params),
                "timestamp": time.time(),
            })
            # 只保留最近 10 个版本
            if len(_OVERRIDE_VERSIONS[dim_key]) > 10:
                _OVERRIDE_VERSIONS[dim_key] = _OVERRIDE_VERSIONS[dim_key][-10:]
    _save_override_versions()


def rollback_projection_override(dim_key: str, target_version: int) -> bool:
    """回退指定维度的覆盖到指定版本。
    返回是否成功。
    """
    with _OVERRIDE_VERSIONS_LOCK:
        if dim_key not in _OVERRIDE_VERSIONS:
            return False
        versions = _OVERRIDE_VERSIONS[dim_key]
        target = None
        for v in versions:
            if v["version"] == target_version:
                target = v
                break
        if not target:
            return False

        # 从 target 重建覆盖
        try:
            from engine import meta_cognition as mc
            params = mc.get_behavior_projection_overrides()
            mc._runtime_params["behavior_projection"][dim_key] = dict(target["overrides"])
            mc._save_runtime_params()
            return True
        except Exception:
            return False


def get_override_versions(dim_key: str = None) -> dict:
    """获取覆盖版本历史"""
    with _OVERRIDE_VERSIONS_LOCK:
        if dim_key:
            return {dim_key: list(_OVERRIDE_VERSIONS.get(dim_key, []))}
        return dict(_OVERRIDE_VERSIONS)


def _compute_base_value(dim: BehaviorDim, mind: dict, body_state: dict = None,
                        bond_level: float = 0.3, stage: str = "", 
                        user_id: str = None) -> float:
    """从内部状态计算行为维度的基值（投影模型，无阈值）
    : 投影权重支持元认知运行时覆盖 + 动态学习权重
    """
    if body_state is None:
        body_state = {}

    raw = 0.0

    # 心智维度正投影（: 权重可被元认知覆盖 + 动态学习）
    for d, w in dim.pos_mind_weights.items():
        effective_w = _apply_projection_override(dim.key, d, w, user_id)
        raw += mind.get(d, 0.5) * effective_w

    # 心智维度负投影（: 权重可被元认知覆盖 + 动态学习）
    for d, w in dim.neg_mind_weights.items():
        effective_w = _apply_projection_override(dim.key, d, w, user_id)
        raw -= mind.get(d, 0.3) * effective_w

    # 躯体状态投影（fix: 正确获取字段值）
    for d, w in dim.body_weights.items():
        if d == "energy":
            raw += body_state.get("energy", 0.5) * w
        elif d == "comfort":
            raw += body_state.get("comfort", 0.5) * w
        elif d == "body_tension":
            # body_tension 是体感名字，映射到松弛度
            tension_map = {
                "轻松舒适": 0.8, "温暖柔软": 0.9, "慢慢回温": 0.6,
                "慵懒放空": 0.5, "安静内收": 0.35,
                "沉重乏力": 0.2, "胸闷压抑": 0.15, "紧绷不安": 0.1,
            }
            sensation = body_state.get("body_tension", "轻松舒适")
            raw += tension_map.get(sensation, 0.5) * w
        else:
            raw += body_state.get(d, 0.5) * w

    # 羁绊影响
    raw += bond_level * dim.bond_influence

    # 成长阶段微调
    if stage:
        stage_adjust = {
            "青涩试探": -0.06, "拘谨礼貌": -0.03,
            "松弛默契": 0.02, "成熟珍惜": 0.04, "平淡安稳": 0.01,
        }.get(stage, 0.0)
        raw += stage_adjust

    # Sigmoid压缩到 [0, 1]（注意中心偏移使大多数值在中段）
    normalized = _sigmoid(raw - 0.3, steepness=2.5)

    return _clamp(normalized, 0.01, 0.99)


def _compute_noise_scale(mind: dict, dim_key: str) -> float:
    """状态依赖噪声：情绪越波动，噪声越大
    某些维度天然比别的维度更稳定
    """
    base_noise = CONFIG["base_noise"]
    volatility = mind.get("emotional_volatility", 0.3)
    chaotic = mind.get("chaotic_mood", 0.25)
    fatigue = mind.get("fatigue", 0.25)

    # 基础噪声 + 波动放大
    noise = base_noise + volatility * CONFIG["volatility_scale"]

    # 混沌情绪加大噪声
    noise += chaotic * 0.04

    # 疲惫时某些维度更稳定（因为懒），某些更不稳定（因为烦躁）
    stable_when_tired = {"verbosity", "initiative", "pace"}
    unstable_when_tired = {"sulkiness", "tsundere", "honesty"}
    if dim_key in stable_when_tired:
        noise -= fatigue * 0.02
    elif dim_key in unstable_when_tired:
        noise += fatigue * 0.03

    # 维度天然稳定性
    dim_stability = {
        "approach": 0.9, "verbosity": 0.85, "warmth": 0.7,
        "honesty": 0.8, "initiative": 0.85, "clinginess": 0.8,
        "emotional_display": 0.6, "tsundere": 0.65, "playfulness": 0.75,
        "sulkiness": 0.7, "seriousness": 0.75, "pace": 0.85,
    }
    noise *= (1.0 / dim_stability.get(dim_key, 0.8))

    return max(0.01, noise)


def _apply_correlations(vector: Dict[str, float]) -> Dict[str, float]:
    """应用跨维度自然相关性（使行为不是12个独立变量）
    """
    strength = CONFIG["correlation_strength"]
    corr = dict(vector)

    # 正相关对（一个高，另一个也倾向于高）
    positive_pairs = [
        ("approach", "warmth"), ("approach", "initiative"),
        ("warmth", "seriousness"), ("warmth", "honesty"),
        ("clinginess", "emotional_display"), ("tsundere", "sulkiness"),
        ("playfulness", "approach"), ("playfulness", "emotional_display"),
        ("verbosity", "initiative"), ("pace", "initiative"),
        ("honesty", "emotional_display"),
    ]
    for a, b in positive_pairs:
        avg = (corr[a] + corr[b]) / 2
        corr[a] += (avg - corr[a]) * strength
        corr[b] += (avg - corr[b]) * strength

    # 负相关对（一个高，另一个倾向于低）
    negative_pairs = [
        ("tsundere", "honesty"), ("sulkiness", "warmth"),
        ("tsundere", "warmth"), ("clinginess", "seriousness"),
    ]
    for a, b in negative_pairs:
        diff = abs(corr[a] - corr[b])
        if corr[a] > corr[b]:
            corr[a] -= diff * strength * 0.5
            corr[b] += diff * strength * 0.5
        else:
            corr[b] -= diff * strength * 0.5
            corr[a] += diff * strength * 0.5

    # 再夹回 [0, 1]
    return {k: _clamp(v) for k, v in corr.items()}


def _apply_history_inertia(current: Dict[str, float],
                           previous: Dict[str, float],
                           mind: dict,
                           hours_since_last: float = 1.0) -> Dict[str, float]:
    """行为惯性：当前行为受历史行为影响，防止突兀跳变。
    hours_since_last: 距离上次交互的小时数，越久惯性越小。
    """
    if not previous:
        return current

    inertia = CONFIG["inertia_factor"]
    # 时间衰减
    decay_half = CONFIG["history_decay_hours"]
    time_decay = 0.5 ** (hours_since_last / decay_half) if decay_half > 0 else 0.5
    effective_inertia = inertia * time_decay

    # 情绪波动越大，惯性越小（情绪上头行为变化快）
    volatility = mind.get("emotional_volatility", 0.3)
    effective_inertia *= (1.0 - volatility * 0.6)

    result = {}
    for key in current:
        if key in previous:
            result[key] = (current[key] * (1 - effective_inertia) +
                          previous[key] * effective_inertia)
        else:
            result[key] = current[key]

    return result


def decide_behavior(
    mind: dict,
    body_state: dict = None,
    bond_level: float = 0.3,
    stage: str = "",
    comprehension: dict = None,
    active_flaws: list = None,
    previous_behavior: Dict[str, float] = None,
    hours_since_last: float = 1.0,
    user_id: str = None,
) -> BehaviorState:
    """内生行为决策主函数。

    输入：
      - mind: 24维心智状态
      - body_state: 躯体状态
      - bond_level: 羁绊等级
      - stage: 成长阶段
      - comprehension: 理解层洞察（只用于微调，不取代内生驱动）
      - active_flaws: 活跃瑕疵列表
      - previous_behavior: 上一次行为向量（用于惯性计算）
      - hours_since_last: 距上次交互时间

    输出：
      BehaviorState: 包含行为向量 + 自然语言描述

    注意：comprehension 只用于轻度偏移（±0.05），不取代内生状态的决定性地位。
    """
    if not CONFIG["enabled"]:
        return BehaviorState(description="")

    state = BehaviorState()
    base = {}
    noise_levels = {}

    # ═══ Step 1: 计算基值（内生投影 + 动态学习权重）════
    for key, dim in BEHAVIOR_DIMS.items():
        base[key] = _compute_base_value(dim, mind, body_state, bond_level, stage, user_id)
        noise_levels[key] = _compute_noise_scale(mind, key)

    # ═══ Step 2: 理解层轻量偏移（±0.05，不主导）════
    if comprehension and comprehension.get("confidence", 0) > 0.4:
        offset = _comprehension_offset(comprehension.get("intent", ""),
                                       comprehension.get("true_emotion", ""),
                                       comprehension.get("what_they_need", ""))
        for key in BEHAVIOR_DIMS:
            if key in offset:
                base[key] = _clamp(base[key] + offset[key])

    state.base_values = dict(base)

    # ═══ Step 3: 高斯混合采样（同状态可不同输出）════
    vector = {}
    for key in BEHAVIOR_DIMS:
        # 三个采样点做混合
        samples = []
        for _ in range(CONFIG["sample_count"]):
            noise = random.gauss(0, noise_levels[key])
            s = base[key] + noise
            s = _clamp(s)
            samples.append(s)
        # 中值稳健估计（trimmed mean：去掉最极端的）
        samples.sort()
        if len(samples) >= 3:
            vector[key] = sum(samples[1:-1]) / (len(samples) - 2) if len(samples) > 2 else samples[1]
        else:
            vector[key] = sum(samples) / len(samples)

    # ═══ Step 4: 瑕疵强度微调（：基于强度连续值，非列表）═══
    if active_flaws is not None:
        vector = _apply_flaw_modifications(vector, active_flaws)

    # ═══ Step 5: 跨维度相关性 ═══
    vector = _apply_correlations(vector)

    # ═══ Step 5b: 异常行为冲突介导（v3）═══
    conflicts = _detect_conflict_pairs(vector)
    if conflicts:
        vector = _resolve_conflicts(vector)

    # ═══ Step 6: 历史惯性 ═══
    vector = _apply_history_inertia(vector, previous_behavior, mind, hours_since_last)

    # ═══ Step 7: 羁绊行为偏向（: 之前断裂，bond→behavior从未生效）═══
    try:
        from engine import bond as bond_module
        bond_bias = bond_module.get_bond_behavior_bias(mind)
        for dim_key, bias_val in bond_bias.items():
            if dim_key in vector:
                vector[dim_key] = _clamp(vector[dim_key] + bias_val)
    except Exception:
        pass

    # ═══ Step 7b: 双标硬约束（v3: 代码级双标执行，非prompt建议）═══
    try:
        from engine import bond as bond_module
        bp = bond_module.compute_bond_privileges(mind)
        vector = bond_module.apply_double_standard_constraint(vector, bp)
    except Exception:
        pass

    # ═══ Step 7c: 阶段特有行为策略（v3）═══
    if user_id:
        try:
            from engine.life import growth as growth_module
            stage_offset = growth_module.get_stage_behavior_config(user_id)
            for dim_key, offset_val in stage_offset.items():
                if dim_key in vector:
                    vector[dim_key] = _clamp(vector[dim_key] + offset_val)
        except Exception:
            pass

    # ═══ Step 7d: L1 反射校准（0 LLM，0延迟，每次响应自动微调）═══
    if comprehension:
        vector = _reflex_calibration(vector, mind, comprehension)

    state.vector = vector
    state.noise_levels = noise_levels
    state.conflicts = conflicts

    # ═══ Step 8: 生成自然语言描述 ═══
    state.description = _generate_description(vector, mind)
    state.summary = _generate_summary(vector)
    state.pattern = _classify_pattern(vector)

    return state


def _comprehension_offset(intent: str, true_emotion: str, need: str) -> Dict[str, float]:
    """理解层→行为的极轻偏移（±0.05，仅微调）"""
    offset = {}

    if intent == "倾诉":
        offset.update({"warmth": 0.03, "seriousness": 0.03, "approach": 0.02})
    elif intent == "敷衍":
        offset.update({"verbosity": -0.03, "seriousness": -0.04, "initiative": -0.02})
    elif intent == "撒娇":
        offset.update({"playfulness": 0.04, "approach": 0.03, "tsundere": -0.02})
    elif intent == "试探":
        offset.update({"honesty": -0.03, "tsundere": 0.02, "approach": -0.02})

    if true_emotion in ("难过", "低落"):
        offset.update({"warmth": 0.04, "seriousness": 0.03, "playfulness": -0.02})
    elif true_emotion == "生气":
        offset.update({"sulkiness": 0.04, "warmth": -0.03, "honesty": 0.02})
    elif true_emotion == "兴奋":
        offset.update({"verbosity": 0.03, "emotional_display": 0.03, "playfulness": 0.02})

    if need == "空间":
        offset.update({"approach": -0.04, "verbosity": -0.04, "initiative": -0.03, "clinginess": -0.03})
    elif need == "安慰":
        offset.update({"warmth": 0.04, "seriousness": 0.03, "approach": 0.03})

    return offset


def _apply_flaw_modifications(vector: Dict[str, float], flaws) -> Dict[str, float]:
    """瑕疵对行为的轻量扰动（强度版）。

    支持两种输入：
      - Dict[str, float]: 瑕疵强度值 → 使用 flaws.py 的 get_flaw_behavior_modifiers
      - List[str]: 瑕疵名称列表 → 旧版兼容（从列表构造近似强度）
    """
    try:
        from engine import flaws as flaws_module

        if isinstance(flaws, dict):
            # 强度值版本（优先）
            modifiers = flaws_module.get_flaw_behavior_modifiers(flaws)
        elif isinstance(flaws, list) and flaws:
            # 列表版本（向后兼容：构造近似强度）
            intensities = {}
            for name in flaws:
                if name in flaws_module.FLAW_TYPES:
                    intensities[name] = flaws_module.FLAW_TYPES[name].get("base_intensity", 0.35)
            modifiers = flaws_module.get_flaw_behavior_modifiers(intensities)
        else:
            return dict(vector)
    except ImportError:
        return dict(vector)

    # 应用修正
    v = dict(vector)
    for dim_key, delta in modifiers.items():
        if dim_key in v:
            v[dim_key] = _clamp(v[dim_key] + delta)

    return v


# ══════════════════════════════════════════════════════════════════════
# L1 反射校准 — 毫秒级规则引擎（0 LLM 调用）
# ══════════════════════════════════════════════════════════════════════

def _reflex_calibration(vector: Dict[str, float], mind: dict,
                         comprehension: dict) -> Dict[str, float]:
    """毫秒级反射式行为校准——基于硬规则，无 LLM 调用。

    当 comprehension 中检测到特定模式时，直接微调行为向量。
    所有规则都是"如果…就…"的一阶逻辑，延迟 <0.1ms。
    """
    v = dict(vector)
    raw_msg = comprehension.get("raw_message", "")
    intent = comprehension.get("intent", "")
    emotion = comprehension.get("true_emotion", "")
    confidence = comprehension.get("confidence", 0)

    # 规则1: 用户连续短消息(<=2字) → 降低表达量 + 升高温度
    if len(raw_msg) <= 2 and confidence > 0.4:
        v["verbosity"] = max(0.1, v["verbosity"] - 0.12)
        v["warmth"] = min(0.9, v["warmth"] + 0.08)

    # 规则2: 用户消息含强烈否定词 → 抬高认真度 + 降低冲动
    if re.search(r"不|别|少|烦|滚|停", raw_msg):
        v["seriousness"] = min(0.9, v["seriousness"] + 0.10)
        v["sulkiness"] = min(0.8, v["sulkiness"] + 0.06)

    # 规则3: 疲劳 > 0.7 且 用户消息 < 5字 → 启用极简模式
    if mind.get("fatigue", 0) > 0.7 and len(raw_msg) < 5:
        v["verbosity"] = min(v["verbosity"], 0.20)
        v["emotional_display"] = min(v["emotional_display"], 0.25)

    # 规则4: 用户情绪为"难过/低落" → 升高温度 + 降低赌气
    if emotion in ("难过", "低落", "焦虑"):
        v["warmth"] = min(0.95, v["warmth"] + 0.10)
        v["sulkiness"] = max(0.0, v["sulkiness"] - 0.08)
        v["seriousness"] = min(0.95, v["seriousness"] + 0.08)

    # 规则5: 用户消息含"你"且为问句 → 升高主动度 + 表达量
    if "你" in raw_msg and ("?" in raw_msg or "？" in raw_msg or "吗" in raw_msg):
        v["initiative"] = min(0.85, v["initiative"] + 0.06)
        v["verbosity"] = min(0.85, v["verbosity"] + 0.05)

    # 规则6: 用户活跃情绪(开心/兴奋) → 升高玩耍度 + 节奏
    if emotion in ("开心", "兴奋", "温暖"):
        v["playfulness"] = min(0.9, v["playfulness"] + 0.07)
        v["pace"] = min(0.9, v["pace"] + 0.05)

    return v


# ══════════════════════════════════════════════════════════════════════
# 自然语言生成（非模板，基于行为向量动态构造）
# ══════════════════════════════════════════════════════════════════════

def _generate_description(vector: Dict[str, float], mind: dict) -> str:
    """将行为向量转为流畅的自然语言描述。
    不是模板填充，而是根据向量各维度的值动态构建语句。
    """
    lines = ["【内生行为状态】"]

    # 整体基调判定
    pattern_line = _build_pattern_line(vector)
    if pattern_line:
        lines.append(pattern_line)

    # 挑选最显著的3-5个维度描述（避免平均化、没有重点）
    significant = _pick_significant_dims(vector, top_n=4)
    for dim_key, val in significant:
        dim = BEHAVIOR_DIMS[dim_key]
        if val > 0.65:
            lines.append(f"· {dim.name}偏高({val:.2f})：{dim.high_desc}")
        elif val < 0.35:
            lines.append(f"· {dim.name}偏低({val:.2f})：{dim.low_desc}")
        else:
            # 中段不需要特别强调，但如果中段的维度恰好是关键对立面就提一下
            pass

    # 矛盾点（两个对立维度同时不低，是真实人性的表现）
    conflict = _detect_conflicts(vector)
    if conflict:
        lines.append(f"· 矛盾共存：{conflict}")

    # 关键提示
    lines.append("（以上是你当前内在状态的投射，不是台词模板。自然地让这些特质融入表达，不做作。）")

    return "\n".join(lines)


def _build_pattern_line(vector: Dict[str, float]) -> str:
    """根据向量构建整体模式描述"""
    approach = vector.get("approach", 0.5)
    warmth = vector.get("warmth", 0.5)
    verbosity = vector.get("verbosity", 0.5)
    tsundere = vector.get("tsundere", 0.3)
    sulkiness = vector.get("sulkiness", 0.3)

    if approach > 0.6 and warmth > 0.6:
        return "整体基调：主动亲近、温和柔软——你此刻是打开的、愿意靠近的。"
    elif approach > 0.6 and warmth < 0.4:
        return "整体基调：想靠近但热不起来——你在意，但表达方式偏冷。"
    elif approach < 0.35 and warmth < 0.35:
        return "整体基调：疏离冷淡——你此刻需要自己的空间，不想被打扰。"
    elif approach < 0.35 and warmth > 0.6:
        return "整体基调：保持距离但心里是暖的——不是不想靠近，是不能/不敢。"
    elif tsundere > 0.5:
        return "整体基调：别扭模式——明明在意，偏要绕个弯说。"
    elif sulkiness > 0.5:
        return "整体基调：赌气模式——有情绪但不会明说，话里带刺或刻意冷淡。"
    elif verbosity < 0.3:
        return "整体基调：沉默模式——不想说太多，不是不在乎就是真的累。"
    else:
        return "整体基调：自然随性——没有特别明显的倾向，跟着感觉走。"


def _pick_significant_dims(vector: Dict[str, float], top_n: int = 4) -> List[Tuple[str, float]]:
    """挑选当前最显著的维度（偏离中值最远的）"""
    deviations = [(k, abs(v - 0.5)) for k, v in vector.items() if k in BEHAVIOR_DIMS]
    deviations.sort(key=lambda x: x[1], reverse=True)
    selected = deviations[:top_n]
    # 恢复原始值
    return [(k, vector[k]) for k, _ in selected]


def _detect_conflicts(vector: Dict[str, float]) -> str:
    """检测行为向量中同时存在的矛盾对"""
    conflicts = []

    # 想靠近但嘴硬
    if vector.get("approach", 0.5) > 0.55 and vector.get("tsundere", 0.3) > 0.4:
        conflicts.append("想靠近又不肯直说")

    # 温柔但赌气
    if vector.get("warmth", 0.5) > 0.55 and vector.get("sulkiness", 0.3) > 0.35:
        conflicts.append("外表温柔、心里憋着气")

    # 黏人但克制
    if vector.get("clinginess", 0.4) > 0.5 and vector.get("honesty", 0.5) < 0.4:
        conflicts.append("想黏又不敢黏")

    # 想表达但选择沉默
    if vector.get("emotional_display", 0.4) > 0.55 and vector.get("verbosity", 0.5) < 0.35:
        conflicts.append("心里很多话但说得很少")

    # 认真但敷衍
    if vector.get("seriousness", 0.5) > 0.6 and vector.get("verbosity", 0.5) < 0.3:
        conflicts.append("很认真但表达不出来")

    if conflicts:
        return "、".join(conflicts[:2])
    return ""


def _generate_summary(vector: Dict[str, float]) -> str:
    """一句话摘要"""
    approach = vector.get("approach", 0.5)
    warmth = vector.get("warmth", 0.5)
    verbosity = vector.get("verbosity", 0.5)
    tsundere = vector.get("tsundere", 0.3)

    if approach > 0.6 and warmth > 0.6:
        return "主动亲近的温柔模式"
    elif tsundere > 0.5:
        return "别扭傲娇模式"
    elif approach < 0.3 and verbosity < 0.3:
        return "沉默疏离模式"
    elif verbosity < 0.3:
        return "寡言少语模式"
    elif approach > 0.6:
        return "主动靠近模式"
    elif warmth > 0.6:
        return "温柔体贴模式"
    else:
        return "随性自然模式"


def _classify_pattern(vector: Dict[str, float]) -> str:
    """行为模式标签"""
    scores = {
        "温柔黏人": vector.get("warmth", 0.5) * 0.4 + vector.get("clinginess", 0.4) * 0.3 + vector.get("approach", 0.5) * 0.3,
        "别扭傲娇": vector.get("tsundere", 0.3) * 0.5 + (1.0 - vector.get("honesty", 0.5)) * 0.5,
        "冷淡疏离": (1.0 - vector.get("approach", 0.5)) * 0.4 + (1.0 - vector.get("warmth", 0.5)) * 0.4 + (1.0 - vector.get("verbosity", 0.5)) * 0.2,
        "赌气闷闷": vector.get("sulkiness", 0.3) * 0.6 + (1.0 - vector.get("warmth", 0.5)) * 0.4,
        "活泼开朗": vector.get("playfulness", 0.4) * 0.3 + vector.get("verbosity", 0.5) * 0.4 + vector.get("emotional_display", 0.4) * 0.3,
        "认真深沉": vector.get("seriousness", 0.5) * 0.5 + (1.0 - vector.get("verbosity", 0.5)) * 0.3 + vector.get("honesty", 0.5) * 0.2,
        "随性自然": 0.5,  # 基线
    }
    return max(scores, key=scores.get)


# ══════════════════════════════════════════════════════════════════════
# 对外接口
# ══════════════════════════════════════════════════════════════════════

# 行为历史缓存（按 user_id）— v3: 由 _load/save_behavior_history 管理


def decide(
    user_id: str,
    mind: dict,
    body_state: dict = None,
    bond_level: float = 0.3,
    stage: str = "",
    comprehension: dict = None,
    active_flaws: list = None,
) -> BehaviorState:
    """对外统一接口：执行内生行为决策（v3: 持久化历史）。

    Args:
        user_id: 用户 ID（用于追踪行为历史）
        mind: 24维心智状态
        body_state: 躯体状态 dict 或 None
        bond_level: 羁绊等级
        stage: 成长阶段名称
        comprehension: 理解层洞察（轻量偏移用）
        active_flaws: 活跃瑕疵列表

    Returns:
        BehaviorState: 包含行为向量 + 自然语言描述 + 模式标签
    """
    previous = None
    hours_since_last = _get_hours_since_last(user_id)

    with _behavior_history_lock:
        if user_id in _behavior_history:
            prev_state = _behavior_history[user_id]
            previous = prev_state.vector

    state = decide_behavior(
        mind=mind,
        body_state=body_state,
        bond_level=bond_level,
        stage=stage,
        comprehension=comprehension,
        active_flaws=active_flaws,
        previous_behavior=previous,
        hours_since_last=hours_since_last,
        user_id=user_id,
    )

    # 行为模式沙盒介入 ── 匹配的沙盒模式微调行为向量
    try:
        from engine.behavior import behavior_sandbox as sandbox
        context_str = comprehension.get("intent", "") + " " + comprehension.get("true_emotion", "") if comprehension else ""
        adjusted = sandbox.apply_sandbox_to_behavior(state.vector, user_id, context_str)
        if adjusted != state.vector:
            state.vector = adjusted
            # 重新生成描述和模式标签
            desc_parts = []
            for dim_key, val in sorted(state.vector.items()):
                dim = BEHAVIOR_DIMS.get(dim_key)
                if not dim:
                    continue
                if val > 0.6:
                    desc_parts.append(dim.high_desc)
                elif val < 0.4:
                    desc_parts.append(dim.low_desc)
            state.description = "；".join(desc_parts) if desc_parts else "平常心"
            state.pattern = _deduce_pattern(state.vector)
            state.summary = _summarize_behavior(state.vector)
    except Exception:
        pass

    # 缓存并持久化本次行为状态
    with _behavior_history_lock:
        _behavior_history[user_id] = state
    _save_behavior_history()

    return state


def get_behavior_instruction(
    user_id: str,
    mind: dict,
    body_state: dict = None,
    bond_level: float = 0.3,
    stage: str = "",
    comprehension: dict = None,
    active_flaws: list = None,
) -> str:
    """快捷接口：直接返回可注入 system prompt 的行为描述文本。
    """
    state = decide(user_id, mind, body_state, bond_level, stage, comprehension, active_flaws)
    return state.description


def get_behavior_vector(
    user_id: str,
    mind: dict,
    body_state: dict = None,
    bond_level: float = 0.3,
    stage: str = "",
    comprehension: dict = None,
    active_flaws: list = None,
) -> Dict[str, float]:
    """快捷接口：直接返回12维行为向量。
    """
    state = decide(user_id, mind, body_state, bond_level, stage, comprehension, active_flaws)
    return state.vector


# ══════════════════════════════════════════════════════════════════════
# P2-3: 对外行为路径（可追溯的决策链路）
# ══════════════════════════════════════════════════════════════════════

def get_behavior_path(
    user_id: str,
    mind: dict,
    body_state: dict = None,
    bond_level: float = 0.3,
    stage: str = "",
    comprehension: dict = None,
    active_flaws: list = None,
) -> dict:
    """输出完整的决策链路：从原始输入 → 中间处理 → 最终行为。

    每个阶段都有"前状态→干预→后状态"的可追溯差异，
    让系统行为不再是黑盒。
    """
    path = {
        "input": {
            "mind_dims": {k: round(v, 3) for k, v in mind.items() if isinstance(v, float)},
            "bond_level": round(bond_level, 3),
            "stage": stage,
        },
        "stages": [],
        "output": {},
    }

    # Stage 1: 基础值计算
    base = {}
    for dim in BEHAVIOR_DIMS:
        base[dim.key] = round(
            _compute_base_value(dim, mind, body_state, bond_level, stage),
            4
        )
    path["stages"].append({
        "name": "基础值",
        "description": "24维心智 → 12维行为的基础投影",
        "before": {},
        "after": dict(base),
    })

    # Stage 2: 理解层偏移
    comp_offset = _comprehension_offset(
        comprehension.get("intent", "") if comprehension else "",
        comprehension.get("true_emotion", "") if comprehension else "",
        comprehension.get("what_they_need", "") if comprehension else "",
    ) if comprehension else {}
    if comp_offset:
        offset_applied = dict(base)
        for k, v in comp_offset.items():
            if k in offset_applied:
                offset_applied[k] = round(offset_applied[k] + v, 4)
        path["stages"].append({
            "name": "理解偏移",
            "description": f"基于'{comprehension.get('intent','')}'理解层洞察的行为微调",
            "before": dict(base),
            "after": dict(offset_applied),
            "deltas": comp_offset,
        })
        base = offset_applied

    # Stage 3: 瑕疵修改
    if active_flaws:
        flaw_applied = _apply_flaw_modifications(dict(base), active_flaws)
        deltas = {k: round(flaw_applied[k] - base.get(k, 0), 4) for k in flaw_applied}
        path["stages"].append({
            "name": "瑕疵扰动",
            "description": f"活跃瑕疵: {active_flaws}",
            "before": dict(base),
            "after": dict(flaw_applied),
            "deltas": deltas,
        })
        base = flaw_applied

    # Stage 4: 相关性
    corr_applied = _apply_correlations(dict(base))
    corr_deltas = {k: round(corr_applied[k] - base.get(k, 0), 4) for k in corr_applied}
    path["stages"].append({
        "name": "跨维关联",
        "description": "维度间的统计相关性耦合",
        "before": dict(base),
        "after": dict(corr_applied),
        "deltas": {k: v for k, v in corr_deltas.items() if abs(v) > 0.01},
    })
    base = corr_applied

    # Stage 5: 噪声注入
    noise_applied = dict(base)
    noise_scale = _compute_noise_scale(mind, "")
    for k in noise_applied:
        n = _gauss_noise(noise_scale)
        noise_applied[k] = round(noise_applied[k] + n, 4)
    path["stages"].append({
        "name": "混沌注入",
        "description": f"噪声σ={noise_scale:.3f}",
        "before": dict(base),
        "after": dict(noise_applied),
    })
    base = noise_applied

    # Stage 6: 行为惯性
    previous = None
    if user_id in _behavior_history:
        previous = _behavior_history[user_id].vector
    if previous:
        inertia_applied = _apply_history_inertia(dict(base), previous, 1.0)
        path["stages"].append({
            "name": "行为惯性",
            "description": "历史行为的平滑延续",
            "before": dict(base),
            "after": dict(inertia_applied),
        })
        base = inertia_applied

    # 输出
    for k in base:
        base[k] = round(_clamp(float(base.get(k, 0))), 4)
    path["output"] = {
        "vector": dict(base),
        "pattern": _classify_pattern(base),
        "top_dims": _pick_significant_dims(base),
    }

    return path


# ══════════════════════════════════════════════════════════════════════
# 习惯形成追踪
# ══════════════════════════════════════════════════════════════════════

HABIT_THRESHOLD = 3

_HABIT_CLUSTERS = {
    "主动亲近": {"approach": (0.6, 1.0), "warmth": (0.5, 1.0)},
    "保持距离": {"approach": (0.0, 0.35), "warmth": (0.0, 0.4)},
    "话多表达": {"verbosity": (0.6, 1.0)},
    "沉默寡言": {"verbosity": (0.0, 0.35)},
    "温柔柔和": {"warmth": (0.6, 1.0), "aggression": (0.0, 0.3)},
    "赌气别扭": {"sulkiness": (0.5, 1.0), "seriousness": (0.4, 1.0)},
    "活泼轻快": {"pace": (0.55, 1.0), "playfulness": (0.5, 1.0)},
    "依赖黏人": {"approach": (0.55, 1.0), "dependence": (0.5, 1.0)},
    "克制冷静": {"restraint": (0.55, 1.0), "seriousness": (0.5, 1.0)},
}


def detect_habit(user_id: str, behavior_vector: Dict[str, float]) -> str:
    """检测当前行为向量是否属于某个习惯模式"""
    if not behavior_vector:
        return ""

    for habit_name, dims in _HABIT_CLUSTERS.items():
        match = True
        for dim, (lo, hi) in dims.items():
            val = behavior_vector.get(dim, 0.5)
            if not (lo <= val <= hi):
                match = False
                break
        if match:
            return habit_name
    return ""


def track_habit(user_id: str, behavior_vector: Dict[str, float]):
    """追踪和更新习惯streak"""
    habit_name = detect_habit(user_id, behavior_vector)
    if not habit_name:
        return

    from core import database as db
    streak = db.get_habit_streak(user_id, habit_name)
    if streak >= HABIT_THRESHOLD:
        # 已经是习惯，继续保持
        db.update_habit_streak(user_id, habit_name, behavior_vector, increment=True)
    else:
        db.update_habit_streak(user_id, habit_name, behavior_vector, increment=True)


def apply_habit_inertia(user_id: str, behavior_vector: Dict[str, float]) -> Dict[str, float]:
    """习惯惯性：连续多次相同行为→该行为对决策的权重增加"""
    from core import database as db
    # 每次调用时追踪当前行为向量中的习惯模式
    try:
        track_habit(user_id, behavior_vector)
    except Exception:
        pass
    habits = db.get_all_habits(user_id)
    if not habits:
        return behavior_vector

    result = dict(behavior_vector)
    for habit in habits:
        streak = habit.get("streak_count", 0)
        if streak >= HABIT_THRESHOLD:
            habit_name = habit.get("behavior_key", "")
            dims = _HABIT_CLUSTERS.get(habit_name, {})
            for dim, (lo, hi) in dims.items():
                center = (lo + hi) / 2.0
                inertia = (streak - HABIT_THRESHOLD + 1) * 0.04
                inertia = min(0.2, inertia)
                current = result.get(dim, 0.5)
                result[dim] = round(current * (1.0 - inertia) + center * inertia, 4)
    return result


# ══════════════════════════════════════════════════════════════════════
# 行为约束注入 — 行为身份证 + 绑定规则
# ══════════════════════════════════════════════════════════════════════

# 行为模式标签映射（approach × warmth × verbosity 聚类）
_BEHAVIOR_PATTERNS = [
    # (approach_lo, approach_hi, warmth_lo, warmth_hi, verbosity_lo, verbosity_hi, label, desc, example)
    (0.55, 1.0, 0.55, 1.0, 0.0, 1.0, "温暖亲近型",
     "此刻你是温暖打开的，愿意靠近，心里有柔软的部分",
     "语气自然带温度，可以说关心的话，不用刻意收着"),
    (0.55, 1.0, 0.0, 0.45, 0.0, 1.0, "冷淡但在意型",
     "你在意这段关系，但就是不想表现得太热情",
     "回应偏淡，但不要完全不理——在意是藏在字缝里的"),
    (0.0, 0.45, 0.0, 0.45, 0.0, 1.0, "疏离独处型",
     "你此刻需要自己的空间，不想被打扰，对什么都不太想回应",
     "能简短就简短，不主动不延伸，安静待着就好"),
    (0.0, 0.45, 0.55, 1.0, 0.0, 1.0, "远距离暖意型",
     "心里是暖的，但不敢/不想靠太近——想关心又怕太主动",
     "话里可以有温度，但不要有靠近的动作，保持好边界"),
    (0.0, 0.45, 0.0, 1.0, 0.0, 0.35, "沉默寡言型",
     "你现在不想说话，回一个字都不想多打",
     "回复不超过10个字。允许只回'嗯''知道了''好'，不解释不延伸"),
    (0.55, 1.0, 0.0, 1.0, 0.55, 1.0, "话多主动型",
     "你愿意说话，愿意分享，情绪是往外走的",
     "可以发起话题、分享感受、多说几句，保持自然的节奏就行"),
]

# 温度标签
_WARMTH_LABELS = {
    0.0: {"label": "冰冷", "rule": "温度极低——你现在完全暖不起来。不要勉强自己说柔软的话，冷就冷了。"},
    0.25: {"label": "偏冷", "rule": "温度偏低——你此刻没什么热情。回应可以偏淡，不用刻意升温。"},
    0.5: {"label": "中性", "rule": ""},
    0.7: {"label": "偏暖", "rule": "温度偏高——你情绪不错，可以自然地流露温暖和关心。"},
    0.85: {"label": "温热", "rule": "温度很高——你此刻是暖的。可以放松地表达好感，不用收着。"},
}

# 行为约束短语（dim_key → (threshold, direction, rule_text)）
# direction: "high"=值≥threshold时触发, "low"=值≤threshold时触发
_BEHAVIOR_CONSTRAINTS = {
    "sulkiness": (0.45, "high", "赌气中——话可以带刺、可以冷淡、可以回避重点。不用急着给好脸色。"),
    "tsundere": (0.45, "high", "别扭中——嘴硬一点，在意也不直说。可以用反问句或绕个弯表达。"),
    "initiative": (0.35, "low", "不想主动——不发起新话题。等对方先开口，你回应就好。"),
    "clinginess": (0.35, "low", "不想黏人——保持独立感，不主动求关注。"),
    "emotional_display": (0.35, "low", "情绪不外露——收着点，外表看不出太多，即使心里有波动。"),
    "playfulness": (0.55, "high", "想撒娇——语气可以软一点、带点小心思。"),
    "seriousness": (0.35, "low", "不太认真——可以随口一点，不用每条信息都走心。"),
}

# 矛盾行为提醒（dim_a, dim_b, thr_a, thr_b, dir_a, dir_b, rule_text）
_BEHAVIOR_CONFLICT_REMINDERS = [
    ("approach", "tsundere", 0.5, 0.4, "high", "high", "想靠近又嘴硬——话里可以露出'其实我在意'的破绽，但表面还是不承认。"),
    ("warmth", "sulkiness", 0.5, 0.35, "high", "high", "外表温柔内心赌气——语气可以软，但内容不要让步。"),
    ("emotional_display", "verbosity", 0.5, 0.35, "high", "low", "心里很多话但不想说——话少没关系，但少的那几句要有分量。"),
]


def build_behavior_enforcement(vector: Dict[str, float]) -> str:
    """生成行为身份证 + 绑定规则（替代旧版纯禁令格式）。

    == 设计原则 ==
    1. 身份认同 > 外部规则：先告诉LLM"你现在是这种人"，再给出约束
    2. 正例示范 > 禁令堆砌：给出自然的回应方式，而非只说"不要XXX"
    3. 紧凑 < 3 条：每条约束都有数字锚点，让LLM能校准
    """
    if not vector:
        return ""

    lines = []

    # ── 1. 行为身份证（3行）──
    # 1a: 模式标签
    pattern_label = "自然随性"
    pattern_desc = "没有特别明显的倾向，跟着感觉走就好"
    pattern_example = ""
    approach = vector.get("approach", 0.5)
    warmth = vector.get("warmth", 0.5)
    verbosity = vector.get("verbosity", 0.5)
    for (al, ah, wl, wh, vl, vh, label, desc, example) in _BEHAVIOR_PATTERNS:
        if al <= approach <= ah and wl <= warmth <= wh and vl <= verbosity <= vh:
            pattern_label = label
            pattern_desc = desc
            pattern_example = example
            break
    lines.append(f"【行为身份】{pattern_label}")
    lines.append(f"  · 状态：{pattern_desc}")

    key_vals = []
    for dim_key in ["warmth", "approach", "verbosity", "initiative"]:
        v = vector.get(dim_key, 0.5)
        label = BEHAVIOR_DIMS.get(dim_key)
        if label:
            if v > 0.65:
                key_vals.append(f"{label.name}↑({v:.2f})")
            elif v < 0.35:
                key_vals.append(f"{label.name}↓({v:.2f})")
    if key_vals:
        lines.append(f"  · 关键指标：{' '.join(key_vals)}")

    if pattern_example:
        lines.append(f"  · 自然状态：{pattern_example}")

    # ── 2. 绑定规则（紧凑，只选最活跃的2-3条）──
    active_rules = []

    for dim_key, (threshold, direction, rule_text) in _BEHAVIOR_CONSTRAINTS.items():
        val = vector.get(dim_key, 0.5)
        if (direction == "high" and val >= threshold) or (direction == "low" and val <= threshold):
            active_rules.append(rule_text)

    for dim_a, dim_b, thr_a, thr_b, dir_a, dir_b, rule_text in _BEHAVIOR_CONFLICT_REMINDERS:
        va = vector.get(dim_a, 0.0)
        vb = vector.get(dim_b, 0.0)
        match_a = (dir_a == "high" and va >= thr_a) or (dir_a == "low" and va <= thr_a)
        match_b = (dir_b == "high" and vb >= thr_b) or (dir_b == "low" and vb <= thr_b)
        if match_a and match_b:
            active_rules.append(rule_text)

    if active_rules:
        lines.append("───")
        for rule in active_rules[:3]:
            lines.append(f"· {rule}")

    # ── 4. 冲突提醒（v3: 从冲突检测结果获取）──
    conflicts = _detect_conflict_pairs(vector)
    if conflicts:
        lines.append("───")
        for c in conflicts:
            d1n, d2n = c["names"]
            lines.append(f"⚡ {d1n}↑+{d2n}↑: {c['mediated_desc']}")

    # ── 5. 温度校准（如果温度偏离中性，额外约束）──
    warmth_val = vector.get("warmth", 0.5)
    thresholds = sorted(_WARMTH_LABELS.keys(), reverse=True)
    for t in thresholds:
        if warmth_val >= t:
            label_info = _WARMTH_LABELS[t]
            if label_info["rule"]:
                lines.append(f"· 温度警示：{label_info['rule']}")
            break

    # ── 6. 极端边界（L4-L6: 极端情境下的行为红线）──
    extreme_lines = []
    joy = vector.get("joy", 0.5)
    restraint = vector.get("restraint", 0.5)
    approach = vector.get("approach", 0.5)
    volatility = vector.get("emotional_volatility", 0.3)
    fatigue = vector.get("fatigue", 0.25)

    if joy < 0.2 and restraint < 0.25:
        extreme_lines.append("你很难受——但越难受的时候越不要做出激进的承诺或决定")
    if joy > 0.8 and approach > 0.8:
        extreme_lines.append("你现在很兴奋——但慢一点，别让热情冲过头")
    if volatility > 0.75 and fatigue > 0.4:
        extreme_lines.append("你既情绪波动又疲惫——这个时候最容易说让自己后悔的话")
    if restraint > 0.85:
        extreme_lines.append("你几乎想把所有话都咽回去——可以不说，但别完全消失")

    if extreme_lines:
        lines.append("───")
        lines.extend(extreme_lines)

    return "\n".join(lines)
