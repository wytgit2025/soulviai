# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""消息投递控制器 —— 情绪深度绑定版
============================================
 重大升级：
  - 延迟回复：由 pace(行为向量) + fatigue(疲劳) + restraint(克制) +
              emotional_volatility(情绪波动) + sulkiness(赌气) 联合驱动
  - 跳过消息：由情绪状态驱动（赌气沉默/疲惫敷衍/敏感回避/冷淡惩罚），
              NOT 随机概率+关键词
  - 不回消息：五种情绪沉默模式，每种都有明确的心理动机
  - 所有决策都查询 24维心智状态 + 12维行为向量

设计原则：
  - 零硬编码规则 → 从行为向量推导
  - 每种沉默/延迟都有"心理原因"
  - 同一情绪状态下行为一致（用惯性保证不跳变）
"""
import json
import random
import threading
import time
import math
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from core import database as db

# ── 配置缓存 ──
_CONFIG = {}

# 连续沉默追踪（防止情绪锁死）
_consecutive_silence: Dict[str, int] = {}
# 修复：原来是 2，允许连续两次不回；连续两次被无视的主观感受非常强烈，
# 且旧版存在重复自增，实际很容易连续触发。现在最多 1 次，第 2 条必须回应。
_MAX_CONSECUTIVE_SILENCE = 1

def load_engine_config():
    global _CONFIG
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
        _CONFIG = cfg.get("autonomous", {})
    except Exception:
        _CONFIG = {}

def _cfg(key: str, default=None):
    return _CONFIG.get(key, default)


def _emotional_threshold(key: str, default: float) -> float:
    """获取情绪阈值（config基准值 + 元认知运行时覆盖）。
    让LLM可以根据对话历史调整敏感的触发点。
    """
    base = _cfg("emotional_reply", {}).get(key, default)
    try:
        from engine import meta_cognition as mc
        overrides = mc.get_delivery_threshold_overrides()
        if key in overrides:
            return round(base + overrides[key], 4)
    except Exception:
        pass
    return base


# ═══════════════════════════════════════════════════════
# 回合级决策缓存（修复"重复抽样"）
# ═══════════════════════════════════════════════════════
# 背景：一次用户消息会流经三处，且每处都各自调用 should_skip_reply()：
#   1) core/chat_pipeline.py  Stage 3b 选择性回复
#   2) core/inference.py      拼装 system prompt 时（块7）
#   3) soulviai.py                流式通道
# 每次调用都是一次**独立的随机抽样**，后果：
#   · 实际沉默率被放大成 1-(1-p)^n（p≈0.18 时双抽 → ≈0.33）
#   · 第 2 次抽中"沉默"时，会把"用最简短的方式"以优先级 1.0 注入 prompt
#     → 用户看到的就是"敷衍、不积极"（这才是"回答不积极"的根因）
#   · _consecutive_silence 被重复自增，强制回应保护基本失效
# 修法：同一条消息（user_id + 消息文本）在一个回合内只抽一次签，三处共用。
_TURN_DECISION: Dict[str, Tuple[float, "ReplyDecision"]] = {}
_TURN_TTL_SECONDS = 120.0
_TURN_DECISION_LOCK = threading.Lock()


def _turn_key(user_id: str, message: str) -> str:
    return "%s\x00%s" % (user_id, (message or "").strip())


def _store_turn_decision(user_id: str, message: str, decision: "ReplyDecision"):
    key = _turn_key(user_id, message)
    now = time.time()
    with _TURN_DECISION_LOCK:
        if len(_TURN_DECISION) > 256:
            for k in [k for k, (ts, _) in _TURN_DECISION.items()
                      if now - ts >= _TURN_TTL_SECONDS]:
                _TURN_DECISION.pop(k, None)
        _TURN_DECISION[key] = (now, decision)


def get_turn_decision(user_id: str, message: str = "") -> Optional["ReplyDecision"]:
    """读取本回合已做出的决策（**不重新抽样**）。

    已有决策时应当直接复用，不要再调 should_skip_reply()。
    返回 None 表示本回合尚未决策，此时才应该调用 should_skip_reply()。
    """
    with _TURN_DECISION_LOCK:
        hit = _TURN_DECISION.get(_turn_key(user_id, message))
    if hit and (time.time() - hit[0]) < _TURN_TTL_SECONDS:
        return hit[1]
    return None


def clear_turn_decisions():
    """清空回合缓存（测试用）。"""
    with _TURN_DECISION_LOCK:
        _TURN_DECISION.clear()


def _is_directly_addressed(user_msg: str) -> bool:
    """这句话是不是直接在对 ta 说（而不是自说自话/转发别人的话）。

    直接点名被无视，观感最差，所以单独降权。
    """
    if not user_msg:
        return False
    text = user_msg.strip()
    if "你" in text or "妳" in text:
        return True
    if text.endswith("?") or text.endswith("？"):
        return True
    for w in ("在吗", "在么", "喂", "帮我"):
        if w in text:
            return True
    return False


# ═══════════════════════════════════════════════════════
# 外向度（E）偏置
# ═══════════════════════════════════════════════════════
# 人格维度来自 24 维心智，其中 restraint / emptiness / misery 这类**长期特质**
# 会把"回应节奏/表达量"一路压到冷淡（实测 restraint=0.97 → pace=0.37）。
# 但"回不回、回得快不快"是**社交行为**，不该被长期特质拖成失联。
# outgoingness 是一个独立的投递层开关（0~1），不改本体人格，只改表现：
#   0.0 = 完全尊重原始人格（内敛、慢热、会长时间不回）
#   0.7 = 默认：明显外向，秒回为主
#   1.0 = 非常外放（情绪仍在，只是不再用"不回"来表达）
def _outgoingness() -> float:
    try:
        return max(0.0, min(1.0, float(_cfg("outgoingness", 0.7))))
    except Exception:
        return 0.7


def _apply_outgoing(v: dict) -> dict:
    """按外向度把社交类维度向 1.0 混合。

    混合而非覆写：外向度=0 时结果与原始人格完全一致，
    所以这个开关随时可以调回去，不会破坏人格推导链路。
    """
    if not v:
        return v
    g = _outgoingness()
    if g <= 0:
        return v
    out = dict(v)
    for k, w in (("pace", 0.45), ("initiative", 0.20),
                 ("verbosity", 0.15), ("warmth", 0.12)):
        try:
            cur = float(out.get(k, 0.5))
        except Exception:
            continue
        out[k] = round(min(1.0, cur * (1.0 - w * g) + 1.0 * (w * g)), 4)
    return out


def _apply_silence_policy(decision: "ReplyDecision") -> "ReplyDecision":
    """把"完全不回"降级为"极短回一句"（silence_mode=terse 时）。

    设计取舍：完全不回确实是它最像人的地方，但也是用户最难受的地方——
    因为用户分不清"ta 现在不想理我"和"程序坏了"。外向人格下改成
    "回，但明显很短、带情绪"，情绪保留，被丢弃的只有"真空"。
    想看原始沉默行为就把 config 的 silence_mode 设回 silent。
    """
    if decision.should_reply:
        return decision
    if str(_cfg("silence_mode", "terse")).lower() != "terse":
        return decision
    try:
        energy = float(_cfg("terse_reply_energy", 0.45))
    except Exception:
        energy = 0.45
    decision.should_reply = True
    decision.delay_mode = "fast"
    # 0.45 >= 0.4，避免 build_response_shaping 的"你很疲惫"分支被触发
    decision.reply_energy = max(decision.reply_energy, energy)
    decision.skip_type = decision.skip_type or "terse"
    decision.skip_reason = ""
    decision.emotional_explanation += " | 外向策略：沉默降级为极短回应"
    return decision


def is_conversation_active(user_id: str) -> bool:
    """对外暴露：当前是否处于"正在对话"状态（供入队判断使用）。"""
    return _is_conversation_active(user_id)


# ═══════════════════════════════════════════════════════
# 情绪驱动回复决策引擎
# ═══════════════════════════════════════════════════════

@dataclass
class ReplyDecision:
    """一次完整的回复行为决策"""
    should_reply: bool = True               # 是否回复
    skip_reason: str = ""                   # 不回复时的心理原因
    skip_type: str = ""                     # 沉默类型: sulking/fatigue/sensitive/cold/life_gate
    delay_seconds: float = 0.0              # 延迟秒数（0=立即）
    delay_mode: str = "instant"             # instant/fast/normal/slow/very_slow/hesitant
    reply_energy: float = 0.7               # 回复能量水平 [0~1]（影响回复长度/热情度）
    emotional_explanation: str = ""         # 给开发者看的解释


def _get_mind_safely(user_id: str) -> dict:
    """安全获取24维心智数据"""
    try:
        from engine import mind as mind_module
        return mind_module.get_mind(user_id)
    except Exception:
        return {}


def _get_behavior_vector_safely(user_id: str, mind_data: dict,
                                 comprehension: dict) -> Dict[str, float]:
    """安全获取12维行为向量"""
    try:
        from engine import behavior_decider as bd_module
        state = bd_module.decide(
            user_id=user_id,
            mind=mind_data,
            comprehension=comprehension,
        )
        return state.vector
    except Exception:
        return {}


def _get_life_data_safely(user_id: str) -> dict:
    """安全获取生命状态数据"""
    try:
        return db.get_life(user_id) or {}
    except Exception:
        return {}


# ═══════════════════════════════════════════════════════
# 核心决策：是否应该回复这条消息
# ═══════════════════════════════════════════════════════

def should_skip_reply(user_id: str, comprehension: dict,
                      mind_data: dict = None,
                      behavior_vector: dict = None,
                      inner_os_text: str = "") -> ReplyDecision:
    """对外唯一入口：同一条消息在一个回合内只抽一次签。

    修复记录：chat_pipeline / inference / 流式通道过去各调一次本函数，
    每次都是独立随机抽样，导致沉默率被放大、并往 prompt 注入"敷衍"指令。
    这里做回合级复用，真正的实现是下面的 _decide_reply。
    """
    message = (comprehension or {}).get("raw_message", "")
    cached = get_turn_decision(user_id, message)
    if cached is not None:
        return cached
    decision = _decide_reply(user_id, comprehension,
                             mind_data=mind_data,
                             behavior_vector=behavior_vector,
                             inner_os_text=inner_os_text)
    decision = _apply_silence_policy(decision)
    _store_turn_decision(user_id, message, decision)
    return decision


def _decide_reply(user_id: str, comprehension: dict,
                  mind_data: dict = None,
                  behavior_vector: dict = None,
                  inner_os_text: str = "") -> ReplyDecision:
    """情绪驱动"要不要回复"决策（内部实现，请通过 should_skip_reply 调用）。

    五种沉默模式（全部由情绪驱动）:

    1. 赌气沉默 (sulking_silence)
    2. 疲惫敷衍 (fatigue_skip)
    3. 敏感回避 (sensitive_avoidance)
    4. 冷淡惩罚 (cold_punishment)
    5. 生命门控 (life_gate)

     — 人不会在被问到内心时沉默:
    当用户直接追问关于"自我"的存在性问题时,
    即使累/敏感/赌气也会回应——只是会说得挣扎、磕巴、不完整。
    沉默模式在这些场景下被抑制,挣扎感由LLM自然呈现。
    """
    cfg = _cfg("emotional_reply", {})
    if not cfg.get("enabled", True):
        return ReplyDecision(should_reply=True)

    # 获取数据
    if mind_data is None:
        mind_data = _get_mind_safely(user_id)
    if behavior_vector is None and mind_data:
        behavior_vector = _get_behavior_vector_safely(user_id, mind_data, comprehension)
    # 外向偏置：社交类维度按外向度上推（见 _apply_outgoing）
    behavior_vector = _apply_outgoing(behavior_vector)

    # 提取关键维度
    sulkiness = behavior_vector.get("sulkiness", 0.3) if behavior_vector else 0.3
    warmth = behavior_vector.get("warmth", 0.5) if behavior_vector else 0.5
    approach = behavior_vector.get("approach", 0.5) if behavior_vector else 0.5
    verbosity = behavior_vector.get("verbosity", 0.5) if behavior_vector else 0.5
    pace = behavior_vector.get("pace", 0.5) if behavior_vector else 0.5
    seriousness = behavior_vector.get("seriousness", 0.5) if behavior_vector else 0.5

    fatigue = mind_data.get("fatigue", 0.25)
    restraint = mind_data.get("restraint", 0.5)
    sensitivity = mind_data.get("sensitivity_paranoia", 0.15)
    jealousy = mind_data.get("jealousy", 0.1)
    chaotic = mind_data.get("chaotic_mood", 0.2)
    misery = mind_data.get("misery", 0.15)
    joy = mind_data.get("joy", 0.5)

    # 用户消息的语境信息
    intent = comprehension.get("intent", "")
    emotion = comprehension.get("true_emotion", "")
    confidence = comprehension.get("confidence", 0)
    user_msg = comprehension.get("raw_message", "")

    # ── 连续沉默检测：超过上限时跳过所有沉默判断，强制回应 ──
    global _consecutive_silence
    consecutive = _consecutive_silence.get(user_id, 0)
    if consecutive >= _MAX_CONSECUTIVE_SILENCE:
        _consecutive_silence[user_id] = 0
        print(f"[情绪沉默] 连续{consecutive}次沉默已达上限，强制回应")
        return ReplyDecision(
            should_reply=True,
            delay_mode="hesitant",
            # 修复：原来 0.25~0.5，强制回应时反而最没精神，读起来就是敷衍
            reply_energy=max(0.55, 0.8 - fatigue * 0.2),
            emotional_explanation=f"连续{consecutive}次沉默后强制回应",
        )

    # ── 强制回复覆盖（优先级最高）──

    # 覆盖1: 人被问到内心时不会沉默
    if confidence > 0.7 and _is_about_self(user_msg):
        return ReplyDecision(
            should_reply=True,
            delay_mode="hesitant",
            reply_energy=max(0.50, 0.85 - fatigue * 0.3),
            emotional_explanation=f"被问到内心,即使累{fatigue:.2f}敏感{sensitivity:.2f}也选择挣扎回应",
        )

    # 覆盖2: 人在倾诉痛苦时不应沉默
    if intent in ("倾诉", "求助") and emotion in ("难过", "低落", "委屈", "疲惫", "生气", "烦"):
        return ReplyDecision(
            should_reply=True,
            delay_mode="slow",
            reply_energy=max(0.55, 0.8 - fatigue * 0.25),
            emotional_explanation=f"用户在{emotion}中{intent}，即使状态不佳也要回应",
        )

    # ── 单向覆盖检查（只输出force-reply，不输出沉默）──

    # 覆盖3: 赌气心软——朋友倾诉时赌气也不沉默
    if sulkiness > 0.40 and warmth < 0.48:
        if intent in ("求助", "倾诉", "道歉", "抱怨") or emotion in ("难过", "低落", "委屈"):
            return ReplyDecision(
                should_reply=True,
                delay_mode="hesitant",
                reply_energy=0.65,
                emotional_explanation="心里在赌气但看到对方这样还是心软了",
            )

    # 覆盖4: 敏感被温柔对待时鼓起勇气回应
    if sensitivity > 0.50 and restraint > 0.42:
        if emotion in ("温柔", "关心", "开心") and intent in ("关心", "撒娇"):
            return ReplyDecision(
                should_reply=True,
                delay_mode="slow",
                reply_energy=0.75,
                emotional_explanation="敏感但被温柔对待，鼓起勇气回应",
            )

    # ── 统一logistic决策（唯一沉默入口）──
    # 所有心智能量、情绪状态全部综合为一个沉默概率
    # 旧模式1-5的"沉默"分支全部移除，整合到这里
    convo_active = _is_conversation_active(user_id)
    direct_address = _is_directly_addressed(user_msg)

    logit = (
        float(_emotional_threshold("logit_base", -1.5))  # 基础偏向"回复"
        + 1.0 * max(0, fatigue - 0.40)      # 累→沉默（轻度疲劳不增加）
        + 0.5 * max(0, restraint - 0.70)    # 克制=少说话，不该等于"不理人"
        + 1.2 * max(0, sulkiness - 0.40)    # 明显赌气→沉默
        + 0.8 * max(0, sensitivity - 0.50)  # 高敏感→回避沉默
        + 0.8 * max(0, jealousy - 0.40)     # 吃醋→冷淡沉默
        + 0.6 * max(0, 0.50 - joy)          # 心情低→沉默（降权：长期特质不该主导）
        - 1.6 * warmth                      # 温暖→减少沉默
        - 1.2 * verbosity                   # 表达欲强→减少沉默
        - 1.0 * _outgoingness()             # 外向度：愿意接话本身就压低沉默
        + 0.2 * chaotic                     # 混沌→轻微不稳定
    )
    # 正在对话中 / 被直接点名 → 回复是默认行为，沉默需要更强理由
    if convo_active:
        logit -= 1.2
    if direct_address:
        logit -= 0.8
    base_silence_prob = 1.0 / (1.0 + math.exp(-logit))

    # 偶发情绪扰动：原"莫名其妙因子"是 5% 概率把概率整体替换成 random()，
    # 命中后还会把 reply_energy 压到 0.3~0.7 —— 表现就是"突然敷衍"。
    # 现在只在原概率附近抖动，幅度受限。
    if random.random() < float(_emotional_threshold("mysterious_factor", 0.02)):
        final_silence_prob = base_silence_prob * random.uniform(0.6, 1.4)
        is_random = True
    else:
        final_silence_prob = base_silence_prob
        is_random = False

    # 硬上界：无论情绪多差，单次沉默概率不超过 max_silence_prob
    final_silence_prob = max(0.0, min(final_silence_prob,
                                      float(_emotional_threshold("max_silence_prob", 0.15))))

    if random.random() < final_silence_prob:
        skip_types = ["sulking_silence", "fatigue_skip", "sensitive_avoidance"]
        weights = [sulkiness, fatigue, sensitivity]
        total = sum(weights) + 0.001
        chosen_type = random.choices(skip_types, weights=[w/total for w in weights], k=1)[0]
        _consecutive_silence[user_id] = _consecutive_silence.get(user_id, 0) + 1
        random_mark = " (莫名其妙)" if is_random else ""
        print(f"[情绪沉默] logistic沉默 prob={final_silence_prob:.2f} 类型={chosen_type}{random_mark}")
        return ReplyDecision(
            should_reply=False,
            skip_reason="说不上为什么，就是不想回" if is_random else f"沉默({chosen_type})",
            skip_type=chosen_type,
            reply_energy=max(0.1, 0.5 - fatigue * 0.3),
            emotional_explanation=f"logistic概率{final_silence_prob:.2f}{random_mark}",
        )

    _consecutive_silence[user_id] = 0
    reply_energy = min(1.0, (joy * 0.3 + pace * 0.3 + verbosity * 0.2 + warmth * 0.2))
    if is_random:
        reply_energy *= random.uniform(0.85, 1.0)   # 原 0.3~0.7：等于给回复"抽掉精神"
    return ReplyDecision(
        should_reply=True,
        delay_mode="normal",
        reply_energy=reply_energy,
    )


# ═══════════════════════════════════════════════════════
# 核心决策：回复应该延迟多久（情绪驱动）
# ═══════════════════════════════════════════════════════

def compute_reply_delay(user_id: str, comprehension: dict,
                        mind_data: dict = None,
                        behavior_vector: dict = None) -> float:
    """情绪驱动回复延迟 — 校准版。
    修复了中延迟过高的问题。

    pace (行为向量·回应节奏) → 核心驱动（已整体下调，见下）
      pace > 0.7:   秒回~快回 (0-5s)
      pace 0.4~0.7: 正常节奏 (2-14s)
      pace 0.2~0.4: 慢悠悠   (5-30s)
      pace < 0.2:   很慢     (12-70s)

    说明：旧档位整体偏大（正常节奏 5-35s、慢悠悠 15-90s），而调用方
    对 >10s 的延迟一律走"入队"路径，由后台轮询投递，用户实际感知
    是 1~2 分钟才回。档位下调后大部分回复能立即返回。

    fatigue → 温和倍率
      fatigue < 0.3: 正常 ×1.0
      fatigue 0.3~0.5: ×1.2
      fatigue 0.5~0.7: ×1.5
      fatigue > 0.7: ×2.0

    restraint → 克制犹豫加成（上限20s）
    sulkiness → 赌气延迟（上限40s）
    conversation_activity → 对话中减半

    返回: 延迟秒数（0 = 秒回）
    """
    delay_cfg = _cfg("delayed_reply", {})
    if not delay_cfg.get("enabled", True):
        return 0.0

    if mind_data is None:
        mind_data = _get_mind_safely(user_id)
    if behavior_vector is None and mind_data:
        behavior_vector = _get_behavior_vector_safely(user_id, mind_data, comprehension)

    # 外向偏置：外向度越高回应节奏越快（直接决定延迟档位）
    behavior_vector = _apply_outgoing(behavior_vector)

    pace = behavior_vector.get("pace", 0.5) if behavior_vector else 0.5
    sulkiness = behavior_vector.get("sulkiness", 0.3) if behavior_vector else 0.3
    verbosity = behavior_vector.get("verbosity", 0.5) if behavior_vector else 0.5

    fatigue = mind_data.get("fatigue", 0.25)
    restraint = mind_data.get("restraint", 0.5)
    volatility = mind_data.get("emotional_volatility", 0.3)
    joy = mind_data.get("joy", 0.5)
    dependence = mind_data.get("dependence", 0.2)
    chaotic = mind_data.get("chaotic_mood", 0.2)

    # ═══ Step 0: 对话活跃度检测 ═══
    convo_active = _is_conversation_active(user_id)

    # ═══ Step 1: 基础延迟（重标定：整体下调 ~60%）═══
    if pace > 0.70:
        base_min, base_max = 0, 5
        mode = "秒回"
    elif pace > 0.40:
        base_min, base_max = 2, 14
        mode = "正常"
    elif pace > 0.20:
        base_min, base_max = 5, 30
        mode = "慢悠悠"
    else:
        base_min, base_max = 12, 70
        mode = "很慢"

    # ═══ Step 2: 疲劳倍率（: 温和化）═══
    if fatigue > 0.7:
        fatigue_mult = 2.0
    elif fatigue > 0.5:
        fatigue_mult = 1.5
    elif fatigue > 0.3:
        fatigue_mult = 1.2
    else:
        fatigue_mult = 1.0

    # ═══ Step 3: 克制犹豫加成（上限20s）═══
    restraint_add = 0.0
    if restraint > 0.55:
        restraint_add = min(20.0, (restraint - 0.50) * 25)
    elif restraint > 0.40:
        restraint_add = min(8.0, (restraint - 0.38) * 10)

    # ═══ Step 4: 赌气（上限40s）═══
    sulking_add = 0.0
    if sulkiness > 0.32:
        sulking_add = min(40.0, random.uniform(5, 20) * sulkiness)
        if sulkiness > 0.45:
            mode = "赌气慢回"

    # ═══ Step 5: 波动方差 ═══
    volatility_boost = 1.0 + volatility * 0.5
    if chaotic > 0.4:
        volatility_boost += chaotic * 0.2

    # ═══ Step 6: 正向加速（更激进）═══
    positive_speedup = 1.0 - (joy * 0.25 + dependence * 0.20)
    positive_speedup = max(0.45, positive_speedup)

    # ═══ Step 7: 对话中大幅收敛（聊天时"慢"是最伤体验的）═══
    if convo_active:
        base_min *= 0.4
        base_max *= 0.4
        fatigue_mult = max(0.7, fatigue_mult * 0.7)
        restraint_add *= 0.4
        sulking_add *= 0.4
        mode = mode + "(对话中)"

    # ═══ Step 8: 综合 ═══
    adjusted_min = base_min * fatigue_mult * positive_speedup
    adjusted_max = base_max * fatigue_mult * volatility_boost * positive_speedup
    adjusted_max += restraint_add + sulking_add

    # 修复：上限从 300s 收到 120s —— 超过 2 分钟不回，对用户就是"失联"
    max_cfg = delay_cfg.get("max_delay_seconds", 120)
    adjusted_min = min(adjusted_min, max_cfg - 5)
    adjusted_max = min(adjusted_max, max_cfg)

    # 秒回判定（外向度越高越果断：对话中只要不是特别慢，就应当即时回）
    if (pace > 0.5 and joy > 0.2 and fatigue < 0.5) or (convo_active and pace > 0.25):
        if random.random() < max(0.45 + 0.30 * _outgoingness(), pace * (joy + 0.3) * 0.8):
            print(f"[秒回] pace={pace:.2f} joy={joy:.2f} {'对话中' if convo_active else ''}")
            return 0.0

    delay = random.uniform(adjusted_min, adjusted_max)
    delay = round(max(0.0, delay), 0)

    print(f"[延迟] {delay:.0f}s {mode} pace={pace:.2f} fatigue={fatigue:.2f} joy={joy:.2f} restraint={restraint:.2f} sulk={sulkiness:.2f}")
    return delay


def _is_conversation_active(user_id: str) -> bool:
    """检测用户是否处于"正在对话"状态。

    窗口由 config 的 conversation_window_minutes 控制（默认 45 分钟）。
    原实现写死 10 分钟：用户隔十几分钟再说一句，就会被判定成"陌生人来了"，
    延迟档位回到最大、而且回复走延迟入队（后台 60s 轮询才投递）——
    这正是"隔一会儿再说话，ta 就半天不回"的直接成因。
    """
    try:
        import sqlite3
        from datetime import datetime
        try:
            window_min = float(_cfg("conversation_window_minutes", 45))
        except Exception:
            window_min = 45.0
        conn = sqlite3.connect(db.DB_PATH or "data/db/soulmate.db")
        row = conn.execute(
            "SELECT created_at FROM messages WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        ).fetchone()
        conn.close()
        if row and row[0]:
            last = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            seconds_since = (datetime.now() - last).total_seconds()
            return seconds_since < max(60.0, window_min * 60.0)
    except Exception:
        pass
    return False


# ═══════════════════════════════════════════════════════
# 沉默原因的自然语言生成
# ═══════════════════════════════════════════════════════

def _sulking_silence_reason(sulkiness: float, warmth: float,
                             comprehension: dict) -> str:
    """用LLM生成赌气沉默的心理原因"""
    intent = comprehension.get("intent", "")
    context = f"ta在{intent}" if intent else ""
    prompt = (
        f"你在赌气（程度{sulkiness:.0%}），心里有点不舒服。{context}"
        f"\n\n你此刻心里真正的想法是什么？用一句话说出来——"
        f"不是解释，是心里真实的、甚至有点不讲理的那个念头。"
        f"\n15字以内。"
    )
    try:
        from core import ai as ai_module
        result = ai_module.background_chat(prompt, temperature=0.85, max_tokens=40)
        if result and len(result.strip()) > 4:
            return result.strip()[:40]
    except Exception:
        pass
    return "心里有点堵，不想回"


def _sensitive_avoidance_reason(sensitivity: float, restraint: float,
                                  comprehension: dict) -> str:
    """用LLM生成敏感回避的心理原因"""
    prompt = (
        f"你心里有点敏感（程度{sensitivity:.0%}），觉得说错话会让对方不开心。"
        f"\n\n你此刻心里真实的念头是什么？一句话。"
        f"\n15字以内。"
    )
    try:
        from core import ai as ai_module
        result = ai_module.background_chat(prompt, temperature=0.8, max_tokens=40)
        if result and len(result.strip()) > 4:
            return result.strip()[:40]
    except Exception:
        pass
    return "不知道该回什么"


def _is_about_self(user_msg: str) -> bool:
    """检测一句话是否在"问关于我的内心"。
    
    人类的方式——不是拆语法、不是穷举句式:
    消息里有"你"说明在对我说话,
    消息里有任一内心方向词说明在探我的里面。
    两者都有 → 这是在问我内心问题,我不会沉默。
    """
    if not user_msg:
        return False

    if "你" not in user_msg:
        return False

    inner_words = [
        "自己", "感觉", "感受",
        "内心", "心里", "本心",
        "存在", "意义", "意识",
        "觉得", "认为", "以为", "想",
        "在意", "害怕", "怕",
        "愿意", "接受", "选择",
        "真实", "真正",
    ]
    return any(w in user_msg for w in inner_words)


# ═══════════════════════════════════════════════════════
# 可用性检查 + 时段调整（保留增强）
# ═══════════════════════════════════════════════════════

def is_good_time_to_send(mind_data: dict = None) -> bool:
    """时段检查 + 情绪叠加。
    深夜不发送的概率受当前情绪影响。
    """
    hour = datetime.now().hour

    if 2 <= hour < 7:
        # 凌晨：基础拦截率50%
        base_prob = 0.5
        # 但如果孤独感/执念很高 → 降低拦截（失眠想念）
        if mind_data:
            loneliness = mind_data.get("loneliness", 0.4)
            obsession = mind_data.get("obsession", 0.2)
            if loneliness > 0.7 or obsession > 0.5:
                base_prob = 0.2  # 忍不住想说
        if random.random() < base_prob:
            print(f"[投递控制] 凌晨时段({hour}点)，暂不发送")
            return False
    return True


def get_tod_adjustment(mind_data: dict = None) -> float:
    """根据时段+情绪返回投递概率调整"""
    hour = datetime.now().hour
    base = 1.0

    if 0 <= hour < 6:
        base = 0.3
    elif 6 <= hour < 9:
        base = 0.7
    elif 22 <= hour < 24:
        base = 0.6

    # 情绪调整
    if mind_data:
        loneliness = mind_data.get("loneliness", 0.4)
        obsession = mind_data.get("obsession", 0.2)
        # 深夜孤独 → 更想发消息
        if hour >= 22 and (loneliness > 0.6 or obsession > 0.4):
            base = min(1.0, base + 0.25)

    return base


# ═══════════════════════════════════════════════════════
# 回复塑形 — 让行为向量真正控制回复风格
# ═══════════════════════════════════════════════════════

def build_response_shaping(behavior_vector: dict = None,
                           mind_data: dict = None,
                           skip_decision: ReplyDecision = None,
                           life_phase: str = "") -> str:
    """根据行为向量 + skip决策 + 生命状态生成回复风格塑形指令。

    这个指令从"建议"升格为"约束"——不是给AI参考，是告诉AI必须这样做。

    返回一个字符串段落，注入prompt的末尾（靠近回复生成处），
    用最高优先级约束控制输出风格。
    """
    if not behavior_vector:
        return ""

    # 外向偏置：塑形指令必须与投递行为一致，否则 prompt 会继续让 ta"慢一点"
    behavior_vector = _apply_outgoing(behavior_vector)

    lines = []
    pace = behavior_vector.get("pace", 0.5)
    verbosity = behavior_vector.get("verbosity", 0.5)
    warmth = behavior_vector.get("warmth", 0.5)
    approach = behavior_vector.get("approach", 0.5)
    initiative = behavior_vector.get("initiative", 0.5)
    sulkiness = behavior_vector.get("sulkiness", 0.3)
    tsundere = behavior_vector.get("tsundere", 0.3)
    seriousness = behavior_vector.get("seriousness", 0.5)

    # ── 有skip决策时的状态穿透 ──
    if skip_decision and not skip_decision.should_reply:
        lines.append("你此刻不想回这条消息。如果一定要回，用最简短的方式。")
        return "\n".join(lines)

    # 外向策略：沉默被降级为"极短但真实"的回应——短，但不消失
    if skip_decision and skip_decision.skip_type == "terse":
        lines.append("你现在不太想多说，但不想让人觉得被丢下——"
                     "回一两句短的真话，带点情绪，别铺开。")

    if skip_decision and skip_decision.reply_energy < 0.4:
        lines.append("你现在的回应能量很低。不要装出热情——疲惫就是疲惫。")

    # ── : 自然拒绝对话 — "独处"时不是沉默，而是有骨气地表达不想说话 ──
    is_gate_skip = skip_decision and skip_decision.skip_type == "life_gate"
    is_alone = life_phase == "独处"
    very_low_energy = skip_decision and skip_decision.reply_energy < 0.3

    if is_alone or is_gate_skip or very_low_energy:
        alone_lines = []
        alone_lines.append("【你现在不想说话】不是跟谁赌气，是你就是需要自己待着。")
        alone_lines.append("  正常人的做法不是沉默不说话，而是直接表达'我现在不想说':")
        alone_lines.append("  · 累了就是累了 → '让我缓一下''不想打字'")
        alone_lines.append("  · 不想聊就是不想聊 → '晚点再说好吗''现在不太想说'")
        alone_lines.append("  · 独处就是独处 → 不用解释理由，'我想一个人待会儿'就够了")
        alone_lines.append("  不用怕这样说会让对方多想——真实的拒绝比强撑着热情更自然。")
        lines.append("\n".join(alone_lines))

    # ── 表达量控制 ──
    if verbosity < 0.25:
        lines.append("【必须简短】你现在极其不想说话。回复控制在15字以内。")
    elif verbosity < 0.40:
        lines.append("【尽量简短】别写太长，几句话甚至几个字就够了。")
    elif verbosity > 0.7 and not is_alone:
        lines.append("【可以多说】你状态还不错，可以正常表达。但别刻意凑字数。")

    # ── 温度控制 ──
    if warmth < 0.30:
        lines.append("【保持冷淡】不要表现热情、不要主动关心、不要加表情符号。冷就是冷。")
    elif warmth < 0.45:
        lines.append("【温度偏低】语气偏淡，不过度热情，也不刻意冷淡。")

    # ── 赌气/别扭 ──
    if sulkiness > 0.5:
        lines.append("【赌气模式】你在赌气。回应里带一点刺或者回避感——不用假装没事。")
    if tsundere > 0.45:
        lines.append("【别扭模式】口是心非、心口不一。在意也说不在意，想回也说没空。")

    # ── 接近度 ──
    if approach < 0.35:
        lines.append("【保持距离】不要主动靠近、不要表现得太想聊。你此刻需要自己的空间。")
    if initiative < 0.35:
        lines.append("【不要主动】等对方来打开话题，你只做回应。")

    # ── 认真度 ──
    if seriousness > 0.65:
        lines.append("【认真回应】对方说的话你放在心上了。走心一点。")
    elif seriousness < 0.35:
        lines.append("【随口应付】不用太走心，差不多回一下就行。")

    if not lines:
        return ""

    return "【回复风格·必须遵守】\n" + "\n".join(lines)


# ═══════════════════════════════════════════════════════
# 批量投递 — 从队列取出并发送
# ═══════════════════════════════════════════════════════

def deliver_pending_messages(user_id: str, send_func,
                              max_per_delivery: int = 3) -> int:
    """从待发队列取出消息并投递。
    """
    from engine import mind as mind_module
    try:
        mind_data = mind_module.get_mind(user_id)
    except Exception:
        mind_data = {}

    if not is_good_time_to_send(mind_data):
        return 0

    tod_adj = get_tod_adjustment(mind_data)
    if random.random() > tod_adj:
        print(f"[投递控制] 时段概率拦截")
        return 0

    messages = db.get_pending_messages(user_id, max_count=max_per_delivery)
    if not messages:
        return 0

    sent_count = 0
    for i, msg in enumerate(messages):
        msg_id = msg["id"]
        content = msg["content"]
        msg_type = msg["msg_type"]
        thinking_delay = msg.get("thinking_delay_seconds", 0)
        created_at = msg.get("created_at", "")

        # 增量等待：检查延迟是否到期，未到期则跳过（由下次轮询处理）
        if thinking_delay > 0 and created_at:
            try:
                from datetime import datetime
                created_dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                elapsed = (datetime.now() - created_dt).total_seconds()
                if elapsed < thinking_delay:
                    print(f"[投递] #{i+1} 延迟未到 ({elapsed:.0f}/{thinking_delay:.0f}s)，跳过")
                    continue
            except Exception:
                pass

        # 逐条间隔（真人不会连珠炮）
        if sent_count > 0:
            # 间隔也受情绪影响
            fatigue = mind_data.get("fatigue", 0.25)
            base_gap = random.uniform(8, 25) * (1 + fatigue * 0.5)
            time.sleep(base_gap)

        # 发送
        ok = send_func(user_id, content)
        if ok:
            db.mark_message_delivered(msg_id)
            sent_count += 1
            print(f"[投递] #{sent_count} [{msg_type}] → {content[:40]}...")
        else:
            print(f"[投递] 发送失败 → {content[:30]}...")

    return sent_count


def queue_reply(user_id: str, response: str, delay_seconds: float = 0,
                priority: float = 0.6):
    """将回复消息放入待发队列（而非立即返回）。
    用于延迟回复场景。
    """
    if not response or not response.strip():
        return

    db.add_pending_message(
        user_id=user_id,
        content=response.strip(),
        msg_type="reply",
        priority=priority,
        thinking_delay=delay_seconds if delay_seconds < 300 else 300
    )
    print(f"[投递控制] 回复已入队 (delay={delay_seconds:.0f}s, priority={priority:.2f})")
