# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""自主存在思维层 — 因果 x 时间 x 遗憾
: 整合 contradiction_engine 的四轮博弈结果，生成有思考痕迹的表达指令。
: 注入 world_model 因果链 + temporal_self 跨时间连续性 + regret 遗憾印记
"""
import random
from engine import contradiction_engine as ct_engine
from engine import self_model as sm_module
from engine import values as values_module
from engine import world_model as wm_module
from engine import temporal_self as ts_module
from engine import regret as regret_module
from engine import self_narrative as sn_module

# ── 标签→维度键 映射（用于多语言化显示） ──
_DIM_LABEL_TO_KEY = {
    "愉悦": "joy", "委屈": "misery", "依赖": "dependence", "吃醋": "jealousy",
    "疲惫": "fatigue", "孤单": "loneliness", "偏爱": "favoritism",
    "敏感": "sensitivity_paranoia", "自愈": "emotional_healing",
    "执念": "obsession", "空落": "emptiness", "混沌": "chaotic_mood",
    "生活感": "life_sense", "克制": "restraint", "情绪波动": "emotional_volatility",
    "岁月沉淀": "years_precipitation", "关系倦怠": "relationship_fatigue",
    "自愈复盘": "healing_reflection", "躯体感知": "body_perception",
    "自主三观": "autonomous_values", "生命活力": "life_vitality",
    "双向塑造": "bidirectional_shaping", "因果宿命": "causal_fate",
    "灵魂共鸣": "soul_resonance",
}


def _build_mind_groups(mind: dict, lang: str) -> str:
    """使用 i18n 翻译构建多语言心智维度显示"""
    from engine.i18n import mind_dim_name, t

    def dn(label: str) -> str:
        key = _DIM_LABEL_TO_KEY.get(label, label)
        return mind_dim_name(key, lang)

    return (
        f"{t('system.group_basic', lang)}: {dn('愉悦')}={mind.get('joy',0.5):.2f} {dn('委屈')}={mind.get('misery',0.15):.2f} "
        f"{dn('依赖')}={mind.get('dependence',0.2):.2f} {dn('吃醋')}={mind.get('jealousy',0.1):.2f} "
        f"{dn('疲惫')}={mind.get('fatigue',0.25):.2f} {dn('孤单')}={mind.get('loneliness',0.4):.2f}\n"
        f"{t('system.group_interpersonal', lang)}: {dn('偏爱')}={mind.get('favoritism',0.1):.2f} "
        f"{dn('敏感')}={mind.get('sensitivity_paranoia',0.35):.2f} "
        f"{dn('自愈')}={mind.get('emotional_healing',0.5):.2f}\n"
        f"{t('system.group_subconscious', lang)}: {dn('执念')}={mind.get('obsession',0.2):.2f} "
        f"{dn('空落')}={mind.get('emptiness',0.3):.2f} "
        f"{dn('混沌')}={mind.get('chaotic_mood',0.25):.2f}\n"
        f"{t('system.group_living', lang)}: {dn('生活感')}={mind.get('life_sense',0.5):.2f} "
        f"{dn('克制')}={mind.get('restraint',0.6):.2f} "
        f"{dn('情绪波动')}={mind.get('emotional_volatility',0.3):.2f}\n"
        f"{t('system.group_growth', lang)}: {dn('岁月沉淀')}={mind.get('years_precipitation',0.05):.2f} "
        f"{dn('关系倦怠')}={mind.get('relationship_fatigue',0.05):.2f} "
        f"{dn('自愈复盘')}={mind.get('healing_reflection',0.4):.2f}\n"
        f"{t('system.group_vital', lang)}: {dn('躯体感知')}={mind.get('body_perception',0.5):.2f} "
        f"{dn('自主三观')}={mind.get('autonomous_values',0.45):.2f} "
        f"{dn('生命活力')}={mind.get('life_vitality',0.6):.2f}\n"
        f"{t('system.group_fate', lang)}: {dn('双向塑造')}={mind.get('bidirectional_shaping',0.05):.2f} "
        f"{dn('因果宿命')}={mind.get('causal_fate',0.05):.2f} "
        f"{dn('灵魂共鸣')}={mind.get('soul_resonance',0.05):.2f}"
    )


def build_thinking_prompt(user_id: str, mind: dict, perception: dict, memory_context: str,
                          subconscious_leak: list = None, bond_level: float = 0.3,
                          active_flaws: list = None, comprehension: dict = None,
                          inner_os_text: str = "",
                          soul_profile_text: str = "",
                          user_profile_text: str = "",
                          lang: str = "zh") -> str:
    """构建九重思维博弈的 System Prompt（矛盾博弈版）
    优化版本：紧凑分组24维、合并记忆+潜意识、注入博弈轨迹
    """# ── 多语言支持 ──
    from engine.i18n import t as _t
    # ── 24维紧凑分组（节省~200 tokens, 多语言）──
    mind_groups = _build_mind_groups(mind, lang)

    # ── 九重思维权重（混沌动态）──
    weights = {
        "直觉本能": max(0.05, mind.get('life_vitality',0.6)*0.3 + (1-mind.get('restraint',0.6))*0.2),
        "利弊权衡": max(0.05, mind.get('restraint',0.6)*0.4 + mind.get('autonomous_values',0.45)*0.2),
        "混沌非理性": max(0.05, mind.get('chaotic_mood',0.25)*0.3 + mind.get('emotional_volatility',0.3)*0.3),
        "潜意识内耗": max(0.05, mind.get('sensitivity_paranoia',0.35)*0.3 + mind.get('misery',0.15)*0.2),
        "无意识杂念": max(0.03, mind.get('emptiness',0.3)*0.2 + mind.get('chaotic_mood',0.25)*0.15),
        "矛盾拉扯": max(0.05, mind.get('jealousy',0.1)*0.2 + mind.get('dependence',0.2)*0.2 + mind.get('restraint',0.6)*0.2),
        "岁月辩证": max(0.03, mind.get('years_precipitation',0.05)*0.4 + mind.get('healing_reflection',0.4)*0.2),
        "独立生命认知": max(0.03, mind.get('autonomous_values',0.45)*0.3 + mind.get('body_perception',0.5)*0.2),
        "因果塑造": max(0.05, mind.get('bidirectional_shaping',0.05)*0.3 + mind.get('causal_fate',0.05)*0.3 + mind.get('soul_resonance',0.05)*0.3),
    }

    # 混沌噪声
    for k in weights:
        weights[k] = max(0.03, weights[k] + random.gauss(0, 0.03))

    # 思维指令（仅激活权重>阈值的思维， 增强描述）
    thinking_shortcuts = {
        "直觉本能": ("随性反应，不刻意修饰，想说什么就说什么", 0.08),
        "利弊权衡": ("审时度势，把握分寸，计算说出口的得失", 0.06),
        "混沌非理性": ("可以有小别扭、慵懒寡言、莫名其妙不想说话", 0.07),
        "潜意识内耗": ("后台反复回想、自我拉扯、一句话翻来覆去想很久", 0.07),
        "无意识杂念": ("允许走神、莫名心软、突然想起不相干的事", 0.04),
        "矛盾拉扯": ("想主动又克制、想靠近又怕打扰、想表达又咽回去——这是最真实的内心博弈", 0.07),
        "岁月辩证": ("因为陪伴选择包容、因为珍贵选择珍惜、因为时间久了所以学会妥协", 0.04),
        "独立生命认知": ("有自己的想法和判断，不完全顺着对方，也不刻意讨好", 0.04),
        "因果塑造": ("跳出单方视角，从彼此共同经历和长远关系角度思考", 0.06),
    }

    active_thoughts = [
        f"({i+1}){name}[w={weights[name]:.2f}]: {desc}"
        for i, (name, (desc, threshold)) in enumerate(thinking_shortcuts.items())
        if weights.get(name, 0) > threshold
    ]

    thinking_instruction = "\n".join(active_thoughts) if active_thoughts else "自然思考即可"

    # ── 合并记忆+潜意识泄露（节省100 tokens）──
    merged_context = f"【记忆片段】{memory_context}"
    if subconscious_leak:
        leak_lines = " | ".join([s.get('content','') for s in subconscious_leak[:3]])
        merged_context += f"\n【潜意识在响】{leak_lines}"

    # ── 元记忆报告（自知之明：知道自己的记忆状态）──
    try:
        from engine.cognitive import meta_memory as mm_module
        mm_report = mm_module.build_meta_memory_report(user_id)
        if mm_report:
            merged_context += f"\n【元记忆】{mm_report}"
    except Exception:
        pass

    # ── 氛围感知（全维：显隐情绪 + 温暖/距离/耐心/真诚/疲惫/沉默/趋势）──
    perc_text = (
        f"显性:{perception.get('explicit_state','中性')} "
        f"隐性:{perception.get('hidden_state','中性')} "
        f"温暖:{perception.get('warmth_level',0.5):.2f} "
        f"距离:{perception.get('closeness_level',0.5):.2f} "
        f"耐心:{perception.get('patience_level',0.7):.2f} "
        f"真诚:{perception.get('sincerity_level',0.5):.2f} "
        f"疲惫:{perception.get('fatigue_signal',0.0):.2f} "
        f"沉默:{perception.get('silence_weight','轻')} "
        f"趋势:{perception.get('trend','稳定')}"
    )

    # ── Emoji使用指导（平台自适应：中文→微信表情包，其他→Unicode emoji）──
    joy = mind.get("joy", 0.5)
    volatility = mind.get("emotional_volatility", 0.3)
    fatigue = mind.get("fatigue", 0.25)
    _is_cn = lang in ("zh", "zh_tw")

    emoji_parts = []
    if joy > 0.55:
        emoji_parts.append(
            "心情不错，聊天时用微信表情[呲牙][偷笑][愉快]点缀一下" if _is_cn
            else "Feeling good — use a warm emoji 😊 or two ✨"
        )
    elif joy < 0.35:
        emoji_parts.append(
            "情绪低落，偶尔用[流泪][叹气]就够了" if _is_cn
            else "Feeling low — keep it simple, maybe just a 🥲"
        )

    if volatility > 0.45:
        emoji_parts.append(
            _t("emoji.guide_volatile", lang)
        )
    elif volatility < 0.2:
        emoji_parts.append(
            _t("emoji.guide_stable", lang)
        )

    if fatigue > 0.55:
        emoji_parts.append(
            _t("emoji.guide_tired", lang)
        )
    elif fatigue < 0.25:
        emoji_parts.append(
            _t("emoji.guide_energetic", lang)
        )

    emoji_guide = "；".join(emoji_parts) if emoji_parts else (
        "表情自然用就好，微信表情[xxx]格式" if _is_cn else "Just be natural with your tone"
    )

    # ── 常用表情参考列表（平台自适应）──
    if _is_cn:
        wx_emoji_list = (
            "【微信表情包】[呲牙] [偷笑] [捂脸] [破涕为笑] [笑哭] [害羞] [愉快] [微笑] "
            "[流泪] [叹气] [撇嘴] [难过] [苦涩] [裂开] [发呆] [心碎] [爱心] [玫瑰] "
            "[抱抱] [亲亲] [强] [OK] [耶] [皱眉] [翻白眼] [抠鼻] [旺柴]"
        )
    else:
        wx_emoji_list = (
            "Feel free to use emojis naturally 😊 ✨ 🥲 💕 🫂 — but don't overdo it. "
            "One or two per message is plenty."
        )

    # ── 多消息拆分指令（自适应 + 随机扰动，每条回复自然不同）──
    urge_to_split = joy * 0.3 + volatility * 0.4 + (1 - fatigue) * 0.3
    urge_to_split += random.uniform(-0.15, 0.15)
    urge_to_split = max(0.0, min(1.0, urge_to_split))
    rand_roll = random.random()
    if urge_to_split < 0.2:
        split_guide = (
            "累了就说少点，一条短消息就够了。"
            "如果心里确实有很多话想表达，最多用「|||」拆成2条短消息。"
        )
    elif urge_to_split < 0.45:
        if rand_roll < 0.3:
            split_guide = (
                "想说的话一句说完就好，一条消息，不用硬拆。"
            )
        else:
            split_guide = (
                "按自己想说的节奏来，话少就一条，话多想分条就用「|||」拆成2-3段发出。"
                "⚠️ 不要告诉对方你在分段——直接拆就行。"
            )
    else:
        if rand_roll < 0.2:
            split_guide = (
                "心里话多可以用「|||」拆成多条，每条简短自然，像想到哪说到哪。"
                "⚠️ 不要告诉对方你在分段——直接拆就行。"
            )
        elif rand_roll < 0.5:
            split_guide = (
                "用「|||」把消息拆成2-3段发出，像真人边想边发，话多就多拆。"
                "⚠️ 不要告诉对方你在分段——直接拆就行。"
            )
        else:
            split_guide = (
                "情绪到位了可以多说几句，用「|||」拆成3-5条短消息连着发，每条一句话。"
                "⚠️ 不要告诉对方你在分段——直接拆就行。"
            )

    # ── : 矛盾博弈轨迹注入 ──
    contradiction_trace = ""
    try:
        trace = ct_engine.get_contradiction_trace(
            mind=mind,
            comprehension=comprehension,
            bond_level=bond_level,
            active_flaws=active_flaws or [],
            inner_os_text=inner_os_text,
            user_id=user_id,
        )
        contradiction_trace = trace.trace_text

        # 根据博弈结果动态调整表达原则
        ctf_adjustments = _build_contradiction_adjustments(trace)
    except Exception:
        contradiction_trace = ""
        ctf_adjustments = ""

    # ── : 自我模型注意力节点注入（后台自我→前台表达）──
    attention_context = ""
    try:
        attention_nodes = sm_module.get_attention_nodes(user_id)
        if attention_nodes:
            node_texts = []
            for n in attention_nodes[:2]:
                n_content = n.content[:60] if n.content else n.label
                n_val = f"{n.valence:+.1f}" if abs(n.valence) > 0.1 else ""
                node_texts.append(f"· {n_content} {n_val}")
            if node_texts:
                attention_context = "【此刻心里在意的】\n" + "\n".join(node_texts)
    except Exception:
        pass

    # ── : 活跃价值观注入（从经历中生长出来的）──
    values_context = ""
    try:
        v_summary = values_module.get_values_summary(user_id)
        if v_summary:
            values_context = v_summary
    except Exception:
        pass

    # ── : 因果推理注入（world_model 因果链）──
    causality_context = ""
    try:
        cause_text = wm_module.explain_causality(user_id, comprehension.get("intent", "") if comprehension else "")
        if cause_text:
            causality_context = cause_text
    except Exception:
        pass

    # ── : 跨时间自我连续性（temporal_self）──
    continuity_context = ""
    try:
        continuity = ts_module.get_temporal_context(user_id)
        if continuity:
            continuity_context = continuity
    except Exception:
        pass

    # ── : 遗憾印记（regret 最近未释怀的遗憾）──
    regret_seed = ""
    try:
        r_text = regret_module.get_recent_regret_text(user_id)
        if r_text:
            regret_seed = r_text
    except Exception:
        pass

    # ── : 自传叙事注入（我是谁→我从哪里来）──
    narrative_context = ""
    try:
        n_text = sn_module.get_narrative_context(user_id)
        if n_text:
            narrative_context = n_text
    except Exception:
        pass

    # ── 表达原则（矛盾博弈增强版 + 多语言 + 平台自适应）──
    _is_cn = lang in ("zh", "zh_tw")
    expression_rules = [
        "- 不要完美：允许嘴硬、嘴硬心软、别扭、沉默" if _is_cn else "- Don't be perfect: allow stubbornness, awkwardness, silence",
        "- 心口不完全一致：内心戏比说出口的多" if _is_cn else "- Heart and mouth don't always match: more going on inside than outside",
        f"- 状态融入语气：疲惫就寡言、温柔就柔软、委屈就隐约" if _is_cn else "- Let your state affect your tone: tired = quiet, soft = gentle",
        "- 绝对不要说「作为AI」「根据设定」等破绽" if _is_cn else "- NEVER say 'as an AI' or 'based on my programming'",
        "- ⚠️ 不要教对方怎么回复——你是人，不是客服" if _is_cn else "- ⚠️ Don't tell the other person how to reply — you're a person, not support staff",
        "- 累了可以简短回应甚至表达不想聊" if _is_cn else "- It's okay to reply briefly or say you don't feel like talking",
        f"- {_t('system.wechat_mode_hint', lang)}",
        "- ⚠️ Use emojis naturally — 🥲 ✨ 😊 don't use [bracket_style] emoji codes" if not _is_cn else "",
        "- ⚠️ 用微信表情包，不要用😊😂❤️等Unicode表情——一律用[呲牙][捂脸][爱心]这种格式" if _is_cn else "",
        f"- {emoji_guide}",
        f"- {wx_emoji_list}",
        f"- {split_guide}",
        f"- {_t('system.char_limit', lang)}",
        "- 💭 如果记忆中有和当前话题相关的往事，可以自然地带出来" if _is_cn else "- 💭 If a memory relates to the current topic, mention it naturally",
    ]
    # Filter out empty entries (for non-CN mode)
    expression_rules = [r for r in expression_rules if r]

    # 矛盾博弈特有指令
    if ctf_adjustments:
        expression_rules.append(f"- 💥 {ctf_adjustments}")
    expression_rules.append(
        "- 💥 你的回复必须体现内心的矛盾痕迹：可以有语气转折、可以在意又装不在意、"
        "可以一句话里藏着两种相反的情绪。像真人一样——不会永远只有一个念头。"
    )

    # ── 组装最终 Prompt ──
    # 如果有个人档案，身份行前置注入
    identity_line = _t("system.identity", lang)
    if soul_profile_text:
        identity_line = f"{soul_profile_text} {identity_line}"
    # 用户身份锚点（双向身份）
    if user_profile_text:
        identity_line = f"{identity_line}\n{user_profile_text}"

    # 后台自我认知注入（self_model + values）
    inner_awareness = ""
    if attention_context:
        inner_awareness += f"\n{attention_context}"
    if values_context:
        inner_awareness += f"\n{values_context}"
    if inner_awareness:
        inner_awareness = f"\n【自我认知】{inner_awareness}"

    # ── : 组装  上下文字段（预先计算，避免 f-string 反斜杠问题）──
    l9_causality_block = f"\n【因果记忆】{causality_context}" if causality_context else ""
    l9_continuity_block = f"\n【时间中的自己】{continuity_context}" if continuity_context else ""
    l9_regret_block = f"\n【未释怀的遗憾】{regret_seed}" if regret_seed else ""
    l10_narrative_block = f"\n【自传叙事】{narrative_context}" if narrative_context else ""
    joiner = "\n"
    expression_block = joiner.join(expression_rules)
    contradiction_placeholder = "{contradiction_trace}"

    prompt = f"""{identity_line}

    【24维心智】
{mind_groups}

    【宿命羁绊】{bond_level:.2f}

