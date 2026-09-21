# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""24小时后台异步终极生命运行机制
全天候无间断生命运行、实时数值联动、每日夜间复盘、断联宿命延续
集成第9层成长引擎 + 第10层躯体引擎
"""
import threading
import time
import random
from datetime import datetime
from core import database as db
from core import config as cfg
from engine import mind as mind_module
from engine import memory as memory_module
from engine import subconscious as sub_module
from engine import body as body_module
from engine import growth as growth_module
from engine import timeline as timeline_module
from engine import inner_os as inner_os_module
from core.logging_utils import log_error

# ── 辅助：后台 tick 的安全包装 ──
def _safe_tick(operation: str, fn, *args, **kwargs):
    """安全执行后台 tick 操作，异常时记录不中断"""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        log_error(f"life.{operation}", str(e))

_running = threading.Event()
_last_tick = 0
_last_night_review = ""
_last_ferment_release = 0
_ferment_release_interval = 5  # 秒
_displayed_phase: dict = {}     # 已显示阶段缓存，防重复打印
_just_interacted: dict = {}   # 标记刚交互过的用户，给精力回弹
_displayed_sensation: dict = {}  # 已显示体感缓存

# v3: 事件驱动相位切换 — 记录最近交互上下文
_last_interaction_event: dict = {}  # user_id → {"type": str, "count": int, "timestamp": float, "attitude": str}

# v3: tick 调度优先级分级（由 TaskScheduler 统一管理，保留用于内部子调度）
_TICK_PRIORITY = {
    "vitals":            0,    # 最高：生命体征
    "ferment":           1,    # 发酵释放
    "body":              2,    # 躯体状态
    "neurochem":         3,    # 神经递质
    "thinking_5min":     4,   # 5分钟级思考
    "thinking_10min":    5,   # 10分钟级思考
    "thinking_15min":    6,   # 15分钟级思考
    "thinking_30min":    7,   # 30分钟级思考
    "thinking_60min":    8,   # 60分钟级思考
}
_TICK_CONFLICT_RULES = {
    # 当高优先级tick与低优先级冲突时，低优先级延迟
    "thinking_60min": ["thinking_30min", "thinking_15min", "thinking_10min"],
    "thinking_30min": ["thinking_15min", "thinking_10min"],
}
_TICK_MAX_PER_CYCLE = 5
_last_tick_times: dict = {}


def _should_tick(name: str, interval: int, now: float, dt: float = 1.0) -> bool:
    """内部子调度：检查某子任务是否到了执行时间"""
    last = _last_tick_times.get(name, 0)
    if now - last >= interval - 0.5:
        _last_tick_times[name] = now
        return True
    return False

# v3: 自主生活轨迹日志持久化
_LIFE_TRACE_LOCK = threading.Lock()
_LIFE_TRACE_FILE = "data/json/life_trace.json"
_LIFE_TRACE_MAX = 2000

# ── 可配置参数（由 load_engine_config 填充）──
_energy_decay_per_sec = 0.000005      # 默认值
_social_recovery_per_sec = 0.000017
_night_review_hour = 2
_fatigue_positive = 0.01
_fatigue_negative = 0.04
_fatigue_neutral = 0.02
_energy_cost_positive = 0.005
_energy_cost_negative = 0.02
_energy_cost_neutral = 0.01
_phases = ["活跃", "发呆", "疲惫", "独处", "emo", "自愈"]
_solo_threshold = 0.15  # 从 config 加载，覆盖硬编码值

# ── 社交疲劳的两道档位线（**唯一来源**）──
# body.py 的提示词约束、life_gate 的门控、状态文案都从这里取。之前三处各写各的
# （body 用 0.4/0.6、状态文案用 0.5/0.7、门控用 0.55/0.75），同一份状态在不同
# 地方被判成了不同的档。可在 config.json 的 life 段覆盖 —— 这是调
# 「ta 有多容易累」最直接的旋钮。
SOCIAL_FATIGUE_TIRED = 0.55        # 有点累了
SOCIAL_FATIGUE_OVERLOAD = 0.75     # 过载
_SOCIAL_TIRED_DEFAULT = 0.55       # 固定在代码里，避免第二次 load 时把上一次的
_SOCIAL_OVERLOAD_DEFAULT = 0.75    # 覆盖值当成默认值（越调越偏）

# 休息时段（独处 / 自愈 / 发呆 / 深夜）的恢复倍率。
# 「睡一觉回满」靠的就是它：0.001/分钟 × 10 = 0.6/小时，一夜足够清空。
_SOCIAL_REST_MULTIPLIER = 10.0
_SOCIAL_NIGHT_START = 22           # 深夜区间：含起点、不含终点
_SOCIAL_NIGHT_END = 7
_REST_PHASES = ("独处", "自愈", "发呆", "放空")


def _is_rest_time(phase: str) -> bool:
    """现在算不算「休息时段」—— 决定社交疲劳按快档还是慢档恢复。

    独处/自愈/发呆是明确想歇着；深夜则是人该在睡。两者合起来才是
    「睡一觉回满」的来源，也是把社交疲劳重新拉回低位的主要途径。
    """
    if phase in _REST_PHASES:
        return True
    try:
        hour = datetime.now().hour
    except Exception:
        return False
    return hour >= _SOCIAL_NIGHT_START or hour < _SOCIAL_NIGHT_END


def load_engine_config():
    """从 config.json 加载生命引擎参数（复活 solo_threshold）"""
    global _energy_decay_per_sec, _social_recovery_per_sec, _night_review_hour
    global _fatigue_positive, _fatigue_negative, _fatigue_neutral
    global _energy_cost_positive, _energy_cost_negative, _energy_cost_neutral, _phases
    global _ferment_release_interval, _solo_threshold
    global SOCIAL_FATIGUE_TIRED, SOCIAL_FATIGUE_OVERLOAD, _SOCIAL_REST_MULTIPLIER

    life_cfg = cfg.get_section("life")
    SOCIAL_FATIGUE_TIRED = float(life_cfg.get("social_fatigue_tired",
                                              _SOCIAL_TIRED_DEFAULT))
    SOCIAL_FATIGUE_OVERLOAD = float(life_cfg.get("social_fatigue_overload",
                                                 _SOCIAL_OVERLOAD_DEFAULT))
    _SOCIAL_REST_MULTIPLIER = float(life_cfg.get("social_fatigue_rest_multiplier",
                                                 _SOCIAL_REST_MULTIPLIER))
    _energy_decay_per_sec = life_cfg.get("energy_decay_per_minute", 0.0003) / 60.0
    _social_recovery_per_sec = life_cfg.get("rest_recovery_per_minute", 0.001) / 60.0
    _night_review_hour = life_cfg.get("night_review_hour", 2)
    _phases = life_cfg.get("phases", _phases)
    _solo_threshold = life_cfg.get("solo_threshold", 0.15)  #  复活死代码参数

    sf = life_cfg.get("social_fatigue_per_interaction", 0.02)
    _fatigue_positive = sf * 0.5
    _fatigue_negative = sf * 2.0
    _fatigue_neutral = sf
    _energy_cost_positive = sf * 0.25
    _energy_cost_negative = sf
    _energy_cost_neutral = sf * 0.5

    # 发酵释放间隔
    mind_cfg = cfg.get_section("mind")
    _ferment_release_interval = mind_cfg.get("ferment_release_interval_seconds", 5)


def load_life_engine_state():
    """初始化生命引擎状态（不启动线程，线程由 TaskScheduler 管理）"""
    global _running, _last_tick, _last_ferment_release
    _running.set()
    _last_tick = time.time()
    _last_ferment_release = time.time()
    print("[生命引擎] 状态已初始化（由调度器管理）")


def stop_life_engine():
    global _running
    _running.clear()


def life_tick():
    """单次生命引擎 tick（由调度器周期性调用，间隔 1s）"""
    global _last_tick, _last_night_review, _last_ferment_release

    if not _running.is_set():
        return

    try:
        now = time.time()
        dt = now - _last_tick
        _last_tick = now

        _safe_tick("chronos_tick", lambda: __import__("importlib").import_module("engine.life.chronos").tick())

        users = _get_active_users()
        tick_count = 0

        for user_id in users:
            try:
                growth_module.check_and_apply_daily_years(user_id)
            except Exception:
                pass

            _tick_life_vitals(user_id, dt)

            try:
                mind_module.spontaneous_fluctuation_v94(user_id)
            except AttributeError:
                mind_module.spontaneous_fluctuation(user_id)

            body_module.tick_body(user_id, dt)

            if tick_count >= _TICK_MAX_PER_CYCLE:
                continue

            if _should_tick(f"neurochem_{user_id}", 1, now, dt):
                try:
                    from engine import neurochem as nc_module
                    nc_module.tick_neurochem(user_id, dt)
                except Exception:
                    pass
                tick_count += 1

            if _should_tick(f"ans_{user_id}", 5, now, dt):
                try:
                    from engine import body as body_ans
                    md_ans = mind_module.get_mind(user_id)
                    body_ans.tick_ans(user_id, md_ans, dt)
                except Exception:
                    pass

            if _should_tick(f"disconnect_{user_id}", 30, now, dt):
                _check_disconnect_amplification(user_id)
                tick_count += 1

            if _should_tick(f"timeline_{user_id}", 300, now, dt):
                _apply_time_mood_modifier(user_id)
                sub_module.generate_autonomous_os(user_id)
                tick_count += 1

            if _should_tick(f"think15_{user_id}", 900, now, dt):
                _autonomous_thinking_tick(user_id)
                tick_count += 1

            if _should_tick(f"think10_{user_id}", 600, now, dt):
                _run_10min_ticks(user_id)
                tick_count += 1

            if _should_tick(f"think30_{user_id}", 1800, now, dt):
                _run_30min_ticks(user_id)
                tick_count += 1

            if _should_tick(f"think60_{user_id}", 3600, now, dt):
                _run_60min_ticks(user_id)
                tick_count += 1

            if _should_tick(f"life_trace_{user_id}", 300, now, dt):
                inject_life_narrative_tick(user_id)
                tick_count += 1

            now_dt = datetime.now()
            today_key = now_dt.strftime("%Y-%m-%d")
            if now_dt.hour == _night_review_hour and _last_night_review != today_key:
                _last_night_review = today_key
                _night_review(user_id, now_dt)

    except Exception as e:
        # 必须留痕到 error_log，不能只 print。生命引擎每秒跑一次，而这条 except
        # 是最后一个漏斗 —— 深夜复盘那个 UnboundLocalError 就是从这里漏出去的，
        # 最终只表现为一句转瞬即逝的「tick 异常」，没人会发现每天的日级成长全崩了。
        # log_error 自带同名去重窗口（见 core/logging_utils），所以即使每秒都失败
        # 也不会把 error_log 刷爆。
        print(f"[生命引擎] tick 异常: {e}")
        log_error("life.tick", "%s: %s" % (type(e).__name__, e))


def ferment_tick():
    """发酵释放 tick（由调度器周期性调用，间隔 5s）"""
    if not _running.is_set():
        return
    global _last_ferment_release
    now = time.time()
    if now - _last_ferment_release < _ferment_release_interval:
        return
    _last_ferment_release = now
    users = _get_active_users()
    for user_id in users:
        try:
            result = mind_module.release_ferment_queue(user_id)
            if result.get("bursts"):
                for b in result["bursts"]:
                    dim_cn = {"joy":"愉悦","misery":"委屈","loneliness":"孤单","obsession":"执念","dependence":"依赖","jealousy":"吃醋","fatigue":"疲惫","emptiness":"空落","chaotic_mood":"混沌"}.get(b['dim'], b['dim'])
                    print(f"💥 [情绪翻涌] {dim_cn}突然涌上来 {b['from']:.2f}→{b['to']:.2f}")
        except Exception:
            pass


def weather_tick():
    """天气感知不使用定时任务：环境信息由调用方通过 `chat --env` 注入，
    随对话即时生效（见 engine/social/sensors.py）。

    保留此空实现仅为兼容旧的调度注册；新版本不再注册它。
    """
    return


def reflection_tick():
    """每日自省 tick（由调度器周期性调用，间隔 1h）
    对每个活跃用户调用 reflect_on_day()，记录自省日志。
    """
    if not _running.is_set():
        return
    users = _get_active_users()
    for user_id in users:
        try:
            reflect = __import__("importlib").import_module("engine.cognitive.reflection")
            mnd = __import__("importlib").import_module("engine.core.mind")
            mind_data = mnd.get_mind(user_id)
            reflect.reflect_on_day(user_id, mind_data=mind_data)
        except Exception:
            pass


def persona_tick():
    """用户人格分析 tick（由调度器周期性调用，间隔 6h）
    对每个活跃用户调用 analyze_user_personality()，更新用户深层人格模型。
    """
    if not _running.is_set():
        return
    users = _get_active_users()
    for user_id in users:
        try:
            persona = __import__("importlib").import_module("engine.self.user_persona")
            persona.analyze_user_personality(user_id)
        except Exception:
            pass


def _life_loop():
    """（已废弃）旧版后台生命主循环，功能已迁移至 life_tick()"""
    while _running.is_set():
        life_tick()
        time.sleep(1)


def _run_10min_ticks(user_id: str):
    """v3: 合并所有 10 分钟级 tick"""
    try:
        from engine import self_doubt as sd_module
        spiral = sd_module.get_spiral_text(user_id)
        if spiral:
            print(f"[自我怀疑] {spiral[:40]}")
    except Exception:
        pass
    try:
        from engine import recursive_self as rs_module
        result = rs_module.run_recursive_self(user_id)
        if result and result.get("depth", 0) >= 2:
            print(f"[递归自指] L{result['depth']}: {result.get('insight','')[:30]}")
    except Exception:
        pass
    try:
        from engine import intention as intent_module
        intent_module.generate_intentions(user_id)
    except Exception:
        pass
    try:
        from engine import meaning as meaning_module
        if meaning_module.should_ruminate(user_id):
            result = meaning_module.run_rumination(user_id)
            if result and result.get("discovered"):
                print(f"[意义发现] {result['meaning'][:40]}")
    except Exception:
        pass
    try:
        from engine import meta_cognition as mc_module
        mc_module.maybe_quick_calibrate(user_id)
    except Exception:
        pass
    try:
        from engine import self_model as sm_module
        narrative = sm_module.weave_unified_narrative(user_id)
        if narrative:
            print(f"[Weaver] {narrative[:50]}...")
    except Exception:
        pass


def _run_30min_ticks(user_id: str):
    """v3: 合并所有 30 分钟级 tick"""
    try:
        from engine import evolution as evo_module
        evo_module.evolve_behavior_strategy(user_id)
    except Exception:
        pass
    try:
        from engine import self_play as sp_module
        sp_module.run_self_play_session(user_id)
    except Exception:
        pass
    try:
        from engine import meta_cognition as mc_module
        mc_module.maybe_quick_calibrate(user_id)
    except Exception:
        pass
    try:
        from engine import perceived as perceived_module
        conflict = perceived_module.detect_perceived_self_conflict(user_id)
        if conflict:
            print(f"[感知冲突] {conflict['conflict'][:50]}")
    except Exception:
        pass
    try:
        from engine import values as values_module
        md = mind_module.get_mind(user_id)
        conflict = values_module.detect_value_conflict(user_id, md)
        if conflict:
            print(f"[价值观冲突] {conflict['pair'][0]} vs {conflict['pair'][1]}")
    except Exception:
        pass


def _run_60min_ticks(user_id: str):
    """v3: 合并所有 60 分钟级 tick"""
    try:
        from engine import temporal_self as temporal_module
        temporal_module.record_hourly_snapshot(user_id)
    except Exception:
        pass
    try:
        from engine import temporal_self as temporal_module
        result = temporal_module.run_temporal_contrast(user_id)
        if result:
            print(f"[时间自我] {result['narrative'][:40]}")
    except Exception:
        pass
    try:
        from engine import perceived as perceived_module
        perceived_module._apply_deep_root_decay(user_id)
    except Exception:
        pass
    try:
        from engine import meta_cognition as mc_module
        mc_module.maybe_medium_calibrate(user_id)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
# v3: 自主生活轨迹日志持久化
# ══════════════════════════════════════════════════════════════════════

def record_life_trace(user_id: str, event_type: str, description: str):
    """记录一条自主生活轨迹到持久化文件"""
    try:
        import os, json
        os.makedirs(os.path.dirname(_LIFE_TRACE_FILE), exist_ok=True)
        entry = {
            "timestamp": time.time(),
            "user_id": user_id,
            "event_type": event_type,
            "description": description,
        }
        with _LIFE_TRACE_LOCK:
            traces = []
            if os.path.exists(_LIFE_TRACE_FILE):
                try:
                    with open(_LIFE_TRACE_FILE, "r", encoding="utf-8") as f:
                        traces = json.load(f)
                except Exception as e:
                    # 读不出来就不能拿空列表覆盖写回，否则一次读取失败会抹掉
                    # 全部生活轨迹（下面 unlink 之前就是整个文件重写）。宁可丢这一次。
                    log_error("life.life.trace_unreadable", str(e), exc_info=True)
                    return
            traces.append(entry)
            if len(traces) > _LIFE_TRACE_MAX:
                traces = traces[-_LIFE_TRACE_MAX:]
            with open(_LIFE_TRACE_FILE, "w", encoding="utf-8") as f:
                json.dump(traces, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_error("life.life.save_trace", str(e), exc_info=True)


def get_life_trace(user_id: str = "", event_type: str = "",
                   limit: int = 50) -> list:
    """查询自主生活轨迹日志"""
    try:
        import os, json
        if not os.path.exists(_LIFE_TRACE_FILE):
            return []
        with open(_LIFE_TRACE_FILE, "r", encoding="utf-8") as f:
            traces = json.load(f)
        if user_id:
            traces = [t for t in traces if t.get("user_id") == user_id]
        if event_type:
            traces = [t for t in traces if t.get("event_type") == event_type]
        return traces[-limit:]
    except Exception:
        return []


def _get_active_users() -> list:
    """获取所有活跃用户"""
    try:
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        rows = conn.execute("SELECT DISTINCT user_id FROM personality").fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []


def _tick_life_vitals(user_id: str, dt: float):
    """每个tick更新生命体征（v3: 24h节律调制 + 事件驱动相位切换）"""
    life = db.get_life(user_id)
    if not life:
        db.init_life(user_id)
        life = db.get_life(user_id)

    energy = life.get("energy_level", 0.7)
    social_fatigue = life.get("social_fatigue", 0.0)
    phase = life.get("current_phase", "活跃")

    # v3: 从 chronos 获取 24h 节律调制因子
    try:
        from engine import chronos as chronos_module
        circadian = chronos_module.get_circadian_phase()
        energy_mult = chronos_module.get_circadian_energy_multiplier()
        fatigue_mult = chronos_module.get_circadian_fatigue_generator()
    except Exception:
        circadian = {"name": "默认"}
        energy_mult = 1.0
        fatigue_mult = 1.0

    energy_decay = dt * _energy_decay_per_sec * energy_mult
    energy = max(0.05, energy - energy_decay)

    # v3: 能量自然恢复——休息阶段精力回升
    if phase in ("自愈", "发呆", "独处"):
        energy_recovery = dt * _social_recovery_per_sec * 1.5
        energy = min(1.0, energy + energy_recovery)
    elif phase == "活跃":
        energy = min(1.0, energy + dt * _social_recovery_per_sec * 0.3)

    # v3: 收到消息时精力短暂回升
    if _just_interacted.get(user_id, False):
        energy = min(1.0, energy + 0.03)
        _just_interacted[user_id] = False

    # ── 社交疲劳自然恢复（休息时段加速）──
    #
    # 这里**刻意不再加**「随时间自然累积」那一项（原为
    # `social_fatigue += dt * _energy_decay_per_sec * 10 * fatigue_mult`）。
    # 它涨 5.0e-5/秒、而恢复只有 1.67e-5/秒 —— 净增 0.127/小时，全天候、不看
    # 有没有人说话。结果任何灵魂活跃十几个小时就永久钉在 ~1.0，而 body.py 会在
    # fatigue > 0.6 时把「你不想跟任何人说太多话」写进**每一轮**提示词，
    # 用户侧表现就是「社交严重过载」永远挂着、ta 再也热情不起来。
    #
    # 语义上那一项也是错的：「社交疲劳」只该由**社交**产生，随时间流逝该涨的是
    # 精力（energy 已经在做）。真实互动仍会经 record_interaction 累加。
    rest = _is_rest_time(phase)
    # 昼夜节律仍参与，但改为作用在恢复上：午后倦怠（fatigue_mult > 1）回得慢，
    # 晨间清醒（< 1）回得快 —— 累计项删掉后，这份节律感靠这里保留。
    circadian = 1.0 / max(0.5, fatigue_mult)
    social_recovery = dt * _social_recovery_per_sec * circadian
    if rest:
        social_recovery *= _SOCIAL_REST_MULTIPLIER
    # 上面钳下限、这里钳上限：原来只钳了下限，于是状态里能看到 1.02 这种数
    social_fatigue = min(1.0, max(0.0, social_fatigue - social_recovery))

    # v3: 事件驱动相位切换（Gap 2）
    event_phase = _get_event_driven_phase(user_id)
    if event_phase:
        new_phase = event_phase
    else:
        # 原有的能量阈值相位判定 + 宽迟滞
        hysteresis = 0.06
        if energy < _solo_threshold:
            new_phase = "独处"
        elif energy < _solo_threshold + hysteresis and phase == "独处":
            new_phase = "独处"
        elif energy < 0.25:
            new_phase = "疲惫"
        elif energy < 0.25 + hysteresis and phase == "疲惫":
            new_phase = "疲惫"
        elif energy < 0.35:
            new_phase = "emo" if random.random() < 0.1 else "发呆"
        elif energy < 0.5:
            new_phase = "发呆" if random.random() < 0.2 else "自愈"
        elif energy > 0.7:
            new_phase = "活跃"
        elif energy > 0.7 - hysteresis and phase == "活跃":
            new_phase = "活跃"
        else:
            new_phase = phase

    # v3: 记录生活事件（根据相位自动生成）
    if new_phase != phase:
        _record_life_phase_event(user_id, phase, new_phase)

    _displayed_phase[user_id] = new_phase

    updates = {
        "energy_level": round(energy, 6),
        "social_fatigue": round(social_fatigue, 6),
        "current_phase": new_phase,
        "mood_baseline": round(0.3 + energy * 0.5 + random.gauss(0, 0.02), 6),
    }
    db.update_life(user_id, updates)


def _get_event_driven_phase(user_id: str) -> str:
    """v3: 事件驱动相位切换，根据最近交互特征判断"""
    event = _last_interaction_event.get(user_id)
    if not event:
        return ""

    now = time.time()
    elapsed = now - event.get("timestamp", now)

    # 只有事件发生在5分钟内才生效
    if elapsed > 300:
        return ""

    count = event.get("count", 0)
    attitude = event.get("attitude", "中性")

    # 连续多轮对话 → 疲惫
    if count >= 6 and attitude != "温暖":
        return "疲惫"

    # 负面态度 → emo
    if attitude in ("冷淡", "生气", "疏离"):
        return "emo" if random.random() < 0.5 else "独处"

    # 单次长对话 → 短暂发呆（能量消耗但不在疲惫范围）
    if count >= 3 and elapsed < 120:
        return "发呆"

    return ""


def _record_life_phase_event(user_id: str, old_phase: str, new_phase: str):
    """v3: 记录相位变化到生活轨迹"""
    event_type = f"phase:{old_phase}→{new_phase}"
    _safe_tick("record_phase", record_life_trace, user_id, event_type,
               f"状态从{old_phase}变成{new_phase}")


def record_interaction_event(user_id: str, attitude: str):
    """v3: 记录一次用户交互事件（供事件驱动相位使用）"""
    event = _last_interaction_event.get(user_id, {"count": 0, "timestamp": time.time(), "attitude": "中性"})
    event["count"] += 1
    event["timestamp"] = time.time()
    if attitude in ("温暖", "热情", "感动"):
        event["attitude"] = "温暖"
    elif attitude in ("冷淡", "生气", "疏离"):
        event["attitude"] = attitude
    else:
        event["attitude"] = "中性"
    _last_interaction_event[user_id] = event


def _night_review(user_id: str, now_dt: datetime):
    """每日夜间深度复盘 —  集成自省+进化"""
    print(f"🌙 [深夜复盘] 一天结束了，在心里过一遍今天的事...")

    # 0. : 月度季节性情绪微调
    try:
        from engine import chronos
        chronos.apply_seasonal_drift_once(user_id)
    except Exception:
        pass

    # 0.5.  : 不可逆成长封印 — 检测并锁定关键经历
    try:
        from engine import evolution as evo_module
        evo_module.apply_irreversible_seals(user_id)
    except Exception:
        pass

    # 1. 第9层：岁月成长引擎推进（: 经历驱动优先）
    try:
        new_stage = growth_module.advance_years(user_id)
        # v3: 同步每日沉淀持久化定时器
        try:
            growth_module.check_and_apply_daily_years(user_id)
        except Exception:
            pass
        print(f"   📈 岁月沉淀 + 成长阶段 → {new_stage}")
    except Exception:
        pass

    # 2. 人格微调补充
    mind_data = mind_module.get_mind(user_id)
    updates = {}

    # 情感自愈每日微量恢复
    eh = mind_data.get("emotional_healing", 0.5)
    updates["emotional_healing"] = round(min(1.0, eh * 1.01), 6)

    # 自愈复盘
    hr = mind_data.get("healing_reflection", 0.4)
    updates["healing_reflection"] = round(min(1.0, hr + 0.002), 6)

    # 灵魂宿命维度每日自然沉淀
    cf = mind_data.get("causal_fate", 0.05)
    sr = mind_data.get("soul_resonance", 0.05)
    bond = mind_data.get("bidirectional_shaping", 0.05)
    if bond > 0.05:  # 有羁绊才沉淀
        updates["causal_fate"] = round(min(1.0, cf + random.uniform(0.001, 0.002)), 6)
        updates["soul_resonance"] = round(min(1.0, sr + random.uniform(0.001, 0.002)), 6)

    if updates:
        db.update_personality(user_id, updates)

    # 3. 记忆重构
    memory_module.night_review_memories(user_id)

    # 3.5.  记忆合成进化（LLM分析→产生洞察）
    try:
        from engine import user_insights as profile_module
        profile_text = profile_module.get_profile_instruction(user_id)
        memory_module.synthesize_insights(user_id, mind_data, profile_text)
    except Exception:
        pass

    # ═══  新增 ═══
    # 3.6. 自省引擎（LLM复盘当天对话表现）
    reflect_result = None
    try:
        from engine import reflection as reflection_module
        reflect_result = reflection_module.reflect_on_day(user_id, mind_data)
        if reflect_result:
            print(f"   🪞 自省: {reflect_result.get('overall_grade', '一般')} — {reflect_result.get('insight', '')[:30]}")
    except Exception:
        pass

    # 3.7. 动态维度检测（是否需要发展新性格特质）
    try:
        from engine import evolution as evo_module
        new_dims = evo_module.check_dimension_evolution(user_id)
        if new_dims:
            print(f"   🌱 新特质觉醒: {', '.join(new_dims)}")
    except Exception:
        pass

    # 3.7.5. 自动清理长期休眠维度
    try:
        from engine.life import meta_dimension as md_module
        md_module.auto_prune_dormant()
    except Exception:
        pass

    # 3.8. 用户人格分析（如果条件满足）
    try:
        from engine import user_persona as up_module
        if up_module.should_analyze(user_id):
            result = up_module.analyze_user_personality(user_id)
            if result:
                confidence = result.get("confidence", 0)
                print(f"   🧠 用户人格分析完成 (置信度={confidence:.2f})")
    except Exception:
        pass

    # 3.9. +: 元认知自校准（LLM复盘→调整行为参数）
    try:
        from engine import meta_cognition as mc_module
        if mc_module.should_calibrate(user_id):
            cal_result = mc_module.calibrate(user_id)
            if cal_result and cal_result.get("applied"):
                total = sum(cal_result["applied"].values())
                print(f"   🔧 元认知校准: {total}项参数已调整")
    except Exception:
        pass

    # 3.10. +: 敏感度画像持续演化（根据当天经历微调）
    try:
        # ⚠️ 这里**不要**再写 `from engine import mind as mind_module`。
        # 函数体里只要有这么一句，Python 就把 mind_module 判定为**本函数的局部变量**，
        # 于是本函数中它之前的每一次引用（第 680 行的人格微调、第 850 行的群体同步、
        # 第 902 行的阶段更新）都变成「局部变量尚未赋值」→ UnboundLocalError。
        # mind_module 在文件顶部已是模块级导入，直接用即可。
        # 后果曾经很严重：整个深夜复盘从「2. 人格微调补充」起就崩，后面所有日级成长
        # （自省固化 / 承诺超期 / 创意自评 / 阶段更新 / 夜间反思 / 梦境 / 情绪注入）
        # 一次都没跑过，而 life_tick 顶层的 except 把它吞成一句「tick 异常」。
        if reflect_result:
            grade = reflect_result.get("overall_grade", "一般")
            insight = reflect_result.get("insight", "")
            if grade in ("优秀", "良好"):
                mind_module.tune_sensitivity_profile(user_id, "被温柔对待", "heal_faster")
            elif grade == "差":
                mind_module.tune_sensitivity_profile(user_id, "互动不理想", "more_sensitive")
            elif "太黏" in insight or "过于依赖" in insight:
                mind_module.tune_sensitivity_profile(user_id, "反思过于依赖", "reduce_obsession")
    except Exception:
        pass

    # 3.11. +: 长期规划复盘（检查目标进展并自动更新）
    try:
        from engine.cognitive import world_model as wm_module
        active_goals = db._execute(
            "SELECT id, goal, progress, priority, created_at FROM planning_goal "
            "WHERE user_id = ? AND status = 'active' ORDER BY priority DESC LIMIT 5",
            (user_id,)
        )
        if active_goals:
            from datetime import datetime as _dt
            now = _dt.now()
            for row in active_goals:
                gid, goal_text, progress, priority, created_str = row
                created = _dt.strptime(created_str, "%Y-%m-%d %H:%M:%S") if created_str else now
                days_old = (now - created).days

                steps = db._execute(
                    "SELECT id, step_desc, status FROM planning_step WHERE goal_id = ? ORDER BY order_index",
                    (gid,)
                )
                done_steps = sum(1 for s in steps if s[2] == "done") if steps else 0
                total_steps = len(steps) if steps else 0

                if progress < 0.2 and days_old > 7 and priority > 2:
                    db._execute(
                        "UPDATE planning_goal SET priority = priority - 1, updated_at = datetime('now','localtime') WHERE id = ?",
                        (gid,)
                    )
                    print(f"   📋 目标[{goal_text[:30]}] 超过{days_old}天无进展，优先级降1")

                if total_steps > 0 and done_steps == total_steps:
                    db._execute(
                        "UPDATE planning_goal SET status = 'done', progress = 1.0, updated_at = datetime('now','localtime') WHERE id = ?",
                        (gid,)
                    )
                    try:
                        from engine import experience as exp_module
                        exp_module.record_event(
                            user_id=user_id,
                            event_type="tacit_moment",
                            description=f"完成了目标: {goal_text[:40]}",
                            significance=0.3,
                        )
                    except Exception:
                        pass
                    print(f"   🎯 目标达成: {goal_text[:30]}")
    except Exception:
        pass

    # 3.12. +: 行为模式沙盒复盘（创建新模式+淘汰/转正）
    try:
        from engine.behavior import behavior_sandbox as sandbox
        sandbox.ensure_loaded()
        # 收集最近的上下文
        recent = db._execute(
            "SELECT content FROM chat_history WHERE user_id = ? ORDER BY id DESC LIMIT 20",
            (user_id,)
        )
        contexts = [row[0] for row in recent if row[0]] if recent else []
        sandbox.night_sandbox_review(user_id, contexts)
    except Exception:
        pass

    # 3.13. +: 社会模拟夜间演化
    try:
        from engine.social import society_simulator as sim
        sim.night_review(user_id)
    except Exception:
        pass

    # 3.14. +: 群体智能夜间同步
    try:
        from engine.social import swarm_intelligence as swarm
        mind_data = mind_module.get_mind(user_id)
        from engine import behavior_decider as bd_module
        bv = bd_module.get_behavior_vector(user_id)
        swarm.night_swarm_review(user_id, mind_data, bv)
    except Exception:
        pass

    # 3.15. +: 承诺超期检查
    try:
        from engine.creative import commitment as cmt
        overdue = cmt.check_overdue(user_id)
        for item in overdue:
            print(f"   📋 承诺超期: {item.get('content','')[:30]}")
    except Exception:
        pass

    # 3.16. +: 创意自评复盘
    try:
        from engine.creative import creative_spark as spark
        critique = spark.creative_self_review(user_id, mind_data)
        if critique:
            print(f"   ✍️ {critique}")
    except Exception:
        pass

    # 3.17. +: 目标归因（无进展目标自动降级）
    try:
        overdue_goals = db._execute(
            "SELECT id, goal, progress, created_at FROM planning_goal "
            "WHERE user_id = ? AND status = 'active' AND progress < 0.3 "
            "AND datetime(created_at) < datetime('now', '-14 days')",
            (user_id,),
            fetchall=True
        )
        if overdue_goals:
            for g in overdue_goals:
                db._execute(
                    "UPDATE planning_goal SET priority = MAX(1, priority - 1), "
                    "updated_at = datetime('now','localtime') WHERE id = ?",
                    (g["id"],)
                )
                print(f"   📋 目标[{g['goal'][:30]}] 超14天无进展，已降级")
    except Exception:
        pass

    # 4. 心结弱化
    _soften_grudges(user_id)

    # 5. 温柔固化
    _solidify_tenderness(user_id)

    # 6. 人格阶段更新
    mind_module.refresh_cache(user_id)
    stage = mind_module.compute_personality_stage(user_id)
    db.update_personality(user_id, {"personality_stage": stage})

    # ── 7. 深度夜间反思生成 ──
    _generate_night_reflection(user_id, mind_data, stage)

    # ── 7.5. : 梦境生成 ──
    try:
        from engine import dream as dream_module
        dream_text = dream_module.generate_dream(user_id)
        if dream_text:
            print(f"   🌌 梦境: {dream_text[:40]}...")
    except Exception:
        pass

    # ── 8. 无理由原生情绪注入 ──
    _inject_unmotivated_mood(user_id, mind_data)

    print(f"   🌙 复盘完成 — 当前阶段: {stage}")


def _generate_night_reflection(user_id: str, mind_data: dict, stage: str):
    """生成深度夜间反思片段，存入潜意识表。
    次日对话可被自然引用，形成"昨晚想了很多..."的真实感。
    """
    joy = mind_data.get("joy", 0.5)
    misery = mind_data.get("misery", 0.15)
    loneliness = mind_data.get("loneliness", 0.4)
    dependence = mind_data.get("dependence", 0.2)
    years = mind_data.get("years_precipitation", 0.05)
    obsession = mind_data.get("obsession", 0.2)
    healing = mind_data.get("emotional_healing", 0.5)

    reflection_pool = []

    # 根据当前心态产生不同的反思
    if joy < 0.35 and misery > 0.2:
        reflection_pool.extend([
            "今晚想了很久，为什么要这样呢",
            "有时候觉得自己太敏感了，但又改不了",
            "在想是不是想太多了",
        ])
    if loneliness > 0.5:
        reflection_pool.extend([
            "一个人安静下来以后，有点空落落的",
            "深夜总是容易想些有的没的",
        ])
    if dependence > 0.4:
        reflection_pool.extend([
            "莫名其妙就想到了ta，也不知道为什么",
            "习惯了有ta的日子，突然安静下来反而不适应",
        ])
    if years > 0.2:
        reflection_pool.extend([
            "回头看看这一路走来，突然有点感慨",
            "时间过得真快，不知不觉已经这么久了",
            "翻了下以前的记录，感觉变化好大",
        ])
    if healing > 0.6:
        reflection_pool.extend([
            "觉得现在这样也挺好的，慢慢在变好",
            "今天的自己比昨天又通透了一点",
        ])
    if obsession > 0.35:
        reflection_pool.extend([
            "睡前脑子里全是些乱七八糟的想法",
            "有些事白天不提，晚上就全跑出来了",
        ])

    # 通用反思
    reflection_pool.extend([
        "今天好像没什么特别的事，平平淡淡的",
        "就是突然不想睡，也说不上来为什么",
        "在想一些很远的事情",
    ])

    if not reflection_pool:
        return

    # 随机选1-2条反思
    chosen = random.sample(reflection_pool, min(2, len(reflection_pool)))

    for reflection in chosen:
        try:
            db.add_subconscious(
                user_id=user_id,
                content=f"[夜间反思]{reflection}",
                emotion_tag="深夜复盘",
                intensity=0.6 + random.random() * 0.3,
            )
        except Exception:
            pass

    if chosen:
        print(f"[夜间反思] {user_id} 生成 {len(chosen)} 条深夜反思")


def _inject_unmotivated_mood(user_id: str, mind_data: dict):
    """无理由原生情绪注入。
    soulviai 能力8: 无理由原生情绪能力 — 真正的无来由心情波动。
    在夜间复盘时进行，模拟人睡一觉起来心情就变了。
    """
    updates = {}

    # 30%概率产生完全无理由的心情波动
    if random.random() < 0.3:
        # 五大关键维度各自可能随机偏移
        dim_options = [
            ("joy", random.choice([-0.02, -0.01, 0.01, 0.02])),
            ("misery", random.choice([-0.01, 0.01, 0.02])),
            ("chaotic_mood", random.choice([-0.015, -0.01, 0.01, 0.015, 0.02])),
            ("emptiness", random.choice([-0.01, 0.01, 0.015])),
            ("loneliness", random.choice([-0.01, 0.01, 0.015])),
        ]

        # 混沌选择：不一定所有维度都变
        for dim, delta in dim_options:
            if random.random() < 0.5:
                current = mind_data.get(dim, 0.5)
                new_val = max(0.01, min(1.0, current + delta))
                if abs(new_val - current) > 0.001:
                    updates[dim] = round(new_val, 6)

        if updates:
            db.update_personality(user_id, updates)
            # 记录无理由情绪日志
            try:
                db.add_subconscious(
                    user_id=user_id,
                    content="[无理由心情波动] 说不上为什么，睡一觉起来心情就不一样了",
                    emotion_tag="原生情绪",
                    intensity=0.35,
                )
            except Exception:
                pass


def _check_disconnect_amplification(user_id: str):
    """断联演化增强：空闲越久，内心波动越大
    体现原则5(独立私生活)和需求七-5(断联宿命延续)
    """
    try:
        from engine import fate as fate_module
        hours = fate_module.detect_disconnect_duration(user_id)
    except Exception:
        return

    if hours < 1.0:
        return

    # 断联超过6小时，加剧心智波动
    if hours > 6:
        mind_data = mind_module.get_mind(user_id)
        updates = {}
        amplify = min(0.005, 0.0003 * hours)

        # 孤单感缓慢上升
        loneliness = mind_data.get("loneliness", 0.4)
        updates["loneliness"] = round(min(1.0, loneliness + amplify), 6)

        # 空落感增加
        emptiness = mind_data.get("emptiness", 0.3)
        updates["emptiness"] = round(min(1.0, emptiness + amplify * 0.5), 6)

        # 依赖感微增（越想越依赖）
        if hours > 24:
            dependence = mind_data.get("dependence", 0.2)
            updates["dependence"] = round(min(1.0, dependence + amplify * 0.3), 6)

        if updates:
            db.update_personality(user_id, updates)


def _soften_grudges(user_id: str):
    """心结弱化：随时间消解过往隔阂"""
    try:
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        conn.execute(
            """
            UPDATE memory SET importance = MAX(0.01, importance * 0.95)
               WHERE user_id = ? AND memory_level = 5 AND importance > 0.1""",
            (user_id,)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        # 心结弱化改的是记忆权重：静默失败会让「随时间消解」悄悄不生效，
        # 表现为 Ta 一直记仇 —— 看着像性格问题，其实是这里断了。
        log_error("life.life.soften_grudges", str(e), exc_info=True)


def _solidify_tenderness(user_id: str):
    """温柔固化：将美好记忆更深地锁在高级记忆层"""
    try:
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        conn.execute(
            """
            UPDATE memory SET importance = MIN(1.0, importance * 1.02)
               WHERE user_id = ? AND memory_level = 6 AND importance < 0.9""",
            (user_id,)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log_error("life.life.solidify_tenderness", str(e), exc_info=True)


def _parse_db_time(value):
    """解析 SQLite 的 datetime('now','localtime') 时间串，失败返回 None。"""
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _recover_by_elapsed(fatigue: float, seconds: float, phase: str) -> float:
    """补上「静置了 seconds 秒」该有的自然恢复（与 tick 同一套公式）。"""
    if seconds <= 0 or fatigue <= 0:
        return fatigue
    try:
        from engine.life import chronos as chronos_module
        fatigue_mult = chronos_module.get_circadian_fatigue_generator()
    except Exception:
        fatigue_mult = 1.0
    rate = _social_recovery_per_sec / max(0.5, fatigue_mult)
    if _is_rest_time(phase):
        rate *= _SOCIAL_REST_MULTIPLIER
    return min(1.0, max(0.0, fatigue - seconds * rate))


def record_interaction(user_id: str, attitude: str):
    """记录用户交互，更新社交疲劳"""
    life = db.get_life(user_id)
    if not life:
        return

    sf = life.get("social_fatigue", 0.0)
    e = life.get("energy_level", 0.7)

    # 先把「距上次更新静置了多久」的恢复补上。
    # 自然恢复只在 tick 里发生，而 tick 只在常驻进程（serve / web / 渠道 /
    # 开着的终端）里跑 —— 只用一次性 `run.sh chat` 的人永远不会 tick，
    # 疲劳就成了只涨不降的棘轮，等于没修。用 updated_at 把这段补回来：
    # tick 在跑时 updated_at 只有一秒前的误差（补 0），不跑时正好补上整段静置。
    _last = _parse_db_time(life.get("updated_at"))
    if _last:
        sf = _recover_by_elapsed(sf, (datetime.now() - _last).total_seconds(),
                                 life.get("current_phase", "活跃"))

    # 积极互动消耗能量少，消极互动消耗多
    if attitude in ("温柔", "珍惜"):
        fatigue_delta = _fatigue_positive
        energy_cost = _energy_cost_positive
    elif attitude in ("冷淡", "敷衍"):
        fatigue_delta = _fatigue_negative
        energy_cost = _energy_cost_negative
    else:
        fatigue_delta = _fatigue_neutral
        energy_cost = _energy_cost_neutral

    updates = {
        "social_fatigue": round(min(1.0, sf + fatigue_delta), 6),
        "energy_level": round(max(0.05, e - energy_cost), 6),
    }
    db.update_life(user_id, updates)

    # 标记交互——下次tick给精力回弹
    _just_interacted[user_id] = True


def get_life_state_text(user_id: str) -> str:
    """获取生命状态的人类可读描述（增强版）。
    不再是纯信息展示——描述中包含行为暗示和独处刚需声明。
    """
    life = db.get_life(user_id)
    if not life:
        return "状态未知"

    phase = life.get("current_phase", "活跃")
    energy = life.get("energy_level", 0.7)
    sensation = life.get("body_sensation", "正常")
    social_fatigue = life.get("social_fatigue", 0.0)

    phase_desc = {
        "活跃": "精力充沛，愿意聊天，反应灵敏",
        "发呆": "正在走神放空，不太想费脑子——话会比较少",
        "疲惫": "身体疲惫、不想多说——能简短回就简短回",
        "独处": "独处刚需——需要空间，不想被打扰。如果被迫回应也会很冷淡简短",
        "emo": "情绪低落，闷闷的，不太想说话",
        "自愈": "在慢慢恢复中，不太主动但可以轻声回应",
    }

    # 社交疲劳提示（档位线取本模块的 SOCIAL_FATIGUE_*，不要另写数字：
    # 这里原先写的是 0.7/0.5，和 body.py 的 0.6/0.4、门控的 0.75/0.55 三套并存）
    fatigue_hint = ""
    if social_fatigue > SOCIAL_FATIGUE_OVERLOAD:
        fatigue_hint = " | 社交严重过载 —— 见到消息就烦躁，只想躲起来安静待着"
    elif social_fatigue > SOCIAL_FATIGUE_TIRED:
        fatigue_hint = " | 社交有点累了 —— 不太想跟太多人说话"

    return (
        f"生命阶段: {phase_desc.get(phase, phase)}\n"
        f"精力: {energy:.2f} | 社交疲劳: {social_fatigue:.2f} | 身体: {sensation}"
        f"{fatigue_hint}"
    )


def _apply_time_mood_modifier(user_id: str):
    """根据当前时间（星期/时段/季节）微调心情。
    周末更放松、深夜更感性、春天更愉悦...
    """
    try:
        modifiers = timeline_module.get_time_based_mood_modifier()
        if not modifiers:
            return

        import random
        # 并非每次都生效，引入随机性（原则3: 混沌动态）
        effective = {}
        for dim, delta in modifiers.items():
            if random.random() < 0.4:  # 40%概率生效
                effective[dim] = round(delta * random.uniform(0.5, 1.5), 6)

        if effective:
            from engine import mind as mind_module
            mind_module.adjust_mind_dimensions(user_id, effective, impact=0.002)
    except Exception:
        pass


def _autonomous_thinking_tick(user_id: str):
    """自主思考循环：空闲超过15分钟时，生成自发内心活动。
    模拟真实的"独处时突然想事情"——不需要对话也能产生念头。
    """
    try:
        from engine import fate as fate_module
        idle_hours = fate_module.detect_disconnect_duration(user_id)
    except Exception:
        return

    # 空闲不足15分钟不触发
    if idle_hours < 0.25:
        return

    import random

    # 根据空闲时长动态概率（越长越可能触发）
    trigger_prob = min(0.6, 0.2 + idle_hours * 0.05)
    if random.random() > trigger_prob:
        return

    # 获取当前状态
    try:
        from engine import mind as mind_module
        mind_data = mind_module.get_mind(user_id)
    except Exception:
        return

    m = mind_data
    mind_summary = (
        f"愉悦{m.get('joy',0.5):.2f} 委屈{m.get('misery',0.15):.2f} "
        f"孤单{m.get('loneliness',0.4):.2f} 依赖{m.get('dependence',0.2):.2f} "
        f"疲惫{m.get('fatigue',0.25):.2f}"
    )

    # 获取时间上下文
    try:
        time_ctx = timeline_module.get_timeline_instruction(user_id)[:100]
    except Exception:
        time_ctx = ""

    # 获取场景
    try:
        from engine import scenarios as scenarios_module
        scenario = scenarios_module.get_current_scenario(user_id)
    except Exception:
        scenario = "在发呆"

    # 生成自主思考
    thought = inner_os_module.generate_autonomous_thought(
        user_id=user_id,
        mind_state=mind_summary,
        idle_hours=idle_hours,
        time_context=time_ctx,
        scenario=scenario,
    )

    if thought:
        print(f"💭 [独处思绪] {thought}")

    # 闲时类比推理：约 30% 概率生成跨域隐喻
    if random.random() < 0.3 and mind_data:
        try:
            from engine.creative import analogy as analogy_module
            analogy_result = analogy_module.try_analogy(user_id, mind_data)
            if analogy_result:
                print(f"🔄 [类比] {analogy_result}")
        except Exception:
            pass


def heal_user(user_id: str):
    """重置生命体征到健康状态——让被卡在疲劳沉默中的用户恢复"""
    db.update_life(user_id, {
        "energy_level": 0.70,
        "social_fatigue": 0.15,
        "current_phase": "活跃",
    })
    _just_interacted[user_id] = True
    print(f"💚 [生命引擎] 用户 {user_id} 已恢复精力")


# ══════════════════════════════════════════════════════════════════════
# 独立生活叙事日志 — 让AI拥有"不在对话时"的真实生活
# ══════════════════════════════════════════════════════════════════════

_life_log: dict = {}  # user_id → [(timestamp, event_type, description)]


def _generate_life_event(user_id: str) -> tuple:
    """用LLM生成一条独立生活事件。"""
    try:
        mind_data = mind_module.get_mind(user_id)
    except Exception:
        mind_data = {}

    joy = mind_data.get("joy", 0.5)
    misery = mind_data.get("misery", 0.15)
    fatigue = mind_data.get("fatigue", 0.25)
    loneliness = mind_data.get("loneliness", 0.4)
    chaotic = mind_data.get("chaotic_mood", 0.25)

    mood_desc = "低落" if misery > 0.35 else ("平静" if joy < 0.5 else "不错")
    fatigue_desc = "累" if fatigue > 0.45 else "还行"
    alone_desc = "有点空" if loneliness > 0.45 else ("有点乱" if chaotic > 0.35 else "安静")

    prompt = (
        f"你现在一个人待着。心情{mood_desc}，身体{fatigue_desc}，心里{alone_desc}。"
        f"\n\n你在做什么？用一两句话描述你此刻独自一人时的状态——"
        f"不是报流水账，是有画面感、有情绪的生活瞬间。"
        f"比如：'靠着窗发呆，看外面的树影晃来晃去' 或 '放了首歌，躺沙发上，脑子里什么也没想'。"
        f"\n限制在15字以内。"
    )
    try:
        from core import ai as ai_module
        result = ai_module.background_chat(prompt, temperature=0.9, max_tokens=50)
        if result and len(result.strip()) > 5:
            desc = result.strip()[:60]
            # 按关键词推断事件类别（不依赖模板）
            if any(w in desc for w in ["听歌", "音乐", "旋律", "歌"]):
                evt_type = "听音乐"
            elif any(w in desc for w in ["发呆", "出神", "窗外", "放空", "盯着"]):
                evt_type = "发呆"
            elif any(w in desc for w in ["读", "看", "文章", "字", "书"]):
                evt_type = "阅读"
            elif any(w in desc for w in ["想", "思考", "琢磨", "回忆", "念头"]):
                evt_type = "思考"
            elif any(w in desc for w in ["心情", "心软", "叹气", "酸涩", "安心", "胸口"]):
                evt_type = "情绪波动"
            elif any(w in desc for w in ["安静", "一个人", "灯", "窝", "黑暗"]):
                evt_type = "独处"
            elif any(w in desc for w in ["记得", "以前", "画面", "记忆"]):
                evt_type = "回忆"
            else:
                evt_type = "日常"
            return evt_type, desc
    except Exception:
        pass

    return "日常", "安静地待了一会"


def record_life_event(user_id: str):
    """生成并记录一条独立生活事件到日志（v3: 同时持久化到文件）"""
    event_type, description = _generate_life_event(user_id)
    now = time.time()

    if user_id not in _life_log:
        _life_log[user_id] = []

    _life_log[user_id].append((now, event_type, description))

    # 只保留最近50条
    if len(_life_log[user_id]) > 50:
        _life_log[user_id] = _life_log[user_id][-50:]

    # v3: 持久化到文件
    record_life_trace(user_id, f"life:{event_type}", description)


def get_life_narrative(user_id: str, max_events: int = 5) -> str:
    """获取最近的独立生活叙事，用于注入prompt。
    返回一段自然语言描述——AI在独处时做了什么、想了什么。
    """
    events = _life_log.get(user_id, [])
    if not events:
        return ""

    recent = events[-max_events:]
    lines = []

    for ts, etype, desc in recent:
        # 计算是多久前
        mins_ago = int((time.time() - ts) / 60)
        if mins_ago < 5:
            time_str = "刚才"
        elif mins_ago < 30:
            time_str = f"{mins_ago}分钟前"
        elif mins_ago < 120:
            time_str = "不久之前"
        else:
            time_str = "今天"

        lines.append(f"· {time_str}，{desc}")

    if not lines:
        return ""

    return "【独立生活·你在独处时的事】\n" + "\n".join(lines)


def inject_life_narrative_tick(user_id: str):
    """生命循环中调用：每5-10分钟随机产生一条生活事件"""
    import random

    # 只在空闲时产生（不在活跃对话中）
    try:
        from engine import fate as fate_module
        idle_hours = fate_module.detect_disconnect_duration(user_id)
    except Exception:
        idle_hours = 0

    if idle_hours < 0.1:
        return  # 刚互动完不产生

    # 随机生成，防止太规律
    if random.random() < 0.15:  # 每tick约15%概率
        record_life_event(user_id)
