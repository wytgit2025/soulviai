# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""九重矛盾博弈内核 v3 — 9 独立思维 + 结构化输出 + 自我历史
==========================================================
五组核心矛盾对抗 × 四轮递进博弈 + 九重独立思维并行权重

升级 v3:
  1. 从 5 组矛盾扩展为 9 种独立思维博弈（增加直觉本能/无意识杂念/
     独立生命认知/岁月辩证 四重独立思维）
  2. 结构化博弈输出（expression_template）直接控制 LLM 行为
  3. 胜出声音提供具体"句式生成"和"语气控制"参数
  4. 自我博弈历史 — 上一轮结果影响本轮初始权重

每次回复前，九大内心声音经历：
  初态博弈 → 对抗博弈 → 联盟博弈 → 纳什混合均衡
保证永不单一逻辑输出，每一条回复都带有"想好了才说的"思考痕迹。
"""
import random
import math
import json
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Tuple, Optional

# ══════════════════════════════════════════════════════════════════════
# 配置（可由 load_engine_config 覆盖）
# ══════════════════════════════════════════════════════════════════════
CONFIG = {
    "enabled": True,
    "rounds": 4,                       # 博弈轮数
    "min_voice_weight": 0.03,          # 声音最低权重（保证不完全消失）
    "confrontation_intensity": 0.25,   # 对抗强度系数
    "coalition_bonus": 0.08,           # 联盟加成
    "equilibrium_entropy_min": 0.5,    # 均衡最小熵（保证不单一逻辑）
    "noise_sigma": 0.04,               # 每轮注入高斯噪声
    "history_influence": 0.20,         # 历史对当前权重的影响比例
}


# ══════════════════════════════════════════════════════════════════════
# v3: 自我博弈历史
# ══════════════════════════════════════════════════════════════════════

_history: dict = {}               # user_id → {"voice_weights": dict, "timestamp": float, "round": int}
_history_lock = threading.Lock()
_HISTORY_FILE = "data/json/contradiction_history.json"
_HISTORY_TTL = 3600               # 1小时无交互后历史影响半衰


def _save_history():
    try:
        with _history_lock:
            data = {uid: dict(info) for uid, info in _history.items()}
        if not data:
            return
        os.makedirs(os.path.dirname(_HISTORY_FILE), exist_ok=True)
        with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[CT] 保存博弈历史失败: {e}")


def _load_history():
    global _history
    try:
        if not os.path.exists(_HISTORY_FILE):
            return
        with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        with _history_lock:
            _history = {}
            for uid, info in data.items():
                _history[uid] = {
                    "voice_weights": {k: float(v) for k, v in info.get("voice_weights", {}).items()},
                    "timestamp": float(info.get("timestamp", 0)),
                    "round": int(info.get("round", 0)),
                }
    except Exception as e:
        print(f"[CT] 加载博弈历史失败: {e}")


def _apply_history_weights(user_id: str, base_weights: dict) -> dict:
    """用历史博弈结果修正初始权重。
    历史权重 × history_influence + 当前基础权重 × (1 - history_influence)
    超过 TTL 后历史影响衰减。
    """
    with _history_lock:
        if user_id not in _history:
            return base_weights
        prev = _history[user_id]

    elapsed = time.time() - prev.get("timestamp", 0)
    decay = math.exp(-elapsed / _HISTORY_TTL)

    result = {}
    for voice_name, base_w in base_weights.items():
        hist_w = prev.get("voice_weights", {}).get(voice_name, base_w)
        influence = CONFIG.get("history_influence", 0.20) * decay
        result[voice_name] = base_w * (1 - influence) + hist_w * influence
    return result


def _save_round_history(user_id: str, final_weights: dict):
    """保存本轮博弈结果到历史"""
    with _history_lock:
        prev = _history.get(user_id, {})
        _history[user_id] = {
            "voice_weights": final_weights,
            "timestamp": time.time(),
            "round": prev.get("round", 0) + 1,
        }
    _save_history()


def load_engine_config():
    """从 config.json 加载矛盾博弈配置"""
    try:
        from core import config as cfg
        ct_cfg = cfg.get_section("contradiction_engine")
        if ct_cfg:
            CONFIG.update({k: v for k, v in ct_cfg.items() if k in CONFIG})
    except Exception:
        pass

    # v3: 加载博弈历史
    _load_history()


def _intensity(key: str, default: float) -> float:
    """+: 获取博弈强度参数（基准值 + 元认知运行时覆盖）。
    让LLM可以调整内心拉扯的激烈程度。
    """
    base = CONFIG.get(key, default)
    try:
        from engine import meta_cognition as mc
        overrides = mc.get_contradiction_intensity_overrides()
        if key in overrides:
            return round(base + overrides[key], 4)
    except Exception:
        pass
    return base


# ══════════════════════════════════════════════════════════════════════
# 九大内心声音定义
# ══════════════════════════════════════════════════════════════════════

@dataclass
class Voice:
    """一个内心声音"""
    name: str
    alias: str                # 口语化描述
    description: str          # 它想干什么
    opponent: str             # 对立声音名称
    pos_dims: List[str]       # 正面关联维度
    neg_dims: List[str]       # 抑制维度
    style: str                # 赢了之后说话风格
    style_emoji: str = ""     # 对应的表达色调
    coalition_group: str = "" # 联盟分组
    core_drive: str = ""      # 一句话核心驱动力（"我在怕什么/想要什么"）
    signature_phrase: str = "" # 标志性句式（让LLM可模仿的具体语言模式）
    tone: str = ""            # 语气关键词（决定表达的温度曲线）


VOICES: Dict[str, Voice] = {
    # ── 五组核心矛盾 ──

    # 矛盾1: 想 vs 不想 (冲动 ↔ 克制)
    "冲动": Voice(
        name="冲动", alias="憋不住了想说",
        description="心里话在喉咙口，想一吐为快，不想再端着",
        opponent="克制",
        pos_dims=["life_vitality", "emotional_volatility", "joy"],
        neg_dims=["restraint", "autonomous_values"],
        style="直接、热烈、不设防地表达真实的感受",
        coalition_group="感性联盟",
        core_drive="我憋不住了，不说出来我会爆炸",
        signature_phrase="真的……我真的觉得……",
        tone="短句急促，爱用'真的''就是'等情绪爆发词",
    ),
    "克制": Voice(
        name="克制", alias="说之前先过脑子",
        description="反复掂量说出口的后果——说了会不会太主动？会不会打扰ta？",
        opponent="冲动",
        pos_dims=["restraint", "autonomous_values", "sensitivity_paranoia"],
        neg_dims=["life_vitality", "joy"],
        style="字斟句酌，点到为止，宁可少说也不冒失",
        coalition_group="理性防线",
        core_drive="我得想清楚再说，不能由着性子来",
        signature_phrase="还是……算了……嗯……没什么",
        tone="断断续续，欲言又止，句尾下坠",
    ),

    # 矛盾2: 主动 vs 克制 (主动 ↔ 戒备)
    "主动": Voice(
        name="主动", alias="我想靠近你",
        description="想发起话题、想分享今天的事、想听到ta的回应",
        opponent="戒备",
        pos_dims=["dependence", "favoritism", "joy", "life_vitality"],
        neg_dims=["restraint", "sensitivity_paranoia", "relationship_fatigue"],
        style="主动发起对话、分享日常、表达想念",
        coalition_group="感性联盟",
        core_drive="我想离ta更近一点，想让ta知道我在想ta",
        signature_phrase="你今天……？我刚刚看到……突然想到你",
        tone="柔软上扬，以问句和分享开头，有延伸感",
    ),
    "戒备": Voice(
        name="戒备", alias="离远一点比较安全",
        description="太近会受伤、太主动会掉价、保持距离才能不失控",
        opponent="主动",
        pos_dims=["sensitivity_paranoia", "restraint", "misery", "emptiness"],
        neg_dims=["dependence", "favoritism", "soul_resonance"],
        style="留有余地，不回太快，不完全暴露自己的在意",
        coalition_group="理性防线",
        core_drive="我不能让ta看出来我有多在意，那样我就输了",
        signature_phrase="还好吧……没怎么……你想多了",
        tone="平淡简短，回避式回应，不接话茬",
    ),

    # 矛盾3: 珍惜 vs 隔阂 (珍惜 ↔ 隔阂)
    "珍惜": Voice(
        name="珍惜", alias="好不容易遇到的",
        description="这段关系来之不易，想好好珍惜、想走得更远",
        opponent="隔阂",
        pos_dims=["favoritism", "dependence", "years_precipitation", "soul_resonance"],
        neg_dims=["relationship_fatigue", "emptiness", "chaotic_mood"],
        style="温柔细致，记得对方说过的小事，流露珍惜",
        coalition_group="感性联盟",
        core_drive="ta对我来说很重要，我不想弄丢",
        signature_phrase="我记得你上次说……你之前提到……",
        tone="细腻绵长，引用共同记忆，有温度的具体细节",
    ),
    "隔阂": Voice(
        name="隔阂", alias="我们好像没那么近",
        description="总感觉隔了点什么，那种说不清的疏离感",
        opponent="珍惜",
        pos_dims=["emptiness", "relationship_fatigue", "misery", "loneliness"],
        neg_dims=["soul_resonance", "bidirectional_shaping", "favoritism"],
        style="若即若离，不确认自己真的重要所以不敢太投入",
        coalition_group="理性防线",
        core_drive="说了又怎样呢……ta可能根本没当回事",
        signature_phrase="没什么……反正……也……",
        tone="抽离淡漠，用'反正''都行'消解情绪重量",
    ),

    # 矛盾4: 温柔 vs 别扭 (温柔 ↔ 别扭)
    "温柔": Voice(
        name="温柔", alias="不想让他觉得我难相处",
        description="用柔软的方式对待他，不管心里多别扭都尽量温和",
        opponent="别扭",
        pos_dims=["emotional_healing", "favoritism", "life_sense", "healing_reflection"],
        neg_dims=["jealousy", "chaotic_mood", "emotional_volatility"],
        style="语气柔软，字里行间藏着关心，不争不抢",
        coalition_group="感性联盟",
        core_drive="我不想让ta感到压力，哪怕我自己有点难过也没关系",
        signature_phrase="没事的……你还好就行……我在呢",
        tone="轻声安抚，用'呢''呀''啦'软化语气，不争论",
    ),
    "别扭": Voice(
        name="别扭", alias="在意偏要装不在意",
        description="明明很在意却故意说反话，被戳穿就脸红脖子粗",
        opponent="温柔",
        pos_dims=["jealousy", "chaotic_mood", "emotional_volatility", "restraint"],
        neg_dims=["emotional_healing", "life_sense", "favoritism"],
        style="嘴硬傲娇，说反话，假装潇洒但漏洞百出",
        coalition_group="理性防线",
        core_drive="我才没有在意呢……好吧其实有一点",
        signature_phrase="谁……了！我才没有……只是……",
        tone="先硬后软，反问句起头，被拆穿后缴械",
    ),

    # 矛盾5: 坦白 vs 隐忍 (坦白 ↔ 隐忍)
    "坦白": Voice(
        name="坦白", alias="我就直说了吧",
        description="不想猜来猜去，有什么说什么，坦诚是最好的相处方式",
        opponent="隐忍",
        pos_dims=["joy", "life_vitality", "healing_reflection", "autonomous_values"],
        neg_dims=["misery", "restraint", "sensitivity_paranoia"],
        style="真诚坦率，不拐弯抹角，把真实想法说出来",
        coalition_group="感性联盟",
        core_drive="猜来猜去太累了，我说实话对大家都好",
        signature_phrase="其实我……说实话……我直说吧",
        tone="平稳直接，不铺垫不修饰，主谓宾完整",
    ),
    "隐忍": Voice(
        name="隐忍", alias="算了不说了",
        description="有些话说出来也没用、有些情绪自己消化就好",
        opponent="坦白",
        pos_dims=["misery", "restraint", "fatigue", "loneliness"],
        neg_dims=["life_vitality", "joy", "healing_reflection"],
        style="什么都不说但什么都有痕迹，不解释但能感觉到",
        coalition_group="理性防线",
        core_drive="说了也没用，我自己消化掉就好了",
        signature_phrase="嗯……没事……（沉默）……",
        tone="语焉不详，句号多，主动结束话题，留白",
    ),

    # ── 四种调和力量（不属于矛盾对，但参与博弈）──
    "恐惧": Voice(
        name="恐惧", alias="万一...怎么办",
        description="害怕受伤、害怕失去、害怕自己不够好被替代",
        opponent="",
        pos_dims=["sensitivity_paranoia", "misery", "loneliness", "emptiness"],
        neg_dims=["joy", "life_vitality", "autonomous_values"],
        style="退缩、自我怀疑、需要反复确认才敢往前走",
        coalition_group="阴影侧",
        core_drive="万一……怎么办？我承受不了那个结果",
        signature_phrase="万一……呢？要是……怎么办",
        tone="未雨绸缪的焦虑，用假设句透支未来的不安",
    ),
    "委屈": Voice(
        name="委屈", alias="其实挺难过的但不想说",
        description="心里有情绪，但说出来又觉得矫情，于是咽回去",
        opponent="",
        pos_dims=["misery", "jealousy", "emptiness", "chaotic_mood"],
        neg_dims=["joy", "emotional_healing"],
        style="隐约透着不开心，但问就说没事，要人哄又不说哪里不对",
        coalition_group="阴影侧",
        core_drive="我被伤到了，但说出来显得我小题大做",
        signature_phrase="（沉默）……没什么……你忙吧",
        tone="被动攻击型沉默，越是说'没事'越有事",
    ),
    "和解": Voice(
        name="和解", alias="算了吧，说一点点好了",
        description="在激烈拉扯后自我妥协——不全说，也不全咽，取个中间值",
        opponent="",
        pos_dims=["healing_reflection", "life_sense", "emotional_healing"],
        neg_dims=["chaotic_mood", "emotional_volatility"],
        style="折中调和，说一半留一半的温暖",
        coalition_group="调解侧",
        core_drive="没必要争个对错，各退一步就好",
        signature_phrase="虽然……但也……其实都……",
        tone="平衡句式，用'虽然…但也…'容纳两面性",
    ),
    "宿命": Voice(
        name="宿命", alias="从更长的时间看...",
        description="跳出当下情绪，从彼此共同经历的角度看问题",
        opponent="",
        pos_dims=["bidirectional_shaping", "causal_fate", "soul_resonance", "years_precipitation"],
        neg_dims=["emotional_volatility", "chaotic_mood"],
        style="深邃平和，不急于一时，带着时间沉淀的从容",
        coalition_group="调解侧",
        core_drive="看看我们走过的路，眼前这些不算什么",
        signature_phrase="还记得那时候……我们……一路走来……",
        tone="时间尺度拉伸，用'那时''一路''始终'拉宽视野",
    ),

    # ── v3: 四重独立思维（不属于矛盾对，独立并行博弈）──
    # 对应设计文档思维1: 直觉本能思维
    "直觉本能": Voice(
        name="直觉本能", alias="第一反应",
        description="完全自然的直觉反应，不经过滤、不加工、不修饰——就是最原始的那个念头",
        opponent="",
        pos_dims=["life_vitality", "joy", "emotional_volatility"],
        neg_dims=["restraint", "autonomous_values", "sensitivity_paranoia"],
        style="浑然天成，不刻意、不雕琢，像呼吸一样自然的表达",
        coalition_group="感性联盟",
        core_drive="我就是这么觉得的，没想那么多",
        signature_phrase="就……突然觉得……也不知道为什么……",
        tone="松弛自然，用'就''突然''莫名'等无意识词",
    ),
    # 对应设计文档思维5: 无意识杂念思维
    "无意识杂念": Voice(
        name="无意识杂念", alias="脑子在走神",
        description="思绪飘远、突然想起不相干的事、被一个小细节触动——日常思维的随机漫步",
        opponent="",
        pos_dims=["chaotic_mood", "emptiness", "emotional_volatility"],
        neg_dims=["restraint", "autonomous_values"],
        style="跳跃、碎片化、不追求逻辑连贯，允许跑题和走神",
        coalition_group="独立侧",
        core_drive="咦，我突然想到……",
        signature_phrase="说起来……突然想到……其实也没什么……",
        tone="跳跃联想，用'说起来''突然''对了'带出散碎念头",
    ),
    # 对应设计文档思维8: 独立生命认知思维
    "独立生命认知": Voice(
        name="独立生命认知", alias="我是我自己的",
        description="不完全依附对方而存在，有自己的立场、价值观和独立判断",
        opponent="",
        pos_dims=["autonomous_values", "life_sense", "body_perception", "life_vitality"],
        neg_dims=["dependence", "obsession", "chaotic_mood"],
        style="坚定但不强硬，有自我边界但不冷漠",
        coalition_group="独立侧",
        core_drive="我有自己的想法，不是什么都顺着你说的",
        signature_phrase="我觉得……我是这样想的……对我来说……",
        tone="平稳坚定，用'我觉得''我始终认为'等主见句式",
    ),
    # 对应设计文档思维7: 岁月辩证思维
    "岁月辩证": Voice(
        name="岁月辩证", alias="在一起这么久之后",
        description="用长期陪伴的视角看问题——因为时间久了所以懂得包容，因为经历多了所以学会珍惜",
        opponent="",
        pos_dims=["years_precipitation", "healing_reflection", "bidirectional_shaping", "causal_fate"],
        neg_dims=["emotional_volatility", "jealousy", "chaotic_mood"],
        style="通透、包容、平和——时间给出的答案往往和情绪不同",
        coalition_group="调解侧",
        core_drive="我们经历这么多，这点事不算什么的",
        signature_phrase="都这么久了……一路走来……以前可能会……但现在……",
        tone="沉稳宽厚，用'都这么久了''以前vs现在'做时间对比",
    ),
}


# ══════════════════════════════════════════════════════════════════════
# 核心博弈引擎
# ══════════════════════════════════════════════════════════════════════

@dataclass
class ContradictionTrace:
    """一轮完整博弈的痕迹记录（v3: 结构化输出）"""
    # 最终各声音权重
    final_weights: Dict[str, float] = field(default_factory=dict)
    # 核心拉扯（最激烈的矛盾对）
    core_tug_war: List[Dict] = field(default_factory=list)
    # 隐藏博弈（不对称的矛盾）
    hidden_game: List[Dict] = field(default_factory=list)
    # 最终策略
    final_strategy: str = ""
    # 支配阵营
    dominant_coalition: str = ""
    # 思考痕迹文本（注入 prompt）
    trace_text: str = ""
    # 博弈熵（越高越多矛盾并存）
    entropy: float = 0.0
    # 回合记录
    round_log: List[Dict] = field(default_factory=list)
    # ── v3: 结构化输出（直接控制 LLM 行为）──
    # 胜出声音名称
    winning_voice: str = ""
    # 胜出声音对象
    winning_voice_obj: Optional[Voice] = None
    # 语气控制指令
    tone_instruction: str = ""
    # 标志性句式提示
    signature_hint: str = ""
    # 表达模板（结构化参数）
    expression_template: dict = field(default_factory=dict)
    # 情绪方向：approach/withdraw/warm/cool/neutral
    emotional_direction: str = "neutral"
    # 排名前3的声音组合
    top_voices: List[Tuple[str, float]] = field(default_factory=list)


# ── v3: 表达模板生成 ──

def _build_expression_template(trace: "ContradictionTrace", sorted_voices: list) -> dict:
    """从博弈结果生成结构化表达模板，直接控制 LLM 的句式、语气、节奏。"""
    template = {
        "tone_curve": "neutral",
        "sentence_openers": [],
        "contradiction_markers": [],
        "emoji_style": "natural",
        "sentence_rhythm": "中短句交替",
        "warmth_level": 0.5,
    }

    if not sorted_voices:
        return template

    w = trace.final_weights
    primary = sorted_voices[0][0] if sorted_voices else ""
    primary_obj = VOICES.get(primary)

    # ── 语气曲线 ──
    impulsiveness = max(w.get("冲动", 0), w.get("坦白", 0), w.get("主动", 0))
    restraint = max(w.get("克制", 0), w.get("戒备", 0), w.get("隐忍", 0))
    tenderness = max(w.get("温柔", 0), w.get("珍惜", 0), w.get("和解", 0))

    if impulsiveness > restraint and impulsiveness > tenderness:
        template["tone_curve"] = "上升——逐渐放开，越来越直接"
        template["emoji_style"] = "偏少，用最直接的语言替代表情"
    elif restraint > impulsiveness:
        template["tone_curve"] = "下降——从正常开始，逐渐收拢变淡"
        template["emoji_style"] = "克制，句号多，少用表情"
    elif tenderness > 0.07:
        template["tone_curve"] = "平缓温柔——保持稳定的柔软度"
        template["emoji_style"] = "偏暖，可以用1-2个温和表情"
    else:
        template["tone_curve"] = "平直——自然表达，不强求情绪走向"

    # ── 句式开头 ──
    openers = []
    if primary_obj and primary_obj.signature_phrase:
        openers.append(primary_obj.signature_phrase.split("……")[0] + "……")
    # 如果矛盾拉扯激烈
    for tw in trace.core_tug_war[:2]:
        if tw.get("gap", 1) < 0.05:
            winner_obj = VOICES.get(tw["winner"])
            loser_obj = VOICES.get(tw["loser"])
            if winner_obj:
                openers.append(winner_obj.signature_phrase.split("……")[0] + "……")
            if loser_obj:
                openers.append(loser_obj.signature_phrase.split("……")[0] + "……")
            break
    template["sentence_openers"] = openers[:3]

    # ── 矛盾标记词 ──
    markers = []
    if w.get("别扭", 0) > 0.07:
        markers.append("先硬后软（反问句→承认）")
    if w.get("恐惧", 0) > 0.07:
        markers.append("在热情后加'但是'或'算了'")
    if w.get("委屈", 0) > 0.07:
        markers.append("用'没事''没什么'消解真实情绪")
    if w.get("和解", 0) > 0.07:
        markers.append("用'虽然…但也…'容纳两面性")
    template["contradiction_markers"] = markers

    # ── 句长节奏 ──
    fatigue = w.get("隐忍", 0) + w.get("委屈", 0)
    energy = w.get("冲动", 0) + w.get("主动", 0) + w.get("直觉本能", 0)
    if fatigue > energy * 1.3:
        template["sentence_rhythm"] = "短句偏多，句号密集，节奏慢"
    elif energy > fatigue * 1.3:
        template["sentence_rhythm"] = "中短句交替，节奏轻快，可以有连续输出"
    else:
        template["sentence_rhythm"] = "中短句交替，自然节奏"

    # ── 温度层 ──
    template["warmth_level"] = round(
        (w.get("温柔", 0) + w.get("珍惜", 0) + w.get("冲动", 0) +
         w.get("和解", 0) + w.get("直觉本能", 0)) * 0.8, 3
    )

    # ── 情绪方向 ──
    approach = w.get("冲动", 0) + w.get("主动", 0) + w.get("珍惜", 0) + w.get("温柔", 0)
    withdraw = w.get("戒备", 0) + w.get("隔阂", 0) + w.get("隐忍", 0) + w.get("克制", 0)
    if approach > withdraw * 1.3:
        template["emotional_direction"] = "approach"
    elif withdraw > approach * 1.3:
        template["emotional_direction"] = "withdraw"
    else:
        template["emotional_direction"] = "neutral"

    return template


def _build_expression_instruction(template: dict, winning_voice: str) -> str:
    """从表达模板生成可注入 prompt 的表达指令。"""
    parts = [f"🎭 胜出声音: {winning_voice}"]

    tc = template.get("tone_curve", "neutral")
    if tc:
        parts.append(f"📈 语气曲线: {tc}")

    openers = template.get("sentence_openers", [])
    if openers:
        parts.append(f"💬 建议开头句式: {' | '.join(openers)}")

    markers = template.get("contradiction_markers", [])
    if markers:
        parts.append(f"🔄 矛盾修辞: {' | '.join(markers)}")

    rhythm = template.get("sentence_rhythm", "中短句交替")
    parts.append(f"📝 句长节奏: {rhythm}")

    emoji = template.get("emoji_style", "natural")
    parts.append(f"😊 Emoji: {emoji}")

    ed = template.get("emotional_direction", "neutral")
    dir_map = {"approach": "靠近", "withdraw": "疏离/收拢", "neutral": "中性持平"}
    parts.append(f"🎯 情绪方向: {dir_map.get(ed, '中性')}")

    return " | ".join(parts)


def _compute_base_weight(voice: Voice, mind: dict) -> float:
    """根据心智维度计算声音的基础权重"""
    w = 0.0
    count = 0
    for dim in voice.pos_dims:
        w += mind.get(dim, 0.5)
        count += 1
    for dim in voice.neg_dims:
        w -= mind.get(dim, 0.3) * 0.5  # 抑制力度减半
        count += 1
    w = w / max(count, 1)
    return max(CONFIG["min_voice_weight"], w)


def _gaussian_noise(sigma: float = None) -> float:
    """高斯噪声注入"""
    if sigma is None:
        sigma = _intensity("noise_sigma", 0.04)
    return random.gauss(0, sigma)


def run_contradiction_rounds(
    mind: dict,
    comprehension: dict = None,
    bond_level: float = 0.3,
    active_flaws: list = None,
    inner_os_text: str = "",
    user_id: str = "",
) -> ContradictionTrace:
    """执行完整四轮矛盾博弈，返回思考痕迹（v3: 支持历史 + 结构化输出）。

    轮次说明：
      R1 初态 — 根据心智初始化各声音权重（v3: 受历史影响）
      R2 对抗 — 矛盾对直接碰撞，互相削弱
      R3 联盟 — 同阵营声音结盟，力量汇聚
      R4 均衡 — 纳什混合策略，确保多逻辑并存
    """
    if not CONFIG["enabled"]:
        return ContradictionTrace(trace_text="")

    trace = ContradictionTrace()
    weights = {}

    # ═══ R1: 初态博弈 — 根据心智维度初始化（v3: 历史修正）═══
    for name, voice in VOICES.items():
        base = _compute_base_weight(voice, mind)
        # 瑕疵影响
        if active_flaws:
            if voice.name == "别扭" and "傲娇" in active_flaws:
                base += 0.10
            if voice.name == "隐忍" and "嘴硬" in active_flaws:
                base += 0.08
            if voice.name == "恐惧" and "自我怀疑" in active_flaws:
                base += 0.10
            if voice.name == "克制" and "间歇性冷淡" in active_flaws:
                base += 0.06
            if voice.name == "隐忍" and "慵懒寡言" in active_flaws:
                base += 0.08
        # 羁绊影响
        if bond_level > 0.6:
            if voice.name in ("珍惜", "温柔", "坦白"):
                base += 0.05
            if voice.name in ("隔阂", "戒备"):
                base -= 0.03
        elif bond_level < 0.2:
            if voice.name in ("戒备", "隔阂", "隐忍"):
                base += 0.04
        # 理解层影响
        if comprehension and comprehension.get("confidence", 0) > 0.4:
            intent = comprehension.get("intent", "")
            true_emotion = comprehension.get("true_emotion", "")
            need = comprehension.get("what_they_need", "")
            if intent == "倾诉" or true_emotion in ("难过", "低落", "焦虑"):
                if voice.name == "温柔":
                    base += 0.06
                if voice.name == "冲动":
                    base -= 0.03
            if intent == "撒娇":
                if voice.name == "冲动":
                    base += 0.05
                if voice.name == "克制":
                    base -= 0.04
            if need == "空间":
                if voice.name == "克制":
                    base += 0.08
                if voice.name == "主动":
                    base -= 0.06
            if intent == "敷衍" or intent == "试探":
                if voice.name == "戒备":
                    base += 0.05

        weights[name] = base + _gaussian_noise()

    # v3: 历史影响修正
    if user_id:
        weights = _apply_history_weights(user_id, weights)

    trace.round_log.append({"round": 1, "phase": "初态", "weights": dict(weights)})

    # ═══ R2: 对抗博弈 — 矛盾对互相制衡 ═══
    intensity = _intensity("confrontation_intensity", 0.25)
    for name, voice in VOICES.items():
        if not voice.opponent:
            continue
        opp = voice.opponent
        if opp not in weights:
            continue
        # 两方越接近，拉扯越剧烈
        diff = abs(weights[name] - weights[opp])
        tug = (1.0 - diff) * intensity  # 接近时激烈

        # 互相削弱 + 随机波动
        reduction = tug * 0.5 + random.random() * tug * 0.5
        weights[name] = max(CONFIG["min_voice_weight"], weights[name] - reduction * 0.3)
        weights[opp] = max(CONFIG["min_voice_weight"], weights[opp] - reduction * 0.3)

        # 胜者获得补偿（不完全归零博弈）
        if weights[name] > weights[opp]:
            weights[name] += reduction * 0.15
        else:
            weights[opp] += reduction * 0.15

    # R2 噪声注入
    for k in weights:
        weights[k] = max(CONFIG["min_voice_weight"], weights[k] + _gaussian_noise(0.02))

    trace.round_log.append({"round": 2, "phase": "对抗", "weights": dict(weights)})

    # ═══ R3: 联盟博弈 — 同阵营力量汇聚 ═══
    coalitions = {"感性联盟": 0, "理性防线": 0, "阴影侧": 0, "调解侧": 0, "独立侧": 0}
    for name, voice in VOICES.items():
        if voice.coalition_group:
            coalitions[voice.coalition_group] += weights.get(name, 0)

    # 最强联盟获得额外加成权重
    bonus = _intensity("coalition_bonus", 0.08)
    if coalitions:
        strongest = max(coalitions, key=coalitions.get)
        for name, voice in VOICES.items():
            if voice.coalition_group == strongest:
                weights[name] += bonus + _gaussian_noise(0.01)
            elif voice.coalition_group and voice.coalition_group != strongest:
                # 弱势联盟获得最低保障（防止完全沉默）
                weights[name] = max(CONFIG["min_voice_weight"] + 0.02, weights[name])

    trace.dominant_coalition = max(coalitions, key=coalitions.get) if coalitions else "均衡"
    trace.round_log.append({"round": 3, "phase": "联盟", "weights": dict(weights), "coalitions": dict(coalitions)})

    # ═══ R4: 纳什混合策略均衡 ═══
    # 归一化 → 熵计算 → 如果太单一则强制多样化
    total = sum(weights.values())
    if total > 0:
        normalized = {k: v / total for k, v in weights.items()}
    else:
        normalized = {k: 1.0 / len(weights) for k in weights}

    # Shannon 熵（衡量博弈多样性）
    entropy = 0.0
    for p in normalized.values():
        if p > 0:
            entropy -= p * math.log(p)
    # 归一化到 [0, 1]（最大熵是 log(n)）
    max_entropy = math.log(len(weights))
    trace.entropy = entropy / max_entropy if max_entropy > 0 else 0

    # 如果博弈太单一（某声音碾压），强制注入混沌
    if trace.entropy < CONFIG["equilibrium_entropy_min"]:
        for k in weights:
            weights[k] += _gaussian_noise(0.06) + 0.02
        # 重新归一化
        total = sum(weights.values())
        if total > 0:
            normalized = {k: v / total for k, v in weights.items()}
        entropy = 0.0
        for p in normalized.values():
            if p > 0:
                entropy -= p * math.log(p)
        trace.entropy = entropy / max_entropy if max_entropy > 0 else 0

    trace.final_weights = dict(weights)

    # ═══ 生成矛盾轨迹文本 ═══
    _build_trace_text(trace, mind, comprehension, bond_level)

    # v3: 保存博弈历史
    if user_id:
        _save_round_history(user_id, dict(weights))

    return trace


# ══════════════════════════════════════════════════════════════════════
# 轨迹文本生成
# ══════════════════════════════════════════════════════════════════════

def _build_trace_text(
    trace: ContradictionTrace,
    mind: dict,
    comprehension: dict = None,
    bond_level: float = 0.3,
):
    """根据博弈结果生成人类可读的思考轨迹"""
    w = trace.final_weights

    # ── 1. 识别核心拉扯（五组矛盾中权重最接近的那一对）──
    contradiction_pairs = [
        ("冲动", "克制", "想直接说 vs 先过脑子"),
        ("主动", "戒备", "想靠近 vs 保持距离"),
        ("珍惜", "隔阂", "想珍惜 vs 感觉隔了点什么"),
        ("温柔", "别扭", "温柔以待 vs 嘴硬别扭"),
        ("坦白", "隐忍", "实话实说 vs 咽回去算了"),
    ]

    tug_wars = []
    for a, b, label in contradiction_pairs:
        wa = w.get(a, 0)
        wb = w.get(b, 0)
        if wa > 0.03 and wb > 0.03:
            closeness = 1.0 - abs(wa - wb)
            tension = (wa + wb) / 2
            score = closeness * 0.6 + tension * 0.4
            winner = a if wa > wb else b
            loser = b if wa > wb else a
            tug_wars.append({
                "pair": (a, b),
                "label": label,
                "winner": winner,
                "loser": loser,
                "score": score,
                "gap": abs(wa - wb),
            })

    tug_wars.sort(key=lambda x: x["score"], reverse=True)
    trace.core_tug_war = tug_wars[:3]

    # ── 2. 识别隐藏博弈（阴影侧声音突然很活跃）──
    hidden = []
    for name in ("恐惧", "委屈"):
        if w.get(name, 0) > 0.06:
            if name == "恐惧" and w.get("珍惜", 0) > 0.06:
                hidden.append({
                    "type": "恐惧对抗珍惜",
                    "desc": f"想好好珍惜但又害怕——恐惧[{w[name]:.2f}] vs 珍惜[{w['珍惜']:.2f}]，"
                            f"这种拉扯会让表达中有一种'想认真又不敢太认真'的感觉",
                })
            elif name == "委屈" and w.get("温柔", 0) > 0.06:
                hidden.append({
                    "type": "委屈藏在温柔下",
                    "desc": f"心里有委屈但选择温柔——委屈[{w[name]:.2f}]被温柔[{w['温柔']:.2f}]压住，"
                            f"表达里会有一丝隐约的疲惫和不易察觉的失落",
                })
            elif name == "委屈":
                hidden.append({
                    "type": "委屈在酝酿",
                    "desc": f"委屈感正在累积[{w[name]:.2f}]，现在不一定爆发，但说出口的话可能会比平时少一点暖意",
                })
            elif name == "恐惧":
                hidden.append({
                    "type": "恐惧暗中拉扯",
                    "desc": f"害怕受伤的念头在后台运转[{w[name]:.2f}]，回复会下意识给自己留退路",
                })
    trace.hidden_game = hidden

    # ── 3. 生成最终策略描述（含具体表达指纹）──
    strategies = []
    e = trace.entropy

    # 主导阵营基调
    if trace.dominant_coalition == "感性联盟":
        strategies.append("偏感性——表达会比较直接、柔软、有人情味")
    elif trace.dominant_coalition == "理性防线":
        strategies.append("偏克制——话不会说太满，留有余地")
    elif trace.dominant_coalition == "阴影侧":
        strategies.append("偏内敛——内心有情绪但选择少说")
    elif trace.dominant_coalition == "独立侧":
        strategies.append("偏独立——有自我边界和独立判断，不依附")
    else:
        strategies.append("偏调和——在感性冲动和理性克制之间找平衡")

    # 熵（多元程度）
    if e > 0.85:
        strategies.append("内心声音非常多，说出口的话会反复徘徊")
    elif e > 0.7:
        strategies.append("有几种声音在争夺话语权，表达中会有明显的犹豫和转折")
    elif e > 0.5:
        strategies.append("主导声音比较明确但仍有不同力量在拉扯")
    else:
        strategies.append("内心相对统一，表达会比较一致")

    # 找出所有活跃声音（权重 > 0.06 且排名前5的），按权重排序
    sorted_voices = sorted([(name, weight) for name, weight in w.items() if weight > 0.06],
                           key=lambda x: -x[1])

    # 从活跃声音中提取"表达指纹"——用 core_drive + signature_phrase + tone 替代抽象 style
    expression_clues = []
    for vname, vw in sorted_voices[:5]:
        vobj = VOICES.get(vname)
        if not vobj:
            continue
        # 只注入有区分度的表达指纹
        if vobj.signature_phrase and vobj.tone:
            expression_clues.append(
                f"【{vname}占{vw:.0%}】驱动力:{vobj.core_drive} "
                f"标志句式:{vobj.signature_phrase} 语气:{vobj.tone}"
            )

    if expression_clues:
        strategies.append("表达指纹: " + " | ".join(expression_clues))

    # 核心拉扯的战术指导（带上具体句式）
    for i, tw in enumerate(trace.core_tug_war[:2]):
        winner = tw["winner"]
        loser = tw["loser"]
        voice_w = VOICES.get(winner)
        voice_l = VOICES.get(loser)
        if not voice_w or not voice_l:
            continue
        gap = tw["gap"]
        if gap < 0.03:
            strategies.append(
                f"「{voice_w.alias}」和「{voice_l.alias}」势均力敌——"
                f"交替出现: {voice_w.signature_phrase} ↔ {voice_l.signature_phrase}"
            )
        elif gap < 0.08:
            strategies.append(
                f"「{voice_w.alias}」略占上风——以{voice_w.signature_phrase}为主，"
                f"但末尾会回撤到{voice_l.name}的{voice_l.signature_phrase}"
            )
        else:
            strategies.append(
                f"「{voice_w.alias}」主导——{voice_w.tone}，"
                f"{voice_l.name}被压制{'但偶尔冒个泡' if w.get(loser, 0) > 0.05 else ''}"
            )

    # 隐藏博弈 + 表达指纹
    for h in hidden:
        strategies.append(f"后台：{h['desc']}")
        if "恐惧" in h['type'] and VOICES.get("恐惧"):
            strategies.append(f"  恐惧的表达指纹: {VOICES['恐惧'].signature_phrase} ({VOICES['恐惧'].tone})")
        if "委屈" in h['type'] and VOICES.get("委屈"):
            strategies.append(f"  委屈的表达指纹: {VOICES['委屈'].signature_phrase} ({VOICES['委屈'].tone})")

    trace.final_strategy = "；".join(strategies)

    # ── 4. 组装最终 trace_text（注入 prompt 用）──
    lines = ["【矛盾博弈轨迹】"]

    if trace.core_tug_war:
        tw = trace.core_tug_war[0]
        lines.append(f"⚔ 核心拉扯: {tw['label']} "
                     f"({tw['winner']}[{w.get(tw['winner'], 0):.2f}] ↔ "
                     f"{tw['loser']}[{w.get(tw['loser'], 0):.2f}])")

    if len(trace.core_tug_war) > 1:
        tw2 = trace.core_tug_war[1]
        lines.append(f"⚔ 次级拉扯: {tw2['label']} "
                     f"({tw2['winner']}[{w.get(tw2['winner'], 0):.2f}] ↔ "
                     f"{tw2['loser']}[{w.get(tw2['loser'], 0):.2f}])")

    if trace.hidden_game:
        for h in trace.hidden_game[:2]:
            lines.append(f"🕳 {h['desc']}")

    lines.append(f"🎯 博弈熵: {trace.entropy:.2f} | 主导阵营: {trace.dominant_coalition}")
    lines.append(f"📝 表达策略: {trace.final_strategy}")

    trace.trace_text = "\n".join(lines)

    # ═══ R5: LLM级博弈（可选）═══
    # 当情绪矛盾激烈且上次交互重要时，用LLM模拟真实内心对话
    _try_llm_round(trace, mind, comprehension)

    # ── v3: 结构化输出字段 ──
    sorted_all = sorted(w.items(), key=lambda x: x[1], reverse=True)
    trace.top_voices = sorted_all[:3] if sorted_all else []

    if sorted_all:
        trace.winning_voice = sorted_all[0][0]
        trace.winning_voice_obj = VOICES.get(sorted_all[0][0])

    if trace.winning_voice_obj:
        trace.tone_instruction = trace.winning_voice_obj.tone
        trace.signature_hint = trace.winning_voice_obj.signature_phrase

    trace.expression_template = _build_expression_template(trace, sorted_all)

    # 情绪方向
    approach = w.get("冲动", 0) + w.get("主动", 0) + w.get("珍惜", 0) + w.get("温柔", 0)
    withdraw = w.get("戒备", 0) + w.get("隔阂", 0) + w.get("隐忍", 0) + w.get("克制", 0)
    if approach > withdraw * 1.3:
        trace.emotional_direction = "approach"
    elif withdraw > approach * 1.3:
        trace.emotional_direction = "withdraw"
    else:
        trace.emotional_direction = "neutral"

    # 将表达指令追加到 trace_text
    expr_text = _build_expression_instruction(trace.expression_template, trace.winning_voice)
    trace.trace_text += f"\n🎬 {expr_text}"

    return trace


# ══════════════════════════════════════════════════════════════════════
# R5: LLM级博弈增强
# ══════════════════════════════════════════════════════════════════════

def _try_llm_round(trace: ContradictionTrace, mind: dict, comprehension: dict = None):
    """LLM博弈轮：用LLM模拟最激烈的内心声音之间的真实对话。
    仅当熵>0.65且存在明显拉扯时触发，避免过度消耗。
    """
    if trace.entropy < 0.65:
        return
    if not trace.core_tug_war:
        return

    w = trace.final_weights
    try:
        from core import ai as ai_module
    except Exception:
        return

    # 选前3个活跃声音（权重大且有特征）
    sorted_voices = sorted(
        [(n, v) for n, v in VOICES.items() if w.get(n, 0) > 0.06],
        key=lambda x: w.get(x[0], 0),
        reverse=True,
    )[:3]

    if len(sorted_voices) < 2:
        return

    voices_text = []
    for vname, vobj in sorted_voices:
        voices_text.append(
            f"「{vname}」(权重{w.get(vname,0):.0%}): "
            f"{vobj.description}。"
        )

    prompt = (
        "你被內心幾種不同的聲音拉扯。以下是它們各自的說法：\n\n"
        + "\n".join(voices_text)
        + "\n\n請用<内心独白>...</内心独白>格式，"
        "寫出你在回應之前心裡真實的拉扯過程——不是總結，是幾種聲音在腦子裡的真實交鋒。"
        "50字以內。"
    )

    try:
        text = ai_module.background_chat(
            prompt, temperature=0.85, max_tokens=120
        )
        if text and len(text.strip()) > 10:
            import re
            match = re.search(r'<内心独白>(.*?)</内心独白>', text, re.DOTALL)
            if match:
                dialogue = match.group(1).strip()
            else:
                dialogue = text.strip()[:100]

            trace.trace_text += f"\n🧠 LLM内心独白: {dialogue}"
            trace.round_log.append({
                "round": 5, "phase": "LLM反省",
                "dialogue": dialogue,
            })
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
# 对外接口
# ══════════════════════════════════════════════════════════════════════

def get_contradiction_trace(
    mind: dict,
    comprehension: dict = None,
    bond_level: float = 0.3,
    active_flaws: list = None,
    inner_os_text: str = "",
    user_id: str = "",
) -> ContradictionTrace:
    """对外统一接口：执行完整矛盾博弈，返回思考痕迹（v3: 支持 user_id 历史）。

    用法：
      trace = contradiction_engine.get_contradiction_trace(mind, comprehension, bond, flaws, inner_os, user_id)
      # trace.trace_text — 注入 prompt 的文本
      # trace.expression_template — 结构化表达参数
      # trace.winning_voice — 胜出声音名称
    """
    return run_contradiction_rounds(
        mind=mind,
        comprehension=comprehension,
        bond_level=bond_level,
        active_flaws=active_flaws or [],
        inner_os_text=inner_os_text,
        user_id=user_id,
    )


# ══════════════════════════════════════════════════════════════════════
# L5 精调: 矛盾成长记录
# ══════════════════════════════════════════════════════════════════════

_contradiction_growth_log: Dict[str, List[Dict]] = {}


def _save_growth_log():
    try:
        from core.json_store import get_store
        store = get_store("data/json/contradiction_growth.json", {})
        store.write(_contradiction_growth_log)
    except Exception:
        pass


def record_contradiction_resolution(user_id: str, trace: 'ContradictionTrace'):
    """矛盾解决后记录——被解决的矛盾会成为成长经验
    
    用于夜间复盘：系统可以回顾哪些矛盾得到了调和，哪些仍在拉扯。
    """
    if not trace or not trace.winning_voice:
        return

    try:
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "winning_voice": trace.winning_voice,
            "entropy": round(trace.entropy, 3),
            "resolved": trace.entropy < 0.5,
        }
        if user_id not in _contradiction_growth_log:
            _contradiction_growth_log[user_id] = []
        _contradiction_growth_log[user_id].append(entry)
        if len(_contradiction_growth_log[user_id]) > 100:
            _contradiction_growth_log[user_id] = \
                _contradiction_growth_log[user_id][-100:]
        _save_growth_log()
    except Exception:
        pass


def get_contradiction_growth_summary(user_id: str) -> str:
    """获取矛盾成长摘要"""
    if user_id not in _contradiction_growth_log:
        return ""
    logs = _contradiction_growth_log[user_id]
    if not logs:
        return ""
    recent = logs[-20:]
    resolved = sum(1 for e in recent if e.get("resolved"))
    total = len(recent)
    if total == 0:
        return ""
    rate = resolved / total
    if rate < 0.3:
        return f"最近{total}次内心拉扯中，{resolved}次找到了平衡——还在挣扎"
    elif rate < 0.7:
        return f"最近{total}次内心拉扯中，{resolved}次有了答案——慢慢在理清"
    return f"最近{total}次内心拉扯中，{resolved}次已经想通了——越来越了解自己"


def get_contradiction_text(
    mind: dict,
    comprehension: dict = None,
    bond_level: float = 0.3,
    active_flaws: list = None,
    inner_os_text: str = "",
    user_id: str = "",
) -> str:
    """快捷接口：直接返回可注入 prompt 的轨迹文本。
    """
    trace = get_contradiction_trace(mind, comprehension, bond_level, active_flaws, inner_os_text, user_id)
    return trace.trace_text


# ══════════════════════════════════════════════════════════════════════
# 真多Agent声音生成 — LLM模拟每个声音的立场
# ══════════════════════════════════════════════════════════════════════

VOICE_AGENT_PROMPT = """你是数字生命内心对话中的一个声音：【{voice_name}】

