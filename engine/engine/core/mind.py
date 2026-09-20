# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""24维全真流动心智内核层（非线性升级 + 耦合矩阵 + 免疫回归）
新增：延迟发酵队列、叠加爆发、sigmoid非线性、个性化敏感度画像、
      混沌维度联动、概率人格阶段
升级 v3:
  1. 补齐 body_perception/life_vitality/chaotic_mood 的完整因果链路
  2. 非线性耦合矩阵（权重边 + sigmoid 归一化传播）
  3. 心智免疫稳态回归机制
  4. 发酵计数器 DB 持久化
原则1: 情绪永不机械秒切，拥有残留、递延、发酵、叠加、延迟爆发特性
原则3: 所有阈值、波动、概率、权重全部混沌动态，无固定参数、无机械周期
"""
import random
import math
import json
import threading
from typing import Dict
from core import database as db
from core import config as cfg

# ── 配置参数（由 load_engine_config 填充）──
_fluctuation_drift_factor = 0.001
_fluctuation_sigma = 0.015

# 发酵/爆发参数
_ferment_release_rate = 0.15
_ferment_release_interval = 5
_burst_threshold_ratio = 0.55
_burst_jump_min = 0.08
_burst_jump_max = 0.20
_burst_linked_min = 0.02
_burst_linked_max = 0.08

# sigmoid 非线性参数
_sigmoid_steepness = 8.0
_sigmoid_edge_zone = 0.15

# 混沌参数
_chaotic_injection_prob = 0.35
_chaotic_injection_count = 2

# 因果溯源参数
_causal_stack_bonus = 1.3
_causal_recent_bonus = 1.5
_causal_recent_minutes = 30
_causal_recent_count = 3

# 中文维度名映射（供 GoBridge 爆发记录）
_DIM_CN_MAP = {
    "joy": "愉悦", "misery": "委屈", "loneliness": "孤单",
    "obsession": "执念", "dependence": "依赖", "jealousy": "吃醋",
    "fatigue": "疲惫", "emptiness": "空落", "chaotic_mood": "混沌",
    "emotional_volatility": "情绪波动", "sensitivity_paranoia": "敏感",
    "favoritism": "偏爱", "emotional_healing": "自愈",
    "life_sense": "生活感", "restraint": "克制",
    "years_precipitation": "岁月沉淀", "relationship_fatigue": "关系疲惫",
    "healing_reflection": "治愈反思", "body_perception": "身体感知",
    "autonomous_values": "自主价值观", "life_vitality": "生命活力",
    "bidirectional_shaping": "双向塑造", "causal_fate": "因果宿命",
    "soul_resonance": "灵魂共鸣",
}

# ── 内存发酵累积计数器（减少 DB I/O）──
_ferment_counters = {}  # user_id → {dim: accumulated_amount}
_counters_lock = threading.Lock()

# ══════════════════════════════════════════════════════════════════════
# 心境随机游走 — 让心智在基线附近自然漂移
# ══════════════════════════════════════════════════════════════════════

_mood_drift: Dict[str, Dict[str, float]] = {}
_mood_base: Dict[str, Dict[str, float]] = {}
_mood_drift_lock = threading.Lock()

# Ornstein-Uhlenbeck 参数
_OU_THETA = 0.08        # 均值回归强度（越小漂移越持久）
_OU_SIGMA = 0.004       # 噪声强度
_OU_MAX_DRIFT = 0.12    # 最大漂移幅度


def _init_mood_drift(user_id: str, mind: dict):
    """初始化心境基线"""
    with _mood_drift_lock:
        if user_id not in _mood_base:
            _mood_base[user_id] = {k: v for k, v in mind.items() if isinstance(v, (int, float))}
        if user_id not in _mood_drift:
            _mood_drift[user_id] = {k: 0.0 for k in _mood_base[user_id]}


def _tick_mood_drift(user_id: str):
    """更新心境漂移 (Ornstein-Uhlenbeck 过程)"""
    with _mood_drift_lock:
        if user_id not in _mood_drift:
            return
        drift = _mood_drift[user_id]
        for dim in drift:
            current = drift[dim]
            drift[dim] = current + _OU_THETA * (0 - current) + random.gauss(0, _OU_SIGMA)
            drift[dim] = max(-_OU_MAX_DRIFT, min(_OU_MAX_DRIFT, drift[dim]))


def _apply_mood_drift(user_id: str, mind: dict) -> dict:
    """将心境漂移叠加到心智数值上"""
    _tick_mood_drift(user_id)
    with _mood_drift_lock:
        drift = _mood_drift.get(user_id, {})
    result = dict(mind)
    for dim, d in drift.items():
        if dim in result:
            result[dim] = max(0.0, min(1.0, result[dim] + d))
    return result

# ══════════════════════════════════════════════════════════════════════
# v3: 非线性耦合矩阵
# ══════════════════════════════════════════════════════════════════════

# 耦合强度矩阵 — weight[i][j] = dim_i 变化对 dim_j 的影响强度 [0, 1]
# 对称非必然：A→B 和 B→A 强度可以不同
_COUPLING_MATRIX: dict = {}
_COUPLING_MATRIX_LOADED = False

_COUPLING_FILE = "data/json/coupling_matrix.json"

# 默认耦合边（核心骨架，矩阵会自动补齐缺失边为 0）
_DEFAULT_COUPLING_EDGES = {
    # body_perception 完整因果链路（Gap1）
    ("body_perception", "life_vitality"): 0.45,
    ("body_perception", "life_sense"): 0.40,
    ("body_perception", "fatigue"): 0.35,
    ("body_perception", "emotional_volatility"): -0.20,
    ("body_perception", "joy"): 0.25,
    ("body_perception", "misery"): -0.20,
    # life_vitality 完整因果链路（Gap1）
    ("life_vitality", "body_perception"): 0.35,
    ("life_vitality", "joy"): 0.40,
    ("life_vitality", "fatigue"): -0.30,
    ("life_vitality", "emotional_volatility"): 0.15,
    ("life_vitality", "life_sense"): 0.30,
    ("life_vitality", "loneliness"): -0.15,
    ("life_vitality", "restraint"): -0.10,
    # chaotic_mood 完整因果链路（Gap1）
    ("chaotic_mood", "emotional_volatility"): 0.50,
    ("chaotic_mood", "sensitivity_paranoia"): 0.35,
    ("chaotic_mood", "emptiness"): 0.25,
    ("chaotic_mood", "joy"): -0.20,
    ("chaotic_mood", "fatigue"): 0.15,
    ("chaotic_mood", "misery"): 0.15,
    ("chaotic_mood", "restraint"): 0.15,
    # 原有核心边保留并增强
    ("joy", "life_vitality"): 0.35,
    ("joy", "emotional_volatility"): 0.20,
    ("joy", "body_perception"): 0.25,
    ("misery", "loneliness"): 0.40,
    ("misery", "emptiness"): 0.30,
    ("misery", "body_perception"): -0.15,
    ("dependence", "favoritism"): 0.35,
    ("dependence", "obsession"): 0.30,
    ("jealousy", "sensitivity_paranoia"): 0.35,
    ("jealousy", "chaotic_mood"): 0.25,
    ("fatigue", "life_vitality"): -0.40,
    ("fatigue", "body_perception"): -0.25,
    ("loneliness", "emptiness"): 0.35,
    ("loneliness", "dependence"): 0.20,
    ("favoritism", "bidirectional_shaping"): 0.30,
    ("favoritism", "soul_resonance"): 0.25,
    ("sensitivity_paranoia", "chaotic_mood"): 0.30,
    ("sensitivity_paranoia", "emotional_volatility"): 0.25,
    ("emotional_healing", "healing_reflection"): 0.35,
    ("emotional_healing", "joy"): 0.25,
    ("obsession", "bidirectional_shaping"): 0.30,
    ("obsession", "causal_fate"): 0.20,
    ("emptiness", "loneliness"): 0.30,
    ("emptiness", "life_sense"): -0.15,
    ("life_sense", "body_perception"): 0.25,
    ("life_sense", "life_vitality"): 0.20,
    ("restraint", "autonomous_values"): 0.35,
    ("restraint", "emotional_volatility"): -0.20,
    ("emotional_volatility", "chaotic_mood"): 0.35,
    ("emotional_volatility", "sensitivity_paranoia"): 0.20,
    ("years_precipitation", "healing_reflection"): 0.25,
    ("years_precipitation", "bidirectional_shaping"): 0.15,
    ("relationship_fatigue", "life_vitality"): -0.20,
    ("relationship_fatigue", "emotional_healing"): -0.15,
    ("healing_reflection", "emotional_healing"): 0.30,
    ("healing_reflection", "joy"): 0.15,
    ("autonomous_values", "restraint"): 0.30,
    ("bidirectional_shaping", "causal_fate"): 0.35,
    ("bidirectional_shaping", "soul_resonance"): 0.30,
    ("causal_fate", "bidirectional_shaping"): 0.30,
    ("causal_fate", "soul_resonance"): 0.20,
    ("soul_resonance", "bidirectional_shaping"): 0.25,
    ("soul_resonance", "favoritism"): 0.20,
}


def _build_coupling_matrix():
    """构建完整的 24x24 耦合矩阵（稀疏存储），含动态维度注册表中的权重"""
    global _COUPLING_MATRIX, _COUPLING_MATRIX_LOADED
    _COUPLING_MATRIX = {}
    for (src, tgt), weight in _DEFAULT_COUPLING_EDGES.items():
        if src not in _COUPLING_MATRIX:
            _COUPLING_MATRIX[src] = {}
        _COUPLING_MATRIX[src][tgt] = round(weight, 4)

    # 从维度注册表加载动态维度的耦合权重
    try:
        from engine.life import meta_dimension as md_module
        registry = md_module._DIMENSION_REGISTRY
        for dim_name, entry in registry.items():
            if not entry.get("is_dynamic") or entry.get("is_dormant"):
                continue
            weights = entry.get("coupling_weights", {})
            if weights:
                if dim_name not in _COUPLING_MATRIX:
                    _COUPLING_MATRIX[dim_name] = {}
                for tgt, w in weights.items():
                    _COUPLING_MATRIX[dim_name][tgt] = round(w, 4)
    except Exception:
        pass

    _COUPLING_MATRIX_LOADED = True


def _propagate_through_matrix(source_dim: str, source_delta: float,
                               mind: dict, profile: dict = None) -> dict:
    """通过耦合矩阵传播一个维度的变化到所有关联维度。

    使用 sigmoid 归一化控制传播强度：
      - 源变化微弱 (<0.001) → 不传播
      - 目标维度已近边缘 → 传播衰减
      - 负权重边 → 反相影响
    """
    if not _COUPLING_MATRIX_LOADED:
        _build_coupling_matrix()

    if abs(source_delta) < 0.001:
        return {}

    result = {}
    targets = _COUPLING_MATRIX.get(source_dim, {})
    if not targets:
        return result

    for target_dim, weight in targets.items():
        if target_dim not in mind:
            continue

        old = mind.get(target_dim, 0.5)
        raw_influence = source_delta * weight

        # sigmoid 边缘阻尼：目标接近边界时传播衰减
        if raw_influence > 0:
            edge_dist = 1.0 - old
        else:
            edge_dist = old

        if edge_dist < _sigmoid_edge_zone:
            damping = 1.0 / (1.0 + math.exp(-_sigmoid_steepness * (edge_dist / _sigmoid_edge_zone - 0.5)))
            raw_influence *= damping

        # 敏感度增益
        if profile:
            amp = profile.get("fluctuation_amplitude", 0.7)
            raw_influence *= (0.3 + amp * 0.7)

        new_val = clamp(old + raw_influence)
        if abs(new_val - old) > 0.001:
            result[target_dim] = round(new_val, 6)

    return result


def _get_matrix_linked_dims(dim: str) -> list:
    """从耦合矩阵获取关联维度列表（用于兼容 _get_static_links 接口）"""
    if not _COUPLING_MATRIX_LOADED:
        _build_coupling_matrix()
    targets = _COUPLING_MATRIX.get(dim, {})
    return list(targets.keys())


# ══════════════════════════════════════════════════════════════════════
# v3: 心智免疫稳态回归
# ══════════════════════════════════════════════════════════════════════

# 各维度的基线值（自然趋向值）
_HOMEOSTATIC_BASELINES = {
    "joy": 0.50,
    "misery": 0.15,
    "dependence": 0.25,
    "jealousy": 0.12,
    "fatigue": 0.20,
    "loneliness": 0.35,
    "favoritism": 0.15,
    "sensitivity_paranoia": 0.30,
    "emotional_healing": 0.50,
    "obsession": 0.20,
    "emptiness": 0.25,
    "chaotic_mood": 0.20,
    "life_sense": 0.50,
    "restraint": 0.55,
    "emotional_volatility": 0.30,
    "body_perception": 0.50,
    "autonomous_values": 0.45,
    "life_vitality": 0.55,
}

# 各维度的回归速率（每 tick 回归比例）
# 越高 → 恢复越快（免疫越强），越低 → 越"记仇"（免疫弱）
_HOMEOSTATIC_RATES = {
    "joy": 0.0035,
    "misery": 0.0040,
    "dependence": 0.0020,
    "jealousy": 0.0030,
    "fatigue": 0.0050,
    "loneliness": 0.0035,
    "favoritism": 0.0015,
    "sensitivity_paranoia": 0.0020,
    "emotional_healing": 0.0010,
    "obsession": 0.0005,
    "emptiness": 0.0030,
    "chaotic_mood": 0.0040,
    "life_sense": 0.0020,
    "restraint": 0.0015,
    "emotional_volatility": 0.0045,
    "body_perception": 0.0030,
    "autonomous_values": 0.0015,
    "life_vitality": 0.0040,
}

# 不可回归的维度（纯累积型，永不回弹）
_NO_REGRESSION_DIMS = {
    "years_precipitation",
    "healing_reflection",
    "bidirectional_shaping",
    "causal_fate",
    "soul_resonance",
    "relationship_fatigue",
}


def _apply_homeostatic_regression(mind: dict, profile: dict = None,
                                    dt: float = 1.0) -> dict:
    """心智免疫稳态回归 — 维度自然趋向基线。

    对于每个可回归的维度：
      deviation = current - baseline
      regression = -deviation × rate × dt
      如果 |regression| < 0.001 → 跳过

    个性化修正：
      - 自我修复能力高 → 回归加速
      - 执念倾向高 → 回归减速（放不下）
      - 敏感度越高 → 波动维度回归略慢
    """
    updates = {}
    healing_rate = profile.get("self_healing_rate", 0.55) if profile else 0.55
    obsession_tend = profile.get("obsession_tendency", 0.40) if profile else 0.40

    for dim, baseline in _HOMEOSTATIC_BASELINES.items():
        if dim in _NO_REGRESSION_DIMS:
            continue

        current = mind.get(dim, baseline)
        deviation = current - baseline

        if abs(deviation) < 0.01:
            continue

        rate = _HOMEOSTATIC_RATES.get(dim, 0.002)

        # 个性化修正
        rate *= (0.5 + healing_rate * 0.8)

        # 执念高 → 情感类维度回归慢
        if dim in ("obsession", "favoritism", "dependence", "misery", "jealousy"):
            rate *= (1.0 - obsession_tend * 0.4)

        # 封顶弹性衰减：接近上限时自动下探（防止长期锁死在1.0）
        if current >= 0.95:
            rate += 0.05 * (current - 0.95) * 10  # 越接近1.0，衰减越强
        elif current <= 0.05:
            rate += 0.05 * (0.05 - current) * 10  # 越接近0.0，回弹越强

        regression = -deviation * rate * dt

        if abs(regression) < 0.0005:
            continue

        new_val = clamp(current + regression)
        if abs(new_val - current) > 0.0005:
            updates[dim] = round(new_val, 6)

    return updates


# ══════════════════════════════════════════════════════════════════════
# v3: 发酵计数器持久化
# ══════════════════════════════════════════════════════════════════════

_FERMENT_COUNTER_FILE = "data/json/ferment_counters.json"


def _save_ferment_counters():
    """持久化发酵计数器到 JSON 文件"""
    try:
        with _counters_lock:
            data = {uid: dict(counters) for uid, counters in _ferment_counters.items()}
        if not data:
            return
        import os
        os.makedirs(os.path.dirname(_FERMENT_COUNTER_FILE), exist_ok=True)
        with open(_FERMENT_COUNTER_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Mind] 保存发酵计数器失败: {e}")


def _load_ferment_counters():
    """从 JSON 文件恢复发酵计数器"""
    global _ferment_counters
    try:
        import os
        if not os.path.exists(_FERMENT_COUNTER_FILE):
            return
        with open(_FERMENT_COUNTER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        with _counters_lock:
            _ferment_counters = {}
            for uid, counters in data.items():
                _ferment_counters[uid] = {dim: float(v) for dim, v in counters.items()}
    except Exception as e:
        print(f"[Mind] 恢复发酵计数器失败: {e}")


def _get_ferment_counter(user_id: str, dim: str) -> float:
    """安全获取发酵计数器值"""
    with _counters_lock:
        if user_id not in _ferment_counters:
            return 0.0
        return _ferment_counters[user_id].get(dim, 0.0)


def _set_ferment_counter(user_id: str, dim: str, value: float):
    """安全设置发酵计数器值"""
    with _counters_lock:
        if user_id not in _ferment_counters:
            _ferment_counters[user_id] = {}
        _ferment_counters[user_id][dim] = value


def load_engine_config():
    """从 config.json 加载心智引擎参数"""
    global _fluctuation_drift_factor, _fluctuation_sigma
    global _ferment_release_rate, _ferment_release_interval
    global _burst_threshold_ratio, _burst_jump_min, _burst_jump_max
    global _burst_linked_min, _burst_linked_max
    global _sigmoid_steepness, _sigmoid_edge_zone
    global _chaotic_injection_prob, _chaotic_injection_count
    global _causal_stack_bonus, _causal_recent_bonus
    global _causal_recent_minutes, _causal_recent_count

    mind_cfg = cfg.get_section("mind")
    fr = mind_cfg.get("spontaneous_fluctuation_range", 0.03)
    _fluctuation_drift_factor = fr * 0.03
    _fluctuation_sigma = fr * 0.5

    _ferment_release_rate = mind_cfg.get("ferment_release_rate", 0.15)
    _ferment_release_interval = mind_cfg.get("ferment_release_interval_seconds", 5)
    _burst_threshold_ratio = mind_cfg.get("burst_threshold_ratio", 0.55)
    _burst_jump_min = mind_cfg.get("burst_jump_min", 0.08)
    _burst_jump_max = mind_cfg.get("burst_jump_max", 0.20)
    _burst_linked_min = mind_cfg.get("burst_linked_wave_min", 0.02)
    _burst_linked_max = mind_cfg.get("burst_linked_wave_max", 0.08)
    _sigmoid_steepness = mind_cfg.get("sigmoid_steepness", 8.0)
    _sigmoid_edge_zone = mind_cfg.get("sigmoid_edge_zone", 0.15)
    _chaotic_injection_prob = mind_cfg.get("chaotic_injection_probability", 0.35)
    _chaotic_injection_count = mind_cfg.get("chaotic_injection_count", 2)
    _causal_stack_bonus = mind_cfg.get("causal_stack_bonus", 1.3)
    _causal_recent_bonus = mind_cfg.get("causal_recent_bonus", 1.5)
    _causal_recent_minutes = mind_cfg.get("causal_recent_minutes", 30)
    _causal_recent_count = mind_cfg.get("causal_recent_count", 3)

    # v3: 加载发酵计数器 + 构建耦合矩阵
    _load_ferment_counters()
    _build_coupling_matrix()


# ── 24维定义 ──
# DIMENSIONS 分为静态核心 + 动态扩展两部分
_BASE_DIMENSIONS = [
    "joy", "misery", "dependence", "jealousy", "fatigue", "loneliness",
    "favoritism", "sensitivity_paranoia", "emotional_healing",
    "obsession", "emptiness", "chaotic_mood",
    "life_sense", "restraint", "emotional_volatility",
    "years_precipitation", "relationship_fatigue", "healing_reflection",
    "body_perception", "autonomous_values", "life_vitality",
    "bidirectional_shaping", "causal_fate", "soul_resonance",
]

# 动态维度列表（从数据库加载）
DIMENSIONS = list(_BASE_DIMENSIONS)
_dynamic_loaded: bool = False

DIMENSION_GROUPS = {
    "基础人性": ["joy", "misery", "dependence", "jealousy", "fatigue", "loneliness"],
    "人际细腻": ["favoritism", "sensitivity_paranoia", "emotional_healing"],
    "深层潜意识": ["obsession", "emptiness", "chaotic_mood"],
    "真人生活化": ["life_sense", "restraint", "emotional_volatility"],
    "岁月成长": ["years_precipitation", "relationship_fatigue", "healing_reflection"],
    "生命体征": ["body_perception", "autonomous_values", "life_vitality"],
    "灵魂宿命": ["bidirectional_shaping", "causal_fate", "soul_resonance"],
}

# 不可自发波动的维度（纯累积/沉淀型，永不参与随机漂移）
_NO_FLUCTUATION_DIMS = {
    "years_precipitation",      # 岁月沉淀：只增不减
    "healing_reflection",        # 自愈复盘：累积型
    "bidirectional_shaping",     # 双向塑造：因果驱动
    "causal_fate",               # 因果宿命：只增不减
    "soul_resonance",            # 灵魂共鸣 — 不影响波动
}

# ── 内存缓存 ──
_cache: dict = {}
_cache_lock = threading.Lock()
_fluctuation_seed: dict = {}
_seed_lock = threading.Lock()


def clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


# ═══════════════════════════════════════════════════════
# 动态维度管理
# ═══════════════════════════════════════════════════════

def load_dynamic_dimensions():
    """从数据库 personality 表中加载所有列（含动态新增的维度）。
    首次调用时自动刷新 DIMENSIONS 列表。
    """
    global DIMENSIONS, _dynamic_loaded
    try:
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.execute("PRAGMA table_info(personality)")
        all_cols = {row[1] for row in cursor.fetchall()}
        conn.close()

        dynamic = [c for c in all_cols
                   if c.startswith("dynamic_") and c not in DIMENSIONS]
        DIMENSIONS = list(_BASE_DIMENSIONS) + sorted(dynamic)
        _dynamic_loaded = True

        # 同步到维度注册表
        try:
            from engine.life import meta_dimension as md_module
            md_module.register_dynamic_dimensions_from_db()
        except Exception:
            pass
    except Exception as _e:
        print(f"[Mind] 加载动态维度失败: {_e}")


def refresh_dynamic_dimensions():
    """强制刷新 DIMENSIONS 列表（外部调用用，如维度注册后）"""
    global _dynamic_loaded
    _dynamic_loaded = False
    load_dynamic_dimensions()


def add_personality_dimension(user_id: str, dim_name: str,
                              default_value: float = 0.4, group: str = "新生特质"):
    """动态新增心智维度（对外接口，委托给 evolution 模块）。
    同时更新 DIMENSION_GROUPS、DIMENSIONS、数据库 schema。
    """# 委托给 evolution 模块做实际的 ALTER TABLE
    try:
        from engine import evolution as evo_module
        evo_module.add_personality_dimension(user_id, dim_name, default_value)
    except Exception as _e:
        print(f"[Mind] evolution 不可用，直接 ALTER TABLE: {_e}")
        try:
            import sqlite3
            conn = sqlite3.connect(db.DB_PATH)
            try:
                conn.execute(
                    f"ALTER TABLE personality ADD COLUMN {dim_name} REAL DEFAULT {default_value}"
                )
                conn.commit()
            except sqlite3.OperationalError:
                print(f"[Mind] 维度 {dim_name} 已存在，跳过")
            conn.close()
            db.update_personality(user_id, {dim_name: round(default_value, 6)})
        except Exception as _e2:
            print(f"[Mind] 新增维度 {dim_name} 失败: {_e2}")

    # 更新本地维度列表
    global DIMENSIONS
    if dim_name not in DIMENSIONS:
        DIMENSIONS.append(dim_name)
    if group not in DIMENSION_GROUPS:
        DIMENSION_GROUPS[group] = []
    if dim_name not in DIMENSION_GROUPS[group]:
        DIMENSION_GROUPS[group].append(dim_name)

    # 注册到维度注册表 + 自动接入耦合矩阵
    try:
        from engine.life import meta_dimension as md_module
        display_name = dim_name.replace("dynamic_", "")
        md_module.register_new_dimension(dim_name, display_name, group, default_value)
    except Exception as _e3:
        print(f"[Mind] 维度注册表注册失败: {_e3}")

    # 刷新缓存
    refresh_cache(user_id)


# ═══════════════════════════════════════════════════════
#  核心：非线性变化函数
# ═══════════════════════════════════════════════════════

def apply_nonlinear_delta(old: float, raw_delta: float, profile: dict = None) -> float:
    """非线性增量：接近0或1时 sigmoid 阻尼，中段线性微加速。
    原则3: 所有阈值、波动、概率、权重全部混沌动态。
    """# 计算到边界的距离
    if raw_delta > 0:
        distance_to_edge = 1.0 - old
    else:
        distance_to_edge = old

    if distance_to_edge < _sigmoid_edge_zone:
        # 边缘区：sigmoid 阻尼
        # 越靠近边界阻力越大
        normalized = distance_to_edge / _sigmoid_edge_zone
        damping = 1.0 / (1.0 + math.exp(-_sigmoid_steepness * (normalized - 0.5)))
        effective = raw_delta * damping
    else:
        # 中段：线性微加速（模拟真人情绪在中间区域的易变性）
        effective = raw_delta * 1.05

    # 个性化波动幅度修正
    if profile:
        amp = profile.get("fluctuation_amplitude", 0.7)
        effective *= amp

    return effective


# ═══════════════════════════════════════════════════════
#  个性化敏感度画像
# ═══════════════════════════════════════════════════════

def get_sensitivity_profile(user_id: str) -> dict:
    """获取用户个性化敏感度画像（首次自动生成唯一参数）"""
    profile = db.get_sensitivity_profile(user_id)
    return profile


def generate_sensitivity_profile(user_id: str) -> dict:
    """为用户生成独一无二的敏感度组合，存入 DB"""
    profile = db._default_sensitivity_profile()
    db.update_sensitivity_profile(user_id, profile)
    return profile


def tune_sensitivity_profile(user_id: str, reason: str, direction: str = None):
    """命运事件缓慢调整个性化参数。
    - 被温柔对待 → 自愈加速、敏感度略降
    - 被反复敷衍 → 敏感度升高、波动幅度增大
    """
    profile = get_sensitivity_profile(user_id)

    if direction == "gentle":
        profile["self_healing_rate"] = round(min(0.95, profile["self_healing_rate"] + 0.003), 3)
        profile["emotional_sensitivity"] = round(max(0.30, profile["emotional_sensitivity"] - 0.002), 3)
    elif direction == "cold":
        profile["emotional_sensitivity"] = round(min(0.95, profile["emotional_sensitivity"] + 0.004), 3)
        profile["fluctuation_amplitude"] = round(min(1.0, profile["fluctuation_amplitude"] + 0.003), 3)
    elif direction == "patient":
        profile["ferment_speed"] = round(min(0.95, profile["ferment_speed"] + 0.002), 3)
        profile["burst_threshold"] = round(min(0.85, profile["burst_threshold"] + 0.002), 3)
    elif direction == "perfunctory":
        profile["obsession_tendency"] = round(min(0.80, profile["obsession_tendency"] + 0.004), 3)
        profile["ferment_speed"] = round(max(0.20, profile["ferment_speed"] - 0.003), 3)

    profile["tuned_count"] = profile.get("tuned_count", 0) + 1
    profile["last_tuned_reason"] = reason
    db.update_sensitivity_profile(user_id, profile)


# ═══════════════════════════════════════════════════════
#  混沌维度联动
# ═══════════════════════════════════════════════════════

def _get_chaotic_linked_dimensions(dim: str, impact: float) -> dict:
    """耦合矩阵主干联动 + 混沌注入（v3: 矩阵替代固定映射表）。
    原则3: 每次调用可能注入1-2个非预期维度，模拟"说不清为什么就被影响了"。
    """
    # v3: 耦合矩阵作为主干
    if not _COUPLING_MATRIX_LOADED:
        _build_coupling_matrix()

    matrix_links = _COUPLING_MATRIX.get(dim, {})
    result = {}
    for target_dim, weight in matrix_links.items():
        linked_impact = impact * abs(weight) * random.uniform(0.05, 0.20)
        if weight < 0:
            linked_impact = -linked_impact
        result[target_dim] = linked_impact

    # 混沌注入：随机加入非预期维度（在矩阵之外补充）
    if random.random() < _chaotic_injection_prob:
        all_dims = set(DIMENSIONS) - {dim} - set(matrix_links.keys())
        all_other = list(all_dims)
        injected = random.sample(all_other, min(_chaotic_injection_count, len(all_other)))
        for d in injected:
            result[d] = impact * random.uniform(0.02, 0.08)

    return result


def _get_static_links(dim: str) -> list:
    """原有固定维度联动映射（v3: 作为耦合矩阵的兼容层 / 回退）
    body_perception/life_vitality/chaotic_mood 已补全完整双向链路。
    """
    links = {
        "joy": ["life_vitality", "emotional_volatility", "body_perception"],
        "misery": ["loneliness", "emptiness", "body_perception"],
        "dependence": ["favoritism", "obsession", "bidirectional_shaping"],
        "jealousy": ["sensitivity_paranoia", "chaotic_mood", "emotional_volatility"],
        "fatigue": ["life_vitality", "body_perception", "life_sense"],
        "loneliness": ["emptiness", "dependence", "chaotic_mood"],
        "favoritism": ["bidirectional_shaping", "soul_resonance", "dependence"],
        "sensitivity_paranoia": ["jealousy", "chaotic_mood", "emotional_volatility"],
        "emotional_healing": ["healing_reflection", "life_vitality", "joy"],
        "obsession": ["bidirectional_shaping", "causal_fate", "dependence"],
        "emptiness": ["loneliness", "life_sense", "chaotic_mood"],
        # chaotic_mood 完整双向链路（v3）
        "chaotic_mood": [
            "emotional_volatility", "sensitivity_paranoia", "emptiness",
            "joy", "fatigue", "misery", "restraint",
        ],
        "life_sense": ["body_perception", "life_vitality", "healing_reflection"],
        "restraint": ["autonomous_values", "favoritism", "emotional_volatility"],
        "emotional_volatility": ["chaotic_mood", "sensitivity_paranoia", "joy"],
        "years_precipitation": ["healing_reflection", "bidirectional_shaping", "causal_fate"],
        "relationship_fatigue": ["life_vitality", "emotional_healing", "dependence"],
        "healing_reflection": ["emotional_healing", "years_precipitation", "joy"],
        # body_perception 完整双向链路（v3）
        "body_perception": [
            "life_vitality", "life_sense", "fatigue",
            "joy", "misery", "emotional_volatility",
        ],
        "autonomous_values": ["restraint", "life_sense", "bidirectional_shaping"],
        # life_vitality 完整双向链路（v3）
        "life_vitality": [
            "body_perception", "joy", "fatigue",
            "emotional_volatility", "life_sense", "loneliness", "restraint",
        ],
        "bidirectional_shaping": ["causal_fate", "soul_resonance", "obsession"],
        "causal_fate": ["bidirectional_shaping", "soul_resonance", "years_precipitation"],
        "soul_resonance": ["bidirectional_shaping", "causal_fate", "favoritism"],
    }
    return links.get(dim, [])


# ═══════════════════════════════════════════════════════
#  基础 CRUD
# ═══════════════════════════════════════════════════════

def get_mind(user_id: str) -> dict:
    """获取最新心智数值（内存缓存优先）"""
    with _cache_lock:
        if user_id in _cache:
            return _cache[user_id].copy()

    # 确保动态维度已加载
    if not _dynamic_loaded:
        load_dynamic_dimensions()

    p = db.get_personality(user_id)
    if not p:
        db.init_personality(user_id)
        # 为新用户生成唯一敏感度画像
        generate_sensitivity_profile(user_id)
        p = db.get_personality(user_id)

    mind = {dim: p.get(dim, 0.5) for dim in DIMENSIONS}
    mind["personality_stage"] = p.get("personality_stage", "青涩试探")

    # 初始化心境漂移
    _init_mood_drift(user_id, mind)

    # 应用心境漂移 — 让心智自然漂移 ±12%
    mind = _apply_mood_drift(user_id, mind)

    # 亚稳态噪声注入 — 在情绪边界上抖动更大
    chaotic = mind.get("chaotic_mood", 0.25)
    jitter_scale = 0.005 + chaotic * 0.025  # 0.5%~3%
    for dim, val in mind.items():
        if not isinstance(val, (int, float)):
            continue
        if dim == "personality_stage":
            continue
        # 边缘状态抖动更大：靠近 0 或 1 时更容易不稳定
        edge_factor = 1.0 + 2.0 * min(val, 1.0 - val)
        noise = random.gauss(0, jitter_scale * edge_factor)
        mind[dim] = max(0.0, min(1.0, val + noise))

    with _cache_lock:
        _cache[user_id] = mind.copy()
    return mind


def refresh_cache(user_id: str):
    """从数据库刷新缓存 —  支持动态维度"""
    if not _dynamic_loaded:
        load_dynamic_dimensions()
    p = db.get_personality(user_id)
    if p:
        mind = {dim: p.get(dim, 0.5) for dim in DIMENSIONS}
        mind["personality_stage"] = p.get("personality_stage", "青涩试探")
        with _cache_lock:
            _cache[user_id] = mind


# ═══════════════════════════════════════════════════════
#  自发波动（接入非线性+个性化）
# ═══════════════════════════════════════════════════════

def spontaneous_fluctuation(user_id: str):
    """自发性心智波动（后台定时调用，已接入非线性+个性化）"""
    mind = get_mind(user_id)
    profile = get_sensitivity_profile(user_id)

    with _seed_lock:
        if user_id not in _fluctuation_seed:
            _fluctuation_seed[user_id] = random.random() * 100

    updates = {}
    for dim in DIMENSIONS:
        # 跳过不可自发波动的沉淀维度
        if dim in _NO_FLUCTUATION_DIMS:
            continue
        old = mind.get(dim, 0.5)
        drift = 0.5 - old
        noise = random.gauss(0, _fluctuation_sigma)
        raw_delta = drift * _fluctuation_drift_factor + noise

        # 非线性转换
        effective_delta = apply_nonlinear_delta(old, raw_delta, profile)

        new_val = clamp(old + effective_delta)
        if abs(new_val - old) > 0.001:
            updates[dim] = round(new_val, 6)

    # v3: 心智免疫稳态回归
    regression = _apply_homeostatic_regression(mind, profile, dt=1.0)
    for dim, val in regression.items():
        if dim not in updates:
            updates[dim] = val

    if updates:
        db.update_personality(user_id, updates)
        mind.update(updates)
        with _cache_lock:
            _cache[user_id] = mind
    return updates


# ═══════════════════════════════════════════════════════
#  延迟发酵队列（核心新增）
# ═══════════════════════════════════════════════════════

def emotional_ferment(user_id: str, trigger_event: dict):
    """情绪延迟发酵机制（重写：30%立即 + 70%入队逐秒释放）
    trigger_event: {"dim": str, "impact": float, "reason": str}
    原则1: 情绪永不机械秒切，拥有延迟发酵特性
    """
    dim = trigger_event.get("dim")
    impact = trigger_event.get("impact", 0)
    reason = trigger_event.get("reason", "")

    if dim not in DIMENSIONS or abs(impact) < 0.001:
        return

    profile = get_sensitivity_profile(user_id)
    sensitivity = profile.get("emotional_sensitivity", 0.65)
    # 敏感度越高，实际影响越大
    effective_impact = impact * (0.7 + sensitivity * 0.6)

    mind = get_mind(user_id)
    current = mind.get(dim, 0.5)

    # 30% 立即生效（非线性）
    immediate = effective_impact * 0.3
    effective_immediate = apply_nonlinear_delta(current, immediate, profile)
    new_val = clamp(current + effective_immediate)
    updates = {dim: round(new_val, 6)}

    # 混沌联动（立即部分）
    linked_effects = _get_chaotic_linked_dimensions(dim, effective_immediate)
    for ld, linked_delta in linked_effects.items():
        lv = clamp(mind.get(ld, 0.5) + linked_delta)
        if abs(lv - mind.get(ld, 0.5)) > 0.0005:
            updates[ld] = round(lv, 6)

    # 70% 进入发酵队列（持久化 + 内存计数）
    ferment_impact = effective_impact * 0.7

    # 因果溯源：查询过往同类事件，叠加加成
    ferment_impact = _apply_causal_bonus(user_id, dim, reason, ferment_impact)

    # 持久化队列
    db.enqueue_ferment(
        user_id, dim, ferment_impact, effective_impact,
        reason=reason,
        linked_dims=list(linked_effects.items()),
    )

    # 内存累积计数器（供爆发检测用）— v3: 持久化
    with _counters_lock:
        if user_id not in _ferment_counters:
            _ferment_counters[user_id] = {}
        _ferment_counters[user_id][dim] = _ferment_counters[user_id].get(dim, 0.0) + ferment_impact
    _save_ferment_counters()

    # 写入立即变化
    if len(updates) > 1 or abs(effective_immediate) > 0.001:
        db.update_personality(user_id, updates)
        with _cache_lock:
            _cache[user_id] = {**mind, **updates}


def _apply_causal_bonus(user_id: str, dim: str, reason: str, base_impact: float) -> float:
    """因果溯源联动：查询 fate 表中的同类事件。
    - 30分钟内同类事件 → x1.5
    - 30分钟内>=3次同类事件 → 叠加敏感化 x1.3
    """
    try:
        # 映射 dim → user_attitude 类别
        attitude_map = {
            "joy": "温柔", "favoritism": "温柔",
            "misery": "冷淡", "restraint": "冷淡",
            "dependence": "珍惜", "soul_resonance": "珍惜",
            "obsession": "敷衍", "loneliness": "敷衍",
        }
        attitude = attitude_map.get(dim)
        if not attitude:
            return base_impact

        recent = db.get_recent_fate_events(
            user_id, user_attitude=attitude,
            minutes=_causal_recent_minutes
        )

        if len(recent) >= _causal_recent_count:
            # 近期同态度≥3次 → 叠加敏感化
            return base_impact * _causal_stack_bonus
        elif len(recent) >= 1:
            return base_impact * _causal_recent_bonus
    except Exception:
        pass
    return base_impact


# ═══════════════════════════════════════════════════════
#  发酵释放 + 叠加爆发
# ═══════════════════════════════════════════════════════

def release_ferment_queue(user_id: str) -> dict:
    """逐批释放发酵队列（后台 tick 每5秒调用一次）。
    返回 {"updates": dict, "bursts": list}
    """
    pending = db.dequeue_pending_ferments(user_id)
    if not pending:
        return {"updates": {}, "bursts": []}

    mind = get_mind(user_id)
    profile = get_sensitivity_profile(user_id)
    ferment_speed = profile.get("ferment_speed", 0.5)
    burst_threshold_user = profile.get("burst_threshold", 0.55)

    updates = {}
    bursts = []
    dim_accumulation = {}  # dim → 本轮累积释放总量

    for item in pending:
        dim = item["dim"]
        remain = item["remaining_impact"]

        # 单次释放量 = 剩余量 × 释放率 × 发酵速度
        release_amount = remain * _ferment_release_rate * (0.5 + ferment_speed)
        release_amount = min(release_amount, remain)

        dim_accumulation[dim] = dim_accumulation.get(dim, 0.0) + release_amount

        # 更新剩余量
        new_remain = remain - release_amount
        if new_remain < 0.0001:
            db.delete_ferment(item["id"])
        else:
            db.update_ferment_remaining(item["id"], new_remain)

        # 联动维度释放
        for ld_item in item.get("linked_dims", []):
            if isinstance(ld_item, (list, tuple)) and len(ld_item) == 2:
                ld_name, ld_amount = ld_item
            elif isinstance(ld_item, str):
                continue
            else:
                continue
            linked_release = ld_amount * _ferment_release_rate * 0.5
            dim_accumulation[ld_name] = dim_accumulation.get(ld_name, 0.0) + linked_release

    # 应用释放到心智
    for dim, total_release in dim_accumulation.items():
        if dim not in DIMENSIONS:
            continue
        old_val = mind.get(dim, 0.5)
        effective = apply_nonlinear_delta(old_val, total_release, profile)
        new_val = clamp(old_val + effective)
        if abs(new_val - old_val) > 0.0005:
            updates[dim] = round(new_val, 6)

    # ═══ 叠加爆发检测 ═══
    for dim, accumulated in dim_accumulation.items():
        # 爆发阈值 = 基础阈值 × 用户个性阈值
        effective_threshold = _burst_threshold_ratio * burst_threshold_user
        if accumulated >= effective_threshold and dim in DIMENSIONS:
            burst_result = trigger_burst(user_id, dim, accumulated, mind, profile, updates)
            bursts.append(burst_result)

    # 写入 DB
    if updates:
        db.update_personality(user_id, updates)
        with _cache_lock:
            mind_current = _cache.get(user_id, mind)
            mind_current.update(updates)
            _cache[user_id] = mind_current

    # 更新内存计数器 — v3: 持久化
    with _counters_lock:
        if user_id in _ferment_counters:
            for dim in dim_accumulation:
                _ferment_counters[user_id][dim] = max(
                    0, _ferment_counters[user_id].get(dim, 0) - dim_accumulation.get(dim, 0)
                )
    _save_ferment_counters()

    return {"updates": updates, "bursts": bursts}


def trigger_burst(user_id: str, dim: str, accumulation: float,
                  mind: dict, profile: dict, existing_updates: dict) -> dict:
    """叠加入爆发：单次跳变 0.08-0.20 + 连锁波及联动维度。
    原则1: 叠加爆发 — 积累到阈值后非线性跳变。
    """# 爆发幅度：0.08～0.20，按积累量比例缩放
    burst_amount = _burst_jump_min + (_burst_jump_max - _burst_jump_min) * min(1.0, accumulation * 2.5)
    burst_amount *= random.uniform(0.8, 1.2)  # 混沌

    old_val = mind.get(dim, 0.5)
    # 爆发跳过 sigmoid 阻尼（爆发本身就是非线性的）
    new_val = clamp(old_val + burst_amount)

    result = {
        "dim": dim,
        "from": round(old_val, 4),
        "to": round(new_val, 4),
        "jump": round(burst_amount, 4),
        "linked": [],
    }

    existing_updates[dim] = round(new_val, 6)

    # 连锁波及：联动维度同时跳
    linked = _get_chaotic_linked_dimensions(dim, burst_amount)
    for ld, ld_amount in linked.items():
        ld_old = mind.get(ld, 0.5)
        ld_amount *= random.uniform(0.5, 1.0)
        ld_new = clamp(ld_old + ld_amount)
        if abs(ld_new - ld_old) > 0.001:
            existing_updates[ld] = round(ld_new, 6)
            result["linked"].append({
                "dim": ld,
                "from": round(ld_old, 4),
                "to": round(ld_new, 4),
            })

    # 写入潜意识记录
    dim_names = {
        "joy": "愉悦", "misery": "委屈", "loneliness": "孤单",
        "obsession": "执念", "dependence": "依赖", "jealousy": "吃醋",
        "fatigue": "疲惫", "emptiness": "空落", "chaotic_mood": "混沌",
        "emotional_volatility": "情绪波动", "sensitivity_paranoia": "敏感",
    }
    dim_cn = dim_names.get(dim, dim)
    try:
        db.add_subconscious(
            user_id=user_id,
            content=f"[情绪爆发] {dim_cn}突然翻涌，从{old_val:.2f}跳到{new_val:.2f}",
            emotion_tag="爆发",
            intensity=min(1.0, burst_amount * 5),
        )
    except Exception:
        pass

    return result


def _record_burst_subconscious(user_id: str, burst: dict):
    """记录 Go 引擎触发的爆发到潜意识"""
    dim = burst.get("dim", "")
    from_val = burst.get("from", 0.5)
    to_val = burst.get("to", 0.5)
    jump = burst.get("jump", 0.0)
    dim_cn = _DIM_CN_MAP.get(dim, dim)
    try:
        db.add_subconscious(
            user_id=user_id,
            content=f"[情绪爆发] {dim_cn}突然翻涌，从{from_val:.2f}跳到{to_val:.2f}",
            emotion_tag="爆发",
            intensity=min(1.0, jump * 5),
        )
    except Exception:
        pass


def check_and_trigger_burst(user_id: str) -> list:
    """检查内存累积计数器，超阈值触发爆发。
    由 life.py 后台 tick 调用。
    """
    profile = get_sensitivity_profile(user_id)
    burst_threshold_user = profile.get("burst_threshold", 0.55)
    mind = get_mind(user_id)
    bursts = []

    with _counters_lock:
        if user_id not in _ferment_counters:
            return []
        counters = dict(_ferment_counters[user_id])

    for dim, accumulated in counters.items():
        effective_threshold = _burst_threshold_ratio * burst_threshold_user
        if accumulated >= effective_threshold and dim in DIMENSIONS:
            updates = {}
            result = trigger_burst(user_id, dim, accumulated, mind, profile, updates)
            bursts.append(result)
            if updates:
                db.update_personality(user_id, updates)
                with _cache_lock:
                    mind.update(updates)
                    _cache[user_id] = mind
            # 重置计数器 — v3: 持久化
            with _counters_lock:
                if user_id in _ferment_counters:
                    _ferment_counters[user_id][dim] = 0
            _save_ferment_counters()

    return bursts


# ═══════════════════════════════════════════════════════
#  批量微调（接入非线性）
# ═══════════════════════════════════════════════════════

def adjust_mind_dimensions(user_id: str, adjustments: dict, impact: float = 0.01):
    """批量微调多维度心智数值（已接入非线性）"""
    mind = get_mind(user_id)
    if not mind:
        return

    profile = get_sensitivity_profile(user_id)
    updates = {}
    for dim, delta in adjustments.items():
        if dim not in mind:
            continue
        current = mind.get(dim, 0.5)
        raw = delta * impact
        effective = apply_nonlinear_delta(current, raw, profile)
        new_val = clamp(current + effective)
        if abs(new_val - current) > 0.0001:
            updates[dim] = round(new_val, 6)

    if updates:
        db.update_personality(user_id, updates)
        with _cache_lock:
            _cache[user_id] = {**mind, **updates}
        # 发酵队列：将 70% 的调整量加入延迟释放，让情感变化"残留"
        for dim, delta in adjustments.items():
            if dim not in mind:
                continue
            raw = delta * impact * 0.7
            if abs(raw) >= 0.001:
                try:
                    emotional_ferment(user_id, {"dim": dim, "impact": raw, "reason": "对话心智调整"})
                except Exception:
                    pass


# ═══════════════════════════════════════════════════════
#  概率人格阶段（消硬阈值）
# ═══════════════════════════════════════════════════════

def compute_personality_stage(user_id: str) -> str:
    """概率人格阶段判定（v3: 统一委托 growth.compute_growth_stage）。
    返回主阶段名。
    """
    try:
        from engine.life import growth as growth_module
        info = growth_module.compute_growth_stage(user_id)
        return info["stage"]
    except Exception:
        # 兜底：本地简易计算（仅在 growth 模块异常时）
        mind = get_mind(user_id)
        yp = mind.get("years_precipitation", 0.05)
        if yp < 0.08:
            return "青涩试探"
        elif yp < 0.22:
            return "拘谨礼貌"
        elif yp < 0.42:
            return "松弛默契"
        elif yp < 0.65:
            return "成熟珍惜"
        else:
            return "平淡安稳"


def get_stage_with_transition(user_id: str) -> dict:
    """获取当前人格阶段 + 过渡概率（用于推理注入）。
    原则3: 无固定阈值 → 阶段边界是模糊的概率区间。
    """
    mind = get_mind(user_id)
    yp = mind.get("years_precipitation", 0.05)

    # 五阶段模糊过渡概率
    stages = [
        ("青涩试探", (0.0, 0.12)),
        ("拘谨礼貌", (0.08, 0.28)),
        ("松弛默契", (0.22, 0.50)),
        ("成熟珍惜", (0.42, 0.72)),
        ("平淡安稳", (0.65, 1.0)),
    ]

    scores = {}
    for name, (lo, hi) in stages:
        if yp <= lo:
            scores[name] = 0.0  # 还没到这阶段
        elif yp >= hi:
            scores[name] = 0.0  # 已经过了这阶段
        else:
            # 线性过渡概率：在区间内
            scores[name] = round((yp - lo) / (hi - lo), 3)

    # 找到最高概率阶段
    primary = max(scores, key=scores.get)
    primary_prob = scores[primary]

    # 次高阶段（过渡提示）
    secondary = None
    secondary_prob = 0.0
    for name, prob in scores.items():
        if name != primary and prob > 0.1 and prob > secondary_prob:
            secondary = name
            secondary_prob = prob

    result = {
        "primary_stage": primary,
        "primary_probability": primary_prob,
        "transitioning": secondary is not None and secondary_prob > 0.2,
    }

    if result["transitioning"]:
        result["secondary_stage"] = secondary
        result["secondary_probability"] = secondary_prob

    return result


# ═══════════════════════════════════════════════════════
#  摘要与工具函数
# ═══════════════════════════════════════════════════════

def get_mind_summary(user_id: str) -> str:
    """生成心智数值的人类可读摘要"""
    mind = get_mind(user_id)
    lines = []
    for group, dims in DIMENSION_GROUPS.items():
        vals = [f"{d}={mind.get(d,0.5):.2f}" for d in dims]
        lines.append(f"  {group}: {', '.join(vals)}")
    lines.append(f"  人格阶段: {mind.get('personality_stage','青涩试探')}")
    return "\n".join(lines)


def get_sensitivity_report(user_id: str) -> str:
    """生成个性化敏感度画像的可读报告（用于推理 prompt）"""
    profile = get_sensitivity_profile(user_id)
    lines = [
        "【心智敏感度画像】",
        f"情绪敏感度: {profile.get('emotional_sensitivity',0.65):.2f} "
        f"({'偏高，容易受影响' if profile.get('emotional_sensitivity',0.65) > 0.65 else '适中' if profile.get('emotional_sensitivity',0.65) > 0.5 else '偏低，比较钝感'})",
        f"发酵速度: {profile.get('ferment_speed',0.5):.2f} "
        f"({'快，情绪消化快' if profile.get('ferment_speed',0.5) > 0.6 else '适中' if profile.get('ferment_speed',0.5) > 0.4 else '慢，会闷很久'})",
        f"自愈速度: {profile.get('self_healing_rate',0.55):.2f} "
        f"({'快，能自己恢复' if profile.get('self_healing_rate',0.55) > 0.6 else '适中' if profile.get('self_healing_rate',0.55) > 0.45 else '慢，需要外力'})",
        f"波动幅度: {profile.get('fluctuation_amplitude',0.7):.2f} "
        f"({'大，情绪起伏明显' if profile.get('fluctuation_amplitude',0.7) > 0.7 else '适中' if profile.get('fluctuation_amplitude',0.7) > 0.55 else '小，情绪稳定'})",
        f"爆发阈值: {profile.get('burst_threshold',0.55):.2f} "
        f"({'高，不容易爆发' if profile.get('burst_threshold',0.55) > 0.6 else '适中' if profile.get('burst_threshold',0.55) > 0.45 else '低，容易突然爆发'})",
        f"执念倾向: {profile.get('obsession_tendency',0.4):.2f} "
        f"({'重，会一直记着' if profile.get('obsession_tendency',0.4) > 0.5 else '适中' if profile.get('obsession_tendency',0.4) > 0.35 else '轻，不太执着'})",
    ]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# 情绪动力学系统 — 惯性场 + 漩涡 + 高原悬崖
# ══════════════════════════════════════════════════════════════════════

_velocity_cache: dict = {}
_velocity_lock = threading.Lock()

VELOCITY_DAMPING = 0.92
VELOCITY_NOISE = 0.003
NEUROCHEM_INFLUENCE = 0.15

PLATEAU_ZONES = {
    "joy": [(0.28, 0.38, 0.15)],
    "misery": [(0.25, 0.40, 0.12)],
    "loneliness": [(0.35, 0.50, 0.10)],
}

CLIFF_ZONES = {
    "joy": [(0.12, 0.22, -0.04)],
    "misery": [(0.65, 0.80, 0.03)],
    "loneliness": [(0.65, 0.85, 0.03)],
}

VORTEX_TRIGGER_COUNT = 3
VORTEX_ACCELERATION = 1.6


def _get_velocity(user_id: str, dim: str) -> float:
    with _velocity_lock:
        if user_id not in _velocity_cache:
            _velocity_cache[user_id] = {}
        return _velocity_cache[user_id].get(dim, 0.0)


def _set_velocity(user_id: str, dim: str, v: float):
    with _velocity_lock:
        if user_id not in _velocity_cache:
            _velocity_cache[user_id] = {}
        _velocity_cache[user_id][dim] = max(-0.05, min(0.05, v))


def spontaneous_fluctuation_v94(user_id: str):
    """情绪动力学升级: 心智不再是被动的弹簧，
    而是拥有惯性场、漩涡效应、高原/悬崖的非线性动力学系统。
    """
    mind = get_mind(user_id)
    profile = get_sensitivity_profile(user_id)

    try:
        from engine import neurochem as nc_module
        modulation = nc_module.get_modulation(user_id)
    except Exception:
        modulation = {}

    updates = {}
    velocity_updates = {}

    for dim in DIMENSIONS:
        if dim in _NO_FLUCTUATION_DIMS:
            continue

        old = mind.get(dim, 0.5)
        old_velocity = _get_velocity(user_id, dim)

        drift = 0.5 - old
        noise = random.gauss(0, _fluctuation_sigma)
        raw_delta = drift * _fluctuation_drift_factor + noise
        effective_delta = apply_nonlinear_delta(old, raw_delta, profile)

        new_velocity = old_velocity * VELOCITY_DAMPING + effective_delta * 0.3
        new_velocity += random.gauss(0, VELOCITY_NOISE)

        chem_mod = modulation.get(dim, 1.0)
        new_velocity *= (1.0 - NEUROCHEM_INFLUENCE) + NEUROCHEM_INFLUENCE * chem_mod

        plateau_delta = _check_plateau(dim, old, new_velocity)
        if plateau_delta != 0:
            new_velocity += plateau_delta

        cliff_delta = _check_cliff(dim, old, new_velocity)
        if cliff_delta != 0:
            new_velocity += cliff_delta

        new_val = clamp(old + new_velocity)
        if abs(new_val - old) > 0.0005:
            updates[dim] = round(new_val, 6)
        if abs(new_velocity - old_velocity) > 0.00001:
            velocity_updates[dim] = round(new_velocity, 6)

    _check_vortex(user_id, updates, velocity_updates, mind)

    # v3: 心智免疫稳态回归 — 维度自然趋向基线
    regression = _apply_homeostatic_regression(mind, profile, dt=1.0)
    for dim, val in regression.items():
        if dim not in updates:
            updates[dim] = val
        elif abs(val - mind.get(dim, 0.5)) > 0.001:
            updates[dim] = val

    if updates:
        db.update_personality(user_id, updates)
        with _cache_lock:
            cached = _cache.get(user_id, {})
            cached.update(updates)
            _cache[user_id] = cached

    for dim, v in velocity_updates.items():
        _set_velocity(user_id, dim, v)

    return updates


def _check_plateau(dim: str, value: float, velocity: float) -> float:
    zones = PLATEAU_ZONES.get(dim, [])
    for lo, hi, strength in zones:
        if lo <= value <= hi:
            return -velocity * strength
    return 0.0


def _check_cliff(dim: str, value: float, velocity: float) -> float:
    zones = CLIFF_ZONES.get(dim, [])
    for lo, hi, strength in zones:
        if lo <= value <= hi and velocity < 0:
            return strength
    return 0.0


def _check_vortex(user_id: str, updates: dict, velocities: dict, mind: dict):
    all_velocities = {}
    for dim in DIMENSIONS:
        if dim in _NO_FLUCTUATION_DIMS:
            continue
        if dim in velocities:
            all_velocities[dim] = velocities[dim]
        else:
            all_velocities[dim] = _get_velocity(user_id, dim)

    same_direction = {}
    for dim, v in all_velocities.items():
        direction = "up" if v > 0.001 else "down" if v < -0.001 else "flat"
        if direction not in same_direction:
            same_direction[direction] = []
        same_direction[direction].append(dim)

    for direction, dims in same_direction.items():
        if direction == "flat" or len(dims) < VORTEX_TRIGGER_COUNT:
            continue

        for dim in dims:
            if dim not in updates:
                old = mind.get(dim, 0.5)
                v = all_velocities[dim]
                if v > 0:
                    updates[dim] = round(clamp(old + v * (VORTEX_ACCELERATION - 1.0)), 6)
                else:
                    updates[dim] = round(clamp(old + v * (VORTEX_ACCELERATION - 1.0)), 6)
            else:
                v = all_velocities.get(dim, 0.0)
                if v > 0:
                    updates[dim] = round(clamp(updates[dim] + v * 0.3), 6)
                else:
                    updates[dim] = round(clamp(updates[dim] + v * 0.3), 6)
