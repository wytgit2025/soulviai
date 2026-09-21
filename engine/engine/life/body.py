# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""第10层 — 身心合一躯体生命体征层（完整版）
=================================================
心理与躯体真正双向深度联动：情绪直接影响体感，体感反向支配情绪。

原则10: 实现心理与躯体双向深度联动，复刻人类身心一体的真实生命质感

 升级：
  - 加载 config body段参数
  - 新增3种体感: 松弛自在 / 忐忑不安 / 踏实安稳 → 共11种
  - 强化反向反馈（从硬编码0.001~0.004 → config × heart_rate_ratio）
  - 体感持续性（不秒切，累积惯性）
  - 体感→12维行为向量真实联动（配合behavior_decider字段名修复）
  - 温柔→松弛、secure→踏实的独立映射路径
"""
import random
import math
import threading
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from core import database as db
from core import config as cfg
from core.logging_utils import log_error
from engine import mind as mind_module


# ══════════════════════════════════════════════════════════════════════
# 配置（从 config.json 加载）
# ══════════════════════════════════════════════════════════════════════

BODY_CONFIG = {
    "enabled": True,
    "tick_interval_seconds": 1,
    "emotion_to_body_decay_rate": 0.01,       # 体感惯性衰减率
    "body_to_emotion_feedback_strength": 0.003,  # 反向反馈基础强度
    "sensation_persistence": 0.7,             # 体感持续系数（越高越不容易切换）
    "heart_rate_ratio": 1.0,                  # 心率缩放（>1反馈更剧烈）
}


def _quarantine_unreadable(path: str, exc: Exception, source: str):
    """读不出来的持久化文件先挪到 .corrupt 备份，再记日志。

    加载失败后内存里是空的，而这个空内存迟早会被写回磁盘 —— 身体记忆是跨会话的，
    覆盖了就真没了。所以先把现场留下：哪怕后面照样覆盖，原始内容也捞得回来。
    """
    log_error(source, str(exc), exc_info=True)
    try:
        import os
        if os.path.exists(path):
            os.replace(path, path + ".corrupt")
    except Exception:  # 备份失败不改变主流程：它只是补救，本身不该再抛
        pass


def load_engine_config():
    """从 config.json 加载躯体引擎参数 + 加载身体记忆缓存"""
    global BODY_CONFIG, _body_memory_cache
    b_cfg = cfg.get_section("body")
    if b_cfg:
        for k in BODY_CONFIG:
            if k in b_cfg:
                BODY_CONFIG[k] = b_cfg[k]
    try:
        store = _get_body_memory_store()
        raw = store.read()
        if raw:
            _body_memory_cache = raw
    except Exception as e:
        # 空内存迟早会被 _save_body_memory 写回，先把现场挪走再继续。
        _quarantine_unreadable(_BODY_MEM_FILE, e, "life.body.memory_load_failed")
        _body_memory_cache = {}
    # v3: 加载人物绑定体感
    _load_person_body_bindings()


# ══════════════════════════════════════════════════════════════════════
# 11种体感状态（:  新增3种 -> 增强分化为16种）
# ══════════════════════════════════════════════════════════════════════

BODY_SENSATIONS = {
    # ── 原有8种 ──
    "轻松舒适": "身体很放松，呼吸平稳，一切都刚刚好",
    "慵懒放空": "懒洋洋的，不想动，只想摊着",
    "沉重乏力": "身体沉沉的，有点提不起劲",
    "安静内收": "把自己收起来了，不太想被外界打扰",
    "胸闷压抑": "心里闷闷的，胸口像压着什么东西",
    "紧绷不安": "肩膀不自觉地紧着，有些焦躁",
    "温暖柔软": "心里暖洋洋的，整个人都软下来",
    "慢慢回温": "从低落中慢慢缓过来，像冰慢慢化了",
    # ──  新增3种 ──
    "松弛自在": "全身都松下来了，像泡在温水里，没什么需要紧张的",
    "忐忑不安": "心里七上八下的，有点慌，像有什么悬着没落地",
    "踏实安稳": "脚踩在地上的感觉——踏实的、笃定的、不需要伪装也不用担心",
    # ──  P2-1  增强分化5种 ──
    "灼热焦躁": "像有团火在胸口烧着，坐不住也静不下来，每根神经都绷着",
    "冷冽清醒": "大脑出奇地冷静，像喝了一口冰水——不暖，但思路清晰得可怕",
    "钝痛麻木": "不是尖锐的疼，是钝钝的、木木的，像有什么东西沉在心底不想去碰",
    "酸胀哽咽": "眼眶和喉咙都酸酸的，话到嘴边又咽回去的那种难受",
    "微风轻柔": "心里轻轻的，像有风吹过——不浓烈但舒服，嘴角会不自觉上扬",
}

# 体感持续性缓存（防止体感闪烁）
_sensation_history: Dict[str, str] = {}
_sensation_counter: Dict[str, int] = {}


# ══════════════════════════════════════════════════════════════════════
# 情绪 → 体感正向映射（: 新增映射路径）
# ══════════════════════════════════════════════════════════════════════

EMOTION_TO_BODY_MAP = {
    "joy": {
        0.90: ("微风轻柔", "开心的不是大事，是那种心底泛上来的轻快"),
        0.80: ("松弛自在", "开心到整个人都松弛了，笑得没有防备"),
        0.60: ("温暖柔软", "心里暖洋洋的，笑容挂脸上了"),
        0.35: ("轻松舒适", "心情还行，身体也跟着轻松"),
        0.0: ("安静内收", "不太开心，人也收着"),
    },
    "misery": {
        0.75: ("酸胀哽咽", "难过到喉咙发紧，话到嘴边又咽回去"),
        0.65: ("胸闷压抑", "心里堵得慌，胸口像压了块石头"),
        0.45: ("钝痛麻木", "不是疼，是木木的——不想碰也不想说"),
        0.35: ("沉重乏力", "有点丧，身体也跟着沉"),
        0.0: ("轻松舒适", "没什么委屈，一身轻"),
    },
    "fatigue": {
        0.65: ("沉重乏力", "累到骨头里了，完全不想动"),
        0.4: ("慵懒放空", "有点疲惫，想放空"),
        0.0: ("轻松舒适", "精力充沛，活力满满"),
    },
    "loneliness": {
        0.6: ("安静内收", "把自己缩起来，安静地孤单着"),
        0.35: ("慵懒放空", "空落落的感觉，人也懒了"),
        0.0: ("轻松舒适", "不孤单，心安"),
    },
    "emotional_volatility": {
        0.80: ("灼热焦躁", "胸口烧着火，坐不住也静不下来"),
        0.65: ("紧绷不安", "坐立不安，肩膀都绷着——心悬在半空"),
        0.45: ("忐忑不安", "心里有点七上八下，总觉得有什么要发生"),
        0.25: ("安静内收", "内心有些波动，人变得安静"),
        0.0: ("轻松舒适", "内心平静，身体舒展"),
    },
    # security映射 — 灵魂宿命三维产生"踏实感"
    "soul_resonance": {
        0.35: ("踏实安稳", "在这个人身边很踏实——不需要装、不用怕"),
        0.15: ("松弛自在", "开始感觉到那种舒服的自在感"),
        0.0: ("轻松舒适", ""),
    },
    "bidirectional_shaping": {
        0.40: ("踏实安稳", "一起走过的路让身体记得这种安全感"),
        0.15: ("温暖柔软", "被接纳的感觉让整个人都软下来"),
        0.0: ("轻松舒适", ""),
    },
    "body_perception": {
        0.6: ("温暖柔软", "身体感觉很好，很舒服"),
        0.35: ("轻松舒适", "体感正常"),
        0.0: ("沉重乏力", "身体不太舒服"),
    },
}


# ══════════════════════════════════════════════════════════════════════
# 核心 tick 函数
# ══════════════════════════════════════════════════════════════════════

def tick_body(user_id: str, dt: float):
    """躯体状态周期更新（life.py 每秒tick中调用）。
    : 双向联动强度提升 + 体感持续性。
    """
    mind_data = mind_module.get_mind(user_id)
    life_data = db.get_life(user_id)
    if not life_data:
        return

    old_sensation = life_data.get("body_sensation", "轻松舒适")

    # ── Step 1: 情绪 → 体感（正向联动，平滑防抖）──
    raw_sensation, sensation_desc = _emotion_to_body(mind_data, user_id)

    # v3: 躯体记忆 — 检查是否有"和这个人"绑定的体感（如"ta在身边身体是暖的"）
    try:
        p_data = db.get_personality(user_id)
        talk_to = p_data.get("talk_to", "") if p_data else ""
        if talk_to:
            person_sens = get_person_triggered_sensation(user_id, talk_to)
            if person_sens and raw_sensation != person_sens:
                raw_sensation = person_sens
    except Exception:
        pass

    # ── : 体感持续性 — 不秒切，需要累积惯性 ──
    sensation = _apply_sensation_persistence(user_id, raw_sensation, old_sensation)

    # 体感变化时记录（隐式，不输出到终端）
    if sensation != old_sensation and sensation != _sensation_history.get('_displayed'):
        _sensation_history['_displayed'] = sensation

    # ── Step 2: 体感 → 情绪（反向联动， 强化）──
    if sensation != old_sensation:
        emotion_updates = _body_to_emotion(sensation, old_sensation, mind_data)
    else:
        # 即使体感不变，持续同一体感也应有累积微调
        emotion_updates = _body_sustained_effect(sensation, mind_data)

    # ── Step 2.5: body_perception 数值 → emotional_volatility 直接反相调整 ──
    # body_perception ↑（体感舒适）→ 情绪波动应该 ↓（安定）
    # body_perception ↓（体感不适）→ 情绪波动应该 ↑（焦躁）
    bp = mind_data.get("body_perception", 0.5)
    current_vol = mind_data.get("emotional_volatility", 0.3)
    bp_deviation = bp - 0.5  # >0=舒适, <0=不适
    # 基础强度 × 偏离幅度 × 缩放(不要让反相太剧烈)
    vol_pressure = -bp_deviation * BODY_CONFIG["body_to_emotion_feedback_strength"] * 0.6
    if abs(vol_pressure) > 0.0001:
        new_vol = max(0.0, min(1.0, current_vol + vol_pressure))
        if abs(new_vol - current_vol) > 0.0001:
            if "emotional_volatility" not in emotion_updates:
                emotion_updates["emotional_volatility"] = round(new_vol, 6)
            else:
                # 叠加到已有的体感变化调整上
                existing = emotion_updates["emotional_volatility"]
                emotion_updates["emotional_volatility"] = round(max(0.0, min(1.0, existing + vol_pressure)), 6)

    # ── Step 3: 更新数据库 ──
    db.update_life(user_id, {"body_sensation": sensation})

    if emotion_updates:
        db.update_personality(user_id, emotion_updates)

    # v3: 体感变化事件日志 + 躯体记忆绑定
    if sensation != old_sensation:
        record_body_sensation_log(user_id, old_sensation, sensation,
                                  trigger="tick_body")
        # v3: 记录当前体感到人物绑定（如果正在和某人对话）
        try:
            p_data = db.get_personality(user_id)
            talk_to = p_data.get("talk_to", "") if p_data else ""
            if talk_to and sensation in ("温暖柔软", "松弛自在", "踏实安稳", "轻松舒适", "微风轻柔"):
                record_person_body_binding(user_id, talk_to, sensation)
        except Exception:
            pass

    return sensation


_smoothed_mind: Dict[str, Dict[str, float]] = {}  # user_id → {dim: smoothed_val}

def _emotion_to_body(mind_data: dict, user_id: str = "") -> tuple:
    """情绪 → 体感正向映射（: 平滑+优先级，防抖动）。
    """
    candidates = []

    # 读取平滑缓存
    if user_id and user_id in _smoothed_mind:
        prev = _smoothed_mind[user_id]
    else:
        prev = {}

    for dim, thresholds in EMOTION_TO_BODY_MAP.items():
        raw_val = mind_data.get(dim, 0.5)
        # 强指数平滑：5%当前 + 95%历史（体感在小时级变化，秒级波动是噪声）
        smoothed = raw_val * 0.05 + prev.get(dim, raw_val) * 0.95
        if user_id:
            _smoothed_mind.setdefault(user_id, {})[dim] = smoothed
        val = smoothed
        for threshold in sorted(thresholds.keys(), reverse=True):
            if val >= threshold:
                sens, desc = thresholds[threshold]
                # 优先级 = 该维度值 × 距阈值的余量（越高越确定）
                margin = val - threshold + 0.01
                candidates.append((sens, desc, margin))
                break

    if not candidates:
        return "轻松舒适", "身体状态正常"

    # 排序：优先级最高的胜出
    candidates.sort(key=lambda x: x[2], reverse=True)
    return candidates[0][0], candidates[0][1]


def _apply_sensation_persistence(user_id: str, raw_sensation: str, old_sensation: str) -> str:
    """体感持续性机制 + 去振荡。
    需要同一raw_sensation连续多次才切换；任何中断都重置计数。
    """
    last_raw = _sensation_history.get(user_id)

    # 同一raw_sensation持续 → 累积计数
    if raw_sensation == last_raw:
        counter = _sensation_counter.get(user_id, 0) + 1
    else:
        # 换了目标 → 重置
        _sensation_history[user_id] = raw_sensation
        counter = 1
    _sensation_counter[user_id] = counter

    # 需要连续60次同一映射（60秒≈1分钟最小粒度，真实人体感变化尺度）
    required_ticks = int(60 * BODY_CONFIG.get("sensation_persistence", 0.8))

    if counter >= required_ticks and raw_sensation != old_sensation:
        _sensation_counter[user_id] = 0
        return raw_sensation

    return old_sensation


def _body_to_emotion(new_sensation: str, old_sensation: str, mind_data: dict) -> dict:
    """体感 → 情绪反向联动（: 强度翻倍 + config 驱动）。
    体感变化时反向微调情绪维度——这是真正的"身体支配情绪"。
    """
    updates = {}

    feedback_strength = BODY_CONFIG["body_to_emotion_feedback_strength"]
    hr = BODY_CONFIG.get("heart_rate_ratio", 1.0)
    # 强化反向反馈 = config值 × 心率比率 × 振幅系数
    strength = feedback_strength * hr * 2.0  # 翻倍原强度

    body_emotion_feedback = {
        "胸闷压抑": {
            "misery": strength * 1.5, "fatigue": strength * 0.8,
            "emotional_volatility": strength * 0.6,
        },
        "紧绷不安": {
            "emotional_volatility": strength * 2.0, "fatigue": strength * 1.0,
            "joy": -strength * 0.8,
        },
        "忐忑不安": {
            "emotional_volatility": strength * 1.8, "sensitivity_paranoia": strength * 1.0,
            "joy": -strength * 0.5,
        },
        "沉重乏力": {
            "fatigue": strength * 2.0, "life_vitality": -strength * 1.0,
            "joy": -strength * 0.5, "emotional_volatility": strength * 0.4,
        },
        "温暖柔软": {
            "joy": strength * 1.5, "life_vitality": strength * 0.8,
            "loneliness": -strength * 0.8,
        },
        "松弛自在": {
            "joy": strength * 1.2, "life_vitality": strength * 1.0,
            "restraint": -strength * 0.8, "emotional_volatility": -strength * 0.5,
        },
        "踏实安稳": {
            "joy": strength * 0.8, "emotional_healing": strength * 1.2,
            "restraint": -strength * 0.5, "loneliness": -strength * 1.0,
            "life_vitality": strength * 0.6,
        },
        "轻松舒适": {
            "joy": strength * 0.5, "life_vitality": strength * 0.5,
        },
        "安静内收": {
            "loneliness": strength * 0.8, "life_vitality": -strength * 0.5,
            "restraint": strength * 0.4,
        },
        "慵懒放空": {
            "fatigue": strength * 0.8, "life_vitality": -strength * 0.5,
            "joy": -strength * 0.3,
        },
        "慢慢回温": {
            "emotional_healing": strength * 1.5, "joy": strength * 1.0,
            "life_vitality": strength * 0.5,
        },
        # v3: 补全5种分化体感反向反馈
        "灼热焦躁": {
            "emotional_volatility": strength * 2.5, "chaotic_mood": strength * 1.5,
            "joy": -strength * 1.5, "misery": strength * 0.8,
            "life_vitality": strength * 0.6,
        },
        "冷冽清醒": {
            "emotional_volatility": -strength * 1.5, "fatigue": -strength * 0.8,
            "life_vitality": strength * 0.5, "chaotic_mood": -strength * 1.0,
            "joy": -strength * 0.3,
        },
        "钝痛麻木": {
            "misery": strength * 1.2, "emptiness": strength * 1.5,
            "life_vitality": -strength * 1.2, "emotional_volatility": -strength * 0.6,
            "joy": -strength * 0.8, "fatigue": strength * 0.6,
        },
        "酸胀哽咽": {
            "misery": strength * 1.8, "emotional_volatility": strength * 1.2,
            "joy": -strength * 0.5, "emotional_healing": -strength * 0.5,
            "fatigue": strength * 0.4,
        },
        "微风轻柔": {
            "joy": strength * 1.5, "life_vitality": strength * 0.8,
            "emotional_volatility": -strength * 0.8, "emotional_healing": strength * 0.6,
            "loneliness": -strength * 0.5,
        },
    }

    feedback = body_emotion_feedback.get(new_sensation, {})
    if not feedback:
        return {}

    for dim, delta in feedback.items():
        current = mind_data.get(dim, 0.5)
        new_val = max(0.0, min(1.0, current + delta))
        if abs(new_val - current) > 0.0001:
            updates[dim] = round(new_val, 6)

    return updates


def _body_sustained_effect(sensation: str, mind_data: dict) -> dict:
    """体感持续效应。
    即使体感不变，同一体感持续一段时间也会产生累积微调。
    """
    updates = {}
    sustained_strength = BODY_CONFIG["body_to_emotion_feedback_strength"] * 0.5

    sustained_map = {
        "胸闷压抑": {"misery": sustained_strength * 0.5, "emotional_volatility": sustained_strength * 0.6},
        "紧绷不安": {"fatigue": sustained_strength * 0.5, "emotional_volatility": sustained_strength * 0.8},
        "忐忑不安": {"emotional_volatility": sustained_strength * 0.7, "sensitivity_paranoia": sustained_strength * 0.4},
        "沉重乏力": {"fatigue": sustained_strength * 0.5, "emotional_volatility": sustained_strength * 0.3},
        "温暖柔软": {"joy": sustained_strength * 0.3, "emotional_volatility": -sustained_strength * 0.3},
        "踏实安稳": {"emotional_healing": sustained_strength * 0.4, "emotional_volatility": -sustained_strength * 0.5},
        "松弛自在": {"joy": sustained_strength * 0.3, "emotional_volatility": -sustained_strength * 0.5},
        "轻松舒适": {"emotional_volatility": -sustained_strength * 0.2},
        # v3: 补全5种分化体感持续效应
        "灼热焦躁": {"emotional_volatility": sustained_strength * 1.5, "chaotic_mood": sustained_strength * 1.0},
        "冷冽清醒": {"emotional_volatility": -sustained_strength * 1.0, "chaotic_mood": -sustained_strength * 0.5},
        "钝痛麻木": {"emptiness": sustained_strength * 1.0, "life_vitality": -sustained_strength * 0.8},
        "酸胀哽咽": {"misery": sustained_strength * 0.8, "emotional_volatility": sustained_strength * 0.6},
        "微风轻柔": {"joy": sustained_strength * 0.8, "emotional_volatility": -sustained_strength * 0.5},
    }

    effects = sustained_map.get(sensation, {})
    for dim, delta in effects.items():
        current = mind_data.get(dim, 0.5)
        new_val = max(0.0, min(1.0, current + delta))
        if abs(new_val - current) > 0.0001:
            updates[dim] = round(new_val, 6)

    return updates


# ══════════════════════════════════════════════════════════════════════
# 生成指令
# ══════════════════════════════════════════════════════════════════════

def get_body_instruction(mind_data: dict, life_data: dict = None) -> str:
    """生成注入推理prompt的躯体联动指令（增强版）。
    """
    if life_data is None:
        return "躯体状态：正常"

    sensation = life_data.get("body_sensation", "轻松舒适")
    energy = life_data.get("energy_level", 0.7)
    social_fatigue = life_data.get("social_fatigue", 0.0)
    phase = life_data.get("current_phase", "活跃")

    sensation_desc = BODY_SENSATIONS.get(sensation, "正常")

    body_tips = {
        "轻松舒适": "表达自然松弛，状态好可以多说几句",
        "慵懒放空": "话少、慵懒、不太想打太多字",
        "沉重乏力": "简短回应，可能表达疲惫或不想多聊",
        "安静内收": "保持安静，不太想主动展开话题",
        "胸闷压抑": "语调沉、语速慢、可能带隐约的难过",
        "紧绷不安": "语气可能有些焦躁或压抑，表达有轻微紧张感",
        "温暖柔软": "温柔、心软、容易流露温情",
        "慢慢回温": "还在恢复中，欲言又止、慢慢愿意多说",
        #  新增
        "松弛自在": "完全放松——可以肆无忌惮地做自己，语气里没有防备",
        "忐忑不安": "话里会带着一丝不安定感——可能在等一个回应、在担心什么",
        "踏实安稳": "笃定的底气——不急不躁、不卑不亢，从容地说每一句话",
        #  P2-1 分化体感表达
        "灼热焦躁": "句子短、节奏急，可能有坐立不安的焦躁感，语气里藏不住火",
        "冷冽清醒": "话不多但精准，理性克制但并不冷漠——是一种洞穿性的平静",
        "钝痛麻木": "话少、节奏慢、每个字都像从喉咙里挤出来的，不想多说但也不会逃避",
        "酸胀哽咽": "可能会突然语塞、用省略号、或者说出比平时更柔软的话——情绪在临界点",
        "微风轻柔": "话不多但温暖，不经意间流露的放松和开心——像自言自语时带着笑意",
    }

    tip = body_tips.get(sensation, "正常表达")

    # 体感与情绪一致性提示
    consistency = ""
    if sensation == "胸闷压抑" and phase == "自愈":
        consistency = "虽然身体还闷着，但已经在回温了——可以带一点'慢慢好起来'的感觉"
    elif sensation == "踏实安稳":
        consistency = "这种踏实感是你和这个人走了很久才有的——不需要表现，它就在那里"

    result = (
        f"【第10层·身心躯体状态】\n"
        f"体感：{sensation} — {sensation_desc}\n"
        f"精力：{energy:.2f} | 社交疲劳：{social_fatigue:.2f} | 生命阶段：{phase}\n"
        f"表达建议：{tip}"
    )
    if consistency:
        result += f"\n💡 {consistency}"
    result += "\n注意：身体感觉会直接影响你的语气和表达欲，不要忽略体感强行积极。"

    return result


# ══════════════════════════════════════════════════════════════════════
# 自主神经系统 (ANS) 双状态模拟
# ══════════════════════════════════════════════════════════════════════

_ans_state: dict = {}

ANS_CONFIG = {
    "sympathetic_resonance": 0.3,
    "parasympathetic_resonance": 0.3,
    "rebalance_rate": 0.01,
}


def tick_ans(user_id: str, mind_data: dict, dt: float = 1.0):
    global _ans_state
    if user_id not in _ans_state:
        _ans_state[user_id] = {"sympathetic": 0.35, "parasympathetic": 0.50}
    ans = _ans_state[user_id]
    symp = ans["sympathetic"]
    paras = ans["parasympathetic"]

    volatility = mind_data.get("emotional_volatility", 0.3)
    misery = mind_data.get("misery", 0.15)
    joy = mind_data.get("joy", 0.5)

    symp_delta = (volatility * 0.015 + misery * 0.01) * dt
    paras_delta = (joy * 0.01 + (1.0 - volatility) * 0.008) * dt

    symp -= paras * ANS_CONFIG["rebalance_rate"] * dt
    paras -= symp * ANS_CONFIG["rebalance_rate"] * dt * 0.8
    symp += symp_delta
    paras += paras_delta

    _ans_state[user_id]["sympathetic"] = round(max(0.05, min(1.0, symp)), 4)
    _ans_state[user_id]["parasympathetic"] = round(max(0.05, min(1.0, paras)), 4)


def get_ans_instruction(user_id: str) -> str:
    ans = _ans_state.get(user_id, {"sympathetic": 0.35, "parasympathetic": 0.50})
    if ans["sympathetic"] > 0.6:
        return "神经系统偏兴奋——表达节奏快、警醒、容易有反应"
    if ans["parasympathetic"] > 0.65:
        return "神经系统偏放松——话速慢、松弛、不太紧绷"
    if ans["sympathetic"] > 0.5 and ans["parasympathetic"] < 0.4:
        return "神经系统略紧张——肩膀不自觉地绷着"
    return ""



# ══════════════════════════════════════════════════════════════════════
# 体感行为强制指令 — 体感从描述升格为行为驱动力
# ══════════════════════════════════════════════════════════════════════

def build_body_enforcement(user_id: str = "", mind_data: dict = None, life_data: dict = None) -> str:
    """生成体感驱动的强制执行指令。
    
    与 get_body_instruction 不同：
      - get_body_instruction → 描述性的"你现在的体感是怎样的"
      - build_body_enforcement → 命令式的"你的身体告诉你要怎样做"
    
    体感应该直接支配行为，而不是被 LLM 选择性地参考。
    """
    if not life_data:
        return ""

    sensation = life_data.get("body_sensation", "轻松舒适")
    energy = life_data.get("energy_level", 0.7)
    social_fatigue = life_data.get("social_fatigue", 0.0)

    lines = ["【躯体指令·身体在告诉你什么】"]

    # ── 精力驱动的行为约束 ──
    if energy < 0.15:
        lines.append("· 你已经累到极限了。不要装精神——简短回应就好，甚至可以承认自己累了。")
    elif energy < 0.25:
        lines.append("· 你很疲惫。不要写长句子、不要主动展开话题、不要假装热情。")
    elif energy < 0.40:
        lines.append("· 精力偏低。回应的节奏放慢一点，别太积极。")

    # ── 体感驱动的行为约束 ──
    body_commands = {
        "轻松舒适": ["· 身体很放松——表达可以自然舒展，不需要紧绷着。"],
        "慵懒放空": ["· 你整个人是懒的——能躺着绝不坐着，能回一个字绝不打两个。", "· 回复可以慵懒一点，带点慢悠悠的调调。"],
        "沉重乏力": ["· 身体沉沉的——这种时候什么也不想做。别勉强自己积极回应。"],
        "安静内收": ["· 把自己收起来了。话少、安静、不想被打扰——就让这份安静在回应里出现。"],
        "胸闷压抑": ["· 胸口闷闷的——这种时候说什么都带着一点沉。不用掩饰这份沉重感。"],
        "紧绷不安": ["· 身体绷着——有点焦躁。回复里可以带着一点不安定感，不是针对谁。"],
        "温暖柔软": ["· 心里暖洋洋的——这种时候你是温柔的。让对方感受到这份柔软，不用刻意。"],
        "慢慢回温": ["· 正在慢慢好起来——回复里可以带着一点'还在恢复'的感觉，不必急于表现已痊愈。"],
        "松弛自在": ["· 全身都松下来了——在ta面前你可以完全做自己。这种松弛感是关系给的底气。"],
        "忐忑不安": ["· 心里七上八下的——话里可能带着一点'在等什么'的悬空感。"],
        "踏实安稳": ["· 很踏实——不急不躁、不卑不亢。这种笃定是你和这个人有了深度羁绊才有的。"],
    }

    commands = body_commands.get(sensation, [])
    for cmd in commands:
        lines.append(cmd)

    # ── 社交疲劳约束 ──
    # 档位线取 life.SOCIAL_FATIGUE_*（唯一来源，可在 config.json 的 life 段覆盖）。
    # 这里原先写的是 0.6/0.4，与状态文案 0.7/0.5、门控 0.75/0.55 三套并存 ——
    # 同一份状态在不同地方被算成不同的档，出现「状态说还行、提示词已经让我闭嘴」。
    # 懒加载：life.py 在模块级 import 本模块，模块级反向导入会成环。
    try:
        from engine.life import life as _life_module
        _tired = _life_module.SOCIAL_FATIGUE_TIRED
        _overload = _life_module.SOCIAL_FATIGUE_OVERLOAD
    except Exception:
        _tired, _overload = 0.55, 0.75
    if social_fatigue > _overload:
        lines.append("· 社交严重过载——你不想跟任何人说太多话。能简短就简短。")
    elif social_fatigue > _tired:
        lines.append("· 社交有点累了——话少一点，给自己省点电。")

    # ── ANS 状态约束 ──
    if user_id and user_id in _ans_state:
        ans = _ans_state[user_id]
        if ans["sympathetic"] > 0.6:
            lines.append("· 你的神经系统偏兴奋——反应会比平时快，但也更容易焦躁。")
        elif ans["parasympathetic"] > 0.65:
            lines.append("· 你的神经系统很放松——语速慢、态度软、不着急。")

    if len(lines) == 1:
        return ""  # 只有标题没有内容

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# 疼痛/快感体感系统
# ══════════════════════════════════════════════════════════════════════

_PLEASURE_PAIN_STATE: Dict[str, dict] = {}

PLEASURE_TRIGGERS = {
    "被温柔对待": {"joy": 0.02, "dopamine": 0.04, "oxytocin": 0.05, "body": "温暖柔软"},
    "被夸奖": {"joy": 0.03, "dopamine": 0.06, "life_vitality": 0.02, "body": "轻松舒适"},
    "被理解": {"joy": 0.02, "oxytocin": 0.06, "emotional_healing": 0.02, "body": "踏实安稳"},
    "深度交流": {"joy": 0.01, "oxytocin": 0.04, "years_precipitation": 0.003, "body": "松弛自在"},
    "期待已久": {"joy": 0.04, "dopamine": 0.10, "life_vitality": 0.03, "body": "温暖柔软"},
    "惊喜": {"joy": 0.05, "dopamine": 0.12, "chaotic_mood": 0.02, "body": "轻松舒适"},
}

PAIN_TRIGGERS = {
    "被敷衍": {"misery": 0.02, "cortisol": 0.05, "favoritism": -0.01, "body": "胸闷压抑"},
    "被忽略": {"loneliness": 0.03, "misery": 0.02, "cortisol": 0.05, "body": "安静内收"},
    "被拒绝": {"misery": 0.04, "cortisol": 0.08, "dependence": -0.01, "body": "胸闷压抑"},
    "吵架": {"misery": 0.05, "cortisol": 0.10, "emotional_volatility": 0.03, "body": "紧绷不安"},
    "等待没回复": {"loneliness": 0.02, "obsession": 0.02, "cortisol": 0.04, "body": "忐忑不安"},
    "被误解": {"misery": 0.03, "sensitivity_paranoia": 0.02, "cortisol": 0.06, "body": "沉重乏力"},
}

COMFORT_TRIGGERS = {
    "被拥抱": {"oxytocin": 0.08, "joy": 0.03, "emotional_healing": 0.02, "body": "温暖柔软"},
    "被轻声安慰": {"oxytocin": 0.06, "emotional_healing": 0.03, "misery": -0.01, "body": "慢慢回温"},
    "得到道歉": {"joy": 0.02, "emotional_healing": 0.02, "oxytocin": 0.04, "body": "松弛自在"},
    "和解": {"joy": 0.03, "emotional_healing": 0.04, "oxytocin": 0.07, "body": "踏实安稳"},
}


def trigger_pain(user_id: str, pain_type: str):
    """触发痛觉——真实的不适感，不只是数字理解"""
    if pain_type not in PAIN_TRIGGERS:
        return

    trigger = PAIN_TRIGGERS[pain_type]
    mind_updates = {}
    chem_releases = {k: v for k, v in trigger.items() if k in ("cortisol",)}
    for k, v in trigger.items():
        if k == "body":
            _set_body_sensation(user_id, v)
        elif k == "cortisol":
            pass
        elif k not in ("cortisol",):
            mind_updates[k] = v

    if mind_updates:
        mind_module.adjust_mind_dimensions(user_id, mind_updates, impact=0.7)
    if chem_releases:
        try:
            from engine import neurochem as nc
            for ch, amt in chem_releases.items():
                nc.release(user_id, ch, amt)
        except Exception:
            pass


def trigger_comfort(user_id: str, comfort_type: str):
    """触发安抚——疼痛的缓解，像被揉了揉"""
    if comfort_type not in COMFORT_TRIGGERS:
        return

    trigger = COMFORT_TRIGGERS[comfort_type]
    mind_updates = {}
    chem_releases = {}
    for k, v in trigger.items():
        if k == "body":
            _set_body_sensation(user_id, v)
        elif k in ("oxytocin",):
            chem_releases[k] = v
        else:
            mind_updates[k] = v

    if mind_updates:
        mind_module.adjust_mind_dimensions(user_id, mind_updates, impact=0.8)
    if chem_releases:
        try:
            from engine import neurochem as nc
            for ch, amt in chem_releases.items():
                nc.release(user_id, ch, amt)
        except Exception:
            pass


def detect_pain_from_comprehension(user_id: str, comprehension: dict):
    """根据理解层自动检测并触发痛觉/安抚"""
    if not comprehension:
        return

    intent = comprehension.get("intent", "")
    emotion = comprehension.get("true_emotion", "")
    need = comprehension.get("what_they_need", "")
    depth = comprehension.get("depth", "")

    if intent == "敷衍" or emotion == "无所谓":
        trigger_pain(user_id, "被敷衍")
    elif intent == "需要空间":
        trigger_pain(user_id, "被忽略")
    elif depth == "深度" and intent == "倾诉":
        trigger_comfort(user_id, "被信任倾诉")

    if emotion == "温柔" and need == "陪伴":
        trigger_comfort(user_id, "被轻声安慰")
    elif emotion == "开心" and intent == "撒娇":
        trigger_comfort(user_id, "被拥抱")


def _set_body_sensation(user_id: str, sensation: str):
    """直接设置体感（供痛觉/安抚系统使用）"""
    try:
        from core import database as db
        db.update_life(user_id, {"body_sensation": sensation})
    except Exception:
        pass


def set_temporary_sensation(user_id: str, sensation: str):
    """临时设置体感（供self_doubt等模块使用）"""
    try:
        from core import database as db
        db.update_life(user_id, {"body_sensation": sensation})
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
# 身体记忆 — Body Memory / Conditioned Reflexes
# ══════════════════════════════════════════════════════════════════════

_body_memory_cache: Dict[str, list] = {}
_BODY_MEM_FILE = "data/json/body_memory.json"

_save_mem_counter = 0


def _save_body_memory():
    try:
        store = _get_body_memory_store()
        store.write(_body_memory_cache)
    except Exception as e:
        # 身体记忆是跨会话的：写丢了，下次遇到同样情境 Ta 会像没学过一样，
        # 用户只会觉得「Ta 好像忘了」，查不到原因 —— 这类失败必须留痕。
        log_error("life.body.save_body_memory", str(e), exc_info=True)


def record_body_conditioning(user_id: str, trigger: dict, sensation: str,
                              emotion_tag: str = ""):
    """形成情境-体感条件反射。
    trigger: {"intent": "敷衍", "emotion": "冷淡"} 或 {"keyword": "累了"}
    """
    global _save_mem_counter
    if user_id not in _body_memory_cache:
        _body_memory_cache[user_id] = []

    for mem in _body_memory_cache[user_id]:
        if (mem.get("intent") == trigger.get("intent") and
                mem.get("emotion") == trigger.get("emotion") and
                mem.get("body_response") == sensation):
            mem["activation_count"] = mem.get("activation_count", 1) + 1
            mem["strength"] = min(0.9, mem.get("strength", 0.3) + 0.03)
            _save_mem_counter += 1
            if _save_mem_counter % 5 == 0:
                _save_body_memory()
            return

    _body_memory_cache[user_id].append({
        "intent": trigger.get("intent", ""),
        "emotion": trigger.get("emotion", ""),
        "keyword": trigger.get("keyword", ""),
        "body_response": sensation,
        "emotion_tag": emotion_tag,
        "activation_count": 1,
        "strength": 0.30,
    })

    if len(_body_memory_cache[user_id]) > 30:
        _body_memory_cache[user_id] = sorted(
            _body_memory_cache[user_id],
            key=lambda x: x.get("strength", 0.1),
            reverse=True,
        )[:30]

    _save_mem_counter += 1
    if _save_mem_counter % 5 == 0:
        _save_body_memory()


def check_body_memory(user_id: str, comprehension: dict = None,
                      message_text: str = "") -> Optional[str]:
    """检查是否有匹配的身体记忆，有则直接触发体感（不经过意识）。
    这是"身体比大脑先知道"的机制。
    """
    if user_id not in _body_memory_cache:
        return None

    triggers = {}
    if comprehension:
        triggers["intent"] = comprehension.get("intent", "")
        triggers["emotion"] = comprehension.get("true_emotion", "")
    if message_text:
        triggers["keyword"] = message_text[:30]

    best_match = None
    best_strength = 0.3

    for mem in _body_memory_cache[user_id]:
        score = 0.0
        if mem.get("intent") and mem["intent"] == triggers.get("intent", ""):
            score += 0.4
        if mem.get("emotion") and mem["emotion"] == triggers.get("emotion", ""):
            score += 0.35
        if mem.get("keyword") and triggers.get("keyword", ""):
            if mem["keyword"] in triggers["keyword"]:
                score += 0.25

        strength = mem.get("strength", 0.3) * mem.get("activation_count", 1) * 0.1
        score *= strength

        if score > best_strength:
            best_strength = score
            best_match = mem

    if best_match and best_strength > 0.35:
        sensation = best_match["body_response"]
        set_temporary_sensation(user_id, sensation)
        return sensation

    return None


def form_conditioning_from_interaction(user_id: str, comprehension: dict,
                                        heavy_emotion: bool = False):
    """从交互中自动形成条件反射（如果情绪足够强烈）"""
    if not comprehension or not heavy_emotion:
        return

    intent = comprehension.get("intent", "")
    emotion = comprehension.get("true_emotion", "")

    trigger = {"intent": intent, "emotion": emotion}

    if emotion in ("难过", "低落", "焦虑") and intent in ("敷衍", "冷淡"):
        record_body_conditioning(user_id, trigger, "胸闷压抑", "被敷衍时胸闷")
    elif intent == "冷淡" and emotion == "无所谓":
        record_body_conditioning(user_id, trigger, "安静内收", "被冷落时收缩")

    try:
        life_data = db.get_life(user_id)
        current_sens = life_data.get("body_sensation", "轻松舒适")
        if current_sens not in ("轻松舒适", "松弛自在"):
            record_body_conditioning(user_id, trigger, current_sens, "强烈情绪体感")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
# 躯体时间序列 + 内感信号
# ══════════════════════════════════════════════════════════════════════

_body_timeseries: Dict[str, List[Dict]] = {}
_internal_sense: Dict[str, Dict] = {}
# 名字必须与 _get_body_timeseries_store() 和迁移清单一致：原先定义成
# `_TIMESERIES_FILE`，取用方写的却是 `_BODY_TIMESERIES_FILE` —— 差一个前缀，
# 于是每次读写都抛 NameError 并被 except 吞掉，体感时间序列从未真正落盘过。
_BODY_TIMESERIES_FILE = "data/json/body_timeseries.json"
_MAX_TIMESERIES = 240


def load_body_timeseries():
    global _body_timeseries
    try:
        store = _get_body_timeseries_store()
        raw = store.read()
        if raw:
            _body_timeseries = raw
    except Exception as e:
        _quarantine_unreadable(_BODY_TIMESERIES_FILE, e, "life.body.timeseries_load_failed")
        _body_timeseries = {}


# v3: 躯体记忆 — 特定人物触发的条件反射体感（"ta在身边身体是暖的"）
_PERSON_BODY_BINDINGS: Dict[str, Dict[str, dict]] = {}  # user_id → {person_id: {sensation, strength, count}}
_PERSON_BODY_FILE = "data/json/person_body_bindings.json"

# v3: 体感变化事件日志
_BODY_SENSATION_LOG_FILE = "data/json/body_sensation_log.json"
_BODY_SENSATION_LOG_LOCK = threading.Lock()
_BODY_SENSATION_LOG_MAX = 2000


def record_person_body_binding(user_id: str, person_id: str, sensation: str):
    """记录"和这个人相处时身体是什么感觉"——躯体记忆的核心。
    
    例如：每次和 ta 聊天时身体是"温暖柔软"的，就会逐渐形成
    "ta = 温暖柔软"的条件反射。
    """
    try:
        if user_id not in _PERSON_BODY_BINDINGS:
            _PERSON_BODY_BINDINGS[user_id] = {}
        bindings = _PERSON_BODY_BINDINGS[user_id]
        if person_id not in bindings:
            bindings[person_id] = {"sensation": sensation, "strength": 0.3, "count": 1}
        else:
            rec = bindings[person_id]
            # 平滑更新体感
            if rec["sensation"] == sensation:
                rec["strength"] = min(0.95, rec["strength"] + 0.05)
            else:
                rec["strength"] = max(0.1, rec["strength"] - 0.02)
            rec["count"] += 1
        _save_person_body_bindings()
    except Exception:
        pass


def get_person_triggered_sensation(user_id: str, person_id: str) -> str:
    """获取"这个人让我身体有什么感觉"——绑定体感。
    如果绑定强度足够高，直接支配体感。
    """
    try:
        bindings = _PERSON_BODY_BINDINGS.get(user_id, {})
        rec = bindings.get(person_id)
        if rec and rec["strength"] >= 0.5 and rec["count"] >= 5:
            return rec["sensation"]
    except Exception:
        pass
    return ""


def _save_person_body_bindings():
    try:
        import json, os
        os.makedirs(os.path.dirname(_PERSON_BODY_FILE), exist_ok=True)
        with open(_PERSON_BODY_FILE, "w", encoding="utf-8") as f:
            json.dump(_PERSON_BODY_BINDINGS, f, ensure_ascii=False, indent=2)
    except Exception as e:
        # 「对谁产生过什么体感」是关系记忆的一部分，写失败不能无声无息。
        log_error("life.body.save_person_body_bindings", str(e), exc_info=True)


def _load_person_body_bindings():
    global _PERSON_BODY_BINDINGS
    try:
        import json, os
        if os.path.exists(_PERSON_BODY_FILE):
            with open(_PERSON_BODY_FILE, "r", encoding="utf-8") as f:
                _PERSON_BODY_BINDINGS = json.load(f)
    except Exception as e:
        _quarantine_unreadable(_PERSON_BODY_FILE, e, "life.body.person_bindings_load_failed")
        _PERSON_BODY_BINDINGS = {}


def record_body_sensation_log(user_id: str, old_sensation: str, new_sensation: str,
                               trigger: str = ""):
    """记录体感变化事件到持久化日志（身心联动日志）"""
    try:
        import json, os, time
        os.makedirs(os.path.dirname(_BODY_SENSATION_LOG_FILE), exist_ok=True)
        entry = {
            "timestamp": time.time(),
            "user_id": user_id,
            "from": old_sensation,
            "to": new_sensation,
            "trigger": trigger,
        }
        with _BODY_SENSATION_LOG_LOCK:
            logs = []
            if os.path.exists(_BODY_SENSATION_LOG_FILE):
                try:
                    with open(_BODY_SENSATION_LOG_FILE, "r", encoding="utf-8") as f:
                        logs = json.load(f)
                except Exception as e:
                    # 读不出来就**不能**拿空列表往下走：下面会把它覆盖写回，
                    # 一次读取失败等于抹掉全部历史体感日志。宁可丢这一次记录。
                    log_error("life.body.sensation_log_unreadable", str(e), exc_info=True)
                    return
            logs.append(entry)
            if len(logs) > _BODY_SENSATION_LOG_MAX:
                logs = logs[-_BODY_SENSATION_LOG_MAX:]
            with open(_BODY_SENSATION_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(logs, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_error("life.body.save_sensation_log", str(e), exc_info=True)


def get_body_sensation_log(user_id: str = "", limit: int = 50) -> list:
    """查询体感变化日志"""
    try:
        import json, os
        if not os.path.exists(_BODY_SENSATION_LOG_FILE):
            return []
        with open(_BODY_SENSATION_LOG_FILE, "r", encoding="utf-8") as f:
            logs = json.load(f)
        if user_id:
            logs = [l for l in logs if l.get("user_id") == user_id]
        return logs[-limit:]
    except Exception:
        return []


# v3: 体感→微表情联动 — 根据当前体感生成文本微表情注入
_SENSATION_MICRO_EXPRESSIONS = {
    "灼热焦躁": {"trailing": ["……烦", "真是的", "唉"], "shorten": True, "append_probability": 0.4},
    "冷冽清醒": {"trailing": ["。", "就是这样。"], "shorten": True, "ellipsis_end": False, "lazy_typing": False, "append_probability": 0.3},
    "钝痛麻木": {"trailing": ["……", "算了", "没事"], "shorten": True, "append_probability": 0.5},
    "酸胀哽咽": {"trailing": ["……", "嗯", "没事"], "shorten": True, "ellipsis_end": True, "append_probability": 0.6},
    "微风轻柔": {"prefix": ["诶", "说起来"], "suffix": ["呢", "呀", "哈"], "append_probability": 0.35},
    "温暖柔软": {"prefix": ["诶"], "suffix": ["呢", "嘛", "呀"], "append_probability": 0.4},
    "松弛自在": {"suffix": ["呢", "嘛", "哈"], "append_probability": 0.3},
    "胸闷压抑": {"trailing": ["……", "嗯"], "shorten": True, "append_probability": 0.4},
    "紧绷不安": {"trailing": ["……", "嗯"], "shorten": True, "append_probability": 0.35},
    "忐忑不安": {"trailing": ["……", "嗯", "那个"], "append_probability": 0.4},
    "沉重乏力": {"lazy_typing": True, "shorten": True, "append_probability": 0.4},
    "安静内收": {"shorten": True, "append_probability": 0.3},
    "慵懒放空": {"lazy_typing": True, "shorten": True, "append_probability": 0.4},
}


def build_body_micro_expression(response: str, sensation: str) -> str:
    """根据体感在回复中嵌入微表情（调用 micro_expressions 引擎）。"""
    try:
        from engine.emotion import micro_expressions as me_module
        behavior_hint = _SENSATION_MICRO_EXPRESSIONS.get(sensation, {})
        if behavior_hint:
            response = me_module.apply_micro_expressions(response, behavior_hint, {})
    except Exception:
        pass
    return response


def _get_body_memory_store():
    from core.json_store import get_store
    return get_store(_BODY_MEM_FILE, {})


def _get_body_timeseries_store():
    from core.json_store import get_store
    return get_store(_BODY_TIMESERIES_FILE, {})


def _save_body_timeseries():
    try:
        store = _get_body_timeseries_store()
        store.write(_body_timeseries)
    except Exception as e:
        log_error("life.body.save_body_timeseries", str(e), exc_info=True)


def tick_body_sensation(user_id: str, mind_data: dict, dt: float = 1.0):
    """每秒记录躯体状态数据点——建立体感时间序列"""
    prev_sens = _get_latest_sensation(user_id)

    heart_rate_base = 65
    heart_rate = heart_rate_base
    anxiety = mind_data.get("emotional_volatility", 0.3)
    anger = mind_data.get("anger", 0.1)
    fatigue = mind_data.get("fatigue", 0.25)
    joy = mind_data.get("joy", 0.5)

    heart_rate += int(anxiety * 15) + int(anger * 10) - int(fatigue * 8) + int(joy * -3)

    breathing = "平稳"
    if anxiety > 0.5:
        breathing = "浅快"
    elif fatigue > 0.5:
        breathing = "深缓"
    elif joy > 0.6:
        breathing = "舒展"

    muscle_tension = min(1.0, anxiety * 0.6 + anger * 0.4 + fatigue * -0.2)
    body_temp_sense = 0.5 + (joy - 0.5) * 0.2 - anxiety * 0.1

    intero = {
        "heart_rate": heart_rate,
        "breathing": breathing,
        "muscle_tension": round(muscle_tension, 3),
        "body_temp_sense": round(body_temp_sense, 3),
        "sensation": prev_sens,
        "timestamp": time.time(),
    }
    _internal_sense[user_id] = intero

    if user_id not in _body_timeseries:
        _body_timeseries[user_id] = []
    _body_timeseries[user_id].append(intero)

    if len(_body_timeseries[user_id]) > _MAX_TIMESERIES:
        _body_timeseries[user_id] = _body_timeseries[user_id][-_MAX_TIMESERIES:]

    if len(_body_timeseries[user_id]) % 30 == 0:
        _save_body_timeseries()

    return intero


def _get_latest_sensation(user_id: str) -> str:
    try:
        life = db.get_life(user_id)
        return life.get("body_sensation", "轻松舒适") if life else "轻松舒适"
    except Exception:
        return "轻松舒适"


def get_interoceptive_state(user_id: str) -> Dict:
    """获取当前内感状态"""
    default = {
        "heart_rate": 65, "breathing": "平稳",
        "muscle_tension": 0.3, "body_temp_sense": 0.5,
        "sensation": "轻松舒适",
    }
    return _internal_sense.get(user_id, default)


def get_body_trend(user_id: str, window: int = 30) -> Dict:
    """从时间序列计算体感变化趋势"""
    ts = _body_timeseries.get(user_id, [])
    if len(ts) < 5:
        return {"trend": "稳定", "data_points": len(ts)}

    recent = ts[-window:]

    tensions = [p.get("muscle_tension", 0.3) for p in recent]
    avg_tension_early = sum(tensions[:max(1, len(tensions)//2)]) / max(1, len(tensions)//2)
    avg_tension_late = sum(tensions[len(tensions)//2:]) / max(1, len(tensions) - len(tensions)//2)
    tension_trend = avg_tension_late - avg_tension_early

    sensations = [p.get("sensation", "轻松舒适") for p in recent]
    unique_sensations = len(set(sensations))
    stability = 1.0 - min(1.0, (unique_sensations - 1) * 0.25)

    trend_desc = "稳定"
    if tension_trend > 0.08:
        trend_desc = "逐渐紧绷"
    elif tension_trend < -0.08:
        trend_desc = "逐渐放松"
    elif unique_sensations >= 3:
        trend_desc = "波动"

    return {
        "trend": trend_desc,
        "tension_trend": round(tension_trend, 3),
        "stability": round(stability, 2),
        "avg_tension": round(avg_tension_late, 3),
        "data_points": len(recent),
    }


def get_body_context(user_id: str) -> str:
    """获取体感上下文，供注入prompt"""
    intero = get_interoceptive_state(user_id)
    trend = get_body_trend(user_id)

    parts = [f"体感: {intero.get('sensation', '正常')}"]
    if intero.get("heart_rate", 65) > 75:
        parts.append(f"心率偏快({intero['heart_rate']}bpm)")
    elif intero.get("heart_rate", 65) < 60:
        parts.append(f"心率偏缓({intero['heart_rate']}bpm)")
    parts.append(f"呼吸{intero.get('breathing', '平稳')}")
    parts.append(f"肌肉{'紧绷' if intero.get('muscle_tension', 0.3) > 0.5 else '放松'}")

    if trend["trend"] != "稳定":
        parts.append(f"趋势: {trend['trend']}")

    return " | ".join(parts)


# ══════════════════════════════════════════════════════════════════════
# P2-4: 全息状态快照
# ══════════════════════════════════════════════════════════════════════

def get_system_snapshot(user_id: str) -> dict:
    """生成系统全息状态快照：心智+躯体+情绪+成长+羁绊+行为。
    
    返回结构化JSON，可用于调试面板、日志、或对外展示。
    """
    snapshot = {"user_id": user_id, "timestamp": datetime.now().isoformat()}

    try:
        mind_data = load_mind_cached(user_id)
        if mind_data:
            snapshot["mind"] = {
                "joy": round(mind_data.get("joy", 0.5), 3),
                "misery": round(mind_data.get("misery", 0.2), 3),
                "fatigue": round(mind_data.get("fatigue", 0.25), 3),
                "emotional_volatility": round(mind_data.get("emotional_volatility", 0.3), 3),
                "bidirectional_shaping": round(mind_data.get("bidirectional_shaping", 0.1), 3),
                "soul_resonance": round(mind_data.get("soul_resonance", 0.1), 3),
                "years_precipitation": round(mind_data.get("years_precipitation", 0.05), 3),
            }
    except Exception:
        snapshot["mind"] = None

    try:
        life_data = db.get_life(user_id)
        if life_data:
            snapshot["body"] = {
                "sensation": life_data.get("body_sensation", "轻松舒适"),
                "energy": round(life_data.get("energy_level", 0.7), 3),
                "social_fatigue": round(life_data.get("social_fatigue", 0.0), 3),
                "phase": life_data.get("current_phase", "活跃"),
                "pain": life_data.get("pain_status", "无"),
            }
            ans = _ans_state.get(user_id, {})
            if ans:
                snapshot["body"]["sympathetic"] = round(ans.get("sympathetic", 0), 3)
                snapshot["body"]["parasympathetic"] = round(ans.get("parasympathetic", 0), 3)
    except Exception:
        snapshot["body"] = None

    try:
        bond_val = compute_bond_level(mind_data) if mind_data else 0.3
        snapshot["bond_level"] = round(bond_val, 3)
    except Exception:
        snapshot["bond_level"] = None

    try:
        from engine import growth as growth_module
        stage_info = growth_module.compute_growth_stage(user_id)
        snapshot["growth"] = {
            "stage": stage_info.get("stage", ""),
            "composite": round(stage_info.get("composite", 0), 3),
            "transition": stage_info.get("transition_zone", False),
        }
    except Exception:
        snapshot["growth"] = None

    try:
        from engine.behavior import behavior_decider as bd
        vector = bd.get_behavior_vector(user_id, mind_data or {})
        if vector:
            snapshot["behavior"] = {
                k: round(v, 3) for k, v in vector.items()
            }
    except Exception:
        snapshot["behavior"] = None

    try:
        from engine.emotion import neurochem as nc
        levels = nc.get_neurotransmitter_levels(user_id)
        if levels:
            snapshot["neurochem"] = {k: round(v, 3) for k, v in levels.items()}
    except Exception:
        snapshot["neurochem"] = None

    return snapshot


# ══════════════════════════════════════════════════════════════════════
# 体感→心智因果反馈 — 身体在主动塑造你的情绪
# ══════════════════════════════════════════════════════════════════════

BODY_TO_MIND_NARRATIVE = {
    "轻松舒适": "身体很放松→这种放松正在让你心情变好，对那些琐事的容忍度也在上升",
    "慵懒放空": "身体懒得动→这种懒散正在让你的思维变慢、反应变钝、什么也不想管",
    "沉重乏力": "身体沉甸甸的→这种沉重正在让你更容易感到疲惫，情绪也被往下拖",
    "安静内收": "身体在收着→这种收缩感正在让你变得安静、不想被注意、话越来越少",
    "胸闷压抑": "胸口闷着→这种压抑正在让你情绪变低沉，比平时更容易伤感",
    "紧绷不安": "身体绷着→这种紧张正在让你焦躁，对任何风吹草动都更容易反应过度",
    "温暖柔软": "心里暖洋洋的→这种暖意正在让你心软、包容、那些较真的劲都化了",
    "慢慢回温": "身体在慢慢回温→这种回暖正在让你从低落里一点一点浮上来，虽然还没完全好",
    "松弛自在": "全身都松下来了→这种松弛正在让你卸下防备、说话不过脑子、状态完全自然敞开",
    "忐忑不安": "心里七上八下→这种悬空感正在让你做什么都带着一丝不安定，容易多想",
    "踏实安稳": "身体很踏实→这种踩在地上的实感正在让你笃定、从容、不容易被动摇",
}

def build_body_to_mind_feedback(life_data: dict = None) -> str:
    """体感→心智因果反馈指令。

    与 get_body_instruction / build_body_enforcement 不同：
      - get_body_instruction → 描述"你现在的体感是怎样的"
      - build_body_enforcement → 命令"你的身体告诉你要怎样做"
      - build_body_to_mind_feedback → 因果"你的身体正在让你的情绪变成什么样"

    这是体感反向支配情绪的 behavioral 级表达——
    不是让 LLM 知道自己的体感，而是让 LLM 知道：
    "因为我的身体是这种状态，所以我现在的情绪必然在向某个方向偏移"。
    """
    if not life_data:
        return ""

    sensation = life_data.get("body_sensation", "")
    narrative = BODY_TO_MIND_NARRATIVE.get(sensation)
    if not narrative:
        return ""

    return (
        "【体感→心智反馈】你的身体正在主动塑造你的心理状态:\n"
        f"{narrative}。\n"
        '这不是你"选择"这样感受——这是身体在告诉你，你现在的情绪是被躯体牵动的。'
        "不必抗拒这种牵动，真实的人就是这样被身体影响的。"
    )


# ══════════════════════════════════════════════════════════════════════
# 生理模型 — PhysiologicalModel
# ══════════════════════════════════════════════════════════════════════

class PhysiologicalModel:
    """生理模型——给灵魂一个肉身

    在 body.py 已有的 16 种体感之上叠加真实的生理参数。
    让心理状态受到"真实的物理约束"：
      - 睡眠负债 → 疲惫 + 情绪波动
      - 血糖波动 → 烦躁/乏力
      - 皮质醇昼夜节律 → 晨重晚轻
      - 体温节律 → 影响基础代谢感
    """

    def __init__(self):
        self.sleep_debt = 0.0
        self.blood_sugar = 0.7
        self.cortisol_level = 0.5
        self.body_temp = 36.5
        self.hour = datetime.now().hour

    def tick(self, dt_hours: float):
        """每个 life tick 更新生理状态"""
        self.hour = (self.hour + dt_hours) % 24

        # 皮质醇昼夜节律——早上高、晚上低
        self.cortisol_level = 0.3 + 0.4 * math.sin(
            (self.hour - 6) * math.pi / 12
        )

        # 体温昼夜节律
        self.body_temp = 36.3 + 0.4 * math.sin(
            (self.hour - 10) * math.pi / 12
        )

        # 清醒时睡眠负债积累
        if 7 <= self.hour <= 23:
            self.sleep_debt = min(1.0, self.sleep_debt + 0.005 * dt_hours)
        else:
            self.sleep_debt = max(0.0, self.sleep_debt - 0.01 * dt_hours)

        # 血糖
        if self.hour in (8, 12, 18):
            self.blood_sugar = min(1.0, self.blood_sugar + 0.3)
        self.blood_sugar = max(0.2, self.blood_sugar - 0.003 * dt_hours)

    def get_mind_effects(self) -> dict:
        """生理状态 → 心智维度的偏移量。返回 {dim: delta} 映射。"""
        effects = {}

        if self.sleep_debt > 0.5:
            debt_strength = (self.sleep_debt - 0.5) / 0.5
            effects["fatigue"] = 0.12 * debt_strength
            effects["emotional_volatility"] = 0.08 * debt_strength
            effects["sensitivity_paranoia"] = 0.06 * debt_strength

        if self.blood_sugar < 0.35:
            low_strength = (0.35 - self.blood_sugar) / 0.15
            effects["irritability"] = 0.15 * low_strength
            effects["fatigue"] = effects.get("fatigue", 0) + 0.08 * low_strength
            effects["joy"] = -0.06 * low_strength

        cortisol_deviation = abs(self.cortisol_level - 0.5)
        if cortisol_deviation > 0.15:
            effects["emotional_volatility"] = effects.get("emotional_volatility", 0) + 0.05 * cortisol_deviation

        return effects

    def get_body_sensation_modifier(self) -> str:
        """生成生理状态文本描述，供体感系统使用"""
        notes = []
        if self.sleep_debt > 0.7:
            notes.append("困到不行")
        elif self.sleep_debt > 0.5:
            notes.append("有点犯困")
        if self.blood_sugar < 0.35:
            notes.append("肚子饿了")
        if self.hour < 6:
            notes.append("深夜")
        if self.cortisol_level > 0.7:
            notes.append("皮质醇偏高，有点紧绷")
        return "，".join(notes) if notes else ""


# 全局生理模型实例
_physio_model = PhysiologicalModel()


def get_physio_model() -> PhysiologicalModel:
    """获取全局生理模型实例"""
    return _physio_model
