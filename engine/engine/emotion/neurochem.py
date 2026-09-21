# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""神经递质化学动力学层 — Neurochemical Dynamics
========================================================
在24维心智数值之上叠加化学递质层，作为心智变化的"速率调控器"而非直接驱动层。
让情绪变化有"化学质感"——不是简单的数字加减，而是有浓度、有半衰期、有级联效应。

五类递质:
  dopamine  — 多巴胺: 驱动愉悦、亲近、活力
  serotonin — 血清素: 稳定情绪、抗焦虑、满足感
  cortisol  — 皮质醇: 压力、委屈、敏感放大器
  oxytocin  — 催产素: 依恋、信任、羁绊深化
  norepi    — 去甲肾上腺素: 警觉、波动、冲动

递质 → 心智维度速率调控映射:
  - 递质浓度不直接改变维度值
  - 递质浓度影响维度的变化速率（加速/减速/阻尼）
  - 递质自身有半衰期、有级联、有对抗关系
"""
import math
import random
import time
from typing import Dict, Tuple
from core import database as db
from core import config as cfg

ACTIVE_CHEMICALS = ["dopamine", "serotonin", "cortisol", "oxytocin", "norepi"]

DEFAULT_LEVELS = {
    "dopamine": 0.45,
    "serotonin": 0.40,
    "cortisol": 0.25,
    "oxytocin": 0.20,
    "norepi": 0.30,
}

HALF_LIFE_SECONDS = {
    "dopamine": 7200,
    "serotonin": 14400,
    "cortisol": 3600,
    "oxytocin": 5400,
    "norepi": 1800,
}

ANTAGONISM = {
    ("serotonin", "cortisol"): 0.4,
    ("dopamine", "cortisol"): 0.3,
    ("oxytocin", "cortisol"): 0.25,
    ("serotonin", "norepi"): 0.35,
}

SYNERGY = {
    ("dopamine", "oxytocin"): 0.3,
    ("dopamine", "norepi"): 0.2,
    ("serotonin", "oxytocin"): 0.25,
    ("cortisol", "norepi"): 0.35,
}

SLOW_DIMS = {"years_precipitation", "healing_reflection", "bidirectional_shaping",
             "causal_fate", "soul_resonance"}

_chemical_cache: Dict[str, Dict[str, float]] = {}
_last_tick: Dict[str, float] = {}


def load_engine_config():
    pass


def _load_chemicals(user_id: str) -> Dict[str, float]:
    """从数据库加载递质浓度，首次自动初始化"""
    if user_id in _chemical_cache:
        return _chemical_cache[user_id]
    try:
        chem = db.get_chemical_state(user_id)
        if chem:
            _chemical_cache[user_id] = {k: chem.get(k, DEFAULT_LEVELS[k]) for k in ACTIVE_CHEMICALS}
        else:
            _chemical_cache[user_id] = dict(DEFAULT_LEVELS)
            db.save_chemical_state(user_id, _chemical_cache[user_id])
    except Exception:
        _chemical_cache[user_id] = dict(DEFAULT_LEVELS)
    return _chemical_cache[user_id]


def _save_chemicals(user_id: str, chem: Dict[str, float]):
    _chemical_cache[user_id] = chem
    try:
        db.save_chemical_state(user_id, chem)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
# 递质自然衰减
# ══════════════════════════════════════════════════════════════════════

def tick_neurochem(user_id: str, dt: float):
    """每秒递质自然衰减 + 对抗/协同效应"""
    global _last_tick
    now = time.time()
    last = _last_tick.get(user_id, now)
    elapsed = now - last
    _last_tick[user_id] = now

    chem = dict(_load_chemicals(user_id))
    changed = False

    for name, half in HALF_LIFE_SECONDS.items():
        if half <= 0:
            continue
        decay_rate = math.log(2) / half
        decay = chem[name] * decay_rate * elapsed
        chem[name] = max(0.01, chem[name] - decay)

    for (a, b), strength in ANTAGONISM.items():
        inhibition = chem[b] * strength * dt * 0.1
        chem[a] = max(0.01, chem[a] - inhibition)

    for (a, b), strength in SYNERGY.items():
        boost = chem[b] * strength * dt * 0.05
        chem[a] = min(1.0, chem[a] + boost)

    for name in ACTIVE_CHEMICALS:
        chem[name] = round(max(0.01, min(1.0, chem[name])), 6)
        if abs(chem[name] - _chemical_cache.get(user_id, {}).get(name, 0)) > 0.001:
            changed = True

    if changed:
        _save_chemicals(user_id, chem)


# ══════════════════════════════════════════════════════════════════════
# 事件驱动的递质释放
# ══════════════════════════════════════════════════════════════════════

def release(user_id: str, chemical: str, amount: float):
    """释放指定递质。amount∈(0,1]，自动clamp"""
    chem = dict(_load_chemicals(user_id))
    if chemical in chem:
        chem[chemical] = min(1.0, chem[chemical] + amount)
        _save_chemicals(user_id, chem)


def on_interaction(user_id: str, comprehension: dict, attitude: str):
    """根据交互结果触发递质释放"""
    intent = comprehension.get("intent", "")
    emotion = comprehension.get("true_emotion", "")
    need = comprehension.get("what_they_need", "")

    if attitude == "温柔" or emotion in ("开心", "温暖", "感动"):
        release(user_id, "dopamine", 0.05)
        release(user_id, "oxytocin", 0.04)
    if attitude == "珍惜":
        release(user_id, "oxytocin", 0.08)
        release(user_id, "dopamine", 0.06)
    if emotion in ("难过", "低落") or need == "安慰":
        release(user_id, "cortisol", 0.03)
    if intent == "倾诉" or comprehension.get("depth") == "深度":
        release(user_id, "oxytocin", 0.07)
        release(user_id, "serotonin", 0.03)
    if attitude == "冷淡" or intent == "敷衍":
        release(user_id, "cortisol", 0.04)
    if emotion == "焦虑":
        release(user_id, "norepi", 0.06)
        release(user_id, "cortisol", 0.03)

    # 深夜额外皮质醇
    try:
        from datetime import datetime
        hour = datetime.now().hour
        if hour >= 22 or hour < 5:
            release(user_id, "cortisol", 0.02)
    except Exception:
        pass


def on_autonomous_thought(user_id: str):
    """自主思考时的递质微调"""
    chem = _load_chemicals(user_id)
    if chem.get("dopamine", 0) > 0.4:
        release(user_id, "serotonin", 0.02)
    if chem.get("cortisol", 0) > 0.5:
        release(user_id, "norepi", 0.03)


# ══════════════════════════════════════════════════════════════════════
# 核心：递质 → 心智变化速率调控（被 mind.py 调用）
# ══════════════════════════════════════════════════════════════════════

def get_modulation(user_id: str) -> Dict[str, float]:
    """返回每个心智维度的速率调控系数。
    > 1.0 = 加速变化，< 1.0 = 减速变化。
    不改变维度本身，只改变 mind.adjust_mind_dimensions 的 impact 参数。
    """
    chem = _load_chemicals(user_id)
    mod = {}

    d = chem.get("dopamine", 0.45)
    s = chem.get("serotonin", 0.40)
    c = chem.get("cortisol", 0.25)
    o = chem.get("oxytocin", 0.20)
    n = chem.get("norepi", 0.30)

    d_boost = 1.0 + d * 0.8
    s_stable = 1.0 - s * 0.5 + 0.5
    c_amp = 1.0 + c * 1.2
    o_bond = 1.0 + o * 0.7
    n_shake = 1.0 + n * 0.9

    joy_mod = d_boost * (1.0 / max(0.3, c_amp))
    mod["joy"] = round(joy_mod, 4)
    mod["misery"] = round(c_amp, 4)
    mod["dependence"] = round(o_bond * (1.0 + c * 0.3), 4)
    mod["jealousy"] = round(c_amp * n_shake * 0.5, 4)
    mod["fatigue"] = round(1.0 / max(0.3, d_boost) * c_amp * 0.5, 4)
    mod["loneliness"] = round(c_amp * (1.0 / max(0.3, o_bond)), 4)
    mod["favoritism"] = round(o_bond, 4)
    mod["sensitivity_paranoia"] = round(c_amp * n_shake * 0.5, 4)
    mod["emotional_healing"] = round(s_stable, 4)
    mod["obsession"] = round(o_bond * c_amp * 0.4, 4)
    mod["emptiness"] = round(c_amp * (1.0 / max(0.3, s_stable)), 4)
    mod["chaotic_mood"] = round(n_shake, 4)
    mod["life_sense"] = round(s_stable, 4)
    mod["restraint"] = round(s_stable * (1.0 + c * 0.3), 4)
    mod["emotional_volatility"] = round(n_shake * c_amp * 0.5, 4)
    mod["life_vitality"] = round(d_boost, 4)

    for dim in SLOW_DIMS:
        mod[dim] = 0.3

    return mod


def apply_neurochem_modulation(user_id: str, raw_adjustments: Dict[str, float]) -> Dict[str, float]:
    """对心智调整量施加递质调控，返回调整后的adjustments"""
    mod = get_modulation(user_id)
    modulated = {}
    for dim, delta in raw_adjustments.items():
        rate = mod.get(dim, 1.0)
        modulated[dim] = round(delta * rate, 6)
    return modulated


# ══════════════════════════════════════════════════════════════════════
# 诊断接口
# ══════════════════════════════════════════════════════════════════════

def get_chemical_summary(user_id: str) -> str:
    chem = _load_chemicals(user_id)
    labels = {"dopamine":"多巴胺","serotonin":"血清素","cortisol":"皮质醇","oxytocin":"催产素","norepi":"去甲"}
    parts = []
    for k, v in chem.items():
        bar = "█" * int(v * 10) + "░" * (10 - int(v * 10))
        parts.append(f"{labels.get(k,k)} [{bar}] {v:.2f}")
    return " | ".join(parts)


# ══════════════════════════════════════════════════════════════════════
# 多巴胺奖励预测误差 (Reward Prediction Error)
# ══════════════════════════════════════════════════════════════════════

_prediction_cache: dict = {}

def set_expectation(user_id: str, expected_outcome: str, expected_joy: float = 0.05):
    """设定一个期望值——下次交互结果和此期望比较，计算预测误差"""
    _prediction_cache[user_id] = {
        "expected": expected_outcome,
        "expected_delta": expected_joy,
        "set_at": time.time(),
    }


def compute_prediction_error(user_id: str, actual_outcome: str,
                              actual_joy_delta: float = 0) -> float:
    """计算多巴胺奖励预测误差 (RPE)。

    这是AI领域最经典的机制之一：
    - RPE > 0: 结果好于预期 → 多巴胺额外释放 → **学习强化**
    - RPE < 0: 结果差于预期 → 多巴胺被抑制 → **行为调整**
    - RPE = 0: 符合预期 → 多巴胺基线 → 不强化不抑制
    """
    prediction = _prediction_cache.pop(user_id, None)
    if not prediction:
        return 0.0

    rpe = actual_joy_delta - prediction["expected_delta"]

    chem = dict(_load_chemicals(user_id))

    if rpe > 0:
        bonus = min(0.15, rpe * 2.0)
        chem["dopamine"] = min(1.0, chem.get("dopamine", 0.45) + bonus)
        _save_chemicals(user_id, chem)
        return round(rpe, 4)
    elif rpe < -0.01:
        penalty = min(0.08, abs(rpe) * 1.5)
        chem["dopamine"] = max(0.01, chem.get("dopamine", 0.45) - penalty)
        chem["cortisol"] = min(1.0, chem.get("cortisol", 0.25) + penalty * 0.5)
        _save_chemicals(user_id, chem)
        return round(rpe, 4)

    return round(rpe, 4)


def on_interaction_with_rpe(user_id: str, comprehension: dict, attitude: str):
    """增强版交互驱动：带预测误差的前瞻性递质释放"""# 先执行基础释放
    on_interaction(user_id, comprehension, attitude)

    # 再计算预测误差
    joy_delta = _estimate_joy_delta(comprehension, attitude)
    actual = f"{attitude}:{comprehension.get('intent','')}:{comprehension.get('true_emotion','')}"
    rpe = compute_prediction_error(user_id, actual, joy_delta)

    # 正预测误差 → 加强学习信号
    if rpe > 0.01:
        try:
            from engine import mind as mind_module
            mind_module.adjust_mind_dimensions(
                user_id,
                {"favoritism": min(0.01, rpe * 0.5)},
                impact=0.3,
            )
        except Exception:
            pass

    # 负预测误差 → 防御/敏感升高
    if rpe < -0.02:
        try:
            from engine import mind as mind_module
            mind_module.adjust_mind_dimensions(
                user_id,
                {"sensitivity_paranoia": min(0.01, abs(rpe) * 0.3)},
                impact=0.2,
            )
        except Exception:
            pass


def _estimate_joy_delta(comprehension: dict, attitude: str) -> float:
    """估算本轮交互带来的愉悦变化量"""
    delta = 0.0
    if attitude == "温柔":
        delta = 0.03
    elif attitude == "珍惜":
        delta = 0.04
    elif attitude in ("冷淡", "敷衍"):
        delta = -0.02
    elif attitude == "沉默":
        delta = -0.04

    emotion = comprehension.get("true_emotion", "")
    if emotion in ("开心", "兴奋", "感动"):
        delta += 0.02
    elif emotion in ("难过", "低落", "焦虑"):
        delta -= 0.01

    if comprehension.get("depth") == "深度":
        delta += 0.01

    return round(delta, 4)


def auto_set_expectation(user_id: str, mind_data: dict):
    """自动根据当前心智状态设定下一轮的隐式期望"""
    joy = mind_data.get("joy", 0.5)
    dependence = mind_data.get("dependence", 0.2)
    loneliness = mind_data.get("loneliness", 0.4)

    if loneliness > 0.5:
        set_expectation(user_id, "希望被回应", 0.04)
    elif dependence > 0.4:
        set_expectation(user_id, "希望被亲近", 0.05)
    elif joy > 0.6:
        set_expectation(user_id, "继续保持", 0.02)
    else:
        set_expectation(user_id, "正常互动", 0.01)
