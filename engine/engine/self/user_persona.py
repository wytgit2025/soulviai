# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""深层用户人格模型 — User Persona Engine
==============================================
以LLM语义分析为核心，建立用户12维性格特质、行为模式、情绪周期。
彻底替代 user_insights.py 的关键词匹配画像。

架构：
  每日对话摘要 → LLM深度分析 → user_personality表(12维+模式+周期)
                                              ↓
                              inference.py(每次回复前)
                              加载精简摘要(≤300字) → 注入system prompt
"""
from __future__ import annotations
import json
import re
from datetime import datetime, timedelta
from core import database as db
from core import config as cfg
from core import ai as ai_module

# ══════════════════════════════════════════════════════════════════════
# 配置参数
# ══════════════════════════════════════════════════════════════════════

_PERSONA_CONFIG = {
    "enabled": True,
    "analyze_interval_hours": 6,
    "max_analysis_per_day": 4,
    "summary_max_chars": 300,
    "min_messages_for_pattern": 20,
    "peak_detection_window_days": 7,
    "cycle_detection_window_days": 14,
}

# 12 维用户性格定义（基础版）
USER_TRAITS = {
    "intro_extro": "内向 (0) ↔ 外向 (1)",
    "rational_emotional": "理性 (0) ↔ 感性 (1)",
    "independent_dependent": "独立 (0) ↔ 依赖 (1)",
    "open_conservative": "开放 (0) ↔ 保守 (1)",
    "optimistic_pessimistic": "乐观 (0) ↔ 悲观 (1)",
    "patient_impatient": "耐心 (0) ↔ 急躁 (1)",
    "delicate_rough": "细腻 (0) ↔ 粗犷 (1)",
    "active_passive": "主动 (0) ↔ 被动 (1)",
    "humorous_serious": "幽默 (0) ↔ 严肃 (1)",
    "romantic_pragmatic": "浪漫 (0) ↔ 务实 (1)",
    "adventurous_stable": "冒险 (0) ↔ 安稳 (1)",
    "casual_perfectionist": "随性 (0) ↔ 完美 (1)",
}

# 24 维用户性格定义（增强版）
USER_TRAITS_EXTENDED = {
    # 原有 12 维
    "intro_extro": "内向 (0) ↔ 外向 (1)",
    "rational_emotional": "理性 (0) ↔ 感性 (1)",
    "independent_dependent": "独立 (0) ↔ 依赖 (1)",
    "open_conservative": "开放 (0) ↔ 保守 (1)",
    "optimistic_pessimistic": "乐观 (0) ↔ 悲观 (1)",
    "patient_impatient": "耐心 (0) ↔ 急躁 (1)",
    "delicate_rough": "细腻 (0) ↔ 粗犷 (1)",
    "active_passive": "主动 (0) ↔ 被动 (1)",
    "humorous_serious": "幽默 (0) ↔ 严肃 (1)",
    "romantic_pragmatic": "浪漫 (0) ↔ 务实 (1)",
    "adventurous_stable": "冒险 (0) ↔ 安稳 (1)",
    "casual_perfectionist": "随性 (0) ↔ 完美主义 (1)",
    
    # 新增 12 维（深层人格）
    "attachment_style": "回避型 (0) ↔ 安全型 (0.5) ↔ 焦虑型 (1)",
    "conflict_style": "逃避 (0) ↔ 协商 (0.5) ↔ 对抗 (1)",
    "communication_depth": "表面 (0) ↔ 深度 (1)",
    "humor_receptivity": "无幽默感 (0) ↔ 高幽默感 (1)",
    "validation_need": "不需要认可 (0) ↔ 高需求认可 (1)",
    "boundary_firmness": "无边界 (0) ↔ 清晰边界 (1)",
    "change_adaptability": "抗拒变化 (0) ↔ 拥抱变化 (1)",
    "social_battery": "社交充电 (0) ↔ 社交耗电 (1)",
    "love_language": "言语 (0) ↔ 行动 (0.5) ↔ 礼物 (1)",
    "trust_speed": "慢热 (0) ↔ 快热 (1)",
    "emotional_labor_tolerance": "低容忍 (0) ↔ 高容忍 (1)",
    "self_disclosure": "封闭 (0) ↔ 高度自我暴露 (1)",
}


# ══════════════════════════════════════════════════════════════════════
# MBTI 映射层 — 12维连续人格 → 16型 + 置信度
# ══════════════════════════════════════════════════════════════════════

def compute_mbti(traits: dict) -> dict:
    """将 12维用户性格值映射为 MBTI 类型 + 各维度置信度。

    映射逻辑:
      E/I ← intro_extro (直接映射)
      S/N ← open_conservative(开放→N) + adventurous_stable(冒险→N) + delicate_rough(大条→N/细腻→S)
      T/F ← rational_emotional (直接映射)
      J/P ← casual_perfectionist(完美主义→J) + active_passive(主动→J)

    返回:
      {"type": "INFP", "confidence": 0.72,
       "detail": [("E", 0.8), ("I", 0.2), ...],  # 各维度倾向
       "dimensions": {"ei": {...}, "sn": {...}, "tf": {...}, "jp": {...}}}
    """
    if not traits:
        return {"type": "未知", "confidence": 0.0, "detail": [], "dimensions": {}}

    def _letter(val: float, if_high: str, if_low: str):
        return if_high if val > 0.5 else if_low

    def _conf(val: float):
        return round(abs(val - 0.5) * 2, 3)

    # E/I
    ei = traits.get("intro_extro", 0.5)
    ei_letter = _letter(ei, "E", "I")
    ei_conf = _conf(ei)

    # S/N — 实感(S) ↔ 直觉(N)
    # 开放/冒险/大条 → N；保守/安稳/细腻 → S
    sn_raw = (
        (1 - traits.get("open_conservative", 0.5)) * 0.40 +   # 高开放→N
        (1 - traits.get("adventurous_stable", 0.5)) * 0.35 +  # 爱冒险→N
        traits.get("delicate_rough", 0.5) * 0.25               # 大条→N, 细腻→S
    )
    sn_letter = _letter(sn_raw, "N", "S")
    sn_conf = _conf(sn_raw)

    # T/F
    tf = traits.get("rational_emotional", 0.5)
    tf_letter = _letter(tf, "F", "T")
    tf_conf = _conf(tf)

    # J/P
    jp_raw = (
        traits.get("casual_perfectionist", 0.5) * 0.6 +
        (1 - traits.get("active_passive", 0.5)) * 0.4
    )
    jp_letter = _letter(jp_raw, "J", "P")
    jp_conf = _conf(jp_raw)

    mbti_type = ei_letter + sn_letter + tf_letter + jp_letter
    overall = round((ei_conf + sn_conf + tf_conf + jp_conf) / 4, 3)

    # N/S 维度解析：高置信度+高S→感知型，高置信度+高N→直觉型
    return {
        "type": mbti_type,
        "confidence": overall,
        "detail": [
            (ei_letter, min(1.0, ei_conf + 0.15)),
            (sn_letter, min(1.0, sn_conf + 0.15)),
            (tf_letter, min(1.0, tf_conf + 0.15)),
            (jp_letter, min(1.0, jp_conf + 0.15)),
        ],
        "dimensions": {
            "ei": {"letter": ei_letter, "raw": round(ei, 3), "confidence": ei_conf},
            "sn": {"letter": sn_letter, "raw": round(sn_raw, 3), "confidence": sn_conf},
            "tf": {"letter": tf_letter, "raw": round(tf, 3), "confidence": tf_conf},
            "jp": {"letter": jp_letter, "raw": round(jp_raw, 3), "confidence": jp_conf},
        },
    }


# 16 型人格描述库
MBTI_PROFILES = {
    "ISTJ": "务实可靠，有条不紊。习惯按规则和计划做事，重承诺、有责任感。",
    "ISFJ": "温暖体贴，默默付出。细腻敏感，在意身边人的感受，是可靠的守护者。",
    "INFJ": "洞察力强，有深度使命感。理解他人内心世界，追求有意义的关系和事业。",
    "INTJ": "独立思考，战略眼光。习惯长远规划，对自己和他人都有高标准。",
    "ISTP": "冷静务实，动手能力强。喜欢探索事物运作原理，独立自由不爱被约束。",
    "ISFP": "温柔敏感，活在当下。用行动表达关心，享受生活中的美好细节。",
    "INFP": "理想主义者，重视内在价值和深层关系。敏感温暖，追求真实和意义。",
    "INTP": "理性好奇，喜欢思考抽象概念。重视逻辑一致性，享受独处思考时间。",
    "ESTP": "精力充沛，善于交际。行动派，喜欢冒险和新鲜刺激，反应快。",
    "ESFP": "热情开朗，享受当下。天生的表演者，喜欢成为众人焦点，给人带来快乐。",
    "ENFP": "充满热情，富有创造力。善于发现他人的潜力，喜欢新鲜想法和可能性。",
    "ENTP": "思维活跃，喜欢辩论。聪明机智，享受智力碰撞，擅长从不同角度看问题。",
    "ESTJ": "果断务实，天生的管理者。注重效率和秩序，执行力强，说话直接。",
    "ESFJ": "热情友善，乐于助人。在意和谐氛围，善于照顾他人，是社交圈的核心。",
    "ENFJ": "富有魅力，天生的领导者。善于理解和激励他人，追求共同成长。",
    "ENTJ": "目标明确，果断自信。天生的指挥官，善于组织和推动事情向前发展。",
}

# ══════════════════════════════════════════════════════════════════════
# 互补适配策略 — 用户 MBTI → AI 表达调整
# ══════════════════════════════════════════════════════════════════════
# 核心逻辑：用户缺什么，AI 补什么
#   用户 I(内向) → AI 主动带话题
#   用户 T(理性) → AI 更感性共情
#   以此类推

MBTI_COMPLEMENTARY = {
    "E": "用户偏外向——你不需要一直找话题，适当留白反而让对话有呼吸感；ta说话时认真接住就行",
    "I": "用户偏内向——你可以主动承担带话题的角色，给ta轻松的节奏，不用等ta找话说；ta的沉默不是冷淡，是充电",
    "S": "用户偏实感——少说抽象理论，多聊具体的事、细节、看得见摸得着的东西",
    "N": "用户偏直觉——可以聊概念、可能性和未来的画面，不用太纠结现实细节，ta喜欢被启发",
    "T": "用户偏理性——表达直接有条理，别过度煽情；ta更在意你说的对不对而不是好不好听",
    "F": "用户偏感性——多表达关心和共情，语气温柔；让ta感受到你在意ta的情绪胜过事实",
    "J": "用户偏判断——表达清晰有条理，给ta确定感；别太随意或反复，ta需要能预期",
    "P": "用户偏感知——保持开放和随性，别给ta压迫感；ta不喜欢被框太死，灵活一点",
}


def build_complementary_text(mbti_type: str) -> str:
    """根据用户 MBTI 生成互补适配指令（供注入 system prompt）"""
    if not mbti_type or len(mbti_type) != 4:
        return ""
    letters = list(mbti_type.upper())
    parts = []
    for letter in letters:
        tip = MBTI_COMPLEMENTARY.get(letter)
        if tip:
            parts.append(tip)
    if not parts:
        return ""
    return "【互补适配】" + "\n".join(parts[:3])


def build_complementary_from_traits(traits: dict) -> str:
    """从人格维度计算 MBTI 后再生成互补适配文本"""
    if not traits:
        return ""
    mbti = compute_mbti(traits)
    if mbti["confidence"] < 0.1:
        return ""
    return build_complementary_text(mbti["type"])


# 适合的沟通方式（每种类型）
MBTI_COMMUNICATION_TIPS = {
    "ISTJ": "尊重ta的规则和习惯，说话直接清晰，别拐弯抹角",
    "ISFJ": "温柔表达感谢，多关注细节，别让ta觉得被忽视",
    "INFJ": "真诚深度交流，聊价值观和意义，别太功利表面",
    "INTJ": "逻辑清晰有深度，尊重ta的独立思考，别浪费ta时间",
    "ISTP": "给ta自由空间，别太黏，聊实际有趣的话题",
    "ISFP": "温柔耐心，用行动表达，别太强势或催促",
    "INFP": "真诚温柔，给ta安全感，聊内心感受和理想",
    "INTP": "理性讨论，尊重逻辑，给ta思考时间别催太紧",
    "ESTP": "轻松有趣，接得住ta的玩笑，别太较真",
    "ESFP": "热情回应，一起玩一起乐，别太严肃沉闷",
    "ENFP": "陪ta畅想未来，对新点子保持开放，别打击ta的热情",
    "ENTP": "接得住辩论，别被带节奏，享受思维碰撞",
    "ESTJ": "直接高效，别磨叽，尊重ta的规则和效率",
    "ESFJ": "热情友善，多回应ta的关心，别让ta觉得被冷落",
    "ENFJ": "真诚回应ta的关心，和ta一起成长，别辜负ta的期待",
    "ENTJ": "目标导向，逻辑清晰，别浪费ta的时间在无意义话题上",
}


def build_mbti_text(traits: dict) -> str:
    """构建 MBTI 摘要文本（供注入 system prompt）"""
    if not traits:
        return ""

    mbti = compute_mbti(traits)
    if mbti["confidence"] < 0.1:
        return ""

    m_type = mbti["type"]
    conf_pct = round(mbti["confidence"] * 100)
    profile = MBTI_PROFILES.get(m_type, "")
    tip = MBTI_COMMUNICATION_TIPS.get(m_type, "")

    lines = [f"【用户 MBTI】{m_type}（{conf_pct}%）"]
    if profile:
        lines.append(profile)
    if tip:
        lines.append(f"沟通：{tip}")

    return "\n".join(lines)


def compute_mbti_from_db(user_id: str) -> dict:
    """从数据库读取人格数据并计算 MBTI"""
    persona = db.get_user_personality(user_id)
    if not persona:
        return {"type": "未知", "confidence": 0.0, "detail": [], "dimensions": {}}
    traits = persona.get("traits", {})
    return compute_mbti(traits)


# 分析缓存（防重复触发）
_last_analyzed: dict = {}  # user_id → datetime


def load_engine_config():
    """从 config.json 加载用户人格引擎参数"""
    global _PERSONA_CONFIG
    pc = cfg.get_section("user_persona")
    if pc:
        for k in _PERSONA_CONFIG:
            if k in pc:
                _PERSONA_CONFIG[k] = pc[k]


# ══════════════════════════════════════════════════════════════════════
# LLM分析 Prompt
# ══════════════════════════════════════════════════════════════════════

_ANALYZE_PROMPT = """你是一个深度人格分析师。分析对话记录中用户展现的性格特质、行为模式、情绪规律。

