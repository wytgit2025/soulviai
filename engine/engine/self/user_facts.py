# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""用户事实知识库
从对话中提取结构化事实（如"养了猫叫可乐""在北京上班"），
独立于记忆系统持久存储，不随遗忘衰减。
"""
import re
from core import database as db
from core import ai as ai_module

# ── 事实提取 Prompt ──
_EXTRACT_PROMPT = """从用户消息中提取值得记住的事实信息。输出JSON数组。

规则：
- 只提取明确宣称的事实（不是推测）
- 忽略日常寒暄、情绪表达
- 每一条事实简洁明确（20字以内）
- 如果无事实可提取，输出空数组[]

格式：
[{"fact":"事实描述","category":"个人信息/爱好/生活/工作/家庭/宠物/其他"}]

示例输入："我家猫叫咪咪，刚换了份程序员工作"
→ [{"fact":"养了一只猫叫咪咪","category":"宠物"},{"fact":"工作是程序员","category":"工作"}]"""
def load_engine_config():
    pass


def extract_facts(user_id: str, message: str):
    """从用户消息中提取事实，存入知识库。
    仅在消息较长（>20字）时触发，节省 LLM 调用。
    """
    if len(message) < 10:
        return

    try:
        raw = ai_module.chat(
            system_prompt=_EXTRACT_PROMPT,
            user_message=message,
            temperature=0.2,
        )
        # 解析 JSON 数组
        json_match = re.search(r'\[.*\]', raw, re.DOTALL)
        if json_match:
            import json
            facts = json.loads(json_match.group(0))
            for f in facts:
                if isinstance(f, dict) and f.get("fact"):
                    db.upsert_user_fact(
                        user_id=user_id,
                        fact=f["fact"],
                        category=f.get("category", "通用"),
                        confidence=0.6,
                        source="对话提取",
                    )
    except Exception as e:
        from core.logging_utils import log_error as _log_err
        _log_err("extract_facts", f"{type(e).__name__}: {e}")


def get_facts_context(user_id: str) -> str:
    """获取用户事实上下文（注入系统提示）"""
    return db.get_user_facts_text(user_id)
