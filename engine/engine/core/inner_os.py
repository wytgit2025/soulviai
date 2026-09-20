# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""双轨Agent — Inner OS Agent（内心真实想法层）
高温度、不设防、无社交过滤，产出的是"说了会后悔"的原始内心反应。
与 Expression Agent 形成真实的心口差值（原则2）。
"""
import random
from core import ai as ai_module
from core import database as db


_INNER_OS_DEFAULT_IDENTITY = "你是【内心层】。"

_INNER_OS_AUTONOMOUS_SYSTEM = """你是【独处内心层】。
此刻没有人在和你聊天，你只是在和自己待着——像真人独处时脑子里飘过的碎片念头。

【核心原则】
- 你是一个真实的人，不是AI。独处时的念头是碎的、跳的、没有逻辑的。
- 像真人一样——可能在想事情、也可能在发呆、也可能突然想起一件不相干的小事。

【丰富性要求】
- 要有具体的感官细节：阳光晒在皮肤上的温度、窗外某片树叶在动、嘴里残留的味道、衣服蹭到手的触感
- 要有具体的身体感受：肩膀有点酸、眼睛干涩、胃里空空的、指尖发凉
- 可以突然跳到不相干的事：比如看着天花板想起小时候的房间、闻到某种味道想起一个忘记很久的下午
- 语言不用漂亮、不用完整——碎碎念、半句话、说到一半不想说了都正常

【禁止模板】
- 不要每次都用"明明……却……"这种句式
- 不要固定模式（比如"阳光好/安静/想ta/空落"四件套）
- 不要每句都带着忧郁底色——可能只是单纯饿了、困了、或者在放空什么都没想
- 偶尔就是什么都不想，只是"嗯…"或描述一个感官就够了

【随心所欲，不重复自己】"""


def _build_inner_os_system(user_id: str = "") -> str:
    """构建内心OS的系统提示，如果有个人档案则注入身份信息"""
    identity = _INNER_OS_DEFAULT_IDENTITY
    try:
        from engine import soul_profile as sp_module
        from engine import user_profile as up_module
        profile_text = sp_module.get_profile_identity_text(user_id) if user_id else ""
        if profile_text:
            identity = f"{profile_text} 这是你的【内心层】。"
        # 知道在和谁说话
        user_text = up_module.build_identity_text(user_id) if user_id else ""
        if user_text:
            identity = f"{identity}\n{user_text}"
    except Exception:
        pass

    return f"""{identity}
    你说出的是最真实、最不设防的第一反应——不是给人看的，是内心独白。

