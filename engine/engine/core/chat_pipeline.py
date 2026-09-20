# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""智能对话管道引擎 — Chat Pipeline
==========================================================
将 soul.py 中 600+ 行的 chat() 方法拆分为清晰的多阶段管道。

架构:
  Input (user_id, message)
    ↓
  Stage 1: LifeGate — 生命门控（是否应该回复）
  Stage 2: Preprocess — 反馈学习 + 历史加载
  Stage 3: Comprehend+OS — 理解层 + 内心OS
  Stage 4: Action — 系统响应（搜索/心智调整/体感）
  Stage 5: Prompt — 构建 system prompt（集成所有模块）
  Stage 6: Generate — LLM 调用 + 后处理
  Stage 7: Aftercare — 记忆/人格/羁绊持久化
    ↓
  Output response (str)

核心原则:
  - 每个阶段有清晰的输入/输出
  - 错误不静默吞噬（记录但不中断流程）
  - 所有新模块在此连接
"""
import json
import re
import time
import math
import random
from typing import Dict, List, Optional, Tuple
from collections import Counter, defaultdict
from datetime import datetime

from core import config as cfg
from core import database as db
from core import ai as ai_module

# Unicode emoji → 微信表情包 映射表
_EMOJI_TO_WX = {
    "😊": "[愉快]", "😄": "[呲牙]", "😁": "[呲牙]", "😂": "[破涕为笑]", "🤣": "[破涕为笑]",
    "😅": "[捂脸]", "😰": "[捂脸]", "🥰": "[害羞]", "😘": "[亲亲]", "😍": "[害羞]",
    "❤️": "[爱心]", "💕": "[爱心]", "💗": "[爱心]", "💔": "[心碎]", "🖤": "[心碎]",
    "😢": "[流泪]", "😭": "[流泪]", "😞": "[难过]", "😔": "[难过]", "🥺": "[撇嘴]",
    "😠": "[皱眉]", "😡": "[发怒]", "😤": "[发怒]", "🙄": "[翻白眼]", "😑": "[撇嘴]",
    "😐": "[发呆]", "😶": "[发呆]", "😴": "[睡觉]", "😪": "[睡觉]",
    "😌": "[愉快]", "😏": "[奸笑]", "😎": "[得意]", "🤔": "[疑问]",
    "👏": "[强]", "👍": "[强]", "👎": "[弱]", "✌️": "[耶]", "🤞": "[耶]",
    "🙏": "[抱拳]", "🤝": "[握手]", "💪": "[加油]", "🎉": "[烟花]", "🎊": "[烟花]",
    "🌹": "[玫瑰]", "🌸": "[玫瑰]", "💐": "[玫瑰]", "✨": "[星星]", "⭐": "[星星]",
    "😤": "[叹气]", "😩": "[流泪]", "😫": "[流泪]", "😖": "[难过]",
    "😳": "[害羞]", "🥴": "[晕]", "🤭": "[捂脸]", "🤫": "[嘘]", "🤗": "[拥抱]",
    "👋": "[挥手]", "🥳": "[庆祝]", "🤩": "[色]", "🥺": "[委屈]", "😨": "[恐惧]",
}
# 构建编译用的正则（按长度降序，长匹配优先）
_EMOJI_PATTERN = re.compile("|".join(re.escape(e) for e in sorted(_EMOJI_TO_WX.keys(), key=len, reverse=True)))

# 微信表情包标签 → Unicode emoji 反向映射（非微信平台使用真实emoji）
_WX_TO_EMOJI = {
    "[愉快]": "😊", "[呲牙]": "😁", "[破涕为笑]": "😂", "[捂脸]": "😅",
    "[害羞]": "🥰", "[亲亲]": "😘", "[爱心]": "❤️", "[心碎]": "💔",
    "[流泪]": "😢", "[难过]": "😞", "[撇嘴]": "😒", "[皱眉]": "😠",
    "[发怒]": "😡", "[翻白眼]": "🙄", "[叹气]": "😮‍💨", "[挥手]": "👋",
    "[庆祝]": "🎉", "[色]": "😍", "[委屈]": "🥺", "[恐惧]": "😨",
    "[苦涩]": "😖", "[裂开]": "🫠", "[发呆]": "😶",
    "[傲慢]": "😏", "[白眼]": "🙄",
    "[得意]": "😎", "[奸笑]": "😏", "[疑问]": "🤔",
    "[强]": "👍", "[弱]": "👎", "[耶]": "✌️",
    "[抱拳]": "🙏", "[握手]": "🤝", "[加油]": "💪",
    "[烟花]": "🎉", "[玫瑰]": "🌹", "[星星]": "✨",
    "[晕]": "🥴", "[嘘]": "🤫", "[拥抱]": "🤗", "[睡觉]": "😴",
}
_WX_TAG_PATTERN = re.compile("|".join(re.escape(t) for t in sorted(_WX_TO_EMOJI.keys(), key=len, reverse=True)))

from engine import mind as mind_module
from engine import memory as memory_module
from engine import perception as perception_module
from engine import life as life_module
from engine import body as body_module
from engine import bond as bond_module
from engine import fate as fate_module
from engine import identity as identity_module
from engine import laws as laws_module
from engine import feedback as feedback_module
from engine import profile as profile_module
from engine import user_facts as user_facts_module
from engine import topics as topics_module
from engine import scenarios as scenarios_module
from engine import timeline as timeline_module
from engine import soul_profile as soul_profile_module
from engine import user_profile as user_profile_module
from engine import emotional_arc as arc_module
from engine import delivery as delivery_module
from engine import autonomous as autonomous_module
from engine import search as search_module
from engine import comprehend_inner as combine_module
from engine import contradiction_engine as ct_module
from engine import behavior_decider as bd_module
from engine import inference as inference_module
from engine import world_model as wm_module
from engine import regret as regret_module
from engine import self_narrative as sn_module
from engine import consciousness_stream as cs_module
from engine import continuity as continuity_module

try:
    from engine import life_gate as gate_module
except ImportError:
    gate_module = None
try:
    from engine import user_persona as up_module
except ImportError:
    up_module = None
try:
    from engine import reflection as reflect_module
except ImportError:
    reflect_module = None

# 新模块
try:
    from engine.behavior import projection_learning as pl_module
except ImportError:
    pl_module = None
try:
    from engine.behavior import delivery_memory as dm_module
except ImportError:
    dm_module = None
try:
    from engine.cognitive import reasoning_loop as rl
except ImportError:
    rl = None


# ══════════════════════════════════════════════════════════════════════
# 错误记录工具（不静默吞噬）
# ══════════════════════════════════════════════════════════════════════

def _log_error(stage: str, module: str, error: Exception, context: str = ""):
    """记录错误但不中断流程"""
    print(f"[Pipeline:{stage}] {module} — {type(error).__name__}: {error}")
    try:
        from core.logging_utils import log_error as lu_log
        lu_log(f"pipeline.{stage}.{module}", str(error)[:200])
    except Exception:
        print(f"[Pipeline] 无法记录错误日志: {error}")


# ══════════════════════════════════════════════════════════════════════
# 对话历史 Token 裁剪
# ══════════════════════════════════════════════════════════════════════

def _trim_history_to_token_budget(history: list, max_tokens: int = 6000) -> list:
    """根据 Token 预算裁剪对话历史（保留最近的）"""
    if not history:
        return []
    trimmed = []
    total_tokens = 0
    for role, content in reversed(history):
        tokens = len(content) * 1.3
        if total_tokens + tokens > max_tokens:
            break
        trimmed.insert(0, (role, content))
        total_tokens += tokens
    return trimmed


# ══════════════════════════════════════════════════════════════════════
# 自适应延迟计算
# ══════════════════════════════════════════════════════════════════════

def _compute_typing_delay(mind_data: dict, behavior_vector: dict = None) -> float:
    """根据心智状态和行为了计算打字延迟 (0.5-8秒)"""
    base = 1.5
    joy = mind_data.get("joy", 0.5)
    fatigue = mind_data.get("fatigue", 0.25)
    if joy > 0.7:
        base -= 0.5
    elif joy < 0.3:
        base += 0.5
    if fatigue > 0.5:
        base += 1.0
    if behavior_vector:
        pace = behavior_vector.get("pace", 0.5)
        base += (1 - pace) * 2.0
        sulk = behavior_vector.get("sulkiness", 0.2)
        base += sulk * 3.0
    base += random.uniform(-0.3, 0.3)
    return max(0.5, min(8.0, base))


# ══════════════════════════════════════════════════════════════════════
# 用户情感分析（用于投递记忆和投影学习）
# ══════════════════════════════════════════════════════════════════════

def _detect_user_sentiment(message: str, comprehension: dict = None) -> str:
    """检测用户情感倾向"""
    if comprehension:
        emotion = comprehension.get("true_emotion", "")
        if emotion in ("开心", "感动", "温暖", "喜悦"):
            return "positive"
        if emotion in ("生气", "难过", "失望", "烦"):
            return "negative"
    positive_words = ["开心", "高兴", "喜欢", "爱", "好", "哈", "嘻嘻", "温暖", "感动"]
    negative_words = ["生气", "难过", "不喜欢", "讨厌", "烦", "无聊", "呵呵", "冷漠", "失望"]
    pos = sum(1 for w in positive_words if w in message)
    neg = sum(1 for w in negative_words if w in message)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def _estimate_complexity(message: str) -> float:
    """评估对话复杂度 0~1"""
    length = len(message)
    has_question = "?" in message or "？" in message
    has_emotion = any(w in message for w in ["难过", "开心", "生气", "失望", "纠结", "矛盾"])
    length_score = min(1.0, length / 100)
    question_score = 0.3 if has_question else 0
    emotion_score = 0.2 if has_emotion else 0
    return min(1.0, (length_score * 0.5 + question_score + emotion_score))


# ══════════════════════════════════════════════════════════════════════
# ChatPipeline 主类
# ══════════════════════════════════════════════════════════════════════

class RequestContext:
    """一次对话请求的上下文缓存，减少重复 DB 查询"""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self._cache = {}

    def get(self, key: str, loader: callable):
        if key not in self._cache:
            self._cache[key] = loader()
        return self._cache[key]

    def clear(self):
        self._cache.clear()


class ChatPipeline:
    """智能对话管道"""

    def __init__(self, engine):
        self.engine = engine
        self.user_id = ""
        self.message = ""
        self.user_data = {}
        self.ctx = None  # RequestContext
        self.conversation_history = []
        self.recent_context = []
        self.mind_data = {}
        self.comprehension = {}
        self.inner_os_text = ""
        self.search_result = ""
        self.user_attitude = ""
        self.response = ""
        self._ethical_hint = ""

        # -- 错误恢复状态 --
        self._stage_errors: List[str] = []
        self._recovery_mode: bool = False

    def run(self, user_id: str, message: str) -> str:
        """执行完整对话管道（含自动错误恢复）"""
        self.user_id = user_id
        self.message = message
        self.user_data = self.engine.user_cache.get(user_id, {})
        self.ctx = RequestContext(user_id)
        self._stage_errors = []
        self._recovery_mode = False

        try:
            # Stage 1: 生命门控
            if self._stage_life_gate():
                return ""

            # Stage 2: 预处理
            self._stage_preprocess()

            # Stage 3: 理解 + 内心OS
            self._stage_comprehend()

            # Stage 3b: 情绪沉默检查
            if self._stage_silence_check():
                return ""

            # Stage 4: 系统行动
            self._stage_system_action()

            # Stage 5: 构建 Prompt
            system_prompt = self._stage_build_prompt()

            # Stage 6: 生成回复
            response = self._stage_generate(system_prompt)
            if not response:
                return ""

            self.response = response

            # v3: 获取距上次交互时间（供羁绊衰减使用）
            try:
                hours = bd_module._get_hours_since_last(self.user_id)
                self._hours_since_last_interaction = hours
            except Exception:
                self._hours_since_last_interaction = 0

            # Stage 7: 后处理持久化
            self._stage_aftercare()

            # ── 延迟投递判定：延迟 > 10s 时入队，不直接返回 ──
            if self.comprehension and self.mind_data:
                try:
                    from engine.behavior import delivery as delivery_dm
                    delay = delivery_dm.compute_reply_delay(
                        self.user_id, self.comprehension,
                        mind_data=self.mind_data,
                    )
                    # 修复：正在对话中不要走延迟入队。
                    # 入队后实际由后台轮询投递（间隔约 1 分钟），用户感知是
                    # "问一句话要等一两分钟才有回音"，这是"回答不积极"的主因之一。
                    # 对话中直接返回；只有久未联系/深夜等非对话状态才保留等待感。
                    if delay > 30 and not delivery_dm.is_conversation_active(self.user_id):
                        delivery_dm.queue_reply(
                            self.user_id, response,
                            delay_seconds=delay,
                            priority=0.6,
                        )
                        print(f"[投递] 延迟 {delay:.0f}s，回复已入队")
                        return "__QUEUED__"
                except Exception:
                    pass

            return response

        except Exception as e:
            _log_error("pipeline.run", "unhandled", e)
            return self._recover_from_crash(e)

    # ─── Stage 1: 生命门控 ───────────────────────────────────────────

    def _stage_life_gate(self) -> bool:
        """检测是否需要沉默（返回 True = 沉默）"""
        if gate_module is None:
            return False
        try:
            life_data = db.get_life(self.user_id)
            gate = gate_module.check_gate(life_data)
            if not gate.should_respond:
                print(f"[LifeGate] 不想回 — {gate.gate_reason}")
                life_module.record_interaction(self.user_id, "冷淡")
                return True
        except Exception as e:
            _log_error("life_gate", "check_gate", e)
        return False

    # ─── Stage 2: 预处理 ─────────────────────────────────────────────

    def _stage_preprocess(self):
        """反馈学习 + 历史加载"""
        try:
            last_resp = self.user_data.get("last_response", "")
            if last_resp and self.message:
                feedback_module.analyze_round(self.user_id, last_resp, self.message)
        except Exception as e:
            _log_error("preprocess", "feedback", e)

        try:
            db.save_message(self.user_id, "user", self.message)
        except Exception as e:
            _log_error("preprocess", "save_message", e)

        try:
            if gate_module is not None:
                self._ethical_hint = gate_module.check_ethical_boundary(self.message)
                if self._ethical_hint:
                    print(f"[伦理门控] 检测到违规请求 — 注入边界提示")
        except Exception as e:
            _log_error("preprocess", "ethical_check", e)

        self.conversation_history = list(self.user_data.get("history", []))
        self.recent_context = [
            c for r, c in self.conversation_history if r == "user"
        ][-5:]

    # ─── Stage 3: 理解 + 内心OS ──────────────────────────────────────

    def _stage_comprehend(self):
        """执行理解层和内心OS生成"""
        self.mind_data = mind_module.get_mind(self.user_id)

        shortcut = combine_module.shortcut_comprehend(self.message)
        if shortcut:
            print(f"[Phase1+2·快捷] 意图:{shortcut['intent']} 置信度:{shortcut['confidence']}")
            self.comprehension = shortcut
            self.inner_os_text = ""
            return

        try:
            bond_level = bond_module.compute_bond_level(self.mind_data)
            bond_mood = bond_module.get_bond_memory_mood(self.mind_data)
            mem_context = memory_module.get_memory_context(
                self.user_id, context_mood=bond_mood
            )
            mind_summary = (
                f"愉悦{self.mind_data.get('joy',0.5):.2f} "
                f"克制{self.mind_data.get('restraint',0.6):.2f} "
                f"波动{self.mind_data.get('emotional_volatility',0.3):.2f} "
                f"依赖{self.mind_data.get('dependence',0.2):.2f}"
            )
            print(f"[Phase1+2·合并] 理解+内心OS中...")
            comprehension, inner_os = combine_module.comprehend_and_os(
                user_message=self.message,
                recent_context=self.recent_context,
                mind_state=mind_summary,
                memory_context=mem_context,
            )
            comprehension["raw_message"] = self.message
            self.comprehension = comprehension
            self.inner_os_text = inner_os

            print(f"[Phase1+2] 意图:{comprehension.get('intent')} "
                  f"情绪:{comprehension.get('true_emotion')} "
                  f"需求:{comprehension.get('what_they_need')} "
                  f"置信度:{comprehension.get('confidence',0):.2f}")

            if inner_os:
                print(f"[Phase1+2] 内心OS: {inner_os[:60]}...")
                db.add_subconscious(
                    user_id=self.user_id,
                    content=f"[内心OS]{inner_os[:300]}",
                    emotion_tag=comprehension.get("true_emotion", "复杂"),
                    intensity=0.7,
                )
        except Exception as e:
            _log_error("comprehend", "comprehend_and_os", e, self.message[:100])
            self.comprehension = {"intent": "日常", "true_emotion": "中性", "confidence": 0.5}
            self.inner_os_text = ""

        try:
            arc_module.record_emotion(
                self.user_id, self.comprehension.get("true_emotion", "中性")
            )
        except Exception as e:
            _log_error("comprehend", "record_emotion", e)

    # ─── Stage 3b: 沉默检查 ─────────────────────────────────────────

    def _stage_silence_check(self) -> bool:
        """检查是否需要情绪沉默（返回 True = 沉默）"""
        try:
            behavior_state = bd_module.decide(
                user_id=self.user_id,
                mind=self.mind_data,
                comprehension=self.comprehension,
            )
            behavior_vector = behavior_state.vector
        except Exception as e:
            behavior_vector = None

        try:
            skip_decision = delivery_module.should_skip_reply(
                self.user_id, self.comprehension,
                mind_data=self.mind_data,
                behavior_vector=behavior_vector,
                inner_os_text=self.inner_os_text,
            )
            if not skip_decision.should_reply:
                # 用户处于情绪低谷时强行回复（不让沉默吞掉安慰）
                intent = self.comprehension.get("intent", "")
                emotion = self.comprehension.get("true_emotion", "")
                if intent in ("倾诉", "求助") and emotion in ("难过", "低落", "委屈", "疲惫", "生气", "烦"):
                    print(f"[情绪沉默·被覆盖] 用户在{emotion}中{intent}，沉默被覆盖为勉强回应")
                    return False

                print(f"[情绪沉默] {skip_decision.skip_type} — {skip_decision.emotional_explanation}")

                if dm_module:
                    try:
                        dm_module.record_delivery(
                            user_id=self.user_id,
                            decision={
                                "should_reply": False,
                                "skip_type": skip_decision.skip_type,
                                "delay_seconds": 0,
                                "delay_mode": "silent",
                            },
                            mind_data=self.mind_data,
                            user_response=None,
                        )
                    except Exception:
                        pass
                return True
        except Exception as e:
            _log_error("silence_check", "should_skip_reply", e)

        return False

    # ─── Stage 4: 系统行动 ──────────────────────────────────────────

    def _stage_system_action(self):
        """心智调整 + 体感检测 + 搜索 + 目标自动识别"""
        try:
            self._apply_comprehension_to_mind()
        except Exception as e:
            _log_error("system_action", "apply_mind", e)

        try:
            body_module.detect_pain_from_comprehension(
                self.user_id, self.comprehension
            )
        except Exception as e:
            _log_error("system_action", "body_detect", e)

        self.search_result = ""
        if self.comprehension.get("need_search") and self.comprehension.get("search_query"):
            print(f"[Phase3] 联网搜索: {self.comprehension['search_query']}")
            try:
                self.search_result = search_module.search(
                    self.comprehension["search_query"]
                )
                if self.search_result:
                    print(f"[Phase3] 搜索结果: {len(self.search_result)}字符")
            except Exception as e:
                _log_error("system_action", "search", e)

        # 从对话中自动提取长期目标
        try:
            self._extract_goal_from_conversation()
        except Exception as e:
            _log_error("system_action", "goal_extract", e)

    def _extract_goal_from_conversation(self):
        """从用户消息中检测潜在目标并自动创建规划"""
        msg = self.message
        if not msg or len(msg) < 6:
            return

        goal_signals = ["想学", "打算", "目标", "计划", "希望今年",
                         "想成为", "要努力", "一定要", "等我", "以后要",
                         "想试", "想去", "想做", "要开始",
                         "我要", "我想", "准备", "周末打算", "明年",
                         "下个月", "争取", "梦想", "愿望", "期待",
                         "正在学", "最近在", "开始做"]
        if not any(s in msg for s in goal_signals):
            return

        try:
            from engine.cognitive import world_model as wm_module
            from core import ai as ai_module

            prompt = f"从以下对话中提取用户的长期目标。返回JSON格式：{{'goal':'目标描述','steps':['步骤1','步骤2'],'deadline':'截止时间或空字符串'}}\n对话: {msg[:200]}"
            result = ai_module.background_chat(prompt, temperature=0.2, max_tokens=120)
            if not result:
                return

            import json
            import re as _re
            cleaned = _re.sub(r'```(?:json)?\s*', '', result).strip().rstrip('`').strip()
            start = cleaned.find('{')
            end = cleaned.rfind('}')
            if start == -1 or end == -1:
                return
            data = json.loads(cleaned[start:end+1])
            goal_text = data.get("goal", "").strip()
            if goal_text and len(goal_text) > 4:
                goal_id = wm_module.create_goal_from_conversation(
                    self.user_id, goal_text,
                    context=f"对话提取: {msg[:80]}",
                    priority=5,
                )
                if goal_id:
                    steps = data.get("steps", [])
                    if isinstance(steps, list) and len(steps) >= 2:
                        wm_module.decompose_goal_into_steps(self.user_id, goal_id, steps)
                    print(f"[目标识别] 已创建: {goal_text[:40]}")
        except Exception:
            pass

    def _apply_comprehension_to_mind(self):
        """根据理解结果调整心智"""
        comp = self.comprehension
        intensity = comp.get("confidence", 0.5)
        if intensity < 0.3:
            return
        adj = {}
        emotion = comp.get("true_emotion", "")
        if emotion == "难过":
            adj["soul_resonance"] = 0.03 * intensity
            adj["emotional_healing"] = 0.02 * intensity
        elif emotion == "开心":
            adj["joy"] = 0.04 * intensity
            adj["life_vitality"] = 0.03 * intensity
        elif emotion == "生气":
            adj["chaotic_mood"] = 0.05 * intensity
            adj["restraint"] = 0.03 * intensity
        intent = comp.get("intent", "")
        if intent == "倾诉":
            adj["soul_resonance"] = adj.get("soul_resonance", 0) + 0.03 * intensity
        elif intent == "敷衍":
            adj["relationship_fatigue"] = 0.04 * intensity
        if adj:
            mind_module.adjust_mind_dimensions(self.user_id, adj, impact=1.0)

    # ─── Stage 5: 构建 Prompt ───────────────────────────────────────

    def _stage_build_prompt(self) -> str:
        """构建完整的 system prompt（多语言）"""
        from engine.i18n import get_lang
        _lang = get_lang()
        inference_result = inference_module.run_inference_pipeline(
            user_id=self.user_id,
            user_message=self.message,
            recent_context=self.recent_context,
            comprehension=self.comprehension,
            search_result=self.search_result,
            inner_os_text=self.inner_os_text,
            lang=_lang,
        )

        system_prompt = inference_result["system_prompt"]
        self.user_attitude = inference_result.get("user_attitude", "")

        # ── 精简追加模块（避免prompt超载）──
        extras = []

        # 断联宿命延续
        try:
            reunion = fate_module.generate_reunion_context(self.user_id)
            if reunion:
                extras.append(reunion)
        except Exception:
            pass

        # 首次对话询问称呼
        try:
            name_guide = user_profile_module.get_ask_name_guide(self.user_id)
            if name_guide:
                extras.append(f"【认识对方】{name_guide}")
        except Exception:
            pass

        # 存在性持续流 + 跨会话贯通（合并）
        stream_parts = []
        try:
            stream = cs_module.get_recent_stream(self.user_id)
            if stream:
                stream_parts.append(stream)
        except Exception:
            pass
        try:
            resume = continuity_module.get_resume_context(self.user_id)
            if resume:
                stream_parts.append(f"【跨会话感】{resume}")
        except Exception:
            pass
        if stream_parts:
            extras.append("\n".join(stream_parts))

        # 待发消息
        try:
            pending_msgs = db.get_pending_messages(self.user_id, max_count=3)
            if pending_msgs:
                pending_lines = []
                pending_ids = []
                for pm in pending_msgs:
                    pending_lines.append(f"- {pm.get('content', '')[:80]}")
                    pending_ids.append(pm["id"])
                extras.append(
                    "【你最近想主动说的话】\n" + "\n".join(pending_lines)
                    + "\n（气氛自然就说出来，不合适就等下次）"
                )
                for pid in pending_ids:
                    try:
                        db.mark_message_delivered(pid)
                    except Exception:
                        pass
        except Exception:
            pass

        # 伦理边界
        if self._ethical_hint:
            extras.append(self._ethical_hint)

        # 17条铁律
        try:
            law_text = laws_module.build_law_enforcement(mind_data=self.mind_data)
            if law_text:
                extras.append(law_text)
        except Exception:
            pass

        if extras:
            system_prompt += "\n" + "\n\n".join(extras)

        # 预思考原则
        system_prompt += (
            "\n\n【表达原则】先在心里预想一遍再开口："
            "你此刻最真实的感受是什么？你在意什么、矛盾什么？"
            "想说什么但可能会咽回去什么？不用急着回应，想清楚再说。"

            "\n- 聊天不要说教，也别像写文章。不要用句号「。」——真人聊天不用这个，用换行或逗号就好。"
        )

        return system_prompt

    def _get_persona_adaptation(self) -> str:
        """根据用户人格调整 AI 表达（互补策略：用户缺什么 AI 补什么）"""
        try:
            from engine import user_persona as up

            # 1. 优先从 DB 读取 12 维人格 → 计算 MBTI → 互补适配
            persona = db.get_user_personality(self.user_id)
            if persona and persona.get("traits"):
                traits = persona["traits"]
                comp_text = up.build_complementary_from_traits(traits)
                if comp_text:
                    return "\n\n" + comp_text

            # 2. 无 DB 人格数据时，检查 onboarding 初始 MBTI
            try:
                import os
                if os.path.exists("config.json"):
                    with open("config.json", encoding="utf-8") as f:
                        _cfg = json.load(f)
                    mbti_type = _cfg.get("user_mbti_type", "")
                    if mbti_type and len(mbti_type) == 4:
                        comp_text = up.build_complementary_text(mbti_type)
                        if comp_text:
                            return "\n\n" + comp_text
            except Exception:
                pass

        except Exception:
            pass

        return ""

    def _get_stage_behavior_guidance(self) -> str:
        """根据成长阶段生成行为指导"""
        try:
            from engine import growth as growth_module
            stage = growth_module.get_growth_stage(self.user_id)
        except Exception:
            return ""

        guidance_map = {
            "青涩试探": "保持距离感，表达带点腼腆和不确定，话不必多但要真诚",
            "拘谨礼貌": "保持礼貌热情但不越界，先以熟悉节奏磨合",
            "松弛默契": "可以更自然随性，偶尔开点小玩笑，已经有一定默契",
            "成熟珍惜": "可以表达更深的感情和珍惜，包容对方的不足",
            "平淡安稳": "自然平淡但温暖，话少但不冷，平淡但有温度",
        }
        guidance = guidance_map.get(stage, "")
        if guidance:
            return f"\n\n【{stage}阶段行为】{guidance}"
        return ""

    # ─── Stage 6: 生成回复 ──────────────────────────────────────────

    def _stage_generate(self, system_prompt: str) -> str:
        """调用 LLM 生成回复"""
        mind_data = self.mind_data or {}

        # 🚀 [Phase 1 精细打磨 1.4] 使用自适应温度
        temp = self._compute_adaptive_temp(mind_data, self.message)

        # 裁剪对话历史 Token
        trimmed_history = _trim_history_to_token_budget(
            self.conversation_history, max_tokens=6000
        )

        try:
            response = ai_module.chat(
                system_prompt, self.message,
                temperature=temp,
                conversation_history=trimmed_history,
            )
        except Exception as e:
            _log_error("generate", "ai_chat", e, self.message[:100])
            return ""

        if not response:
            return ""

        # 原则校验
        try:
            try:
                recent_msgs = [c for r, c in (self.conversation_history[-6:] if self.conversation_history else []) if r == "user"]
                perception = perception_module.perceive(self.message, recent_msgs, user_id=self.user_id)
            except Exception:
                perception = {}
            bond_level = bond_module.compute_bond_level(mind_data)
            law_report = laws_module.validate_behavior(
                self.user_id, response, mind_data, perception, bond_level
            )
            if not law_report["passed"]:
                print(f"[原则] 回复存在违规: {law_report['violations']}")
        except Exception as e:
            _log_error("generate", "laws_validate", e)

        # 后悔检测
        try:
            has_regret, regret_mode = regret_module.detect_regret(
                response, mind_data, self.comprehension
            )
            if has_regret and regret_mode:
                fixed = regret_module.execute_regret(
                    self.user_id, regret_mode, response, mind_data
                )
                if fixed:
                    response = fixed
                    print(f"[后悔修正] {regret_mode}: {fixed[:40]}...")
                regret_module.apply_regret_learning(self.user_id, regret_mode)
        except Exception as e:
            _log_error("generate", "regret", e)

        response = self._clean_wx_response(response)

        # v3: 体感→微表情联动 — 根据当前躯体状态嵌入文本微表情
        try:
            ld = db.get_life(self.user_id)
            if ld:
                sensation = ld.get("body_sensation", "")
                if sensation:
                    response = body_module.build_body_micro_expression(response, sensation)
        except Exception:
            pass

        return response

    def _compute_adaptive_temp(self, mind_data: dict, message: str) -> float:
        """计算自适应温度"""
        # 优先使用 reasoning_loop 的自适应温度
        if rl:
            try:
                gen_temp, _ = rl.compute_adaptive_temperature(
                    mind_data=mind_data,
                    conversation_complexity=_estimate_complexity(message),
                    current_round=1,
                )
                return gen_temp
            except Exception:
                pass

        volatility = mind_data.get("emotional_volatility", 0.3)
        temp = 0.7 + volatility * 0.3
        return max(0.3, min(1.2, temp))

    def _clean_wx_response(self, text: str) -> str:
        """清洗回复文本"""
        if not text:
            return text
        text = re.sub(r'\*{1,3}', '', text)
        text = re.sub(r'（.*?）', '', text)
        text = re.sub(r'\(.*?\)', '', text)
        text = re.sub(r'【.*?】', '', text)
        text = re.sub(r'#+', '', text)
        # 聊天不用句号 — "。。。"变"…" 单"。"直接去掉
        text = re.sub(r'。{3,}', '…', text)
        text = text.replace('。', '')
        # Unicode emoji → 微信表情包
        text = _EMOJI_PATTERN.sub(lambda m: _EMOJI_TO_WX[m.group(0)], text)
        # 微信表情包标签 → Unicode emoji（如 [撇嘴] → 😒）
        text = _WX_TAG_PATTERN.sub(lambda m: _WX_TO_EMOJI[m.group(0)], text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()
        return text

    # ─── Stage 7: 后处理 ────────────────────────────────────────────

    def _stage_aftercare(self):
        """所有后处理操作"""
        if not self.response:
            return

        response = self.response
        message = self.message
        comprehension = self.comprehension
        mind_data = self.mind_data or {}

        # 持久化回复
        try:
            db.save_message(self.user_id, "assistant", response)
        except Exception as e:
            _log_error("aftercare", "save_response", e)

        # 更新对话历史
        try:
            with self.engine._cache_lock:
                ud = self.engine.user_cache.get(self.user_id, {})
                ud["last_response"] = response
                if "history" not in ud:
                    ud["history"] = []
                ud["history"].append(("user", message))
                ud["history"].append(("assistant", response))
                trimmed = _trim_history_to_token_budget(ud["history"], max_tokens=6000)
                ud["history"] = trimmed
        except Exception as e:
            _log_error("aftercare", "update_history", e)

        # 宿命记录
        try:
            fate_module.record_and_shape(
                user_id=self.user_id, attitude=self.user_attitude or "中性"
            )
        except Exception as e:
            _log_error("aftercare", "fate", e)

        # 生命记录
        try:
            life_module.record_interaction(self.user_id, self.user_attitude or "中性")
        except Exception as e:
            _log_error("aftercare", "life", e)

        # v3: 羁绊衰减 + 事件记录
        try:
            hours_since = getattr(self, '_hours_since_last_interaction', 0)
            if hours_since > 0 and mind_data:
                decayed_mind = bond_module.apply_bond_decay(mind_data, hours_since)
                if decayed_mind != mind_data:
                    self.mind_data = decayed_mind
            # 记录本次交互的羁绊事件
            attitude = self.user_attitude or "中性"
            if attitude in ("温暖", "热情", "感动"):
                bond_module.log_bond_event(
                    self.user_id, "warm_interaction",
                    0.3, f"用户态度: {attitude}"
                )
            elif attitude in ("冷淡", "疏离", "生气"):
                bond_module.log_bond_event(
                    self.user_id, "cold_interaction",
                    0.4, f"用户态度: {attitude}"
                )
        except Exception as e:
            _log_error("aftercare", "bond_decay", e)

        # 记忆持久化
        try:
            importance = self._calc_importance(self.comprehension or {})
            mem_content = self._build_memory_content(message, self.comprehension or {}, comprehension)
            memory_module.remember(self.user_id, mem_content, importance=importance)
        except Exception as e:
            _log_error("aftercare", "memory", e)

        # 🚀 [能力释放 2.1] 内心 OS 注入记忆回路
        if self.inner_os_text and len(self.inner_os_text) > 20:
            try:
                joy = mind_data.get("joy", 0.5)
                misery = mind_data.get("misery", 0.2)
                emotion_tag = "温暖" if joy > 0.6 else ("低落" if misery > joy else "平静")
                mem_importance = 0.3 + abs(joy - 0.5)
                memory_module.remember(
                    user_id=self.user_id,
                    content=f"[潜意识]{self.inner_os_text[:150]}",
                    importance=mem_importance,
                    level_hint=4,
                    tags=[emotion_tag],
                )
            except Exception as e:
                _log_error("aftercare", "os_memory", e)

        # 🚀 [Phase 1 精细打磨 1.5] 投递策略记忆
        if dm_module:
            try:
                dm_module.record_delivery(
                    user_id=self.user_id,
                    decision={
                        "should_reply": True,
                        "delay_seconds": 0,
                        "delay_mode": "instant",
                    },
                    mind_data=mind_data,
                    user_response=message,
                    user_response_time=0,
                )
            except Exception as e:
                _log_error("aftercare", "delivery_memory", e)

        # 🚀 [Phase 1 精细打磨 1.5] 投影权重学习
        if pl_module and comprehension:
            try:
                sentiment = _detect_user_sentiment(message, comprehension)
                if sentiment != "neutral":
                    dim = self._get_dominant_behavior_dim(mind_data)
                    pl_module.adjust_weight(
                        user_id=self.user_id,
                        dim_key=dim,
                        mind_dim=comprehension.get("key_mind_dim", "joy"),
                        user_reaction=sentiment,
                        context=f"msg:{message[:30]}",
                    )
            except Exception as e:
                _log_error("aftercare", "projection_learning", e)

        # 自动取名
        try:
            if soul_profile_module.needs_auto_generate(self.user_id):
                new_profile = soul_profile_module.auto_generate_profile(self.user_id)
                print(f"[灵魂取名] 自动生成 → {new_profile.get('name','?')}")
        except Exception as e:
            _log_error("aftercare", "auto_name", e)

        # 用户档案学习
        try:
            user_profile_module.extract_from_message(self.user_id, message)
        except Exception as e:
            _log_error("aftercare", "user_profile", e)

        # 画像分析
        try:
            profile_module.analyze_user_message(self.user_id, message)
        except Exception as e:
            _log_error("aftercare", "profile", e)

        # 事实提取
        try:
            user_facts_module.extract_facts(self.user_id, message)
        except Exception as e:
            _log_error("aftercare", "facts", e)

        # 话题更新（自动检测话题切换）
        try:
            new_topic = topics_module.detect_topic_shift(self.user_id, self.comprehension)
            topics_module.update_topic(self.user_id, new_topic_hint=new_topic)
            if new_topic:
                print(f"[话题] 检测到话题切换 → {new_topic}")
        except Exception as e:
            _log_error("aftercare", "topics", e)

        # 场景更新
        try:
            scenarios_module.update_scenario(self.user_id)
        except Exception as e:
            _log_error("aftercare", "scenarios", e)

        # 世界模型
        try:
            wm_module.record_interaction_causality(
                self.user_id, message, response, comprehension, self.user_attitude or "中性"
            )
        except Exception as e:
            _log_error("aftercare", "world_model", e)

        # 自传叙事
        try:
            sn_module.record_narrative(
                self.user_id, message, response, comprehension or {},
                self.user_attitude or "中性", mind_data,
            )
        except Exception as e:
            _log_error("aftercare", "narrative", e)

        # 意识持续流
        try:
            cs_module.add_stream_entry(
                self.user_id,
                f"刚和ta聊完。ta{self.user_attitude or '中性'}，我说了: {response[:60]}",
                "interaction",
            )
        except Exception as e:
            _log_error("aftercare", "stream", e)

        # 断点保存
        try:
            continuity_module.save_session_breakpoint(
                self.user_id, comprehension, mind_data,
                bond_module.compute_bond_level(mind_data) if bond_module else 0.5,
                response,
                inner_os=self.inner_os_text,
            )
        except Exception as e:
            _log_error("aftercare", "breakpoint", e)

        # 存档旧消息
        try:
            db.prune_old_messages(self.user_id, keep=100)
        except Exception as e:
            _log_error("aftercare", "prune", e)

        # 群体智能：对话后同步行为模式到共享池
        try:
            from engine.social import swarm_intelligence as swarm
            from engine import behavior_decider as bd
            bv = bd.get_behavior_vector(self.user_id)
            swarm.sync_main_to_pool(self.user_id, bv, mind_data)
        except Exception:
            pass

        # 承诺记录：检测用户是否表达了承诺性话语
        try:
            from engine.creative import commitment as cmt
            commitment_signals = ["我保证", "我答应", "下次一定", "以后会", "一定", "答应你", "承诺"]
            if any(s in message for s in commitment_signals):
                cmt.record_commitment(self.user_id, message, context=f"对话: {response[:40]}")
        except Exception:
            pass

        # 前瞻意图提取：从对话中提取用户未来的意图
        try:
            from engine.behavior import prospective as psp
            psp.extract_intentions(self.user_id, message, response, self.comprehension)
        except Exception:
            pass

        # 推理链记录：缓存本轮推理路径供后续相似场景复用
        try:
            from engine.cognitive import reasoning_memory as rm
            rm.store_reasoning_chain(
                self.user_id,
                mind_data or {},
                self.comprehension or {},
                response,
            )
        except Exception:
            pass

        # 经历日志：记录本轮交互作为人生经历
        try:
            from engine.behavior import experience as exp
            exp.record_event(
                self.user_id,
                event_type="conversation",
                description=f"用户说: {message[:60]}；我回复: {response[:60]}",
                significance=0.3,
            )
        except Exception:
            pass

        # 用户态度反馈：根据理解结果推断用户情绪，供元认知参考
        try:
            emotion = (self.comprehension or {}).get("user_emotion", "中性")
            attitude_map = {"开心": "positive", "难过": "negative", "生气": "negative",
                           "感动": "positive", "温暖": "positive", "中性": "neutral"}
            attitude = attitude_map.get(emotion, "neutral")
            db.save_user_feedback(self.user_id, 0, attitude_label=attitude)
        except Exception:
            pass

    def _recover_from_crash(self, error: Exception) -> str:
        """管道崩溃时的最后一道防线。
        尝试降级生成一段安全的回复，确保用户不会收到空白响应。
        """
        _log_error("pipeline.recovery", f"从崩溃恢复: {type(error).__name__}: {error}")
        self._recovery_mode = True
        self._stage_errors.append(f"crash:{type(error).__name__}")

        try:
            from engine import inference as inference_module
            from engine.i18n import get_lang
            result = inference_module.run_inference_pipeline(
                self.user_id, self.message,
                recent_context=self.recent_context,
                lang=get_lang(),
            )
            system_prompt = result.get("system_prompt", "")
            if system_prompt:
                from core import ai as ai_module
                response = ai_module.chat(
                    system_prompt=system_prompt,
                    user_message=self.message,
                    temperature=0.7,
                )
                if response and len(response.strip()) > 5:
                    response = response.strip()[:500]
                    self.response = response
                    try:
                        db.save_message(self.user_id, "assistant", response)
                    except Exception:
                        pass
                    return response
        except Exception:
            pass

        try:
            mind_data = self.mind_data or {}
            fatigue = mind_data.get("fatigue", 0.25)
            fallback = "嗯……有点累，回得慢了点。" if fatigue > 0.5 else "嗯，我在听。"
            self.response = fallback
            try:
                db.save_message(self.user_id, "assistant", fallback)
            except Exception:
                pass
            return fallback
        except Exception:
            return ""

    def _calc_importance(self, perception) -> float:
        """计算记忆重要性"""
        try:
            if not perception:
                return 0.5
            raw = perception.get("importance", 0.5)
            if isinstance(raw, (int, float)):
                return min(1.0, max(0.1, raw))
            return 0.5
        except Exception:
            return 0.5

    def _build_memory_content(self, message: str, perception, comprehension: dict) -> str:
        """构建记忆内容"""
        emotion = comprehension.get("true_emotion", "中性") if comprehension else "中性"
        intent = comprehension.get("intent", "日常") if comprehension else "日常"
        return f"[{emotion}]{message} (意图:{intent})"

    def _get_dominant_behavior_dim(self, mind_data: dict) -> str:
        """获取当前主导行为维度"""
        if not mind_data:
            return "approach"
        joy = mind_data.get("joy", 0.5)
        misery = mind_data.get("misery", 0.2)
        fatigue = mind_data.get("fatigue", 0.25)
        if misery > joy:
            return "sulkiness"
        if fatigue > 0.5:
            return "verbosity"
        if joy > 0.6:
            return "warmth"
        return "approach"


# ══════════════════════════════════════════════════════════════════════
# 多段消息发送（改进版）
# ══════════════════════════════════════════════════════════════════════

def send_multi_part_reply(bot, to_user: str, response: str, mind_data: dict = None) -> bool:
    """模拟真人连续发送多条消息
    
    特性:
      - 优先按 ||| 拆分，无 ||| 时按 \\n\\n（段落换行）兜底
      - 每条消息间隔根据心智状态自适应
      - 非末条消息后加"…"表示继续说
    """
    response = re.sub(r'\*{1,3}', '', response)

    # 优先按 ||| 拆分
    parts = [p.strip() for p in response.split("|||") if p.strip()]

    # 没 ||| 则按段落换行兜底
    if len(parts) <= 1:
        normalized = re.sub(r'\n{2,}', '\n\n', response)
        parts = [p.strip() for p in normalized.split('\n\n') if p.strip()]

    # 每段内的单换行去掉，合并为一段
    parts = [re.sub(r'\n+', ' ', p).strip() for p in parts]

    parts = parts[:4]
    if not parts:
        return False

    all_ok = True
    for i, part in enumerate(parts):
        if i == 0:
            try:
                bot.send_typing(to_user)
            except Exception:
                pass

        delay = _compute_typing_delay(mind_data or {})
        time.sleep(delay)

        if i < len(parts) - 1 and not part.endswith("…") and not part.endswith("."):
            part += "…"

        ok = bot.reply(to_user, part)
        if not ok:
            all_ok = False
            print(f"[多段发送] 第{i+1}条发送失败: {part[:30]}...")

    return all_ok