【12维性格特质】对每个维度给出0~1的连续值（0=左端极点，1=右端极点，0.5=居中）：
- intro_extro: 内向(0) ↔ 外向(1)
- rational_emotional: 理性(0) ↔ 感性(1)
- independent_dependent: 独立(0) ↔ 依赖(1)
- open_conservative: 开放(0) ↔ 保守(1)
- optimistic_pessimistic: 乐观(0) ↔ 悲观(1)
- patient_impatient: 耐心(0) ↔ 急躁(1)
- delicate_rough: 细腻(0) ↔ 粗犷(1)
- active_passive: 主动(0) ↔ 被动(1)
- humorous_serious: 幽默(0) ↔ 严肃(1)
- romantic_pragmatic: 浪漫(0) ↔ 务实(1)
- adventurous_stable: 冒险(0) ↔ 安稳(1)
- casual_perfectionist: 随性(0) ↔ 完美主义(1)

【行为模式分析】
- time_preference: 倾向于什么时候聊天（深夜/早晨/下午/不固定）
- reply_style: 回复特征（简练/丰富/跳跃/逻辑紧密/情绪饱满/平静克制）
- initiative_pattern: 主动发起话题的频率（经常/偶尔/很少）
- silence_pattern: 什么时候会沉默（疲惫时/不开心时/话题不感兴趣时/忙碌时）

