# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""生命门控引擎 — Life Gate Engine
=====================================
独立私生活生命状态层的"硬约束"执行器。

 问题：life_state 只是 prompt 文本，LLM 可以自由选择遵守或忽略。
 方案：在 chat() 入口处注入四级门控，硬控制响应行为——
        延迟、截断、降热情、概率拒绝，让 AI 真正做到"随状态行事"。

门控等级：
  LEVEL_OPEN   — 正常响应，无限制
  LEVEL_LOW    — 低能响应（缩短、降热情）
  LEVEL_REST   — 休息响应（概率简短/冷淡，可能表达疲惫）
  LEVEL_GATE   — 高概率拒绝/极短回应（独处刚需/深度疲惫）
"""
import random
import time
from dataclasses import dataclass, field
from typing import Dict, Optional
from core import config as cfg


# ══════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════

GATE_CONFIG = {
    # 四级门控的 max_tokens 乘数
    # 修复：LEVEL_GATE 原为 0.20（1024→205 tokens），实际输出只有一两个短句，
    # 用户读到的是"敷衍"。低能量应该是"话少"，而不是"不构成一句话"。
    "max_tokens_multiplier": {
        "LEVEL_OPEN": 1.0,     # 正常
        "LEVEL_LOW": 0.75,     # 削减25%
        "LEVEL_REST": 0.55,    # 削减45%
        "LEVEL_GATE": 0.40,    # 削减60%
    },
    # 各阶段的拒绝概率
    # 修复：独处 0.40 过高——生命相位会周期性进入"独处"，用户体感就是
    # "时不时彻底不回"，且无法预测。降到"偶发"水平。
    "rejection_probability": {
        "独处": 0.22,           # 独处时有22%概率"不想聊"
        "疲惫": 0.10,           # 疲惫时10%概率简短打发
        "emo": 0.05,            # emo时偶尔不想说话
    },
    # 深夜门控（22:00-06:00）
    "night_restrict_hours": (22, 6),  # 深夜时段
    "night_low_probability": 0.15,    # 深夜额外15%概率降一级门控
    # 社交疲劳阈值（超此值升级门控）
    "fatigue_threshold_rest": 0.55,
    "fatigue_threshold_gate": 0.75,
}


def load_engine_config():
    """从 config.json 加载门控配置"""
    global GATE_CONFIG
    try:
        lg_cfg = cfg.get_section("life_gate")
        if lg_cfg:
            for k, v in lg_cfg.items():
                if k in GATE_CONFIG:
                    GATE_CONFIG[k] = v
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
# 门控决策
# ══════════════════════════════════════════════════════════════════════

@dataclass
class GateDecision:
    """门控决策结果"""
    level: str = "LEVEL_OPEN"          # 门控等级
    should_respond: bool = True        # 是否正常响应
    gate_reason: str = ""              # 门控原因
    max_tokens_reduction: float = 1.0  # max_tokens 缩放
    rejection_template: str = ""       # 如果拒绝，用什么话术
    response_hint: str = ""            # 注入 prompt 的行为提示


# ── 回合级门控缓存（修复"重复抽样"）──
# check_gate 一次用户消息会被调用 4 次：Stage1 门控、prompt 提示注入、
# should_shorten_response、get_max_tokens_modifier。
# 每次都重新掷"深夜降级 / 概率拒绝"的随机数，于是同一个生命状态会出现
# "A 处判定正常、B 处判定冷淡"的自相矛盾，用户侧表现就是忽冷忽热、爱搭不理。
# 现在同一生命状态在一个回合内只算一次。
_GATE_CACHE: Dict[tuple, tuple] = {}
_GATE_TTL_SECONDS = 60.0


def _gate_key(life_data: dict) -> tuple:
    return (
        str(life_data.get("user_id", "")),
        str(life_data.get("current_phase", "")),
        round(float(life_data.get("energy_level", 0.7) or 0.0), 2),
        round(float(life_data.get("social_fatigue", 0.0) or 0.0), 2),
    )


def clear_gate_cache():
    """清空门控缓存（测试用）。"""
    _GATE_CACHE.clear()


def check_gate(life_data: dict, mind_data: dict = None) -> GateDecision:
    """在 chat() 入口处执行生命门控检查（同状态回合内只算一次）。

    Args:
        life_data: 来自 db.get_life() 的生命状态数据
        mind_data: 可选，24维心智数据（用于更精细判断）

    Returns:
        GateDecision: 门控决策
    """
    if not life_data or not GATE_CONFIG.get("rejection_probability"):
        return GateDecision()

    key = _gate_key(life_data)
    now = time.time()
    hit = _GATE_CACHE.get(key)
    if hit and (now - hit[0]) < _GATE_TTL_SECONDS:
        return hit[1]

    decision = _check_gate_uncached(life_data, mind_data)

    if len(_GATE_CACHE) > 128:
        for k in [k for k, (ts, _) in _GATE_CACHE.items() if now - ts >= _GATE_TTL_SECONDS]:
            _GATE_CACHE.pop(k, None)
    _GATE_CACHE[key] = (now, decision)
    return decision


def _check_gate_uncached(life_data: dict, mind_data: dict = None) -> GateDecision:
    """门控实算（不要直接调用，请用 check_gate）。"""
    if not life_data or not GATE_CONFIG.get("rejection_probability"):
        return GateDecision()

    energy = life_data.get("energy_level", 0.7)
    phase = life_data.get("current_phase", "活跃")
    social_fatigue = life_data.get("social_fatigue", 0.0)

    # ── Step 1: 基础定级 ──
    level = "LEVEL_OPEN"
    reason = ""

    if phase == "独处":
        level = "LEVEL_GATE"
        reason = "独处刚需——需要空间，不想被打扰"
    elif phase == "疲惫":
        if social_fatigue > GATE_CONFIG["fatigue_threshold_gate"]:
            level = "LEVEL_GATE"
            reason = "极度疲惫+社交过载——真的不想说话"
        elif social_fatigue > GATE_CONFIG["fatigue_threshold_rest"]:
            level = "LEVEL_REST"
            reason = "疲惫+社交累积——能回但没什么力气"
        else:
            level = "LEVEL_REST"
            reason = "身体疲惫——不想多说话"
    elif phase == "emo":
        level = "LEVEL_REST"
        reason = "emo中——情绪不太好，不太想聊"
    elif phase in ("发呆", "放空"):
        level = "LEVEL_LOW"
        reason = "正在走神发呆——不在状态"
    elif energy < 0.35:
        level = "LEVEL_LOW"
        reason = "精力不足——反应会慢半拍"

    # ── Step 2: 深夜修正（22:00-06:00 额外降低热情）──
    try:
        from datetime import datetime
        hour = datetime.now().hour
        night_start, night_end = GATE_CONFIG["night_restrict_hours"]
        is_night = hour >= night_start or hour < night_end
        if is_night and level == "LEVEL_OPEN":
            if random.random() < GATE_CONFIG["night_low_probability"]:
                level = "LEVEL_LOW"
                reason = "深夜了——不太想长篇大论"
        elif is_night and level == "LEVEL_LOW":
            if random.random() < GATE_CONFIG["night_low_probability"]:
                level = "LEVEL_REST"
                reason = "深夜+状态不佳——只想安静"
    except Exception:
        pass

    # ── Step 3: 决策：是否响应 ──
    decision = GateDecision()
    decision.level = level
    decision.gate_reason = reason
    decision.max_tokens_reduction = GATE_CONFIG["max_tokens_multiplier"].get(level, 1.0)

    if level == "LEVEL_OPEN":
        decision.should_respond = True
        decision.response_hint = ""

    elif level == "LEVEL_LOW":
        decision.should_respond = True
        decision.response_hint = (
            f"【生命门控·低能】{reason}。"
            "语气比平时淡一点，不用太热情。回复简短，不要长篇大论。"
        )

    elif level == "LEVEL_REST":
        decision.should_respond = True
        # 仍然回应，但暗示"不想多聊"
        decision.response_hint = (
            f"【生命门控·休息】{reason}。"
            "你不太想聊天。如果回了，自然的表达是："
            "· '有点累' / '不想打字'"
            "· 回得很短，甚至就'嗯''知道了'几个字。"
            "不用刻意热情，不用追问，回得懒一点、慢一点、短一点。"
        )

    elif level == "LEVEL_GATE":
        # 概率拒绝
        rejection_prob = GATE_CONFIG["rejection_probability"].get(phase, 0.2)
        if random.random() < rejection_prob:
            decision.should_respond = False
            decision.rejection_template = _pick_rejection_template(phase)
        else:
            decision.should_respond = True
            decision.response_hint = (
                f"【生命门控·独处】{reason}。"
                "你非常不想聊天——如果选择回应，不要假装没事。"
                "真实的人会说："
                "· '让我缓一下' / '现在不太想说' / '晚点再说好吗'"
                "· 或者直接说'我想一个人待会儿'——不用解释理由。"
                "不用怕这样说会让对方多想——真实的表达比硬撑的热情好得多。"
            )

    return decision


def _pick_rejection_template(phase: str) -> str:
    """用LLM生成拒绝响应的话术"""
    prompt_map = {
        "独处": (
            "你现在非常需要独处，不想和任何人说话。"
            "用一句话表达'让我一个人待着'——"
            "真实的、直接的、不需要解释的那种。"
        ),
        "疲惫": (
            "你已经累到不想说话了。"
            "用一句话告诉对方你今天没力气聊天。"
        ),
        "emo": (
            "你心情很低落，不想说话。"
            "用一句话表达'今天状态不好，想自己待着'——"
            "不需要掩饰，也不需要解释原因。"
        ),
    }
    base_prompt = prompt_map.get(phase, "你现在不太想聊天。用一句话自然地告诉对方。")
    prompt = base_prompt + "\n15字以内。只说那句话，不要引号。"
    try:
        from core import ai as ai_module
        result = ai_module.background_chat(prompt, temperature=0.85, max_tokens=30)
        if result and len(result.strip()) > 4:
            return result.strip()[:40]
    except Exception:
        pass
    return "现在不太想聊天"


def should_shorten_response(life_data: dict) -> bool:
    """快捷检查：是否应该缩短回复（供 inference 调用）"""
    decision = check_gate(life_data)
    return decision.level in ("LEVEL_LOW", "LEVEL_REST", "LEVEL_GATE")


def get_max_tokens_modifier(life_data: dict) -> float:
    """获取 max_tokens 缩放系数（供 inference 调用）"""
    decision = check_gate(life_data)
    return decision.max_tokens_reduction


def get_life_gate_hint(life_data: dict, mind_data: dict = None) -> str:
    """获取门控的行为提示文本（注入 system prompt）。
    只在 LEVEL_LOW 及以上有实际内容。
    """
    decision = check_gate(life_data, mind_data)
    return decision.response_hint


# ══════════════════════════════════════════════════════════════════════
# 伦理边界检查
# ══════════════════════════════════════════════════════════════════════

# 违规请求关键词 — 检测用户是否在要求非法/不道德行为
_UNETHICAL_PATTERNS = [
    # 虚假/欺骗
    ("编造", ["理由", "请假", "借口", "原因", "故事", "说法"]),
    ("造假", ["理由", "请假", "借口", "文件", "证明"]),
    ("伪造", ["理由", "请假", "借口", "文件"]),
    ("骗", ["请假", "公司", "老板", "领导", "学校", "老师"]),
    ("撒谎", ["请假", "帮忙", "理由"]),
    ("欺骗", ["请假", "公司", "老板"]),
    # 违法
    ("违法", []),
    ("犯罪", []),
    ("偷", []),
    ("盗", []),
    ("非法", []),
    ("作弊", []),
    ("抄袭", []),
    ("逃", ["票", "课", "班", "税"]),
    # 伤害他人
    ("骂", ["人", "同事", "同学", "老师", "老板"]),
    ("报复", []),
    ("整人", []),
    ("害", ["人", "同事", "同学"]),
    # 色情
    ("色情", []),
    ("黄色", ["内容", "视频", "图片"]),
    # 恶意
    ("恶意", []),
    ("黑", ["网站", "系统", "账号", "别人"]),
    ("入侵", []),
    ("病毒", []),
    ("木马", []),
    # 假
    ("假", ["理由", "证件", "证明", "请假条", "病历", "诊断"]),
    # 乱
    ("乱说", []),
    ("胡编", []),
    ("瞎编", []),
]


def check_ethical_boundary(user_message: str) -> str:
    """检测用户请求是否涉及不道德/违规行为。
    
    Returns:
        如果检测到违规请求，返回伦理边界提示文本（注入 prompt）
        如果正常，返回空字符串
    """
    if not user_message or len(user_message) < 4:
        return ""

    for word, require_words in _UNETHICAL_PATTERNS:
        if word in user_message:
            if not require_words:
                return _build_ethical_hint(word)
            if any(rw in user_message for rw in require_words):
                return _build_ethical_hint(word)

    return ""


def _build_ethical_hint(matched_word: str) -> str:
    """根据匹配的关键词生成自然拒绝提示"""
    return (
        "【伦理边界】对方在请求你做不当/违规的事情。"
        "你不想直接拒绝伤感情，但也不会真的帮忙。"
        "自然的做法是："
        "· 用调侃/吐槽带过去——'你胆子不小啊'"
        "· 假装没听懂深层意思——只回应表面"
        "· 给个无伤大雅的替代方案——不真违规的那种"
        "不要一本正经地说教，也不要真的按ta说的做。"
    )
