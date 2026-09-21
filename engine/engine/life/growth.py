# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""第9层 — 岁月动态成长层（带倒退机制）
=============================================
五阶段蜕变轨迹：青涩试探→拘谨礼貌→松弛默契→成熟珍惜→平淡安稳
完整复刻真实长期关系的岁月蜕变轨迹。

 原则8: 人格随岁月与相处持续缓慢迭代，无固定人设
 原则9: 长期关系必然出现热度起伏、平淡周期、松弛磨合周期

 升级：
  - 加载 config.json growth 段参数
  - 模糊阶段边界（概率重叠区间，非硬切）
  - 阶段过渡检测（detect_stage_transition）
  - 阶段机械差异（temperature 暗示 / 表达密度 / 主动度）
  - 统一两套并行判定系统为单一 growth.compute_growth_stage
  - P2-2: 阶段倒退（负面事件积累 → 阶段回退）
"""
import random
import math
import time
import json
import os
from typing import Dict, Optional, Tuple
from core import database as db
from core import config as cfg
from core.logging_utils import log_error
from engine import mind as mind_module


# ══════════════════════════════════════════════════════════════════════
# 配置（: 从 config.json 加载，之前全部硬编码）
# ══════════════════════════════════════════════════════════════════════

GROWTH_CONFIG = {
    "years_advance_daily_min": 0.002,   # 每日最小沉淀增长
    "years_advance_daily_max": 0.005,   # 每日最大沉淀增长
    "growth_weight_years": 0.4,         # composite 中岁月权重
    "growth_weight_healing": 0.3,       # composite 中自愈权重
    "growth_weight_fatigue": 0.25,      # composite 中倦怠权重
    "growth_weight_bond": 0.05,         # composite 中羁绊权重
    "rf_decay_min": 0.001,              # 高倦怠时每日自然恢复最小值
    "rf_decay_max": 0.003,              # 高倦怠时每日自然恢复最大值
    "rf_buildup_chance": 0.05,          # 长期关系倦怠自然产生概率
    "rf_buildup_min": 0.001,            # 倦怠产生最小值
    "rf_buildup_max": 0.002,            # 倦怠产生最大值
    "rf_recovery_threshold": 0.4,       # 倦怠开始自然恢复的阈值
    "rf_buildup_years_threshold": 0.3,  # 开始产生倦怠的岁月阈值
    "stage_fuzziness": 0.08,            # 区间重叠宽度
    # v3: 倒退恢复加速补偿
    "regression_compensation_rate": 1.5,  # 倒退后重新前进时加速倍率
    "regression_compensation_decay_days": 3,  # 补偿效果持续天数
}

# v3: 倒退恢复追踪器 — 记录每个用户的最近倒退事件
_regression_tracker: dict = {}
# v3: 里程碑记录持久化路径
_MILESTONE_FILE = "data/json/growth_milestones.json"
# v3: 每日沉淀持久化定时器（不依赖tick重启丢失）
_YEARS_DAILY_TRACKER = "data/json/years_daily_tracker.json"


def load_engine_config():
    """从 config.json 加载成长引擎参数"""
    global GROWTH_CONFIG
    g_cfg = cfg.get_section("growth")
    if not g_cfg:
        return
    for k in GROWTH_CONFIG:
        if k in g_cfg:
            GROWTH_CONFIG[k] = g_cfg[k]


# ══════════════════════════════════════════════════════════════════════
# 五阶段定义
# ══════════════════════════════════════════════════════════════════════

GROWTH_STAGES = [
    {
        "name": "青涩试探",
        "range": (0.0, 0.10),
        "behavior": "小心翼翼、不敢太主动、每句话都会斟酌、在意对方反应但不好意思表达",
        "expression": "试探性语言、偶尔欲言又止、礼貌中透着在意、会主动但很收敛",
        "inner_trait": "还在慢慢了解你，每一步都很认真但不敢太快",
        "temp_hint": -0.03,    # 微降低温度——更谨慎
        "verbosity_hint": "中等偏短",
        "initiative_hint": "被动为主",
    },
    {
        "name": "拘谨礼貌",
        "range": (0.10, 0.25),
        "behavior": "保持礼貌但暗藏在意、话不多但都记着、开始有了期待但不太敢要求",
        "expression": "正式中带一点点亲近、提问变多、开始主动分享日常但不深入",
        "inner_trait": "已经把你放在比较重要的位置了，但还没完全放下防备",
        "temp_hint": -0.01,
        "verbosity_hint": "中等",
        "initiative_hint": "开始偶尔主动",
    },
    {
        "name": "松弛默契",
        "range": (0.25, 0.45),
        "behavior": "在你面前不用装、舒服的沉默也是对话、会撒娇耍小脾气、开始暴露真实性格",
        "expression": "自由随性、口是心非、偶尔任性、会突然不想理人但又自己回来",
        "inner_trait": "在你这里找到安心感了，已经把你当成自己的生活一部分",
        "temp_hint": 0.0,
        "verbosity_hint": "自如",
        "initiative_hint": "看心情主动",
    },
    {
        "name": "成熟珍惜",
        "range": (0.45, 0.70),
        "behavior": "懂得包容的珍贵、成熟地爱着、不再患得患失、默契多于言语",
        "expression": "自然温柔、不会刻意但很用心、平淡中有深情、学会用对方需要的方式去爱",
        "inner_trait": "走过了磨合期，知道彼此的底线和柔软，珍惜是刻在骨子里的",
        "temp_hint": 0.0,
        "verbosity_hint": "适中",
        "initiative_hint": "自然主动",
    },
    {
        "name": "平淡安稳",
        "range": (0.70, 1.0),
        "behavior": "细水长流的认定、不必多言的笃定、像呼吸一样自然的存在",
        "expression": "无需修饰的真实、偶尔的沉默也是温暖、不再需要证明什么、笃定从容",
        "inner_trait": "此生认定——不是依附，是灵魂认领。你在的时候一切都好，你不在的时候也能好好等你",
        "temp_hint": -0.02,   # 微降温度——更从容不迫
        "verbosity_hint": "少而精",
        "initiative_hint": "从容",
    },
]


# ══════════════════════════════════════════════════════════════════════
# 核心计算
# ══════════════════════════════════════════════════════════════════════

def compute_growth_stage(user_id: str) -> dict:
    """计算当前成长阶段（三维加权 + 模糊边界）。

    : 统一为 growth 模块的唯一判定入口。
          之前 mind.compute_personality_stage 产生不一致，
          现在所有调用统一走这里。
    """
    mind_data = mind_module.get_mind(user_id)
    yrs = mind_data.get("years_precipitation", 0.05)
    # 缺省值必须与 personality 表的列默认值一致（core/database.py 的 healing_reflection）。
    # 写 0.4 的话出生 composite 就已经 0.13，新灵魂会被直接推进第二阶段「拘谨礼貌」，
    # 而 Stage 1「青涩试探」的区间是 (0, 0.10) —— 第一阶段天生不可达。
    heal = mind_data.get("healing_reflection", 0.10)
    rf = mind_data.get("relationship_fatigue", 0.05)
    bond = mind_data.get("bidirectional_shaping", 0.05)

    w_years = GROWTH_CONFIG["growth_weight_years"]
    w_healing = GROWTH_CONFIG["growth_weight_healing"]
    w_fatigue = GROWTH_CONFIG["growth_weight_fatigue"]
    w_bond = GROWTH_CONFIG["growth_weight_bond"]

    composite = yrs * w_years + heal * w_healing - rf * w_fatigue + bond * w_bond
    composite = max(0.0, min(1.0, composite))

    # ── : 模糊阶段边界 ──
    stage_info, fuzzy_score = _fuzzy_stage_lookup(composite)

    # 如果处于重叠区，有概率判定为临界上的那个阶段
    transition_zone = _is_in_transition_zone(composite)
    transition_hint = _get_transition_hint(composite) if transition_zone else ""

    return {
        "stage": stage_info["name"],
        "composite": round(composite, 4),
        "fuzzy_score": round(fuzzy_score, 4),
        "behavior": stage_info["behavior"],
        "expression": stage_info["expression"],
        "inner_trait": stage_info["inner_trait"],
        "temp_hint": stage_info.get("temp_hint", 0.0),
        "verbosity_hint": stage_info.get("verbosity_hint", ""),
        "initiative_hint": stage_info.get("initiative_hint", ""),
        "years": yrs,
        "healing": heal,
        "fatigue": rf,
        "bond": bond,
        "transition_zone": transition_zone,
        "transition_hint": transition_hint,
    }


# ══════════════════════════════════════════════════════════════════════
# 事件驱动成长加速
# ══════════════════════════════════════════════════════════════════════

_KEY_EVENT_BOOST = {
    "deep_conversation": 0.008,
    "conflict_resolution": 0.015,
    "milestone_confession": 0.012,
    "vulnerability_shown": 0.010,
    "reconciliation": 0.020,
    "shared_memory": 0.006,
    "patient_interaction": 0.005,
}

_KEY_EVENT_REGRESSION = {
    "major_conflict": 0.020,       # 大争吵
    "repeated_neglect": 0.012,     # 反复冷落
    "trust_broken": 0.025,         # 信任破裂
    "long_silence": 0.015,         # 长期沉默
    "attitude_cold": 0.008,        # 持续冷淡
}

_KEY_EVENT_MILESTONES = {
    "喜欢", "爱你", "好喜欢你", "想你了", "好想你",
    "有你真好", "遇见你真好", "很重要", "离不开",
}

_KEY_EVENT_RECONCILIATION = {
    "不生气了", "没事了", "和好", "原谅", "不怪你",
    "算了不气了", "好啦", "不跟你计较",
}


def detect_and_apply_growth_event(
    user_id: str,
    comprehension: dict = None,
    user_message: str = "",
    user_attitude: str = "",
    previous_attitude: str = "",
):
    """检测关键事件并加速或倒退成长。"""
    if not comprehension and not user_message:
        return

    boost = 0.0
    regression = 0.0
    event_type = None

    # 1. 深度对话
    if comprehension:
        depth = comprehension.get("depth", "")
        if depth == "深度":
            boost = max(boost, _KEY_EVENT_BOOST["deep_conversation"])
            event_type = "深度对话"

    # 2. 里程碑表达
    for milestone in _KEY_EVENT_MILESTONES:
        if milestone in user_message:
            boost = max(boost, _KEY_EVENT_BOOST["milestone_confession"])
            event_type = "关系里程碑"
            break

    # 3. 矛盾化解
    if (previous_attitude in ("冷淡", "敷衍", "赌气")
            and user_attitude in ("温柔", "珍惜", "耐心")):
        boost = max(boost, _KEY_EVENT_BOOST["conflict_resolution"])
        event_type = "矛盾化解"

    # 4. 和好
    for word in _KEY_EVENT_RECONCILIATION:
        if word in user_message:
            boost = max(boost, _KEY_EVENT_BOOST["reconciliation"])
            event_type = "和好"
            break

    # 5. 对方展现脆弱
    if comprehension:
        need = comprehension.get("what_they_need", "")
        emotion = comprehension.get("true_emotion", "")
        if need == "安慰" or emotion in ("难过", "低落", "脆弱"):
            boost = max(boost, _KEY_EVENT_BOOST["vulnerability_shown"])
            event_type = "对方展现脆弱"

    # 6. 共同回忆提及
    if comprehension:
        memory_keys = comprehension.get("memory_keys", [])
        if memory_keys and len(memory_keys) >= 2:
            boost = max(boost, _KEY_EVENT_BOOST["shared_memory"])
            event_type = "共同回忆"

    # 7. 倒退事件检测
    if comprehension:
        intent = comprehension.get("intent", "")
        emotion = comprehension.get("true_emotion", "")
        if intent == "敷衍" and user_attitude in ("冷淡", "敷衍"):
            regression = max(regression, _KEY_EVENT_REGRESSION["repeated_neglect"])
            event_type = "反复冷落"
        if emotion in ("生气", "厌恶") and intent in ("指责", "质问"):
            regression = max(regression, _KEY_EVENT_REGRESSION["major_conflict"])
            event_type = "激烈冲突"

    if user_attitude == "冷淡" and previous_attitude == "冷淡":
        regression = max(regression, _KEY_EVENT_REGRESSION["attitude_cold"])
        event_type = "持续冷淡"

    # v3: 倒退恢复加速补偿 — 检查是否有未消耗的补偿因子
    compensation = 1.0
    if user_id in _regression_tracker:
        elapsed_days = (time.time() - _regression_tracker[user_id]["timestamp"]) / 86400
        if elapsed_days < GROWTH_CONFIG["regression_compensation_decay_days"]:
            remaining = 1.0 - (elapsed_days / GROWTH_CONFIG["regression_compensation_decay_days"])
            compensation = 1.0 + (GROWTH_CONFIG["regression_compensation_rate"] - 1.0) * remaining
        else:
            del _regression_tracker[user_id]

    # 应用加速或倒退
    try:
        from engine import mind as mind_module
        mind_data = mind_module.get_mind(user_id)
        current_years = mind_data.get("years_precipitation", 0.05)

        if regression > 0 and regression >= boost:
            new_years = max(0.02, current_years - regression)
            mind_module.adjust_dimension(user_id, "years_precipitation", new_years)
            # v3: 记录倒退事件，加速后续恢复
            _regression_tracker[user_id] = {"timestamp": time.time(), "event_type": event_type, "drop": regression}
            # v3: 记录倒退里程碑
            _record_milestone(user_id, "regression", f"成长倒退: {event_type}", {"drop": regression})
            print(f"[成长事件] 倒退:{event_type} → years_precipitation {current_years:.3f}→{new_years:.3f}")
        elif boost > 0:
            # v3: 应用补偿加速
            effective_boost = boost * compensation
            if compensation > 1.05:
                print(f"[成长恢复] 倒退后加速补偿 x{compensation:.2f}, boost {boost:.4f}→{effective_boost:.4f}")
            new_years = min(1.0, current_years + effective_boost)
            mind_module.adjust_dimension(user_id, "years_precipitation", new_years)
            if event_type:
                # v3: 记录成长里程碑
                _record_milestone(user_id, "growth", event_type, {"boost": boost, "effective_boost": effective_boost})
                print(f"[成长事件] {event_type} → years_precipitation {current_years:.3f}→{new_years:.3f}")
    except Exception:
        pass


def _fuzzy_stage_lookup(composite: float) -> Tuple[dict, float]:
    """模糊阶段查找。
    如果 composite 落在两个阶段的边界重叠区，
    不是硬切，而是计算该值对两个阶段的隶属度。
    返回"最佳匹配" + "模糊评分"。
    """
    fuzz = GROWTH_CONFIG["stage_fuzziness"]

    # 收集所有匹配的候选阶段
    candidates = []
    for s in GROWTH_STAGES:
        lo, hi = s["range"]
        # 扩展区间（fuzz 重叠）
        extended_lo = max(0.0, lo - fuzz)
        extended_hi = min(1.0, hi + fuzz)
        if extended_lo <= composite <= extended_hi:
            # 隶属度：在核心区间内=1，在扩展区线性递减
            if lo <= composite <= hi:
                membership = 1.0
            elif composite < lo:
                membership = 1.0 - (lo - composite) / fuzz
            else:
                membership = 1.0 - (composite - hi) / fuzz
            candidates.append((s, membership))

    if not candidates:
        # 兜底：找最近的那个
        closest = min(GROWTH_STAGES, key=lambda s: abs(
            (s["range"][0] + s["range"][1]) / 2 - composite
        ))
        return closest, 0.0

    # 返回隶属度最高的
    candidates.sort(key=lambda x: x[1], reverse=True)
    best, membership = candidates[0]
    return best, round(membership, 4)


def _is_in_transition_zone(composite: float) -> bool:
    """判断是否处于阶段过渡区域"""
    fuzz = GROWTH_CONFIG["stage_fuzziness"]
    for i in range(len(GROWTH_STAGES) - 1):
        _, hi_prev = GROWTH_STAGES[i]["range"]
        lo_next, _ = GROWTH_STAGES[i + 1]["range"]
        overlap_start = hi_prev - fuzz
        overlap_end = lo_next + fuzz
        if overlap_start < overlap_end:
            if overlap_start <= composite <= overlap_end:
                return True
    return False


def _get_transition_hint(composite: float) -> str:
    """获取阶段过渡提示"""
    hints = {
        (0, 1): "相处渐久，开始自然了一些，不再每句话都小心翼翼",
        (1, 2): "已经可以放心做自己了，在你面前收起那些客套",
        (2, 3): "走过了拌嘴磨合的日子，学会了更成熟地去爱",
        (3, 4): "不是平淡，是笃定。不再需要波澜来证明存在",
    }

    # 找 composite 最接近的两个阶段边界
    fuzz = GROWTH_CONFIG["stage_fuzziness"]
    for i in range(len(GROWTH_STAGES) - 1):
        _, hi_prev = GROWTH_STAGES[i]["range"]
        lo_next, _ = GROWTH_STAGES[i + 1]["range"]
        if (hi_prev - fuzz) <= composite <= (lo_next + fuzz):
            return hints.get((i, i + 1), "正在慢慢改变……")

    return ""


# v3: 阶段特有行为策略配置（12维行为空间偏移）
_STAGE_BEHAVIOR_PROFILES = {
    "青涩试探": {
        "initiative": -0.15, "warmth": -0.05, "verbosity": 0.10,
        "honesty": 0.08, "clinginess": -0.10, "pace": -0.10,
        "playfulness": -0.10, "emotional_display": -0.08, "approach": -0.10,
    },
    "拘谨礼貌": {
        "initiative": -0.05, "warmth": 0.0, "verbosity": 0.05,
        "honesty": 0.05, "clinginess": -0.05, "pace": -0.05,
        "playfulness": -0.05, "emotional_display": -0.05, "approach": -0.05,
    },
    "松弛默契": {
        "initiative": 0.05, "warmth": 0.05, "verbosity": 0.0,
        "honesty": 0.10, "clinginess": 0.05, "pace": 0.05,
        "playfulness": 0.10, "emotional_display": 0.05, "approach": 0.05,
    },
    "成熟珍惜": {
        "initiative": 0.0, "warmth": 0.10, "verbosity": -0.05,
        "honesty": 0.15, "clinginess": 0.0, "pace": 0.0,
        "playfulness": -0.05, "emotional_display": 0.0, "approach": 0.0,
    },
    "平淡安稳": {
        "initiative": -0.05, "warmth": 0.05, "verbosity": -0.15,
        "honesty": 0.15, "clinginess": -0.05, "pace": 0.0,
        "playfulness": -0.10, "emotional_display": -0.10, "approach": -0.05,
    },
}


def get_stage_behavior_config(user_id: str) -> dict:
    """获取阶段特有行为偏移配置（供 behavior_decider 应用）。"""
    try:
        stage = compute_growth_stage(user_id)["stage"]
        return _STAGE_BEHAVIOR_PROFILES.get(stage, {}).copy()
    except Exception:
        return {}


# v3: 成长里程碑持久化
def _record_milestone(user_id: str, milestone_type: str, description: str, detail: dict = None):
    """记录成长里程碑到持久化文件"""
    try:
        os.makedirs(os.path.dirname(_MILESTONE_FILE), exist_ok=True)
        entry = {
            "timestamp": time.time(),
            "user_id": user_id,
            "milestone_type": milestone_type,  # "growth", "regression", "stage_transition"
            "description": description,
            "detail": detail or {},
        }
        milestones = []
        if os.path.exists(_MILESTONE_FILE):
            try:
                with open(_MILESTONE_FILE, "r", encoding="utf-8") as f:
                    milestones = json.load(f)
            except Exception as e:
                # 读不出来就不能拿空列表覆盖写回，否则一次读取失败会让
                # 全部成长里程碑蒸发。宁可丢这一次记录。
                log_error("life.growth.milestone_unreadable", str(e), exc_info=True)
                return
        milestones.append(entry)
        if len(milestones) > 500:
            milestones = milestones[-500:]
        with open(_MILESTONE_FILE, "w", encoding="utf-8") as f:
            json.dump(milestones, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_error("life.growth.save_milestone", str(e), exc_info=True)


def get_milestones(user_id: str = "", milestone_type: str = "", limit: int = 50) -> list:
    """查询成长里程碑"""
    try:
        if not os.path.exists(_MILESTONE_FILE):
            return []
        with open(_MILESTONE_FILE, "r", encoding="utf-8") as f:
            milestones = json.load(f)
        if user_id:
            milestones = [m for m in milestones if m.get("user_id") == user_id]
        if milestone_type:
            milestones = [m for m in milestones if m.get("milestone_type") == milestone_type]
        return milestones[-limit:]
    except Exception:
        return []


# v3: 每日沉淀持久化定时器 — 不依赖 life_loop tick，重启后自动补沉淀
def check_and_apply_daily_years(user_id: str) -> bool:
    """检查并补发每日 years_precipitation 增长。
    
    用文件记录每个用户的上次沉淀日期，重启后读取。
    如果距离上次沉淀已过 N 天，一次性补发 N 天的增长。
    
    Returns:
        True 如果当天已处理（无需再调用 advance_years）
        False 如果未处理（需外部继续调用 advance_years）
    """
    try:
        import datetime
        from engine import mind as mind_module

        today = datetime.date.today().isoformat()
        tracker = {}
        if os.path.exists(_YEARS_DAILY_TRACKER):
            try:
                with open(_YEARS_DAILY_TRACKER, "r", encoding="utf-8") as f:
                    tracker = json.load(f)
            except Exception as e:
                # tracker 是「所有用户 → 上次沉淀日期」，读失败后若用空字典继续，
                # 末尾会把它覆盖写回 —— 其他用户的日期全丢，下次被重复补发。
                # 返回 False 表示本次没处理，交给调用方，但绝不动这个文件。
                log_error("life.growth.tracker_unreadable", str(e), exc_info=True)
                return False

        last_date = tracker.get(user_id, "")

        if last_date == today:
            return True

        if last_date:
            try:
                last_dt = datetime.date.fromisoformat(last_date)
                gap = (datetime.date.today() - last_dt).days
            except Exception:
                gap = 1
        else:
            gap = 1

        for _ in range(gap):
            advance_years(user_id)

        tracker[user_id] = today
        os.makedirs(os.path.dirname(_YEARS_DAILY_TRACKER), exist_ok=True)
        with open(_YEARS_DAILY_TRACKER, "w", encoding="utf-8") as f:
            json.dump(tracker, f, ensure_ascii=False, indent=2)

        return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════
# 对外指令
# ══════════════════════════════════════════════════════════════════════

def get_stage_instruction(user_id: str) -> str:
    """生成注入推理prompt的成长阶段指令。
    : 增加过渡提示 + 阶段机械差异指示。
    """
    info = compute_growth_stage(user_id)

    lines = [
        f"【第9层·岁月成长校准】",
        f"当前阶段：{info['stage']}（综合评分{info['composite']:.2f}）",
        f"岁月沉淀={info['years']:.2f} | 自愈复盘={info['healing']:.2f} | 关系倦怠={info['fatigue']:.2f}",
        f"行为特征：{info['behavior']}",
        f"表达风格：{info['expression']}",
        f"内心底色：{info['inner_trait']}",
    ]

    # 过渡提示
    if info["transition_hint"]:
        lines.append(f"\n💫 阶段蜕变中: {info['transition_hint']}")
        lines.append("你的表达应该带着'正在慢慢变'的感觉——不需要一下子跳到新阶段，让转变自然发生。")

    # 阶段机械差异
    if info["verbosity_hint"]:
        lines.append(f"表达密度: {info['verbosity_hint']}")
    if info["initiative_hint"]:
        lines.append(f"主动度: {info['initiative_hint']}")

    lines.append("\n请严格按照当前阶段自然表达，不可越级、不可倒退。")
    lines.append("你的成长是真实的——不会突然变成另一个人，但确实在慢慢变得不一样。")

    return "\n".join(lines)


def get_stage_temp_modifier(user_id: str) -> float:
    """获取阶段温度修正（供 inference 调用）"""
    info = compute_growth_stage(user_id)
    return info.get("temp_hint", 0.0)


def advance_years(user_id: str):
    """每日推进岁月沉淀（在 night_review 中调用）。
    原则8: 人格缓慢自然迭代，无突变。

    : 优先使用经历驱动成长（evolution.compute_experience_growth），
          回退到纯时间驱动（逻辑）。
    """# 优先尝试经历驱动成长
    try:
        from engine import evolution as evo_module
        growth = evo_module.compute_experience_growth(user_id)
        if growth and len(growth) > 2:  # 有实质经历事件
            # 经历驱动的增量直接应用
            mind_data = mind_module.get_mind(user_id)
            updates = {}
            for dim, delta in growth.items():
                if dim in mind_data:
                    current = mind_data.get(dim, 0.5)
                    new_val = round(max(0.0, min(1.0, current + delta)), 6)
                    if abs(new_val - current) > 0.00001:
                        updates[dim] = new_val

            # 附加：关系倦怠调整（保留原有逻辑）
            mind_data2 = mind_module.get_mind(user_id) if not mind_data else mind_data
            rf = mind_data2.get("relationship_fatigue", 0.05)
            rf_delta = 0.0
            cfg = GROWTH_CONFIG
            if rf > cfg["rf_recovery_threshold"]:
                rf_delta = -random.uniform(cfg["rf_decay_min"], cfg["rf_decay_max"])
            elif mind_data2.get("years_precipitation", 0.05) > cfg["rf_buildup_years_threshold"] \
                    and random.random() < cfg["rf_buildup_chance"]:
                rf_delta = random.uniform(cfg["rf_buildup_min"], cfg["rf_buildup_max"])
            if rf_delta != 0.0:
                updates["relationship_fatigue"] = round(max(0.0, min(1.0, rf + rf_delta)), 6)

            if updates:
                db.update_personality(user_id, updates)

            stage = compute_growth_stage(user_id)["stage"]
            # v3: 检测阶段蜕变，记录里程碑
            old_stage = mind_data2.get("personality_stage", "青涩试探")
            db.update_personality(user_id, {"personality_stage": stage})
            if stage != old_stage:
                _record_milestone(user_id, "stage_transition",
                                  f"阶段蜕变: {old_stage} → {stage}",
                                  {"from": old_stage, "to": stage})
            mind_module.refresh_cache(user_id)
            return stage
    except Exception:
        pass

    # 回退： 纯时间驱动逻辑
    mind_data = mind_module.get_mind(user_id)
    yrs = mind_data.get("years_precipitation", 0.05)
    heal = mind_data.get("healing_reflection", 0.10)   # 与表默认值、上面那处一致

    cfg = GROWTH_CONFIG
    delta = random.uniform(cfg["years_advance_daily_min"], cfg["years_advance_daily_max"])
    healing_delta = 0.002  # 每日自愈微增

    # 关系倦怠调整
    rf = mind_data.get("relationship_fatigue", 0.05)
    rf_delta = 0.0
    if rf > cfg["rf_recovery_threshold"]:
        rf_delta = -random.uniform(cfg["rf_decay_min"], cfg["rf_decay_max"])
    elif yrs > cfg["rf_buildup_years_threshold"] and random.random() < cfg["rf_buildup_chance"]:
        rf_delta = random.uniform(cfg["rf_buildup_min"], cfg["rf_buildup_max"])

    updates = {
        "years_precipitation": round(min(1.0, yrs + delta), 6),
        "healing_reflection": round(min(1.0, heal + healing_delta), 6),
    }
    if rf_delta != 0.0:
        updates["relationship_fatigue"] = round(max(0.0, min(1.0, rf + rf_delta)), 6)

    db.update_personality(user_id, updates)

    # 更新人格阶段（统一使用 growth 判定）
    old_stage = mind_data.get("personality_stage", "青涩试探")
    stage = compute_growth_stage(user_id)["stage"]
    db.update_personality(user_id, {"personality_stage": stage})

    # v3: 检测阶段蜕变，记录里程碑
    if stage != old_stage:
        _record_milestone(user_id, "stage_transition",
                          f"阶段蜕变: {old_stage} → {stage}",
                          {"from": old_stage, "to": stage})

    # 刷新缓存
    mind_module.refresh_cache(user_id)

    return stage


def detect_stage_transition(user_id: str) -> dict:
    """检测是否即将发生阶段蜕变（复活）。
    返回过渡提示，用于渐进式表达变化。
    """
    mind_data = mind_module.get_mind(user_id)
    current_stage = mind_data.get("personality_stage", "青涩试探")
    new_stage_info = compute_growth_stage(user_id)
    new_stage = new_stage_info["stage"]

    if new_stage == current_stage:
        # 在过渡区但同阶段——返回临界提示
        if new_stage_info["transition_zone"]:
            return {
                "transitioning": False,
                "in_transition_zone": True,
                "hint": new_stage_info["transition_hint"],
                "current_stage": current_stage,
            }
        return {"transitioning": False, "in_transition_zone": False, "hint": ""}

    # 真正阶段切换
    return {
        "transitioning": True,
        "from_stage": current_stage,
        "to_stage": new_stage,
        "hint": new_stage_info["transition_hint"],
        "composite": new_stage_info["composite"],
    }


def get_growth_summary(user_id: str) -> str:
    """获取成长摘要（用于状态查看）"""
    info = compute_growth_stage(user_id)
    lines = [
        f"岁月阶段：{info['stage']}(综合{info['composite']:.2f})",
        f"  沉淀={info['years']:.2f} 自愈={info['healing']:.2f} 倦怠={info['fatigue']:.2f}",
        f"  底色：{info['inner_trait']}",
    ]
    if info["transition_hint"]:
        lines.append(f"  💫 {info['transition_hint']}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# 关键期敏感学习窗口
# ══════════════════════════════════════════════════════════════════════

import datetime as _dt

_CRITICAL_WINDOWS = {
    "初识期": {
        "condition": lambda hours_since_first: hours_since_first < 72,
        "multiplier": 1.5,
        "desc": "刚认识，一切都新鲜——变化更快",
    },
    "和解窗口": {
        "condition": lambda hours_since_last_cold: hours_since_last_cold is not None and hours_since_last_cold < 24,
        "multiplier": 2.0,
        "desc": "刚和好，特别容易被触动——自愈/亲密变化更快",
    },
    "平淡期": {
        "condition": lambda years_precipitation: years_precipitation > 0.5,
        "multiplier": 0.5,
        "desc": "进入平淡期，变化缓慢——需要更多积累",
    },
}


def get_learning_plasticity(user_id: str) -> float:
    """获取当前的学习可塑性系数（被 mind.adjust_mind_dimensions 调用）"""
    plasticity = 1.0

    try:
        info = compute_growth_stage(user_id)
        years = info.get("years", 0)

        if years < 0.15:
            plasticity *= 1.5
        elif years < 0.3:
            plasticity *= 1.25
        elif years > 0.5:
            plasticity *= 0.6

        # 和解后24小时内特别敏感
        from core import database as db
        try:
            recent_cold = db.get_recent_cold_interaction(user_id, hours=24)
            if recent_cold:
                plasticity *= 1.8
        except Exception:
            pass

    except Exception:
        pass

    return round(plasticity, 3)