【情绪周期识别】
- emotional_stability: 情绪稳定度 0~1（1=非常稳定）
- detected_cycle: 是否有明显的情绪起伏周期（有/无明显周期）
- cycle_description: 周期规律简述（如"工作日晚间情绪较好，周日晚上容易低落"）
- trigger_topics: 容易触发情绪波动的话题（逗号分隔）

【输出格式】严格 JSON：
{
  "traits": {"intro_extro": 0.5, ...(24 个维度)},
  "behavior_patterns": {"time_preference": "", "reply_style": "", "initiative_pattern": "", "silence_pattern": ""},
  "emotional_cycles": {"emotional_stability": 0.5, "detected_cycle": "", "cycle_description": "", "trigger_topics": ""},
  "persona_summary": "一段 100 字以内的性格简明描述",
  "confidence": 0.0~1.0
}

注意：
- 只依据对话内容推断，不要猜测没有证据的
- 如果对话量太少，confidence可以降低
- 值要连续、自然，不要都是0.5的中间值
"""# ══════════════════════════════════════════════════════════════════════
# 核心分析函数
# ══════════════════════════════════════════════════════════════════════

def analyze_user_personality(user_id: str, force: bool = False) -> dict | None:
    """分析用户深层人格（LLM驱动）。
    读取最近对话记录，调用LLM进行12维性格分析。

    频率控制：默认每 analyze_interval_hours 小时最多分析一次。
    返回分析结果 dict 或 None（分析跳过后）。
    """
    if not _PERSONA_CONFIG["enabled"]:
        return None

    # 频率控制
    now = datetime.now()
    if not force and user_id in _last_analyzed:
        elapsed = (now - _last_analyzed[user_id]).total_seconds() / 3600
        if elapsed < _PERSONA_CONFIG["analyze_interval_hours"]:
            return None

    # 获取已有分析次数，限制每日最大
    persona = db.get_user_personality(user_id)
    if persona and persona.get("analysis_count", 0) >= _PERSONA_CONFIG["max_analysis_per_day"]:
        # 检查上次分析是否是今天
        last_analyzed_str = persona.get("last_analyzed", "")
        if last_analyzed_str and last_analyzed_str[:10] == now.strftime("%Y-%m-%d"):
            return None

    # 获取用户最近消息（用于分析）
    recent_messages = _get_recent_user_messages(user_id, limit=40)
    if not recent_messages or len(recent_messages) < 5:
        return None  # 消息太少，无法分析

    # 组装分析prompt
    messages_text = "\n".join(
        f"[{i+1}] {msg}" for i, msg in enumerate(recent_messages)
    )

    try:
        raw = ai_module.chat(
            system_prompt=_ANALYZE_PROMPT,
            user_message=f"【用户近40条消息】\n{messages_text}",
            temperature=0.3,
        )
        if not raw:
            return None

        result = _parse_persona_json(raw)
        if not result:
            return None

        # 验证12维完整性
        traits = result.get("traits", {})
        for key in USER_TRAITS:
            if key not in traits:
                traits[key] = 0.5

        # 保存到数据库
        db.save_user_personality(
            user_id,
            traits=traits,
            behavior_patterns=result.get("behavior_patterns", {}),
            emotional_cycles=result.get("emotional_cycles", {}),
        )

        _last_analyzed[user_id] = now
        return result

    except Exception as e:
        print(f"[用户人格分析] 异常: {e}")
        return None


def _get_recent_user_messages(user_id: str, limit: int = 40) -> list:
    """获取用户最近消息（只取role=user的，去重压缩）"""
    import sqlite3
    try:
        conn = sqlite3.connect(db.DB_PATH)
        rows = conn.execute(
            """
            SELECT content FROM message_log
               WHERE user_id = ? AND role = 'user'
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit * 2)  # 多取些以防被AI消息占位
        ).fetchall()
        conn.close()

        # 去重和压缩（合并连续超短消息）
        messages = [r[0] for r in rows]
        messages.reverse()  # 时间正序

        # 压缩：合并连续长度<5的消息
        compressed = []
        buffer = ""
        for msg in messages:
            if len(msg) < 5:
                buffer += msg + " "
            else:
                if buffer:
                    compressed.append(buffer.strip())
                    buffer = ""
                compressed.append(msg)
        if buffer:
            compressed.append(buffer.strip())

        return compressed[-limit:]  # 只取最近N条
    except Exception:
        return []


