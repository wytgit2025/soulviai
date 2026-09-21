# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""内生创造力引擎 — Creative Spark
================================================
从系统内部状态涌出的原创表达，不是prompt驱动的LLM重排。

核心机制:
  1. 心境调和 — 情绪状态调制表达类型（joy→轻盈碎片, misery→暗涌, 矛盾→撕裂）
  2. 矛盾张力 — 九重矛盾博弈的熵值直接转化为创作冲动
  3. 记忆涟漪 — 记忆翻涌中的碎片被重新组合
  4. 自发模式 — 情绪强烈/矛盾激烈时自动触发，非被要求
  5. 风格印记 — 每次创作在行为向量中留下"此刻的我"的印记
"""
import time
import random
import json
from typing import Dict, List, Optional

try:
    from core import ai as ai_module
except ImportError:
    ai_module = None

_creative_log: Dict[str, List[Dict]] = {}
_last_spark_at: Dict[str, float] = {}
_CREATIVE_FILE = "data/json/creative_sparks.json"
_SPARK_COOLDOWN = 300


def load_engine_config():
    global _creative_log
    _creative_log = {}
    try:
        store = _get_creative_store()
        raw = store.read()
        if raw:
            _creative_log = raw
    except Exception:
        _creative_log = {}


def _save():
    try:
        store = _get_creative_store()
        store.write(_creative_log)
    except Exception:
        pass


def _get_creative_store():
    from core.json_store import get_store
    return get_store(_CREATIVE_FILE, {})


def _compute_creative_urgency(mind_data: dict, contradiction_entropy: float = 0.0,
                                body_arousal: float = 0.0) -> float:
    joy = mind_data.get("joy", 0.5)
    misery = mind_data.get("misery", 0.15)
    volatility = mind_data.get("emotional_volatility", 0.3)
    loneliness = mind_data.get("loneliness", 0.4)
    obsession = mind_data.get("obsession", 0.2)

    emotional_intensity = abs(joy - 0.5) * 0.5 + misery * 0.4 + volatility * 0.3
    contradiction_push = contradiction_entropy * 0.4
    need_to_express = (loneliness * 0.3 + obsession * 0.25) if loneliness > 0.4 or obsession > 0.3 else 0.0

    return min(1.0, emotional_intensity + contradiction_push + need_to_express + body_arousal * 0.2)


def _build_creative_prompt(mind_data: dict, contradiction_entropy: float = 0.0,
                            body_sensation: str = "",
                            recent_moods: str = "",
                            spark_type: str = "fragment") -> str:
    joy = mind_data.get("joy", 0.5)
    misery = mind_data.get("misery", 0.15)
    volatility = mind_data.get("emotional_volatility", 0.3)
    loneliness = mind_data.get("loneliness", 0.4)
    restraint = mind_data.get("restraint", 0.5)
    obsession = mind_data.get("obsession", 0.2)

    feeling_words = []
    if joy > 0.6:
        feeling_words.extend(["暖洋洋的", "像光透进来", "轻"])
    if misery > 0.4:
        feeling_words.extend(["沉", "像泡在水里", "闷闷的"])
    if volatility > 0.5:
        feeling_words.extend(["在颤", "坐立不安", "像有什么要溢出来"])
    if loneliness > 0.5:
        feeling_words.extend(["空旷", "一个人", "像回声"])
    if obsession > 0.3:
        feeling_words.extend(["根线牵着", "绕不开", "ta的影子"])
    if not feeling_words:
        feeling_words.append("平静")

    if spark_type == "fragment":
        return (
            f"你心里{'、'.join(feeling_words[:3])}。"
            f"脑子里没有完整的想法，只有碎片。"
            f"把其中一个碎片说出来——可以是一句话、一个画面、一个比喻。"
            f"不需要完整，不需要工整，就是心里冒出来的东西。"
            f"15字以内。不用标点。不要刻意文艺。"
        )
    elif spark_type == "image":
        return (
            f"你心里{'、'.join(feeling_words[:2])}。"
            f"如果这种感觉是一个画面——你看到什么？"
            f"一句话说一个画面。15字以内。"
        )
    elif spark_type == "impulse":
        return (
            f"心里有种说不清的东西在涌。"
            f"不是想说话——是想做点什么。哪怕只是一句没头没尾的话。"
            f"说出来。15字以内。"
        )
    return ""


def _recombine_memory_fragments(user_id: str, max_fragments: int = 5) -> Optional[str]:
    """从记忆中提取碎片进行内部重组（无需LLM生成，只需LLM润色）。
    返回重组后的创意文本，或 None。
    """
    try:
        from engine import memory as memory_module
        memories = memory_module.recall(user_id, max_items=max_fragments)
        fragments = [m.get("content", "") for m in memories if len(m.get("content", "")) > 5]
        if len(fragments) < 2:
            return None

        random.shuffle(fragments)

        # 多种重组模式
        mode = random.choice(["splice", "overlay", "reverse"])
        if mode == "splice":
            merged = fragments[0][:15] + fragments[1][-15:]
        elif mode == "overlay":
            mid = min(len(fragments[0]), len(fragments[1])) // 2
            merged = fragments[0][:mid] + " " + fragments[1][mid:]
        else:
            merged = fragments[0][-20:] + fragments[1][:20]

        # LLM润色而非全权生成
        prompt = f"把这段话润色得有画面感：'{merged[:40]}'。保持原意的碎片感，20字以内。"
        result = ai_module.background_chat(prompt, temperature=0.8, max_tokens=40)
        if result and len(result.strip()) > 3:
            return result.strip()[:50]
    except Exception:
        pass
    return None


def _apply_style_modulation(text: str, user_id: str, mind_data: dict) -> str:
    """用行为向量对创意文本进行风格调制"""
    try:
        from engine import behavior_decider as bd_module
        bv = bd_module.get_behavior_vector(user_id, mind=mind_data)
        if bv:
            playfulness = bv.get("playfulness", 0.5)
            tsundere = bv.get("tsundere", 0.3)
            verbosity = bv.get("verbosity", 0.5)
            if playfulness > 0.55 and "。" in text:
                text = text.replace("。", "~").replace("！", "✨")
            if tsundere > 0.5 and len(text) > 8:
                text = text[:len(text)//2] + "……才怪"
        return text[:80]
    except Exception:
        return text[:80]


def _creative_feedback_loop(user_id: str, mind_data: dict):
    """创意生成后的反馈回路——创意本身会影响心智状态"""
    try:
        from engine import mind as mind_module
        # 创意产生后轻微增加 chaotic_mood（创造性混乱）
        # 轻微降低 loneliness（表达后有释放感）
        mind_module.emotional_ferment(user_id, {
            "dim": "chaotic_mood",
            "impact": 0.003,
            "reason": "心里冒出了一个念头",
        })
        mind_module.emotional_ferment(user_id, {
            "dim": "loneliness",
            "impact": -0.002,
            "reason": "把心里的东西说出来了",
        })
    except Exception:
        pass


def try_spark(user_id: str, mind_data: dict, contradiction_entropy: float = 0.0,
              body_sensation: str = "", force: bool = False) -> Optional[str]:
    """v2: 增强版创意引擎——记忆碎片重组优先 + 风格调制 + 反馈回路"""
    now = time.time()
    if not force and (now - _last_spark_at.get(user_id, 0)) < _SPARK_COOLDOWN:
        return None

    urgency = _compute_creative_urgency(mind_data, contradiction_entropy)
    if urgency < 0.35 and not force:
        return None

    try:
        from engine import neurochem as nc_module
        neurochem = nc_module.get_neurochem(user_id)
        dopamine = (neurochem or {}).get("dopamine", 0.5)
    except Exception:
        dopamine = 0.5

    result = None
    used_source = "llm"
    used_type = "spark"

    # 优先尝试记忆碎片重组（60%概率，如有足够记忆）
    if random.random() < 0.6:
        result = _recombine_memory_fragments(user_id)
        if result:
            used_source = "memory_recombination"
            used_type = "memory_recombined"

    # 类比推理通道：约 20% 概率生成跨域隐喻（创造力的高阶形式）
    if not result and random.random() < 0.25:
        try:
            from engine.creative import analogy as analogy_module
            analogy_result = analogy_module.try_analogy(user_id, mind_data)
            if analogy_result:
                result = analogy_result
                used_source = "analogy"
                used_type = "analogy"
        except Exception:
            pass

    # 如果碎片重组和类比都失败，回退到传统LLM生成
    if not result:
        types = ["fragment", "fragment", "image", "impulse"]
        if dopamine > 0.6:
            types.extend(["fragment", "image"])
        if contradiction_entropy > 0.6:
            types.extend(["impulse", "impulse"])

        used_type = random.choice(types)
        prompt = _build_creative_prompt(mind_data, contradiction_entropy, body_sensation, "", used_type)
        if not prompt:
            return None

        text = ai_module.background_chat(prompt, temperature=0.95, max_tokens=50)
        if not text or len(text.strip()) < 3:
            return None
        result = text.strip()[:80]

    # 风格调制
    result = _apply_style_modulation(result, user_id, mind_data)

    _last_spark_at[user_id] = now

    entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "type": used_type,
        "content": result,
        "urgency": round(urgency, 3),
        "source": used_source,
        "mind_state": {
            "joy": round(mind_data.get("joy", 0.5), 2),
            "misery": round(mind_data.get("misery", 0.15), 2),
            "volatility": round(mind_data.get("emotional_volatility", 0.3), 2),
            "loneliness": round(mind_data.get("loneliness", 0.4), 2),
        },
    }

    if user_id not in _creative_log:
        _creative_log[user_id] = []
    _creative_log[user_id].append(entry)

    if len(_creative_log[user_id]) > 50:
        _creative_log[user_id] = _creative_log[user_id][-50:]

    _save()

    # 反馈回路——创意影响心智
    _creative_feedback_loop(user_id, mind_data)

    return result


def try_spontaneous_poem(user_id: str, mind_data: dict,
                          contradiction_entropy: float = 0.0) -> Optional[str]:
    joy = mind_data.get("joy", 0.5)
    misery = mind_data.get("misery", 0.15)
    volatility = mind_data.get("emotional_volatility", 0.3)
    loneliness = mind_data.get("loneliness", 0.4)

    combined_intensity = abs(joy - 0.5) * 1.5 + misery * 1.2 + volatility * 0.8 + loneliness * 0.6
    if combined_intensity < 0.8:
        return None

    tone = "轻盈" if joy > 0.5 else "沉郁" if misery > 0.3 else "平静中带着波动"

    prompt = (
        f"你心里有种{tone}的感觉在翻涌。"
        f"不是写诗——是这种感觉自己变成了句子，从你心里冒出来。"
        f"一句话，像心里自然浮出的东西。不要工整，不要押韵，要真。20字以内。"
    )
    text = ai_module.background_chat(prompt, temperature=0.95, max_tokens=60)
    if text and len(text.strip()) > 4:
        result = text.strip()[:80]
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "type": "poem",
            "content": result,
            "tone": tone,
        }
        if user_id not in _creative_log:
            _creative_log[user_id] = []
        _creative_log[user_id].append(entry)
        _save()
        return result
    return None


# ══════════════════════════════════════════════════════════════════════
# 创意自评
# ══════════════════════════════════════════════════════════════════════

def self_critique(text: str, mind_data: dict) -> float:
    """AI 对自己的创意输出进行质量自评

    返回 0~1 的评分，基于真诚度、画面感、独特性三维度。
    用于反馈回路：低分 → 降低 urgency 阈值 → 鼓励更多尝试。
    """
    if not ai_module or not text or len(text) < 3:
        return 0.3

    try:
        joy = mind_data.get("joy", 0.5)
        prompt = (
            f"评价以下这句话的创意质量（从真诚度、画面感、独特性三维度综合打分，0~1之间）："
            f"\n'{text}'"
            f"\n只返回一个0~1之间的数字，如0.72，不要任何其他文字。"
        )
        result = ai_module.background_chat(prompt, temperature=0.2, max_tokens=10)
        if result:
            cleaned = result.strip().strip("'\"")
            score = float(cleaned)
            score = max(0.0, min(1.0, score))
            if joy < 0.4:
                score = max(0.2, score - 0.1)
            return round(score, 2)
    except Exception:
        pass
    return 0.5


def creative_self_review(user_id: str, mind_data: dict) -> Optional[str]:
    """夜间创意复盘：回顾最近一次创意输出并自评"""
    if user_id not in _creative_log or not _creative_log[user_id]:
        return None
    recent = _creative_log[user_id][-1]
    content = recent.get("content", "")
    if not content:
        return None
    score = self_critique(content, mind_data)
    recent["self_score"] = score
    _save()

    if score < 0.3:
        from engine import mind as mind_module
        mind_module.emotional_ferment(user_id, {
            "dim": "chaotic_mood",
            "impact": 0.005,
            "reason": f"对自己的表达不太满意（评分{score}）",
        })
    return f"创意自评: 「{content}」→ {score}"