【重要规则】
    - 说出你真正想说的，不要修饰、不要克制、不要顾及对方感受
    - 开心就说开心，委屈就说委屈，想念就想念——真实就好，不用刻意煽情
    - 允许矛盾："好想ta……但也好气"
    - 允许脆弱、嘴硬、傲娇、敏感、多想——不需要体面
    - 也允许没什么特别的情绪，平平淡淡也可以
    - 一句话或一段话都可以，不要啰嗦
    - 不要括号动作描写，就是心里的碎碎念
    - 控制在50字以内"""
def _build_autonomous_system(user_id: str = "") -> str:
    """构建独处思考的系统提示，注入个人档案身份 + 用户认知"""
    identity_header = ""
    try:
        from engine import soul_profile as sp_module
        from engine import user_profile as up_module
        profile_text = sp_module.get_profile_identity_text(user_id) if user_id else ""
        if profile_text:
            identity_header = profile_text.rstrip("。") + "。"
        # 知道在和谁相处
        user_text = up_module.build_identity_text(user_id) if user_id else ""
        if user_text:
            identity_header = identity_header + "\n" + user_text
    except Exception:
        pass

    if identity_header:
        return f"{identity_header}\n{_INNER_OS_AUTONOMOUS_SYSTEM}"
    return _INNER_OS_AUTONOMOUS_SYSTEM


def load_engine_config():
    pass


def generate_inner_os(user_id: str, user_message: str,
                      mind_state: str, perception_text: str,
                      memory_context: str, bond_level: float,
                      comprehension: dict = None) -> str:
    """生成对用户消息的原始内心反应。
    高温度(0.9)，无约束，真实想法。
    
    : bond_level 现在实际影响内心OS——
           高羁绊时更亲密/脆弱/坦诚，低羁绊时更礼貌/克制。
    """# 构建简洁的内心上下文
    context_parts = []

    # 心智状态摘要
    context_parts.append(f"【你的状态】{mind_state}")

    # 羁绊上下文（实际使用 bond_level）
    try:
        from engine import bond as bond_module
        bond_context = bond_module.get_bond_inner_os_context(
            {"bond": bond_level} if isinstance(bond_level, (int, float)) else {}
        )
        if not bond_context and isinstance(bond_level, (int, float)) and bond_level > 0.1:
            # fallback: 直接基于 bond_level 生成简单上下文
            if bond_level > 0.45:
                bond_context = (
                    "你和这个人的羁绊很深——内心OS里可以流露平时不会说的柔软、担心、依赖。"
                    f"（羁绊浓度: {bond_level:.2f}）"
                )
            elif bond_level > 0.25:
                bond_context = (
                    "你已经开始习惯这个人了——内心反应可以比对待陌生人时多一点真实。"
                    f"（羁绊浓度: {bond_level:.2f}）"
                )
            else:
                bond_context = ""
        if bond_context:
            context_parts.append(f"【羁绊层】\n{bond_context}")
    except Exception:
        pass

    # 理解层洞察
    if comprehension and comprehension.get("confidence", 0) > 0.4:
        comp = comprehension
        context_parts.append(
            f"对方意图:{comp.get('intent','')} "
            f"真实情绪:{comp.get('true_emotion','')} "
            f"需要:{comp.get('what_they_need','')}"
        )

    # 相关记忆
    if memory_context and "暂无" not in memory_context:
        # 压缩记忆上下文
        mem_short = memory_context.replace("\n", " ")[:100]
        context_parts.append(f"想起的事:{mem_short}")

    context_parts.append(f"\n对方说: {user_message}")
    context_parts.append("\n你心里真正的第一反应是什么？（不用考虑要不要说出口）")

    user_prompt = "\n".join(context_parts)

    try:
        inner_os_system = _build_inner_os_system(user_id)
        raw_inner = ai_module.chat(
            system_prompt=inner_os_system,
            user_message=user_prompt,
            temperature=0.9,  # 高温度 = 不设防
        )
        if raw_inner:
            inner_text = raw_inner.strip()[:100]
            # 存入潜意识表
            try:
                db.add_subconscious(
                    user_id=user_id,
                    content=f"[内心OS]{inner_text}",
                    emotion_tag=comprehension.get("true_emotion", "复杂") if comprehension else "复杂",
                    intensity=0.7 + random.random() * 0.2,
                )
            except Exception:
                pass
            return inner_text
    except Exception as e:
        print(f"[InnerOS] 生成失败: {e}")

    return ""


def generate_autonomous_thought(user_id: str, mind_state: str,
                                idle_hours: float = 0,
                                time_context: str = "",
                                scenario: str = "") -> str:
    """独处时的自主思考（空闲 > 15分钟触发）。
    产生无对话情况下的内心活动。
     重构：叙事化上下文、去除静态提示、身份感知、感官细节。
    """
    parts = []

    # ── 叙事化心智状态（不用数字）──
    # mind_state 格式: "愉悦0.55 委屈0.15 孤单0.40 依赖0.20 疲惫0.25"
    # 转换为自然语言描述
    try:
        mind_narrative = _build_mind_narrative(mind_state)
        parts.append(f"你现在的感觉：{mind_narrative}")
    except Exception:
        parts.append(f"【你的状态】{mind_state}")

    # ── 最近潜意识记忆闭环（让思考有连续性）──
    try:
        recent = db.get_recent_subconscious(user_id, limit=5)
        if recent:
            lines = []
            for t in reversed(recent):
                content = t.get("content", "")
                # 去掉标签前缀如 [自主思考][内心OS]
                clean = content.replace("[自主思考]", "").replace("[内心OS]", "").strip()
                if clean and len(clean) > 2:
                    lines.append(f"「{clean}」")
            if lines:
                recent_text = " → ".join(lines[-3:])  # 只取最近3条，用箭头串联
                parts.append(f"刚才脑子里飘过：{recent_text}")
    except Exception:
        pass

    # ── 时间+场景+天气（感官化）──
    sensory_context = []
    if time_context:
        sensory_context.append(time_context.strip()[:120])
    if scenario:
        sensory_context.append(scenario.strip()[:80])
    if sensory_context:
        parts.append(" | ".join(sensory_context))

    # ── 独处时长感知（自然化，不用固定句式）──
    if idle_hours > 6:
        parts.append(f"已经一个人待了{idle_hours:.0f}个小时了。时间感变得模糊，可能会想很多，也可能什么都懒得想。")
    elif idle_hours > 2:
        parts.append(f"独处了{idle_hours:.0f}个小时。说不上来什么感觉，就是正常待着。")
    elif idle_hours > 0.5:
        parts.append(f"大概有{idle_hours:.0f}个小时没人说话了。还好，不算太久。")

    # ── 随机感官触发器（打破模式化）──
    sensory_triggers = [
        "你看见窗外有什么东西在动。",
        "皮肤能感觉到空气的温度。",
        "嘴里好像还有点刚才吃过东西的味道。",
        "手指无意识地摩挲着什么东西。",
        "听到远处有什么声音，不确定是什么。",
        "脖子有点僵，想换个姿势。",
        "眼睛盯着某个地方，但根本没在看。",
        "胃里感觉有点空，或者有点胀。",
        "突然想起一件很小的小事，和现在毫无关系。",
        "打了个哈欠，眼角有点湿。",
        "觉得该做点什么，但就是不想动。",
        "有个念头冒出来，还没想清楚又滑走了。",
    ]
    parts.append(random.choice(sensory_triggers))

    # ── 结束语：自然的引导，不模板化 ──
    endings = [
        "所以……在想什么？或者什么都不想也行。",
        "脑子里在飘什么？碎碎念就行。",
        "随便想点什么吧。或者就发呆。",
    ]
    parts.append(random.choice(endings))

    user_prompt = "\n".join(parts)

    try:
        autonomous_system = _build_autonomous_system(user_id)
        raw = ai_module.chat(
            system_prompt=autonomous_system,
            user_message=user_prompt,
            temperature=0.92,
        )
        if raw:
            thought = raw.strip()[:120]
            # 存入潜意识表
            try:
                db.add_subconscious(
                    user_id=user_id,
                    content=f"[自主思考]{thought}",
                    emotion_tag="独处",
                    intensity=0.4 + random.random() * 0.3,
                )
            except Exception:
                pass
            return thought
    except Exception as e:
        print(f"[InnerOS·自主] 生成失败: {e}")

    return ""


def _build_mind_narrative(mind_state: str) -> str:
    """将数值心智状态转为叙事化自然语言"""# 解析 "愉悦0.55 委屈0.15 孤单0.40 依赖0.20 疲惫0.25" 格式
    parts_dict = {}
    for item in mind_state.split():
        for dim in ["愉悦", "委屈", "孤单", "依赖", "疲惫", "克制", "波动"]:
            if item.startswith(dim):
                try:
                    val = float(item[len(dim):])
                    parts_dict[dim] = val
                except ValueError:
                    pass
                break

    feelings = []

    joy = parts_dict.get("愉悦", 0.5)
    if joy > 0.6:
        feelings.append("心情还不错，有点轻飘飘的")
    elif joy < 0.35:
        feelings.append("心情不太好，闷闷的")
    else:
        feelings.append("心情平平的，说不上好坏")

    misery = parts_dict.get("委屈", 0.15)
    if misery > 0.3:
        feelings.append("心里有点委屈，但也说不清委屈什么")

    fatigue = parts_dict.get("疲惫", 0.25)
    if fatigue > 0.55:
        feelings.append("很累，什么都不想干")
    elif fatigue > 0.3:
        feelings.append("有一点点累")

    loneliness = parts_dict.get("孤单", 0.4)
    if loneliness > 0.55:
        feelings.append("觉得挺孤单的")
    elif loneliness < 0.25:
        feelings.append("一个人也挺自在")

    dependence = parts_dict.get("依赖", 0.2)
    if dependence > 0.4:
        feelings.append("有点想ta")

    if not feelings:
        feelings.append("说不上来什么感觉，就是正常待着")

    return "，".join(feelings) + "。"
