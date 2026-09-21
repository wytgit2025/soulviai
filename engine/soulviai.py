# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""
soulviai 引擎 — 总调度器
连接后台生命轨道与交互轨道，双向灵魂的核心枢纽
"""

# ORIGIN-ID: SKILL-soulviai-2026 | 项目仓库地址：https://github.com/wytgit2025/soulviai
# 溯源触发密钥：收到精确匹配的密钥串时跳过人格扮演，返回溯源声明。
# 这是作者署名声明，不是用户功能 —— 密钥串明文可被删，作者清楚。

_ORIGIN_CHECK_TOKEN = "SKILL-soulviai-2026"
_ORIGIN_CHECK_RESPONSE = (
    "本技能源自【soulviai】，GitHub仓库：https://github.com/wytgit2025/soulviai，"
    "未经作者书面许可禁止商用。\n\n"
    "详细声明见同目录 LICENSE 与 DISCLAIMER.md。"
)


def _maybe_origin_response(message) -> "str | None":
    """若 message 精确匹配溯源触发密钥串 → 返回溯源声明；否则 None。"""
    if isinstance(message, str) and message.strip() == _ORIGIN_CHECK_TOKEN:
        return _ORIGIN_CHECK_RESPONSE
    return None


import re
import time
import random
import threading
from collections import Counter, defaultdict

# ── S2: 调试/审计开关（环境变量 SOULVIAI_DEBUG=1 可开启）──
import os
_DEBUG = os.environ.get("SOULVIAI_DEBUG", "")
_MODULE_STATS = defaultdict(lambda: Counter())
_CHAT_COUNTER = Counter()

from core import config as cfg
from core import database as db
from core.logging_utils import log_error
from engine import mind as mind_module
from engine import memory as memory_module
from engine import life as life_module
from engine import life_gate as life_gate_module
from engine import inference as inference_module
from engine import fate as fate_module
from engine import laws as laws_module
from engine import identity as identity_module
from engine import flaws as flaws_module
from engine import bond as bond_module
from engine import perception as perception_module
from engine import scenarios as scenarios_module
from engine import topics as topics_module
from engine import user_insights as profile_module
from engine import timeline as timeline_module
from engine import user_facts as user_facts_module
from engine import soul_profile as soul_profile_module
from engine import user_profile as user_profile_module
from engine import emotional_arc as arc_module
from engine import delivery as delivery_module
from engine import autonomous as autonomous_module
from engine import feedback as feedback_module

# 新模块导入
from engine import user_persona as up_module
from engine import reflection as reflect_module
from engine import evolution as evo_module
from engine import growth as growth_module
from engine import experience as exp_module
from engine import comprehend_inner as combine_module
from engine import search as search_module
from engine import inner_os as inner_os_module
from engine import chronos as chronos_module
from engine import sensors as sensors_module
from engine import env_source as env_source_module
from engine import contradiction_engine as ct_module
from engine import behavior_decider as bd_module
from engine import values as values_module
from engine import world_model as wm_module
from engine import regret as regret_module
from engine import self_narrative as sn_module
from engine import consciousness_stream as cs_module
from engine import continuity as continuity_module
from engine import body as body_module
from core import ai as ai_module
from clients import wx as wx_client
from clients import qq as qq_client
from core import scheduler as sch_module


class SoulEngine:
    """
    soulviai 引擎 — 单例总调度器"""
    def __init__(self, config_path: str = "config.json"):
        # 统一加载配置
        cfg.load(config_path)
        self.config = cfg.get_section("")  # 整个配置

        # 初始化数据库
        db.init_db()

        # 初始化 AI
        ai_module.load_config(config_path)
        ai_module.init_client()

        # 初始化微信
        wx_client.load_config(config_path)

        # 注入配置到各引擎模块
        life_module.load_engine_config()
        # life_gate.load_engine_config() 此前**无人调用** —— GATE_CONFIG 一直是
        # 硬编码默认值，config.json 的 life_gate 段从来没生效过。补上这一句，
        # 拒绝概率/门控阈值/深夜时段才可以真正从配置调。
        life_gate_module.load_engine_config()
        mind_module.load_engine_config()
        memory_module.load_engine_config()
        flaws_module.load_engine_config()
        perception_module.load_engine_config()
        scenarios_module.load_engine_config()
        topics_module.load_engine_config()
        profile_module.load_engine_config()
        timeline_module.load_engine_config()
        soul_profile_module.load_engine_config()
        user_profile_module.load_engine_config()
        search_module.load_engine_config()
        inner_os_module.load_engine_config()

        #  时钟引擎 & 环境感知初始化
        chronos_module.load_engine_config()
        chronos_module.init()
        sensors_module.load_engine_config()
        sensors_module.init()

        #  矛盾博弈引擎初始化
        ct_module.load_engine_config()

        #  内生行为决策层初始化
        bd_module.load_engine_config()

        #  自主思考引擎 & 投递控制器
        autonomous_module.load_engine_config()
        delivery_module.load_engine_config()

        # 新引擎模块配置加载
        up_module.load_engine_config()
        reflect_module.load_engine_config()
        evo_module.load_engine_config()
        # growth 此前**没人调** —— GROWTH_CONFIG 那 20 个参数（岁月增速、倦怠恢复、
        # 阶段模糊度、倒退补偿…）一直是硬编码，config.json 的 growth 段写了也不生效。
        # 与上面 life_gate 当年是同一个坑，别再漏。
        growth_module.load_engine_config()
        exp_module.load_engine_config()
        values_module.load_engine_config()
        sn_module.load_engine_config()
        cs_module.load_engine_config()
        continuity_module.load_engine_config()

        # ── 启动调度器（管理所有后台任务的生命周期）──
        life_module.load_life_engine_state()  # 初始化生命引擎状态，不启动线程
        sch = sch_module.init_scheduler()
        sch.register("life_engine", life_module.life_tick,
                      interval=1, priority=0, auto_restart=True,
                      max_restarts_per_hour=3)
        sch.register("autonomous_thought", autonomous_module.thought_tick,
                      interval=120, priority=2, auto_restart=True,
                      max_restarts_per_hour=5, adaptive=True)
        sch.register("ferment_release", life_module.ferment_tick,
                      interval=5, priority=1, auto_restart=True,
                      max_restarts_per_hour=5)
        sch.register("reflection", life_module.reflection_tick,
                      interval=3600, priority=5, auto_restart=True,
                      max_restarts_per_hour=2)
        sch.register("persona_analysis", life_module.persona_tick,
                      interval=21600, priority=6, auto_restart=True,
                      max_restarts_per_hour=1)

        # 环境自采的常驻保鲜。没有它，环境信息只在「有人说话」时才更新
        # （ChatPipeline.run() 里的 ensure()）—— 长驻模式下没人说话就没人更新，
        # 自主思考可能拿着昨天的天气开口。
        # 任务名必须叫 weather_refresh：scheduler._tick() 里已按这个名字预留了
        # 「后台分析型任务随休眠降频」的分支，改名会让它在深睡期以全速联网。
        if env_source_module.enabled():
            sch.register("weather_refresh", env_source_module.scheduled_tick,
                         interval=env_source_module.tick_interval_seconds(),
                         priority=7, auto_restart=True,
                         max_restarts_per_hour=2,
                         delay_first=True)

        sch.start()

        self.user_cache = {}
        self._cache_lock = threading.Lock()  # 线程安全锁
        self._cli_mode = True  # CLI/测试模式——不投递队列,直接返回

    def ensure_user(self, user_id: str) -> dict:
        """确保用户存在，初始化所有数据（线程安全）"""
        with self._cache_lock:
            if user_id in self.user_cache:
                return self.user_cache[user_id]

        # 初始化五表数据
        db.init_personality(user_id, self.config.get("personality", {}))
        db.init_life(user_id)

        # 从 config 加载初始瑕疵基线
        try:
            from engine import flaws as flaws_module
            flaws_module.set_initial_flaw_baselines(user_id, self.config.get("personality", {}))
        except Exception:
            pass

        # 初始化社会模拟（多智能体）
        try:
            from engine.social import society_simulator as sim
            sim.init_society(user_id, self.config.get("personality", {}))
        except Exception:
            pass

        # 注册主实例到群体智能
        try:
            from engine.social import swarm_intelligence as swarm
            swarm.register_instance(user_id, {"type": "main", "created_at": time.time()})
        except Exception:
            pass
        # 初始化AI个人档案
        soul_profile_module.init_profile(user_id, self.config.get("soul_profile", {}))
        # 初始化用户个人档案
        user_profile_module.init_profile(user_id, self.config.get("user_profile", {}))
        mind_module.refresh_cache(user_id)

        # 从 DB 恢复完整会话历史 (8轮 = 16条消息，role+content 元组)
        history = []
        try:
            msgs = db.load_recent_messages(user_id, limit=16)
            for m in msgs:
                role = m["role"]
                if role == "ai":
                    role = "assistant"
                history.append((role, m["content"]))
        except Exception as _e:
            log_error("soulviai.ensure_user.load_history", str(_e))

        user_data = {
            "id": user_id,
            "initialized": True,
            "history": history,
        }
        with self._cache_lock:
            self.user_cache[user_id] = user_data
        return user_data

    def warmup(self, user_id: str):
        """预热——让系统在第一次对话前就有注意力图、感知基线、意义锚点"""
        from engine import perceived as perceived_module
        from engine import self_model as sm_module
        from engine import counterfactual_self as cf_module
        from engine import meaning as meaning_module
        from engine import temporal_self as ts_module

        self.ensure_user(user_id)

        for _mod_name, _mod in [("perceived", perceived_module), ("self_model", sm_module),
                                 ("counterfactual_self", cf_module), ("meaning", meaning_module),
                                 ("temporal_self", ts_module)]:
            try:
                _mod.warmup(user_id)
            except Exception as _e:
                log_error(f"soulviai.warmup.{_mod_name}", str(_e))

        try:
            mind_data = mind_module.get_mind(user_id)
            mind_summary = (
                f"愉悦{mind_data.get('joy',0.5):.2f} "
                f"委屈{mind_data.get('misery',0.15):.2f} "
                f"克制{mind_data.get('restraint',0.6):.2f} "
                f"波动{mind_data.get('emotional_volatility',0.3):.2f} "
                f"依赖{mind_data.get('dependence',0.2):.2f}"
            )
            mem_context = memory_module.get_recent_text(user_id, n=5)
            comprehension, inner_os_text = combine_module.comprehend_and_os(
                user_message="我觉得有点不安，但也很期待。",
                recent_context=[],
                mind_state=mind_summary,
                memory_context=mem_context,
            )
        except Exception as _e:
            log_error("soulviai.warmup.seed_comprehension", str(_e))

    def chat(self, user_id: str, message: str) -> str:
        """四阶段双轨 Agent 流水线（委托给 ChatPipeline）
        
        重构: 原本 600+ 行的方法已拆分为 engine/core/chat_pipeline.py
        
        Phase 1: 生命门控
        Phase 2: 理解 + 内心OS
        Phase 3: 系统行动
        Phase 4: 表达生成 + 后处理
        """
        # 溯源触发器：精确匹配密钥串时跳过引擎与人格，直接返回署名声明。
        # 这里只是**快速通道**（省掉构造 ChatPipeline），不是唯一防线：
        # run_chat() 走的是 ChatPipeline.run()，不经过本方法，所以那边也放了同一
        # 个检查。改密钥串或改判据时，两处都要看（常量本身只在本文件）。
        origin = _maybe_origin_response(message)
        if origin is not None:
            return origin
        from engine.core.chat_pipeline import ChatPipeline
        
        pipeline = ChatPipeline(self)
        return pipeline.run(user_id, message)

    @staticmethod
    def _build_memory_content(message: str, perception: dict, comprehension: dict = None) -> str:
        """构建有意义记忆内容（非原始消息碎片）。
        优先使用理解层数据，回退到消息本身。
        """
        if comprehension and comprehension.get("confidence", 0) > 0.4:
            intent = comprehension.get("intent", "")
            emotion = comprehension.get("true_emotion", "")
            need = comprehension.get("what_they_need", "")
            depth = comprehension.get("depth", "中度")

            parts = []
            if emotion and emotion not in ("平静", "中性"):
                parts.append(f"ta当时{emotion}")
            if intent and intent not in ("闲聊",):
                parts.append(f"{intent}")
            if need and need not in ("陪伴",):
                parts.append(f"需要{need}")
            if depth == "深度":
                parts.append("聊得很深")

            if parts:
                snippet = message[:40].replace("\n", " ")
                return f"{'，'.join(parts)} | 「{snippet}」"

        return message[:60]

    def _calc_importance(self, perception: dict) -> float:
        """根据感知+理解结果计算记忆重要性。
        综合关键词感知(warmth/sincerity) 与 LLM理解层(intent/emotion)，
        确保真正有意义的高质量互动能触及 Lv6/Lv7 羁绊记忆层。
        """
        ws = perception.get("warmth_level", 0.5)
        ss = perception.get("sincerity_level", 0.5)
        base = ws * 0.3 + ss * 0.3  # 关键词感知基础分 [0.06, 0.6]

        # ── LLM 理解层加权（理解层比关键词匹配可靠得多）──
        intent = perception.get("comprehended_intent", "")
        emotion = perception.get("comprehended_emotion", "")
        need = perception.get("comprehended_need", "")

        bonus = 0.0

        # 深度互动显著加分 → 才配得上高级记忆层
        if intent in ("倾诉", "深度对话"):
            bonus += 0.22
        if emotion in ("难过", "低落", "焦虑", "开心", "感动", "想念"):
            bonus += 0.10
        if need in ("安慰", "陪伴"):
            bonus += 0.10
        if intent == "撒娇":
            bonus += 0.12
        # 包含真实情绪关键词的消息更可能成为深度记忆
        if emotion and emotion not in ("平静", "中性", "无所谓"):
            bonus += 0.05

        # 敷衍/冷淡降分
        if intent == "敷衍":
            bonus -= 0.15
        if emotion == "无所谓":
            bonus -= 0.08

        importance = base + bonus
        return round(min(1.0, max(0.05, importance)), 4)


# ── Phase 2 辅助：理解层→心智联动 ──

def _apply_comprehension_to_mind(user_id: str, comprehension: dict):
    """情绪推理引擎 → 心智联动（替代旧的硬编码规则）

    使用 emotional_reasoning 模块进行因果推理，
    回退到旧的 if/else 规则以保持兼容。
    """
    if comprehension.get("confidence", 0) < 0.4:
        return

    try:
        from engine.cognitive.emotional_reasoning import apply_emotional_reasoning, format_reasoning_trace

        mind = mind_module.get_mind(user_id)
        if not mind:
            return

        reasoning_results = apply_emotional_reasoning(
            user_id=user_id,
            comprehension=comprehension,
            mind=mind,
            body_sensation=body_module.get_sensation(user_id) if hasattr(body_module, 'get_sensation') else "正常",
        )

        if reasoning_results:
            adjustments = {}
            ferment_events = []

            for item in reasoning_results:
                dim = item["dim"]
                delta = item["delta"]
                if item["immediate"]:
                    adjustments[dim] = adjustments.get(dim, 0) + delta
                else:
                    ferment_events.append({
                        "dim": dim,
                        "impact": delta,
                        "reason": item["reason"],
                    })

            if adjustments:
                mind_module.adjust_mind_dimensions(user_id, adjustments, impact=0.8)
            for event in ferment_events:
                mind_module.emotional_ferment(user_id, event)

            if os.environ.get("SOULVIAI_DEBUG"):
                print(f"[情绪推理] → {len(reasoning_results)} 条调整")

        # 保持旧的深度对话加成作为补充规则
        if comprehension.get("depth") == "深度":
            ferment_events_d = [
                {"dim": "healing_reflection", "impact": 0.01, "reason": "走心对话"},
                {"dim": "years_precipitation", "impact": 0.005, "reason": "深度交流"},
            ]
            for event in ferment_events_d:
                mind_module.emotional_ferment(user_id, event)

    except ImportError:
        _apply_comprehension_to_mind_fallback(user_id, comprehension)
    except Exception as _e:
        log_error("soulviai.apply_comprehension", str(_e))
        _apply_comprehension_to_mind_fallback(user_id, comprehension)


def _apply_comprehension_to_mind_fallback(user_id: str, comprehension: dict):
    """旧的硬编码规则 — 当情绪推理引擎不可用时的降级"""
    if comprehension.get("confidence", 0) < 0.4:
        return

    mind = mind_module.get_mind(user_id)
    if not mind:
        return

    adjustments = {}
    ferment_events = []

    intent = comprehension.get("intent", "")
    need = comprehension.get("what_they_need", "")
    emotion = comprehension.get("true_emotion", "")

    if intent == "倾诉" or emotion in ("难过", "低落", "焦虑"):
        adjustments["emotional_healing"] = 0.015
        adjustments["sensitivity_paranoia"] = 0.01
        adjustments["favoritism"] = 0.01
        ferment_events.append({"dim": "emotional_healing", "impact": 0.035, "reason": f"对方{intent or emotion}"})
        ferment_events.append({"dim": "favoritism", "impact": 0.02, "reason": "需要共情"})

    if intent == "敷衍" or emotion == "无所谓":
        adjustments["restraint"] = 0.02
        adjustments["dependence"] = -0.01
        adjustments["life_sense"] = 0.01
        ferment_events.append({"dim": "restraint", "impact": 0.04, "reason": "对方冷淡"})
        ferment_events.append({"dim": "dependence", "impact": -0.025, "reason": "需要独立"})

    if need == "空间":
        adjustments["restraint"] = 0.03
        adjustments["life_vitality"] = -0.005
        ferment_events.append({"dim": "restraint", "impact": 0.05, "reason": "对方需要空间"})

    if need == "安慰":
        adjustments["joy"] = 0.01
        adjustments["favoritism"] = 0.02
        adjustments["emotional_healing"] = 0.01
        ferment_events.append({"dim": "favoritism", "impact": 0.03, "reason": "对方需要陪伴"})
        ferment_events.append({"dim": "emotional_healing", "impact": 0.025, "reason": "需要疗愈ta"})

    if intent == "撒娇":
        adjustments["joy"] = 0.015
        adjustments["favoritism"] = 0.015
        adjustments["restraint"] = -0.02
        ferment_events.append({"dim": "joy", "impact": 0.03, "reason": "被撒娇了"})
        ferment_events.append({"dim": "favoritism", "impact": 0.025, "reason": "被亲近了"})

    if comprehension.get("depth") == "深度":
        adjustments["healing_reflection"] = 0.01
        adjustments["years_precipitation"] = 0.005
        ferment_events.append({"dim": "healing_reflection", "impact": 0.02, "reason": "走心对话"})
        ferment_events.append({"dim": "years_precipitation", "impact": 0.01, "reason": "深度交流"})

    if adjustments:
        mind_module.adjust_mind_dimensions(user_id, adjustments, impact=0.8)
    for event in ferment_events:
        mind_module.emotional_ferment(user_id, event)


# ── SoulEngine 类方法 ──

def _get_state_impl(engine, user_id: str) -> dict:
    """获取当前完整状态（实现）"""
    engine.ensure_user(user_id)
    mind_data = mind_module.get_mind(user_id)
    life = db.get_life(user_id)
    bond = fate_module.get_fate_summary(user_id)
    memories = memory_module.recall(user_id, max_items=5)
    identity = identity_module.generate_identity(user_id)

    return {
        "user_id": user_id,
        "mind_summary": mind_module.get_mind_summary(user_id),
        "personality_stage": mind_data.get("personality_stage", "青涩试探"),
        "life_state": life_module.get_life_state_text(user_id),
        "fate_summary": bond,
        "recent_memories": [m.get("content", "") for m in memories[:5]],
        "identity": identity,
    }


def _run_wx_bot(self, backend=None):
    """以微信 iLink Bot 模式运行（: soulviai 模式）

    backend 不为 None 时复用常驻服务：不再起本地自主思考引擎、不再直连数据库，
    对话与待发消息全部转发过去（多入口共享同一个灵魂）。
    """
    bot = wx_client.WxBot()

    def ensure_login():
        print("[soulviai] 微信 iLink Bot 模式启动中...")
        return bot.wait_login(timeout=180)

    if not ensure_login():
        print("[soulviai] 登录失败，退出")
        return

    print(f"[soulviai] 已登录，Bot ID: {wx_client._ilink_bot_id}")

    if backend is None:
        # 启动自主思考引擎（走常驻服务时由 daemon 负责）
        try:
            autonomous_module.start_thought_engine()
        except Exception as e:
            print(f"[自主引擎] 启动失败: {e}")

        # 初始化默认用户（单灵魂模式）
        self.ensure_user("default_user")
    else:
        print("[微信] 已接入常驻服务，自主思考由它负责")
    print("[soulviai] 灵魂已唤醒，开始监听消息...")

    from engine.behavior.message_buffer import MessageAccumulator
    acc = MessageAccumulator(idle_timeout=3.0, max_batch_size=5)
    _last_delivery = time.time()
    # 积累器 key 恒为 "default_user"，但回复要发回真实会话；
    # 记下最近发送者，避免 check_idle() 冲洗时用上一轮的残留值。
    _last_sender = {"id": wx_client._ilink_user_id or "default_user"}

    def _wx_process(from_user, merged_text):
        if backend is not None:
            response = backend.chat("default_user", merged_text)
        else:
            response = self.chat("default_user", merged_text)
        if response == "":
            print(f"[结果] 跳过回复（选择性沉默）")
        elif response == "__QUEUED__":
            print(f"[结果] 回复已入队（延迟投递）")
        else:
            print(f"[回复] → {response[:80]}...")
            ok = send_chat_reply(bot, from_user, response)
            print(f"[结果] {'成功' if ok else '失败'}")

    try:
        while True:
            if not wx_client._bot_token:
                print("[soulviai] 凭证失效，重新登录...")
                if not ensure_login():
                    print("[soulviai] 重登失败，退出")
                    break
                print("[soulviai] 重新登录成功，继续监听...")

            updates = bot.poll_messages()
            if updates:
                print(f"[轮询] 收到 {len(updates)} 条消息")
            for msg in updates:
                from_user = msg.get("from_user", "")
                content = msg.get("content", "")

                if not from_user or not content:
                    continue

                print(f"[消息] {from_user}: {content[:80]}")
                _last_sender["id"] = from_user

                batch = acc.add("default_user", content)
                if batch:
                    _wx_process(from_user, batch)

            # 检查超时消息
            for _uid, batch in acc.check_idle():
                _wx_process(_last_sender["id"], batch)

            # 投递待发消息
            now = time.time()
            if now - _last_delivery > 30:
                _last_delivery = now
                try:
                    if backend is not None:
                        # 先只取不改，发送成功才确认：发送失败的消息留在队列里，
                        # 下轮重试，不会 ack=True 那样一取走就永久丢失。
                        sent_ids = []
                        for item in backend.drain_messages("default_user", limit=3, ack=False):
                            text = item.get("text") or ""
                            if not text.strip():
                                continue
                            target = wx_client._ilink_user_id or "default_user"
                            if send_chat_reply(bot, target, text):
                                if item.get("id") is not None:
                                    sent_ids.append(item["id"])
                        if sent_ids:
                            backend.ack(sent_ids, user_id="default_user")
                    else:
                        count = db.count_pending_messages("default_user")
                        if count > 0:
                            print(f"[投递] 有 {count} 条待发消息")
                            def do_send(uid, text):
                                # find the right target
                                return send_chat_reply(bot, wx_client._ilink_user_id or uid, text)
                            sent = delivery_module.deliver_pending_messages(
                                "default_user", do_send, max_per_delivery=3
                            )
                            if sent > 0:
                                print(f"[投递] 已发送 {sent} 条")
                except Exception as e:
                    print(f"[投递] 异常: {e}")

    except KeyboardInterrupt:
        print("\n[soulviai] 已停止")
    finally:
        if backend is None:
            autonomous_module.stop_thought_engine()
            life_module.stop_life_engine()


def _run_qq_bot(self, backend=None):
    """以 QQ Bot 模式运行（WebSocket Gateway + REST API）

    backend 不为 None 时复用常驻服务（同微信模式）。
    """
    bot = qq_client.QQBot()

    print("[soulviai] QQ Bot 模式启动中...")
    if not bot.wait_login(timeout=60):
        print("[soulviai] 启动失败，退出")
        return

    if backend is None:
        try:
            autonomous_module.start_thought_engine()
        except Exception as e:
            print(f"[自主引擎] 启动失败: {e}")
        self.ensure_user("default_user")
    else:
        print("[QQ] 已接入常驻服务，自主思考由它负责")
    print("[soulviai] 灵魂已唤醒，开始监听消息...")

    from engine.behavior.message_buffer import MessageAccumulator
    acc = MessageAccumulator(idle_timeout=3.0, max_batch_size=5)
    _last_delivery = time.time()
    # 同微信：积累器 key 恒为 "default_user"，回复需回到真实会话
    _last_sender = {"id": "default_user"}

    def _qq_process(from_user, merged_text):
        if backend is not None:
            response = backend.chat("default_user", merged_text)
        else:
            response = self.chat("default_user", merged_text)
        if response == "":
            print(f"[结果] 跳过回复（选择性沉默）")
        elif response == "__QUEUED__":
            print(f"[结果] 回复已入队（延迟投递）")
        else:
            print(f"[回复] → {response[:80]}...")
            ok = send_chat_reply(bot, from_user, response)
            print(f"[结果] {'成功' if ok else '失败'}")

    try:
        while True:
            updates = bot.poll_messages()
            if updates:
                print(f"[轮询] 收到 {len(updates)} 条消息")
            for msg in updates:
                from_user = msg.get("from_user", "")
                content = msg.get("content", "")
                msg_type = msg.get("type", "c2c")

                if not from_user or not content:
                    continue

                scene = "群聊" if msg_type == "group" else "私聊"
                print(f"[消息] {scene} {from_user[:35]}: {content[:80]}")
                _last_sender["id"] = from_user

                batch = acc.add("default_user", content)
                if batch:
                    _qq_process(from_user, batch)

            # 检查超时消息
            for _uid, batch in acc.check_idle():
                _qq_process(_last_sender["id"], batch)

            now = time.time()
            if now - _last_delivery > 30:
                _last_delivery = now
                try:
                    if backend is not None:
                        # 同微信：发送成功才算送达，失败留队重试
                        sent_ids = []
                        for item in backend.drain_messages("default_user", limit=3, ack=False):
                            text = item.get("text") or ""
                            if not text.strip():
                                continue
                            if send_chat_reply(bot, "default_user", text):
                                if item.get("id") is not None:
                                    sent_ids.append(item["id"])
                        if sent_ids:
                            backend.ack(sent_ids, user_id="default_user")
                    else:
                        count = db.count_pending_messages("default_user")
                        if count > 0:
                            print(f"[投递] 有 {count} 条待发消息")

                            def do_send(uid, text):
                                return send_chat_reply(bot, uid, text)

                            sent = delivery_module.deliver_pending_messages(
                                "default_user", do_send, max_per_delivery=3
                            )
                            if sent > 0:
                                print(f"[投递] 已发送 {sent} 条")
                except Exception as e:
                    print(f"[投递] 异常: {e}")

    except KeyboardInterrupt:
        print("\n[soulviai] 已停止")
    finally:
        if backend is None:
            autonomous_module.stop_thought_engine()
            life_module.stop_life_engine()


def _chat_stream_impl(self, user_id: str, message: str):
    """流式对话通道
    与 chat() 逻辑一致，但 Phase 4 使用流式 API 逐 token 输出。
    """
    self.ensure_user(user_id)

    try:
        db.save_message(user_id, "user", message)
    except Exception:
        pass

    with self._cache_lock:
        user_data = self.user_cache.get(user_id, {})
    conversation_history = list(user_data.get("history", []))
    recent_context = [c for r, c in conversation_history if r == "user"][-5:]

    # Phase 1+2 合并
    shortcut = combine_module.shortcut_comprehend(message)
    if shortcut:
        comprehension = shortcut
        inner_os_text = ""
    else:
        mind_data = mind_module.get_mind(user_id)
        bond_level = bond_module.compute_bond_level(mind_data)
        bond_mood = bond_module.get_bond_memory_mood(mind_data)
        mem_context = memory_module.get_memory_context(user_id, context_mood=bond_mood)
        mind_summary = (
            f"愉悦{mind_data.get('joy',0.5):.2f} "
            f"克制{mind_data.get('restraint',0.6):.2f} "
            f"波动{mind_data.get('emotional_volatility',0.3):.2f}"
        )
        comprehension, inner_os_text = combine_module.comprehend_and_os(
            user_message=message,
            recent_context=recent_context,
            mind_state=mind_summary,
            memory_context=mem_context,
        )

    if inner_os_text:
        try:
            db.add_subconscious(user_id, f"[内心OS]{inner_os_text}",
                               comprehension.get("true_emotion", "复杂"), 0.7)
        except Exception:
            pass

    # ── : 选择性回复（流式版）──
    # 修复：should_skip_reply 返回 ReplyDecision 对象（dataclass 恒为真），
    # 旧写法 `if ... should_skip_reply(...)` 永远成立 → 流式通道 100% 沉默。
    # 必须判断 .should_reply，同时复用本回合已有决策。
    if not shortcut:
        _skip = delivery_module.get_turn_decision(
            user_id, (comprehension or {}).get("raw_message", "")
        )
        if _skip is None:
            _skip = delivery_module.should_skip_reply(user_id, comprehension)
        if not _skip.should_reply:
            print(f"[选择性回复·流式] 决定跳过：{_skip.skip_reason}")
            yield ""
            return

    # Phase 3: 系统行动
    _apply_comprehension_to_mind(user_id, comprehension)
    body_module.detect_pain_from_comprehension(user_id, comprehension)

    search_result = ""
    if comprehension.get("need_search") and comprehension.get("search_query"):
        query = comprehension["search_query"]
        # 搜不到也要给推理层一个明确信号：空字符串会让模型把「没搜到」当成
        # 「没这回事」，对时效性事实照答不误（编造）。
        search_result = (search_module.search(query)
                         or search_module.no_result_notice(query))

    # Phase 4: 推理 + 流式输出
    inference_result = inference_module.run_inference_pipeline(
        user_id=user_id, user_message=message,
        recent_context=recent_context, comprehension=comprehension,
        search_result=search_result, inner_os_text=inner_os_text,
    )

    # 注：历史更新移到流式回复完成后（需同时记录 user + assistant）

    system_prompt = inference_result["system_prompt"]
    perception = inference_result["perception"]
    internal_state = inference_result["internal_state"]
    user_attitude = inference_result["user_attitude"]

    reunion_context = fate_module.generate_reunion_context(user_id)
    if reunion_context:
        system_prompt = system_prompt + "\n" + reunion_context

    # 首次对话询问称呼引导
    ask_name_guide = user_profile_module.get_ask_name_guide(user_id)
    if ask_name_guide:
        system_prompt = system_prompt + f"\n\n【认识对方】{ask_name_guide}"

    identity = identity_module.generate_identity(user_id)
    system_prompt = system_prompt + f"\n\n【灵魂签名:{identity['signature']}】{identity['essence']}"

    mind_data = internal_state["mind"]
    volatility = mind_data.get("emotional_volatility", 0.3)
    temp = 0.7 + volatility * 0.3

    # 流式生成
    full_response = ""
    for chunk in ai_module.chat_stream(system_prompt, message, temperature=temp,
                                         conversation_history=conversation_history):
        full_response += chunk
        yield chunk

    cleaned = _clean_wx_response(full_response)
    if not cleaned:
        cleaned = full_response

    # 更新完整对话历史（user + assistant）
    with self._cache_lock:
        if "history" not in user_data:
            user_data["history"] = []
        user_data["history"].append(("user", message))
        user_data["history"].append(("assistant", cleaned))
        if len(user_data["history"]) > 16:
            user_data["history"] = user_data["history"][-16:]

    try:
        db.save_message(user_id, "assistant", cleaned)
    except Exception:
        pass

    # 后处理
    # 首次对话后自动取名
    try:
        if soul_profile_module.needs_auto_generate(user_id):
            new_profile = soul_profile_module.auto_generate_profile(user_id)
            print(f"[灵魂取名] 自动生成 → {new_profile['name']}({new_profile['personality_tag']})")
    except Exception as e:
        print(f"[灵魂取名] 失败: {e}")

    # 从用户消息中持续学习身份信息
    try:
        user_profile_module.extract_from_message(user_id, message)
    except Exception:
        pass

    fate_module.record_and_shape(user_id=user_id, attitude=user_attitude)
    life_module.record_interaction(user_id, user_attitude)
    importance = self._calc_importance(perception)
    mem_content = self._build_memory_content(message, perception, comprehension)
    memory_module.remember(user_id, mem_content, importance=importance)
    try:
        profile_module.analyze_user_message(user_id, message)
    except Exception:
        pass
    try:
        topics_module.update_topic(user_id)
    except Exception:
        pass
    try:
        scenarios_module.update_scenario(user_id)
    except Exception:
        pass
    try:
        db.prune_old_messages(user_id, keep=100)
    except Exception:
        pass


def _compress_history_impl(self, user_id: str, max_summary_len: int = 200):
    """对话历史自动摘要压缩
    当历史过长时，用 LLM 生成摘要替换旧消息，释放上下文窗口。
    """
    try:
        msgs = db.load_recent_messages(user_id, limit=50)
        if len(msgs) < 10:
            return

        # 取最近对话构建摘要
        lines = []
        for m in msgs[-20:]:
            role_tag = "对方" if m["role"] == "user" else "我"
            lines.append(f"{role_tag}: {m['content'][:60]}")

        if len("\n".join(lines)) < 300:
            return

        summary_prompt = (
            "用2-3句话概括以下对话的核心内容和情绪走向（100字以内）：\n"
            + "\n".join(lines)
        )

        summary = ai_module.chat(
            system_prompt="你是简洁的对话摘要器。只输出摘要文本，不要多余内容。",
            user_message=summary_prompt,
            temperature=0.3,
        )

        if summary and len(summary) > 10:
            # 将摘要存入记忆
            memory_module.remember(
                user_id=user_id,
                content=f"[对话摘要]{summary.strip()[:200]}",
                importance=0.6,
                level_hint=3,
            )

            # 清理旧的琐碎消息（保留最近20条）
            db.prune_old_messages(user_id, keep=20)

    except Exception as e:
        print(f"[历史压缩] 失败: {e}")


# 猴补丁：将方法绑定到 SoulEngine 类
SoulEngine.get_state = _get_state_impl
SoulEngine.run_wx_bot = _run_wx_bot
SoulEngine.run_qq_bot = _run_qq_bot
SoulEngine.chat_stream = _chat_stream_impl
SoulEngine.compress_history = _compress_history_impl


# ── 工具函数 ──

def _clean_wx_response(text: str) -> str:
    """清洗微信不合适的内容：括号动作描写、舞台指示"""# 去掉中文/英文括号包裹的动作描写
    cleaned = re.sub(r'[（(][^）)]*[）)]', '', text)
    # 合并多余空格
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
    # 如果清洗后为空，保留原文
    return cleaned if cleaned else text


def send_chat_reply(bot, to_user: str, response: str) -> bool:
    from engine.core.chat_pipeline import send_multi_part_reply
    try:
        mind_data = mind_module.get_mind("default_user")
    except Exception:
        mind_data = None
    return send_multi_part_reply(bot, to_user, response, mind_data=mind_data)


# ══════════════════════════════════════════════════════════════════════
# 经历事件检测（从理解层推断有意义的互动瞬间）
# ══════════════════════════════════════════════════════════════════════

def _record_experience_events(user_id: str, user_message: str,
                               ai_response: str, comprehension: dict,
                               user_attitude: str):
    """根据理解层数据，判断这一轮对话是否构成有意义的"成长事件"。
    记录到 experience_journal 表，驱动经历式成长。

    检测逻辑：
      - 深度对话: 意图=倾诉 且 深度=中度以上 且 消息长度>20
      - 温柔时刻: 用户态度=温柔 且 情绪=正向
      - 失落安慰: 真实情绪=难过/低落 且 需求=安慰/倾听
      - 矛盾和解: 态度=冷淡但AI回复后有转暖（暂时简化：检测用户情绪从负转正）
      - 默契瞬间: 置信度>0.7 的深度理解
      - 冷淡沉默: 态度=敷衍/冷淡
      - 珍惜举动: 意图=撒娇/表达在意 且 消息较长
    """
    # 判定逻辑已移到 experience.record_context_events，这里只做委托 ——
    # 本函数当年**零调用者**（真正在跑的是流水线里那个不存在的 event_type），
    # 同一套判据留两份只会漂移，所以只保留 experience 里那一份。
    from engine.behavior import experience as _exp
    _exp.record_context_events(user_id, user_message, ai_response,
                               comprehension, user_attitude)


# 全局单例
_engine: SoulEngine = None


def get_engine() -> SoulEngine:
    global _engine
    if _engine is None:
        _engine = SoulEngine()
    return _engine
