# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""前瞻性记忆引擎 — Prospective Memory
==============================================
让AI记住"下次要问ta的事"，下次对话自动注入。
解决"每次都像第一次见面"的根本问题。

机制:
  1. LLM理解层检测"将来要做的事"意图 → 存入pending_intentions表
  2. 下次对话开头/合适时机 → 自动扫描并注入
  3. 已完成的意图自动标记，避免重复
"""
import json
import re
from datetime import datetime
from core import database as db
from core import ai as ai_module

EXTRACTION_PROMPT = """分析以下AI回复，判断其中是否包含"下次要记得做/问的事"。

需要检测的意图类型:
- 记得问: "我下次要问问ta面试结果"、"回头问ta那个事情怎么样了"
- 记得做: "下次给ta推荐那首歌"、"改天跟ta聊聊那个话题"
- 等待回复: "等ta告诉我结果"、"ta说回头跟我说"
- 关心跟进: "ta身体不舒服，下次要关心一下"

用户原始消息: {user_message}
AI回复: {ai_response}

输出JSON:
{"has_intention": true/false, "intentions": [{"type":"ask/do/wait/care","content":"简短描述15字内","trigger_keywords":["关键词1","关键词2"]}]}

仅输出JSON。"""
def extract_intentions(user_id: str, user_message: str, ai_response: str,
                       comprehension: dict = None):
    """从交互中提取前瞻意图"""
    try:
        prompt = EXTRACTION_PROMPT.format(
            user_message=user_message[:100],
            ai_response=ai_response[:200]
        )
        result = ai_module.chat(
            system_prompt="仅输出JSON，不要其他内容。",
            user_message=prompt,
            temperature=0.2,
        )
        start = result.find("{")
        end = result.rfind("}")
        if start == -1 or end == -1:
            return
        data = json.loads(result[start:end+1])
        if not data.get("has_intention"):
            return

        for intent in data.get("intentions", []):
            db.add_pending_intention(
                user_id=user_id,
                content=intent.get("content", ""),
                intent_type=intent.get("type", "ask"),
                trigger_keywords=json.dumps(intent.get("trigger_keywords", [])),
            )
    except Exception:
        pass


def get_pending_intentions(user_id: str, limit: int = 3) -> list:
    """获取待触发的意图列表"""
    return db.get_pending_intentions(user_id, limit=limit)


def get_injection_text(user_id: str, current_message: str = "") -> str:
    """获取前瞻记忆注入文本，用于主动对话中。
    匹配当前消息与触发关键词，找到最相关的意图。
    """
    intentions = get_pending_intentions(user_id, limit=5)
    if not intentions:
        return ""

    injection_templates = {
        "ask": "对了，上次说的{content}，后来怎么样了？",
        "do": "说起来，之前想着{content}——现在正好想起来了",
        "wait": "之前说{content}，有后续了吗？",
        "care": "忽然想起来，{content}，现在好点了吗？",
    }

    for intent in intentions:
        content = intent.get("content", "")
        i_type = intent.get("intent_type", "ask")
        try:
            keywords = json.loads(intent.get("trigger_keywords", "[]"))
        except Exception:
            keywords = []

        # 如果能匹配到当前消息的关键词，更自然
        if current_message and keywords:
            match = any(kw in current_message for kw in keywords)
            if match:
                template = injection_templates.get(i_type, injection_templates["ask"])
                db.mark_intention_done(intent.get("id"))
                return template.format(content=content)

    # 没有关键词匹配则取第一条
    first = intentions[0]
    template = injection_templates.get(first.get("intent_type", "ask"), injection_templates["ask"])
    return template.format(content=first.get("content", ""))


def check_and_inject(user_id: str, current_message: str) -> str:
    """检查是否需要注入前瞻记忆，返回注入文本或空字符串"""
    try:
        hours_since_last = db.hours_since_last_interaction(user_id)
        if hours_since_last and hours_since_last > 2:
            return get_injection_text(user_id, current_message)
    except Exception:
        pass
    return ""