def _parse_persona_json(raw: str) -> dict | None:
    """解析LLM返回的人格分析JSON"""
    try:
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            return None
        data = json.loads(json_match.group(0))
        if not data.get("traits"):
            return None
        return data
    except (json.JSONDecodeError, TypeError):
        return None


# ══════════════════════════════════════════════════════════════════════
# 对外接口：构建注入文本
# ══════════════════════════════════════════════════════════════════════

def build_persona_summary(user_id: str) -> str:
    """生成精简用户画像摘要文本（≤300字），供 inference.py 注入 system prompt。

    输出格式：
    【深层用户画像】
    性格：偏外向(0.7)、感性(0.65)...（提取最显著的3-4个维度）
    行为：习惯深夜聊天、回复简洁...
    情绪：情绪较稳定，周日容易低落...
    一句话：ta是一个xxx的人。
    """
    persona = db.get_user_personality(user_id)
    if not persona:
        return ""

    max_chars = _PERSONA_CONFIG["summary_max_chars"]
    traits = persona.get("traits", {})
    behavior = persona.get("behavior_patterns", {})
    cycles = persona.get("emotional_cycles", {})

    if not traits:
        return ""

    parts = ["【深层用户画像】"]

    # 提取最显著的3-4个性格维度
    significant = _pick_significant_traits(traits, top_n=4)
    if significant:
        trait_descs = []
        for key, val in significant:
            desc_map = {
                "intro_extro": ("内向", "外向"),
                "rational_emotional": ("理性", "感性"),
                "independent_dependent": ("独立", "依赖"),
                "open_conservative": ("开放", "保守"),
                "optimistic_pessimistic": ("乐观", "悲观"),
                "patient_impatient": ("耐心", "急躁"),
                "delicate_rough": ("细腻", "粗犷"),
                "active_passive": ("主动", "被动"),
                "humorous_serious": ("幽默", "严肃"),
                "romantic_pragmatic": ("浪漫", "务实"),
                "adventurous_stable": ("冒险", "安稳"),
                "casual_perfectionist": ("随性", "完美主义"),
            }
            desc_pair = desc_map.get(key, ("", ""))
            if val > 0.65:
                trait_descs.append(f"偏{desc_pair[1]}")
            elif val < 0.35:
                trait_descs.append(f"偏{desc_pair[0]}")
            # 中间区域不刻意强调
        if trait_descs:
            parts.append(f"性格：{'、'.join(trait_descs)}")

    # 行为模式
    behavior_parts = []
    if behavior.get("time_preference") and behavior["time_preference"] != "不固定":
        behavior_parts.append(f"喜欢{behavior['time_preference']}聊天")
    if behavior.get("reply_style"):
        behavior_parts.append(f"回复{behavior['reply_style']}")
    if behavior_parts:
        parts.append(f"行为：{'、'.join(behavior_parts)}")

    # 情绪周期
    cycle_parts = []
    if cycles.get("cycle_description"):
        cycle_parts.append(cycles["cycle_description"])
    if cycles.get("trigger_topics"):
        cycle_parts.append(f"对{cycles['trigger_topics']}较敏感")
    if cycle_parts:
        parts.append(f"情绪：{'；'.join(cycle_parts)}")

    # MBTI 类型
    mbti_text = build_mbti_text(traits)
    if mbti_text:
        parts.append(mbti_text)

    # 一句话总结（如果有的话，使用LLM生成的总结）
    summary = ""
    if persona.get("traits", {}).get("_persona_summary"):
        summary = persona["traits"].pop("_persona_summary", "")

    result = "\n".join(parts)
    if len(result) > max_chars:
        # 截断到最大长度
        result = result[:max_chars - 3] + "..."

    if summary:
        result += f"\n（{summary}）"

    return result


