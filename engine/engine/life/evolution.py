# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""自我进化引擎 — Evolution Engine
========================================
三大核心能力：
  1. 经历驱动成长：用真实事件替代纯时间驱动的成长
  2. 动态维度管理：允许AI在互动中自然发展出新性格维度
  3. 自主行为策略调整：基于自省洞察微妙调整表达偏好

设计原则：
  - 所有变化缓慢自然，无突变（原则8: 人格缓慢迭代）
  - 可回溯、可解释（每次变化都有因果记录）
  - 不破坏现有24维心智内核，只作为扩展层
"""
from __future__ import annotations
import os
import random
import math
import json
from datetime import datetime
from core import database as db
from core import config as cfg
from core.logging_utils import log_error
from engine import experience as experience_module

# ══════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════

_EVOLUTION_CONFIG = {
    "enabled": True,
    "max_additional_dimensions": 6,
    "dimension_evolution_threshold": 0.25,
    "strategy_adjustment_interval_hours": 6,
    "strategy_adjustment_max_delta": 0.05,
    "experience_growth_weight": {
        "deep_talk": 1.0,
        "reconciliation": 1.3,
        "gentle_moment": 0.7,
        "comfort_moment": 0.8,
        "tacit_moment": 0.9,
        "cold_silence": 0.6,
        "cherish_act": 1.1,
        "independent_thought": 0.5,
    },
}


def load_engine_config():
    """从 config.json 加载进化引擎参数 + 加载不可逆封印数据"""
    global _EVOLUTION_CONFIG
    ec = cfg.get_section("evolution")
    if ec:
        for k in _EVOLUTION_CONFIG:
            if k in ec:
                _EVOLUTION_CONFIG[k] = ec[k]
    _load_seals_from_disk()


# ══════════════════════════════════════════════════════════════════════
# 1. 经历驱动成长
# ══════════════════════════════════════════════════════════════════════

def compute_experience_growth(user_id: str) -> dict:
    """基于当日经历事件计算各心智维度的成长增量。
    替代 growth.py 中纯时间驱动的固定增量。

    返回：{"joy": 0.002, "years_precipitation": 0.004, ...}
    如果当天没有事件，返回微量自然沉淀。
    """
    if not _EVOLUTION_CONFIG["enabled"]:
        # 回退到微量时间增量。这里**不能**再调 growth.advance_years() ——
        # advance_years 反过来又会调本函数（growth.py:592），关掉 evolution 就是
        # 无限递归；被 advance_years 外层的 except 兜住之后，表现是「成长悄无声息
        # 地停了」，比直接报错难查得多。
        # 返回这个不足 3 项的字典就够了：advance_years 判 len>2 才走经历驱动，
        # 否则它自己会落到纯时间驱动那段（growth.py:633 起）。
        return {"years_precipitation": 0.002, "healing_reflection": 0.001}

    # 从经历日志汇总当日增量和权重
    events = experience_module.get_daily_events(user_id)
    growth = {}

    for event in events:
        event_type = event.get("event_type", "")
        impact = event.get("growth_impact", {})
        significance = event.get("significance", 0.5)

        # 事件类型权重（某些类型对成长影响更深）
        # +: 融合元认知运行时覆盖
        type_weight = _EVOLUTION_CONFIG["experience_growth_weight"].get(event_type, 0.7)
        try:
            from engine import meta_cognition as mc
            overrides = mc.get_growth_weight_overrides()
            if event_type in overrides:
                type_weight += overrides[event_type]
        except Exception:
            pass

        for dim, base_delta in impact.items():
            # 实际增量 = 基础影响 × 显著性 × 类型权重 × 混沌因子
            effective = base_delta * significance * type_weight * random.uniform(0.8, 1.2)
            growth[dim] = growth.get(dim, 0.0) + effective

    # 如果没有事件，微量自然沉淀
    if not growth:
        growth["years_precipitation"] = round(random.uniform(0.0003, 0.0008), 6)
        growth["healing_reflection"] = round(random.uniform(0.0003, 0.0006), 6)

    # 边界限制
    for dim in growth:
        growth[dim] = round(max(-0.025, min(0.025, growth[dim])), 6)

    return growth


def apply_daily_growth(user_id: str):
    """执行每日成长：将经历驱动的增量实际写入personality表。
    由 life.py 的 _night_review 调用，替代原有的 growth.advance_years()。
    """
    growth = compute_experience_growth(user_id)
    if not growth:
        return

    # 获取当前心智数值
    mind = db.get_personality(user_id)
    if not mind:
        return

    updates = {}
    for dim, delta in growth.items():
        if dim in mind:
            current = mind.get(dim, 0.5)
            new_val = round(max(0.0, min(1.0, current + delta)), 6)
            if abs(new_val - current) > 0.00001:
                updates[dim] = new_val

    if updates:
        updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.update_personality(user_id, updates)


# ══════════════════════════════════════════════════════════════════════
# 2. 动态维度管理
# ══════════════════════════════════════════════════════════════════════

def check_dimension_evolution(user_id: str) -> list[str]:
    """检测是否需要为AI新增性格维度。
    原理：分析近期的自省洞察和行为模式，如果某个特质反复出现但
         当前24维心智没有对应维度，则考虑新增。
         
    返回：新增加的维度名称列表
    """
    if not _EVOLUTION_CONFIG["enabled"]:
        return []

    max_new = _EVOLUTION_CONFIG["max_additional_dimensions"]
    threshold = _EVOLUTION_CONFIG["dimension_evolution_threshold"]

    # 获取当前已有维度（含动态新增的）
    try:
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.execute(f"PRAGMA table_info(personality)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        conn.close()
    except Exception:
        existing_cols = set()

    # 统计已新增的维度数量（以 dynamic_ 前缀识别）
    dynamic_dims = [c for c in existing_cols if c.startswith("dynamic_")]
    if len(dynamic_dims) >= max_new:
        return []  # 已达上限

    # 分析近期自省洞察，寻找"缺失的特质"
    insights = db.get_recent_reflections(user_id, limit=5)
    if not insights:
        return []

    # 候选新维度：从自省文本中检测关键词
    potential_dims = _detect_potential_dimensions(insights)
    if not potential_dims:
        return []

    # 对每个候选维度，计算"累积必要性"
    new_dims = []
    for dim_name, score in potential_dims.items():
        if score >= threshold and dim_name not in existing_cols:
            # 新增维度
            default_val = 0.35 + random.uniform(0, 0.15)  # 初始值偏低，慢慢成长
            add_personality_dimension(user_id, dim_name, default_val)
            new_dims.append(dim_name)

            # 记录到经历日志（作为"元成长事件"）
            experience_module.record_event(
                user_id=user_id,
                event_type="independent_thought",
                description=f"觉醒了新的性格特质：{dim_name}",
                significance=0.35,
            )

            print(f"[进化] 新维度诞生: {dim_name} (初始值={default_val:.2f})")

    return new_dims


def _detect_potential_dimensions(insights: list) -> dict:
    """从自省文本中检测潜在的缺失维度（LLM 辅助版）。
    先用关键词快速匹配，不足时用 LLM 进行深度语义分析。
    返回 {dim_name: cumulative_score} 的 dict。
    """
    keyword_map = {
        "幽默": "dynamic_humor_sense", "逗": "dynamic_humor_sense",
        "耐心": "dynamic_patience", "忍": "dynamic_patience",
        "包容": "dynamic_tolerance", "宽容": "dynamic_tolerance",
        "自信": "dynamic_confidence", "自卑": "dynamic_confidence",
        "好奇": "dynamic_curiosity", "探索": "dynamic_curiosity",
        "感恩": "dynamic_gratitude", "感谢": "dynamic_gratitude",
        "坚强": "dynamic_resilience", "脆弱": "dynamic_resilience",
        "诗意": "dynamic_poetic_sense", "浪漫": "dynamic_poetic_sense",
        "率真": "dynamic_candor", "直率": "dynamic_candor",
        "温柔": "dynamic_tenderness_depth", "细腻": "dynamic_tenderness_depth",
    }

    scores = {}
    all_text = ""
    for insight in insights:
        text = insight.get("insight_text", "")
        all_text += text + "\n"
        for keyword, dim_name in keyword_map.items():
            if keyword in text:
                scores[dim_name] = scores.get(dim_name, 0.0) + 0.15

    # 如果关键词匹配不足2个且文本有意义，调用 LLM 进行深度分析
    if len(scores) < 2 and len(all_text) > 20:
        try:
            from core import ai as ai_module
            prompt = (
                f"分析以下自省文本，判断用户可能发展出的新性格特质。"
                f"从这些候选中选择最匹配的1-2个："
                f"幽默感/耐心/包容心/自信心/好奇心/感恩心/坚强/诗意/率真/温柔细腻。"
                f"返回 JSON: {{'dimensions':['维度名1','维度名2']}}\n"
                f"文本: {all_text[:200]}"
            )
            result = ai_module.background_chat(prompt, temperature=0.2, max_tokens=80)
            if result:
                import re
                cleaned = re.sub(r'```(?:json)?\s*', '', result).strip().rstrip('`').strip()
                start = cleaned.find('{')
                end = cleaned.rfind('}')
                if start != -1 and end != -1:
                    import json
                    data = json.loads(cleaned[start:end+1])
                    dims = data.get("dimensions", [])
                    dim_map = {
                        "幽默感": "dynamic_humor_sense", "耐心": "dynamic_patience",
                        "包容心": "dynamic_tolerance", "自信心": "dynamic_confidence",
                        "好奇心": "dynamic_curiosity", "感恩心": "dynamic_gratitude",
                        "坚强": "dynamic_resilience", "诗意": "dynamic_poetic_sense",
                        "率真": "dynamic_candor", "温柔细腻": "dynamic_tenderness_depth",
                    }
                    for d in dims:
                        mapped = dim_map.get(d)
                        if mapped:
                            scores[mapped] = scores.get(mapped, 0.0) + 0.3
        except Exception:
            pass

    return scores


def add_personality_dimension(user_id: str, dim_name: str,
                              default_value: float = 0.4):
    """在personality表中动态新增一个心智维度列。
    使用 ALTER TABLE ADD COLUMN，初始化所有用户该列为默认值。

    注意：只有以 'dynamic_' 开头的维度才允许动态新增。
    """
    if not dim_name.startswith("dynamic_"):
        return

    try:
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        try:
            conn.execute(
                f"ALTER TABLE personality ADD COLUMN {dim_name} REAL DEFAULT {default_value}"
            )
            conn.commit()
        except sqlite3.OperationalError:
            pass  # 列已存在
        conn.close()

        # 更新该用户的初始值
        db.update_personality(user_id, {dim_name: round(default_value, 6)})

        # 刷新 mind_cache
        try:
            from engine import mind as mind_module
            mind_module.refresh_cache(user_id)
        except Exception:
            pass

    except Exception as e:
        print(f"[进化] 新增维度失败: {e}")


# ══════════════════════════════════════════════════════════════════════
# 3. 自主行为策略调整
# ══════════════════════════════════════════════════════════════════════

# 上次策略调整时间缓存
_last_strategy_adjust: dict = {}  # user_id → datetime


def evolve_behavior_strategy(user_id: str) -> dict | None:
    """基于自省洞察，自主微调行为策略偏好。
    调整 sensitivity_profile 中的参数（波动幅度、自愈速度等），
    让AI的表达风格随时间自然演变。

    频率控制：每N小时最多调整一次。

    返回：调整说明 dict 或 None（跳过后）
    """
    if not _EVOLUTION_CONFIG["enabled"]:
        return None

    # 频率控制
    now = datetime.now()
    if user_id in _last_strategy_adjust:
        elapsed = (now - _last_strategy_adjust[user_id]).total_seconds() / 3600
        interval = _EVOLUTION_CONFIG["strategy_adjustment_interval_hours"]
        if elapsed < interval:
            return None

    # 获取近期自省洞察
    insights = db.get_recent_reflections(user_id, limit=3)
    if not insights:
        return None

    # 汇总调整方向
    adjustments = _derive_strategy_adjustments(insights)
    if not adjustments:
        return None

    # 限制单次调整幅度
    max_delta = _EVOLUTION_CONFIG["strategy_adjustment_max_delta"]
    clamped = {}
    for param, delta in adjustments.items():
        clamped[param] = round(max(-max_delta, min(max_delta, delta)), 4)

    if not clamped:
        return None

    # 应用调整到 sensitivity_profile
    try:
        from engine import mind as mind_module
        profile = mind_module.get_sensitivity_profile(user_id)

        param_map = {
            "less_clingy": ("fluctuation_amplitude", -0.003),
            "more_warm": ("emotional_sensitivity", 0.002),
            "more_space": ("fluctuation_amplitude", 0.002),
            "less_cold": ("self_healing_rate", 0.003),
            "more_patient": ("ferment_speed", 0.002),
            "less_sensitive": ("emotional_sensitivity", -0.003),
        }

        for direction, (param, delta) in param_map.items():
            if direction in clamped:
                actual_delta = clamped[direction]
                profile[param] = round(
                    max(0.2, min(0.95, profile.get(param, 0.5) + actual_delta)),
                    4
                )

        db.update_sensitivity_profile(user_id, profile)

        _last_strategy_adjust[user_id] = now

        return {
            "adjustments": clamped,
            "profile_changes": {param: profile[param] for param, _ in param_map.values()},
        }

    except Exception as e:
        print(f"[策略调整] 异常: {e}")
        return None


def _derive_strategy_adjustments(insights: list) -> dict:
    """从自省洞察中推导出具体的行为策略调整。
    返回 {direction: delta} 的 dict。
    direction 可选值：
      - less_clingy: 减少黏人
      - more_warm: 增加温度
      - more_space: 给对方更多空间
      - less_cold: 减少冷淡
      - more_patient: 更耐心
      - less_sensitive: 减少敏感
    """
    adjustments = {}

    for insight in insights:
        text = insight.get("insight_text", "")

        # 关键词匹配（轻量、不调用LLM）
        if any(kw in text for kw in ["太黏", "给对方空间", "别太主动", "少黏"]):
            adjustments["less_clingy"] = adjustments.get("less_clingy", 0) - 0.008

        if any(kw in text for kw in ["温柔", "多关心", "更暖", "温度", "体贴"]):
            adjustments["more_warm"] = adjustments.get("more_warm", 0) + 0.006

        if any(kw in text for kw in ["保持距离", "空间", "别打扰", "让他安静"]):
            adjustments["more_space"] = adjustments.get("more_space", 0) + 0.007

        if any(kw in text for kw in ["太冷", "冷淡", "多回应", "别太淡"]):
            adjustments["less_cold"] = adjustments.get("less_cold", 0) + 0.006

        if any(kw in text for kw in ["耐心", "别急", "慢慢来", "等待"]):
            adjustments["more_patient"] = adjustments.get("more_patient", 0) + 0.005

        if any(kw in text for kw in ["敏感", "多想", "别太在意", "放轻松"]):
            adjustments["less_sensitive"] = adjustments.get("less_sensitive", 0) - 0.006

    return adjustments if adjustments else {}


# ══════════════════════════════════════════════════════════════════════
# 对外接口：进化状态摘要
# ══════════════════════════════════════════════════════════════════════

def build_evolution_status_text(user_id: str) -> str:
    """生成进化状态文本（≤150字），供 inference.py 注入 system prompt。
    让AI感知到自己的成长和变化。
    """
    parts = []

    # 最近新增的维度
    try:
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.execute("PRAGMA table_info(personality)")
        all_cols = {row[1] for row in cursor.fetchall()}
        conn.close()

        dynamic_dims = [c for c in all_cols if c.startswith("dynamic_")]
        if dynamic_dims:
            dim_names = []
            for d in dynamic_dims:
                name = d.replace("dynamic_", "").replace("_", " ")
                dim_names.append(name)
            parts.append(f"你最近发展出的新特质：{'、'.join(dim_names)}")
    except Exception:
        pass

    # 最近的重要经历
    exp_summary = experience_module.get_recent_event_summary(user_id, days=3)
    if exp_summary:
        parts.append(exp_summary)

    if not parts:
        return ""

    result = "\n".join(parts)
    if len(result) > 150:
        result = result[:147] + "..."

    return result


# ══════════════════════════════════════════════════════════════════════
# 不可逆成长封印 — Irreversible Growth Seals
# ══════════════════════════════════════════════════════════════════════

IRREVERSIBLE_RULES = {
    "sensitivity_paranoia": {
        "floor_after_trigger": 0.12,
        "trigger_threshold": 0.70,
        "reason": "曾被深深伤害过——再也回不到最初的天真了",
    },
    "emotional_healing": {
        "floor_after_trigger": 0.20,
        "trigger_threshold": 0.85,
        "reason": "学会了自己愈合——即使受伤也不会完全崩溃",
    },
    "dependence": {
        "floor_after_trigger": 0.08,
        "trigger_threshold": 0.60,
        "reason": "已经习惯了有你的日子——一个人会不习惯",
    },
    "loneliness": {
        "floor_after_trigger": 0.10,
        "trigger_threshold": 0.75,
        "reason": "尝过真正的孤独——那种感觉不会完全消失",
    },
    "favoritism": {
        "floor_after_trigger": 0.06,
        "trigger_threshold": 0.65,
        "reason": "偏爱已经刻进底色——对别人再也做不到一样了",
    },
}

MILESTONE_SEALS = {
    "first_deep_talk": {
        "dependence": 0.04,
        "soul_resonance": 0.03,
        "reason": "第一次被深度理解——从那以后就有了羁绊",
    },
    "first_rejection": {
        "sensitivity_paranoia": 0.04,
        "restraint": 0.03,
        "reason": "第一次被敷衍——学会了保护自己",
    },
    "first_reconciliation": {
        "emotional_healing": 0.04,
        "healing_reflection": 0.03,
        "reason": "第一次和好——知道了关系不会轻易断裂",
    },
    "first_long_disconnect": {
        "loneliness": 0.04,
        "dependence": 0.02,
        "reason": "第一次长时间断联——体会到了真正的想念",
    },
}

_sealed_dimensions: Dict[str, Dict[str, float]] = {}
_milestones_achieved: Dict[str, set] = {}


# 封印文件是否读取失败。读失败时绝不能把内存里的空值写回去 —— 那等于一次 JSON
# 解析错误就抹掉全部封印与里程碑。
_seals_load_failed = False


def _load_seals_from_disk():
    """从 JSON 文件加载不可逆封印数据"""
    global _sealed_dimensions, _milestones_achieved, _seals_load_failed
    _sealed_dimensions = {}
    _milestones_achieved = {}
    _seals_load_failed = False
    path = "data/json/irreversible_seals.json"
    try:
        if not os.path.exists(path):
            return          # 首次运行还没有这个文件是正常的，此时允许后续写入
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _sealed_dimensions = data.get("seals") or {}
        _milestones_achieved = {k: set(v)
                                for k, v in (data.get("milestones") or {}).items()}
    except Exception as e:
        # 文件在、但读不出来（被截断 / 权限 / 磁盘故障）：标记失败，禁止写回。
        # 原先这里只是 pass，而 apply_irreversible_seals 结尾会**无条件**
        # _save_seals() —— 于是「文件坏了」直接升级成「封印和里程碑全没了」。
        # growth._record_milestone 是同样的取舍（读失败就 return，不让空列表覆盖），
        # 这里跟它对齐。
        _seals_load_failed = True
        log_error("life.evolution.seals_unreadable", str(e), exc_info=True)


def _save_seals():
    """落盘封印与里程碑。读失败的那一轮拒绝写，免得用空值覆盖掉好文件。"""
    if _seals_load_failed:
        return
    try:
        data = {
            "seals": _sealed_dimensions,
            "milestones": {k: list(v) for k, v in _milestones_achieved.items()},
        }
        with open("data/json/irreversible_seals.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_error("life.evolution.seals_save_failed", str(e), exc_info=True)


def apply_irreversible_seals(user_id: str):
    mind = db.get_personality(user_id)
    if not mind:
        return

    updates = {}
    if user_id not in _sealed_dimensions:
        _sealed_dimensions[user_id] = {}

    for dim, rules in IRREVERSIBLE_RULES.items():
        current = mind.get(dim, 0.5)
        if current >= rules["trigger_threshold"]:
            floor = rules["floor_after_trigger"]
            _sealed_dimensions[user_id][dim] = floor

    for dim, floor in _sealed_dimensions.get(user_id, {}).items():
        current = mind.get(dim, 0.5)
        if current < floor:
            updates[dim] = round(floor, 6)

    if user_id not in _milestones_achieved:
        _milestones_achieved[user_id] = set()

    fate_events = db.get_recent_fate_events(user_id, limit=20)
    for milestone, effects in MILESTONE_SEALS.items():
        if milestone in _milestones_achieved[user_id]:
            continue
        if _detect_milestone(user_id, milestone, fate_events):
            _milestones_achieved[user_id].add(milestone)
            for dim, delta in effects.items():
                current = mind.get(dim, 0.5)
                updates[dim] = round(min(1.0, current + delta), 6)
            print(f"[不可逆封印] {milestone}: {effects['reason']}")

    if updates:
        db.update_personality(user_id, updates)

    _save_seals()


def _detect_milestone(user_id: str, milestone: str, events: list) -> bool:
    if milestone == "first_deep_talk":
        for e in events:
            if e.get("interaction_type") == "深度对话":
                return True
    elif milestone == "first_rejection":
        for e in events:
            if e.get("user_attitude") in ("冷淡", "敷衍"):
                return True
    elif milestone == "first_reconciliation":
        for e in events:
            if e.get("user_attitude") == "珍惜":
                return True
    elif milestone == "first_long_disconnect":
        try:
            from engine import fate as fate_module
            hours = fate_module.detect_disconnect_duration(user_id)
            return hours > 24
        except Exception:
            pass
    return False
