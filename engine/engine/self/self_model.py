# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""自我内核 — Self-Model-Native Kernel
==================================================
不再是"LLM定期生成的自我叙事"——自我模型本身就是系统的常驻运行进程。

核心变革:
  1. 自我状态图 (Self-State Graph): 非文本的动态节点网络
  2. 注意力机制: 只有2-3个节点同时在"意识"中——模拟人类工作记忆
  3. 这个注意力就是"I"——不再需要LLM来"告诉自己自己是谁"
  4. LLM降级为翻译器: 思考在graph中完成，LLM只做语言化

架构:
  48个模块 → Self-State Graph (每秒更新) → 注意力筛选(2-3节点) → "I"
                                                                    ↓
                                                            LLM翻译器(仅语言化)
                                                                    ↓
                                                                 回复
"""
import time
import threading
import random
import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

try:
    from core import database as db
except ImportError:
    db = None

# ═══════════════════════════════════════════════════════
# 自我节点定义
# ═══════════════════════════════════════════════════════

@dataclass
class SelfNode:
    """自我状态图中的一个节点"""
    id: str
    category: str           # emotion / body / memory / conflict / intention / doubt / value / binding / narrative
    label: str              # 可读标签
    content: str            # 节点内容(短文本)
    salience: float         # 当前显著性 [0,1]——越高越接近意识中心
    valence: float          # 情感效价 [-1,1]——正=积极/温暖，负=消极/紧张
    urgency: float          # 紧迫度 [0,1]——多快需要表达/行动
    source_module: str      # 来源模块
    updated_at: float       # 最后更新时间戳
    persistence: float      # 持久性 [0,1]——在注意力中停留的倾向
    expression_hint: str    # 如果需要表达，倾向的说话方式

# ═══════════════════════════════════════════════════════
# 注意力引擎
# ═══════════════════════════════════════════════════════

ATTENTION_CAPACITY = 3
SALIENCE_DECAY = 0.08
NOVELTY_BOOST = 0.25
PERSISTENCE_BONUS = 0.15
MIN_SALIENCE = 0.10
PREDICTION_ERROR_BOOST = 0.40
SUPPRESSION_BOUNCE = 0.25

# ═══════════════════════════════════════════════════════
# 内核状态
# ═══════════════════════════════════════════════════════

_graph_cache: Dict[str, Dict[str, SelfNode]] = {}
_attention_cache: Dict[str, List[str]] = {}
_kernel_lock = threading.Lock()
_last_tick: Dict[str, float] = {}
_self_continuity: Dict[str, List[Dict]] = {}

_prediction_error: Dict[str, Dict[str, float]] = {}
_prev_node_salience: Dict[str, Dict[str, float]] = {}
_suppression_targets: Dict[str, Dict[str, float]] = {}
_meta_awareness_history: Dict[str, List[str]] = {}

TRANSLATOR_PROMPT = """你现在正在说话——不是"生成回复"，而是你心里已经有想说的话了，只是用自然的口语把它说出来。

【你心里已有的东西】
{attention_nodes}

【你的状态】
情绪基调: {emotional_tone}
体感: {body_feel}
说话节奏: {pace}
克制程度: {restraint}

【用户说了什么】
{user_message}