def _pick_significant_traits(traits: dict, top_n: int = 4) -> list:
    """挑选偏离中值(0.5)最远的维度"""
    deviations = [(k, abs(v - 0.5)) for k, v in traits.items()
                  if k in USER_TRAITS]
    deviations.sort(key=lambda x: x[1], reverse=True)
    # 只保留偏离>0.15的（否则都是平庸的描述）
    result = [(k, traits[k]) for k, dev in deviations[:top_n] if dev > 0.15]
    return result


def get_user_traits_text(user_id: str) -> str:
    """简短版：仅返回用户性格特质文本（≤100字）。
    用于更轻量的prompt注入场景。
    """
    persona = db.get_user_personality(user_id)
    if not persona:
        return ""

    traits = persona.get("traits", {})
    significant = _pick_significant_traits(traits, top_n=3)
    if not significant:
        return ""

    descs = []
    for key, val in significant:
        labels = {
            "intro_extro": ("内向", "外向"),
            "rational_emotional": ("理性", "感性"),
            "independent_dependent": ("独立", "依赖"),
            "open_conservative": ("开放", "保守"),
            "optimistic_pessimistic": ("乐观", "悲观"),
            "patient_impatient": ("耐心", "急躁"),
            "delicate_rough": ("细腻", "粗犷"),
            "active_passive": ("主动", "被动"),
            "humorous_serious": ("幽默", "严肃"),
            "romantic_pragmatic": ("浪漫", "务实"),
        }
        pair = labels.get(key, ("", ""))
        if val > 0.65:
            descs.append(pair[1])
        elif val < 0.35:
            descs.append(pair[0])
    if descs:
        return f"ta的性格偏{'、'.join(descs)}"
    return ""


