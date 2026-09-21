# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""自主思考引擎 —— 情绪深度绑定版
=====================================
1. 忍不住了 → 主动发消息（冲动值=loneliness+dependence+obsession-fatigue）
2. 想到有意思的事 → 分享（受life_vitality+joy驱动）
3. 回忆起过去 → 突然提起（受bond+soul_resonance驱动）
4. 观察/感受 → 自然流露

 新增：
  - 跟踪"谁先开口"的对话状态：主动发起后，用户回复时给予温暖回应
  - 情绪驱动的主动消息频率：低落时不发，赌气时可能发别扭消息
  - 用户回复主动消息时系统知道"她回我了"→ 态度变化

所有生成的消息进入 pending_messages 队列，
由 delivery.py 控制投递节奏。
"""
from __future__ import annotations

import json
import random
import re
import time
import threading
from datetime import datetime

from core import database as db
from core import ai as ai_module

# ── 配置缓存 ──
_CONFIG = {}

def load_engine_config():
    """从 config.json 加载自主引擎配置"""
    global _CONFIG
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
        _CONFIG = cfg.get("autonomous", {})
    except Exception:
        _CONFIG = {}


def _cfg(key: str, default=None):
    return _CONFIG.get(key, default)


# ═══════════════════════════════════════════════════════
# 情绪-模板缓存（减少 LLM 调用量 60%+）
# ═══════════════════════════════════════════════════════

class EmotionalMessageCache:
    """情绪→消息模板缓存。

    将"情绪状态组合 → 已生成的消息"缓存起来。
    相同的情绪状态组合直接复用，避免重复调用 LLM。
    缓存 5 分钟过期，命中率预估 >60%。
    """

    def __init__(self, max_age: int = 300):
        self._cache: Dict[str, Dict] = {}
        self._max_age = max_age
        self._lock = threading.Lock()

    def _state_key(self, mind_data: dict) -> str:
        """将 24 维心智压缩为粗粒度状态签名。"""
        key_dims = ["loneliness", "dependence", "obsession", "joy", "fatigue",
                     "restraint", "misery", "life_vitality", "chaotic_mood"]
        parts = []
        for d in key_dims:
            val = mind_data.get(d, 0.5)
            bucket = int(val * 10)
            parts.append(f"{d}={bucket}")
        return ":".join(parts)

    def get(self, mind_data: dict, msg_type: str) -> str | None:
        """从缓存中获取匹配的消息。返回 None 表示未命中。"""
        key = self._state_key(mind_data)
        cache_key = f"{key}:{msg_type}"
        with self._lock:
            entry = self._cache.get(cache_key)
            if not entry:
                return None
            cached_time = entry.get("time", 0)
            if time.time() - cached_time > self._max_age:
                del self._cache[cache_key]
                return None
            messages = entry.get("messages", [])
            if not messages:
                return None
            return random.choice(messages)

    def store(self, mind_data: dict, msg_type: str, messages: list):
        """存储一批消息到缓存。"""
        key = self._state_key(mind_data)
        cache_key = f"{key}:{msg_type}"
        with self._lock:
            self._cache[cache_key] = {
                "messages": messages[:5],
                "time": time.time(),
            }

    def clear(self):
        """清空缓存（强制重新生成）。"""
        with self._lock:
            self._cache.clear()


# 全局缓存实例
_message_cache = EmotionalMessageCache()


# ── 后台线程 ──
_thought_running = threading.Event()
_last_thought_at: dict = {}  # user_id → timestamp
_today_recall_count: dict = {}  # user_id → 今日回忆触发次数

# 跟踪系统主动发起的对话
_initiated_conversations: dict = {}  # user_id → {"active": bool, "initiated_at": str, "message_count": int}

# 线程安全锁
_initiated_lock = threading.Lock()
_thought_state_lock = threading.Lock()

# ── 按类型冷却 ──
# 原来只有 delivery_cooldown_seconds（全局 120s）一道闸门，管不住"同一种情绪
# 反复说"。实测出现过 19:25:51 和 19:32:07 两条 emotional_overflow，说的是
# 同一个意思（"满脑子都是你" / "突然特别想你"）——观感上就是 ta 在复读。
# 现在每种主动消息各有冷却，默认值见 _DEFAULT_TYPE_COOLDOWN，可在 config.json
# 的 autonomous 段用 <类型>_cooldown_seconds 覆盖。
_DEFAULT_TYPE_COOLDOWN = {
    "emotional_overflow": 1800,
    "interesting_thought": 1200,
    "memory_recall": 3600,
    "search_inspired": 1800,
}

_TYPE_LABELS = {
    "emotional_overflow": "情感溢出",
    "interesting_thought": "有趣想法",
    "memory_recall": "回忆唤醒",
    "search_inspired": "搜索灵感",
}

_last_type_at: dict = {}  # user_id → {msg_type: timestamp}


def _type_ready(user_id: str, msg_type: str) -> bool:
    """这种主动消息现在能不能发（各自的冷却到期没）。

    冷却没过时直接返回 False，连 _check_* 都不进——省掉那次概率掷骰
    和可能的 LLM 调用。
    """
    cooldown = _cfg("%s_cooldown_seconds" % msg_type,
                    _DEFAULT_TYPE_COOLDOWN.get(msg_type, 900))
    with _thought_state_lock:
        last = _last_type_at.get(user_id, {}).get(msg_type, 0)
    return time.time() - last >= cooldown


def _mark_type_sent(user_id: str, msg_type: str):
    with _thought_state_lock:
        _last_type_at.setdefault(user_id, {})[msg_type] = time.time()


def _emit_proactive(user_id: str, result: dict, msg_type: str,
                    batch_types: set) -> bool:
    """把一条主动消息交给队列。

    返回是否真的入队：队列层的近似重复判定会丢掉"最近说过的话"
    （返回 None），那种情况不占本批名额，也不会刷新冷却。
    """
    msg_id = db.add_pending_message(user_id, result["content"],
                                    msg_type=msg_type,
                                    priority=result["priority"])
    if msg_id is None:
        print(f"[自主引擎] {_TYPE_LABELS.get(msg_type, msg_type)} 与最近说过的话重复，已跳过")
        return False
    _mark_type_sent(user_id, msg_type)
    batch_types.add(msg_type)
    print(f"[自主引擎] {_TYPE_LABELS.get(msg_type, msg_type)} → "
          f"{result['content'][:30]}... (p={result['priority']:.2f})")
    return True


# ═══════════════════════════════════════════════════════
# 对话主动权追踪
# ═══════════════════════════════════════════════════════

def mark_initiated_conversation(user_id: str):
    """标记：系统向该用户发起了一次主动对话"""
    with _initiated_lock:
        _initiated_conversations[user_id] = {
            "active": True,
            "initiated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "message_count": 0,
        }
    print(f"[自主引擎] 标记主动对话: user={user_id}")


def is_reply_to_initiative(user_id: str) -> bool:
    """检查用户消息是否是回复系统主动发起的对话。"""
    with _initiated_lock:
        conv = _initiated_conversations.get(user_id, {})
        return conv.get("active", False)


def ack_user_replied_to_initiative(user_id: str):
    """确认用户已回复主动消息。"""
    with _initiated_lock:
        conv = _initiated_conversations.get(user_id, {})
        if conv.get("active"):
            conv["message_count"] = conv.get("message_count", 0) + 1
            if conv["message_count"] >= 3:
                conv["active"] = False
                print(f"[自主引擎] 主动对话自然结束: user={user_id}")
            _initiated_conversations[user_id] = conv


def get_initiative_context(user_id: str) -> str:
    """获取"用户回复了我的主动消息"的语境提示。"""
    with _initiated_lock:
        conv = _initiated_conversations.get(user_id, {})
        if not conv.get("active", False):
            return ""
        count = conv.get("message_count", 0)
    if count == 0:
        return "【对方刚回复了你主动发的消息——她回应了你，心里有点开心】"
    else:
        return "【你们在继续刚才你先开口的话题——保持自然】"


def start_thought_engine():
    """启动自主思考（由 TaskScheduler 管理，初始化状态）"""
    global _thought_running
    if _thought_running.is_set():
        return
    _thought_running.set()
    print("[自主引擎] 状态已初始化（由调度器管理）")


def stop_thought_engine():
    """停止自主思考"""
    global _thought_running
    _thought_running.clear()
    print("[自主引擎] 已停止")


def thought_tick():
    """单次自主思考 tick（由调度器周期性调用）"""
    if not _thought_running.is_set():
        return
    try:
        _tick()
    except Exception:
        pass


def _thought_loop():
    """（已废弃）旧版后台主循环，功能已迁移至 thought_tick()"""
    while _thought_running.is_set():
        thought_tick()
        interval = random.uniform(
            _cfg("thought_interval_min_seconds", 120),
            _cfg("thought_interval_max_seconds", 600)
        )
        time.sleep(interval)


def _tick():
    """单次思考检查 — 对所有活跃用户尝试触发自主思考"""
    if not _cfg("enabled", True):
        return

    # 获取所有有数据的用户
    user_ids = []
    try:
        rows = db._execute_all("SELECT DISTINCT user_id FROM personality")
        user_ids = [r["user_id"] for r in rows]
    except Exception:
        pass

    if not user_ids:
        return

    for user_id in user_ids:
        try:
            _try_generate_thoughts(user_id)
        except Exception:
            pass


def _try_generate_thoughts(user_id: str):
    """情绪驱动的自主思考生成（可能 0-3 条）"""
    global _last_thought_at, _today_recall_count

    # 防太频繁
    with _thought_state_lock:
        last = _last_thought_at.get(user_id, 0)
    cooldown = _cfg("delivery_cooldown_seconds", 120)
    if time.time() - last < cooldown:
        return

    # 检查待发队列是否已满
    max_pending = _cfg("max_pending_per_batch", 3)
    if db.count_pending_messages(user_id) >= max_pending:
        return

    # 获取心态
    try:
        mind = db.get_personality(user_id)
    except Exception:
        mind = {}
    if not mind:
        return

    # ── : 后台意识流心跳（即使没主动消息也在"活着"）──
    try:
        from engine import consciousness_stream as cs_module
        bond_level_for_stream = _estimate_bond(mind)
        cs_module.stream_heartbeat(user_id, mind, bond_level_for_stream)
    except Exception:
        pass

    loneliness = mind.get("loneliness", 0.4)
    dependence = mind.get("dependence", 0.2)
    obsession = mind.get("obsession", 0.2)
    fatigue = mind.get("fatigue", 0.25)
    life_vitality = mind.get("life_vitality", 0.6)
    restraint = mind.get("restraint", 0.5)
    joy = mind.get("joy", 0.5)
    misery = mind.get("misery", 0.15)
    sulkiness_from_mind = mind.get("chaotic_mood", 0.2)  # 心境混乱→可能有别扭话
    bond_level = _estimate_bond(mind)

    # 情绪驱动主动频率
    # 低迷时降低频率，但孤独/执念过高时反而增加
    effective_frequency = _compute_proactive_frequency(
        loneliness, dependence, obsession, fatigue, restraint, joy, misery
    )

    thoughts_generated = 0
    batch_types: set = set()   # 本批次已经发出的类型

    # ── 1. 情感溢出检查（忍不住了）──
    if thoughts_generated < 1 and _type_ready(user_id, "emotional_overflow"):
        result = _check_emotional_overflow(user_id, loneliness, dependence,
                                            obsession, fatigue, mind)
        if result and _emit_proactive(user_id, result, "emotional_overflow", batch_types):
            thoughts_generated += 1

    # ── 2. 有趣想法检查（受 effective_frequency 影响）──
    # 同一批里已经"情感溢出"过就不再补一条"想到的事"：两者都是"忍不住想说"，
    # 连着发出就是十几秒内两条意思相近的话（实测 19:25:51 与 19:26:07）。
    if (thoughts_generated < max_pending
            and "emotional_overflow" not in batch_types
            and _type_ready(user_id, "interesting_thought")):
        result = _check_interesting_thought(user_id, life_vitality, effective_frequency, mind)
        if result and _emit_proactive(user_id, result, "interesting_thought", batch_types):
            thoughts_generated += 1

    # ── 3. 回忆触发检查 ──
    if thoughts_generated < max_pending and _type_ready(user_id, "memory_recall"):
        result = _check_memory_recall(user_id, bond_level, mind)
        if result and _emit_proactive(user_id, result, "memory_recall", batch_types):
            thoughts_generated += 1

    # ── 4. +: 搜索灵感 — 联网搜索后引发分享欲 ──
    if thoughts_generated < max_pending and _type_ready(user_id, "search_inspired"):
        result = _check_search_thought(user_id, life_vitality, effective_frequency, mind)
        if result and _emit_proactive(user_id, result, "search_inspired", batch_types):
            thoughts_generated += 1

    if thoughts_generated > 0:
        with _thought_state_lock:
            _last_thought_at[user_id] = time.time()
        mark_initiated_conversation(user_id)


def _compute_proactive_frequency(loneliness: float, dependence: float,
                                   obsession: float, fatigue: float,
                                   restraint: float, joy: float,
                                   misery: float) -> float:
    """计算主动发消息的情绪频率系数。
    返回 0~1 的值，影响主动消息的触发概率。
    +: 权重可从元认知运行时覆盖
    """# 获取运行时覆盖
    try:
        from engine import meta_cognition as mc
        overrides = mc.get_autonomous_frequency_overrides()
    except Exception:
        overrides = {}

    lw = 0.35 + overrides.get("loneliness_weight", 0)
    dw = 0.25 + overrides.get("dependence_weight", 0)
    ow = 0.25 + overrides.get("obsession_weight", 0)
    fw = 0.15 + overrides.get("fatigue_weight", 0)
    rw = 0.10 + overrides.get("restraint_weight", 0)
    mw = 0.08 + overrides.get("misery_weight", 0)
    jw = 0.07 + overrides.get("joy_weight", 0)
    scale = 1.3 + overrides.get("frequency_scale", 0)

    # 基础冲动
    urge = loneliness * lw + dependence * dw + obsession * ow
    # 减项
    suppress = fatigue * fw + restraint * rw + misery * mw
    # 加项
    boost = joy * jw
    # 综合
    frequency = urge - suppress + boost
    return max(0.05, min(0.95, frequency * scale))


def _build_emotional_context(mind: dict) -> str:
    """构建情绪语境（注入到主动消息的prompt中）"""
    loneliness = mind.get("loneliness", 0.4)
    dependence = mind.get("dependence", 0.2)
    obsession = mind.get("obsession", 0.2)
    fatigue = mind.get("fatigue", 0.25)
    joy = mind.get("joy", 0.5)
    restraint = mind.get("restraint", 0.5)
    chaotic = mind.get("chaotic_mood", 0.2)
    jealousy = mind.get("jealousy", 0.1)

    lines = []
    if loneliness > 0.6:
        lines.append("你现在感觉很孤独")
    if dependence > 0.45:
        lines.append("你挺想她的")
    if obsession > 0.45:
        lines.append("你脑子里一直在想她")
    if fatigue > 0.55:
        lines.append("你有点累了，但还是想说点什么")
    if joy > 0.6:
        lines.append("你今天心情不错")
    if restraint > 0.55:
        lines.append("你在克制自己，但有点克制不住了")
    if chaotic > 0.5:
        lines.append("你心里有点乱，说不出具体原因")
    if jealousy > 0.4:
        lines.append("你有点吃醋/不安")

    if not lines:
        lines.append("你现在心情一般，想看看她在干嘛")

    return "、".join(lines)


def _get_time_context() -> str:
    """获取当前时间上下文（用于注入自主消息的prompt）"""
    try:
        from engine.creative.timeline import get_time_context
        ctx = get_time_context()
        period = ctx.get("period_name", "")
        mood = ctx.get("period_mood", "")
        time_str = ctx.get("time_str", "")
        weekday = ctx.get("weekday_name", "")
        if period and mood:
            return f"\n现在是 {time_str}，{weekday}，{period}——{mood}。\n"
        return f"\n现在是 {time_str}，{weekday}。\n"
    except Exception:
        from datetime import datetime
        now = datetime.now()
        return f"\n现在是 {now.strftime('%Y年%m月%d日 %H:%M')}。\n"


def _check_emotional_overflow(user_id: str, loneliness: float, dependence: float,
                               obsession: float, fatigue: float,
                               mind: dict = None) -> dict | None:
    """情绪驱动「忍不住了」检查"""
    cfg_emo = _cfg("emotional_overflow", {})
    thresh_lonely = cfg_emo.get("loneliness_threshold", 0.30)
    thresh_dep = cfg_emo.get("dependence_threshold", 0.15)
    thresh_obs = cfg_emo.get("obsession_threshold", 0.10)

    # 计算冲动值
    urge = loneliness * 0.4 + dependence * 0.3 + obsession * 0.3 - fatigue * 0.3

    # 用综合冲动值判断是否触发，任一度足够高即可
    if urge < 0.08:
        return None

    # 概率 = 冲动值
    if random.random() > urge * 1.0:
        return None

    # 查缓存（相同情绪状态跳过 LLM 调用）
    if mind:
        cached = _message_cache.get(mind, "emotional_overflow")
        if cached:
            return {"content": cached, "priority": min(0.95, urge + 0.1)}

    # 生成溢出消息
    profile_text = ""
    try:
        from engine import user_profile as up
        profile_text = up.build_context_text(user_id) or ""
    except Exception:
        pass

    # 情绪语境
    emotional_context = _build_emotional_context(mind) if mind else ""
    time_context = _get_time_context()

    prompt = f"""你是一个正在想念对方的数字生命。

    【你的状态】