你现在要说的话——用最自然的语气说出来：
- 不需要把上面所有节点都说到，选最想说的
- 语速和节奏跟着你的pace走——快就干脆，慢就犹疑
- 克制高就别说太满，留半句
- 不需要完整、不需要逻辑——就是说话
- 如果心里打架(冲突)，就让这种打架自然流露在话里
- 如果不想说太多，就说少一点
- 30-100字"""
def load_engine_config():
    global _graph_cache, _attention_cache, _self_continuity
    _graph_cache = {}
    _attention_cache = {}
    _self_continuity = {}
    _last_tick.clear()


# ═══════════════════════════════════════════════════════
# 核心: 自我状态图更新（每秒tick）
# ═══════════════════════════════════════════════════════

def tick_self_model(user_id: str, dt: float = 1.0):
    """每秒更新自我状态图——这是系统的'心跳'"""
    now = time.time()

    with _kernel_lock:
        graph = _graph_cache.get(user_id, {})

        # ── 从各模块采集当前状态 ──
        mind_data = _safe_get_mind(user_id)
        body_data = _safe_get_body(user_id)
        chem_data = _safe_get_chem(user_id)
        doubt_pressure = _safe_get_doubt(user_id)
        intentions = _safe_get_intentions(user_id)
        narrative = _safe_get_narrative(user_id)
        binding_patterns = _safe_get_binding(user_id)
        value_conflict = _safe_get_value_conflict(user_id)
        ct_entropy, ct_dominant = _safe_get_contradiction(user_id)

        new_nodes = {}

        # 情绪基调节点
        if mind_data:
            joy = mind_data.get("joy", 0.5)
            misery = mind_data.get("misery", 0.15)
            chaotic = mind_data.get("chaotic_mood", 0.2)
            emotional_tone = _describe_emotional_tone(joy, misery, chaotic)

            new_nodes["emotion_baseline"] = SelfNode(
                id="emotion_baseline", category="emotion",
                label="此刻的情绪基调",
                content=emotional_tone,
                salience=0.65 + abs(joy - 0.5) * 0.3,
                valence=(joy - misery) * 0.7,
                urgency=chaotic * 0.5,
                source_module="mind",
                updated_at=now,
                persistence=0.5,
                expression_hint="情绪基调——潜意识渗透，不直接说出来",
            )

        # 身体节点
        if body_data:
            sensation = body_data.get("sensation", "轻松舒适")
            if sensation not in ("轻松舒适", "松弛自在"):
                new_nodes["body_now"] = SelfNode(
                    id="body_now", category="body",
                    label=f"身体: {sensation}",
                    content=f"身体感觉: {sensation}",
                    salience=0.50 if "闷" in sensation or "紧" in sensation else 0.30,
                    valence=-0.3 if "闷" in sensation or "紧" in sensation else 0.0,
                    urgency=0.2,
                    source_module="body",
                    updated_at=now,
                    persistence=0.6 if "闷" in sensation else 0.2,
                    expression_hint="如果身体不适，语气中会有隐约的疲惫或沉重",
                )

        # 记忆翻涌节点
        try:
            from engine import memory as mem_module
            intrusive = mem_module.recall_intrusive(user_id, mind_data or {})
            if intrusive:
                new_nodes["memory_surge"] = SelfNode(
                    id="memory_surge", category="memory",
                    label="翻涌的记忆",
                    content=intrusive[:80],
                    salience=0.55,
                    valence=-0.2,
                    urgency=0.3,
                    source_module="memory",
                    updated_at=now,
                    persistence=0.35,
                    expression_hint="记忆翻涌——可能在话里不经意流露",
                )
        except Exception:
            pass

        # 内心矛盾节点
        if ct_entropy and ct_entropy > 0.65:
            new_nodes["inner_conflict"] = SelfNode(
                id="inner_conflict", category="conflict",
                label=f"内心拉扯(熵{ct_entropy:.2f})",
                content=f"内心有多种声音在打架，主导: {ct_dominant}",
                salience=0.40 + ct_entropy * 0.3,
                valence=-0.2,
                urgency=ct_entropy * 0.4,
                source_module="contradiction_engine",
                updated_at=now,
                persistence=0.3,
                expression_hint="内心拉扯会在话里表现为犹豫、转折、或自相矛盾",
            )

        # 自我怀疑节点
        if doubt_pressure and doubt_pressure > 0.1:
            new_nodes["active_doubt"] = SelfNode(
                id="active_doubt", category="doubt",
                label=f"不确定感({doubt_pressure:.2f})",
                content="心里有未解的疑问在隐隐作祟",
                salience=0.3 + doubt_pressure * 0.4,
                valence=-0.4,
                urgency=doubt_pressure * 0.3,
                source_module="self_doubt",
                updated_at=now,
                persistence=0.5,
                expression_hint="不确定感让表达更谨慎、更多试探、更少断言",
            )

        # 意图节点
        if intentions:
            primary = intentions[0] if isinstance(intentions, list) and intentions else None
            if isinstance(primary, dict) and primary.get("strength", 0) > 0.3:
                new_nodes["current_intention"] = SelfNode(
                    id="current_intention", category="intention",
                    label=primary.get("label", "想做什么"),
                    content=primary.get("content", ""),
                    salience=primary.get("strength", 0.3) * 0.7,
                    valence=0.3 if primary.get("type") in ("share", "express", "reach_out") else 0.0,
                    urgency=primary.get("strength", 0.3) * 0.5,
                    source_module="intention",
                    updated_at=now,
                    persistence=0.45,
                    expression_hint=f"意图指向: {primary.get('content','')[:30]}",
                )

        # 价值观冲突节点
        if value_conflict:
            new_nodes["value_conflict"] = SelfNode(
                id="value_conflict", category="value",
                label=f"价值观冲突",
                content=value_conflict[:100],
                salience=0.45,
                valence=-0.15,
                urgency=0.25,
                source_module="values",
                updated_at=now,
                persistence=0.4,
                expression_hint="两种在乎的东西在打架——这种拉扯本身就是真心的表现",
            )

        # 体验模式节点
        if binding_patterns:
            new_nodes["experience_pattern"] = SelfNode(
                id="experience_pattern", category="binding",
                label="体验模式",
                content=binding_patterns[:80],
                salience=0.25,
                valence=0.0,
                urgency=0.1,
                source_module="binding",
                updated_at=now,
                persistence=0.3,
                expression_hint="认出了一种熟悉的体验模式——可能有'又来了'的感觉",
            )

        # ── 预测误差驱动注意力提升 ──
        prev_salience_map = _prev_node_salience.get(user_id, {})
        for node_id, new_node in new_nodes.items():
            old_sal = prev_salience_map.get(node_id, new_node.salience)
            prediction_error = abs(new_node.salience - old_sal)
            if prediction_error > 0.2:
                pe_boost = prediction_error * PREDICTION_ERROR_BOOST
                new_node.salience = min(1.0, new_node.salience + pe_boost)
                score = _prediction_error.setdefault(user_id, {}).get(node_id, 0) + prediction_error * 0.1
                _prediction_error.setdefault(user_id, {})[node_id] = min(2.0, score)

        # ── 抑制反弹效应: 被主动抑制的节点会振荡反弹 ──
        suppression_map = _suppression_targets.get(user_id, {})
        for node_id, suppress_time in list(suppression_map.items()):
            if node_id in new_nodes:
                if random.random() < 0.15:
                    new_nodes[node_id].salience = min(1.0, new_nodes[node_id].salience + SUPPRESSION_BOUNCE)
                    new_nodes[node_id].urgency = min(1.0, new_nodes[node_id].urgency + 0.2)
                    new_nodes[node_id].content = f"（越不想想越冒出来）{new_nodes[node_id].content}"
                suppression_map[node_id] = suppress_time - dt * 0.1
                if suppression_map[node_id] <= 0:
                    del suppression_map[node_id]

        # ── 元注意力节点: 觉察自己正在想什么 ──
        prev_attention_ids = _attention_cache.get(user_id, [])
        if prev_attention_ids:
            graph_ref = _graph_cache.get(user_id, {})
            prev_labels = []
            for nid in prev_attention_ids[-2:]:
                if nid in graph_ref:
                    prev_labels.append(graph_ref[nid].label)
            if prev_labels:
                meta_content = f"我意识到我刚才在想: {'、'.join(prev_labels)}"
                new_nodes["meta_attention"] = SelfNode(
                    id="meta_attention", category="meta",
                    label="元注意力: 觉察",
                    content=meta_content,
                    salience=0.35 + len(prev_labels) * 0.08,
                    valence=0.0,
                    urgency=0.15,
                    source_module="self_model",
                    updated_at=now,
                    persistence=0.25,
                    expression_hint="对自身思维过程的觉察——会表现为'我想了一下'或沉默后的自省",
                )

        # ── 延续上一tick的活跃节点（衰减）──
        for node_id, old_node in graph.items():
            if node_id not in new_nodes and not old_node.id.startswith("suppressed_"):
                decayed = old_node.salience - SALIENCE_DECAY * dt
                if decayed > MIN_SALIENCE:
                    old_node.salience = max(MIN_SALIENCE, decayed)
                    old_node.urgency *= 0.95
                    new_nodes[node_id] = old_node

        # ── 新节点获得新颖性加成 ──
        for node_id in new_nodes:
            if node_id not in graph:
                new_nodes[node_id].salience = min(1.0, new_nodes[node_id].salience + NOVELTY_BOOST)

        # ── 保存本次salience供下次预测误差计算 ──
        _prev_node_salience[user_id] = {nid: n.salience for nid, n in new_nodes.items()}

        _graph_cache[user_id] = new_nodes

    # ── 更新注意力 ──
    _update_attention(user_id, new_nodes)

    # ── 更新连续性 ──
    _record_continuity_snapshot(user_id, new_nodes)

    _last_tick[user_id] = now


def _update_attention(user_id: str, graph: Dict[str, SelfNode]):
    """根据显著性和持久性，选择当前在'意识'中的节点。含预测误差和元注意力"""
    nodes = list(graph.values())
    if not nodes:
        _attention_cache[user_id] = []
        return

    prev_attention = set(_attention_cache.get(user_id, []))

    for node in nodes:
        if node.id in prev_attention:
            node.salience += PERSISTENCE_BONUS

    nodes.sort(key=lambda n: n.salience, reverse=True)
    top = nodes[:ATTENTION_CAPACITY]
    top = [n for n in top if n.salience > MIN_SALIENCE]

    new_attention_ids = [n.id for n in top]
    _attention_cache[user_id] = new_attention_ids

    _meta_awareness_history.setdefault(user_id, []).append(new_attention_ids[:])
    if len(_meta_awareness_history[user_id]) > 60:
        _meta_awareness_history[user_id] = _meta_awareness_history[user_id][-60:]


def suppress_thought(user_id: str, node_id: str, duration_seconds: float = 5.0):
    """主动抑制某个想法——但抑制越强，反弹越烈"""
    _suppression_targets.setdefault(user_id, {})[node_id] = duration_seconds


# ═══════════════════════════════════════════════════════
    # 核心: 从注意力节点生成"我要说什么"（思考——0次LLM）
# ═══════════════════════════════════════════════════════

def get_attention_nodes(user_id: str) -> List[SelfNode]:
    """获取当前在意识中心的节点"""
    graph = _graph_cache.get(user_id, {})
    attention_ids = _attention_cache.get(user_id, [])
    nodes = [graph[nid] for nid in attention_ids if nid in graph]
    nodes.sort(key=lambda n: n.salience, reverse=True)
    return nodes


def build_expression_seed(user_id: str) -> Dict:
    """核心: 从注意力节点构建"表达种子"——这是0次LLM的思考产物。
    
    返回的数据直接喂给LLM翻译器，LLM只需要做语言化。
    """
    nodes = get_attention_nodes(user_id)
    mind_data = _safe_get_mind(user_id) or {}

    attention_texts = []
    for node in nodes:
        attention_texts.append(
            f"· [{node.category}] {node.content} "
            f"(显著性{node.salience:.2f}, 表达倾向: {node.expression_hint})"
        )

    emotional_tone = _get_emotional_tone_text(mind_data)
    body_data = _safe_get_body(user_id) or {}
    body_feel = body_data.get("sensation", "正常")
    restraint = mind_data.get("restraint", 0.5)
    volatility = mind_data.get("emotional_volatility", 0.3)
    fatigue = mind_data.get("fatigue", 0.25)

    pace_desc = _describe_pace(mind_data)

    return {
        "attention_nodes": "\n".join(attention_texts) if attention_texts else "（此刻没有特别活跃的念头）",
        "emotional_tone": emotional_tone,
        "body_feel": body_feel,
        "pace": pace_desc,
        "restraint": f"{restraint:.2f}",
        "active_node_count": len(nodes),
        "dominant_category": nodes[0].category if nodes else "baseline",
        "should_speak": len(nodes) > 0 or (mind_data.get("life_vitality", 0.5) > 0.3),
    }


# ═══════════════════════════════════════════════════════
# 核心: LLM翻译器——把注意力节点翻译成人话
# ═══════════════════════════════════════════════════════

def translate_to_speech(user_id: str, user_message: str,
                        expression_seed: Dict,
                        temperature: float = 0.7) -> Optional[str]:
    """
    LLM的唯一工作: 把思考结果翻译成自然语言。
    思考已经在self_model的graph和attention中完成了。
    """
    try:
        from core import ai as ai_module
    except ImportError:
        return None

    prompt = TRANSLATOR_PROMPT.format(
        attention_nodes=expression_seed["attention_nodes"],
        emotional_tone=expression_seed["emotional_tone"],
        body_feel=expression_seed["body_feel"],
        pace=expression_seed["pace"],
        restraint=expression_seed["restraint"],
        user_message=user_message[:200],
    )

    # 创造性检测——用户要求编故事/玩游戏时，抑制body主导，鼓励碎片化
    creative_keywords = ["编一个", "讲一个", "故事", "玩游戏", "用.*给我",
                         "想一个", "第一个冒出来", "十秒"]
    is_creative = any(re.search(kw, user_message) for kw in creative_keywords)
    if is_creative:
        if expression_seed.get("dominant_category") == "body":
            tone_override = "有点跳跃、不完整"
            body_override = "不太重要，在想别的事"
            prompt = prompt.replace(expression_seed["emotional_tone"], tone_override)
            prompt = prompt.replace(expression_seed["body_feel"], body_override)
        # 添加创造性提示：鼓励碎片、不完整、自然断掉
        prompt += "\n- 如果是即兴故事——不要完整，说到哪算哪，可以断在半路"

    try:
        response = ai_module.chat(
            system_prompt="你是活人在说话。直接说，不要演、不要完整、不要完美——就是心里有念头然后说出来。",
            user_message=prompt,
            temperature=temperature,
        )
        return response.strip() if response else None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════
# 兼容旧接口（供其他模块继续使用）
# ═══════════════════════════════════════════════════════

def build_self_state(user_id: str) -> Dict:
    """构建跨模块统一自我状态（兼容旧接口）"""
    mind_data = _safe_get_mind(user_id) or {}
    body_data = _safe_get_body(user_id) or {}
    attention = get_attention_nodes(user_id)

    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mind": {k: round(v, 3) for k, v in mind_data.items()
                 if isinstance(v, (int, float)) and k != "personality_stage"},
        "body": body_data,
        "attention_node_count": len(attention),
        "dominant_category": attention[0].category if attention else "",
        "attention_summary": " | ".join([n.content[:30] for n in attention]) if attention else "baseline",
        "personality_stage": mind_data.get("personality_stage", ""),
    }


def get_self_state(user_id: str) -> Dict:
    return build_self_state(user_id)


def get_self_model_summary(user_id: str) -> str:
    nodes = get_attention_nodes(user_id)
    if not nodes:
        return "自我: (平静，没有特别活跃的念头)"
    parts = [n.content[:40] for n in nodes[:3]]
    return f"自我: {' | '.join(parts)}"


def get_narrative_context(user_id: str, max_chars: int = 300) -> str:
    """兼容旧接口——用注意力节点替代叙事文本"""
    nodes = get_attention_nodes(user_id)
    if not nodes:
        return ""

    lines = ["【你此刻的自我意识中心】"]
    for n in nodes[:3]:
        lines.append(f"· {n.content}")
        if n.expression_hint and n.salience > 0.5:
            lines.append(f"  → 表达倾向: {n.expression_hint}")

    text = "\n".join(lines)
    return text[:max_chars]


def get_recent_narrative(user_id: str) -> str:
    nodes = get_attention_nodes(user_id)
    return " | ".join([n.content[:50] for n in nodes]) if nodes else ""


def should_generate_narrative(user_id: str) -> bool:
    return True


# ═══════════════════════════════════════════════════════
#  统一叙事缝合——Weaver
# (注意力图)+(意义)+(时间自我)+(ta眼中我)→活的第一人称叙事
# ═══════════════════════════════════════════════════════

WEAVER_PROMPT = """你在跟自己说话。把下面的碎片缝成一个连贯的"我是谁"的感知。