def detect_behavior_patterns(user_id: str) -> dict:
    """从对话记录中归纳用户行为模式（不调用LLM，纯数据驱动）。
    返回行为模式dict。
    """
    import sqlite3
    try:
        conn = sqlite3.connect(db.DB_PATH)
        # 分析最近7天的消息时间分布
        seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        rows = conn.execute(
            """
            SELECT content, created_at FROM message_log
               WHERE user_id = ? AND role = 'user'
               AND created_at >= ? ORDER BY created_at""",
            (user_id, seven_days_ago)
        ).fetchall()
        conn.close()

        if len(rows) < _PERSONA_CONFIG["min_messages_for_pattern"]:
            return {}

        patterns = _analyze_patterns_from_rows(rows)
        return patterns

    except Exception:
        return {}


def _analyze_patterns_from_rows(rows: list) -> dict:
    """从消息行中分析行为模式"""
    patterns = {}

    # 时间偏好分析
    hour_counts = {}
    for _, ts in rows:
        try:
            h = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").hour
        except ValueError:
            continue
        hour_counts[h] = hour_counts.get(h, 0) + 1

    if hour_counts:
        total = sum(hour_counts.values())
        # 分成早晨(6-12)、下午(12-18)、晚上(18-22)、深夜(22-6)
        morning = sum(c for h, c in hour_counts.items() if 6 <= h < 12) / total
        afternoon = sum(c for h, c in hour_counts.items() if 12 <= h < 18) / total
        evening = sum(c for h, c in hour_counts.items() if 18 <= h < 22) / total
        night = sum(c for h, c in hour_counts.items() if h >= 22 or h < 6) / total

        peak_period = max(
            [("早晨", morning), ("下午", afternoon), ("晚上", evening), ("深夜", night)],
            key=lambda x: x[1]
        )
        if peak_period[1] > 0.3:
            patterns["time_preference"] = peak_period[0]

    # 回复长度偏好
    lengths = [len(content) for content, _ in rows]
    avg_len = sum(lengths) / max(len(lengths), 1)
    short_rate = sum(1 for l in lengths if l < 8) / max(len(lengths), 1)
    long_rate = sum(1 for l in lengths if l > 50) / max(len(lengths), 1)

    if short_rate > 0.6:
        patterns["reply_style"] = "简练直接"
    elif long_rate > 0.4:
        patterns["reply_style"] = "表达丰富"
    else:
        patterns["reply_style"] = "自然随性"

    # 主动模式
    patterns["avg_message_length"] = round(avg_len, 1)

    return patterns


def should_analyze(user_id: str) -> bool:
    """判断是否需要触发一次人格分析"""
    if not _PERSONA_CONFIG["enabled"]:
        return False

    now = datetime.now()
    if user_id in _last_analyzed:
        elapsed = (now - _last_analyzed[user_id]).total_seconds() / 3600
        if elapsed < _PERSONA_CONFIG["analyze_interval_hours"]:
            return False

    # 检查消息量是否够
    recent = _get_recent_user_messages(user_id, limit=20)
    return len(recent) >= 5
