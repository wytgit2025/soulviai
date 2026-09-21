# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""用户个人档案引擎
双向身份系统的另一半——让AI认识正在聊天的这个人。
支持从对话中自动学习（名字/称呼/职业/兴趣），也支持手动设置。
"""
from __future__ import annotations
import json
import re
from core import database as db

_USER_PROFILE_EXTRACT_PROMPT = """你是一个用户信息提取器。分析用户消息，判断是否包含身份信息。

【输入】用户消息
【任务】提取用户的身份信息

输出格式（严格JSON）：
{
  "has_info": true或false,
  "name": "提取的名字（如'张三'），没有则为空字符串",
  "display_name": "提取的称呼（如'小李'、'老王'），没有则为空字符串",
  "preferred_name": "用户明确偏好的称呼（如'叫我姐姐'→'姐姐'），没有则为空字符串",
  "gender": "推断的性别（男/女），不确定则为空字符串",
  "age": "提取的年龄，没有则为空字符串",
  "occupation": "提取的职业（如'程序员'），没有则为空字符串",
  "hobbies": "提取的兴趣爱好（用逗号分隔，如'打篮球,看动漫'），没有则为空字符串"
}

规则：
- 只提取用户明确提到的信息，不要猜测
- "我叫xxx" → name="xxx"
- "叫我小李就行" → display_name="小李"
- "我是做设计的" → occupation="设计"
- "我喜欢打篮球" → hobbies="打篮球"
- "我是个28岁的程序员" → age="28", occupation="程序员"
- 如果消息没有任何身份信息，has_info=false
"""
def load_engine_config():
    pass


def get_profile(user_id: str):
    """获取用户的身份档案，返回 dict 或 None"""
    return db.get_user_identity(user_id)


def init_profile(user_id: str, config: dict = None):
    """初始化用户身份档案（仅当不存在时）"""
    auto_learn = True
    if config:
        auto_learn = config.get("auto_learn", True)
    db.init_user_identity(user_id, auto_learn=auto_learn)


def save_profile(user_id: str, **kwargs):
    """更新用户身份档案字段"""
    db.save_user_identity(user_id, **kwargs)


def build_identity_text(user_id: str) -> str:
    """构建简短身份文本（用于 thinking.py 系统提示注入）。
    例："正在和你聊天的人叫「小李」，是个男生。"
    空档案返回空字符串。
    """
    profile = db.get_user_identity(user_id)
    if not profile:
        return ""

    # 确定称呼：preferred_name > display_name > name
    name = (profile.get("preferred_name", "") or
            profile.get("display_name", "") or
            profile.get("name", ""))
    if not name:
        return ""

    gender = profile.get("gender", "")
    gender_text = ""
    if gender == "男":
        gender_text = "，是个男生"
    elif gender == "女":
        gender_text = "，是个女生"

    return f"正在和你聊天的人叫「{name}」{gender_text}。"


def build_context_text(user_id: str) -> str:
    """构建档案上下文文本（用于 inference.py scene_blocks 注入）。
    例："小李是个28岁的程序员，平时喜欢打篮球和看动漫。"
    空档案返回空字符串。
    """
    profile = db.get_user_identity(user_id)
    if not profile:
        return ""

    # 确定称呼
    name = (profile.get("preferred_name", "") or
            profile.get("display_name", "") or
            profile.get("name", ""))
    if not name:
        return ""

    details = []
    age = profile.get("age", "")
    occupation = profile.get("occupation", "")
    hobbies = profile.get("hobbies", "")

    if age:
        details.append(f"{age}岁")
    if occupation:
        details.append(occupation)

    detail_text = f"是个{''.join(details)}" if details else ""

    result = f"{name}"
    if detail_text:
        result += detail_text
    if hobbies:
        result += f"，平时喜欢{hobbies}"

    return f"{result}。"


def needs_ask_name(user_id: str) -> bool:
    """检查是否需要询问用户称呼（档案为空 + 自动学习开启）"""
    profile = db.get_user_identity(user_id)
    if not profile:
        return True
    # 档案存在但没有任何名字信息 → 需要问
    has_name = (profile.get("name") or profile.get("display_name") or
                profile.get("preferred_name"))
    auto_learn = profile.get("auto_learn", 1)
    return not has_name and auto_learn == 1


def get_ask_name_guide(user_id: str) -> str:
    """生成询问称呼的场景引导文本"""
    if not needs_ask_name(user_id):
        return ""
    return ("你还不认识对方——不知道ta叫什么、怎么称呼。"
            "如果对话自然地进行到了合适的时机，可以问一下'怎么称呼你？'。"
            "但不要生硬地一开始就问，等聊了几句氛围到了再自然地问。")


def extract_from_message(user_id: str, message: str):
    """从用户消息中提取身份信息并更新档案。
    使用 LLM 轻量解析，提取名字/称呼/性别/年龄/职业/兴趣。
    静默失败，不影响主流程。
    """
    try:
        profile = db.get_user_identity(user_id)
        if not profile or not profile.get("auto_learn", 1):
            return

        # 用 LLM 解析消息
        from core import ai as ai_module
        raw = ai_module.chat(
            system_prompt=_USER_PROFILE_EXTRACT_PROMPT,
            user_message=f"【用户消息】{message[:200]}",
            temperature=0.15,
        )
        if not raw:
            return

        # 解析 JSON
        json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
        if not json_match:
            return

        data = json.loads(json_match.group(0))
        if not data.get("has_info", False):
            return

        # 合并更新
        updates = {}
        if data.get("name"):
            updates["name"] = data["name"].strip()[:20]
        if data.get("display_name"):
            updates["display_name"] = data["display_name"].strip()[:20]
        if data.get("preferred_name"):
            updates["preferred_name"] = data["preferred_name"].strip()[:20]
        if data.get("gender") and not profile.get("gender"):
            updates["gender"] = data["gender"].strip()[:2]
        if data.get("age") and not profile.get("age"):
            updates["age"] = data["age"].strip()[:10]
        if data.get("occupation"):
            updates["occupation"] = data["occupation"].strip()[:30]
        if data.get("hobbies"):
            existing = profile.get("hobbies", "")
            new_hobby = data["hobbies"].strip()[:60]
            if existing:
                # 合并不重复的兴趣
                exist_set = set(h.strip() for h in existing.split(",") if h.strip())
                new_set = set(h.strip() for h in new_hobby.split(",") if h.strip())
                merged = ", ".join(exist_set | new_set)
                updates["hobbies"] = merged[:100]
            else:
                updates["hobbies"] = new_hobby

        if updates:
            db.save_user_identity(user_id, **updates)
            print(f"[用户档案] 学习到: {updates}")

    except Exception as e:
        # 静默失败
        pass
