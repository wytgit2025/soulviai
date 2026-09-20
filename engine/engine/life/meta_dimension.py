# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""动态维度注册表 — Meta-Dimension Registry
================================================
让动态新增的心智维度自动接入耦合矩阵和核心心智计算。

三级进化：
  Level 1: 动态新增维度列 (已有 ✓)
  Level 2: 自动注册到耦合矩阵 (本模块实现)
  Level 3: 维度分裂/合并/消亡 (本模块实现)

架构：
  DIMENSION_REGISTRY 维护每个维度的完整定义
  新维度通过遗传算法从相似维度继承耦合权重
  零使用维度自动休眠，不影响心智计算效率
"""
import json
import math
import os
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from core import database as db
from core import config as cfg

# ── 配置 ──
_DIM_CONFIG = {
    "max_dynamic_dimensions": 12,
    "dormant_days_threshold": 30,
    "dormant_usage_threshold": 1,
    "inheritance_similarity_threshold": 0.3,
    "initial_coupling_weight": 0.05,
    "split_maturity_days": 60,
}

# ── 维度注册表 ──
_DIMENSION_REGISTRY: Dict[str, dict] = {}
# 相对 cwd（core.paths.chdir_home() 切到数据家目录），不要用 __file__ 拼
_REGISTRY_FILE = os.path.join("data", "json", "dimension_registry.json")

# 基础维度中文名映射（用于显示）
_BASE_DIM_NAMES = {
    "joy": "愉悦", "misery": "委屈", "dependence": "依赖", "jealousy": "吃醋",
    "fatigue": "疲惫", "loneliness": "孤单", "favoritism": "偏爱",
    "sensitivity_paranoia": "敏感多疑", "emotional_healing": "情感自愈",
    "obsession": "执念", "emptiness": "空落", "chaotic_mood": "混沌情绪",
    "life_sense": "生活感", "restraint": "克制", "emotional_volatility": "情绪波动",
    "years_precipitation": "岁月沉淀", "relationship_fatigue": "关系疲惫",
    "healing_reflection": "自愈复盘", "body_perception": "躯体感知",
    "autonomous_values": "自主价值观", "life_vitality": "生命活力",
    "bidirectional_shaping": "双向塑造", "causal_fate": "因果宿命",
    "soul_resonance": "灵魂共鸣",
}

# 基本耦合模板（基础维度的典型耦合模式）
_BASE_COUPLING_TEMPLATES = {
    "joy": {"misery": -0.25, "life_vitality": 0.20, "emotional_healing": 0.15},
    "misery": {"joy": -0.25, "loneliness": 0.15, "sensitivity_paranoia": 0.12},
    "dependence": {"favoritism": 0.20, "soul_resonance": 0.15, "bidirectional_shaping": 0.10},
    "sensitivity_paranoia": {"misery": 0.12, "obsession": 0.15, "emotional_volatility": 0.20},
    "chaotic_mood": {"emotional_volatility": 0.15, "life_sense": -0.10, "restraint": -0.12},
    "life_vitality": {"joy": 0.18, "fatigue": -0.20, "life_sense": 0.15},
}


# ══════════════════════════════════════════════════════════════════════
# 内部：注册表持久化
# ══════════════════════════════════════════════════════════════════════

def _load_registry():
    """从文件加载维度注册表"""
    global _DIMENSION_REGISTRY
    try:
        if os.path.exists(_REGISTRY_FILE):
            with open(_REGISTRY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                _DIMENSION_REGISTRY = data if isinstance(data, dict) else {}
        else:
            _DIMENSION_REGISTRY = {}
    except Exception:
        _DIMENSION_REGISTRY = {}


def _save_registry():
    """保存维度注册表到文件"""
    try:
        os.makedirs(os.path.dirname(_REGISTRY_FILE), exist_ok=True)
        with open(_REGISTRY_FILE, "w", encoding="utf-8") as f:
            json.dump(_DIMENSION_REGISTRY, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
# Level 2: 自动注册到耦合矩阵
# ══════════════════════════════════════════════════════════════════════

def register_new_dimension(dim_name: str, display_name: str = "",
                           group: str = "新生特质", base_intensity: float = 0.4):
    """将新维度注册到完整的 DIMENSION_REGISTRY 中。
    
    自动完成：
      1. 生成维度定义
      2. 从相似维度继承耦合权重
      3. 写入注册表
      4. 通知 mind.py 刷新 DIMENSIONS 列表
    """
    _load_registry()

    if dim_name in _DIMENSION_REGISTRY or dim_name in _BASE_DIM_NAMES:
        return

    display = display_name or dim_name.replace("dynamic_", "")

    # 从相似维度继承耦合权重
    coupling = _inherit_coupling_weights(dim_name)

    entry = {
        "name": dim_name,
        "display_name": display,
        "group": group,
        "base_intensity": base_intensity,
        "is_dynamic": True,
        "coupling_weights": coupling,
        "birth_time": time.time(),
        "usage_count": 0,
        "last_used": 0.0,
        "is_dormant": False,
        "inherited_from": _find_similar_dimension(dim_name),
    }
    _DIMENSION_REGISTRY[dim_name] = entry
    _save_registry()

    # 通知 mind.py 刷新 DIMENSIONS
    try:
        from engine import mind as mind_module
        mind_module.refresh_dynamic_dimensions()
    except Exception:
        pass

    print(f"[维度注册表] 新维度 '{display}' 已注册，继承自 {entry['inherited_from']}")


def _find_similar_dimension(new_dim_name: str) -> str:
    """找语义上最相似的基础维度名"""
    name_lower = new_dim_name.lower().replace("dynamic_", "")
    # 关键词匹配
    keyword_map = {
        "humor": "joy", "幽默": "joy", "funny": "joy",
        "patience": "restraint", "耐心": "restraint",
        "tolerance": "restraint", "包容": "restraint",
        "confidence": "life_vitality", "自信": "life_vitality",
        "curiosity": "life_sense", "好奇": "life_sense",
        "gratitude": "emotional_healing", "感恩": "emotional_healing",
        "resilience": "emotional_healing", "坚强": "emotional_healing",
        "poetic": "chaotic_mood", "诗意": "life_sense",
        "candor": "chaotic_mood", "率真": "chaotic_mood",
        "tenderness": "favoritism", "温柔": "favoritism", "细腻": "sensitivity_paranoia",
    }
    matched = None
    for keyword, target in keyword_map.items():
        if keyword in name_lower or keyword in new_dim_name:
            matched = target
            break
    return matched or "joy"  # fallback


def _inherit_coupling_weights(new_dim_name: str) -> Dict[str, float]:
    """从最相似的基础维度继承初始耦合权重"""
    similar = _find_similar_dimension(new_dim_name)
    template = _BASE_COUPLING_TEMPLATES.get(similar, {})

    inherited = {}
    for target, weight in template.items():
        inherited[target] = round(weight * random.uniform(0.6, 1.0), 4)

    # 对每个已有注册维度添加弱反向边
    for existing_dim, entry in _DIMENSION_REGISTRY.items():
        if existing_dim not in inherited:
            inherited[existing_dim] = _DIM_CONFIG["initial_coupling_weight"]

    return inherited


def register_dynamic_dimensions_from_db():
    """扫描数据库中的 dynamic_ 列，注册所有未注册的动态维度"""
    _load_registry()

    try:
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.execute("PRAGMA table_info(personality)")
        columns = [row[1] for row in cursor.fetchall()]
        conn.close()
    except Exception:
        return

    dynamic_dims = [c for c in columns if c.startswith("dynamic_")]
    for dim in dynamic_dims:
        if dim not in _DIMENSION_REGISTRY and dim not in _BASE_DIM_NAMES:
            # 自动注册
            register_new_dimension(dim)


# ══════════════════════════════════════════════════════════════════════
# Level 3: 维度分裂/合并/消亡
# ══════════════════════════════════════════════════════════════════════

def split_dimension(old_dim: str, new_dim_a: str, new_dim_b: str,
                    split_ratio: float = 0.5, display_a: str = "",
                    display_b: str = "", group: str = "新生特质"):
    """将一个维度分裂为两个子维度——心智架构的细化（架构级自修改）

    流程：
      1. 从所有用户获取旧维度值
      2. ALTER TABLE 新增两个子列
      3. 按 split_ratio 分配旧值到两个子列
      4. 旧维度的耦合权重分裂到两个子维度
      5. 注册两个新维度到注册表
      6. 旧维度标记为休眠

    注意：分裂操作不可逆，需要先在测试环境验证。
    """
    _load_registry()

    if old_dim not in _DIMENSION_REGISTRY and old_dim not in _BASE_DIM_NAMES:
        print(f"[维度分裂] {old_dim} 不在注册表中，跳过")
        return

    try:
        # 1. 获取旧维度值
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        rows = conn.execute(
            f"SELECT user_id, COALESCE({old_dim}, 0.4) as val FROM personality"
        ).fetchall()
    except Exception as e:
        print(f"[维度分裂] 读取 {old_dim} 失败: {e}")
        return

    # 2 + 3. ALTER TABLE + 分裂值
    try:
        conn.execute(f"ALTER TABLE personality ADD COLUMN {new_dim_a} REAL DEFAULT {0.2}")
    except Exception:
        pass
    try:
        conn.execute(f"ALTER TABLE personality ADD COLUMN {new_dim_b} REAL DEFAULT {0.2}")
    except Exception:
        pass

    for user_id, val in rows:
        try:
            conn.execute(
                f"UPDATE personality SET {new_dim_a}=?, {new_dim_b}=? WHERE user_id=?",
                (round(val * split_ratio, 6), round(val * (1 - split_ratio), 6), user_id)
            )
        except Exception:
            pass
    conn.commit()

    # 4. 耦合权重分裂
    old_weights = _DIMENSION_REGISTRY.get(old_dim, {}).get("coupling_weights", {})
    weights_a = {k: round(v * split_ratio, 4) for k, v in old_weights.items()}
    weights_b = {k: round(v * (1 - split_ratio), 4) for k, v in old_weights.items()}

    # 5. 注册新维度
    entry_a = {
        "name": new_dim_a, "display_name": display_a or new_dim_a,
        "group": group, "base_intensity": 0.4, "is_dynamic": True,
        "coupling_weights": weights_a, "birth_time": time.time(),
        "usage_count": 0, "last_used": 0.0, "is_dormant": False,
        "parent_dim": old_dim,
    }
    entry_b = {
        "name": new_dim_b, "display_name": display_b or new_dim_b,
        "group": group, "base_intensity": 0.4, "is_dynamic": True,
        "coupling_weights": weights_b, "birth_time": time.time(),
        "usage_count": 0, "last_used": 0.0, "is_dormant": False,
        "parent_dim": old_dim,
    }
    _DIMENSION_REGISTRY[new_dim_a] = entry_a
    _DIMENSION_REGISTRY[new_dim_b] = entry_b

    # 6. 旧维度休眠
    if old_dim in _DIMENSION_REGISTRY:
        _DIMENSION_REGISTRY[old_dim]["is_dormant"] = True
        _DIMENSION_REGISTRY[old_dim]["dormant_since"] = time.time()

    _save_registry()
    conn.close()

    # 通知 mind 刷新
    try:
        from engine import mind as mind_module
        mind_module.refresh_dynamic_dimensions()
    except Exception:
        pass

    print(f"[维度分裂] {old_dim} → {new_dim_a} + {new_dim_b}")


def check_dormant_dimensions():
    """定期检测零使用维度→标记为休眠"""
    _load_registry()
    now = time.time()
    changed = False

    for dim_name, entry in list(_DIMENSION_REGISTRY.items()):
        if not entry.get("is_dynamic") or entry.get("is_dormant"):
            continue

        age_days = (now - entry.get("birth_time", now)) / 86400
        usage = entry.get("usage_count", 0)
        if age_days > _DIM_CONFIG["dormant_days_threshold"] and usage / max(1, age_days) < _DIM_CONFIG["dormant_usage_threshold"]:
            entry["is_dormant"] = True
            entry["dormant_since"] = now
            print(f"[维度注册表] {entry.get('display_name', dim_name)} 已休眠 (使用率{usage}/{age_days:.0f}天)")
            changed = True

    if changed:
        _save_registry()


def increment_usage(dim_name: str):
    """增加维度使用计数——从 mind.py 调用"""
    if dim_name in _DIMENSION_REGISTRY:
        _DIMENSION_REGISTRY[dim_name]["usage_count"] = \
            _DIMENSION_REGISTRY[dim_name].get("usage_count", 0) + 1
        _DIMENSION_REGISTRY[dim_name]["last_used"] = time.time()


def get_active_dimensions() -> List[str]:
    """获取当前活跃的所有维度（排除休眠的）"""
    _load_registry()
    active = set()
    # 基础维度始终活跃
    for dim in _BASE_DIM_NAMES:
        active.add(dim)
    # 动态维度过滤休眠
    for dim_name, entry in _DIMENSION_REGISTRY.items():
        if not entry.get("is_dormant"):
            active.add(dim_name)
    return sorted(active)


def get_registry_summary() -> str:
    """获取维度注册表摘要"""
    _load_registry()
    dynamic_count = sum(1 for e in _DIMENSION_REGISTRY.values() if e.get("is_dynamic"))
    dormant_count = sum(1 for e in _DIMENSION_REGISTRY.values() if e.get("is_dormant"))
    return f"注册表: {dynamic_count}动态/{dormant_count}休眠"


# ══════════════════════════════════════════════════════════════════════
# Level 4: 维度合并/自动清理
# ══════════════════════════════════════════════════════════════════════

def merge_dimensions(dim_a: str, dim_b: str, new_name: str,
                     display_name: str = "", group: str = "合并特质"):
    """将两个相似维度合并为一个——分裂的反操作

    merge_dimensions("dynamic_warmth", "dynamic_tenderness", "dynamic_care")
    → warmth 和 tenderness 合并为 care，保留两者的耦合权重均值
    """
    _load_registry()

    for d in [dim_a, dim_b]:
        if d not in _DIMENSION_REGISTRY and d not in _BASE_DIM_NAMES:
            print(f"[维度合并] {d} 不在注册表中，跳过")
            return

    import sqlite3
    try:
        conn = sqlite3.connect(db.DB_PATH)

        # 1. 获取两个维度的值，合并为新列
        rows = conn.execute(
            f"SELECT user_id, COALESCE({dim_a}, 0.4) as va, "
            f"COALESCE({dim_b}, 0.4) as vb FROM personality"
        ).fetchall()

        conn.execute(f"ALTER TABLE personality ADD COLUMN {new_name} REAL DEFAULT 0.4")

        for uid, va, vb in rows:
            merged_val = (va + vb) / 2
            conn.execute(
                f"UPDATE personality SET {new_name} = ? WHERE user_id = ?",
                (round(merged_val, 4), uid)
            )
        conn.commit()

        # 2. 合并耦合权重
        weights_a = _DIMENSION_REGISTRY.get(dim_a, {}).get("coupling_weights", {})
        weights_b = _DIMENSION_REGISTRY.get(dim_b, {}).get("coupling_weights", {})
        merged_weights = {}
        all_keys = set(weights_a.keys()) | set(weights_b.keys())
        for k in all_keys:
            w_a = weights_a.get(k, 0)
            w_b = weights_b.get(k, 0)
            merged_weights[k] = round((w_a + w_b) / 2, 4)

        register_new_dimension(new_name, display_name or new_name, group,
                               coupling_weights=merged_weights, is_dynamic=True)

        # 3. 标记旧维度为休眠
        for d in [dim_a, dim_b]:
            if d in _DIMENSION_REGISTRY:
                _DIMENSION_REGISTRY[d]["is_dormant"] = True
                _DIMENSION_REGISTRY[d]["merged_into"] = new_name

        _save_registry()
        conn.close()
        print(f"[维度合并] {dim_a} + {dim_b} → {new_name}")
    except Exception as e:
        print(f"[维度合并] 失败: {e}")


def auto_prune_dormant(max_dormant_days: int = 60):
    """自动清理长期休眠维度（从 personality 表中移除列）

    安全策略:
      - 只清理休眠超过 max_dormant_days 天且标记为 is_dynamic 的维度
      - 基础维度永不清理
      - 先备份后删除
    """
    _load_registry()
    now = time.time()
    candidates = []

    for dim_name, entry in _DIMENSION_REGISTRY.items():
        if not entry.get("is_dynamic"):
            continue
        if not entry.get("is_dormant"):
            continue
        dormant_since = entry.get("dormant_since", now)
        if (now - dormant_since) > max_dormant_days * 86400:
            candidates.append(dim_name)

    if not candidates:
        return

    import sqlite3
    try:
        conn = sqlite3.connect(db.DB_PATH)
        for dim in candidates:
            if dim in _BASE_DIM_NAMES:
                continue
            try:
                conn.execute(f"ALTER TABLE personality DROP COLUMN {dim}")
                del _DIMENSION_REGISTRY[dim]
                print(f"[维度清理] 已移除休眠维度: {dim}")
            except Exception:
                pass
        conn.close()
        _save_registry()
    except Exception:
        pass