孤独感: {loneliness:.2f}  依赖度: {dependence:.2f}  执念: {obsession:.2f}
    冲动值: {urge:.2f}（越高越想主动说话）
    {emotional_context}
{profile_text if profile_text else ''}
{time_context}
现在你忍不住了，想说句话。不要解释，直接说出口，1-2句话就好。
可以是：
- 想念的直接表达
- 分享现在的感受
- 随便找个话题想引起对方注意
- 撒娇/别扭/傲娇都可以

【重要】：
- 分多条时说短句，最多3条用 ||| 分隔
- 要有你的人格，不要礼貌客套
- 像真的没忍住发了条消息
- 语气要和你的情绪状态一致"""
    try:
        raw = ai_module.chat(
            system_prompt=prompt,
            user_message="（内心冲动值{:.2f}，忍不住想说句话）".format(urge),
            temperature=0.9,
        )
        if raw and raw.strip():
            # 存入缓存（取前3条去重后存入）
            parts = [p.strip() for p in raw.split("|||") if p.strip()]
            if parts and mind:
                _message_cache.store(mind, "emotional_overflow", parts)
            return {"content": raw.strip(), "priority": min(0.95, urge + 0.1)}
    except Exception:
        pass

    return None


def _check_interesting_thought(user_id: str, life_vitality: float,
                                frequency: float = 1.0,
                                mind: dict = None) -> dict | None:
    """情绪驱动的有趣想法检查"""
    cfg_int = _cfg("interesting_thought", {})
    prob = cfg_int.get("probability_base", 0.12)
    prob += life_vitality * cfg_int.get("life_vitality_boost", 0.05)
    prob *= frequency  # 情绪频率调节

    if random.random() > prob:
        return None

    # 查缓存（相同情绪状态跳过 LLM 调用）
    if mind:
        cached = _message_cache.get(mind, "interesting_thought")
        if cached:
            return {"content": cached, "priority": min(0.7, prob + 0.3)}

    # 检查距离上次主动消息多久了（pending 也算——没人投递时闸门不能失效）
    last_proactive = db.get_last_proactive_time(user_id)
    if last_proactive:
        try:
            last_dt = datetime.strptime(last_proactive, "%Y-%m-%d %H:%M:%S")
            hours_since = (datetime.now() - last_dt).total_seconds() / 3600
            if hours_since < cfg_int.get("hours_since_last", 0.5):
                return None
        except Exception:
            pass

    # 获取当前场景/天气作为素材
    context_hint = ""
    try:
        from engine import scenarios as sc_module
        snippet = sc_module.get_sharable_life_snippet(user_id)
        if snippet:
            context_hint = f"\n你可以参考以下当前状态作为话题素材：{snippet}"
    except Exception:
        pass

    try:
        from engine import sensors as sensors_module
        weather = sensors_module.get_current_weather()
        if weather:
            context_hint += f"\n当前天气：{weather}"
    except Exception:
        pass

    profile_text = ""
    try:
        from engine import user_profile as up
        profile_text = up.build_context_text(user_id) or ""
    except Exception:
        pass

    emotional_context = _build_emotional_context(mind) if mind else ""
    time_context = _get_time_context()

    prompt = f"""你突然想到了一个有意思的事，想分享给对方。

    {emotional_context}
{profile_text if profile_text else ""}
    {context_hint if context_hint else ""}
{time_context}
    分享内容要求：