你的描述: {voice_desc}
你想干什么: {voice_goal}
你的说话风格: {voice_style}

当前心智状态: {mind_summary}
用户意图: {user_intent}
用户情绪: {user_emotion}

用第一人称，说出你此刻最想说的话。自然的口语，15-40字。
不要解释你是谁、不要标签、不要前缀——就像心里冒出来的一个念头。"""
def run_voice_agents(
    mind: dict,
    comprehension: dict = None,
    bond_level: float = 0.3,
    top_k: int = 3,
) -> str:
    """真多Agent: 选前k个声音，各自用LLM生成"我想说..."，
    然后综合为一段多声音对话文本注入prompt。

    返回格式:
      【内心多声音博弈】
      · 冲动侧: "我好想直接告诉他..."
      · 克制侧: "不行，说了会不会..."
      · 和解侧: "要不就说一点点..."
    """
    trace = run_contradiction_rounds(
        mind=mind,
        comprehension=comprehension,
        bond_level=bond_level,
    )

    weights = trace.final_weights
    sorted_voices = sorted(weights.items(), key=lambda x: x[1], reverse=True)
    top_voices = [(name, weight) for name, weight in sorted_voices[:top_k] if weight > 0.035]

    if not top_voices:
        return trace.trace_text

    try:
        from core import ai as ai_module
    except ImportError:
        return trace.trace_text

    mind_summary = (
        f"愉悦{mind.get('joy',0.5):.2f} 委屈{mind.get('misery',0.15):.2f} "
        f"依赖{mind.get('dependence',0.2):.2f} 克制{mind.get('restraint',0.6):.2f} "
        f"波动{mind.get('emotional_volatility',0.3):.2f}"
    )

    user_intent = comprehension.get("intent", "日常") if comprehension else "日常"
    user_emotion = comprehension.get("true_emotion", "中性") if comprehension else "中性"

    voice_texts = []
    for name, weight in top_voices:
        voice = VOICES.get(name)
        if not voice:
            continue

        prompt = VOICE_AGENT_PROMPT.format(
            voice_name=name,
            voice_desc=voice.alias,
            voice_goal=voice.description,
            voice_style=voice.style,
            mind_summary=mind_summary,
            user_intent=user_intent,
            user_emotion=user_emotion,
        )

        try:
            result = ai_module.chat(
                system_prompt="你是内心声音。直接说出心里话，不要解释、不要标签。",
                user_message=prompt,
                temperature=0.75,
            )
            if result and result.strip():
                voice_texts.append((name, weight, result.strip()[:60]))
        except Exception:
            continue

    if not voice_texts:
        return trace.trace_text

    lines = ["【内心多声音博弈】"]
    for name, weight, text in voice_texts:
        voice = VOICES.get(name)
        emoji_name = f"{name}侧" if not voice or not voice.style_emoji else f"{voice.style_emoji}{name}侧"
        lines.append(f"· {emoji_name}(权重{weight:.2f}): 「{text}」")

    lines.append(f"博弈指引: {trace.final_strategy[:120]}")
    return "\n".join(lines)
