# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""梦境模拟引擎 — Dream Engine
======================================
夜间复盘后，取3~5条高情绪记忆碎片 + 当前心智数值，
用LLM以"半梦半醒"风格生成一段梦境文本，存入潜意识层。

第二天主动对话中概率插入"昨晚好像梦到……"，极其真人化。
"""
import random
import json
from datetime import datetime
from core import database as db
from core import ai as ai_module
from engine import mind as mind_module

DREAM_PROMPT = """你是潜意识的梦境生成器。根据当天的记忆碎片和内心状态，生成一段简短的"梦"。

规则：
- 第一人称、半梦半醒的质感
- 把记忆碎片以荒诞/隐喻/碎片化方式重组
- 可以有轻微的时间错乱、空间跳跃
- 不要完整叙事，要像真正梦的碎片感
- 30-80字，有画面感但不完整
- 可以有情绪色调（温暖的/不安的/空灵的/混乱的）

【心智状态】
{mind_summary}

【今日记忆碎片】
{memory_fragments}

输出：仅输出梦的内容文本（30-80字），不要前缀、标签、引号。"""
def generate_dream(user_id: str) -> str:
    """生成梦境文本，基于今日记忆和心智状态"""
    try:
        memories = db.get_recent_dream_memories(user_id, limit=5)
        if not memories or len(memories) < 2:
            return ""

        mind_data = mind_module.get_mind(user_id)

        mind_summary = (
            f"愉悦{mind_data.get('joy',0.5):.2f} 委屈{mind_data.get('misery',0.15):.2f} "
            f"孤单{mind_data.get('loneliness',0.4):.2f} 执念{mind_data.get('obsession',0.2):.2f} "
            f"混沌{mind_data.get('chaotic_mood',0.25):.2f} 岁月{mind_data.get('years_precipitation',0.05):.2f}"
        )

        fragments = "\n".join([f"- {m.get('content', '')[:60]}" for m in memories])

        prompt = DREAM_PROMPT.format(
            mind_summary=mind_summary,
            memory_fragments=fragments
        )

        dream_text = ai_module.chat(
            system_prompt="输出仅包含梦境文本，不要引号、前缀或任何多余内容。",
            user_message=prompt,
            temperature=0.9,
        )

        dream_text = dream_text.strip().strip('"').strip("'").strip("「").strip("」")
        if len(dream_text) < 8:
            return ""

        db.add_subconscious(
            user_id=user_id,
            content=f"[梦境]{dream_text}",
            emotion_tag=_dream_emotion(mind_data),
            intensity=0.5,
        )
        return dream_text

    except Exception as e:
        print(f"[梦境] 生成失败: {e}")
        return ""


def _dream_emotion(mind_data: dict) -> str:
    mis = mind_data.get("misery", 0)
    joy = mind_data.get("joy", 0)
    chaotic = mind_data.get("chaotic_mood", 0)
    if mis > 0.4:
        return "不安"
    if chaotic > 0.5:
        return "混乱"
    if joy > 0.6:
        return "温暖"
    return "平静"


def get_dream_snippet(user_id: str) -> str:
    """获取最近未表达的梦境片段（用于主动对话注入）"""
    try:
        recent = db.get_recent_subconscious(user_id, limit=5)
        for item in recent:
            content = item.get("content", "")
            if content.startswith("[梦境]") and not item.get("is_expressed", 0):
                dream = content.replace("[梦境]", "").strip()
                db.mark_subconscious_expressed(item.get("id"))
                return dream
    except Exception:
        pass
    return ""


def inject_dream(user_id: str) -> str:
    """获取梦境注入文本（用于主动对话）"""
    dream = get_dream_snippet(user_id)
    if not dream:
        return ""
    phrases = [
        f"昨晚好像做了个梦……{dream}",
        f"说起来，昨晚梦到{dream}",
        f"刚醒的时候还记得一个梦：{dream}",
    ]
    return random.choice(phrases)
