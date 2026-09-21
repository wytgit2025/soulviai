# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""全维氛围精准感知层（v3 — 状态机+深度融合版）
高精度识别对话氛围、隐性情绪、敷衍程度等9大隐性状态。
关键词池扩至200+，加入Emoji/标点/句式多维分析，支持LLM理解层深度融合。

升级 v3:
  1. 高频状态机 — 跨消息状态持续性/渐变，非单次快照
  2. 客套/敷衍区分 — 重构关键词池，消除重叠，增加区分特征
  3. 沉默重量计算 — 多因子加权连续值（消息长度+趋势+疲劳+时段+基线偏差）
  4. 深度融合模型 — LLM理解层与关键词加权融合，非后覆盖
"""
import re
import random
import time
import json
import os
from collections import deque
from core import config as cfg

# ── 上下文感知参数 ──
_context_weight = 0.3

# ══════════════════════════════════════════════════════════════════════
# 高频状态机 — 跨消息状态持续性
# ══════════════════════════════════════════════════════════════════════

_state_machine: dict = {}          # user_id → {"current_state": str, "stickiness": float, "last_update": float}
_STICKINESS_INIT = 0.55             # 初始惯性系数（新用户/重启时）
_STICKINESS_DECAY = 0.92            # 每轮衰减（时间越久越容易变）
_STICKINESS_BOOST_PER_MATCH = 0.12  # 同状态连续命中时惯性增强
_STATE_TRANSITION_THRESHOLD = 0.25  # 新状态得分需超过旧状态此比例才切换
_STATE_MACHINE_TTL = 600            # 10分钟无交互重置惯性

# 状态渐变平滑系数（值越低→变化越慢）
_SMOOTHING_FACTOR = {
    "warmth_level": 0.35,
    "closeness_level": 0.30,
    "sincerity_level": 0.30,
    "patience_level": 0.25,
    "fatigue_signal": 0.40,
    "emotional_intensity": 0.30,
}


def _init_state_machine(user_id: str):
    """初始化用户状态机"""
    if user_id not in _state_machine:
        _state_machine[user_id] = {
            "current_state": "中性",
            "previous_state": "中性",
            "stickiness": _STICKINESS_INIT,
            "last_update": time.time(),
            "consecutive_matches": 0,
            "smoothed_values": {},
        }


def _update_state_machine(user_id: str, new_state: str, state_scores: dict) -> str:
    """带惯性的状态切换决策。
    
    只有当新状态得分显著高于当前状态时，才执行切换。
    同状态连续命中会增强惯性，时间流逝会减弱惯性。
    """
    sm = _state_machine.get(user_id)
    if not sm:
        return new_state

    now = time.time()
    elapsed = now - sm["last_update"]
    sm["last_update"] = now

    # 时间衰减：长时间无交互 →惯性回归初始值
    if elapsed > _STATE_MACHINE_TTL:
        sm["stickiness"] = _STICKINESS_INIT
        sm["consecutive_matches"] = 0

    current = sm["current_state"]

    # 同状态连续命中 → 增强惯性
    if new_state == current:
        sm["consecutive_matches"] += 1
        sm["stickiness"] = min(0.92, sm["stickiness"] + _STICKINESS_BOOST_PER_MATCH)
        return current

    # 不同状态：需要满足切换阈值
    sm["consecutive_matches"] = 0
    current_score = state_scores.get(current, 0)
    new_score = state_scores.get(new_state, 0)

    # 当前状态没有得分 → 自由切换
    if current_score <= 0:
        sm["current_state"] = new_state
        sm["previous_state"] = current
        sm["stickiness"] = _STICKINESS_INIT
        return new_state

    # 新状态得分需显著超越旧状态
    score_ratio = (new_score + 0.01) / (current_score + 0.01)
    if score_ratio > (1.0 + _STATE_TRANSITION_THRESHOLD / sm["stickiness"]):
        sm["current_state"] = new_state
        sm["previous_state"] = current
        sm["stickiness"] = _STICKINESS_INIT
        return new_state

    # 切换阈值不足 → 保持当前状态，但允许渐变
    return current


def _smooth_value(user_id: str, dim: str, new_value: float) -> float:
    """对连续值进行指数平滑，防止突变"""
    sm = _state_machine.get(user_id)
    if not sm:
        return new_value
    smoothed = sm.get("smoothed_values", {})
    prev = smoothed.get(dim, new_value)
    factor = _SMOOTHING_FACTOR.get(dim, 0.3)
    result = prev * (1 - factor) + new_value * factor
    smoothed[dim] = result
    sm["smoothed_values"] = smoothed
    return round(result, 4)

# ═══════════════════════════════════════════
# 九大隐性状态 — 扩展关键词池（200+）
# ═══════════════════════════════════════════

_STATE_KEYWORDS = {
    "温柔": [
        # 直白柔软
        "想你了", "想你", "好想你", "想你了呢", "好想抱抱", "贴贴",
        "慢慢来", "不急", "不着急", "你慢慢说", "我等你",
        "辛苦了", "辛苦啦", "注意休息", "别太累", "你也是", "你也一样",
        "在干嘛", "在干嘛呢", "你在干嘛", "忙什么呢",
        "抱抱", "摸摸头", "揉揉", "贴一下",
        # 含蓄温柔
        "喜欢你", "好喜欢你", "喜欢", "爱你", "好爱你",
        "有你真好", "遇见你真好", "很开心认识你",
        "今天过得怎么样", "你今天过得怎么样", "睡得好吗", "吃饭了吗",
        # 轻柔软语
        "嗯呢", "好呢", "好的呢", "听你的", "都听你的",
        "温暖", "暖和", "安心", "踏实",
    ],
    "关心": [
        "多休息", "早点睡", "别熬夜", "注意身体", "照顾好自己",
        "按时吃饭", "别太累", "别太辛苦", "别勉强",
        "冷吗", "热吗", "穿多点", "记得带伞", "路上小心",
        "不舒服吗", "好点了吗", "怎么样了", "还疼吗",
        "别想太多", "开心点", "没事的", "我在呢",
        "吃药了吗", "看了吗", "去看一下吧",
    ],
    "赌气": [
        # 经典赌气
        "没事", "没事了", "不用了", "不用", "算了", "随便吧",
        "随便你", "不想说了", "不说了", "懒得说",
        "你开心就好", "你觉得行就行", "我无所谓",
        # 隐晦赌气
        "呵呵", "行吧行吧", "知道了知道了",
        "反正", "又不是第一次", "习惯了",
        "不用管我", "别管我", "我自己可以",
    ],
    "隐忍": [
        "还好", "还行吧", "我没事", "没关系", "没事的没事的",
        "可以接受", "能接受", "无所谓了",
        "不说了", "不聊这个", "不提了",
        "忍忍就过去了", "习惯了就好",
        "没什么", "没啥", "小事", "不至于",
    ],
    "敷衍": [
        # 极简敷衍 — 纯应付
        "嗯", "哦", "噢", "额", "呃",
        "行吧", "好吧", "好叭",
        "随便", "都行", "你定吧", "你决定",
        "就这样", "那就这样吧",
        # 转移式敷衍
        "哈哈", "哈哈哈", "haha", "6", "牛逼",
        "可以可以", "不错不错", "挺好挺好",
        # 结束话题式敷衍
        "那先这样", "先不说了", "晚点说",
        "下次聊", "先忙", "回头说",
        # 回避式敷衍
        "不太清楚", "不知道", "没注意", "忘了",
        "再说吧", "改天", "以后再说",
    ],
    "客套": [
        # 双音节礼貌回应（区别于单音节敷衍）
        "嗯嗯", "好哒", "好的", "好的好的", "好滴",
        "好嘞", "好咧", "好哦",
        # 感谢式客气
        "谢谢", "谢谢啦", "谢谢你", "多谢", "感谢",
        "辛苦了", "辛苦啦", "费心了", "劳烦了",
        # 确认式客气
        "收到收到", "明白了", "清楚", "没问题",
        "可以的", "可以呀", "好的呢",
        # 社交客气
        "麻烦了", "麻烦你了", "不好意思", "打扰了",
        "抱歉", "抱歉抱歉",
        # 开场/结束客气
        "你好", "您好", "幸会", "久仰", "客气",
        "欢迎", "欢迎欢迎",
    ],
    "冷淡": [
        "嗯", "哦", "行", "好", "知道",
        # 短促回应
        "不", "没", "对", "是",
        # 否定式冷淡
        "不知道", "不清楚", "不懂",
        "不用", "不要", "没啥好说的",
    ],
    "无奈": [
        "哎", "唉", "害",
        "没办法", "没法子", "又能怎样",
        "我也不想", "我能怎么办", "有什么办法呢",
        "又是", "又来了", "每次都这样",
        "那就这样", "那行吧", "就这样吧",
        "随便了", "无所谓了",
    ],
    "沉默难过": [
        "…", "..", "。。。", "……",
        "嗯。", "哦。", "好。",
        "没事。", "不用。", "睡了。",
        "算了。", "不说了。",
        # 低落碎片语
        "累了", "好累", "好烦", "难受", "难过",
        "睡不着", "失眠了",
    ],
}

# ── Emoji 情绪映射 ──
_EMOJI_MOOD = {
    # 正向
    "😊": ("温柔", 0.8), "🥰": ("温柔", 0.9), "😘": ("温柔", 0.9),
    "❤️": ("温柔", 1.0), "💕": ("温柔", 0.9), "💗": ("温柔", 0.9),
    "😄": ("开心", 0.7), "😂": ("开心", 0.6), "🤣": ("开心", 0.6),
    "🌹": ("温柔", 0.7), "🌸": ("温柔", 0.6),
    # 负向
    "😢": ("难过", 0.8), "😭": ("难过", 0.9), "🥺": ("赌气", 0.7),
    "😞": ("难过", 0.7), "😔": ("难过", 0.6), "💔": ("难过", 0.8),
    "😠": ("生气", 0.8), "😡": ("生气", 0.9), "🤬": ("生气", 1.0),
    "😑": ("冷淡", 0.6), "😐": ("冷淡", 0.5),
    # 中性/复杂
    "😅": ("无奈", 0.5), "😰": ("焦虑", 0.7), "😨": ("焦虑", 0.7),
    "🙃": ("隐忍", 0.6),
}
# 文本颜文字映射
_TEXT_EMOJI_MOOD = {
    "T_T": ("难过", 0.8), "TAT": ("难过", 0.8), "T.T": ("难过", 0.7),
    "QAQ": ("难过", 0.7), "QwQ": ("难过", 0.6),
    ">_<": ("焦虑", 0.5), "><": ("无奈", 0.4),
    "orz": ("无奈", 0.6), "OTL": ("无奈", 0.6),
    "^_^": ("温柔", 0.5), "^^": ("温柔", 0.4),
    "= =": ("冷淡", 0.5), "-_-": ("冷淡", 0.6),
    "0.0": ("冷淡", 0.4), "o.o": ("冷淡", 0.4),
    ";w;": ("难过", 0.7), ";_;": ("难过", 0.7),
}
# 微信表情文本
_WX_EMOJI_MOOD = {
    "[微笑]": ("客套", 0.6), "[呲牙]": ("开心", 0.5),
    "[大哭]": ("难过", 0.9), "[流泪]": ("难过", 0.8),
    "[捂脸]": ("无奈", 0.6), "[破涕为笑]": ("无奈", 0.5),
    "[裂开]": ("无奈", 0.7), "[苦涩]": ("难过", 0.7),
    "[抱抱]": ("温柔", 0.8), "[爱心]": ("温柔", 0.9),
    "[玫瑰]": ("温柔", 0.6), "[亲亲]": ("温柔", 0.9),
    "[叹气]": ("无奈", 0.7), "[翻白眼]": ("冷淡", 0.5),
    "[发呆]": ("冷淡", 0.4),
}

# ── 句式结构特征 ──
def _analyze_structure(msg: str) -> dict:
    """分析消息结构特征"""
    info = {
        "has_question": bool(re.search(r'[?？]|吗|呢|吧|怎么|什么|谁|哪|为什么|能不能', msg)),
        "has_exclamation": bool(re.search(r'[!！]{1,}', msg)),
        "has_ellipsis": bool(re.search(r'\.{2,}|。{2,}|…{1,}', msg)),
        "has_repetition": bool(re.search(r'(.)\1{3,}', msg)),  # 同一字符重复4+
        "has_caps": bool(re.search(r'[A-Z]{3,}', msg)),  # 全大写
        "sentence_count": len(re.split(r'[。！？!?\n]', msg)),
        "avg_sentence_len": 0,
        "word_count": len(re.sub(r'\s', '', msg)),
    }
    sentences = [s.strip() for s in re.split(r'[。！？!?\n]', msg) if s.strip()]
    if sentences:
        info["avg_sentence_len"] = sum(len(s) for s in sentences) / len(sentences)
    return info


# ══════════════════════════════════════════════════════════════════════
# 沉默重量计算 — 多因子加权连续值
# ══════════════════════════════════════════════════════════════════════

_SILENCE_WEIGHTS = {
    "msg_len_factor": 0.30,         # 消息长度
    "trend_factor": 0.20,           # 趋势（冷却中加重）
    "fatigue_factor": 0.15,         # 疲劳信号
    "time_factor": 0.10,            # 时段（深夜加重）
    "baseline_factor": 0.15,        # 与用户基线的偏差
    "state_factor": 0.10,           # 状态（沉默难过/冷淡加重）
}


def _compute_silence_weight(msg: str, result: dict, recent_context: list = None,
                            user_id: str = "") -> tuple:
    """计算沉默重量，返回 (连续值 0~1, 等级标签)
    
    多因子加权：
      - 消息越短 → 沉默越重
      - 趋势冷却中 → 沉默加重
      - 疲劳信号高 → 沉默加重
      - 深夜（22-6点）→ 沉默加重
      - 比用户平时短很多 → 沉默加重
      - 状态为沉默难过/冷淡 → 沉默加重
    """
    msg_len = len(msg.strip())
    score = 0.0

    # 因子1: 消息长度因子（核心）
    if msg_len <= 1:
        len_score = 1.0
    elif msg_len <= 2:
        len_score = 0.85
    elif msg_len <= 4:
        len_score = 0.55
    elif msg_len <= 8:
        len_score = 0.30
    elif msg_len <= 15:
        len_score = 0.15
    else:
        len_score = 0.05
    score += len_score * _SILENCE_WEIGHTS["msg_len_factor"]

    # 因子2: 趋势因子
    trend = result.get("trend", "稳定")
    if trend == "冷却中" or "降温" in str(result.get("hidden_state", "")):
        score += 0.65 * _SILENCE_WEIGHTS["trend_factor"]
    elif trend == "回暖中":
        score += 0.15 * _SILENCE_WEIGHTS["trend_factor"]
    else:
        score += 0.30 * _SILENCE_WEIGHTS["trend_factor"]

    # 因子3: 疲劳/耐心因子
    patience = result.get("patience_level", 0.7)
    fatigue = result.get("fatigue_signal", 0.0)
    patience_score = max(0, 0.6 - patience * 0.8) + fatigue * 0.5
    score += min(1.0, patience_score) * _SILENCE_WEIGHTS["fatigue_factor"]

    # 因子4: 时段因子
    try:
        hour = time.localtime().tm_hour
        if hour >= 22 or hour < 6:
            score += 0.6 * _SILENCE_WEIGHTS["time_factor"]
        elif hour >= 6 and hour < 9:
            score += 0.2 * _SILENCE_WEIGHTS["time_factor"]
    except Exception:
        pass

    # 因子5: 状态因子
    state = result.get("primary_state", "中性")
    if state in ("沉默难过", "冷淡"):
        score += 0.7 * _SILENCE_WEIGHTS["state_factor"]
    elif state in ("赌气", "敷衍", "隐忍"):
        score += 0.5 * _SILENCE_WEIGHTS["state_factor"]
    elif state in ("无奈",):
        score += 0.3 * _SILENCE_WEIGHTS["state_factor"]

    # 因子6: 上下文 — 连续短消息加重
    if recent_context and len(recent_context) >= 2:
        prev_short = sum(1 for m in recent_context[-3:] if len(m.strip()) <= 3)
        if prev_short >= 2:
            score += 0.15 * (prev_short / 3.0)

    # 因子7: 用户基线偏差（由 enrich_with_history 补充）

    # 最终分数裁剪
    final_score = round(max(0.0, min(1.0, score)), 3)

    # 等级标签
    if final_score >= 0.70:
        label = "重"
    elif final_score >= 0.40:
        label = "中"
    else:
        label = "轻"

    return final_score, label


def load_engine_config():
    pass


def perceive(user_message: str, recent_context: list = None,
             comprehension: dict = None, user_id: str = "") -> dict:
    """全维氛围感知（v3 — 状态机+深度融合）
    
    Args:
        user_message: 当前用户消息
        recent_context: 最近几条用户消息列表
        comprehension: LLM理解层结果（来自 comprehend_inner），用于融合修正
        user_id: 用户ID（启用状态机和基线校准）
    
    Returns:
        完整的感知结果字典
    """
    msg = user_message.strip()
    result = {
        "explicit_state": "中性",
        "hidden_state": "中性",
        "patience_level": 0.7,
        "sincerity_level": 0.7,
        "closeness_level": 0.5,
        "fatigue_signal": 0.0,
        "silence_weight": "轻",
        "silence_score": 0.0,
        "warmth_level": 0.5,
        "trend": "稳定",
        "primary_state": "中性",
        "state_confidence": 0.0,
        "emotional_intensity": 0.0,
        "emoji_signal": None,
    }

    # ── 初始化状态机（如果启用 user_id）──
    if user_id:
        _init_state_machine(user_id)

    # ── Step 1: Emoji/颜文字检测 ──
    _detect_emoji_signal(msg, result)

    # ── Step 2: 句式结构分析 ──
    structure = _analyze_structure(msg)

    # ── Step 3: 九大状态关键词匹配 ──
    state_scores = _score_all_states(msg)

    # ── Step 4: 综合打分判态 ──
    _determine_primary_state(msg, state_scores, structure, result)

    # ── Step 4b: 高频状态机 — 跨消息持续性（v3 新增）──
    if user_id:
        smoothed_state = _update_state_machine(user_id, result.get("primary_state", "中性"), state_scores)
        # 如果状态机保持旧状态 → 降低新状态的置信度
        if smoothed_state != result.get("primary_state"):
            result["state_confidence"] = round(result["state_confidence"] * 0.6, 2)
        result["primary_state"] = smoothed_state

    # ── Step 5: 上下文趋势分析 ──
    if recent_context and len(recent_context) >= 2:
        _analyze_context_trend(msg, recent_context, result)

    # ── Step 6: 消息结构微调 ──
    _apply_structure_modifiers(msg, structure, result)

    # ── Step 6b: 沉默重量 — 多因子计算（v3 新增）──
    silence_score, silence_label = _compute_silence_weight(msg, result, recent_context, user_id)
    result["silence_score"] = silence_score
    result["silence_weight"] = silence_label

    # ── Step 7: LLM理解层深度融合（v3 — 加权融合替代后覆盖）──
    if comprehension and comprehension.get("confidence", 0) > 0.4:
        result = _fuse_with_comprehension(result, comprehension)

    # ── Step 7b: 状态机平滑连续值（v3 新增）──
    if user_id:
        for dim in ["warmth_level", "closeness_level", "sincerity_level", "patience_level", "fatigue_signal"]:
            if dim in result:
                result[dim] = _smooth_value(user_id, dim, result[dim])

    # ── Step 8: 好奇心检测（检测陌生实体，积累好奇值）──
    if user_id and len(msg) >= 4:
        try:
            from engine import curiosity as curiosity_module
            # 从 comprehension 或关键词中检测可能的新实体
            if comprehension and comprehension.get("confidence", 0) > 0.4:
                unknown_entities = _detect_unknown_entities(user_id, msg)
                for entity, etype, importance in unknown_entities:
                    curiosity_module.on_unknown_entity(user_id, entity, etype, importance)
        except Exception:
            pass

    return result


# ═══════════════════════════════════════════
# 好奇心辅助函数
# ═══════════════════════════════════════════

def _detect_unknown_entities(user_id: str, msg: str) -> list:
    """检测消息中可能的新实体（不在知识图谱中）。
    返回 [(entity, type, importance), ...]
    """
    import re
    candidates = re.findall(r'[\u4e00-\u9fff]{2,6}', msg)
    stopwords = {"用户", "对方", "数字", "生命", "灵魂", "什么", "怎么",
                 "这个", "那个", "可以", "不过", "但是", "因为", "所以",
                 "如果", "虽然", "然后", "最后", "没有", "时候", "一个",
                 "自己", "今天", "昨天", "明天", "刚才", "知道", "感觉",
                 "觉得", "就是", "还是", "已经", "以后", "以前", "大家",
                 "可能", "应该", "不会", "不要", "一起", "一下", "一直",
                 "有点", "真的", "那么", "这么", "这样", "那样",
                 "虽然", "如果", "然后", "只是"}

    # 情感/兴趣相关词 → 高好奇权重
    interest_signals = {
        "喜欢": "interest", "爱": "interest", "想": "interest",
        "玩": "interest", "看": "interest", "读": "interest",
        "去": "place", "在": "place",
        "朋友": "person", "同事": "person",
    }

    unknown = []
    for w in candidates:
        if w in stopwords or len(w) < 2:
            continue
        # 确定类型
        etype = "concept"
        for signal, t in interest_signals.items():
            if signal in w or signal in msg:
                etype = t
                break

        importance = 0.4
        if etype == "person":
            importance = 0.6
        elif etype == "interest":
            importance = 0.5

        unknown.append((w, etype, importance))

    return unknown[:5]


# ═══════════════════════════════════════════
# Step 1: Emoji 信号
# ═══════════════════════════════════════════

def _detect_emoji_signal(msg: str, result: dict):
    """检测 Emoji / 颜文字 / 微信表情的情绪信号"""
    best_mood, best_score = None, 0

    # Unicode Emoji
    for emoji, (mood, score) in _EMOJI_MOOD.items():
        if emoji in msg:
            if score > best_score:
                best_mood, best_score = mood, score

    # 文本颜文字
    if not best_mood:
        for face, (mood, score) in _TEXT_EMOJI_MOOD.items():
            if face in msg:
                if score > best_score:
                    best_mood, best_score = mood, score

    # 微信表情 [xxx]
    if not best_mood:
        for face, (mood, score) in _WX_EMOJI_MOOD.items():
            if face in msg:
                if score > best_score:
                    best_mood, best_score = mood, score

    if best_mood:
        result["emoji_signal"] = best_mood
        result["emotional_intensity"] = best_score
        # Emoji 情绪直接映射
        emoji_to_state = {
            "温柔": ("温柔", "温暖"),
            "开心": ("温柔", "温暖"),
            "难过": ("沉默难过", "难过的样子"),
            "赌气": ("赌气", "可能赌气"),
            "生气": ("赌气", "赌气"),
            "冷淡": ("冷淡", "疏离"),
            "无奈": ("无奈", "麻木"),
            "焦虑": ("沉默难过", "不安"),
            "隐忍": ("隐忍", "内耗"),
        }
        state_map = emoji_to_state.get(best_mood, ("中性", "中性"))
        result["explicit_state"] = best_mood
        result["hidden_state"] = state_map[1]
        result["primary_state"] = state_map[0]


# ═══════════════════════════════════════════
# Step 3: 九状态打分
# ═══════════════════════════════════════════

def _score_all_states(msg: str) -> dict:
    """对所有九大状态进行加权打分（区分客套/敷衍）"""
    scores = {}
    for state, keywords in _STATE_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in msg:
                # 长关键词匹配置信度更高
                score += 2 if len(kw) >= 3 else 1
        scores[state] = score

    # ── 客套/敷衍 区分特征注入 ──
    msg_len = len(msg)

    # 特征1: 单字/极短 → 强烈倾向于敷衍而非客套
    if msg_len <= 2:
        scores["敷衍"] = scores.get("敷衍", 0) + 3
        scores["客套"] = max(0, scores.get("客套", 0) - 2)
    elif msg_len <= 4:
        scores["敷衍"] = scores.get("敷衍", 0) + 1

    # 特征2: 含"您" → 一定是客套，不是敷衍
    if "您" in msg:
        scores["客套"] = scores.get("客套", 0) + 4
        scores["敷衍"] = max(0, scores.get("敷衍", 0) - 1)

    # 特征3: 含感谢类词 → 客套信号
    gratitude_signals = ["谢谢", "多谢", "感谢", "辛苦了", "费心"]
    if any(s in msg for s in gratitude_signals):
        scores["客套"] = scores.get("客套", 0) + 3

    # 特征4: 完整句子（>8字且含主谓结构）→ 不是敷衍
    if msg_len >= 8:
        scores["敷衍"] = max(0, scores.get("敷衍", 0) - 1)

    # 特征5: "哈哈/哈哈哈"单独成句 → 敷衍；带其他内容 → 可能是真笑
    if msg.strip() in ("哈哈", "哈哈哈", "hhhh", "haha"):
        scores["敷衍"] = scores.get("敷衍", 0) + 5
        scores["客套"] = max(0, scores.get("客套", 0) - 1)

    # 特征6: 双重确认词 "好的没问题""明白了好的" → 客套
    if "好的" in msg and ("没问题" in msg or "明白" in msg or "收到" in msg):
        scores["客套"] = scores.get("客套", 0) + 3

    return scores


# ═══════════════════════════════════════════
# Step 4: 综合判态
# ═══════════════════════════════════════════

def _determine_primary_state(msg: str, state_scores: dict,
                              structure: dict, result: dict):
    """综合关键词 + 结构 + 上下文判定主要状态"""# Emoji 已发出强信号 → 不轻易覆盖
    emoji_override = result.get("emoji_signal") is not None and result.get("emotional_intensity", 0) >= 0.6

    # 长度修正因子
    msg_len = len(msg)
    if not emoji_override:
        if msg_len <= 2:
            # 极短消息：冷淡/敷衍权重增加
            state_scores["冷淡"] = state_scores.get("冷淡", 0) + 3
            state_scores["敷衍"] = state_scores.get("敷衍", 0) + 2
            if msg in ("嗯", "哦", "好", "行", "对", "不", "没", "是"):
                state_scores["冷淡"] += 4
        elif msg_len <= 4:
            state_scores["冷淡"] = state_scores.get("冷淡", 0) + 1

    if msg_len >= 30:
        if structure["has_question"]:
            state_scores["温柔"] = state_scores.get("温柔", 0) + 2
        state_scores["关心"] = state_scores.get("关心", 0) + 1

    # 省略号 → 沉默难过/隐忍
    if structure["has_ellipsis"]:
        state_scores["沉默难过"] = state_scores.get("沉默难过", 0) + 2
        state_scores["隐忍"] = state_scores.get("隐忍", 0) + 1

    # 感叹号 → 除非在温柔/关心池，否则增加情绪强度
    if structure["has_exclamation"]:
        if state_scores.get("温柔", 0) == 0 and state_scores.get("关心", 0) == 0:
            state_scores["无奈"] = state_scores.get("无奈", 0) + 1

    # Emoji 强信号优先：跳过关键词竞争，直接用 emoji 判定
    if emoji_override and result.get("emotional_intensity", 0) >= 0.7:
        emo_state = result.get("primary_state", "中性")
        _apply_state_to_result(emo_state, score=4, confidence=0.82, msg_len=msg_len, result=result)
        result["primary_state"] = emo_state
        result["state_confidence"] = 0.82
        return

    all_zero = all(v == 0 for v in state_scores.values()) if state_scores else True

    if not state_scores or all_zero:
        result["primary_state"] = "中性"
        result["state_confidence"] = 0.0
        return

    max_state = max(state_scores, key=state_scores.get)
    max_score = state_scores[max_state]

    # 信心度：最高分与次高分差距越大越确信
    sorted_states = sorted(state_scores.items(), key=lambda x: x[1], reverse=True)
    if len(sorted_states) >= 2 and sorted_states[0][1] > 0:
        second_score = sorted_states[1][1]
        confidence = min(1.0, (max_score - second_score) / max(max_score, 1) + 0.3)
    else:
        confidence = 0.3 if max_score > 0 else 0.0

    result["primary_state"] = max_state if max_score > 0 else "中性"
    result["state_confidence"] = round(confidence, 2)

    # ── 综合判定 → 赋值各维度 ──
    _apply_state_to_result(max_state, max_score, confidence, msg_len, result)


def _apply_state_to_result(state: str, score: int, confidence: float,
                            msg_len: int, result: dict):
    """根据判定状态填充感知结果各维度"""# 强度基数 = 关键词分 × 信心度
    intensity = min(1.0, score * 0.1 * confidence)

    if state in ("温柔", "关心"):
        result["explicit_state"] = state
        result["hidden_state"] = "温暖"
        result["warmth_level"] = round(min(1.0, 0.6 + intensity * 0.4), 2)
        result["sincerity_level"] = round(min(1.0, 0.7 + intensity * 0.3), 2)
        result["closeness_level"] = round(min(1.0, 0.6 + intensity * 0.4), 2)
        result["emotional_intensity"] = intensity

    elif state in ("赌气", "沉默难过"):
        result["explicit_state"] = "表面平静"
        result["hidden_state"] = state
        result["warmth_level"] = round(max(0.1, 0.3 - intensity * 0.2), 2)
        result["sincerity_level"] = round(0.5, 2)
        result["closeness_level"] = round(max(0.1, 0.35 - intensity * 0.15), 2)
        result["emotional_intensity"] = intensity

    elif state in ("冷淡", "敷衍"):
        result["explicit_state"] = state
        result["hidden_state"] = "疏离"
        result["patience_level"] = round(max(0.1, 0.4 - intensity * 0.3), 2)
        result["warmth_level"] = round(max(0.05, 0.2 - intensity * 0.2), 2)
        result["sincerity_level"] = round(max(0.1, 0.35 - intensity * 0.25), 2)
        result["closeness_level"] = round(max(0.1, 0.25 - intensity * 0.15), 2)

    elif state == "隐忍":
        result["explicit_state"] = "平静"
        result["hidden_state"] = "内耗"
        result["warmth_level"] = round(0.4, 2)
        result["sincerity_level"] = round(min(0.6, 0.4 + intensity * 0.15), 2)
        result["emotional_intensity"] = intensity

    elif state == "客套":
        result["explicit_state"] = "礼貌"
        result["hidden_state"] = "疏远"
        result["closeness_level"] = round(max(0.15, 0.35 - intensity * 0.15), 2)
        result["warmth_level"] = round(0.35, 2)
        result["sincerity_level"] = round(0.5, 2)

    elif state == "无奈":
        result["explicit_state"] = "疲惫"
        result["hidden_state"] = "麻木"
        result["fatigue_signal"] = round(min(1.0, 0.4 + intensity * 0.5), 2)
        result["warmth_level"] = round(max(0.15, 0.35 - intensity * 0.2), 2)
        result["emotional_intensity"] = intensity


# ═══════════════════════════════════════════
# Step 5: 上下文趋势分析
# ═══════════════════════════════════════════

def _analyze_context_trend(msg: str, recent_context: list, result: dict):
    """分析最近几条消息的趋势变化"""
    if len(recent_context) < 2:
        return

    prev_brief = _quick_perceive(recent_context[-1])
    prev2_brief = _quick_perceive(recent_context[-2]) if len(recent_context) >= 2 else prev_brief

    warmth_trend = prev_brief["warmth_level"] - prev2_brief["warmth_level"]

    # 明显降温
    if warmth_trend < -0.25:
        result["trend"] = "冷却中"
        result["patience_level"] = round(max(0.05, result["patience_level"] - 0.15), 2)
        if result["hidden_state"] == "中性":
            result["hidden_state"] = "可能赌气或疲倦"

    # 明显回暖
    elif warmth_trend > 0.2:
        result["trend"] = "回暖中"
        result["warmth_level"] = round(min(1.0, result["warmth_level"] + 0.1), 2)

    # 连续短消息 → 耐心枯竭
    if len(msg) <= 3 and len(recent_context[-1]) <= 3:
        result["silence_weight"] = "重"
        result["patience_level"] = round(max(0.05, result["patience_level"] - 0.25), 2)
        if result["hidden_state"] == "中性":
            result["hidden_state"] = "持续沉默"

    # 激情→冷淡突变 → 赌气概率极高
    if prev2_brief["warmth_level"] > 0.6 and prev_brief["warmth_level"] < 0.3:
        result["hidden_state"] = "情绪突变·疑似赌气"


# ═══════════════════════════════════════════
# Step 6: 消息结构微调
# ═══════════════════════════════════════════

def _apply_structure_modifiers(msg: str, structure: dict, result: dict):
    """根据消息长度、标点、句式微调各维度"""
    # 沉默重量由 _compute_silence_weight 独立计算
    # 此处只影响 patience_level

    msg_len = len(msg)
    if msg_len <= 2:
        result["patience_level"] = round(max(0.05, result["patience_level"] - 0.2), 2)

    # 句末标点信号
    if "!!" in msg or "！！" in msg:
        result["explicit_state"] = "激动"
        result["emotional_intensity"] = min(1.0, result.get("emotional_intensity", 0) + 0.2)
    if "??" in msg or "？？" in msg:
        result["hidden_state"] = "困惑"

    # 波浪线 → 放松/温柔
    if "~" in msg or "～" in msg:
        if result["warmth_level"] < 0.6:
            result["warmth_level"] = round(min(1.0, result["warmth_level"] + 0.08), 2)
        result["closeness_level"] = round(min(1.0, result.get("closeness_level", 0.5) + 0.05), 2)

    # 语气词"啦""呢""嘛""呀" → 柔软
    soft_particles = re.findall(r'啦|呢|嘛|呀|哦|哟|哈', msg)
    if soft_particles and result["warmth_level"] < 0.7:
        bonus = min(0.12, len(soft_particles) * 0.03)
        result["warmth_level"] = round(min(1.0, result["warmth_level"] + bonus), 2)
        result["closeness_level"] = round(min(1.0, result.get("closeness_level", 0.5) + bonus * 0.5), 2)


# ═══════════════════════════════════════════
# Step 7: LLM 理解层深度融合（v3 — 加权融合替代后覆盖）
# ═══════════════════════════════════════════

def _fuse_with_comprehension(result: dict, comprehension: dict) -> dict:
    """v3: LLM理解层深度融合（加权融合替代后覆盖）

    融合策略（按置信度分级）：
      - confidence < 0.5: 关键词为主(75%)，LLM为辅(25%)
      - 0.5 ≤ confidence ≤ 0.7: 加权均衡（关键词40% + LLM 60%）
      - confidence > 0.7: LLM主导(80%)，保留关键词残留信号(20%)

    保持两种来源的双向可见性
    """
    confidence = comprehension.get("confidence", 0.4)
    intent = comprehension.get("intent", "")
    emotion = comprehension.get("true_emotion", "")
    need = comprehension.get("what_they_need", "")
    depth = comprehension.get("depth", "")
    surface = comprehension.get("surface_emotion", "")

    # ── 计算融合权重 ──
    if confidence < 0.5:
        llm_weight, kw_weight = 0.25, 0.75
    elif confidence <= 0.7:
        llm_weight, kw_weight = 0.60, 0.40
    else:
        llm_weight, kw_weight = 0.80, 0.20

    # ── 1. 显性/隐性状态融合 ──
    intent_map = {
        "倾诉": ("倾诉", "需要被倾听"),
        "撒娇": ("温柔", "撒娇中"),
        "敷衍": ("应付", "疏离"),
        "隐忍": ("隐忍", "内耗"),
        "试探": ("隐忍", "试探性互动"),
        "分享": ("温柔", "愉快的分享"),
        "求助": ("无奈", "需要帮助"),
    }

    if intent in intent_map and confidence > 0.4:
        llm_explicit, llm_hidden = intent_map[intent]

        # 融合：LLM意图 + 关键词当前状态 = 加权融合
        kw_confidence = result.get("state_confidence", 0)

        # 如果关键词高度确信(>0.7)且LLM不太确信(<0.6) → 维持关键词
        if kw_confidence > 0.7 and confidence < 0.6:
            pass  # 保持 result 现有值
        elif confidence > 0.7:
            # LLM 高确信 → LLM 主导
            result["explicit_state"] = llm_explicit
            result["hidden_state"] = llm_hidden
            result["primary_state"] = llm_explicit
        else:
            # 中等确信 → 概率性混合
            if random.random() < llm_weight:
                result["explicit_state"] = llm_explicit
                result["hidden_state"] = llm_hidden
                result["primary_state"] = llm_explicit

    # ── 2. 连续值维度融合 ──
    emotion_adj = {
        "开心": {"warmth_level": (0.7, 0.9), "sincerity_level": (0.7, 0.9), "closeness_level": (0.6, 0.8)},
        "难过": {"warmth_level": (0.2, 0.4), "sincerity_level": (0.5, 0.7), "patience_level": (0.3, 0.5)},
        "低落": {"warmth_level": (0.15, 0.35)},
        "焦虑": {"warmth_level": (0.3, 0.5), "fatigue_signal": (0.5, 0.8)},
        "感动": {"warmth_level": (0.8, 1.0), "sincerity_level": (0.8, 1.0), "closeness_level": (0.7, 0.9)},
        "想念": {"warmth_level": (0.7, 0.9), "sincerity_level": (0.7, 0.9)},
        "无所谓": {"warmth_level": (0.1, 0.25), "sincerity_level": (0.2, 0.4), "patience_level": (0.2, 0.4)},
    }

    if emotion in emotion_adj:
        for dim, (lo, hi) in emotion_adj[emotion].items():
            if dim in result:
                current = result[dim]
                llm_target = (lo + hi) / 2
                # 加权融合：current(关键词) × kw_weight + llm_target × llm_weight
                result[dim] = round(current * kw_weight + llm_target * llm_weight, 2)

    # ── 3. 需求融合 ──
    if need == "空间":
        current_close = result.get("closeness_level", 0.5)
        current_warm = result.get("warmth_level", 0.5)
        result["closeness_level"] = round(
            current_close * kw_weight + max(0.1, current_close - 0.2) * llm_weight, 2)
        result["warmth_level"] = round(
            current_warm * kw_weight + max(0.1, current_warm - 0.1) * llm_weight, 2)
    elif need == "安慰":
        current = result.get("sincerity_level", 0.7)
        result["sincerity_level"] = round(
            current * kw_weight + min(1.0, current + 0.15) * llm_weight, 2)

    # ── 4. 深度融合 ──
    if depth == "深度":
        cur_sinc = result.get("sincerity_level", 0.7)
        cur_fat = result.get("fatigue_signal", 0.0)
        result["sincerity_level"] = round(
            cur_sinc * kw_weight + min(1.0, cur_sinc + 0.1) * llm_weight, 2)
        result["fatigue_signal"] = round(
            cur_fat * kw_weight + min(1.0, cur_fat + 0.15) * llm_weight, 2)

    # ── 5. 理解层附加元数据（始终保留，不融合）──
    result["comprehended_intent"] = intent
    result["comprehended_emotion"] = emotion
    result["comprehended_need"] = need
    result["llm_fusion_weight"] = round(llm_weight, 2)

    # ── 6. 表面 ≠ 真实情绪 → 丰富 hidden_state ──
    if surface and emotion and surface != emotion:
        keyword_hidden = result.get("hidden_state", "")
        llm_hidden = f"字面{surface}·实际{emotion}"
        result["hidden_state"] = llm_hidden if llm_weight > 0.5 else (keyword_hidden or llm_hidden)

    return result


# ═══════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════

def _quick_perceive(msg: str) -> dict:
    """轻量级快速感知，计算 warmth/sincerity，用于趋势对比"""
    result = {"warmth_level": 0.5, "sincerity_level": 0.5}
    msg = msg.strip()

    warm_signals = 0
    cold_signals = 0

    # 扫描温柔/关心关键词池
    warm_kws = _STATE_KEYWORDS.get("温柔", []) + _STATE_KEYWORDS.get("关心", [])
    for kw in warm_kws:
        if kw in msg:
            warm_signals += len(kw) * 0.5

    # 扫描冷淡/敷衍池
    cold_kws = _STATE_KEYWORDS.get("冷淡", []) + _STATE_KEYWORDS.get("敷衍", [])
    for kw in cold_kws:
        if kw in msg:
            cold_signals += len(kw) * 0.5

    # Emoji 信号
    for emoji, (mood, score) in _EMOJI_MOOD.items():
        if emoji in msg:
            if mood in ("温柔", "开心"):
                warm_signals += score * 2
            elif mood in ("难过", "冷淡", "赌气"):
                cold_signals += score * 2

    length_factor = min(1.0, len(msg) / 20)

    if warm_signals > 0:
        result["warmth_level"] = round(min(1.0, 0.55 + warm_signals * 0.08), 2)
        result["sincerity_level"] = round(min(1.0, 0.6 + warm_signals * 0.06), 2)
    elif cold_signals > 0:
        result["warmth_level"] = round(max(0.1, 0.45 - cold_signals * 0.08), 2)
        result["sincerity_level"] = round(max(0.15, 0.5 - cold_signals * 0.06), 2)
    else:
        result["warmth_level"] = round(0.4 + length_factor * 0.25, 2)
        result["sincerity_level"] = round(0.4 + length_factor * 0.35, 2)

    # 语气词修正
    soft = len(re.findall(r'啦|呢|嘛|呀|哦|~|～', msg))
    result["warmth_level"] = round(min(1.0, result["warmth_level"] + soft * 0.03), 2)

    return result


def detect_user_attitude(perception: dict) -> str:
    """根据感知结果推断用户相处态度，用于双向人格塑造。
     增强：同时参考 LLM 理解层的 emotion/need 字段。
    """
    ws = perception.get("warmth_level", 0.5)
    ss = perception.get("sincerity_level", 0.5)
    ps = perception.get("patience_level", 0.5)
    trend = perception.get("trend", "稳定")

    # ── LLM 情绪辅助判断 ──
    comp_emotion = perception.get("comprehended_emotion", "")
    comp_need = perception.get("comprehended_need", "")

    # LLM 说需要"空间" → 冷淡概率显著增加
    if comp_need == "空间":
        if trend == "冷却中":
            return "敷衍"
        return "冷淡"

    # 高温暖 + 高真诚 = 温柔
    if ws > 0.7 and ss > 0.7:
        return "温柔"
    if ws > 0.75:
        return "珍惜" if ss > 0.5 else "温柔"

    # 低耐心 + 低温暖 = 冷淡
    if ps < 0.3 and ws < 0.25:
        if trend == "冷却中":
            return "敷衍"
        return "冷淡"

    if ss < 0.4 and ps < 0.4:
        return "敷衍" if trend == "冷却中" else "冷淡"

    # 高耐心 + 高真诚 = 耐心
    if ps > 0.6 and ss > 0.6:
        return "耐心"

    # LLM 情绪兜底
    if comp_emotion in ("难过", "低落"):
        return "中性"  # 虽然难过但是真实的

    return "中性"


# ═══════════════════════════════════════════════════════
# 感知历史累积层 — 多轮趋势感知 + 用户基线校准
# ═══════════════════════════════════════════════════════

_HISTORY_FILE = "data/json/perception_history.json"
_perception_history: dict = {}
_history_loaded = False


def _load_history():
    global _perception_history, _history_loaded
    if _history_loaded:
        return
    try:
        if os.path.exists(_HISTORY_FILE):
            with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
                for uid, entries in raw.items():
                    _perception_history[uid] = deque(entries, maxlen=20)
    except Exception:
        pass
    _history_loaded = True


def _save_history():
    try:
        os.makedirs(os.path.dirname(_HISTORY_FILE), exist_ok=True)
        raw = {uid: list(dq) for uid, dq in _perception_history.items()}
        with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def record_perception(user_id: str, msg: str, result: dict):
    """记录一次感知结果到历史队列（保留最近20轮）"""
    _load_history()
    if user_id not in _perception_history:
        _perception_history[user_id] = deque(maxlen=20)
    snapshot = {
        "ts": time.time(),
        "msg_len": len(msg.strip()),
        "warmth": result.get("warmth_level", 0.5),
        "closeness": result.get("closeness_level", 0.5),
        "patience": result.get("patience_level", 0.7),
        "sincerity": result.get("sincerity_level", 0.5),
        "fatigue": result.get("fatigue_signal", 0.0),
        "silence": result.get("silence_weight", "轻"),
        "silence_score": result.get("silence_score", 0.0),
    }
    _perception_history[user_id].append(snapshot)
    _save_history()


def get_user_baseline(user_id: str) -> dict:
    """获取用户感知基线——过去N轮的平均状态。
    返回 None 表示历史数据不足（<3轮）。
    """
    _load_history()
    entries = list(_perception_history.get(user_id, []))
    if len(entries) < 3:
        return None
    n = min(len(entries), 10)
    recent = entries[-n:]
    return {
        "avg_warmth": round(sum(e["warmth"] for e in recent) / n, 3),
        "avg_closeness": round(sum(e["closeness"] for e in recent) / n, 3),
        "avg_patience": round(sum(e["patience"] for e in recent) / n, 3),
        "avg_msg_len": round(sum(e["msg_len"] for e in recent) / n, 1),
        "avg_silence_score": round(sum(e.get("silence_score", 0) for e in recent) / n, 3),
        "sample_count": n,
    }


def enrich_with_history(user_id: str, msg: str, result: dict) -> dict:
    """用历史数据丰富当前感知结果：
      - 计算与用户基线的偏差
      - 检测异常降温/升温
      - 修正沉默重量（考虑用户平时的消息长度 + 沉默基线）
      - 修正距离感（考虑用户平时的亲近度）
      - 联动状态机
    返回扩展后的 result 字典。
    """
    baseline = get_user_baseline(user_id)

    # 存储当前轮（先存再查，这样基线包含当前轮）
    record_perception(user_id, msg, result)

    if not baseline:
        return result

    # ── 温暖度偏差：ta比平时冷了多少？ ──
    warmth_dev = result.get("warmth_level", 0.5) - baseline["avg_warmth"]
    if warmth_dev < -0.2:
        result["hidden_state"] = "明显降温·" + result.get("hidden_state", "中性")
        result["trend"] = "冷却中"
    elif warmth_dev > 0.2:
        result["trend"] = "回暖中"

    # ── 沉默重量基线偏差修正（v3 增强）──
    msg_len = len(msg.strip())
    avg_len = baseline["avg_msg_len"]
    avg_silence = baseline.get("avg_silence_score", 0.2)

    deviation_penalty = 0.0
    if avg_len > 6 and msg_len <= 2:
        deviation_penalty = 0.35  # 话痨突然沉默 → 极重
    elif avg_len > 6 and msg_len <= 4:
        deviation_penalty = 0.20
    elif avg_len > 3 and msg_len <= 2:
        deviation_penalty = 0.15

    if deviation_penalty > 0:
        new_score = min(1.0, result.get("silence_score", 0) + deviation_penalty)
        result["silence_score"] = new_score
        # 同步更新标签
        if new_score >= 0.70:
            result["silence_weight"] = "重"
        elif new_score >= 0.40:
            result["silence_weight"] = "中"

    # ── 距离感修正 ──
    closeness = result.get("closeness_level", 0.5)
    closeness_dev = closeness - baseline["avg_closeness"]
    if closeness_dev < -0.15:
        result["closeness_level"] = round(max(0.05, closeness - 0.08), 2)

    return result
