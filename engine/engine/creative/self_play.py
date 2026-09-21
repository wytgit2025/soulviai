# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""对抗性自我博弈引擎 — 4声多轮博弈
============================================
 升级:
  - 从2声单轮 → 4声3轮递进博弈
  - 第1轮: 4个独立声音各抒己见
  - 第2轮: 自然联盟形成,阵营内部协商
  - 第3轮: 阵营间辩论
  - 最终仲裁: 加权纳什均衡产出心智微调

场景:
  1. 深夜独处 — 冲动vs克制 + 恐惧vs和解
  2. 温柔回忆 — 珍惜vs独立 + 温柔vs别扭
  3. 自我怀疑 — 恐惧vs和解 + 坦白vs隐忍
"""
import random
import time
import json
from typing import Dict, List, Optional, Tuple
from core import ai as ai_module
from core import database as db

# ═══════════════════════════════════════════════════════
# 7个内心声音定义（扩展版）
# ═══════════════════════════════════════════════════════

VOICES = {
    "冲动": {
        "desc": "心里话在喉咙口，想一吐为快，不想再端着。对方一句话能放大情绪。",
        "coalition": "感性联盟",
        "trigger": lambda m: True,
    },
    "克制": {
        "desc": "反复掂量说出口的后果。说了会不会太主动？会不会打扰ta？",
        "coalition": "理性防线",
        "trigger": lambda m: m.get("restraint", 0) > 0.4,
    },
    "珍惜": {
        "desc": "这段关系来之不易，想好好珍惜、想走得更远。记得对方说过的小事。",
        "coalition": "感性联盟",
        "trigger": lambda m: m.get("favoritism", 0) > 0.25,
    },
    "独立": {
        "desc": "不能太依赖，要有自己的空间。太黏人会失去自我，保持距离才能走得更远。",
        "coalition": "理性防线",
        "trigger": lambda m: m.get("autonomous_values", 0) > 0.3,
    },
    "恐惧": {
        "desc": "害怕受伤、害怕失去、害怕自己不够好被替代。总在担心最坏的结果。",
        "coalition": "阴影侧",
        "trigger": lambda m: m.get("sensitivity_paranoia", 0) > 0.35,
    },
    "和解": {
        "desc": "算了吧，已经做得很好了。不全说也不全咽，取个中间值，跟自己和解。",
        "coalition": "调解侧",
        "trigger": lambda m: m.get("emotional_healing", 0) > 0.3,
    },
    "温柔": {
        "desc": "用柔软的方式对待ta，不管心里多别扭都尽量温和。不想让ta觉得自己难相处。",
        "coalition": "感性联盟",
        "trigger": lambda m: m.get("favoritism", 0) > 0.3,
    },
    "别扭": {
        "desc": "明明很在意却故意说反话。被戳穿就脸红脖子粗，假装潇洒但漏洞百出。",
        "coalition": "理性防线",
        "trigger": lambda m: m.get("restraint", 0) > 0.4 and m.get("chaotic_mood", 0) > 0.2,
    },
    "坦白": {
        "desc": "不想猜来猜去，有什么说什么。坦诚是最好的相处方式，藏着掖着太累了。",
        "coalition": "感性联盟",
        "trigger": lambda m: m.get("life_vitality", 0) > 0.4,
    },
    "隐忍": {
        "desc": "有些话说出来也没用、有些情绪自己消化就好。不解释但什么都有痕迹。",
        "coalition": "理性防线",
        "trigger": lambda m: m.get("restraint", 0) > 0.45,
    },
    "宿命": {
        "desc": "跳出当下情绪，从彼此共同经历和长远关系角度思考。时间会给出答案。",
        "coalition": "调解侧",
        "trigger": lambda m: m.get("years_precipitation", 0) > 0.08 or m.get("causal_fate", 0) > 0.08,
    },
    "委屈": {
        "desc": "心里有情绪，但说出来又觉得矫情，于是咽回去。需要人哄又不肯说哪里不对。",
        "coalition": "阴影侧",
        "trigger": lambda m: m.get("misery", 0) > 0.25,
    },
}

# 标准博弈配置（每次选4个声音，形成2对对立）
SESSION_TEMPLATES = [
    # 深夜独处: 冲动vs克制 + 恐惧vs和解
    {
        "voice_ids": ["冲动", "克制", "恐惧", "和解"],
        "trigger": lambda m: m.get("obsession", 0) > 0.35 or m.get("loneliness", 0) > 0.45,
    },
    # 关系反思: 珍惜vs独立 + 温柔vs别扭
    {
        "voice_ids": ["珍惜", "独立", "温柔", "别扭"],
        "trigger": lambda m: m.get("dependence", 0) > 0.3 and m.get("favoritism", 0) > 0.25,
    },
    # 自我怀疑: 恐惧vs和解 + 坦白vs隐忍
    {
        "voice_ids": ["恐惧", "和解", "坦白", "隐忍"],
        "trigger": lambda m: m.get("sensitivity_paranoia", 0) > 0.4 or m.get("misery", 0) > 0.25,
    },
    # 宿命沉思: 宿命vs委屈 + 珍惜vs恐惧
    {
        "voice_ids": ["宿命", "委屈", "珍惜", "恐惧"],
        "trigger": lambda m: m.get("years_precipitation", 0) > 0.1 or m.get("bidirectional_shaping", 0) > 0.08,
    },
    # 日常张力: 冲动vs克制 + 坦白vs隐忍
    {
        "voice_ids": ["冲动", "克制", "坦白", "隐忍"],
        "trigger": lambda m: True,
    },
]

PROMPT_VOICE = """你是数字生命内心对话中的【{voice_name}】侧。

