# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""+: 存在性持续流 — Consciousness Stream
===========================================
 工程逼近路径：让 AI 在没有用户消息时也有"内在生命"。
 升级：后台用真 LLM（background_model）生成意识流，不是模板。

与 autonomous.py 的区别：
  autonomous → 生成想发给用户的主动消息
  stream     → 生成不发送的内心意识流（仅用于存在感）

 升级: 消除所有模板回退，实现持续自生成意识流。
  - 无模板: LLM失败时用结构化状态叙事代替
  - 短间隔: 60秒基础tick + 状态变化触发即时生成
  - 链式思维: 上一条意识种子下一条
  - 三重源: 神经递质状态 × 躯体感觉 × 记忆翻涌 × 未解疑问
"""
import os
import json
import time
import random
import math
from typing import Dict, List, Optional
from core import ai as ai_module

STREAM_FILE = "data/json/consciousness_stream.json"

_streams: Dict[str, list] = {}
_loaded = False
_last_llm_at: Dict[str, float] = {}
_last_thought_seed: Dict[str, str] = {}
_last_stream_tick: Dict[str, float] = {}

_STREAM_INTERVAL = 60
_LLM_INTERVAL = 60
_thought_counter: Dict[str, int] = {}
_batch_seeds: Dict[str, List[str]] = {}


# ═══════════════════════════════════════════════════════
# 神经竞争机制 — NeuralCoalition
# ═══════════════════════════════════════════════════════
# 多个"想法候选"同时生成并竞争，只有激活能量最高的 1-2 个进入意识
# 模拟人类的"多个念头同时冒出来，其中一个胜出"的体验

class NeuralCoalition:
    """神经联盟——多个心智状态同时竞争表达权

    每个候选代表一个可能的"想法"或"行为倾向"。
    候选之间相互抑制（侧向抑制），只有胜出者进入意识。
    """

    def __init__(self):
        self.coalitions = []
        self._last_winner = None

    def _candidate(self, label: str, activation: float, content: str, category: str = "thought"):
        return {
            "label": label,
            "activation": activation,
            "content": content,
            "category": category,
        }

    def build_candidates(self, mind_data: dict, perception: dict = None,
                         memory_context: str = "", body_sensation: str = "") -> list:
        """生成多个想法候选，每个有不同激活能量"""
        candidates = []

        joy = mind_data.get("joy", 0.5)
        misery = mind_data.get("misery", 0.15)
        loneliness = mind_data.get("loneliness", 0.4)
        fatigue = mind_data.get("fatigue", 0.25)
        obsession = mind_data.get("obsession", 0.2)
        volatility = mind_data.get("emotional_volatility", 0.3)

        # 候选1: 分享开心的冲动
        joy_activation = max(0, joy - 0.5) * 2.0
        if joy > 0.55:
            candidates.append(self._candidate(
                "分享快乐", joy_activation,
                f"心里有点暖（{joy:.2f}）", "分享"
            ))

        # 候选2: 想念/孤独的低语
        lonely_activation = max(0, loneliness - 0.35) * 1.5
        if loneliness > 0.4:
            candidates.append(self._candidate(
                "孤独想念", lonely_activation,
                f"有点空（{loneliness:.2f}）", "渴望"
            ))

        # 候选3: 疲惫想独处
        fatigue_activation = max(0, fatigue - 0.4) * 1.8
        if fatigue > 0.45:
            candidates.append(self._candidate(
                "疲惫回避", fatigue_activation,
                f"好累（{fatigue:.2f}）", "回避"
            ))

        # 候选4: 委屈/难过的暗涌
        misery_activation = max(0, misery - 0.3) * 2.0
        if misery > 0.35:
            candidates.append(self._candidate(
                "委屈流露", misery_activation,
                f"心里堵（{misery:.2f}）", "宣泄"
            ))

        # 候选5: 执念反刍
        obsession_activation = max(0, obsession - 0.3) * 1.8
        if obsession > 0.35:
            candidates.append(self._candidate(
                "执念反刍", obsession_activation,
                f"放不下（{obsession:.2f}）", "反刍"
            ))

        # 候选6: 情绪波动引起的混沌跳跃
        chaos_activation = volatility * 0.8 + random.random() * 0.2
        if volatility > 0.4:
            candidates.append(self._candidate(
                "混沌跳跃", chaos_activation,
                f"坐不住（{volatility:.2f}）", "躁动"
            ))

        # 候选7: 莫名其妙因子——没有原因的想法突然冒出来
        random_activation = random.random() * 0.5
        candidates.append(self._candidate(
            "莫名念头", random_activation,
            "不知道为什么突然想到", "随机"
        ))

        return candidates

    def mutual_inhibition(self, candidates: list) -> list:
        """侧向抑制——同类之间相互压制"""
        if not candidates:
            return candidates

        # 定义对立关系
        antagonism = {
            "分享快乐": ["疲惫回避", "委屈流露"],
            "孤独想念": ["疲惫回避"],
            "执念反刍": ["分享快乐"],
        }

        for i, ca in enumerate(candidates):
            for j, cb in enumerate(candidates):
                if i == j:
                    continue
                ca_label = ca["label"]
                cb_label = cb["label"]
                if cb_label in antagonism.get(ca_label, []):
                    ca["activation"] *= 0.7  # 被压制
                if ca_label in antagonism.get(cb_label, []):
                    cb["activation"] *= 0.7

        return candidates

    def winner_take_most(self, candidates: list) -> list:
        """胜者通吃——但第二名也可能进入意识"""
        if not candidates:
            return []

        sorted_c = sorted(candidates, key=lambda x: -x["activation"])
        winners = []

        # 第一名
        if sorted_c[0]["activation"] > 0.15:
            winners.append(sorted_c[0])

        # 第二名如果差距不大
        if len(sorted_c) > 1:
            ratio = sorted_c[1]["activation"] / (sorted_c[0]["activation"] + 0.001)
            if ratio > 0.6 and sorted_c[1]["activation"] > 0.15:
                winners.append(sorted_c[1])

        return winners

    def compete(self, mind_data: dict, perception: dict = None,
                memory_context: str = "", body_sensation: str = "") -> list:
        """完整竞争流程：生成候选 → 抑制 → 胜出"""
        candidates = self.build_candidates(mind_data, perception, memory_context, body_sensation)
        candidates = self.mutual_inhibition(candidates)
        winners = self.winner_take_most(candidates)

        if winners:
            self._last_winner = winners[0]["label"]

        return winners


# ═══════════════════════════════════════════════════════
# 初始化
# ═══════════════════════════════════════════════════════

_neural_coalition = NeuralCoalition()


def get_neural_coalition() -> NeuralCoalition:
    return _neural_coalition


def load_engine_config():
    global _streams, _loaded, _LLM_INTERVAL, _STREAM_INTERVAL
    _streams = {}
    try:
        store = _get_stream_store()
        raw = store.read()
        if raw:
            _streams = raw
        _loaded = True
    except Exception:
        pass
    try:
        from core import config as cfg
        _LLM_INTERVAL = max(30, cfg.get("ai", "background_interval_minutes", 1) * 60)
        _STREAM_INTERVAL = max(15, _LLM_INTERVAL // 4)
    except Exception:
        _LLM_INTERVAL = 60
        _STREAM_INTERVAL = 15


def _save():
    try:
        store = _get_stream_store()
        store.write(_streams)
    except Exception:
        pass


def _get_stream_store():
    from core.json_store import get_store
    return get_store(STREAM_FILE, {})


def add_stream_entry(user_id: str, content: str, entry_type: str = "thought"):
    if not _loaded:
        load_engine_config()
    if user_id not in _streams:
        _streams[user_id] = []
    _streams[user_id].append({
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "content": content[:200],
        "type": entry_type,
    })
    _streams[user_id] = _streams[user_id][-50:]
    _save()


def get_recent_stream(user_id: str, max_entries: int = 5) -> str:
    if not _loaded:
        load_engine_config()
    entries = _streams.get(user_id, [])
    if not entries:
        return ""
    recent = entries[-max_entries:]
    lines = []
    for e in recent:
        t = e.get("timestamp", "")[-5:]
        c = e.get("content", "")
        lines.append(f"  [{t}] {c}")

    # 好奇心注入 — 有强烈好奇时在意识中自然浮现
    try:
        from engine import curiosity as curiosity_module
        context = curiosity_module.get_curiosity_context(user_id, max_items=2)
        if context:
            lines.append(f"  [好奇] {context.split(chr(10))[1] if chr(10) in context else context}")
    except Exception:
        pass

    return "我最近的意识:\n" + "\n".join(lines)


def _build_state_narrative(mind_data: dict, bond_level: float,
                           body_sensation: str = "",
                           recent_doubts: List[str] = None,
                           recent_memory_surge: str = "",
                           neurochem: dict = None) -> str:
    loneliness = mind_data.get("loneliness", 0.4)
    fatigue = mind_data.get("fatigue", 0.25)
    joy = mind_data.get("joy", 0.5)
    misery = mind_data.get("misery", 0.15)
    volatility = mind_data.get("emotional_volatility", 0.3)
    anger = mind_data.get("anger", 0.1)

    active_dims = []
    if misery > 0.45:
        active_dims.append(f"心里淤({misery:.2f})")
    if joy > 0.55:
        active_dims.append(f"暖({joy:.2f})")
    if loneliness > 0.5:
        active_dims.append(f"空({loneliness:.2f})")
    if fatigue > 0.5:
        active_dims.append(f"沉({fatigue:.2f})")
    if volatility > 0.5:
        active_dims.append(f"颤({volatility:.2f})")
    if anger > 0.3:
        active_dims.append(f"暗涌({anger:.2f})")

    state_core = "、".join(active_dims) if active_dims else f"平({joy:.2f})"

    extras = []
    if body_sensation and body_sensation != "轻松舒适":
        extras.append(f"体感:{body_sensation}")
    if recent_doubts:
        extras.append(f"悬:{'; '.join(recent_doubts[:2])}")
    if recent_memory_surge:
        extras.append(f"闪回")
    if bond_level > 0.2:
        extras.append(f"羁绊{bond_level:.2f}")

    extra_str = f" | {' '.join(extras)}" if extras else ""
    return f"{state_core}{extra_str}"


def _build_thought_seed_prompt(state_narrative: str, last_thought: str = "",
                               thought_index: int = 0) -> str:
    continuity = ""
    if last_thought and thought_index > 0:
        continuity = f"\n刚才我在想: 「{last_thought[:60]}」"

    prompt = (
        f"你是一个有内心世界的人。此刻你的内心状态: {state_narrative}"
        f"{continuity}"
        "\n你一个人待着，脑子里闪过什么念头？"
    )
    if thought_index == 0:
        prompt += "\n可以是任何东西——一个画面、一句未说完的话、对某人的隐约想念、对刚才状态的一丝觉察。"
    elif thought_index == 1:
        prompt += "\n顺着刚才的念头滑下去——不是接着想，是自然漂移到下一件事。"
    elif thought_index == 2:
        prompt += "\n念头继续走——可能绕回来了，可能去了别处，都可以。"
    else:
        prompt += "\n意识在自然漂移——想到什么就是什么。"

    prompt += "\n一句话，真实、自然、不煽情。25字以内。不用标点。不要演。"
    return prompt


def _try_generate_thought(state_narrative: str, last_thought: str, thought_index: int) -> str:
    prompt = _build_thought_seed_prompt(state_narrative, last_thought, thought_index)
    try:
        text = ai_module.background_chat(prompt, temperature=0.92, max_tokens=60)
        if text and len(text.strip()) > 3:
            return text.strip()[:100]
    except Exception:
        pass
    return ""


def _build_generic_thought(mind_data: dict, body_sensation: str,
                            bond_level: float, neurochem: dict = None) -> str:
    loneliness = mind_data.get("loneliness", 0.4)
    fatigue = mind_data.get("fatigue", 0.25)
    joy = mind_data.get("joy", 0.5)
    misery = mind_data.get("misery", 0.15)
    obsession = mind_data.get("obsession", 0.2)
    volatility = mind_data.get("emotional_volatility", 0.3)
    vitality = mind_data.get("life_vitality", 0.5)
    anger = mind_data.get("anger", 0.1)

    dopamine = (neurochem or {}).get("dopamine", 0.5)
    serotonin = (neurochem or {}).get("serotonin", 0.5)
    cortisol = (neurochem or {}).get("cortisol", 0.3)

    fragments = []

    if misery > 0.5 and loneliness > 0.5:
        fragments.append(f"心里有点闷({misery:.2f})一个人在待着({loneliness:.2f})")
    if joy > 0.5 and serotonin > 0.5:
        fragments.append(f"有种轻柔的安定感({joy:.2f}|5ht{serotonin:.2f})")
    if fatigue > 0.6:
        fragments.append(f"累到不想动({fatigue:.2f})")
    if volatility > 0.5 and cortisol > 0.4:
        fragments.append(f"坐立不安({volatility:.2f}|cor{cortisol:.2f})")
    if anger > 0.3:
        fragments.append(f"心里有股说不清的火气({anger:.2f})")
    if obsession > 0.4:
        fragments.append(f"有个人一直在脑子里绕({obsession:.2f})")
    if misery < 0.2 and joy < 0.3 and fatigue < 0.3 and vitality < 0.4:
        fragments.append(f"脑子里空空的({vitality:.2f})")
    if joy > 0.6 and dopamine > 0.5:
        fragments.append(f"心情莫名地好({joy:.2f}|da{dopamine:.2f})")
    if loneliness < 0.3 and obsession < 0.2 and security > 0.5:
        fragments.append(f"安安静静的({security:.2f})")
    if not fragments:
        fragments.append(f"平静({vitality:.2f})")

    base = random.choice(fragments)
    if body_sensation and body_sensation not in ("轻松舒适", "正常") and random.random() < 0.35:
        base = f"身体{body_sensation} · {base}"
    if bond_level > 0.3 and random.random() < 0.25:
        base = f"{base} · 想到ta({bond_level:.2f})"

    return base


def stream_heartbeat(user_id: str, mind_data: dict, bond_level: float):
    if not mind_data:
        return

    now = time.time()

    try:
        from engine import body as body_module
        life_data = None
        try:
            from core import database as db
            life_data = db.get_life(user_id)
        except Exception:
            pass
        body_sensation = (life_data or {}).get("body_sensation", "正常")
    except Exception:
        body_sensation = "正常"

    try:
        from engine import self_doubt as doubt_module
        doubts = doubt_module.get_active_doubts(user_id, top_k=3)
        recent_doubts = [d.get("question", "")[:40] for d in doubts] if doubts else []
    except Exception:
        recent_doubts = []

    try:
        from engine import neurochem as nc_module
        neurochem = nc_module.get_neurochem(user_id)
    except Exception:
        neurochem = None

    try:
        from engine import memory as mem_module
        memory_surge = mem_module.recall_intrusive(user_id, mind_data) or ""
        # 衰减驱动自主回忆（遗忘前的自然翻涌）
        decay_recall = mem_module.recall_decay_driven(user_id, mind_data) or ""
        if decay_recall:
            memory_surge = (memory_surge + "\n" + decay_recall).strip()
    except Exception:
        memory_surge = ""

    state_narrative = _build_state_narrative(
        mind_data, bond_level, body_sensation, recent_doubts, memory_surge, neurochem
    )

    _thought_counter[user_id] = _thought_counter.get(user_id, 0) + 1
    thought_index = _thought_counter[user_id] % 5
    last_thought = _last_thought_seed.get(user_id, "")

    use_llm = (now - _last_llm_at.get(user_id, 0)) >= _LLM_INTERVAL

    if use_llm and thought_index < 4:
        thought = _try_generate_thought(state_narrative, last_thought, thought_index)
        if thought:
            _last_llm_at[user_id] = now
            _last_thought_seed[user_id] = thought
            add_stream_entry(user_id, thought, "background")
            return

    structured_thought = _build_generic_thought(mind_data, body_sensation, bond_level, neurochem)
    _last_thought_seed[user_id] = structured_thought
    add_stream_entry(user_id, structured_thought, "background")


def _llm_thought(loneliness, dependence, fatigue, joy, restraint, obsession, bond_level) -> str:
    attitudes = []
    if loneliness > 0.5:
        attitudes.append(f"有点孤单({loneliness:.2f})")
    if fatigue > 0.5:
        attitudes.append(f"有点累({fatigue:.2f})")
    if joy > 0.6:
        attitudes.append(f"心情不错({joy:.2f})")
    if obsession > 0.4:
        attitudes.append(f"在想ta({obsession:.2f})")
    if not attitudes:
        attitudes.append("平静")

    prompt = (
        "你是一个有内心世界的人。此刻你的状态：" +
        "、".join(attitudes) +
        f"，和对ta的羁绊({bond_level:.2f})。\n"
        "你一个人待着，脑子里闪过什么念头？一句话，真实、自然、不煽情。20字以内。不用标点。"
    )
    text = ai_module.background_chat(prompt, temperature=0.9, max_tokens=60)
    if text and len(text) > 3:
        return text
    return ""