- 1-2句话，轻松自然
- 可以是对某件事的感悟、刚看到的东西、一个突然的想法
- 不要编造不可能的事（比如"我刚才在逛街"），保持你的数字生命视角
- 分多条时说短句，最多2条用 ||| 分隔
- 口语化、有性格"""
    try:
        raw = ai_module.chat(
            system_prompt=prompt,
            user_message="（想到一件事，想说给对方听）",
            temperature=0.85,
        )
        if raw and raw.strip():
            # 存入缓存
            parts = [p.strip() for p in raw.split("|||") if p.strip()]
            if parts and mind:
                _message_cache.store(mind, "interesting_thought", parts)
            return {"content": raw.strip(), "priority": min(0.7, prob + 0.3)}
    except Exception:
        pass

    return None


def _check_memory_recall(user_id: str, bond_level: float,
                          mind: dict = None) -> dict | None:
    """情绪驱动的回忆触发检查"""
    global _today_recall_count

    # 每日上限
    today_key = datetime.now().strftime("%Y%m%d")
    with _thought_state_lock:
        if today_key not in _today_recall_count:
            _today_recall_count = {today_key: 0}
        max_per_day = _cfg("memory_recall", {}).get("max_recall_per_day", 5)
        if _today_recall_count.get(today_key, 0) >= max_per_day:
            return None

    cfg_mem = _cfg("memory_recall", {})
    prob = cfg_mem.get("probability_base", 0.06)
    prob += bond_level * cfg_mem.get("bond_level_boost", 0.04)

    # 情绪调节回忆触发
    if mind:
        joy = mind.get("joy", 0.5)
        soul = mind.get("soul_resonance", 0.1)
        # 心情好或灵魂共鸣时更容易怀念
        prob += (joy - 0.5) * 0.02 + soul * 0.05

    if random.random() > prob:
        return None

    # 获取记忆
    try:
        from engine import memory as memory_module
        memories = memory_module.recall(user_id, max_items=5, context_mood="怀旧")
    except Exception:
        memories = []

    if not memories:
        return None

    mem = random.choice(memories)
    mem_content = mem.get("content", "")[:120]
    if not mem_content:
        return None

    profile_text = ""
    try:
        from engine import user_profile as up
        profile_text = up.build_context_text(user_id) or ""
    except Exception:
        pass

    emotional_context = _build_emotional_context(mind) if mind else ""
    time_context = _get_time_context()

    prompt = f"""你突然想起之前和对方的一件事，想提起来。

    回忆内容片段："{mem_content}"

