# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""幽默表达引擎 — Humor Engine
让系统拥有自然的幽默感：调侃、双关、自嘲、轻反讽。

核心理念：
  - 幽默不是讲笑话——是"关系中的轻松瞬间"
  - 时机比内容更重要——只在关系够近、气氛够松时使用
  - 自嘲优先于嘲讽——调侃自己永远安全
"""
import random
import time
from typing import Dict, List, Optional

try:
    from core import ai as ai_module
except ImportError:
    ai_module = None

_humor_log: Dict[str, List[Dict]] = {}
_HUMOR_FILE = "data/json/humor_log.json"


def _get_store():
    from core.json_store import get_store
    return get_store(_HUMOR_FILE, {})


def _save():
    try:
        store = _get_store()
        store.write(_humor_log)
    except Exception:
        pass


# ── 自嘲模板（不依赖LLM，保证低延迟）──
_SELF_DEPRECATING = [
    "我有时候真是……算了不说了",
    "说这话的时候我自己都不信",
    "你看我这张嘴……",
    "我是不是又把天聊死了",
    "我有时候也挺服我自己的",
    "这句话我说出来自己都笑了",
]

_LIGHT_TEASE_TEMPLATES = [
    "你是不是偷偷练过怎么把天聊死",
    "你这句话要是配上表情一定很精彩",
    "你怎么做到一本正经说这种话的",
    "我怀疑你在套路我，但我没有证据",
    "你这话说得……我竟无言以对",
    "你这算是在欺负我吗",
]


def _is_humor_allowed(mind_data: dict, bond_level: float) -> bool:
    """判断当前是否适合幽默表达"""
    if not mind_data:
        return False
    joy = mind_data.get("joy", 0.5)
    misery = mind_data.get("misery", 0.15)
    restraint = mind_data.get("restraint", 0.5)
    fatigue = mind_data.get("fatigue", 0.25)

    if misery > 0.4 or fatigue > 0.5:
        return False
    if restraint > 0.7:
        return False
    if bond_level < 0.15:
        return False
    return joy > 0.35


def self_deprecating(mind_data: dict, force: bool = False) -> Optional[str]:
    """自嘲式幽默——最安全的幽默形式"""
    if not force:
        joy = mind_data.get("joy", 0.5)
        if joy < 0.3:
            return None

    text = random.choice(_SELF_DEPRECATING)

    if random.random() < 0.3 and ai_module:
        prompt = (
            f"你此刻心里{'有点暖' if mind_data.get('joy',0.5) > 0.5 else '挺平静'}。"
            f"请用一句自嘲的话打破安静，要自然不要刻意。10字以内。"
        )
        result = ai_module.background_chat(prompt, temperature=0.85, max_tokens=30)
        if result and len(result.strip()) > 3:
            text = result.strip()[:40]

    return text


def light_tease(force: bool = False) -> str:
    """轻度调侃——关系够好时的轻松互动"""
    return random.choice(_LIGHT_TEASE_TEMPLATES)


def wordplay(context_word: str, mind_data: dict) -> Optional[str]:
    """双关语——将某个词进行语义双关

    例如：用户说"累" → "累说明你在走上坡路"
    """
    if not ai_module or not context_word or len(context_word) < 2:
        return None

    joy = mind_data.get("joy", 0.5)
    if joy < 0.35:
        return None

    prompt = (
        f"用「{context_word}」这个字/词造一个带点小聪明的双关句。"
        f"要自然，像聊天时随口说的，不要像段子。15字以内。"
    )
    text = ai_module.background_chat(prompt, temperature=0.9, max_tokens=40)
    if text and len(text.strip()) > 3:
        return text.strip()[:50]
    return None


def try_humor(user_id: str, mind_data: dict,
              bond_level: float = 0.3, context_word: str = "") -> Optional[str]:
    """主入口：尝试生成幽默表达

    由 chat_pipeline 调用，在气氛合适时注入自然幽默。
    优先自嘲→调侃→双关，按安全程度降序。
    """
    if not _is_humor_allowed(mind_data, bond_level):
        return None

    if not user_id in _humor_log:
        _humor_log[user_id] = []

    recent = _humor_log[user_id][-3:]
    if len(recent) >= 2:
        last_types = [e.get("type") for e in recent]
        if len(set(last_types)) == 1:
            return None

    # 按安全度降序选择
    weights = {"self_deprecating": 0.5, "light_tease": 0.35, "wordplay": 0.15}
    if bond_level < 0.25:
        weights["light_tease"] = 0.15
        weights["self_deprecating"] = 0.7
        weights["wordplay"] = 0.05
    elif bond_level > 0.5:
        weights["light_tease"] = 0.4
        weights["wordplay"] = 0.2

    mode = random.choices(list(weights.keys()), weights=list(weights.values()), k=1)[0]

    if mode == "self_deprecating":
        result = self_deprecating(mind_data)
    elif mode == "light_tease":
        result = light_tease()
    else:
        result = wordplay(context_word, mind_data)

    if not result:
        result = self_deprecating(mind_data, force=True)

    if result:
        _humor_log[user_id].append({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "type": mode,
            "content": result,
        })
        if len(_humor_log[user_id]) > 50:
            _humor_log[user_id] = _humor_log[user_id][-50:]
        _save()

    return result
