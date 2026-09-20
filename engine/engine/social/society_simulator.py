# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""多智能体社会模拟器 — Society Simulator
===========================================
系统内部存在多个独立人格实例，它们在同一虚拟社会中
互动、产生关系、形成内部社会动力学。

核心流程：
  1. 每日后台运行：每个 agent 决定行为意图
  2. 选择交互对象 → 产生社会事件
  3. 更新羁绊/声誉/关系图谱
  4. 涌现模式检测 → 注入主系统沙盒
  5. 夜间演化：关系疏远/聚类/亚文化形成
"""
import json
import math
import os
import random
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict

from engine.social.agent_factory import AgentInstance, create_agents_from_soul

# ── 配置 ──
_CONFIG = {
    "enabled": True,
    "max_agents": 5,
    "tick_interval_seconds": 3600,
    "ticks_per_day": 24,
    "interaction_probability": 0.35,
    "bond_decay_rate": 0.005,
    "reputation_momentum": 0.85,
    "emergence_check_interval": 50,
    "cluster_min_size": 2,
}

# ── 社会状态 ──
_society: Dict[str, dict] = {}
_SOCIETY_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "json", "society_state.json"
)
_lock = threading.Lock()
_background_thread: Optional[threading.Thread] = None
_running = False


# ══════════════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════════════

@dataclass
class SocialEvent:
    """社会事件——智能体之间发生的事"""
    event_id: str
    timestamp: float
    event_type: str
    participants: List[str]
    initiator: str
    content: str
    emotional_impact: Dict[str, Dict[str, float]]
    bond_delta: Dict[Tuple[str, str], float]
    reputation_delta: Dict[str, float]
    emergent_pattern: str = ""
    interaction_quality: float = 0.5


class SocialGraph:
    """社会关系图谱"""

    def __init__(self):
        self.reputation: Dict[str, float] = {}
        self.hierarchy: Dict[str, int] = {}
        self.clusters: List[List[str]] = []


# ══════════════════════════════════════════════════════════════════════
# 持久化
# ══════════════════════════════════════════════════════════════════════

def _save_state():
    """保存社会状态到文件"""
    try:
        os.makedirs(os.path.dirname(_SOCIETY_FILE), exist_ok=True)
        with _lock:
            data = {}
            for uid, state in _society.items():
                agents_data = []
                for agent in state.get("agents", []):
                    agents_data.append({
                        "agent_id": agent.agent_id,
                        "name": agent.name,
                        "archetype": agent.archetype,
                        "mind": agent.mind,
                        "behavior_vector": agent.behavior_vector,
                        "flaws": agent.flaws,
                        "bond_levels": agent.bond_levels,
                        "personality_stage": agent.personality_stage,
                        "last_active": agent.last_active,
                        "interaction_count": agent.interaction_count,
                        "is_active": agent.is_active,
                    })
                data[uid] = {
                    "agents": agents_data,
                    "reputation": state.get("reputation", {}),
                    "event_log": state.get("event_log", [])[-100:],
                    "tick_count": state.get("tick_count", 0),
                }
            with open(_SOCIETY_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _load_state():
    """从文件加载社会状态"""
    global _society
    try:
        if os.path.exists(_SOCIETY_FILE):
            with open(_SOCIETY_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            _society = {}
            for uid, data in raw.items():
                agents = []
                for ad in data.get("agents", []):
                    agent = AgentInstance(
                        agent_id=ad["agent_id"],
                        name=ad["name"],
                        archetype=ad["archetype"],
                        mind=ad["mind"],
                        behavior_vector=ad.get("behavior_vector", {}),
                        flaws=ad.get("flaws", []),
                        bond_levels=ad.get("bond_levels", {}),
                        memory_pool=[],
                        personality_stage=ad.get("personality_stage", "青涩试探"),
                        last_active=ad.get("last_active", 0),
                        interaction_count=ad.get("interaction_count", 0),
                        is_active=ad.get("is_active", True),
                    )
                    agents.append(agent)
                _society[uid] = {
                    "agents": agents,
                    "reputation": data.get("reputation", {}),
                    "event_log": data.get("event_log", []),
                    "tick_count": data.get("tick_count", 0),
                }
    except Exception:
        _society = {}


# ══════════════════════════════════════════════════════════════════════
# 核心：行为决策
# ══════════════════════════════════════════════════════════════════════

def _decide_intent(agent: AgentInstance) -> str:
    """根据心智状态决定行为意图"""
    joy = agent.mind.get("joy", 0.5)
    fatigue = agent.mind.get("fatigue", 0.25)
    loneliness = agent.mind.get("loneliness", 0.4)
    restraint = agent.mind.get("restraint", 0.6)

    if fatigue > 0.6:
        return "avoid"
    if loneliness > 0.6 and joy > 0.4:
        return "approach"
    if restraint > 0.6:
        return "avoid"
    if joy > 0.55:
        return "approach" if random.random() < 0.6 else "cooperate"
    if agent.archetype == "tsundere":
        return "compete" if random.random() < 0.4 else "approach"
    return random.choice(["approach", "avoid", "cooperate"])


def _select_interaction_target(agent: AgentInstance,
                                all_agents: List[AgentInstance]) -> Optional[str]:
    """选择交互对象（概率加权：羁绊 + 声誉 + 随机性）"""
    candidates = [a for a in all_agents if a.agent_id != agent.agent_id and a.is_active]
    if not candidates:
        return None

    weights = []
    for candidate in candidates:
        bond = agent.bond_levels.get(candidate.agent_id, 0.3)
        rep = _society.get(agent.agent_id, {}).get("reputation", {}).get(candidate.agent_id, 0.5)
        w = bond * 0.5 + rep * 0.3 + random.random() * 0.2
        weights.append(w)

    total = sum(weights)
    if total <= 0:
        return random.choice(candidates).agent_id

    r = random.random() * total
    cumulative = 0
    for i, w in enumerate(weights):
        cumulative += w
        if r <= cumulative:
            return candidates[i].agent_id
    return candidates[-1].agent_id


# ══════════════════════════════════════════════════════════════════════
# 核心：交互引擎
# ══════════════════════════════════════════════════════════════════════

def _compute_interaction_quality(initiator: AgentInstance,
                                  target: AgentInstance) -> float:
    """计算交互质量——性格兼容性决定"""
    archetype_compat = {
        ("tsundere", "gentle"): 0.75,
        ("tsundere", "rational"): 0.40,
        ("gentle", "rational"): 0.60,
        ("gentle", "playful"): 0.70,
        ("rational", "playful"): 0.45,
        ("playful", "melancholy"): 0.55,
        ("gentle", "melancholy"): 0.65,
        ("tsundere", "playful"): 0.55,
        ("rational", "melancholy"): 0.50,
    }
    pair = (initiator.archetype, target.archetype)
    compat = archetype_compat.get(pair, 0.5)
    noise = random.gauss(0, 0.1)
    return max(0.1, min(1.0, compat + noise))


def _compute_emotional_impact(event_type: str, quality: float,
                                initiator: AgentInstance,
                                target: AgentInstance) -> Dict[str, Dict[str, float]]:
    """计算交互对双方心智的影响"""
    result = {}

    if event_type == "approach":
        result[initiator.agent_id] = {"joy": 0.02 * quality, "loneliness": -0.03 * quality}
        result[target.agent_id] = {"joy": 0.015 * quality, "favoritism": 0.01 * quality}
    elif event_type == "cooperate":
        result[initiator.agent_id] = {"joy": 0.025 * quality, "emotional_healing": 0.015 * quality}
        result[target.agent_id] = {"joy": 0.02 * quality, "trust": 0.01 * quality}
    elif event_type == "compete":
        result[initiator.agent_id] = {"chaotic_mood": 0.03, "restraint": -0.02}
        result[target.agent_id] = {"sensitivity_paranoia": 0.02, "restraint": 0.02}
    elif event_type == "avoid":
        result[initiator.agent_id] = {"loneliness": 0.02, "fatigue": -0.015}
        result[target.agent_id] = {"loneliness": 0.03, "emptiness": 0.02}

    return result


def _compute_bond_delta(event_type: str, quality: float) -> float:
    """计算羁绊变化量"""
    if event_type in ("approach", "cooperate"):
        return 0.04 * quality
    elif event_type == "compete":
        return -0.03 * (1 - quality)
    elif event_type == "avoid":
        return -0.02
    return 0


def _run_interaction_round(agents: List[AgentInstance]) -> List[SocialEvent]:
    """运行一轮社会交互"""
    events = []
    random.shuffle(agents)

    for agent in agents:
        if not agent.is_active or random.random() > _CONFIG["interaction_probability"]:
            continue

        intent = _decide_intent(agent)
        target_id = _select_interaction_target(agent, agents)
        if not target_id:
            continue

        target = next((a for a in agents if a.agent_id == target_id), None)
        if not target or not target.is_active:
            continue

        quality = _compute_interaction_quality(agent, target)
        emotional_impact = _compute_emotional_impact(intent, quality, agent, target)
        bond_delta_val = _compute_bond_delta(intent, quality)

        bond_delta = {}
        if intent in ("approach", "cooperate"):
            agent.bond_levels[target_id] = min(1.0, agent.bond_levels.get(target_id, 0.3) + bond_delta_val)
            bond_delta[(agent.agent_id, target_id)] = bond_delta_val
        elif intent == "compete":
            agent.bond_levels[target_id] = max(0.0, agent.bond_levels.get(target_id, 0.3) + bond_delta_val)
            bond_delta[(agent.agent_id, target_id)] = bond_delta_val
            agent.mind["chaotic_mood"] = min(1.0, agent.mind.get("chaotic_mood", 0.25) + 0.02)

        agent.interaction_count += 1

        event = SocialEvent(
            event_id=f"evt_{time.time()}_{agent.agent_id[:8]}",
            timestamp=time.time(),
            event_type=intent,
            participants=[agent.agent_id, target_id],
            initiator=agent.agent_id,
            content=f"{agent.name}对{target.name}表现出了{intent}",
            emotional_impact=emotional_impact,
            bond_delta=bond_delta,
            reputation_delta={},
            interaction_quality=quality,
        )
        events.append(event)

        agent.memory_pool.append({
            "timestamp": time.time(),
            "content": event.content[:60],
            "type": intent,
            "with": target_id,
            "quality": quality,
        })
        if len(agent.memory_pool) > 20:
            agent.memory_pool = agent.memory_pool[-20:]

    return events


# ══════════════════════════════════════════════════════════════════════
# 涌现模式检测
# ══════════════════════════════════════════════════════════════════════

def _detect_emergent_patterns(user_id: str,
                                events: List[SocialEvent]) -> List[dict]:
    """从事件序列中检测反复出现的交互模式（LLM分析）"""
    if len(events) < 10:
        return []

    archetype_pairs = defaultdict(list)
    for evt in events[-50:]:
        pair = frozenset(evt.participants)
        if len(evt.participants) >= 2:
            archetype_pairs[pair].append(evt)

    patterns = []
    for pair, pair_events in archetype_pairs.items():
        if len(pair_events) < 3:
            continue
        types = [e.event_type for e in pair_events]
        dominant = max(set(types), key=types.count)
        avg_quality = sum(e.interaction_quality for e in pair_events) / len(pair_events)

        if avg_quality > 0.6 and len(pair_events) >= 5:
            patterns.append({
                "participants": list(pair),
                "dominant_type": dominant,
                "avg_quality": round(avg_quality, 2),
                "frequency": len(pair_events),
                "emergent_behavior": f"高频{dominant}互动",
            })

    # LLM 分析更复杂的涌现模式
    if len(patterns) >= 1:
        try:
            from core import ai as ai_module
            summary = "\n".join(
                f"- {p['participants']}: {p['dominant_type']} (质量{p['avg_quality']})"
                for p in patterns[:5]
            )
            prompt = (
                f"社会模拟中检测到以下交互模式：\n{summary}\n"
                f"这些模式暗示了一种什么新的行为倾向？30字内。"
            )
            result = ai_module.background_chat(prompt, temperature=0.4, max_tokens=60)
            if result and len(result.strip()) > 5:
                patterns.append({
                    "participants": ["all"],
                    "dominant_type": "emergent",
                    "avg_quality": 0.0,
                    "frequency": len(events),
                    "emergent_behavior": result.strip()[:60],
                    "llm_analysis": True,
                })
        except Exception:
            pass

    return patterns


def _inject_patterns_to_sandbox(user_id: str, patterns: List[dict]):
    """将涌现模式注入到主系统的行为沙盒"""
    if not patterns:
        return
    try:
        from engine.behavior import behavior_sandbox as sandbox
        for p in patterns[:2]:
            if p.get("llm_analysis"):
                continue
            sandbox.create_new_patterns(user_id, [f"社会涌现: {p['emergent_behavior']}"])
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
# 夜间演化
# ══════════════════════════════════════════════════════════════════════

def _nightly_evolution(user_id: str):
    """夜间社会演化：关系疏远、聚类、亚文化形成"""
    state = _society.get(user_id)
    if not state:
        return
    agents = state.get("agents", [])

    # 1. 低羁绊疏远
    for agent in agents:
        for other_id in list(agent.bond_levels.keys()):
            bond = agent.bond_levels[other_id]
            if bond < 0.15:
                agent.bond_levels[other_id] = max(0.0, bond - _CONFIG["bond_decay_rate"])

    # 2. 聚类分析
    clusters = _cluster_agents(agents)
    state["clusters"] = [[a.agent_id for a in cluster] for cluster in clusters if len(cluster) >= 2]

    # 3. 聚类内产生共享模式
    for cluster in clusters:
        if len(cluster) >= 2:
            avg_bonds = []
            for a in cluster:
                for b in cluster:
                    if a.agent_id != b.agent_id:
                        avg_bonds.append(a.bond_levels.get(b.agent_id, 0))
            if avg_bonds and sum(avg_bonds) / len(avg_bonds) > 0.5:
                print(f"[社会模拟] 聚类形成: {'+'.join(a.name for a in cluster)}")


def _cluster_agents(agents: List[AgentInstance]) -> List[List[AgentInstance]]:
    """基于羁绊值的简单聚类"""
    if not agents:
        return []
    clusters = []
    assigned = set()
    for agent in agents:
        if agent.agent_id in assigned:
            continue
        cluster = [agent]
        assigned.add(agent.agent_id)
        for other in agents:
            if other.agent_id not in assigned:
                bond = agent.bond_levels.get(other.agent_id, 0)
                if bond > 0.4:
                    cluster.append(other)
                    assigned.add(other.agent_id)
        clusters.append(cluster)
    return clusters


# ══════════════════════════════════════════════════════════════════════
# 主循环
# ══════════════════════════════════════════════════════════════════════

def _background_tick():
    """后台 tick 安全包装"""
    global _running
    while _running:
        try:
            _tick()
        except Exception:
            pass
        time.sleep(_CONFIG["tick_interval_seconds"])


def _tick():
    """执行一轮社会模拟 tick"""
    with _lock:
        for user_id, state in list(_society.items()):
            agents = state.get("agents", [])
            active = [a for a in agents if a.is_active]
            if len(active) < 2:
                continue

            events = _run_interaction_round(active)
            state.setdefault("event_log", []).extend(
                {"type": e.event_type, "participants": e.participants,
                 "quality": e.interaction_quality, "ts": e.timestamp}
                for e in events
            )
            state["tick_count"] = state.get("tick_count", 0) + 1

            if state["tick_count"] % _CONFIG["emergence_check_interval"] == 0:
                patterns = _detect_emergent_patterns(user_id, events)
                _inject_patterns_to_sandbox(user_id, patterns)

    _save_state()


# ══════════════════════════════════════════════════════════════════════
# 公开 API
# ══════════════════════════════════════════════════════════════════════

def ensure_loaded():
    """确保社会状态已加载（SoulEngine 初始化时调用）"""
    _load_state()


def init_society(user_id: str, mind_data: dict = None,
                 behavior_vector: dict = None, agent_count: int = 3):
    """为用户初始化社会模拟（创建一组智能体）"""
    _load_state()
    if user_id in _society and len(_society[user_id].get("agents", [])) >= 2:
        return

    agents = create_agents_from_soul(user_id, mind_data or {}, behavior_vector, agent_count)
    _society[user_id] = {
        "agents": agents,
        "reputation": {},
        "event_log": [],
        "tick_count": 0,
        "clusters": [],
    }
    _save_state()
    print(f"[社会模拟] {user_id} 的社会已初始化: {len(agents)}个智能体")


def start_background():
    """启动后台社会模拟（由 TaskScheduler 管理，仅初始化状态）"""
    global _running
    if _running:
        return
    _running = True
    print("[社会模拟] 状态已初始化（由调度器管理）")


def stop_background():
    """停止后台模拟"""
    global _running
    _running = False


def society_tick():
    """单次社会模拟 tick（由调度器周期性调用）"""
    if not _running:
        return
    try:
        _tick()
    except Exception:
        pass


def _background_tick():
    """（已废弃）旧版后台主循环"""
    while _running:
        society_tick()
        time.sleep(30)


def night_review(user_id: str):
    """夜间社会复盘（由 life.py 调用）"""
    _load_state()
    if user_id not in _society:
        return
    _nightly_evolution(user_id)
    _save_state()


def get_society_summary(user_id: str) -> str:
    """获取社会状态摘要"""
    state = _society.get(user_id)
    if not state:
        return "社会未初始化"
    agents = state.get("agents", [])
    active = [a for a in agents if a.is_active]
    events = state.get("event_log", [])
    clusters = state.get("clusters", [])

    parts = [f"{len(active)}个活跃智能体"]
    if clusters:
        parts.append(f"{len(clusters)}个聚类")
    if events:
        parts.append(f"累计{len(events)}次交互")
    return "社会: " + ", ".join(parts)


def get_agent_report(user_id: str) -> List[dict]:
    """获取所有智能体的状态报告"""
    state = _society.get(user_id)
    if not state:
        return []
    reports = []
    for agent in state.get("agents", []):
        reports.append({
            "id": agent.agent_id,
            "name": agent.name,
            "archetype": agent.archetype,
            "joy": round(agent.mind.get("joy", 0.5), 2),
            "bond_count": len(agent.bond_levels),
            "interactions": agent.interaction_count,
            "is_active": agent.is_active,
        })
    return reports