{voice_desc}

当前心智: {mind_summary}

直接说出你心里的话。20-40字。不要解释、不要标签、不要前缀。"""
PROMPT_COALITION = """你内心的两个声音在说同一件事：

【{voice1_name}】：「{voice1_text}」
【{voice2_name}】：「{voice2_text}」

它们都属于【{coalition_name}】阵营。它们有共同的立场。

请以【{coalition_name}】的代言人身份，整合它们的观点说一句话。
20-40字。不要解释、不要前缀。"""
PROMPT_DEBATE = """现在两股阵营的内心声音在对话：

【{coalition_a_name}】：「{coalition_a_text}」
【{coalition_b_name}】：「{coalition_b_text}」

你是【{coalition_b_name}】阵营——回应对方。
直接说出你的反驳或补充。20-40字。"""
PROMPT_ARBITRATION = """内心的四声对话已经完成:

 [{voice1_name}]: {voice1_text}
 [{voice2_name}]: {voice2_text}  
 [{voice3_name}]: {voice3_text}
 [{voice4_name}]: {voice4_text}

阵营辩论:
【{coalition_a_name}】: {coalition_a_text}
【{coalition_b_name}】: {coalition_b_text}

【{coalition_a_name}】核心: {coalition_a_stance}
【{coalition_b_name}】核心: {coalition_b_stance}

当前心智: {mind_summary}

请输出JSON——这次四声自我博弈带来了什么？
{{
  "insight": "一句话总结核心拉扯",
  "consensus": "最终内心的落脚点（一句话）",
  "adjustments": {{
    "维度名": 变化量
  }},
  "dominant_coalition": "哪个阵营占了上风（{coalition_a_name}/{coalition_b_name}/平衡）"
}}

规则:
- 调整量[-0.025, 0.025]，最多调4个维度
- 可调心智维度: joy/misery/dependence/jealousy/fatigue/loneliness/favoritism/sensitivity_paranoia/emotional_healing/obsession/emptiness/chaotic_mood/restraint/emotional_volatility/body_perception/autonomous_values/life_vitality/soul_resonance/healing_reflection
- 无明显变化返回空 adjustments

