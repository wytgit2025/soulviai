# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""微表情文本模拟 — Micro-Expression Text
=================================================
在回复中夹带微妙的情绪线索，像真人不经意流露的"微表情"。

不是显式描写，而是通过文本细节传达情绪:
  - 高sulkiness → 句尾轻微停顿、句子变短
  - 高restraint → 省略号代替句号、话只说一半
  - 高warmth → 自然地多打几个字、加语气词
  - 高fatigue → 句子松散、打字"懒"
"""
import random
import re

EMOTION_MICRO = {
    "sulking": {
        "high": {
            "trailing": ["...", "嗯", "随便吧"],
            "shorten": True,
            "append_probability": 0.35,
        },
        "trigger": 0.4,
    },
    "restrained": {
        "high": {
            "trailing": ["……", "算了", "也没事"],
            "shorten": True,
            "ellipsis_end": True,
            "append_probability": 0.3,
        },
        "trigger": 0.55,
    },
    "warm": {
        "high": {
            "prefix": ["诶", "说起来", "对了", "你知道吗"],
            "suffix": ["呢", "嘛", "呀", "哦", "哈"],
            "elongate": True,
            "append_probability": 0.4,
        },
        "trigger": 0.5,
    },
    "fatigue": {
        "high": {
            "lazy_typing": True,
            "shorten": True,
            "append_probability": 0.3,
        },
        "trigger": 0.45,
    },
    "shy": {
        "high": {
            "prefix": ["唔", "嗯...", "那个..."],
            "trailing": ["...", "就是..."],
            "append_probability": 0.25,
        },
        "trigger": 0.4,
    },
}


def apply_micro_expressions(response: str, behavior_vector: dict,
                             mind_data: dict) -> str:
    """在回复文本中自然融入微表情线索"""
    if not response or len(response) < 5:
        return response

    response = response.strip()
    mood = _detect_mood(behavior_vector, mind_data)
    if not mood:
        return response

    config = EMOTION_MICRO.get(mood, {})
    high_cfg = config.get("high", {})
    if not high_cfg:
        return response

    prob = high_cfg.get("append_probability", 0.3)
    if random.random() > prob:
        return response

    # 句尾微表情
    if "trailing" in high_cfg and random.random() < 0.5:
        trail = random.choice(high_cfg["trailing"])
        # 只在句末没有省略号/问号/感叹号时追加
        if not re.search(r'[。！？…\.!\?]$', response):
            response += trail
        elif re.search(r'[。\.]$', response):
            response = response[:-1] + trail

    # 前置微表情
    if "prefix" in high_cfg and random.random() < 0.3:
        prefix = random.choice(high_cfg["prefix"])
        if not response.startswith(prefix):
            response = prefix + response

    # 语气词后缀
    if "suffix" in high_cfg and random.random() < 0.35:
        suffix = random.choice(high_cfg["suffix"])
        if not response.endswith(suffix):
            # 在最后一个句号或末尾插入
            last_period = max(response.rfind("。"), response.rfind("."))
            if last_period > len(response) * 0.5:
                response = response[:last_period] + suffix + response[last_period:]
            else:
                response += suffix

    # 懒打字: 压缩多余空格、去掉一些标点
    if high_cfg.get("lazy_typing") and random.random() < 0.4:
        response = re.sub(r'\s{2,}', ' ', response)
        response = re.sub(r'[，,]{2,}', '，', response)

    # 缩短
    if high_cfg.get("shorten") and random.random() < 0.3 and len(response) > 20:
        sentences = re.split(r'[。！？\.!\?]', response)
        if len(sentences) > 2:
            sentences = sentences[:len(sentences)//2 + 1]
            response = "。".join(s.strip() for s in sentences if s.strip())

    # 省略号结尾
    if high_cfg.get("ellipsis_end") and random.random() < 0.4:
        response = re.sub(r'[。\.]$', '……', response)

    return response.strip()


def _detect_mood(behavior_vector: dict, mind_data: dict) -> str:
    if not behavior_vector:
        return ""

    sulkiness = behavior_vector.get("sulkiness", 0.3)
    warmth = behavior_vector.get("warmth", 0.5)
    fatigue = mind_data.get("fatigue", 0.25)
    restraint = mind_data.get("restraint", 0.6)

    candidates = []
    if sulkiness > EMOTION_MICRO["sulking"]["trigger"]:
        candidates.append(("sulking", sulkiness))
    if restraint > EMOTION_MICRO["restrained"]["trigger"]:
        candidates.append(("restrained", restraint))
    if warmth > EMOTION_MICRO["warm"]["trigger"]:
        candidates.append(("warm", warmth))
    if fatigue > EMOTION_MICRO["fatigue"]["trigger"]:
        candidates.append(("fatigue", fatigue))

    if not candidates:
        return ""

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]