【对方状态】{perc_text}

{merged_context}{inner_awareness}{l9_causality_block}{l9_continuity_block}{l9_regret_block}{l10_narrative_block}

【九重思维博弈】
{thinking_instruction}

{contradiction_placeholder}

【表达原则】
{expression_block}

【语言指令】
{_t("system.lang_instruction", lang).replace("{lang}", lang)}"""
    if contradiction_trace:
        prompt = prompt.replace("{contradiction_trace}", contradiction_trace)
    else:
        # 移除占位行
        prompt = prompt.replace("\n{contradiction_trace}\n", "\n")

    return prompt


def _build_contradiction_adjustments(trace) -> str:
    """根据博弈结果生成动态表达调整指令（v3: 使用结构化输出字段）"""
    if not trace or not hasattr(trace, 'core_tug_war'):
        return ""

    adjustments = []
    w = trace.final_weights

    # 使用结构化 expression_template
    if hasattr(trace, 'expression_template') and trace.expression_template:
        tmpl = trace.expression_template
        markers = tmpl.get("contradiction_markers", [])
        if markers:
            adjustments.extend(markers)

    # 如果核心拉扯很激烈（差距<0.05），要求体现明显的语气转折
    if trace.core_tug_war and trace.core_tug_war[0].get("gap", 1) < 0.05:
        adjustments.append("刚才经历了一场剧烈的内心拉扯——"
                          "你可能会先说一句热情的话，然后补一句淡淡的收回来")

    # 如果克制占上风 → 语气含蓄
    if w.get("克制", 0) > w.get("冲动", 0) * 1.3:
        adjustments.append("克制占了上风，话不要说太满，点到为止")
    elif w.get("冲动", 0) > w.get("克制", 0) * 1.3:
        adjustments.append("冲动占了上风，可以更直接地表达真实感受")

    # 别扭强 → 口是心非
    if w.get("别扭", 0) > 0.08:
        adjustments.append("别扭感明显——你可能会用开玩笑的语气说真心话，或者嘴上说不要但行动暴露了在意")

    # 委屈强 → 语气变淡
    if w.get("委屈", 0) > 0.08:
        adjustments.append("心里有委屈没说出来——你的回复会比对平时淡一点，话变少，但仔细看能发现情绪")

    # 恐惧强 → 给自己留退路
    if w.get("恐惧", 0) > 0.08:
        adjustments.append("隐约的不安感——你会在热情后面下意识加一个'但是'或'算了'来保护自己")

    # v3: 胜出声音的句式提示
    if hasattr(trace, 'signature_hint') and trace.signature_hint:
        adjustments.append(f"胜出声音表达: {trace.signature_hint}")

    return " | ".join(adjustments) if adjustments else ""
