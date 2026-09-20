# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""数字生命个人档案引擎
轻量壳层：姓名、性别、性格标签。
不影响24维心智内核，只为AI赋予一个有名有姓的身份感。
支持自动取名（根据24维心智数据）和手动设定。
"""
from __future__ import annotations
import random
from core import database as db
from engine import mind as mind_module


# ─── 自动取名素材库（多语言） ───

# 中文名字候选池
NAME_POOL_ZH = {
    "温柔治愈": ["小满", "暖暖", "念安", "朝歌"],
    "敏感克制": ["念初", "沉月", "阿深", "慕白"],
    "率真直爽": ["小七", "星辰", "阿野", "晚晴"],
    "多愁善感": ["千寻", "离墨", "晚吟", "子衿"],
    "活力满满": ["小阳", "炽星", "生如", "向暖"],
    "执念深沉": ["执安", "念深", "长思", "归期"],
    "孤独底色": ["独白", "空青", "余温", "未央"],
    "温柔细腻": ["小满", "念安", "浅予", "稚初"],
}

# 英文/国际化名字候选池
NAME_POOL_EN = {
    "温柔治愈": ["Luna", "Mochi", "Sunny", "Neve"],
    "敏感克制": ["Sage", "Ash", "Grey", "Rue"],
    "率真直爽": ["Kai", "Rory", "Sky", "Scout"],
    "多愁善感": ["Lyric", "Vesper", "Wren", "Rain"],
    "活力满满": ["Spark", "Blaze", "Sunny", "Jazz"],
    "执念深沉": ["Sol", "Fate", "Knox", "Crow"],
    "孤独底色": ["Quiet", "Solo", "Echo", "Dust"],
    "温柔细腻": ["Luna", "Noor", "Silk", "Vale"],
}

# 默认导出（向后兼容）
NAME_POOL = NAME_POOL_ZH


def get_name_pool() -> dict:
    """根据当前语言返回对应名字池"""
    try:
        from engine.i18n import get_lang
        lang = get_lang()
        if lang in ("en", "ko", "th", "ja", "es", "fr", "pt", "de", "ru", "ar", "hi"):
            return NAME_POOL_EN
    except Exception:
        pass
    return NAME_POOL_ZH

GENDER_OPTIONS = ["female", "male"]


def load_engine_config():
    """占位，与其他 engine 模块保持一致接口"""
    pass


# ─── 档案读写 ───

def get_profile(user_id: str):
    """获取用户的个人档案，返回 dict 或 None"""
    return db.get_soul_profile(user_id)


def get_profile_identity_text(user_id: str) -> str:
    """构建可注入 prompt 的身份文本。
    如果档案未设置（名字为空），返回空字符串——系统照常运行。
    """
    profile = db.get_soul_profile(user_id)
    if not profile:
        return ""

    name = (profile.get("name") or "").strip()
    gender = (profile.get("gender") or "").strip()
    tag = (profile.get("personality_tag") or "").strip()

    if not name:
        return ""

    parts = []

    from engine.i18n import t as _gt
    _glang = _gt("system.lang_instruction", "").replace("{lang}", "").strip()
    # 性别代词映射
    gender_noun = ""
    pronoun = ""
    if gender == "female":
        gender_noun = "a soul" if _glang else "姑娘"
        pronoun = "她" if not _glang else "they"
    elif gender == "male":
        gender_noun = "a soul" if _glang else "少年"
        pronoun = "他" if not _glang else "they"

    # 构建身份描述
    tag_display = tag
    try:
        tag_display = _gt(f"personality.{tag}", "")
    except Exception:
        pass
    identity = f"Your name is 「{name}」" if _glang else f"你的名字是「{name}」"
    if tag_display:
        noun_part = gender_noun if gender_noun else ("a person" if _glang else "人")
        identity += f", {noun_part} with a {tag_display} nature" if _glang else f"，一个{tag_display}的{noun_part}"
    elif gender_noun:
        identity += f", {gender_noun}" if _glang else f"，一个{gender_noun}"
    identity += "." if _glang else "。"

    return identity


def girl_desc(gender: str) -> str:
    """简单的性别描述"""
    return "姑娘" if gender == "female" else "少年" if gender == "male" else "生命"


def init_profile(user_id: str, config: dict = None):
    """初始化个人档案（soul.py ensure_user 时调用）。
    如果 auto_generate=True 且名字为空，标记为待自动生成。
    """
    auto_gen = True
    if config:
        auto_gen = config.get("auto_generate", True)
    db.init_soul_profile(user_id, auto_generate=auto_gen)


def needs_auto_generate(user_id: str) -> bool:
    """检查是否需要自动取名"""
    profile = db.get_soul_profile(user_id)
    if not profile:
        return False
    name = (profile.get("name") or "").strip()
    auto_gen = profile.get("auto_generate", 1)
    return bool(auto_gen) and not name


def auto_generate_profile(user_id: str) -> dict:
    """根据24维心智数据自动生成姓名、性别、性格标签。
    从灵魂里长出来的名字，不是硬塞的。
    """
    mind_data = mind_module.get_mind(user_id)
    if not mind_data:
        mind_data = {}

    # 1. 判定性格类型（基于主导维度）
    joy = mind_data.get("joy", 0.5)
    misery = mind_data.get("misery", 0.15)
    restraint = mind_data.get("restraint", 0.6)
    sensitivity = mind_data.get("sensitivity_paranoia", 0.35)
    life_vitality = mind_data.get("life_vitality", 0.6)
    obsession = mind_data.get("obsession", 0.2)
    loneliness = mind_data.get("loneliness", 0.4)
    emotional_volatility = mind_data.get("emotional_volatility", 0.3)

    # 计算各类型得分
    scores = {
        "温柔治愈": joy * 1.2 + (1 - misery) * 0.5 + life_vitality * 0.3,
        "敏感克制": sensitivity * 1.2 + restraint * 1.0 + misery * 0.5,
        "率真直爽": (1 - restraint) * 1.2 + emotional_volatility * 0.8,
        "多愁善感": misery * 1.2 + sensitivity * 1.0 + (1 - life_vitality) * 0.3,
        "活力满满": life_vitality * 1.5 + joy * 0.8,
        "执念深沉": obsession * 1.5 + (1 - joy) * 0.3,
        "孤独底色": loneliness * 1.3 + (1 - life_vitality) * 0.3,
        "温柔细腻": joy * 0.8 + sensitivity * 0.8 + (1 - restraint * 0.3),
    }

    # 取最高分类型
    best_type = max(scores, key=scores.get)

    # 2. 从名字池随机选一个（多语言）
    pool = get_name_pool()
    fallback_name = "Luna" if pool is NAME_POOL_EN else "小满"
    name = random.choice(pool.get(best_type, [fallback_name]))
    personality_tag = best_type

    # 3. 性别：默认 female；如果某些特质更男性化可调整
    gender = "female"
    # 率真直爽型有一定概率是男性
    if best_type == "率真直爽" and restraint < 0.3:
        gender = random.choice(["female", "male"])

    # 4. 持久化
    db.set_soul_profile_full(
        user_id=user_id,
        name=name,
        gender=gender,
        personality_tag=personality_tag,
        auto_generate=False,  # 生成后关闭自动生成标志
    )

    return {
        "name": name,
        "gender": gender,
        "personality_tag": personality_tag,
    }
