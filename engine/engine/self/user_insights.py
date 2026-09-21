# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""用户画像系统（升级版）
================================
: 废弃关键词匹配，接入 user_persona.py LLM语义分析。
保留通信风格分析和微习惯检测作为辅助层。

: 长期观察用户习惯、喜好、性格特征，形成专属用户画像。
用于丰富对话，让AI感觉"越来越懂你"。
"""
import random
import re
from datetime import datetime
from core import database as db

# ── 用户画像缓存 ──
_profile_cache = {}

# 废弃关键词匹配，保留仅作为回退参考
# _INTEREST_PATTERNS 在 analyze_user_message 中不再作为主逻辑


def load_engine_config():
    pass


def get_user_profile(user_id: str) -> dict:
    """获取用户画像（带缓存）"""
    global _profile_cache
    if user_id in _profile_cache:
        return _profile_cache[user_id]

    # 尝试从DB加载
    try:
        profile = _load_profile_from_db(user_id)
    except Exception:
        profile = {"traits": {}, "interests": {}, "communication_style": "未知", "notes": []}

    _profile_cache[user_id] = profile
    return profile


def _load_profile_from_db(user_id: str) -> dict:
    """从message_log分析并构建画像，存入DB"""
    try:
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)

        # 确保用户画像表存在（新增 micro_habits 列）
        conn.execute("""
        CREATE TABLE IF NOT EXISTS user_profile (
                user_id TEXT UNIQUE NOT NULL,
                interests TEXT DEFAULT '{}',
                traits TEXT DEFAULT '{}',
                communication_style TEXT DEFAULT '未知',
                notes TEXT DEFAULT '[]',
                micro_habits TEXT DEFAULT '{}',
                message_count INTEGER DEFAULT 0,
                last_analyzed TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        try:
            conn.execute("ALTER TABLE user_profile ADD COLUMN micro_habits TEXT DEFAULT '{}'")
        except Exception:
            pass  # 列已存在
        conn.commit()

        # 加载已有画像
        row = conn.execute(
            "SELECT interests, traits, communication_style, notes, micro_habits FROM user_profile WHERE user_id = ?",
            (user_id,)
        ).fetchone()

        if row:
            import json
            profile = {
                "interests": json.loads(row[0]) if row[0] else {},
                "traits": json.loads(row[1]) if row[1] else {},
                "communication_style": row[2] or "未知",
                "notes": json.loads(row[3]) if row[3] else [],
                "micro_habits": json.loads(row[4]) if row[4] else {},
            }
        else:
            profile = {"interests": {}, "traits": {}, "communication_style": "未知",
                       "notes": [], "micro_habits": {}}

        conn.close()
        return profile
    except Exception:
        return {"interests": {}, "traits": {}, "communication_style": "未知",
                "notes": [], "micro_habits": {}}


def analyze_user_message(user_id: str, message: str):
    """分析用户消息，更新用户画像。
    提取兴趣关键词、沟通风格等特征。
    """
    profile = get_user_profile(user_id)

    # ── 兴趣提取 ──
    try:
        for category, keywords in _INTEREST_PATTERNS.items():
            for kw in keywords:
                if kw in message:
                    if category not in profile["interests"]:
                        profile["interests"][category] = 0
                    profile["interests"][category] += 1
                    break  # 每类只计一次
    except NameError:
        pass

    # ── 沟通风格分析 ──
    _analyze_communication_style(profile, message)

    # ── 画像保存 ──
    _save_profile_to_db(user_id, profile)
    _profile_cache[user_id] = profile


def _analyze_communication_style(profile: dict, message: str):
    """从消息中分析沟通风格 + 微习惯"""# 消息长度
    msg_len = len(message)

    # emoji检测
    emoji_count = len(re.findall(r'[\U0001F300-\U0001F9FF\u2600-\u26FF\u2700-\u27BF]', message))

    # 感叹号/语气词
    exclamation = message.count('!') + message.count('！')
    question = message.count('?') + message.count('？')

    # 简单启发式
    notes = profile.get("notes", [])
    micro_habits = profile.get("micro_habits", {})

    # ──  微习惯提取 ──

    # 常用口头禅检测
    common_phrases = ["哈哈", "笑死", "绝了", "离谱", "救命", "真的", "确实", "嗯嗯",
                      "啊啊", "就是说", "怎么说呢", "其实", "感觉", "好烦", "无语"]
    for phrase in common_phrases:
        if phrase in message and phrase not in micro_habits:
            micro_habits[f"口头禅:{phrase}"] = 1
        elif phrase in message and phrase in micro_habits:
            micro_habits[f"口头禅:{phrase}"] += 1

    # Emoji偏好
    if emoji_count >= 1:
        emojis = re.findall(r'[\U0001F300-\U0001F9FF\u2600-\u26FF\u2700-\u27BF]', message)
        for e in emojis:
            key = f"表情:{e}"
            micro_habits[key] = micro_habits.get(key, 0) + 1

    # 标点习惯
    if message.endswith("~"):
        micro_habits["标点:波浪号~"] = micro_habits.get("标点:波浪号~", 0) + 1
    if message.endswith("..."):
        micro_habits["标点:省略号"] = micro_habits.get("标点:省略号", 0) + 1

    # 回复长度偏好 (用分位数追踪)
    length_key = f"长度:{'短' if msg_len < 10 else '中' if msg_len < 50 else '长'}"
    micro_habits[length_key] = micro_habits.get(length_key, 0) + 1

    # 限制微习惯条目
    if len(micro_habits) > 20:
        # 保留计数最高的前15个
        top_habits = sorted(micro_habits.items(), key=lambda x: x[1], reverse=True)[:15]
        micro_habits = dict(top_habits)

    profile["micro_habits"] = micro_habits

    if msg_len < 5:
        if "简练型" not in str(notes):
            notes.append("喜欢简短回复")
    elif msg_len > 50:
        if "表达丰富" not in str(notes):
            notes.append("表达丰富")

    if emoji_count >= 2:
        if "常用表情" not in str(notes):
            notes.append("常用表情")

    if exclamation > 2:
        if "情绪饱满" not in str(notes):
            notes.append("情绪饱满")

    if question > 2:
        if "善于提问" not in str(notes):
            notes.append("善于提问")

    # 限制笔记数量
    profile["notes"] = notes[-8:]

    # 沟通风格判定
    if msg_len < 8:
        profile["communication_style"] = "简练直接"
    elif emoji_count > 3:
        profile["communication_style"] = "活泼热情"
    elif question > 3:
        profile["communication_style"] = "善于发问"
    else:
        profile["communication_style"] = "自然随性"


def _save_profile_to_db(user_id: str, profile: dict):
    """保存用户画像到数据库"""
    import json
    try:
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        conn.execute(
            """
            INSERT OR REPLACE INTO user_profile
               (user_id, interests, traits, communication_style, notes, micro_habits, last_analyzed)
               VALUES (?,?,?,?,?,?,?)""",
            (
                user_id,
                json.dumps(profile.get("interests", {}), ensure_ascii=False),
                json.dumps(profile.get("traits", {}), ensure_ascii=False),
                profile.get("communication_style", "未知"),
                json.dumps(profile.get("notes", []), ensure_ascii=False),
                json.dumps(profile.get("micro_habits", {}), ensure_ascii=False),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_profile_instruction(user_id: str) -> str:
    """生成用户画像注入指令（升级版）。
    优先使用 user_persona.py 的LLM语义分析结果。
    回退到原来的关键词画像。
    """# 优先使用深层用户人格模型
    try:
        from engine import user_persona as up_module
        persona_text = up_module.build_persona_summary(user_id)
        if persona_text:
            return persona_text + "\n（根据对ta的了解自然调整语气，不要刻意提这些信息）"
    except Exception:
        pass

    # 回退：原来的关键词画像
    profile = get_user_profile(user_id)
    parts = []

    # 兴趣
    interests = profile.get("interests", {})
    if interests:
        top = sorted(interests.items(), key=lambda x: x[1], reverse=True)[:3]
        interest_text = "、".join([f"{k}(提及{int(v)}次)" for k, v in top])
        parts.append(f"对方兴趣: {interest_text}")

    # 沟通风格
    style = profile.get("communication_style", "")
    if style and style != "未知":
        parts.append(f"沟通风格: {style}")

    # 特征笔记
    notes = profile.get("notes", [])
    if notes:
        parts.append(f"特征: {'；'.join(notes[-3:])}")

    # 微习惯（仅显著项目）
    micro = profile.get("micro_habits", {})
    if micro:
        top_micro = sorted(micro.items(), key=lambda x: x[1], reverse=True)[:3]
        micro_text = "、".join([k.replace("口头禅:", "").replace("表情:", "") for k, v in top_micro if v >= 2])
        if micro_text:
            parts.append(f"习惯: {micro_text}")

    if not parts:
        return ""

    return "【用户画像·专属观察】\n" + "\n".join(parts) + \
           "\n（根据对ta的了解自然调整语气，不要刻意提这些信息）"


def get_shared_interest_topics(user_id: str) -> str:
    """获取可聊的共同兴趣话题"""
    profile = get_user_profile(user_id)
    interests = profile.get("interests", {})
    if not interests:
        return ""

    top_interest = max(interests, key=interests.get)
    category_topics = {
        "音乐": "最近有听到什么好歌吗？",
        "电影": "最近有什么片子推荐吗？",
        "游戏": "最近在玩什么游戏？",
        "美食": "有没有什么好吃的推荐？",
        "运动": "最近还在坚持运动吗？",
        "旅行": "有没有想去的地方？",
        "读书": "最近在看什么书？",
        "宠物": "家里的小家伙最近怎么样？",
        "工作": "最近工作忙不忙？",
        "科技": "最近有什么新鲜的数码产品吗？",
    }
    return category_topics.get(top_interest, "")
