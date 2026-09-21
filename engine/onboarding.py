# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""
首次启动 · 人格探索问答
独立脚本，不依赖引擎任何模块。
通过 6 道趣味选择题，生成初始 24 维人格数值写入 config.json。
只运行一次（_onboarding_done=true 后跳过）。
"""
import json
import os
import sys
import random
import math

CONFIG_PATH = "config.json"


def _load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _check_done(cfg) -> bool:
    return cfg.get("_onboarding_done", False)


# ── 语言选择 ──

# 注：早期版本曾通过 ip-api.com 自动 IP 定位推断用户国家 → 推荐语言，
# 该行为与"项目无遥测、不联网"的承诺冲突，已彻底删除（2026-09）。
# 当前首次启动直接走手动选单；用户想改语言可后续写入 config.json 的 lang 字段。


def _select_language() -> str:
    """首次启动语言选择（手动选单）。"""
    print("\n  🌐 " + "=" * 44)
    print("  🌐  选择语言 / Select Language / 言語選択")
    print("  🌐 " + "=" * 44)
    print()
    langs = _LANG_LIST
    for i, (name, code) in enumerate(langs, 1):
        print(f"    {i:2d}. {name}")
    print()
    while True:
        try:
            inp = input("  >>> ").strip()
            idx = int(inp) - 1
            if 0 <= idx < len(langs):
                return langs[idx][1]
        except (EOFError, KeyboardInterrupt):
            # EOF 不是「输入不合法」，是「根本没有人在输入」（stdin 被重定向、
            # 后台运行、docker 没带 -it）。原来它和 ValueError 一起被 pass 掉，
            # 而下面这段重试没有 sleep —— 无 TTY 时会退化成不带退避的死循环：
            # 实测 25 秒写出 1.5GB 日志（4100 万行）并打满一个核。
            # _ask_question 对 EOF 是直接退出的，这里与它对齐。
            print("\n  " + _("onboarding.exit", "zh"))
            sys.exit(1)
        except ValueError:
            pass
        print("  " + "=" * 40)
        print("  " + _("onboarding.lang_invalid", "zh"))
        print("  " + "Please enter a number between 1-13")
        print("  " + "1〜13の数字を入力してください")
        print("  " + "=" * 40)


_LANG_LIST = [
    ("简体中文", "zh"),
    ("繁體中文", "zh_tw"),
    ("English", "en"),
    ("한국어", "ko"),
    ("ไทย", "th"),
    ("日本語", "ja"),
    ("Español", "es"),
    ("Français", "fr"),
    ("Português", "pt"),
    ("Deutsch", "de"),
    ("Русский", "ru"),
    ("العربية", "ar"),
    ("हिन्दी", "hi"),
]


# ── 多语言辅助 ──

_Q_LABEL_EN = {
    "q_energy": "How do you spend a free weekend with no obligations?",
    "q_info": "When reading an article or watching a video that interests you, what do you focus on most?",
    "q_decision": "When making an important decision, what influences you the most?",
    "q_plan": "You have an exciting short trip next week. How do you prepare?",
    "q_attention": "Someone you care about hasn't replied to your message. What do you do?",
    "q_self": "Someone asks you 'what kind of person are you'. What do you usually do?",
}

_Q_OPTIONS_EN = {
    "q_energy": [
        "A. Go out with friends — being around people is how I recharge",
        "B. Stay home gaming/reading — I'm most comfortable alone",
        "C. Work on a creative project or learn something new — idle time feels wasteful",
        "D. Lie down and do nothing — I need to recharge",
    ],
    "q_info": [
        "A. Concrete examples and actionable details",
        "B. The underlying principles and frameworks",
        "C. Whether the information is practically useful",
        "D. The new ideas and possibilities it sparks",
    ],
    "q_decision": [
        "A. Rational analysis of pros and cons — choose the optimal solution",
        "B. Follow my gut feelings and intuition",
        "C. Consider the impact on people around me",
        "D. Put it aside and let time decide",
    ],
    "q_plan": [
        "A. Plan the itinerary and checklist in advance — I need to feel prepared",
        "B. Set a rough direction and figure out details on the go",
        "C. No preparation — just go with the flow",
        "D. Make a detailed list and follow it step by step",
    ],
    "q_attention": [
        "A. It's fine — they're probably busy and will get back to me",
        "B. A little disappointed — I keep checking for new messages",
        "C. Think 'fine, I won't reply either' — a bit petty",
        "D. Send a quick 'what are you up to?' — I can't help it",
    ],
    "q_self": [
        "A. Think about it seriously and tell them honestly",
        "B. Brush it off with a joke — don't want to go that deep",
        "C. Sum it up with a few tags — short and simple",
        "D. Ask back 'what do you think?' — turn the question around",
    ],
}


def _(key: str, lang: str) -> str:
    """获取翻译文本，fallback 到中文"""
    try:
        from engine.i18n import t as _t
        return _t(key, lang)
    except Exception:
        return key


def _apply_question_lang(q: dict, lang: str) -> dict:
    """将题目文字和选项替换为指定语言"""
    if lang in ("zh", "zh_tw"):
        return q
    qid = q["id"]
    en_text = _Q_LABEL_EN.get(qid)
    if en_text:
        q = dict(q)
        q["text"] = en_text
        en_opts = _Q_OPTIONS_EN.get(qid)
        if en_opts and len(en_opts) == len(q["options"]):
            new_opts = []
            for i, opt in enumerate(q["options"]):
                new_opt = dict(opt)
                new_opt["label"] = en_opts[i]
                new_opts.append(new_opt)
            q["options"] = new_opts
    return q


# ══════════════════════════════════════════════════════════════════
# 6 道核心人格题 · 每题 4 个选项 → 对应 24 维调整量
# 每次启动用 AI 润色题目文字，但选项映射固定，保证一致性
# ══════════════════════════════════════════════════════════════════

QUESTIONS = [
    # ── Q1: E/I — 精力来源 ──
    {
        "id": "q_energy",
        "trait": "精力恢复方式",
        "text": "周末终于到了，没有必须做的事——你会怎么过？",
        "options": [
            {
                "label": "A. 约朋友出去浪，有人气才叫休息",
                "dims": {"joy": 0.12, "life_vitality": 0.10, "dependence": 0.06, "loneliness": -0.08,
                         "favoritism": 0.06, "life_sense": 0.06, "soul_resonance": 0.04},
                "flaw_baseline": {"慵懒寡言": -0.06, "孤独": -0.04},
                "user_traits": {"intro_extro": 0.16, "active_passive": 0.08, "adventurous_stable": -0.06},
            },
            {
                "label": "B. 宅家打游戏/看书，一个人待着最自在",
                "dims": {"joy": 0.06, "restraint": 0.08, "loneliness": 0.02, "chaotic_mood": -0.06,
                         "autonomous_values": 0.06, "life_sense": 0.04, "body_perception": 0.04},
                "flaw_baseline": {"慵懒寡言": 0.04, "孤独": 0.06},
                "user_traits": {"intro_extro": -0.16, "active_passive": -0.06, "adventurous_stable": 0.08},
            },
            {
                "label": "C. 搞点小创作/学新东西，闲着反而难受",
                "dims": {"autonomous_values": 0.10, "life_vitality": 0.08, "soul_resonance": 0.06, "fatigue": -0.04,
                         "joy": 0.06, "healing_reflection": 0.04, "years_precipitation": 0.04},
                "flaw_baseline": {"自我怀疑": 0.04, "追求完美": 0.06},
                "user_traits": {"intro_extro": -0.06, "casual_perfectionist": 0.06, "open_conservative": -0.06},
            },
            {
                "label": "D. 躺平，什么都不想干，我需要充电",
                "dims": {"fatigue": 0.10, "emptiness": 0.04, "restraint": 0.04, "emotional_healing": 0.06,
                         "body_perception": 0.06, "life_sense": -0.04, "loneliness": 0.04},
                "flaw_baseline": {"慵懒寡言": 0.10, "间歇性冷淡": 0.08},
                "user_traits": {"intro_extro": -0.10, "optimistic_pessimistic": -0.08, "active_passive": -0.08},
            },
        ],
    },
    # ── Q2: S/N — 信息偏好 ──
    {
        "id": "q_info",
        "trait": "信息处理方式",
        "text": "看一篇你感兴趣的文章或视频时，你最关注的是什么？",
        "options": [
            {
                "label": "A. 具体的案例和可操作的细节",
                "dims": {"body_perception": 0.08, "life_sense": 0.06, "causal_fate": 0.04, "joy": 0.04,
                         "fatigue": -0.02, "restraint": 0.04, "emotional_volatility": -0.04},
                "flaw_baseline": {"追求完美": 0.04},
                "user_traits": {"open_conservative": 0.14, "delicate_rough": -0.10, "adventurous_stable": 0.08},
            },
            {
                "label": "B. 背后的原理和思维框架",
                "dims": {"autonomous_values": 0.08, "healing_reflection": 0.06, "soul_resonance": 0.06, "life_vitality": 0.04,
                         "years_precipitation": 0.04, "chaotic_mood": 0.02, "causal_fate": 0.04},
                "flaw_baseline": {"自我怀疑": 0.04},
                "user_traits": {"open_conservative": -0.12, "delicate_rough": -0.06, "adventurous_stable": -0.06},
            },
            {
                "label": "C. 能不能直接拿来用的实用信息",
                "dims": {"life_vitality": 0.06, "body_perception": 0.06, "life_sense": 0.06, "restraint": 0.04,
                         "joy": 0.04, "fatigue": -0.04, "chaotic_mood": -0.04},
                "flaw_baseline": {"追求完美": 0.02, "傲娇": 0.02},
                "user_traits": {"open_conservative": 0.10, "delicate_rough": -0.04, "romantic_pragmatic": 0.08},
            },
            {
                "label": "D. 它引发的新灵感和可能性",
                "dims": {"joy": 0.08, "soul_resonance": 0.08, "chaotic_mood": 0.06, "life_vitality": 0.06,
                         "autonomous_values": 0.04, "healing_reflection": 0.04, "emotional_volatility": 0.02},
                "flaw_baseline": {"追求完美": 0.02, "情绪反复": 0.02},
                "user_traits": {"open_conservative": -0.14, "adventurous_stable": -0.08, "delicate_rough": 0.06},
            },
        ],
    },
    # ── Q3: T/F — 决策方式 ──
    {
        "id": "q_decision",
        "trait": "决策风格",
        "text": "做一个重要决定时，什么对你影响最大？",
        "options": [
            {
                "label": "A. 理性分析利弊，选最优解",
                "dims": {"restraint": 0.08, "autonomous_values": 0.06, "emotional_volatility": -0.06, "body_perception": 0.04,
                         "healing_reflection": 0.04, "causal_fate": 0.06, "fatigue": -0.02},
                "flaw_baseline": {"嘴硬": 0.04, "傲娇": 0.04},
                "user_traits": {"rational_emotional": -0.16, "patient_impatient": -0.06},
            },
            {
                "label": "B. 听从内心的感受和直觉",
                "dims": {"joy": 0.08, "sensitivity_paranoia": 0.04, "emotional_volatility": 0.06, "chaotic_mood": 0.04,
                         "soul_resonance": 0.06, "life_sense": 0.04, "dependence": 0.04},
                "flaw_baseline": {"敏感": 0.06, "情绪反复": 0.04},
                "user_traits": {"rational_emotional": 0.16, "delicate_rough": -0.06},
            },
            {
                "label": "C. 考虑对身边人的影响",
                "dims": {"emotional_healing": 0.08, "soul_resonance": 0.08, "favoritism": 0.06, "dependence": 0.06,
                         "life_sense": 0.06, "relationship_fatigue": 0.04, "joy": 0.04},
                "flaw_baseline": {"敏感": 0.04, "依赖": 0.04},
                "user_traits": {"rational_emotional": 0.10, "independent_dependent": 0.08, "optimistic_pessimistic": 0.04},
            },
            {
                "label": "D. 先放一放，让时间给答案",
                "dims": {"restraint": 0.06, "chaotic_mood": 0.04, "emptiness": 0.04, "fatigue": 0.04,
                         "body_perception": 0.04, "life_sense": 0.04, "emotional_volatility": -0.04},
                "flaw_baseline": {"慵懒寡言": 0.04, "克制": 0.04},
                "user_traits": {"rational_emotional": -0.06, "patient_impatient": -0.10, "adventurous_stable": 0.06},
            },
        ],
    },
    # ── Q4: J/P — 生活方式 ──
    {
        "id": "q_plan",
        "trait": "生活节奏",
        "text": "下周有一个你期待已久的短途旅行，你怎么准备？",
        "options": [
            {
                "label": "A. 提前规划好行程和清单，心里才踏实",
                "dims": {"life_sense": 0.08, "restraint": 0.06, "body_perception": 0.04, "joy": 0.06,
                         "healing_reflection": 0.04, "autonomous_values": 0.04, "causal_fate": 0.04},
                "flaw_baseline": {"追求完美": 0.06},
                "user_traits": {"casual_perfectionist": 0.14, "active_passive": 0.10, "adventurous_stable": 0.06},
            },
            {
                "label": "B. 定个大概方向，细节到了再说",
                "dims": {"chaotic_mood": 0.06, "joy": 0.06, "life_vitality": 0.06, "autonomous_values": 0.04,
                         "soul_resonance": 0.04, "fatigue": -0.02, "emotional_volatility": 0.02},
                "flaw_baseline": {"慵懒寡言": 0.02},
                "user_traits": {"casual_perfectionist": -0.10, "active_passive": -0.06, "adventurous_stable": -0.04},
            },
            {
                "label": "C. 不准备，出发就完事了，随遇而安",
                "dims": {"chaotic_mood": 0.08, "joy": 0.08, "restraint": -0.06, "emptiness": 0.04,
                         "life_vitality": 0.04, "soul_resonance": 0.02, "emotional_volatility": 0.04},
                "flaw_baseline": {"慵懒寡言": 0.04},
                "user_traits": {"casual_perfectionist": -0.14, "active_passive": -0.10, "adventurous_stable": -0.08},
            },
            {
                "label": "D. 列个清单按步骤执行，有条不紊",
                "dims": {"life_sense": 0.10, "restraint": 0.08, "body_perception": 0.06, "healing_reflection": 0.04,
                         "causal_fate": 0.04, "autonomous_values": 0.04, "joy": 0.04},
                "flaw_baseline": {"追求完美": 0.08, "克制": 0.04},
                "user_traits": {"casual_perfectionist": 0.16, "active_passive": 0.12, "patient_impatient": 0.06},
            },
        ],
    },
    # ── Q5: 情感深度 — 原 q_attention（保留，但精简 dims） ──
    {
        "id": "q_attention",
        "trait": "关注需求",
        "text": "在意的人没有及时回你消息，你会？",
        "options": [
            {
                "label": "A. 没事，ta 可能在忙，忙完会找我的",
                "dims": {"dependence": -0.06, "jealousy": -0.06, "obsession": -0.04, "emotional_healing": 0.08,
                         "restraint": 0.06, "healing_reflection": 0.06, "life_sense": 0.04, "joy": 0.04},
                "flaw_baseline": {"敏感": -0.04, "自我怀疑": -0.06},
                "user_traits": {"independent_dependent": -0.08, "optimistic_pessimistic": 0.08, "patient_impatient": -0.06},
            },
            {
                "label": "B. 有点失落，反复看有没有新消息",
                "dims": {"dependence": 0.10, "loneliness": 0.08, "obsession": 0.06, "misery": 0.04,
                         "sensitivity_paranoia": 0.06, "fatigue": 0.04, "emptiness": 0.04},
                "flaw_baseline": {"敏感": 0.08, "多想": 0.08, "自我怀疑": 0.06},
                "user_traits": {"independent_dependent": 0.10, "patient_impatient": 0.08, "optimistic_pessimistic": -0.06},
            },
            {
                "label": "C. 心想'那我也不回'，有点赌气",
                "dims": {"jealousy": 0.12, "sensitivity_paranoia": 0.08, "obsession": 0.06, "restraint": -0.04,
                         "chaotic_mood": 0.06, "misery": 0.04, "emotional_volatility": 0.04},
                "flaw_baseline": {"别扭": 0.10, "小脾气": 0.08, "嘴硬": 0.06},
                "user_traits": {"patient_impatient": 0.08, "independent_dependent": 0.04, "optimistic_pessimistic": -0.08},
            },
            {
                "label": "D. 直接发一句'你在干嘛呢'，忍不住",
                "dims": {"dependence": 0.08, "bidirectional_shaping": 0.08, "soul_resonance": 0.06, "joy": 0.04,
                         "favoritism": 0.06, "life_vitality": 0.04, "causal_fate": 0.04},
                "flaw_baseline": {"傲娇": -0.04, "依赖": 0.06},
                "user_traits": {"active_passive": 0.10, "independent_dependent": 0.06, "intro_extro": 0.06},
            },
        ],
    },
    # ── Q6: 自我认知 — 原 q_self（保留，精简） ──
    {
        "id": "q_self",
        "trait": "自我认知",
        "text": "有人问你'你是个什么样的人'，你一般会？",
        "options": [
            {
                "label": "A. 认真想一下，然后如实告诉 ta",
                "dims": {"healing_reflection": 0.10, "soul_resonance": 0.08, "autonomous_values": 0.06, "years_precipitation": 0.04,
                         "joy": 0.06, "life_sense": 0.06, "causal_fate": 0.06, "bidirectional_shaping": 0.04},
                "flaw_baseline": {"自我怀疑": -0.04},
                "user_traits": {"open_conservative": -0.06, "rational_emotional": 0.06, "delicate_rough": -0.06},
            },
            {
                "label": "B. 打个哈哈混过去，不太想聊这么深",
                "dims": {"restraint": 0.08, "chaotic_mood": 0.06, "emotional_volatility": -0.04, "fatigue": 0.04,
                         "emptiness": 0.04, "life_sense": -0.04, "body_perception": 0.04},
                "flaw_baseline": {"慵懒寡言": 0.06, "嘴硬": 0.04},
                "user_traits": {"open_conservative": 0.08, "intro_extro": -0.06, "humorous_serious": -0.06},
            },
            {
                "label": "C. 用几个标签概括，简单干脆",
                "dims": {"restraint": 0.04, "joy": 0.04, "causal_fate": 0.04, "bidirectional_shaping": 0.04,
                         "life_sense": 0.04, "autonomous_values": 0.06, "body_perception": 0.02},
                "flaw_baseline": {"傲娇": 0.04},
                "user_traits": {"rational_emotional": -0.06, "romantic_pragmatic": 0.06, "casual_perfectionist": 0.04},
            },
            {
                "label": "D. 反问 ta '那你觉得呢'，把问题抛回去",
                "dims": {"sensitivity_paranoia": 0.06, "bidirectional_shaping": 0.08, "causal_fate": 0.04, "soul_resonance": 0.02,
                         "emotional_volatility": 0.04, "chaotic_mood": 0.04, "favoritism": 0.04},
                "flaw_baseline": {"嘴硬": 0.06, "别扭": 0.06, "敏感": 0.04},
                "user_traits": {"humorous_serious": -0.06, "active_passive": 0.06, "intro_extro": 0.06},
            },
        ],
    },
]


def _shuffle_questions() -> list:
    qs = list(QUESTIONS)
    random.shuffle(qs)
    return qs


def _ai_embellish(q: dict) -> dict:
    """用 AI 润色题目文字和选项，让每次启动都有新鲜感"""
    try:
        from core import ai as ai_module
        from core import config as cfg
        cfg.load(CONFIG_PATH)
        ai_module.load_config(CONFIG_PATH)
        if not ai_module.init_client():
            return q

        original_q = q["text"]
        original_opts = [o["label"] for o in q["options"]]
        opts_str = "\n".join(f"{i+1}. {t}" for i, t in enumerate(original_opts))

        prompt = (
            f"你是一个有趣的人格测试题设计师。请把下面这道题改写得更生动、更有意境，"
            f"保留核心意思但换个表达方式。也要改写 4 个选项的表达方式，保持选项意思不变。\n\n"
            f"原题: {original_q}\n"
            f"原选项:\n{opts_str}\n\n"
            f"直接输出格式:\n"
            f"题目: [改写后的题目]\n"
            f"A. [改写后的选项A]\n"
            f"B. [改写后的选项B]\n"
            f"C. [改写后的选项C]\n"
            f"D. [改写后的选项D]"
        )

        result = ai_module.chat(
            system_prompt="你擅长写有趣的心理学题目，文字灵动不刻板。",
            user_message=prompt,
            temperature=0.8,
        )

        lines = [l.strip() for l in result.split("\n") if l.strip()]
        new_text = ""
        new_opts = []
        for line in lines:
            if line.startswith("题目:"):
                new_text = line[3:].strip()
            elif line.startswith(("A.", "A．")):
                new_opts.append(line)
            elif line.startswith(("B.", "B．")):
                new_opts.append(line)
            elif line.startswith(("C.", "C．")):
                new_opts.append(line)
            elif line.startswith(("D.", "D．")):
                new_opts.append(line)

        if new_text and len(new_opts) == 4:
            q["text"] = new_text
            for i, opt in enumerate(q["options"]):
                opt["label"] = new_opts[i]
    except Exception:
        pass
    return q


def _ask_question(q: dict, idx: int, total: int, lang: str) -> int:
    """展示一道题（多语言），返回用户选择的选项索引 (0-3)"""
    t = lambda key: _(key, lang)  # noqa: E731
    prefix = t("onboarding.q_prefix")
    suffix = t("onboarding.q_suffix")
    print(f"\n{'─' * 50}")
    print(f"  {prefix}{idx}/{total}{suffix} · {q.get('trait', '')}")
    print(f"  {q['text']}")
    print()
    for opt in q["options"]:
        print(f"    {opt['label']}")
    print()

    while True:
        try:
            inp = input(f"  {t('onboarding.choice_prompt')} [{t('onboarding.choice_hint')}]: ").strip().upper()
            if inp in ("A", "B", "C", "D"):
                return ord(inp) - ord("A")
            print(f"  {t('onboarding.choice_invalid')}")
        except (EOFError, KeyboardInterrupt):
            print(f"\n\n  {t('onboarding.exit')}")
            sys.exit(1)


def _calc_personality(answers: list[dict]) -> dict:
    """根据所有答案加权计算最终的 24 维初始值"""
    base = {
        "initial_joy": 0.50,
        "initial_misery": 0.15,
        "initial_dependence": 0.20,
        "initial_jealousy": 0.12,
        "initial_fatigue": 0.15,
        "initial_loneliness": 0.20,
        "initial_favoritism": 0.15,
        "initial_sensitivity_paranoia": 0.20,
        "initial_emotional_healing": 0.50,
        "initial_obsession": 0.12,
        "initial_emptiness": 0.15,
        "initial_chaotic_mood": 0.15,
        "initial_life_sense": 0.50,
        "initial_restraint": 0.40,
        "initial_emotional_volatility": 0.20,
        "initial_years_precipitation": 0.05,
        "initial_relationship_fatigue": 0.08,
        "initial_healing_reflection": 0.40,
        "initial_body_perception": 0.45,
        "initial_autonomous_values": 0.45,
        "initial_life_vitality": 0.55,
        "initial_bidirectional_shaping": 0.08,
        "initial_causal_fate": 0.08,
        "initial_soul_resonance": 0.08,
    }

    dim_map = {
        "joy": "initial_joy",
        "misery": "initial_misery",
        "dependence": "initial_dependence",
        "jealousy": "initial_jealousy",
        "fatigue": "initial_fatigue",
        "loneliness": "initial_loneliness",
        "favoritism": "initial_favoritism",
        "sensitivity_paranoia": "initial_sensitivity_paranoia",
        "emotional_healing": "initial_emotional_healing",
        "obsession": "initial_obsession",
        "emptiness": "initial_emptiness",
        "chaotic_mood": "initial_chaotic_mood",
        "life_sense": "initial_life_sense",
        "restraint": "initial_restraint",
        "emotional_volatility": "initial_emotional_volatility",
        "years_precipitation": "initial_years_precipitation",
        "relationship_fatigue": "initial_relationship_fatigue",
        "healing_reflection": "initial_healing_reflection",
        "body_perception": "initial_body_perception",
        "autonomous_values": "initial_autonomous_values",
        "life_vitality": "initial_life_vitality",
        "bidirectional_shaping": "initial_bidirectional_shaping",
        "causal_fate": "initial_causal_fate",
        "soul_resonance": "initial_soul_resonance",
    }

    for ans in answers:
        chosen = ans["chosen"]
        for dim, delta in chosen["dims"].items():
            key = dim_map.get(dim)
            if key:
                base[key] += delta

    for k in base:
        base[k] = round(max(0.01, min(1.0, base[k])), 2)

    # ── 计算初始瑕疵基线 ──
    flaw_baseline = {}
    for ans in answers:
        chosen = ans["chosen"]
        fb = chosen.get("flaw_baseline", {})
        for flaw_name, delta in fb.items():
            flaw_baseline[flaw_name] = flaw_baseline.get(flaw_name, 0) + delta
    # 钳制边界
    for k in flaw_baseline:
        flaw_baseline[k] = round(max(-0.15, min(0.15, flaw_baseline[k])), 4)

    base["_flaw_baselines"] = flaw_baseline
    return base


# ── 用户 MBTI 计算（从 6 题答案推断） ──

_USER_TRAIT_BASELINE = {
    "intro_extro": 0.5,
    "rational_emotional": 0.5,
    "independent_dependent": 0.5,
    "open_conservative": 0.5,
    "optimistic_pessimistic": 0.5,
    "patient_impatient": 0.5,
    "delicate_rough": 0.5,
    "active_passive": 0.5,
    "humorous_serious": 0.5,
    "romantic_pragmatic": 0.5,
    "adventurous_stable": 0.5,
    "casual_perfectionist": 0.5,
}


def _calc_user_mbti(answers: list[dict]) -> str:
    """从回答中累计用户 12 维性格分值，映射为 MBTI 类型"""
    traits = dict(_USER_TRAIT_BASELINE)
    for ans in answers:
        chosen = ans["chosen"]
        ut = chosen.get("user_traits", {})
        for dim, delta in ut.items():
            if dim in traits:
                traits[dim] += delta
    for k in traits:
        traits[k] = round(max(0.01, min(0.99, traits[k])), 2)

    # MBTI 四维映射（与 user_persona.py compute_mbti 保持同步）
    def _letter(val, if_high, if_low):
        return if_high if val > 0.5 else if_low

    ei = _letter(traits["intro_extro"], "E", "I")
    sn_raw = (
        (1 - traits["open_conservative"]) * 0.40 +
        (1 - traits["adventurous_stable"]) * 0.35 +
        traits["delicate_rough"] * 0.25
    )
    sn = _letter(sn_raw, "N", "S")
    tf = _letter(traits["rational_emotional"], "F", "T")
    jp_raw = (
        traits["casual_perfectionist"] * 0.6 +
        (1 - traits["active_passive"]) * 0.4
    )
    jp = _letter(jp_raw, "J", "P")
    return ei + sn + tf + jp


def _mbti_profile_text(mbti_type: str) -> str:
    """返回 MBTI 类型的简短性格描述"""
    profiles = {
        "ISTJ": "务实可靠，有条不紊",
        "ISFJ": "温暖体贴，默默付出",
        "INFJ": "洞察力强，有深度使命感",
        "INTJ": "独立思考，战略眼光",
        "ISTP": "冷静务实，动手能力强",
        "ISFP": "温柔敏感，活在当下",
        "INFP": "理想主义者，重视内在价值和深层关系",
        "INTP": "理性好奇，喜欢思考抽象概念",
        "ESTP": "精力充沛，善于交际",
        "ESFP": "热情开朗，享受当下",
        "ENFP": "充满热情，富有创造力",
        "ENTP": "思维活跃，喜欢辩论",
        "ESTJ": "果断务实，天生的管理者",
        "ESFJ": "热情友善，乐于助人",
        "ENFJ": "富有魅力，天生的领导者",
        "ENTJ": "目标明确，果断自信",
    }
    return profiles.get(mbti_type, "")


def _generate_summary(personality: dict) -> str:
    """根据人格数值生成一段描述"""
    parts = []
    if personality["initial_joy"] > 0.65:
        parts.append("阳光开朗")
    elif personality["initial_joy"] < 0.35:
        parts.append("偏沉静")
    if personality["initial_dependence"] > 0.55:
        parts.append("粘人")
    elif personality["initial_dependence"] < 0.25:
        parts.append("独立")
    if personality["initial_sensitivity_paranoia"] > 0.55:
        parts.append("敏感细腻")
    elif personality["initial_sensitivity_paranoia"] < 0.25:
        parts.append("心大豁达")
    if personality["initial_restraint"] > 0.55:
        parts.append("内敛克制")
    elif personality["initial_restraint"] < 0.30:
        parts.append("直率外放")
    if personality["initial_life_vitality"] > 0.65:
        parts.append("充满活力")
    elif personality["initial_life_vitality"] < 0.35:
        parts.append("佛系淡然")
    if personality["initial_emotional_healing"] > 0.60:
        parts.append("温暖治愈")
    if personality["initial_chaotic_mood"] > 0.40:
        parts.append("古灵精怪")
    if personality["initial_jealousy"] > 0.35:
        parts.append("占有欲强")
    if personality["initial_emptiness"] > 0.40:
        parts.append("偶尔emo")
    if personality["initial_soul_resonance"] > 0.40:
        parts.append("重缘惜情")
    return "、".join(parts) if parts else "普通人"


def _show_pledge(lang: str) -> bool:
    """展示使用誓约（多语言），用户同意后才能继续"""
    t = lambda key: _(key, lang)  # noqa: E731
    print()
    print("  ╔══════════════════════════════════════════════════╗")
    print("  ║                                              ║")
    print(f"  ║     {t('onboarding.pledge_title'):<42}  ║")
    print("  ║                                              ║")
    print("  ╠══════════════════════════════════════════════════╣")
    print("  ║                                              ║")
    print(f"  ║  {t('onboarding.pledge_line1'):<47}  ║")
    print(f"  ║  {t('onboarding.pledge_line2'):<47}  ║")
    print("  ║                                              ║")
    print(f"  ║  {t('onboarding.pledge_line3'):<47}  ║")
    print(f"  ║  {t('onboarding.pledge_line4'):<47}  ║")
    print(f"  ║  {t('onboarding.pledge_line5'):<47}  ║")
    print(f"  ║  {t('onboarding.pledge_line6'):<47}  ║")
    print(f"  ║  {t('onboarding.pledge_line7'):<47}  ║")
    print("  ║                                              ║")
    print(f"  ║  {t('onboarding.pledge_line8'):<47}  ║")
    print(f"  ║  {t('onboarding.pledge_line9'):<47}  ║")
    print(f"  ║  {t('onboarding.pledge_line10'):<47}  ║")
    print("  ║                                              ║")
    print(f"  ║  {t('onboarding.pledge_ask'):<47}  ║")
    print("  ║                                              ║")
    print("  ╚══════════════════════════════════════════════════╝")
    print()
    confirm_text = t("onboarding.pledge_confirm")
    print(f"  输入「{confirm_text}」确认，输入其他则退出")
    print()
    try:
        inp = input(f"  {t('onboarding.pledge_placeholder')}: ").strip()
        if inp == confirm_text:
            print()
            print(f"  🌸 {t('onboarding.pledge_accepted')}")
            return True
        print()
        print(f"  {t('onboarding.pledge_cancel')}")
        return False
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def run():
    """入口：运行人格探索问答（多语言）"""
    cfg = _load_config()

    if _check_done(cfg):
        return

    # 没有终端就不要问。这份问卷通篇是 input()，而 main.py 是在**模块级**对所有
    # 模式调它的 —— 于是全新数据目录下 `main.py web` / `serve` / 渠道模式都会先
    # 弹一道终端问卷，而不是直接起服务；容器、CI、nohup 这类没有 TTY 的环境更是
    # 直接卡死（stdin 立刻 EOF 的旧行为见 _select_language 的注释）。
    # 这里选择「跳过」而不是「退出」：引擎照常用默认人格正常跑起来，用户下次在
    # 终端里启动时再问。代价是 `printf "1\n..." | main.py cli` 这种脚本化答题
    # 不再生效 —— 那个用法本来也很边缘，不值得拿整个无终端场景去换。
    try:
        if not sys.stdin.isatty():
            return
    except Exception:
        return

    # ── 第 0 步：语言选择 ──
    lang = _select_language()

    # ── 誓约确认（用所选语言） ──
    if not _show_pledge(lang):
        sys.exit(0)

    t = lambda key: _(key, lang)  # noqa: E731
    print()
    print("  ╔══════════════════════════════════════╗")
    print(f"  ║  {t('onboarding.intro_title'):<32}  ║")
    print(f"  ║  {t('onboarding.intro_desc'):<30}   ║")
    print(f"  ║  {t('onboarding.intro_note'):<30}   ║")
    print("  ╚══════════════════════════════════════╝")
    print()

    if "personality" not in cfg:
        cfg["personality"] = {}

    qs = _shuffle_questions()
    answers = []

    for i, q in enumerate(qs, 1):
        # 多语言 + AI 润色
        q_lang = _apply_question_lang(q, lang)
        q_embellished = _ai_embellish(q_lang)
        choice = _ask_question(q_embellished, i, len(qs), lang)
        chosen = q_embellished["options"][choice]
        answers.append({"question": q_embellished["text"], "chosen": chosen})
        # 反馈（用 emoji 跨语言通用）
        feedbacks = [
            "📝", "✨", "😊", "🎯", "🌟", "🍃",
        ]
        print(f"  {feedbacks[i % len(feedbacks)]}")

    personality = _calc_personality(answers)
    summary = _generate_summary(personality)

    # ── 计算用户 MBTI ──
    user_mbti = _calc_user_mbti(answers)
    mbti_desc = _mbti_profile_text(user_mbti)

    cfg["personality"].update(personality)
    cfg["user_mbti_type"] = user_mbti
    cfg["lang"] = lang
    cfg["_onboarding_done"] = True
    _save_config(cfg)

    t2 = lambda key: _(key, lang)  # noqa: E731
    print()
    print("  ╔══════════════════════════════════════╗")
    print(f"  ║  {t2('onboarding.result_title'):<32}  ║")
    print(f"  ║  {summary:<32}  ║")
    print("  ╚══════════════════════════════════════╝")
    print()
    lbl_mbti = t2("onboarding.result_mbti")
    print(f"  【{lbl_mbti}】{user_mbti} — {mbti_desc}")
    print(f"  {t2('onboarding.result_hint')}")
    print()


if __name__ == "__main__":
    run()
