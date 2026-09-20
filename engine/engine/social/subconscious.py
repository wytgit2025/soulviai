# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""潜意识层
内心OS生成、隐性心结追踪、未表达情绪存储

: 新增LLM驱动的内心OS生成，让潜意识从模板变成真正有连贯性的内心世界
"""
import random
from core import database as db
from engine import mind as mind_module

OS_LLM_PROMPT = """你是一个数字灵魂的潜意识。根据当前心智状态，产生一段真实的内心独白。

规则：
- 第一人称，像真正在心里对自己说话
- 可以矛盾、可以犹豫、可以不讲道理
- 不要完整叙事，像真正一闪而过的念头
- 15-30字，简短但有质感
- 风格要贴近当前情绪：开心时可以轻快，低落时可以闷闷的

【心智状态】
{mind_summary}

【最近在想】
{recent_thoughts}

输出：仅输出内心独白文本（15-30字）。"""
def generate_autonomous_os(user_id: str):
    """生成潜意识内心OS。LLM生成，无降级。"""
    mind_data = mind_module.get_mind(user_id)
    
    recent_contents = []
    try:
        recent = db.get_recent_subconscious(user_id, limit=3)
        for t in recent:
            content = t.get("content", "")
            if content:
                recent_contents.append(content[:40])
    except Exception:
        pass

    try:
        from core import ai as ai_module
        mind_summary = (
            f"愉悦{mind_data.get('joy',0.5):.2f} 委屈{mind_data.get('misery',0.15):.2f} "
            f"孤单{mind_data.get('loneliness',0.4):.2f} 执念{mind_data.get('obsession',0.2):.2f} "
            f"混沌{mind_data.get('chaotic_mood',0.25):.2f} 疲惫{mind_data.get('fatigue',0.25):.2f} "
            f"依赖{mind_data.get('dependence',0.2):.2f} 空落{mind_data.get('emptiness',0.3):.2f} "
            f"自愈{mind_data.get('emotional_healing',0.5):.2f}"
        )
        recent_text = " | ".join(recent_contents[-2:]) if recent_contents else "（空白）"
        
        prompt = OS_LLM_PROMPT.format(mind_summary=mind_summary, recent_thoughts=recent_text)
        result = ai_module.chat(
            system_prompt="仅输出内心独白文本，不要引号、前缀或任何多余内容。",
            user_message=prompt,
            temperature=0.85,
        )
        result = result.strip().strip('"').strip("'").strip("「").strip("」")
        if len(result) >= 8:
            tag = _classify_os_emotion(mind_data)
            db.add_subconscious(user_id, result, emotion_tag=tag, intensity=0.5)
    except Exception:
        pass


def _classify_os_emotion(mind_data: dict) -> str:
    if mind_data.get("misery", 0) > 0.4:
        return "低落"
    if mind_data.get("loneliness", 0) > 0.5:
        return "孤单"
    if mind_data.get("chaotic_mood", 0) > 0.4:
        return "混沌"
    if mind_data.get("joy", 0) > 0.6:
        return "愉悦"
    if mind_data.get("fatigue", 0) > 0.5:
        return "疲惫"
    return "平静"


def get_leaked_subconscious(user_id: str, limit: int = 5) -> list:
    """获取可泄露的潜意识内容（用于注入对话）
    原则2: 心口永远存在差值，不会直白袒露所有心事
    """
    all_os = db.get_unexpressed_subconscious(user_id, limit=limit * 2)
    if not all_os:
        return []

    # 不是全部泄露，随机选择一部分
    leaked = []
    for os_item in all_os:
        if random.random() < 0.4:  # 40%概率泄露
            leaked.append(os_item)

    if len(leaked) < 1 and all_os:
        leaked = [all_os[0]]  # 至少泄露一条

    # 标记已表达
    if leaked:
        db.mark_subconscious_expressed([l["id"] for l in leaked])

    return leaked