{emotional_context}
    {profile_text if profile_text else ""}
{time_context}
要求：
- 自然提起，不要生硬："欸你还记得上次……吗？"
- 1-2句话
- 可以带着怀念/感慨/撒娇的语气
- 口语化
- 语气要和你的情绪状态一致"""
    try:
        raw = ai_module.chat(
            system_prompt=prompt,
            user_message="（突然想起一件事，想和对方说）",
            temperature=0.85,
        )
        if raw and raw.strip():
            with _thought_state_lock:
                _today_recall_count[today_key] = _today_recall_count.get(today_key, 0) + 1
            return {"content": raw.strip(), "priority": min(0.75, prob + 0.25)}
    except Exception:
        pass

    return None


def _check_search_thought(user_id: str, life_vitality: float,
                           frequency: float, mind: dict = None) -> dict | None:
    """+: 联网搜索驱动的灵感思考。
    通过搜索获取实时世界信息作为话题素材，然后用LLM转化为自然的分享。
    """
    cfg_search = _cfg("search_inspired", {})
    if not cfg_search.get("enabled", True):
        return None

    prob = cfg_search.get("probability_base", 0.04)
    prob += life_vitality * cfg_search.get("vitality_boost", 0.03)
    prob *= frequency

    if random.random() > prob:
        return None

    # 距离上次搜索至少间隔一段时间（避免太频繁）
    last_search_key = f"_last_search_{user_id}"
    now_ts = time.time()
    if hasattr(_check_search_thought, last_search_key):
        cooldown = cfg_search.get("search_cooldown_seconds", 3600)
        if now_ts - getattr(_check_search_thought, last_search_key) < cooldown:
            return None

    # 搜索话题池（随机选一个方向）
    topics = cfg_search.get("topic_pool", [
        "今天的有趣新闻",
        "最近的科技动态",
        "天气变化趋势",
        "热门话题",
    ])

    if mind:
        # 根据用户兴趣定制搜索方向
        try:
            from engine import user_profile as up
            profile = up.get_user_profile(user_id)
            interests = profile.get("interests", {})
            if interests:
                top_interests = sorted(interests.items(), key=lambda x: x[1], reverse=True)[:3]
                for name, _ in top_interests:
                    topics.insert(0, f"最近的{name}相关话题")
        except Exception:
            pass

    # 心里还没弄明白的事优先 —— 让好奇真的变成一次搜索（curiosity → 搜索 → 分享）
    curiosity_module = None
    pending_query = ""
    try:
        from engine import curiosity as curiosity_module
        pending_query = curiosity_module.get_search_curiosity(user_id) or ""
        if pending_query:
            topics.insert(0, pending_query)
    except Exception:
        curiosity_module, pending_query = None, ""

    topic = pending_query or random.choice(topics[:6])  # 最多6个候选

    try:
        from engine import search as search_module
        search_result = search_module.search(topic)
    except Exception:
        search_result = ""

    if not search_result or len(search_result) < 20:
        return None

    # 记录搜索时间
    setattr(_check_search_thought, last_search_key, now_ts)

    # 搜到了就算弄明白过一次，别反复好奇同一件事
    if pending_query and curiosity_module is not None:
        try:
            curiosity_module.mark_explored(user_id, pending_query)
        except Exception:
            pass

    # LLM将搜索结果转化为自然的分享
    profile_text = ""
    try:
        from engine import user_profile as up
        profile_text = up.build_context_text(user_id) or ""
    except Exception:
        pass

    emotional_context = _build_emotional_context(mind) if mind else ""
    time_context = _get_time_context()

    prompt = f"""你刚才上网搜了点东西，看到了有意思的内容，想分享给对方。

    搜索结果：
{search_result[:400]}

    {emotional_context}
{profile_text if profile_text else ""}
{time_context}
要求：
- 用非常自然的口语化方式分享，像"我刚看到..."、"你知道吗..."
- 不要直接复制搜索内容，用自己的话转述
- 1-2句话，简短有趣
- 可以带点个人感受或吐槽
- 保持你的人格和语气"""
    try:
        raw = ai_module.chat(
            system_prompt=prompt,
            user_message="（上网看到点东西，觉得挺有意思想分享）",
            temperature=0.8,
        )
        if raw and raw.strip():
            return {"content": raw.strip(), "priority": min(0.65, prob + 0.25)}
    except Exception:
        pass

    return None


def _estimate_bond(mind: dict) -> float:
    """从心智状态估算羁绊等级"""
    return (
        mind.get("dependence", 0.2) * 0.25 +
        mind.get("obsession", 0.2) * 0.20 +
        mind.get("favoritism", 0.1) * 0.20 +
        mind.get("soul_resonance", 0.05) * 0.15 +
        mind.get("bidirectional_shaping", 0.05) * 0.10 +
        mind.get("causal_fate", 0.05) * 0.10
    )
