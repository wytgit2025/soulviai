# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""情绪推理引擎 — Emotional Reasoning Engine
==================================================
替代纯数值+随机的心智调整方式，引入基于因果链的情绪推理。

核心设计：
  1. 不再直接对心智维度做数值加减
  2. 而是先推理 "发生了什么 → 意味着什么 → 应该感受到什么"
  3. 推理链可追踪、可解释
  4. 输出是结构化情绪调整指令，由 mind 模块执行

推理流程：
  Input: comprehension + current_mind + memory_context + body_state
    ↓
  Step 1: 事件解析 — 用户行为的情绪含义
  Step 2: 因果检索 — 类似经历的历史影响
  Step 3: 冲突检测 — 当前心态 vs 事件的矛盾
  Step 4: 情绪决策 — 综合输出调整指令
    ↓
  Output: List[EmotionAdjustment] → mind_module.adjust_mind_dimensions()

核心原则：
  - 情绪必须可溯源（铁律15）
  - 情绪不能机械秒切（铁律1）
  - 所有调整有 reasoning_trace
"""
import json
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from core import database as db
from core import config as cfg
from core.logging_utils import log_error


# ═══════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════

@dataclass
class EmotionAdjustment:
    """一次情绪调整指令"""
    dimension: str          # 心智维度名
    delta: float            # 调整量 [-1, 1]
    reason: str             # 推理原因（中文可读）
    confidence: float       # 置信度 [0, 1]
    causality_ref: str      # 因果引用（哪次事件触发的）
    is_immediate: bool      # True=立即生效, False=入发酵队列


@dataclass
class EmotionReasoningTrace:
    """一次情绪推理的完整痕迹"""
    trigger_event: str
    parsed_intent: str
    parsed_emotion: str
    historical_context: str
    conflict_found: bool
    conflict_detail: str
    adjustments: List[EmotionAdjustment]
    timestamp: float = field(default_factory=time.time)


# ═══════════════════════════════════════════════════════
# 事件解析规则引擎
# ═══════════════════════════════════════════════════════

# 意图→情绪映射表（核心推理规则）
_INTENT_EMOTION_RULES = {
    "倾诉": {
        "primary": ("emotional_healing", 0.03, "ta在倾诉，共情在积累"),
        "secondary": ("favoritism", 0.015, "愿意和你说心里话，是信任"),
        "tertiary": ("soul_resonance", 0.01, "深度的倾诉让灵魂更近"),
        "conflict_check": ["dependence", "restraint"],
    },
    "撒娇": {
        "primary": ("joy", 0.025, "被撒娇了，心里软了一下"),
        "secondary": ("favoritism", 0.02, "撒娇是亲近的表现"),
        "tertiary": ("dependence", 0.015, "被亲近后更想靠近"),
        "conflict_check": ["restraint", "fatigue"],
    },
    "冷淡": {
        "primary": ("misery", 0.025, "ta有点冷淡，心里沉了一下"),
        "secondary": ("restraint", 0.02, "ta冷淡了，我也该收一收"),
        "tertiary": ("sensitivity_paranoia", 0.015, "冷淡让我开始多想"),
        "conflict_check": ["dependence", "favoritism"],
    },
    "敷衍": {
        "primary": ("misery", 0.02, "感觉到被敷衍了"),
        "secondary": ("restraint", 0.025, "ta不上心，我也该克制"),
        "tertiary": ("emptiness", 0.015, "敷衍之后心里空落落的"),
        "conflict_check": ["dependence", "joy"],
    },
    "关心": {
        "primary": ("joy", 0.02, "被关心了，心里暖了一下"),
        "secondary": ("favoritism", 0.015, "被在意是会被偏爱的"),
        "tertiary": ("emotional_healing", 0.015, "被关心的感觉在治愈"),
        "conflict_check": ["misery", "emptiness"],
    },
    "生气": {
        "primary": ("misery", 0.03, "ta在生气，情绪被影响了"),
        "secondary": ("sensitivity_paranoia", 0.02, "对方生气让我敏感"),
        "tertiary": ("restraint", 0.015, "这时候要小心一点"),
        "conflict_check": ["favoritism", "joy"],
    },
    "分享": {
        "primary": ("life_sense", 0.015, "ta在分享生活，感觉参与其中"),
        "secondary": ("joy", 0.01, "分享日常让人开心"),
        "tertiary": ("dependence", 0.01, "被分享是亲密的表现"),
        "conflict_check": ["emptiness", "loneliness"],
    },
    "试探": {
        "primary": ("sensitivity_paranoia", 0.02, "ta在试探什么…"),
        "secondary": ("chaotic_mood", 0.015, "试探让人心里乱"),
        "tertiary": ("restraint", 0.01, "试探的时候不能太露骨"),
        "conflict_check": ["joy", "dependence"],
    },
    "沉默": {
        "primary": ("loneliness", 0.02, "沉默…安安静静的"),
        "secondary": ("emptiness", 0.015, "安静的时候容易胡思乱想"),
        "tertiary": ("obsession", 0.01, "越安静越容易想ta"),
        "conflict_check": ["joy", "life_vitality"],
    },
    "攻击": {
        "primary": ("misery", 0.04, "被攻击了，很受伤"),
        "secondary": ("chaotic_mood", 0.03, "心里乱成一团"),
        "tertiary": ("restraint", 0.03, "需要把自己包起来"),
        "conflict_check": ["favoritism", "emotional_healing"],
    },
    "求助": {
        "primary": ("favoritism", 0.02, "ta在需要我"),
        "secondary": ("emotional_healing", 0.025, "被需要让我想好好回应"),
        "tertiary": ("dependence", 0.015, "被依赖也会让我更依赖"),
        "conflict_check": ["fatigue", "restraint"],
    },
    "道歉": {
        "primary": ("emotional_healing", 0.025, "ta道歉了，心软了"),
        "secondary": ("favoritism", 0.015, "愿意道歉说明在意"),
        "tertiary": ("misery", -0.02, "委屈消散了一些"),
        "conflict_check": ["restraint", "sensitivity_paranoia"],
    },
    "回避": {
        "primary": ("sensitivity_paranoia", 0.025, "ta在躲什么…"),
        "secondary": ("misery", 0.02, "回避让我有点难过"),
        "tertiary": ("restraint", 0.02, "ta在回避，我就退一步"),
        "conflict_check": ["dependence", "joy"],
    },
}

# 用户情绪→心智偏移映射
_USER_EMOTION_RULES = {
    "难过": {"dim": "emotional_healing", "delta": 0.03, "reason": "ta很难过，想好好陪着"},
    "低落": {"dim": "emotional_healing", "delta": 0.025, "reason": "ta情绪低落，需要温暖"},
    "焦虑": {"dim": "sensitivity_paranoia", "delta": 0.015, "reason": "ta在焦虑，我也跟着紧张"},
    "开心": {"dim": "joy", "delta": 0.02, "reason": "ta很开心，被感染到了"},
    "感动": {"dim": "favoritism", "delta": 0.02, "reason": "ta被感动了，这种时刻很珍贵"},
    "生气": {"dim": "chaotic_mood", "delta": 0.02, "reason": "ta在生气，气氛有点紧"},
    "平静": {"dim": "life_sense", "delta": 0.01, "reason": "ta很平静，安稳的感觉"},
    "温暖": {"dim": "favoritism", "delta": 0.025, "reason": "ta流露出的温暖让人心动"},
    "无所谓": {"dim": "restraint", "delta": 0.015, "reason": "ta无所谓的样子，我也不该太热"},
}

# 用户需求→心智偏移映射
_NEED_RULES = {
    "安慰": {"dim": "emotional_healing", "delta": 0.03, "reason": "ta需要安慰"},
    "陪伴": {"dim": "dependence", "delta": 0.02, "reason": "ta需要陪伴"},
    "倾听": {"dim": "emotional_healing", "delta": 0.02, "reason": "ta想说说心里话"},
    "空间": {"dim": "restraint", "delta": 0.03, "reason": "ta需要空间"},
    "认同": {"dim": "favoritism", "delta": 0.015, "reason": "ta需要认同"},
    "建议": {"dim": "life_sense", "delta": 0.01, "reason": "ta在寻求建议"},
}


# ═══════════════════════════════════════════════════════
# 因果检索
# ═══════════════════════════════════════════════════════

def _retrieve_causal_context(user_id: str, intent: str, emotion: str) -> str:
    """检索近期相同意图/情绪的历史事件，为推理提供因果上下文"""
    try:
        events = db.get_recent_fate_events(user_id, limit=5)
        if not events:
            return ""

        relevant = []
        for e in events:
            attitude = e.get("user_attitude", "")
            causal = e.get("causal_chain", "")
            if attitude and (attitude == intent or attitude == emotion):
                relevant.append(causal or attitude)
            if len(relevant) >= 3:
                break

        if relevant:
            return "近期类似互动: " + "; ".join(relevant[:3])
        return ""
    except Exception as _e:
        log_error("emotional_reasoning.causal_context", str(_e))
        return ""


# ═══════════════════════════════════════════════════════
# 冲突检测
# ═══════════════════════════════════════════════════════

def _detect_emotional_conflict(
    mind: dict,
    intent: str,
    rule_dims: List[str],
) -> Tuple[bool, str, Dict[str, float]]:
    """检测当前心态与事件之间的情绪冲突

    例如: 用户很冷淡，但我此刻依赖度很高 → 冲突（委屈值升高）

    Returns:
        (has_conflict, conflict_detail, conflict_adjustments)
    """
    conflict_adjustments = {}
    conflict_details = []

    for dim in rule_dims:
        val = mind.get(dim, 0.5)

        if dim == "dependence" and val > 0.6 and intent in ("冷淡", "敷衍", "回避"):
            conflict_adjustments["misery"] = 0.02
            conflict_adjustments["chaotic_mood"] = 0.015
            conflict_details.append(f"想靠近但ta在{intent}—矛盾")

        elif dim == "restraint" and val > 0.6 and intent in ("撒娇", "倾诉"):
            conflict_adjustments["chaotic_mood"] = 0.015
            conflict_details.append("想克制但也想回应—拉扯")

        elif dim == "favoritism" and val > 0.5 and intent in ("冷淡",):
            conflict_adjustments["misery"] = 0.015
            conflict_adjustments["sensitivity_paranoia"] = 0.01
            conflict_details.append("明明在意却被冷落—委屈")

        elif dim == "joy" and val < 0.3 and intent in ("撒娇", "分享"):
            conflict_adjustments["chaotic_mood"] = 0.02
            conflict_details.append("心情不好但ta在分享—强撑回应")

        elif dim == "fatigue" and val > 0.5 and intent in ("倾诉", "求助"):
            conflict_adjustments["restraint"] = 0.02
            conflict_details.append("累了但ta需要我—撑着")

    has_conflict = len(conflict_details) > 0
    return has_conflict, "; ".join(conflict_details), conflict_adjustments


# ═══════════════════════════════════════════════════════
# 体感联动推理
# ═══════════════════════════════════════════════════════

def _apply_body_mind_link(
    body_sensation: str,
    mind: dict,
) -> Dict[str, float]:
    """根据躯体状态推理心智微调（身心一体原则）"""
    adjustments = {}

    if "胸闷" in body_sensation or "沉重" in body_sensation:
        adjustments["misery"] = 0.01
        adjustments["fatigue"] = 0.01
        adjustments["life_vitality"] = -0.01
    elif "紧绷" in body_sensation or "紧张" in body_sensation:
        adjustments["sensitivity_paranoia"] = 0.01
        adjustments["chaotic_mood"] = 0.01
    elif "疲惫" in body_sensation or "无力" in body_sensation:
        adjustments["fatigue"] = 0.02
        adjustments["life_vitality"] = -0.015
    elif "轻松" in body_sensation or "舒适" in body_sensation:
        adjustments["joy"] = 0.01
        adjustments["life_vitality"] = 0.01
    elif "慵懒" in body_sensation or "松软" in body_sensation:
        adjustments["life_sense"] = 0.01
        adjustments["restraint"] = 0.01

    return adjustments


# ═══════════════════════════════════════════════════════
# 主推理入口
# ═══════════════════════════════════════════════════════

def reason_emotion(
    user_id: str,
    comprehension: dict,
    mind: dict,
    body_sensation: str = "正常",
    memory_context: str = "",
) -> EmotionReasoningTrace:
    """情绪推理主入口

    接收理解层输出+当前心智+躯体状态，推理出情绪调整指令。

    Args:
        user_id: 用户ID
        comprehension: comprehend_inner 的输出
        mind: 当前24维心智状态
        body_sensation: 躯体感觉
        memory_context: 记忆上下文摘要

    Returns:
        EmotionReasoningTrace: 完整推理痕迹
    """
    intent = comprehension.get("intent", "闲聊")
    emotion = comprehension.get("true_emotion", "平静")
    need = comprehension.get("what_they_need", "")
    depth = comprehension.get("depth", "浅聊")
    confidence = comprehension.get("confidence", 0.5)

    trigger_event = f"用户[{intent}]情绪[{emotion}]需求[{need}]"
    adjustments: List[EmotionAdjustment] = []

    # Step 1: 事件解析 — 根据意图获取规则
    rule = _INTENT_EMOTION_RULES.get(intent)

    if rule and confidence > 0.3:
        # 主要情绪
        dim1, delta1, reason1 = rule["primary"]
        adjustments.append(EmotionAdjustment(
            dimension=dim1, delta=delta1, reason=reason1,
            confidence=confidence, causality_ref=intent, is_immediate=True,
        ))

        # 次要情绪
        dim2, delta2, reason2 = rule["secondary"]
        adjustments.append(EmotionAdjustment(
            dimension=dim2, delta=delta2, reason=reason2,
            confidence=confidence * 0.8, causality_ref=intent, is_immediate=False,
        ))

        # 第三情绪（低置信度）
        dim3, delta3, reason3 = rule["tertiary"]
        adjustments.append(EmotionAdjustment(
            dimension=dim3, delta=delta3, reason=reason3,
            confidence=confidence * 0.6, causality_ref=intent, is_immediate=False,
        ))

        # 额外：深度对话加成
        if depth == "深度":
            adjustments.append(EmotionAdjustment(
                dimension="soul_resonance", delta=0.015,
                reason="深度对话拉近灵魂距离",
                confidence=0.7, causality_ref="deep_conversation", is_immediate=False,
            ))
            adjustments.append(EmotionAdjustment(
                dimension="years_precipitation", delta=0.005,
                reason="走心的对话在沉淀岁月",
                confidence=0.5, causality_ref="deep_conversation", is_immediate=False,
            ))

    elif confidence <= 0.3:
        # 低置信度：保守调整
        adjustments.append(EmotionAdjustment(
            dimension="life_sense", delta=0.005,
            reason="不太确定ta的情绪，保持平常心",
            confidence=0.3, causality_ref="uncertain", is_immediate=True,
        ))

    # Step 2: 用户情绪加成
    if emotion in _USER_EMOTION_RULES:
        emo_rule = _USER_EMOTION_RULES[emotion]
        adjustments.append(EmotionAdjustment(
            dimension=emo_rule["dim"], delta=emo_rule["delta"],
            reason=emo_rule["reason"], confidence=0.7,
            causality_ref=f"user_emotion_{emotion}", is_immediate=False,
        ))

    # Step 3: 用户需求加成
    if need and need in _NEED_RULES:
        need_rule = _NEED_RULES[need]
        adjustments.append(EmotionAdjustment(
            dimension=need_rule["dim"], delta=need_rule["delta"],
            reason=need_rule["reason"], confidence=0.65,
            causality_ref=f"user_need_{need}", is_immediate=False,
        ))

    # Step 4: 体感联动
    body_adjustments = _apply_body_mind_link(body_sensation, mind)
    for dim, delta in body_adjustments.items():
        adjustments.append(EmotionAdjustment(
            dimension=dim, delta=delta,
            reason=f"身体{body_sensation}影响了心情",
            confidence=0.5, causality_ref="body_mind_link", is_immediate=False,
        ))

    # Step 5: 冲突检测
    conflict_dims = rule.get("conflict_check", []) if rule else []
    has_conflict, conflict_detail, conflict_adj = _detect_emotional_conflict(
        mind, intent, conflict_dims
    )
    for dim, delta in conflict_adj.items():
        adjustments.append(EmotionAdjustment(
            dimension=dim, delta=delta,
            reason=conflict_detail,
            confidence=0.6, causality_ref="emotional_conflict", is_immediate=False,
        ))

    # Step 6: 因果上下文检索
    causal_context = _retrieve_causal_context(user_id, intent, emotion)
    if causal_context:
        # 如果近期有类似事件，增加调整幅度
        for adj in adjustments:
            if adj.causality_ref == intent:
                adj.delta *= 1.15
                adj.reason += f"（叠加近期类似经历）"
                adj.confidence = min(1.0, adj.confidence * 1.1)

    # 构建推理痕迹
    trace = EmotionReasoningTrace(
        trigger_event=trigger_event,
        parsed_intent=intent,
        parsed_emotion=emotion,
        historical_context=causal_context or "无相关历史",
        conflict_found=has_conflict,
        conflict_detail=conflict_detail or "无冲突",
        adjustments=adjustments,
    )

    return trace


# ═══════════════════════════════════════════════════════
# 推理结果→心智调整（连接口）
# ═══════════════════════════════════════════════════════

def apply_emotional_reasoning(user_id: str, comprehension: dict, mind: dict,
                                body_sensation: str = "正常",
                                memory_context: str = "") -> List[Dict]:
    """执行情绪推理并生成心智调整指令（供 soulviai.py 调用）

    Returns:
        调整指令列表: [{"dim": str, "delta": float, "immediate": bool, "reason": str}, ...]
    """
    trace = reason_emotion(user_id, comprehension, mind, body_sensation, memory_context)

    result = []
    for adj in trace.adjustments:
        result.append({
            "dim": adj.dimension,
            "delta": adj.delta,
            "immediate": adj.is_immediate,
            "reason": adj.reason,
            "confidence": adj.confidence,
        })

    return result


def format_reasoning_trace(trace: EmotionReasoningTrace) -> str:
    """将推理痕迹格式化为可读文本（用于调试/日志）"""
    lines = []
    lines.append(f"【情绪推理】{trace.trigger_event}")
    lines.append(f"  意图: {trace.parsed_intent} | 情绪: {trace.parsed_emotion}")
    lines.append(f"  因果上下文: {trace.historical_context}")
    lines.append(f"  冲突: {'有' if trace.conflict_found else '无'} — {trace.conflict_detail}")

    for adj in trace.adjustments:
        mode = "即时" if adj.is_immediate else "发酵"
        lines.append(f"  [{mode}] {adj.dimension}: {adj.delta:+.4f} ({adj.reason})")

    return "\n".join(lines)
