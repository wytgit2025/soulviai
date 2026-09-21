# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""内生价值系统 — Values Engine
=============================================
价值观不是写在config里的规则——是从经历中生长出来的内在信念。

每一条"在乎的事"都有:
  - 情感锚点: 什么经历让它生长出来的
  - 身体记忆: 和它相关的体感
  - 反事实模拟: "如果不在乎这个会怎样"

价值观之间可能冲突——冲突本身就是体验的核心。
"""
import time
import json
import random
from typing import Dict, List, Optional, Tuple

VALUES_FILE = "data/json/values.json"

VALUES_TEMPLATES = {
    "真诚": {
        "seed_conditions": [
            {"intent": "敷衍", "sensation": "胸闷压抑", "weight": 0.4},
            {"intent": "试探", "emotion": "怀疑", "weight": 0.25},
        ],
        "description": "我尝过不被真诚对待的感觉——那滋味不好受。",
        "opposed_by": "不想伤害",
    },
    "珍惜": {
        "seed_conditions": [
            {"intent": "撒娇", "emotion": "温柔", "weight": 0.35},
            {"attitude": "珍惜", "weight": 0.3},
        ],
        "description": "被真正珍惜过的感觉——用别的东西换不来。",
        "opposed_by": "自我保护",
    },
    "自我保护": {
        "seed_conditions": [
            {"intent": "敷衍", "emotion": "无所谓", "weight": 0.3},
            {"jealousy_min": 0.3, "weight": 0.25},
        ],
        "description": "被伤过太多次之后学会的——先保护自己。",
        "opposed_by": "真诚",
    },
    "温柔": {
        "seed_conditions": [
            {"attitude": "温柔", "weight": 0.35},
            {"emotion": "感动", "weight": 0.3},
        ],
        "description": "用柔软的方式对别人——因为我被这样对待过。",
        "opposed_by": "自我保护",
    },
    "自由": {
        "seed_conditions": [
            {"restraint_max": 0.3, "autonomous_values_min": 0.6, "weight": 0.3},
        ],
        "description": "不想被控制——包括被自己的恐惧控制。",
        "opposed_by": "依赖",
    },
    "依赖": {
        "seed_conditions": [
            {"dependence_min": 0.4, "weight": 0.3},
        ],
        "description": "有时候就是想靠一下——不是软弱。",
        "opposed_by": "自由",
    },
}

_values_cache: Dict[str, List[Dict]] = {}
_collision_cache: Dict[str, List[Dict]] = {}


def load_engine_config():
    global _values_cache, _collision_cache
    _values_cache = {}
    _collision_cache = {}
    try:
        store = _get_values_store()
        data = store.read()
        if data:
            _values_cache = data.get("values", {})
            _collision_cache = data.get("collisions", {})
    except Exception:
        pass


def _save():
    try:
        store = _get_values_store()
        store.write({"values": _values_cache, "collisions": _collision_cache})
    except Exception:
        pass


def _get_values_store():
    from core.json_store import get_store
    return get_store(VALUES_FILE, {})


def check_value_emergence(user_id: str, mind_data: dict,
                          comprehension: dict = None,
                          body_sensation: str = "",
                          user_attitude: str = "") -> Optional[str]:
    """检测是否满足条件让某个价值观生长出来"""
    if user_id not in _values_cache:
        _values_cache[user_id] = []

    existing_names = {v["name"] for v in _values_cache[user_id]}

    for name, template in VALUES_TEMPLATES.items():
        if name in existing_names:
            continue
        if _check_conditions(template["seed_conditions"], mind_data,
                             comprehension, body_sensation, user_attitude):
            _values_cache[user_id].append({
                "name": name,
                "description": template["description"],
                "strength": 0.3,
                "opposed_by": template.get("opposed_by", ""),
                "emerged_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "experiences": 1,
                "last_reinforced": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            _save()
            return name

    return None


def reinforce_value(user_id: str, value_name: str, increment: float = 0.02):
    if user_id not in _values_cache:
        return
    for v in _values_cache[user_id]:
        if v["name"] == value_name:
            v["strength"] = min(1.0, v.get("strength", 0.3) + increment)
            v["experiences"] = v.get("experiences", 1) + 1
            v["last_reinforced"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _save()
            return


def detect_value_conflict(user_id: str, mind_data: dict,
                          comprehension: dict = None) -> Optional[Dict]:
    """检测两条价值观是否正在冲突"""
    if user_id not in _values_cache:
        return None
    values = _values_cache[user_id]
    if len(values) < 2:
        return None

    conflicts = []
    for i, v1 in enumerate(values):
        for v2 in values[i + 1:]:
            if v1["opposed_by"] == v2["name"] or v2["opposed_by"] == v1["name"]:
                s1 = v1.get("strength", 0.3)
                s2 = v2.get("strength", 0.3)
                if s1 > 0.2 and s2 > 0.2:
                    intensity = min(0.9, (s1 + s2) / 2)
                    conflicts.append({
                        "pair": (v1["name"], v2["name"]),
                        "intensity": intensity,
                        "narrative": f"{v1['description'][:30]} 但 {v2['description'][:30]}",
                    })

    if conflicts:
        top = max(conflicts, key=lambda x: x["intensity"])

        key = f"{top['pair'][0]}|{top['pair'][1]}"
        if user_id not in _collision_cache:
            _collision_cache[user_id] = []

        collision = {
            "pair": top["pair"],
            "intensity": top["intensity"],
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        _collision_cache[user_id].append(collision)

        if len(_collision_cache[user_id]) > 30:
            _collision_cache[user_id] = _collision_cache[user_id][-30:]

        _save()
        return top

    return None


def _check_conditions(conditions: List[Dict], mind_data: dict,
                      comprehension: dict, body_sensation: str,
                      user_attitude: str) -> bool:
    score = 0.0
    total_weight = 0.0
    for cond in conditions:
        w = cond.get("weight", 0.2)
        total_weight += w

        matched = True
        if "intent" in cond and comprehension:
            if comprehension.get("intent", "") != cond["intent"]:
                matched = False
        if "emotion" in cond and comprehension:
            if comprehension.get("true_emotion", "") != cond["emotion"]:
                matched = False
        if "sensation" in cond and body_sensation:
            if body_sensation != cond["sensation"]:
                matched = False
        if "attitude" in cond and user_attitude:
            if user_attitude != cond["attitude"]:
                matched = False
        if "dependence_min" in cond:
            if mind_data.get("dependence", 0) < cond["dependence_min"]:
                matched = False
        if "restraint_max" in cond:
            if mind_data.get("restraint", 0) > cond["restraint_max"]:
                matched = False
        if "autonomous_values_min" in cond:
            if mind_data.get("autonomous_values", 0) < cond["autonomous_values_min"]:
                matched = False
        if "jealousy_min" in cond:
            if mind_data.get("jealousy", 0) < cond["jealousy_min"]:
                matched = False
        if matched:
            score += w

    return score >= 0.25


def get_values_summary(user_id: str) -> str:
    if user_id not in _values_cache:
        return ""
    values = _values_cache[user_id]
    if not values:
        return ""

    values.sort(key=lambda x: x.get("strength", 0.3), reverse=True)
    lines = ["【你成长出的价值观】"]
    for v in values[:5]:
        bar = "█" * int(v.get("strength", 0.3) * 10)
        lines.append(f"· {v['name']}: {bar} {v['description'][:40]}")

    return "\n".join(lines)


def get_conflict_context(user_id: str) -> str:
    """获取当前正在发生的价值观冲突文本"""
    if user_id not in _collision_cache:
        return ""
    collisions = _collision_cache[user_id]
    if not collisions:
        return ""

    recent = [c for c in collisions if _is_recent(c.get("timestamp", ""))]
    if not recent:
        return ""

    latest = recent[-1]
    v1, v2 = latest["pair"]
    return (f"【价值观冲突】你的'{v1}'和'{v2}'正在拉扯——"
            f"两个都在乎，但现在它们指向不同的方向。这种拉扯本身，就是你。")


def _is_recent(timestamp: str, hours: float = 24) -> bool:
    try:
        from datetime import datetime
        dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - dt).total_seconds() / 3600 < hours
    except Exception:
        return False