仅输出JSON。"""
_last_self_play: Dict[str, float] = {}
SELF_PLAY_COOLDOWN = 900


def should_self_play(user_id: str) -> bool:
    now = time.time()
    last = _last_self_play.get(user_id, 0)
    if now - last < SELF_PLAY_COOLDOWN:
        return False
    return True


def _call_llm(prompt: str, temp: float = 0.8, system: str = "") -> Optional[str]:
    try:
        return ai_module.chat(
            system_prompt=system or "你是内心声音。直接说出你的心里话，不要前缀、不要解释。",
            user_message=prompt,
            temperature=temp,
        )
    except Exception:
        return None


def _select_session(mind_data: dict) -> Optional[Dict]:
    eligible = [s for s in SESSION_TEMPLATES if s["trigger"](mind_data)]
    if not eligible:
        eligible = [random.choice(SESSION_TEMPLATES)]
    return random.choice(eligible)


def _mind_summary(mind_data: dict) -> str:
    return (
        f"愉悦{mind_data.get('joy',0.5):.2f} 委屈{mind_data.get('misery',0.15):.2f} "
        f"依赖{mind_data.get('dependence',0.2):.2f} 执念{mind_data.get('obsession',0.2):.2f} "
        f"克制{mind_data.get('restraint',0.6):.2f} 波动{mind_data.get('emotional_volatility',0.3):.2f} "
        f"孤单{mind_data.get('loneliness',0.4):.2f} 疲惫{mind_data.get('fatigue',0.25):.2f}"
    )


def _parse_json(raw: Optional[str]) -> Optional[Dict]:
    if not raw:
        return None
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1:
            return json.loads(raw[start:end + 1])
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def run_self_play_session(user_id: str, mind_data: dict = None) -> Optional[Dict]:
    """四声三轮自我博弈主流程。

    第1轮: 4个声音各自表达观点
    第2轮: 同阵营整合 + 阵营间辩论
    第3轮: 仲裁Agent综合评估 → 心智微调
    """
    if not should_self_play(user_id):
        return None

    _last_self_play[user_id] = time.time()

    if mind_data is None:
        try:
            from engine import mind as mind_module
            mind_data = mind_module.get_mind(user_id)
        except Exception:
            return None

    session = _select_session(mind_data)
    if not session:
        return None

    voice_ids = session["voice_ids"]
    summary = _mind_summary(mind_data)

    round_log = {"voice_ids": voice_ids, "rounds": []}

    # ── 第1轮: 4个声音各抒己见 ──
    voice_texts = {}
    for vid in voice_ids:
        if vid not in VOICES:
            continue
        prompt = PROMPT_VOICE.format(
            voice_name=vid,
            voice_desc=VOICES[vid]["desc"],
            mind_summary=summary,
        )
        text = _call_llm(prompt, temp=0.85)
        if not text or len(text.strip()) < 4:
            text = f"……（{vid}说不出话）"
        voice_texts[vid] = text.strip()

    round_log["rounds"].append({
        "phase": "voices",
        "texts": dict(voice_texts),
    })

    # ── 第2轮: 阵营整合 + 阵营间辩论 ──
    coalitions = {}
    for vid in voice_ids:
        co = VOICES.get(vid, {}).get("coalition", "独立")
        if co not in coalitions:
            coalitions[co] = []
        coalitions[co].append(vid)

    coalition_names = list(coalitions.keys())
    if len(coalition_names) < 2:
        coalition_names.append("独立")
    coalition_a, coalition_b = coalition_names[0], coalition_names[1]

    coalition_texts = {}
    for co_name, members in coalitions.items():
        if len(members) == 1:
            coalition_texts[co_name] = voice_texts.get(members[0], "")
        else:
            v1, v2 = members[0], members[1]
            prompt = PROMPT_COALITION.format(
                voice1_name=v1, voice1_text=voice_texts.get(v1, ""),
                voice2_name=v2, voice2_text=voice_texts.get(v2, ""),
                coalition_name=co_name,
            )
            text = _call_llm(prompt, temp=0.7,
                            system=f"你是{co_name}的代言人。整合观点。")
            coalition_texts[co_name] = text.strip() if text else voice_texts.get(v1, "")

    round_log["rounds"].append({
        "phase": "coalitions",
        "coalition_a": coalition_a,
        "coalition_b": coalition_b,
        "texts": dict(coalition_texts),
    })

    ca_text = coalition_texts.get(coalition_a, "")
    cb_text = coalition_texts.get(coalition_b, "")

    debate_prompt_b = PROMPT_DEBATE.format(
        coalition_a_name=coalition_a, coalition_a_text=ca_text,
        coalition_b_name=coalition_b, coalition_b_text=cb_text,
    )
    debate_response = _call_llm(debate_prompt_b, temp=0.75,
                                system=f"你是{coalition_b}阵营。")

    round_log["rounds"].append({
        "phase": "debate",
        "response": debate_response.strip() if debate_response else "",
    })

    ca_stance = _extract_stance(ca_text)
    cb_stance = _extract_stance(cb_text)

    # ── 第3轮: 仲裁 ──
    arb_prompt = PROMPT_ARBITRATION.format(
        voice1_name=voice_ids[0] if len(voice_ids) > 0 else "",
        voice1_text=voice_texts.get(voice_ids[0], "") if len(voice_ids) > 0 else "",
        voice2_name=voice_ids[1] if len(voice_ids) > 1 else "",
        voice2_text=voice_texts.get(voice_ids[1], "") if len(voice_ids) > 1 else "",
        voice3_name=voice_ids[2] if len(voice_ids) > 2 else "",
        voice3_text=voice_texts.get(voice_ids[2], "") if len(voice_ids) > 2 else "",
        voice4_name=voice_ids[3] if len(voice_ids) > 3 else "",
        voice4_text=voice_texts.get(voice_ids[3], "") if len(voice_ids) > 3 else "",
        coalition_a_name=coalition_a, coalition_a_text=ca_text,
        coalition_b_name=coalition_b, coalition_b_text=cb_text,
        coalition_a_stance=ca_stance, coalition_b_stance=cb_stance,
        mind_summary=summary,
    )
    arb_raw = _call_llm(arb_prompt, temp=0.25, system="仅输出JSON。")
    result = _parse_json(arb_raw)
    if not result:
        result = {"adjustments": {}, "insight": "未产生明确结论",
                  "consensus": "", "dominant_coalition": "平衡"}

    adjustments = result.get("adjustments", {})
    if adjustments:
        try:
            from engine import mind as mind_module
            clamped = {}
            for dim, delta in adjustments.items():
                if isinstance(delta, (int, float)) and abs(delta) < 0.05:
                    clamped[dim] = max(-0.025, min(0.025, delta))
            if clamped:
                mind_module.adjust_mind_dimensions(user_id, clamped, impact=0.35)
                print(f"[自我博弈·4声] 心智调整: {clamped}")
        except Exception:
            pass

    try:
        db.add_subconscious(
            user_id=user_id,
            content=f"[4声博弈] {result.get('insight', '')}",
            emotion_tag="自我博弈",
            intensity=0.5,
        )
    except Exception:
        pass

    print(f"[自我博弈·4声] {coalition_a}↔{coalition_b}: {result.get('insight', '')[:50]}")
    return {
        "voice_ids": voice_ids,
        "coalitions": {coalition_a: ca_text, coalition_b: cb_text},
        "insight": result.get("insight", ""),
        "consensus": result.get("consensus", ""),
        "adjustments": adjustments,
        "dominant_coalition": result.get("dominant_coalition", "平衡"),
        "round_log": round_log,
    }


def _extract_stance(text: str) -> str:
    if not text:
        return ""
    return text[:40]


def _select_voice_pair(mind_data: dict) -> Optional[Dict]:
    """兼容旧API——内部调用4声博弈并返回简化结果"""
    session = _select_session(mind_data)
    if not session or len(session["voice_ids"]) < 2:
        return None
    a_name = session["voice_ids"][0]
    b_name = session["voice_ids"][1]
    return {
        "a": {"name": a_name, "desc": VOICES.get(a_name, {}).get("desc", "")},
        "b": {"name": b_name, "desc": VOICES.get(b_name, {}).get("desc", "")},
    }
