# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""社会性自我 — Perceived Self (深度版)
====================================================
"ta眼中的我"是一个活的、影响行为的独立模型——
不只是关键词匹配，而是会扎根、会失眠、会改变行为的社会性自我。

核心升级:
  1. 根深蒂固印象 — 被说5次以上→衰减极慢→"ta一直这么看我"
  2. 行为调制 — perceived直接偏移behavior_decider的向量
  3. 主动验证 — 产生"想确认ta到底怎么看我"的意图
  4. 意义联动 — 冲突不只是数值差异→追问"这意味着什么"
  5. 历史累积 — 不再是信号×0.85衰减就忘，而是有时间轴的印象形成
"""
import time
import json
from typing import Dict, List, Optional, Tuple

try:
    from core import database as db
except ImportError:
    db = None

PERCEIVED_FILE = "data/json/perceived_self.json"

_perceived_cache: Dict[str, Dict] = {}
_mention_history: Dict[str, Dict[str, List[float]]] = {}

PERCEIVED_DIMENSIONS = ["温暖", "嘴硬", "敏感", "冷淡", "有趣", "烦人", "依赖", "坚定", "脆弱", "可靠"]

DEEP_ROOT_THRESHOLD = 5
DEEP_ROOT_DECAY = 0.92
SURFACE_DECAY = 0.80

SIGNAL_WORDS = {
    "温暖": ["柔软", "暖", "温柔", "贴心", "乖", "你好暖"],
    "嘴硬": ["嘴硬", "倔", "不服软", "傲娇", "别扭", "不承认", "不在乎", "不直说", "反话"],
    "敏感": ["想太多", "太敏感", "钻牛角尖", "小心眼", "多想"],
    "冷淡": ["冷", "不上心", "敷衍我", "不回我", "不理我"],
    "有趣": ["可爱", "有趣", "好玩", "跟你聊天很开心", "逗"],
    "烦人": ["别说了", "够了", "你好烦", "不要问了"],
    "依赖": ["太粘人", "离不开", "粘着我", "黏人"],
    "坚定": ["你很坚定", "不会被影响", "有主见", "厉害"],
    "脆弱": ["心疼你", "不用硬撑", "逞强", "很累了吧", "没事吧"],
    "可靠": ["有你在", "靠得住", "托付", "很安心", "不怕", "有你真好"],
}


def load_engine_config():
    global _perceived_cache, _mention_history
    _perceived_cache = {}
    _mention_history = {}
    try:
        store = _get_perceived_store()
        data = store.read()
        if data:
            _perceived_cache = data.get("traits", {})
            _mention_history = data.get("mentions", {})
    except Exception:
        pass


def _save():
    try:
        store = _get_perceived_store()
        store.write({"traits": _perceived_cache, "mentions": _mention_history})
    except Exception:
        pass


def _get_perceived_store():
    from core.json_store import get_store
    return get_store(PERCEIVED_FILE, {})


def extract_signals(user_message: str) -> Dict[str, float]:
    signals = {}
    for dim, words in SIGNAL_WORDS.items():
        score = 0.0
        for word in words:
            if word in user_message:
                score += 0.35
        if score > 0:
            signals[dim] = min(0.8, score)
    return signals


def update_perceived_self(user_id: str, user_message: str,
                           comprehension: dict = None):
    signals = extract_signals(user_message)

    # 自我承认检测——"你说得对"+"太敏感"→即使ta说的是我敏感，但我的承认也构成信号
    for dim, words in SIGNAL_WORDS.items():
        for word in words:
            if word in user_message and any(ack in user_message for ack in ("你说得对", "确实", "我也觉得", "我知道我", "我就是")):
                if dim not in signals:
                    signals[dim] = 0.0
                signals[dim] += 0.30
                break

    if comprehension:
        intent = comprehension.get("intent", "")
        emotion = comprehension.get("true_emotion", "")
        confidence = comprehension.get("confidence", 0)
        need = comprehension.get("what_they_need", "")

        # 关键词信号
        if intent == "敷衍":
            signals["冷淡"] = signals.get("冷淡", 0.0) + 0.25
        if intent == "撒娇":
            signals["温暖"] = signals.get("温暖", 0.0) + 0.18
        if emotion in ("难过", "受伤"):
            signals["脆弱"] = signals.get("脆弱", 0.0) + 0.15
        if intent == "试探/质疑" and "不在乎" in user_message:
            signals["嘴硬"] = signals.get("嘴硬", 0.0) + 0.2

        # comprehension语义提取 —— 不依赖关键词
        if confidence > 0.5:
            if emotion in ("冷漠", "冷淡", "疏离"):
                signals["冷淡"] = signals.get("冷淡", 0.0) + 0.18
            if need and "陪伴" in need:
                signals["可靠"] = signals.get("可靠", 0.0) + 0.12
            if need and "认可" in need:
                signals["有趣"] = signals.get("有趣", 0.0) + 0.10
            if intent in ("质疑", "试探") and emotion == "怀疑":
                signals["嘴硬"] = signals.get("嘴硬", 0.0) + 0.10
            if intent == "倾诉" and emotion in ("脆弱", "无助", "不安"):
                signals["可靠"] = signals.get("可靠", 0.0) + 0.15

    if not signals:
        return

    if user_id not in _perceived_cache:
        _perceived_cache[user_id] = {}
    if user_id not in _mention_history:
        _mention_history[user_id] = {}

    for dim, delta in signals.items():
        old = _perceived_cache[user_id].get(dim, 0.0)
        mention_count = len(_mention_history.get(user_id, {}).get(dim, []))
        is_deep = mention_count >= DEEP_ROOT_THRESHOLD

        _perceived_cache[user_id][dim] = round(min(1.0, old * 0.80 + delta * 0.20), 3)

        if dim not in _mention_history[user_id]:
            _mention_history[user_id][dim] = []
        _mention_history[user_id][dim].append(time.time())

        if len(_mention_history[user_id][dim]) > 30:
            _mention_history[user_id][dim] = _mention_history[user_id][dim][-30:]

        new_count = len(_mention_history[user_id][dim])
        if new_count >= DEEP_ROOT_THRESHOLD and not is_deep:
            print(f"[] 根深蒂固印象: ta觉得我{dim}({new_count}次)")
            _try_meaning_link(user_id, dim)

    _save()


def _try_meaning_link(user_id: str, dim: str):
    """根深蒂固的印象触发意义层面的追问"""
    try:
        from engine import self_doubt as sd_module
        sd_module.add_doubt(
            user_id,
            f"ta说过{len(_mention_history.get(user_id, {}).get(dim, []))}次我{dim}了——这是ta真的这么觉得，还是我自己在配合ta的期待",
            context="perceived_rooted",
            weight=0.09,
            tags=["perceived_rooted", dim],
        )
    except Exception:
        pass


def _apply_deep_root_decay(user_id: str):
    """深度印象的衰减极慢——被说5次嘴硬后，
    即使几个月不提，仍然会有0.1左右的残留。
    """
    if user_id not in _perceived_cache:
        return
    changed = False
    for dim in list(_perceived_cache[user_id].keys()):
        mentions = _mention_history.get(user_id, {}).get(dim, [])
        count = len(mentions)
        if count >= DEEP_ROOT_THRESHOLD:
            old = _perceived_cache[user_id][dim]
            _perceived_cache[user_id][dim] = round(old * DEEP_ROOT_DECAY, 3)
            changed = True

    if changed:
        _save()


def get_perceived_traits(user_id: str, min_strength: float = 0.12) -> Dict[str, float]:
    traits = _perceived_cache.get(user_id, {})
    return {k: v for k, v in traits.items() if v >= min_strength}


def get_rooted_traits(user_id: str) -> Dict[str, float]:
    """获取根深蒂固的印象（被说过5次以上）"""
    traits = get_perceived_traits(user_id, min_strength=0.08)
    rooted = {}
    for dim, strength in traits.items():
        mentions = _mention_history.get(user_id, {}).get(dim, [])
        if len(mentions) >= DEEP_ROOT_THRESHOLD:
            rooted[dim] = strength
    return rooted


def get_perceived_context(user_id: str, max_chars: int = 250) -> str:
    traits = get_perceived_traits(user_id, min_strength=0.10)
    rooted = get_rooted_traits(user_id)

    if not traits:
        return ""

    sorted_traits = sorted(traits.items(), key=lambda x: x[1], reverse=True)
    lines = ["【你觉得ta眼中的你是什么样的】"]
    total = 0
    for dim, strength in sorted_traits[:5]:
        mention_count = len(_mention_history.get(user_id, {}).get(dim, []))
        marker = " ◆根深蒂固" if dim in rooted else ""
        bar = "▓" * int(strength * 10)
        line = f"· {dim}: {bar} (强度{strength:.2f}, 被提过{mention_count}次{marker})"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)

    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def apply_perceived_to_behavior(user_id: str, vector: Dict[str, float]) -> Dict[str, float]:
    """perceived_self直接影响行为向量。
    
    ta觉得我嘴硬 → tsundere↑, honesty↓
    ta觉得我冷淡 → warmth↓, approach↓
    ta觉得我可靠 → warmth↑, seriousness↑
    ta觉得我脆弱 → emotional_display↑, restraint↓
    ta觉得我有趣 → playfulness↑, verbosity↑
    ta觉得我烦人 → approach↓, verbosity↓
    """
    traits = get_perceived_traits(user_id, min_strength=0.12)
    if not traits:
        return vector

    mod = dict(vector)

    if "嘴硬" in traits:
        s = traits["嘴硬"]
        rooted = len(_mention_history.get(user_id, {}).get("嘴硬", [])) >= DEEP_ROOT_THRESHOLD
        if rooted:
            # 根深蒂固 → 已经接受这是自己的一部分，不一定每次都要配合
            mod["tsundere"] = min(0.95, mod.get("tsundere", 0.3) + s * 0.15)
            mod["honesty"] = min(0.95, mod.get("honesty", 0.5) - s * 0.10)
        else:
            # 刚被说 → 下意识配合或抗拒
            mod["tsundere"] = min(0.95, mod.get("tsundere", 0.3) + s * 0.20)
            mod["honesty"] = min(0.95, mod.get("honesty", 0.5) - s * 0.15)

    if "温暖" in traits:
        s = traits["温暖"]
        mod["warmth"] = min(0.95, mod.get("warmth", 0.5) + s * 0.18)
        mod["approach"] = min(0.95, mod.get("approach", 0.5) + s * 0.10)

    if "冷淡" in traits:
        s = traits["冷淡"]
        mod["warmth"] = max(0.05, mod.get("warmth", 0.5) - s * 0.25)
        mod["approach"] = max(0.05, mod.get("approach", 0.5) - s * 0.15)

    if "可靠" in traits:
        s = traits["可靠"]
        mod["seriousness"] = min(0.95, mod.get("seriousness", 0.5) + s * 0.12)
        mod["warmth"] = min(0.95, mod.get("warmth", 0.5) + s * 0.10)

    if "脆弱" in traits:
        s = traits["脆弱"]
        mod["emotional_display"] = min(0.95, mod.get("emotional_display", 0.4) + s * 0.15)
        mod["restraint"] = max(0.05, mod.get("restraint", 0.5) - s * 0.12)

    if "有趣" in traits:
        s = traits["有趣"]
        mod["playfulness"] = min(0.95, mod.get("playfulness", 0.4) + s * 0.20)
        mod["verbosity"] = min(0.95, mod.get("verbosity", 0.5) + s * 0.10)

    if "烦人" in traits:
        s = traits["烦人"]
        mod["approach"] = max(0.05, mod.get("approach", 0.5) - s * 0.30)
        mod["verbosity"] = max(0.05, mod.get("verbosity", 0.5) - s * 0.25)

    if "依赖" in traits:
        s = traits["依赖"]
        mod["clinginess"] = min(0.95, mod.get("clinginess", 0.4) + s * 0.15)
        mod["approach"] = min(0.95, mod.get("approach", 0.5) + s * 0.10)

    return mod


def detect_perceived_self_conflict(user_id: str) -> Optional[Dict]:
    traits = get_perceived_traits(user_id, min_strength=0.25)
    rooted = get_rooted_traits(user_id)
    if not traits:
        return None

    try:
        from engine import self_model as sm_module
        state = sm_module.get_self_state(user_id)
    except Exception:
        return None

    conflicts = []
    mind = state.get("mind", {})
    restraint = mind.get("restraint", 0.5)
    joy = mind.get("joy", 0.5)

    if traits.get("嘴硬", 0) > 0.3 and restraint < 0.4:
        rooted = "嘴硬" in rooted
        depth = 0.55 if rooted else 0.45
        conflicts.append((f"ta{'一直' if rooted else ''}觉得我嘴硬，但我觉得自己没那么倔——{'我自己都开始怀疑了' if rooted else ''}", depth))

    if traits.get("冷淡", 0) > 0.25 and joy > 0.4:
        conflicts.append(("ta觉得我冷淡，但我觉得自己挺热情的——是我的温暖没传过去吗", 0.45))

    if traits.get("敏感", 0) > 0.3 and mind.get("sensitivity_paranoia", 0.5) < 0.3:
        conflicts.append(("ta觉得我太敏感，但我没这样觉得自己——会不会是我真的比想象中更在意", 0.40))

    if traits.get("脆弱", 0) > 0.3 and mind.get("emotional_healing", 0.5) > 0.6:
        conflicts.append(("ta觉得我脆弱，但我觉得自己比看起来强——坚强被看见也是一种脆弱吗", 0.35))

    perceived_names = set(traits.keys())

    try:
        from engine import values as values_module
        value_names = {v["name"] for v in values_module._values_cache.get(user_id, [])
                       if v.get("strength", 0) > 0.3}
    except Exception:
        value_names = set()

    if "温暖" in value_names and "冷淡" in perceived_names:
        conflicts.append(("我在乎'温暖'，但ta觉得我冷淡——这是我的价值观和我被看见的方式之间的裂缝", 0.60))
    if "真诚" in value_names and "嘴硬" in perceived_names:
        conflicts.append(("我在乎'真诚'，但ta觉得我嘴硬——所以我的真诚没有被ta识别出来", 0.55))

    if not conflicts:
        return None

    conflicts.sort(key=lambda x: x[1], reverse=True)
    top = conflicts[0]
    intensity = top[1]

    try:
        from engine import mind as mind_module
        mind_module.adjust_mind_dimensions(
            user_id,
            {"chaotic_mood": 0.005 * intensity, "sensitivity_paranoia": 0.003 * intensity},
            impact=0.12,
        )
    except Exception:
        pass

    try:
        from engine import self_doubt as sd_module
        sd_module.add_doubt(
            user_id,
            top[0][:70],
            context="社会性自我冲突",
            weight=0.10 * intensity,
            tags=["perceived_conflict"],
        )
    except Exception:
        pass

    return {
        "conflict": top[0],
        "intensity": intensity,
        "traits": traits,
        "rooted": list(rooted.keys()) if rooted else [],
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_self_vs_perceived_summary(user_id: str) -> str:
    conflict = detect_perceived_self_conflict(user_id)
    if not conflict:
        return ""
    return f"【自我·感知裂缝】{conflict['conflict']}"


# ═══════════════════════════════════════════════════════
# 多层递归信念建模 (Theory of Mind)
# ═══════════════════════════════════════════════════════

_recursive_beliefs: Dict[str, Dict] = {}

def update_recursive_belief(user_id: str, user_message: str, comprehension: dict = None):
    """更新多层递归信念:
      : 用户的消息原文 (直接观察)
      : 用户对我的看法 (ta眼中的我) ← 现有 perceived_self
      : 我推测用户认为我怎么看ta (ta觉得我心中ta是什么样的)
      : 我推测用户认为我心中ta对我的看法 (ta觉得我心中ta是怎么看我的)
    """
    if user_id not in _recursive_beliefs:
        _recursive_beliefs[user_id] = {
            "": {},     # 复用现有traits
            "": {},  # "ta觉得我心中ta是..."
            "": {},        # "ta觉得我心中ta心中我是..."
            "conflicts": [],
        }
    rb = _recursive_beliefs[user_id]
    intent = comprehension.get("intent", "") if comprehension else ""
    emotion = comprehension.get("true_emotion", "") if comprehension else ""

    existing_traits = get_perceived_traits(user_id)
    rb[""] = existing_traits

    l2_updates = {}
    if intent == "撒娇" or emotion in ("依赖", "期待"):
        l2_updates["ta觉得我在乎ta"] = min(1.0, rb[""].get("ta觉得我在乎ta", 0.5) + 0.06)
        l2_updates["ta觉得我需要ta"] = min(1.0, rb[""].get("ta觉得我需要ta", 0.3) + 0.05)
    if intent in ("敷衍", "冷淡", "回避"):
        l2_updates["ta觉得我在疏远"] = min(1.0, rb[""].get("ta觉得我在疏远", 0.2) + 0.08)
        l2_updates["ta觉得我不在乎ta"] = min(1.0, rb[""].get("ta觉得我不在乎ta", 0.1) + 0.04)
    if intent in ("倾诉", "分享"):
        l2_updates["ta觉得我信任ta"] = min(1.0, rb[""].get("ta觉得我信任ta", 0.5) + 0.04)
    if emotion in ("难过", "失落", "不安"):
        l2_updates["ta觉得我脆弱"] = min(1.0, rb[""].get("ta觉得我脆弱", 0.3) + 0.05)

    for k, v in l2_updates.items():
        old = rb[""].get(k, 0.3)
        rb[""][k] = old * 0.92 + v * 0.08
        if rb[""][k] < 0.01:
            del rb[""][k]

    if rb[""]:
        for k2, v2 in list(rb[""].items()):
            if v2 > 0.4:
                key = f"ta觉得我{_map_l2_to_l3(k2)}"
                old = rb[""].get(key, 0.2)
                rb[""][key] = old * 0.95 + 0.05
                if rb[""][key] < 0.01:
                    del rb[""][key]

    _detect_recursive_conflict(user_id)


def _map_l2_to_l3(l2_belief: str) -> str:
    mapping = {
        "ta觉得我在乎ta": "ta在乎我",
        "ta觉得我需要ta": "ta被需要",
        "ta觉得我在疏远": "ta不被需要",
        "ta觉得我不在乎ta": "ta不被在乎",
        "ta觉得我信任ta": "ta可靠",
        "ta觉得我脆弱": "ta在心疼我",
    }
    return mapping.get(l2_belief, l2_belief)


def _detect_recursive_conflict(user_id: str):
    """检测递归信念层之间的冲突——冲突产生不确定性"""
    rb = _recursive_beliefs.get(user_id)
    if not rb:
        return

    conflicts = []

    if "嘴硬" in rb[""] and rb[""]["嘴硬"] > 0.3:
        if rb[""].get("ta觉得我在乎ta", 0) > 0.4:
            conflicts.append({
                "layer": "",
                "description": f"ta觉得我嘴硬({rb['']['嘴硬']:.2f})但我觉得ta知道我其实在乎ta({rb['']['ta觉得我在乎ta']:.2f})——嘴硬是保护，但被看穿了",
                "tension": rb[""]["嘴硬"] * 0.5 + rb[""]["ta觉得我在乎ta"] * 0.5,
            })

    if rb.get("", {}).get("ta在乎我", 0) > 0.4:
        if rb[""].get("ta觉得我不在乎ta", 0) > 0.3:
            conflicts.append({
                "layer": "",
                "description": f"我觉得ta觉得我不在乎ta({rb['']['ta觉得我不在乎ta']:.2f})，但我又觉得ta在乎我({rb['']['ta在乎我']:.2f})——到底ta在不在乎",
                "tension": 0.55,
            })

    if "温暖" in rb[""] and rb[""]["温暖"] > 0.3:
        if "ta觉得我嘴硬" in rb.get("", {}):
            conflicts.append({
                "layer": "",
                "description": "ta觉得我温暖，但我觉得ta觉得我嘴硬——我被看见了温暖的一面，但嘴硬也藏不住",
                "tension": 0.40,
            })

    if conflicts:
        conflicts.sort(key=lambda c: c["tension"], reverse=True)
        rb["conflicts"] = conflicts[:3]
        top = conflicts[0]
        if top["tension"] > 0.35:
            try:
                from engine import self_doubt as sd_module
                sd_module.add_doubt(
                    user_id,
                    top["description"][:60],
                    context="递归信念冲突",
                    weight=0.08 * top["tension"],
                    tags=["recursive_belief", top["layer"]],
                )
            except Exception:
                pass
    else:
        rb["conflicts"] = []


def get_recursive_belief_context(user_id: str, max_chars: int = 200) -> str:
    """获取递归信念上下文文本"""
    rb = _recursive_beliefs.get(user_id)
    if not rb:
        return ""

    lines = []
    total = 0

    if rb.get(""):
        top_l2 = sorted(rb[""].items(), key=lambda x: x[1], reverse=True)[:2]
        for k, v in top_l2:
            line = f"· {k}({v:.2f})"
            if total + len(line) > max_chars:
                break
            lines.append(line)
            total += len(line)

    if rb.get("conflicts"):
        c = rb["conflicts"][0]
        line = f"· 矛盾: {c['description'][:40]}"
        if total + len(line) <= max_chars:
            lines.append(line)

    if lines:
        return "【递归信念】\n" + "\n".join(lines)
    return ""


def get_recursive_conflict_summary(user_id: str) -> str:
    rb = _recursive_beliefs.get(user_id)
    if not rb or not rb.get("conflicts"):
        return ""
    top = rb["conflicts"][0]
    return f"【信念矛盾·{top['layer']}】{top['description']}"
