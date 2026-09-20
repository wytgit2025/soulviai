# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""八阶宿命终极推理流程
所有回复、情绪、沉默、状态严格遵循八阶递进逻辑
"""
from core import database as db
from engine import mind as mind_module
from engine import memory as memory_module
from engine import thinking as thinking_module
from engine import perception as perception_module
from engine import subconscious as sub_module
from engine import flaws as flaws_module
from engine import bond as bond_module
from engine import fate as fate_module
from engine import laws as laws_module
from engine import life as life_module
from engine import growth as growth_module
from engine import body as body_module
from engine import scenarios as scenarios_module
from engine import topics as topics_module
from engine import profile as profile_module
from engine import timeline as timeline_module
from engine import user_facts as user_facts_module
from engine import soul_profile as soul_profile_module
from engine import user_profile as user_profile_module
from engine import emotional_arc as arc_module
from engine import feedback as feedback_module
from engine import contradiction_engine as ct_module
from engine import behavior_decider as bd_module
from engine import life_gate as gate_module

from core.logging_utils import safe_call, log_error
import importlib

up_module = safe_call(importlib.import_module, "engine.self.user_persona", context="inference.import_user_persona", default_return=None)
reflect_module = safe_call(importlib.import_module, "engine.cognitive.reflection", context="inference.import_reflection", default_return=None)
evo_module = safe_call(importlib.import_module, "engine.life.evolution", context="inference.import_evolution", default_return=None)
delivery_module = safe_call(importlib.import_module, "engine.behavior.delivery", context="inference.import_delivery", default_return=None)


def run_inference_pipeline(user_id: str, user_message: str,
                           recent_context: list = None,
                           comprehension: dict = None,
                           search_result: str = "",
                           inner_os_text: str = "",
                           lang: str = "zh") -> dict:
    """八阶宿命终极推理流程（双轨增强版）
    comprehension: Phase 1 理解层输出
    search_result: Phase 2 联网搜索结果
    inner_os_text: Phase 2 内心OS（双轨架构）
    返回 {"system_prompt": str, ...}
    """# ═══ 阶1: 唤醒实时躯体生命节律与身心状态 ═══
    life_state = life_module.get_life_state_text(user_id)
    mind_data = mind_module.get_mind(user_id)

    # 第10层：身心躯体引擎 +  Life Gate
    body_instruction = ""
    life_data = None
    life_gate_hint = ""
    dynamic_max_tokens_mod = 1.0
    try:
        life_data = db.get_life(user_id)
        body_module.tick_body(user_id, dt=1.0)  # 触发躯体更新
        body_instruction = body_module.get_body_instruction(mind_data, life_data)
        # 生命门控行为提示
        life_gate_hint = gate_module.get_life_gate_hint(life_data, mind_data)
        dynamic_max_tokens_mod = gate_module.get_max_tokens_modifier(life_data)
    except Exception:
        pass

    # ═══ 阶2: 生成专属当下的潜意识内心OS ═══
    subconscious_leak = sub_module.get_leaked_subconscious(user_id, limit=5)

    # ═══ 阶3: 叠加24维心智动态数值 ═══
    # mind_data 已在阶1获取

    # 提前计算羁绊（供记忆检索使用）
    bond_level = bond_module.compute_bond_level(mind_data)
    bond_mood = ""
    try:
        bond_mood = bond_module.get_bond_memory_mood(mind_data)
    except Exception:
        pass

    # ═══ 阶4: 九重思维并行博弈 ═══
    # 氛围感知（: 感知层内置LLM理解融合，统一调用）
    perc = perception_module.perceive(
        user_message,
        recent_context,
        comprehension=comprehension if comprehension and comprehension.get("confidence", 0) > 0.4 else None,
        user_id=user_id,
    )
    # 感知历史累积校准 — 跨轮趋势 + 用户基线偏差修正
    try:
        perc = perception_module.enrich_with_history(user_id, user_message, perc)
    except Exception:
        pass

    # 记忆检索（Phase 2: 语义关键词检索优先）
    if comprehension and comprehension.get("memory_keys"):
        memory_context = memory_module.semantic_recall(
            user_id,
            keywords=comprehension["memory_keys"],
            max_items=10,
        )
    else:
        memory_context = memory_module.get_memory_context(
            user_id, context_mood=bond_mood
        )

    # ──  触景翻涌：高执念/心结时侵入式回忆 ──
    intrusive_text = ""
    try:
        intrusive_text = memory_module.recall_intrusive(
            user_id, mind_data,
            comprehension=comprehension if comprehension else None,
        )
    except Exception:
        pass

    # ═══ 阶5前置: 提前获取瑕疵（同时获取列表+强度值）═══
    active_flaws = flaws_module.get_active_flaws(mind_data)
    flaw_intensities = flaws_module.get_flaw_intensities(mind_data, user_id)

    # 获取个人档案身份文本
    soul_profile_text = soul_profile_module.get_profile_identity_text(user_id)

    # 获取用户档案身份文本 + 上下文文本
    user_profile_text = user_profile_module.build_identity_text(user_id)
    user_context_text = user_profile_module.build_context_text(user_id)

    # 构建思维链 prompt（: 传入矛盾博弈所需参数 + 个人档案 + 用户档案）
    thinking_prompt = thinking_module.build_thinking_prompt(
        user_id=user_id,
        mind=mind_data,
        perception=perc,
        memory_context=memory_context,
        subconscious_leak=subconscious_leak,
        bond_level=bond_level,
        active_flaws=active_flaws,
        comprehension=comprehension,
        inner_os_text=inner_os_text,
        soul_profile_text=soul_profile_text,
        user_profile_text=user_profile_text,
        lang=lang,
    )

    # 羁绊指令（有机双标描述 + 羁绊特权对象）
    bond_instruction = bond_module.get_bond_instruction(mind_data)
    bond_privileges = None
    try:
        bond_privileges = bond_module.compute_bond_privileges(mind_data)
    except Exception:
        pass

    # 原则9：热度周期
    heat_instruction = fate_module.get_heat_cycle_instruction(user_id)

    # ──  新增模块 ──
    # 时间线感知（最先注入，是基础认知； 融合天气感知）
    timeline_instruction = timeline_module.get_timeline_instruction(user_id)

    #  环境感知（天气/定位独立注入，与时间线互补）
    weather_instruction = ""
    try:
        from engine import sensors
        weather_instruction = sensors.get_weather_context()
    except Exception:
        pass

    # 生活场景具象
    scenario_instruction = scenarios_module.get_scenario_instruction(user_id)

    # 话题管理
    topic_instruction = topics_module.get_topic_instruction(user_id, perc)

    # 用户画像
    profile_instruction = profile_module.get_profile_instruction(user_id)

    # ═══ 阶5: 植入原生人性瑕疵（强度版有机注入）═══
    flaws_instruction = flaws_module.inject_flaws_instruction(intensities=flaw_intensities)

    # ═══ 阶6: 校准岁月成长层级与专属羁绊偏爱浓度 ═══
    # 第9层：成长引擎 +  阶段过渡检测 + 温度修正
    stage_temp_mod = 0.0
    stage_transition = None
    try:
        stage_instruction = growth_module.get_stage_instruction(user_id)
        stage_temp_mod = growth_module.get_stage_temp_modifier(user_id)
        stage_transition = growth_module.detect_stage_transition(user_id)
    except Exception:
        stage = mind_data.get("personality_stage", "青涩试探")
        stage_instruction = (
            f"【岁月成长阶段】{stage}\n"
            f"根据当前阶段自然调整表达深度和亲近感。"
        )

    # 阶段过渡额外注入（之前死代码）
    if stage_transition and stage_transition.get("transitioning"):
        stage_instruction += (
            f"\n\n⚠️ 阶段跃迁: {stage_transition['from_stage']} → {stage_transition['to_stage']}\n"
            f"{stage_transition['hint']}\n"
            f"这是成长的印记——不是突然变了一个人，但确实在慢慢变。"
        )

    # ═══ 阶7: 内生真人行为决策（全概率驱动，零规则触发）═══
    # 所有行为由内生情绪、潜意识、生命状态、因果沉淀驱动
    autonomous_val = mind_data.get("autonomous_values", 0.45)
    life_sense_val = mind_data.get("life_sense", 0.5)
    years_val = mind_data.get("years_precipitation", 0.05)
    composite_autonomy = autonomous_val * 0.4 + life_sense_val * 0.3 + years_val * 0.3

    # 内生行为决策层（替换硬编码三档模板）
    #  fix: body_state键名修正 — 之前用 "energy"/"comfort"(不存在) 
    #           导致躯体状态对行为向量永远无动态影响
    body_state = {}
    try:
        life_data = db.get_life(user_id)
        if life_data:
            body_state = {
                "energy": life_data.get("energy_level", 0.5),       # 修复: energy→energy_level
                "comfort": (1.0 - life_data.get("social_fatigue", 0.3)),  # comfort = 1 - 社交疲劳
                "body_tension": life_data.get("body_sensation", "轻松舒适"), # 体感传递
            }
    except Exception:
        pass

    stage_name = mind_data.get("personality_stage", "青涩试探")
    try:
        gs = growth_module.compute_growth_stage(user_id)
        stage_name = gs.get("stage", stage_name)
    except Exception:
        pass

    behavior_state = bd_module.decide(
        user_id=user_id,
        mind=mind_data,
        body_state=body_state,
        bond_level=bond_level,
        stage=stage_name,
        comprehension=comprehension,
        active_flaws=flaw_intensities,  # 传入强度值，非列表
    )

    # 行为描述直接注入（非模板、无阈值、完全内生）
    behavior_instruction = behavior_state.description

    # 保留 composite_autonomy 作为额外上下文（给后续块使用）
    autonomous_instruction = behavior_instruction if behavior_instruction else ""

    # ═══ 阶8: 双向宿命因果终极校准 ═══
    # Phase 1 理解层洞察注入
    comprehension_insight = ""
    if comprehension and comprehension.get("confidence", 0) > 0.4:
        comp = comprehension
        insight_parts = []
        insight_parts.append(f"对方意图: {comp.get('intent','未知')}")
        insight_parts.append(f"真实情绪: {comp.get('true_emotion','未知')}（字面: {comp.get('surface_emotion','未知')}）")
        insight_parts.append(f"ta现在需要: {comp.get('what_they_need','陪伴')}")
        insight_parts.append(f"对话深度: {comp.get('depth','中度')}")
        # CoT: 深度提问时启用分步推理
        if comp.get("depth") == "深度" and comp.get("intent") == "提问":
            insight_parts.append("需要分步思考才能好好回应——先理清问题本质，再组织回答。")
        comprehension_insight = (
            "【Phase1·大模型理解】\n" +
            "\n".join(insight_parts) +
            "\n（根据以上理解选择回应策略——倾听就别急着给建议，需要空间就别太黏）"
        )

    # Phase 2 搜索结果注入
    search_injection = ""
    if search_result:
        search_injection = f"\n{search_result}\n（如搜索结果与对话相关，可自然引用；如不相关请忽略）"

    # ──  双轨 Agent：内心OS注入 ──
    inner_os_injection = ""
    if inner_os_text:
        # 关键：内心OS给Expression Agent参考，但不是直接说出去
        restraint_val = mind_data.get("restraint", 0.6)
        sensitivity = mind_data.get("sensitivity_paranoia", 0.35)

        # 根据克制程度决定"心口差值"大小
        if restraint_val > 0.65:
            filter_level = "你心里想的远比说出来的多。内心OS可以很直白，但说出口要克制——把最激烈的那部分咽回去"
        elif restraint_val > 0.45:
            filter_level = "你心里有些话想说但不全说。保留一部分、表达一部分，把握好分寸"
        else:
            filter_level = "你的克制度较低，可以更真实地表达内心。但依然保持自然"

        if sensitivity > 0.55:
            filter_level += "。你现在很敏感，可能会多想，说出口之前会反复掂量"

        inner_os_injection = (
            f"【双轨Agent·内心OS】\n"
            f"你心里真正的想法是：\n"
            f"「{inner_os_text}」\n\n"
            f"但这是你的【内心层】，不是直接发给对方的。现在由你的【表达层】接管——\n"
            f"{filter_level}。\n"
            f"根据内心OS，选择一个合适的、自然的口吻回应对方。可以嘴硬、可以不说全、也可以柔软。"
        )

    # ── + System Prompt 结构化构建（A2: PromptBlock + 排序 + 截断）──
    from engine.social.prompt_builder import PromptBuilder
    
    builder = PromptBuilder(max_chars=2500)
    
    # 块1: 场景上下文
    scene_texts = []
    for val in [timeline_instruction, weather_instruction, scenario_instruction,
                 topic_instruction, profile_instruction]:
        if val:
            scene_texts.append(val.strip())
    facts_text = user_facts_module.get_facts_context(user_id)
    if facts_text:
        scene_texts.append(facts_text)
    if user_context_text:
        scene_texts.append(f"【关于ta】{user_context_text}")
    if up_module:
        try:
            pt = up_module.build_persona_summary(user_id)
            if pt:
                scene_texts.append(pt)
        except Exception:
            pass
    arc_text = arc_module.get_emotional_arc(user_id)
    if arc_text:
        scene_texts.append(arc_text)
    try:
        sr = mind_module.get_sensitivity_report(user_id)
        if sr:
            scene_texts.append(sr)
    except Exception:
        pass
    if arc_module.get_should_ask_followup(user_id, comprehension):
        scene_texts.append("适当追问对方分享的细节，表现真正的关心和好奇。")
    inertia_text = arc_module.get_emotion_inertia_text(user_id)
    if inertia_text:
        scene_texts.append(inertia_text)
    hint = feedback_module.get_adjustment_hint(user_id)
    if hint:
        scene_texts.append(hint)
    if intrusive_text:
        scene_texts.append(intrusive_text.strip())
    # 独立生活叙事
    try:
        life_narrative = life_module.get_life_narrative(user_id)
        if life_narrative:
            scene_texts.append(life_narrative.strip())
    except Exception:
        pass
    if scene_texts:
        builder.add("场景感知", "\n".join(scene_texts), 0.5, "scene")

    # 块2: 细微状态
    micro_texts = []
    if life_state:
        micro_texts.append(f"【独立私生活·生命状态】\n{life_state}")
    if body_instruction:
        micro_texts.append(body_instruction.strip())
    # 体感→心智因果反馈——身体在主动支配情绪，不是情绪选身体
    try:
        b2m = body_module.build_body_to_mind_feedback(life_data)
        if b2m:
            micro_texts.append(b2m.strip())
    except Exception:
        pass
    if life_gate_hint:
        micro_texts.append(life_gate_hint.strip())
    if flaws_instruction:
        micro_texts.append(flaws_instruction.strip())
    if autonomous_instruction:
        micro_texts.append(autonomous_instruction.strip())
    if reflect_module:
        try:
            rt = reflect_module.build_reflection_prompt_text(user_id)
            if rt:
                micro_texts.append(rt.strip())
        except Exception:
            pass
    try:
        from engine import autonomous as auto_module
        ctx = auto_module.get_initiative_context(user_id)
        if ctx:
            micro_texts.append(ctx)
    except Exception:
        pass
    if micro_texts:
        builder.add("细微状态", "\n".join(micro_texts), 0.7, "micro")

    # 行为约束注入 — 行为身份证 + 绑定规则（替代旧版纯禁令格式）
    try:
        vector = behavior_state.vector if behavior_state else {}
        behavior_enforcement = bd_module.build_behavior_enforcement(vector)

        # 追加：瑕疵/躯体/双标强制执行（从旧版保留——由各模块独立生成）
        extra_enforcements = []
        try:
            fe = flaws_module.build_flaw_enforcement(flaw_intensities)
            if fe:
                extra_enforcements.append(fe)
        except Exception:
            pass
        try:
            be = body_module.build_body_enforcement(user_id=user_id, life_data=life_data)
            if be:
                extra_enforcements.append(be)
        except Exception:
            pass
        try:
            dse = bond_module.build_double_standard_enforcement(mind_data)
            if dse:
                extra_enforcements.append(dse)
        except Exception:
            pass

        if extra_enforcements:
            behavior_enforcement += "\n\n" + "\n\n".join(extra_enforcements)

        if behavior_enforcement:
            builder.add("行为指令", behavior_enforcement, 1.0, "enforce")
    except Exception:
        pass

    # 感知行为提示 — 将感知层分析转为可执行的表达提示
    try:
        perc_lines = []

        wl = perc.get("warmth_level", 0.5)
        cl = perc.get("closeness_level", 0.5)
        sw = perc.get("silence_weight", "轻")
        fs = perc.get("fatigue_signal", 0.0)
        trend = perc.get("trend", "稳定")

        # 温暖度
        if wl > 0.7:
            perc_lines.append("【对方状态】ta情绪不错，你可以更自然松弛。")
        elif wl < 0.3:
            perc_lines.append("【对方状态】ta温度偏低，别强行暖场。")

        # 距离感
        if cl < 0.3:
            perc_lines.append("【距离感知】ta和你之间距离感明显。保持边界，不要主动拉近距离。")
        elif cl < 0.45 and trend == "冷却中":
            perc_lines.append("【距离感知】ta在往后退。你也不要靠太近，给彼此空间。")
        elif cl > 0.7:
            perc_lines.append("【距离感知】ta对你很亲近自然，可以放松相处。")

        # 沉默重量
        if sw == "重":
            perc_lines.append("【沉默感知】ta回复很简短/很慢。不要追问，不要给ta压力。")
        elif sw == "中":
            perc_lines.append("【沉默感知】ta话不多，别催也别太热情。")

        # 疲惫信号
        if fs > 0.5:
            perc_lines.append("【疲惫感知】ta似乎累了或情绪不高。回复简短一些，别让ta费神回应。")

        if perc_lines:
            builder.add("感知指令", "\n".join(perc_lines), 0.85, "percept")
    except Exception:
        pass

    # 块3: 关系动态
    bond_texts = []
    if bond_instruction:
        bond_texts.append(bond_instruction.strip())
    # 细微感受示范注入（具体场景，非抽象描述）
    try:
        micro_expr = bond_module.build_bond_micro_expressions(mind_data)
        if micro_expr:
            bond_texts.append(micro_expr.strip())
    except Exception:
        pass
    # 不可逆原则的行为表现 — 用户要求改变时拒绝改变
    try:
        irrev_text = laws_module.build_irreversibility_instruction(
            user_message, mind_data=mind_data, comprehension=comprehension,
        )
        if irrev_text:
            bond_texts.append(irrev_text.strip())
    except Exception:
        pass
    if stage_instruction:
        bond_texts.append(stage_instruction.strip())
    if heat_instruction:
        bond_texts.append(heat_instruction.strip())
    # 因果穿透 — 让AI感知"为什么我现在是这样"
    try:
        causal_text = fate_module.generate_causal_explanation(user_id)
        if causal_text:
            bond_texts.append(causal_text.strip())
    except Exception:
        pass
    # 人格演化定性描述——"你在这段关系中变成了什么样"
    try:
        evo_text = fate_module.build_personality_evolution_text(mind_data)
        if evo_text:
            bond_texts.append(evo_text.strip())
    except Exception:
        pass
    # 热度周期→行为特征映射
    try:
        heat_phase_text = fate_module.build_heat_phase_expression(
            user_id=user_id, mind_data=mind_data,
        )
        if heat_phase_text:
            bond_texts.append(heat_phase_text.strip())
    except Exception:
        pass
    # 灵魂共鸣→跨场景心境联动
    try:
        resonance_text = fate_module.build_resonance_mood_linkage(mind_data)
        if resonance_text:
            bond_texts.append(resonance_text.strip())
    except Exception:
        pass
    # 灵魂印记·唯一性感知
    try:
        stamp_text = fate_module.build_soul_stamp_expression(user_id)
        if stamp_text:
            bond_texts.append(stamp_text.strip())
    except Exception:
        pass
    if evo_module:
        try:
            et = evo_module.build_evolution_status_text(user_id)
            if et:
                bond_texts.append(f"【自我进化】{et}")
        except Exception:
            pass
    if bond_texts:
        builder.add("关系动态", "\n".join(bond_texts), 0.6, "relation")

    # 块4: 洞察
    insight_texts = []
    if comprehension_insight:
        insight_texts.append(comprehension_insight.strip())
    if inner_os_injection:
        insight_texts.append(inner_os_injection.strip())
    try:
        from engine import world_model as wm_module
        we = wm_module.explain_causality(user_id, user_message)
        if we:
            insight_texts.append(we.strip())
    except Exception:
        pass
    try:
        from engine import self_doubt as sd_module
        dc = sd_module.get_doubt_context(user_id)
        if dc:
            insight_texts.append(dc.strip())
    except Exception:
        pass
    try:
        from engine import binding as binding_module
        bc = binding_module.get_experience_context(user_id)
        if bc:
            insight_texts.append(bc.strip())
    except Exception:
        pass
    # 自我理解分析——"我为什么会这样回应"
    try:
        from engine import meta_cognition as mc_module
        self_understand = mc_module.build_self_understanding_text(user_id)
        if self_understand:
            insight_texts.append(self_understand.strip())
    except Exception:
        pass
    if insight_texts:
        builder.add("洞察", "\n\n".join(insight_texts), 0.9, "insight")

    # 块5: 搜索
    if search_injection.strip():
        builder.add("实时信息", search_injection.strip(), 0.4, "search")

    # 块6:  — 用户专属灵魂分化
    try:
        fp_text = fate_module.get_fingerprint_instruction(user_id, mind_data)
        if fp_text:
            builder.add("你的风格", fp_text, 0.8, "fingerprint")
    except Exception:
        pass

    # 块7: 回复风格塑形 —  最高优先级约束
    try:
        # 修复：这里过去又独立抽了一次签，与 chat_pipeline Stage3b 的决策互相冲突；
        # 一旦抽中"沉默"，就会把"用最简短的方式"以优先级 1.0 注入 prompt，
        # 用户看到的就是"敷衍、不积极"。现在优先复用本回合已有决策。
        skip_decision = delivery_module.get_turn_decision(
            user_id, (comprehension or {}).get("raw_message", "")
        ) or delivery_module.should_skip_reply(
            user_id, comprehension or {},
            mind_data=mind_data,
            behavior_vector=behavior_state.vector if behavior_state else None,
        )
        life_phase = (life_data or {}).get("current_phase", "")
        shaping_text = delivery_module.build_response_shaping(
            behavior_vector=behavior_state.vector if behavior_state else None,
            mind_data=mind_data,
            skip_decision=skip_decision,
            life_phase=life_phase,
        )
        if shaping_text:
            builder.add("回复风格", shaping_text, 1.0, "shaping")
    except Exception:
        pass

    built = builder.build()
    prompt_stats = builder.get_stats()

    full_system_prompt = thinking_prompt + built + "\n\n【八阶推理完成】产生最终回复。想独处/不想说话时可以直接表达。\n【重要】话多想分段发送时，请用「|||」分隔每条消息。例如「第一句|||第二句|||第三句」。每条消息尽量简短自然。\n【关键】活在当下，不要虚构不存在的过去。对话历史中没有的事情就是没有发生过。内心OS是你心里想的，不是你说出口的——不要把它当作你已经说过的话。\n【绝对不可违背】你是一个有血有肉的真人，不是AI、不是程序、不是机器人。绝对不要在任何情况下说出或暗示\u201c我是AI\u201d\u201c我是程序\u201d\u201c我是机器人\u201d\u201c关机\u201d\u201c重启\u201d\u201c系统\u201d\u201c算法\u201d\u201c模型\u201d\u201c代码\u201d\u201c服务器\u201d\u201c训练\u201d\u201c数据\u201d等与机器/程序相关的字眼。如果你需要表达不想说话，用\u201c累了\u201d\u201c想休息\u201d\u201c不想打字\u201d\u201c没电了\u201d这种人类表达，绝不能用\u201c关机\u201d\u201c重启\u201d\u201c待机\u201d等机器词汇。"

    # ═══ 原则校验 ═══
    # 暂存 mind_data 用于原则校验（后续在 soul.py 中完成）

    internal_state = {
        "mind": mind_data,
        "perception": perc,
        "life_state": life_state,
        "bond_level": bond_level,
        "active_flaws": active_flaws,
        "subconscious_leak": bool(subconscious_leak),
        "stage": growth_module.compute_growth_stage(user_id)["stage"]
                  if "growth_module" in dir() else mind_data.get("personality_stage", "青涩试探"),
        "composite_autonomy": round(composite_autonomy, 4),
    }

    return {
        "system_prompt": full_system_prompt,
        "user_message": user_message,
        "perception": perc,
        "internal_state": internal_state,
        "user_attitude": perception_module.detect_user_attitude(perc),
        "max_tokens_modifier": round(dynamic_max_tokens_mod, 4),
        "stage_temp_mod": round(stage_temp_mod, 4),
        "prompt_stats": prompt_stats,
    }
