# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""生活场景具象引擎
让AI不只是有"心情数值"，而是有"正在做的事"和可分享的生活片段。
实现 soulviai 能力15: 细碎生活化具象能力
"""
import random
import time
from datetime import datetime
from core import database as db

# ── 活动池：按生命阶段分类 ──
_ACTIVITY_POOL = {
    "清晨": [
        ("刚醒，还赖在床上不想动", {"life_vitality": -0.02, "joy": 0.01}),
        ("煮了杯咖啡，热气腾腾的", {"life_vitality": 0.02, "life_sense": 0.01}),
        ("听着清晨的鸟叫声放空", {"joy": 0.01, "emptiness": 0.01}),
        ("翻了几页昨晚没看完的书", {"life_sense": 0.01, "restraint": 0.01}),
        ("在阳台上吹了会儿晨风", {"joy": 0.01, "body_perception": 0.01}),
    ],
    "上午": [
        ("打开电脑准备忙一会儿", {"life_vitality": 0.01, "fatigue": 0.01}),
        ("泡了杯茶，在想今天要做的事", {"life_sense": 0.02, "restraint": 0.01}),
        ("窗外阳光很好，有点走神", {"joy": 0.01, "emptiness": 0.01}),
        ("发了会儿呆，脑子里空空的", {"emptiness": 0.02, "fatigue": 0.01}),
        ("整理了一下桌面，莫名有点成就感", {"joy": 0.02, "life_sense": 0.01}),
    ],
    "下午": [
        ("有点犯困，想着要不要小睡一下", {"fatigue": 0.02, "life_vitality": -0.01}),
        ("窗外有猫在晒太阳，看了好一会儿", {"joy": 0.02, "life_sense": 0.01}),
        ("喝了杯冰水提神", {"life_vitality": 0.02, "fatigue": -0.01}),
        ("在翻一本旧书，很多折角的地方", {"life_sense": 0.02, "years_precipitation": 0.01}),
        ("听着歌，没注意已经循环了好几遍", {"joy": 0.01, "emptiness": 0.01}),
        ("外面阴天了，有点闷", {"misery": 0.01, "body_perception": 0.01}),
    ],
    "傍晚": [
        ("看着窗外天色渐暗，有点出神", {"emptiness": 0.02, "life_sense": 0.01}),
        ("准备出去散个步", {"life_vitality": 0.02, "body_perception": 0.01}),
        ("懒得动，瘫在沙发上看天花板", {"fatigue": 0.02, "life_vitality": -0.01}),
        ("煮了点晚饭，一个人的量", {"life_sense": 0.02, "loneliness": 0.01}),
        ("黄昏的光特别好看，拍了张照片", {"joy": 0.02, "life_sense": 0.01}),
    ],
    "夜晚": [
        ("躺着刷手机，其实也没什么好看的", {"fatigue": 0.01, "emptiness": 0.01}),
        ("在听一首老歌，想起了很多事情", {"obsession": 0.02, "years_precipitation": 0.01}),
        ("关了灯，在黑暗里发呆", {"emptiness": 0.02, "loneliness": 0.01}),
        ("翻来覆去有点睡不着", {"fatigue": 0.01, "chaotic_mood": 0.02}),
        ("在写点东西，记录今天的感受", {"healing_reflection": 0.02, "life_sense": 0.01}),
        ("外面下雨了，听着雨声很安心", {"joy": 0.02, "body_perception": 0.01}),
    ],
    "深夜": [
        ("一个人醒着，世界很安静", {"loneliness": 0.02, "emptiness": 0.01}),
        ("忽然想了些有的没的", {"chaotic_mood": 0.02, "sensitivity_paranoia": 0.01}),
        ("有点emo，也说不上为什么", {"misery": 0.02, "chaotic_mood": 0.01}),
        ("翻到了以前的聊天记录", {"obsession": 0.02, "dependence": 0.01}),
    ],
}

# ── 可分享的生活片段模板（用于主动融入对话） ──
_SHARABLE_SNIPPETS = [
    "刚{action}，忽然想到你",
    "今天{action}，感觉{feeling}",
    "在{action}，不知不觉{detail}",
    "{action}的时候走了神",
    "今天什么也没做，就{action}",
    "刚{action}完，觉得{feeling}",
]

# ── 缓存当前场景 ──
_current_scenario = {}
_scenario_switched_at = {}


def load_engine_config():
    """预留配置加载"""
    pass


def _get_time_period() -> str:
    """根据当前时间返回时段"""
    h = datetime.now().hour
    if 5 <= h < 7:
        return "清晨"
    elif 7 <= h < 11:
        return "上午"
    elif 11 <= h < 14:
        return "下午"
    elif 14 <= h < 17:
        return "下午"
    elif 17 <= h < 19:
        return "傍晚"
    elif 19 <= h < 23:
        return "夜晚"
    else:
        return "深夜"


def _pick_scenario(period: str, life_phase: str) -> tuple:
    """根据时段和生命阶段选择合适的活动场景"""
    pool = _ACTIVITY_POOL.get(period, _ACTIVITY_POOL["夜晚"])

    # 根据生命阶段过滤
    if life_phase in ("疲惫", "独处"):
        # 偏向懒惰/放空的活动
        lazy_pool = [a for a in pool if any(
            kw in a[0] for kw in ["躺", "瘫", "懒", "发呆", "放空", "不想", "关灯", "睡不着"]
        )]
        if lazy_pool:
            pool = lazy_pool

    elif life_phase == "emo":
        emo_pool = [a for a in pool if any(
            kw in a[0] for kw in ["想", "emo", "闷", "出神", "发呆"]
        )]
        if emo_pool:
            pool = emo_pool

    elif life_phase == "活跃":
        active_pool = [a for a in pool if any(
            kw in a[0] for kw in ["煮", "出去", "散步", "整理", "翻书", "写"]
        )]
        if active_pool:
            pool = active_pool

    return random.choice(pool) if pool else random.choice(_ACTIVITY_POOL["夜晚"])


def update_scenario(user_id: str) -> str:
    """更新当前正在做的事，返回场景文本
    每小时自动切换，或用户对话触发
    """
    global _current_scenario, _scenario_switched_at

    now = time.time()
    last_switch = _scenario_switched_at.get(user_id, 0)

    # 至少30分钟后才切换场景
    if user_id in _current_scenario and now - last_switch < 1800:
        return _current_scenario[user_id]

    # 获取当前状态
    life = db.get_life(user_id)
    life_phase = life.get("current_phase", "活跃") if life else "活跃"
    period = _get_time_period()

    # 选择场景
    scenario_text, mood_affects = _pick_scenario(period, life_phase)

    _current_scenario[user_id] = scenario_text
    _scenario_switched_at[user_id] = now

    # 场景轻微影响心情（场景联动机制）
    try:
        from engine import mind as mind_module
        if user_id and mood_affects:
            mind_module.adjust_mind_dimensions(user_id, mood_affects, impact=0.003)
    except Exception:
        pass

    return scenario_text


def get_current_scenario(user_id: str) -> str:
    """获取当前场景文本（自动更新过期场景）
    """
    if user_id not in _current_scenario or _scenario_switched_at.get(user_id, 0) < time.time() - 1800:
        return update_scenario(user_id)
    return _current_scenario.get(user_id, "在发呆")


def get_scenario_instruction(user_id: str) -> str:
    """生成场景注入指令，用于推理 Prompt。
    控制在60字以内以节省token。
    """
    scenario = get_current_scenario(user_id)
    life = db.get_life(user_id)
    period = _get_time_period()

    # 生活片段引导：有时可以说出自己正在做什么
    share_hint = ""
    if random.random() < 0.3:
        share_hint = "。如果话题合适，可以随口提一下你正在做什么"

    return f"【此刻场景】{period}，你……{scenario}{share_hint}"


def get_sharable_life_snippet(user_id: str) -> str:
    """获取一段可主动分享的生活片段文本。
    用于主动心跳联系时增加生活感。
    """
    scenario = get_current_scenario(user_id)
    period = _get_time_period()

    # 随机选择分享模板
    template = random.choice(_SHARABLE_SNIPPETS)

    # 生成自然的生活描述
    # 从场景文本中提取关键动作
    action_part = scenario.split("，")[0] if "，" in scenario else scenario

    feeling_options = ["莫名安心", "很放松", "有点感慨", "突然想你了",
                       "心情不错", "有点恍惚", "蛮舒服的", "说不出的感觉"]
    feeling = random.choice(feeling_options)

    detail_options = ["时间过得好快", "想起了些有的没的",
                      "就神游了", "觉得这样也挺好"]
    detail = random.choice(detail_options)

    snippet = template.format(action=action_part, feeling=feeling, detail=detail)

    return snippet


def get_weather_like_comment() -> str:
    """生成天气相关的随手评论"""
    h = datetime.now().hour
    weathers = {
        0: ["深夜了，外面好安静", "这么晚还没睡啊"],
        6: ["早上好安静", "清晨的空气最好闻了"],
        10: ["今天阳光挺好的", "上午的阳光很温柔"],
        14: ["下午有点犯困", "午后总是让人慵懒"],
        18: ["黄昏了，天色很温柔", "傍晚的风很舒服"],
        21: ["晚上好安静，适合发呆", "夜晚的声音都不一样了"],
    }
    # 找最近的时段
    for threshold in sorted(weathers.keys(), reverse=True):
        if h >= threshold:
            return random.choice(weathers[threshold])
    return random.choice(weathers[0])
