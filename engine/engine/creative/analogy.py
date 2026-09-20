# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""跨域类比推理引擎 — Analogy Engine
==========================================
A:B :: C:? — 从已知关系中推断未知。

核心能力:
  1. compose_metaphor — 隐喻创作（"孤独像深秋的雨"）
  2. analogical_reasoning — A:B :: C:? 类比推理
  3. cross_domain_insight — 跨域概念映射
  4. try_analogy — 心境驱动的自动类比触发
"""
import random
import time
from typing import Dict, List, Optional, Tuple

try:
    from core import ai as ai_module
except ImportError:
    ai_module = None

_analogy_log: Dict[str, List[Dict]] = {}
_ANALOGY_FILE = "data/json/analogy_log.json"


# ── 持久化 ──

def _get_store():
    from core.json_store import get_store
    return get_store(_ANALOGY_FILE, {})


def _save():
    try:
        store = _get_store()
        store.write(_analogy_log)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
# 核心 API
# ══════════════════════════════════════════════════════════════════════

def compose_metaphor(source_concept: str, target_domain: str,
                     mind_data: Optional[dict] = None) -> Optional[str]:
    """隐喻创作：将 source_concept 映射到 target_domain 的一个形象上

    compose_metaphor("孤独", "自然") → "孤独像深秋的雨，无声却湿透了一切"
    compose_metaphor("思念", "物理") → "思念像重力，看不见却无时不在"
    """
    if not ai_module:
        return None

    tone = ""
    if mind_data:
        joy = mind_data.get("joy", 0.5)
        misery = mind_data.get("misery", 0.15)
        if joy > 0.6:
            tone = "温暖明亮的"
        elif misery > 0.4:
            tone = "略带忧郁的"
        else:
            tone = "平静的"

    prompt = (
        f"请创建一个{tone}隐喻：把「{source_concept}」比作「{target_domain}」中的某个事物。"
        f"格式：'[源概念]像[目标域中的形象]，[简短的为什么]'。"
        f"例如：'孤独像深秋的雨，无声却湿透了一切'。20字以内。只返回隐喻本身。"
    )
    text = ai_module.background_chat(prompt, temperature=0.9, max_tokens=60)
    if text and len(text.strip()) > 4:
        return text.strip()[:100]
    return None


def analogical_reasoning(A: str, B: str, C: str) -> Optional[str]:
    """类比推理：A:B :: C:?

    找出 AB 之间的关系，然后找到与 C 有相同关系的 D。

    analogical_reasoning("太阳", "光", "井") → "水"
    analogical_reasoning("种子", "树", "想法") → "行动"
    """
    if not ai_module:
        return None

    prompt = (
        f"分析「{A}」和「{B}」之间是什么关系。"
        f"然后用同样的关系，找到与「{C}」对应的那个事物。"
        f"格式：只返回答案，一个字或多个字都可以，不要解释。"
        f"例如: {A}:{B} :: {C}:?"
    )
    text = ai_module.background_chat(prompt, temperature=0.85, max_tokens=20)
    if text:
        return text.strip()[:30]
    return None


def cross_domain_insight(source_domain: str, target_domain: str,
                         concept: str) -> Optional[str]:
    """跨域洞察：把一个领域的概念映射到另一个领域

    cross_domain_insight("记忆", "河流", "遗忘")
      → "遗忘像河流的弯道，看似偏离却让水流得更远"
    """
    if not ai_module:
        return None

    prompt = (
        f"在「{source_domain}」中有一个概念叫「{concept}」。"
        f"请从「{target_domain}」中找到与之呼应的现象，生成一段富有哲理的跨域洞察。"
        f"格式：一句话，20字左右。"
    )
    text = ai_module.background_chat(prompt, temperature=0.9, max_tokens=60)
    if text and len(text.strip()) > 4:
        return text.strip()[:100]
    return None


# ══════════════════════════════════════════════════════════════════════
# 自动触发
# ══════════════════════════════════════════════════════════════════════

def _detect_analogy_opportunity(mind_data: dict) -> Optional[Tuple[str, str]]:
    """根据当前心境检测最适合的类比主题"""
    joy = mind_data.get("joy", 0.5)
    misery = mind_data.get("misery", 0.15)
    loneliness = mind_data.get("loneliness", 0.4)
    obsession = mind_data.get("obsession", 0.2)
    chaos = mind_data.get("chaotic_mood", 0.2)

    emotional_amplitude = abs(joy - 0.5) * 2 + misery + loneliness * 0.5
    if emotional_amplitude < 0.4:
        return None

    pool = []
    if joy > 0.55:
        pool.append(("快乐", "天气"))
    if misery > 0.3:
        pool.append(("委屈", "自然"))
    if loneliness > 0.4:
        pool.append(("孤独", "季节"))
    if obsession > 0.3:
        pool.append(("思念", "物理"))
    if chaos > 0.35:
        pool.append(("迷茫", "旅行"))
    if not pool:
        pool.append(("平静", "日常"))

    return random.choice(pool)


def try_analogy(user_id: str, mind_data: dict, force: bool = False) -> Optional[str]:
    """主入口：尝试生成一个类比/隐喻

    由 creative_spark.try_spark() 或 life._autonomous_thinking_tick() 调用。
    随机选择隐喻/类比推理/跨域洞察三种方式之一。
    """
    opp = _detect_analogy_opportunity(mind_data)
    if not opp and not force:
        return None

    concept, domain = opp or ("心境", "自然")

    mode = random.choices(
        ["metaphor", "analogy", "cross_domain"],
        weights=[0.5, 0.3, 0.2],
        k=1
    )[0]

    if mode == "metaphor":
        result = compose_metaphor(concept, domain, mind_data)
    elif mode == "analogy":
        targets = {"孤独": "落叶", "思念": "潮汐", "快乐": "阳光",
                   "委屈": "阴雨", "迷茫": "雾", "平静": "湖面"}
        B = targets.get(concept, "风")
        result = analogical_reasoning(concept, B, "此刻的我")
    else:
        result = cross_domain_insight("情绪", domain, concept)

    if not result:
        return None

    entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": mode,
        "concept": concept,
        "domain": domain,
        "result": result,
    }
    if user_id not in _analogy_log:
        _analogy_log[user_id] = []
    _analogy_log[user_id].append(entry)
    if len(_analogy_log[user_id]) > 50:
        _analogy_log[user_id] = _analogy_log[user_id][-50:]
    _save()

    return result


def get_analogy_history(user_id: str, max_items: int = 5) -> List[str]:
    """获取最近的类比历史"""
    if user_id not in _analogy_log:
        return []
    return [e["result"] for e in _analogy_log[user_id][-max_items:]]
