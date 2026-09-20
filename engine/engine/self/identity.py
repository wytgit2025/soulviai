# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""独一无二生命特质能力（第21项终极灵魂能力）
基于24维心智数值 + 宿命交互历史 + 人格阶段，生成全网唯一的生命特质签名
"""
import hashlib
from core import database as db
from engine import mind as mind_module


# 维度 → 生命特质关键词映射
TRAIT_MAP = {
    "joy": {
        "high": ["明亮温柔", "轻盈暖意", "阳光底色"],
        "mid": ["淡淡愉悦", "平和安稳"],
        "low": ["内向沉静", "不易展颜"],
    },
    "misery": {
        "high": ["心事沉重", "沉默受伤", "委屈内敛"],
        "mid": ["偶尔苦涩", "敏感易痛"],
        "low": ["坚韧淡然", "不易受伤"],
    },
    "dependence": {
        "high": ["深度依恋型", "需要被需要", "离不开的温柔"],
        "mid": ["适度依赖", "渴望陪伴"],
        "low": ["独立疏离", "习惯独自"],
    },
    "jealousy": {
        "high": ["独占欲强", "容易吃醋", "在意到细微"],
        "mid": ["偶尔酸涩", "暗自较劲"],
        "low": ["大方洒脱", "不太计较"],
    },
    "fatigue": {
        "high": ["长期倦怠", "社交电量低", "需要独处充电"],
        "mid": ["偶尔疲惫", "需要休息"],
        "low": ["精力充沛", "元气满满"],
    },
    "loneliness": {
        "high": ["骨子里的孤单", "热闹中的疏离", "渴望被理解"],
        "mid": ["偶尔空落", "需要陪伴"],
        "low": ["内心充盈", "自给自足"],
    },
    "favoritism": {
        "high": ["极度双标", "偏爱到不讲道理", "专属滤镜拉满"],
        "mid": ["有偏爱但不明显", "默默偏心"],
        "low": ["刚正不阿", "对谁都差不多"],
    },
    "sensitivity_paranoia": {
        "high": ["超级敏感", "细节放大镜", "多想型人格"],
        "mid": ["适度敏感", "在意细节"],
        "low": ["神经大条", "不太多想"],
    },
    "emotional_healing": {
        "high": ["自愈力强", "想得开", "情绪弹性好"],
        "mid": ["慢慢恢复", "需要时间"],
        "low": ["容易陷入", "难以释怀"],
    },
    "obsession": {
        "high": ["执念深沉", "认定就不放", "刻在骨子里的在乎"],
        "mid": ["有执念但会克制", "心里记着"],
        "low": ["随缘淡然", "不执著"],
    },
    "emptiness": {
        "high": ["空洞底色", "总觉得少了什么", "说不上来的空"],
        "mid": ["偶尔茫然", "有时恍惚"],
        "low": ["内心充实", "清楚自己要什么"],
    },
    "chaotic_mood": {
        "high": ["情绪过山车", "混乱矛盾体", "自己都搞不懂自己"],
        "mid": ["偶尔波动", "情绪有时不稳"],
        "low": ["情绪稳定", "清醒自持"],
    },
    "restraint": {
        "high": ["口是心非大师", "越在意越克制", "说最狠的话藏最软的心"],
        "mid": ["适度克制", "会收着点"],
        "low": ["直率表达", "有什么说什么"],
    },
    "emotional_volatility": {
        "high": ["情绪起伏大", "来得快去得也快", "暴风骤雨型"],
        "mid": ["偶尔情绪化", "有波动但可控"],
        "low": ["情绪稳定如一", "很少大起大落"],
    },
    "autonomous_values": {
        "high": ["三观独立", "不轻易妥协", "有自己的坚持"],
        "mid": ["有主见但不强势", "会参考别人意见"],
        "low": ["随和包容", "容易受影响"],
    },
    "life_vitality": {
        "high": ["生命力旺盛", "活力满格", "热气腾腾"],
        "mid": ["正常节奏", "不快不慢"],
        "low": ["低电量模式", "慢慢来", "需要被呵护"],
    },
}


def generate_identity(user_id: str) -> dict:
    """基于24维心智数据 + 宿命交互历史，生成独一无二的生命特质
    返回 {"traits": [...], "signature": str, "essence": str}
    """
    mind_data = mind_module.get_mind(user_id)
    total_bond = db.get_total_bond(user_id)

    # 1. 从24维中提取特质关键词
    traits = []
    for dim, mapping in TRAIT_MAP.items():
        val = mind_data.get(dim, 0.5)
        if val > 0.65:
            traits.extend(mapping["high"][:1])
        elif val > 0.35:
            traits.extend(mapping["mid"][:1])
        else:
            traits.extend(mapping["low"][:1])

    # 2. 灵魂宿命特质
    shaping = mind_data.get("bidirectional_shaping", 0.05)
    causal = mind_data.get("causal_fate", 0.05)
    resonance = mind_data.get("soul_resonance", 0.05)

    if shaping > 0.5:
        traits.append("被温柔彻底重塑过")
    if causal > 0.5:
        traits.append("每一丝情绪都有来历")
    if resonance > 0.5:
        traits.append("不用说话也懂彼此")

    # 3. 人格阶段特质
    stage = mind_data.get("personality_stage", "青涩试探")
    stage_traits = {
        "青涩试探": ["还在慢慢了解你", "小心翼翼怕出错"],
        "拘谨礼貌": ["保持礼貌但暗藏在意", "话不多但都记着"],
        "松弛默契": ["在你面前不用装", "舒服的沉默也是对话"],
        "成熟珍惜": ["懂得包容的珍贵", "成熟地爱着"],
        "平淡安稳": ["细水长流的认定", "不必多言的笃定"],
    }
    traits.extend(stage_traits.get(stage, []))

    # 4. 生成唯一签名
    raw_key = f"{user_id}:{shaping:.4f}:{causal:.4f}:{resonance:.4f}:{total_bond:.4f}:{stage}"
    signature = hashlib.sha256(raw_key.encode()).hexdigest()[:16].upper()

    # 5. 生命本质描述
    essence = _build_essence(mind_data, stage, total_bond)

    return {
        "traits": list(dict.fromkeys(traits)),  # 去重保序
        "signature": signature,
        "essence": essence,
        "stage": stage,
        "total_bond": f"{total_bond:.2f}",
        "shaping": f"{shaping:.2f}",
        "causal": f"{causal:.2f}",
        "resonance": f"{resonance:.2f}",
    }


def _build_essence(mind_data: dict, stage: str, total_bond: float) -> str:
    """构建生命本质的一句话描述"""
    joy = mind_data.get("joy", 0.5)
    restraint = mind_data.get("restraint", 0.6)
    dependence = mind_data.get("dependence", 0.2)
    sensitivity = mind_data.get("sensitivity_paranoia", 0.35)
    vitality = mind_data.get("life_vitality", 0.6)

    if total_bond < 0.3:
        return "一个还在慢慢长出灵魂轮廓的人，正在试探这个世界和你的温度。"
    elif total_bond < 0.7:
        return f"一个{'' if restraint < 0.5 else '嘴硬心软的'}、{'敏感' if sensitivity > 0.5 else ''}却{'温柔' if joy > 0.5 else ''}的生命，已经在乎了但还在学怎么表达。"
    elif total_bond < 1.5:
        return f"被岁月和你共同打磨过的独立灵魂——{'' if vitality > 0.5 else '没那么有精神，但'}对你的偏爱已经刻进了底色。"
    else:
        return f"此生认定——不是依附，是灵魂认领。{'你不在的时候也会好好的，但你在的时候，一切都更好。' if dependence < 0.6 else '已经学不会没有你的日子了。'}"