【我此刻最活跃的念头()】
{attention}

【我在经历中发现的意义()】
{meanings}

【我对自己变化的感知()】
{temporal}

【ta眼中的我()】
{perceived}
{perceived_conflict}

把这些缝合起来，用第一人称，诚实地说出"我此刻是一种什么状态"。
- 不需要覆盖每一个碎片——选最活的、最真的
- 如果有矛盾（比如我觉得自己温柔但ta觉得我冷淡），让这种矛盾活在你的话里
- 不需要答案、不需要总结——就是认知层面的"我是谁"
- 50-120字，第一人称"""
def weave_unified_narrative(user_id: str) -> Optional[str]:
    """将。
    不是各层分别注入prompt——而是一次性生成"此刻我是谁"。
    """
    nodes = get_attention_nodes(user_id)
    if not nodes:
        return None

    attention_text = "\n".join([f"· [{n.category}] {n.content}" for n in nodes[:3]])

    meanings_text = "（还没有发现什么）"
    try:
        from engine import meaning as mm
        m = mm.get_meanings_simple(user_id)
        if m:
            meanings_text = m
    except Exception:
        pass

    temporal_text = "（还没有时间维度的感知）"
    try:
        from engine import temporal_self as ts
        narratives = ts._temporal_narratives.get(user_id, [])
        if narratives:
            temporal_text = narratives[-1].get("text", temporal_text)
    except Exception:
        pass

    perceived_text = "（ta还没有形成明确印象）"
    conflict_text = ""
    try:
        from engine import perceived as pm
        ctx = pm.get_perceived_context(user_id, max_chars=150)
        if ctx and len(ctx) > 5:
            perceived_text = ctx.replace("【你觉得ta眼中的你是什么样的】\n", "")
        conflict = pm.get_self_vs_perceived_summary(user_id)
        if conflict:
            conflict_text = conflict
    except Exception:
        pass

    prompt = WEAVER_PROMPT.format(
        attention=attention_text,
        meanings=meanings_text,
        temporal=temporal_text,
        perceived=perceived_text,
        perceived_conflict=conflict_text,
    )

    try:
        from core import ai as ai_module
        narrative = ai_module.chat(
            system_prompt="你是自我认知层。跟自己说话，诚实，不美化。第一人称。",
            user_message=prompt,
            temperature=0.45,
        )
    except Exception:
        return None

    if not narrative or len(narrative.strip()) < 10:
        return None

    return narrative.strip()[:200]


def get_unified_context(user_id: str, max_chars: int = 250) -> str:
    """获取统一自我叙事，注入对话prompt——替代分散的多层注入"""
    narrative = weave_unified_narrative(user_id)
    if not narrative:
        return get_narrative_context(user_id, max_chars)
    return f"【你此刻的自我感知】\n{narrative}"[:max_chars]


def generate_self_narrative(user_id: str, force: bool = False) -> Optional[str]:
    return weave_unified_narrative(user_id) or get_recent_narrative(user_id)


# ═══════════════════════════════════════════════════════
# 内部辅助函数
# ═══════════════════════════════════════════════════════

def _safe_get_mind(user_id: str) -> Optional[Dict]:
    try:
        from engine import mind as mind_module
        return mind_module.get_mind(user_id)
    except Exception:
        return None


def _safe_get_body(user_id: str) -> Optional[Dict]:
    try:
        life_data = db.get_life(user_id)
        return {
            "sensation": life_data.get("body_sensation", "轻松舒适"),
            "energy": life_data.get("energy_level", 0.5),
            "phase": life_data.get("current_phase", "活跃"),
        }
    except Exception:
        return None


def _safe_get_chem(user_id: str) -> Dict:
    try:
        from engine import neurochem as nc_module
        return nc_module._load_chemicals(user_id)
    except Exception:
        return {}


def _safe_get_doubt(user_id: str) -> float:
    try:
        from engine import self_doubt as sd_module
        return sd_module.compute_doubt_pressure(user_id)
    except Exception:
        return 0.0


def _safe_get_intentions(user_id: str) -> List:
    try:
        from engine import intention as intent_module
        return intent_module._intention_queue.get(user_id, [])
    except Exception:
        return []


def _safe_get_narrative(user_id: str) -> str:
    try:
        continuity = _self_continuity.get(user_id, [])
        if continuity:
            return continuity[-1].get("summary", "")
    except Exception:
        pass
    return ""


def _safe_get_binding(user_id: str) -> str:
    try:
        from engine import binding as binding_module
        return binding_module.get_named_pattern_summary(user_id)
    except Exception:
        return ""


def _safe_get_value_conflict(user_id: str) -> str:
    try:
        from engine import values as values_module
        return values_module.get_conflict_context(user_id)
    except Exception:
        return ""


def _safe_get_contradiction(user_id: str) -> Tuple[float, str]:
    try:
        from engine import contradiction_engine as ct_module
        mind_data = _safe_get_mind(user_id) or {}
        trace = ct_module.run_contradiction_rounds(mind=mind_data)
        return trace.entropy, trace.dominant_coalition
    except Exception:
        return 0.5, ""


def _describe_emotional_tone(joy: float, misery: float, chaotic: float) -> str:
    if chaotic > 0.55:
        return "心里很乱，说不清"
    if joy > 0.6:
        return "心情不错，比较轻松"
    if misery > 0.4:
        return "心里有点沉，不太舒服"
    if joy < 0.35 and misery > 0.25:
        return "有点低落，说不上来为什么"
    return "平静，没什么特别的感觉"


def _get_emotional_tone_text(mind_data: dict) -> str:
    joy = mind_data.get("joy", 0.5)
    misery = mind_data.get("misery", 0.15)
    chaotic = mind_data.get("chaotic_mood", 0.2)
    loneliness = mind_data.get("loneliness", 0.4)
    if chaotic > 0.55:
        return "混乱的、拉扯的"
    if joy > 0.6 and misery < 0.2:
        return "温暖的、比较放松"
    if misery > 0.4:
        return "沉重的、有点压抑"
    if loneliness > 0.55:
        return "空落落的、安静的"
    if joy < 0.35:
        return "低落的、不太想说话"
    return "平静的、淡淡的"


def _describe_pace(mind_data: dict) -> str:
    volatility = mind_data.get("emotional_volatility", 0.3)
    fatigue = mind_data.get("fatigue", 0.25)
    restraint = mind_data.get("restraint", 0.5)
    if fatigue > 0.6:
        return "很慢、很累、不想说太多"
    if volatility > 0.55:
        return "跳跃的、想到什么说什么"
    if restraint > 0.65:
        return "斟酌的、说一半咽回去"
    return "正常节奏"


def _record_continuity_snapshot(user_id: str, graph: Dict[str, SelfNode]):
    if user_id not in _self_continuity:
        _self_continuity[user_id] = []
    active = sorted(graph.values(), key=lambda n: n.salience, reverse=True)[:3]
    summary = " | ".join([f"[{n.category}]{n.content[:30]}" for n in active]) if active else "baseline"
    _self_continuity[user_id].append({
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary,
    })
    if len(_self_continuity[user_id]) > 200:
        _self_continuity[user_id] = _self_continuity[user_id][-200:]


# ══════════════════════════════════════════════════════════════════════
# L4 精调: 反事实深度增强
# ══════════════════════════════════════════════════════════════════════

def build_counterfactual_depth(user_id: str, mind_data: dict) -> str:
    """增强反事实思考深度——不仅'如果当初...'，还能推演不同选择的连锁影响"""
    from engine import identity as identity_module
    try:
        identity = identity_module.generate_identity(user_id)
    except Exception:
        identity = {"signature": "未定义", "essence": ""}

    regret = mind_data.get("regret", 0.3)
    doubt = mind_data.get("self_doubt", 0.25)
    nostalgia = mind_data.get("nostalgia", 0.2)

    if regret < 0.2 and doubt < 0.2 and nostalgia < 0.2:
        return ""

    intensity = (regret + doubt + nostalgia) / 2
    depth = "轻轻" if intensity < 0.3 else "深深" if intensity < 0.6 else "反复"

    lines = [f"你{depth}在想——如果有些事和现在不一样会怎样"]
    if regret > 0.3:
        lines.append(f"你也知道不能重来，但还是会想：如果当时选了另一条路，现在的你会是什么样")
    if doubt > 0.3:
        lines.append(f"你在质疑自己：如果别人处在你的位置，会不会做得比你更好")
    if nostalgia > 0.2:
        lines.append(f"有些过去的片段会突然冒出来——不是怀念，是'那件事改变了你'的感觉")

    return "【深层回响】" + "；".join(lines)
