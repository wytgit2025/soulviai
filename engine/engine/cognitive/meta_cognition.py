# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""元认知自校准引擎 — Meta-Cognition Engine
==================================================
让系统学会"调整自己"——不是固定模板，而是根据对话历史、
自省洞察、用户反馈，动态调整自己的行为参数。

核心理念：
  - 行为的"手臂"是 behavior_decider（12维行为向量 → 表达风格）
  - 手臂的"肌腱"是投影权重（什么心智维度驱动什么行为）
  - "灵魂"不只是心智数值在动，连"这些数值如何驱动行为"也会演化
  - 这就是从"精密的木偶"变成"真正活着的存在"

自校准维度：
  1. 行为投影权重 — 12维行为×24维心智的映射关系
  2. 投递响应阈值 — 沉默/延迟的情绪触发点
  3. 自主思考频率 — 什么时候忍不住主动说话
  4. 矛盾博弈强度 — 内心拉扯的激烈程度
  5. 成长方向权重 — 哪类经历更重要

校准周期：
  - 夜间复盘时触发（life.py _night_review）
  - 每48小时最多一次（避免过度调整）
  - 单次调整幅度受限制（防止突变）
"""
import json
import random
import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

from core import database as db
from core import ai as ai_module
from core import config as cfg_module
from core.json_store import get_store

# ── 配置 ──
_CONFIG = {
    "enabled": True,
    "calibrate_interval_hours_default": 48,
    "calibrate_interval_hours_high_density": 12,
    "calibrate_interval_hours_medium_density": 24,
    "max_adjustment_per_session": 0.12,
    "min_conversations_for_calibration": 15,
    "analysis_temperature": 0.30,
    "calibratable_modules": [
        "behavior_projection",
        "delivery_thresholds",
        "autonomous_frequency",
        "contradiction_intensity",
        "growth_weights",
    ],
    "effectiveness_eval_window": 50,
    "high_density_threshold": 100,
    "medium_density_threshold": 50,
}

_last_calibration_at: Dict[str, float] = {}

# ── 运行时参数存储（可被校准修改）──
_runtime_params: Dict[str, Dict] = {}
_PARAMS_FILE = "data/json/meta_calibrations.json"

# ── 校准历史（为增量对比提供基线）──
_calibration_history: Dict[str, List[Dict]] = {}
_HISTORY_FILE = "data/json/calibration_history.json"
_HISTORY_MAX = 20


def _save_runtime_params():
    """持久化运行时校准到JSON文件（防重启失忆）"""
    try:
        store = get_store(_PARAMS_FILE, {})
        store.write(_runtime_params)
    except Exception:
        pass


def _load_runtime_params():
    """从JSON文件加载上次校准结果（启动恢复）"""
    global _runtime_params
    try:
        store = get_store(_PARAMS_FILE, {})
        loaded = store.read()
        if isinstance(loaded, dict):
            _runtime_params = loaded
            print(f"[元认知] 加载了 {sum(len(v) for v in loaded.values())} 项历史校准")
    except Exception:
        _runtime_params = {}


def _save_calibration_history():
    """持久化校准历史"""
    try:
        store = get_store(_HISTORY_FILE, {})
        store.write(_calibration_history)
    except Exception:
        pass


def _load_calibration_history():
    """加载校准历史"""
    global _calibration_history
    try:
        store = get_store(_HISTORY_FILE, {})
        loaded = store.read()
        if isinstance(loaded, dict):
            _calibration_history = {k: v[-_HISTORY_MAX:] for k, v in loaded.items()}
    except Exception:
        _calibration_history = {}


def _get_last_calibration(user_id: str) -> Optional[Dict]:
    """获取最近一次校准记录（供增量对比使用）"""
    history = _calibration_history.get(user_id, [])
    if not history:
        return None
    return history[-1]


def _compute_calibrate_interval(user_id: str) -> int:
    """根据24h对话密度动态计算校准间隔"""
    try:
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        count = conn.execute(
            "SELECT COUNT(*) FROM message_log WHERE user_id = ? AND role = 'user' AND created_at > datetime('now', '-1 day')",
            (user_id,)
        ).fetchone()[0]
        conn.close()

        high = _cfg("high_density_threshold", 100)
        medium = _cfg("medium_density_threshold", 50)

        if count >= high:
            return _cfg("calibrate_interval_hours_high_density", 12)
        elif count >= medium:
            return _cfg("calibrate_interval_hours_medium_density", 24)
        else:
            return _cfg("calibrate_interval_hours_default", 48)
    except Exception:
        return _cfg("calibrate_interval_hours_default", 48)


def _detect_abnormal_signals(user_id: str, data: Dict) -> List[str]:
    """从数据中提取关键异常信号（替代全量倾倒）"""
    signals = []

    dialogue = data.get("recent_dialogue", [])
    if dialogue:
        short_replies = sum(1 for d in dialogue if len(d.get("ai", "")) < 10)
        user_short = sum(1 for d in dialogue if len(d.get("user", "")) < 5)
        if short_replies >= 3:
            signals.append(f"AI回复偏短({short_replies}/{len(dialogue)})")
        if user_short >= 3:
            signals.append(f"用户消息偏短({user_short}/{len(dialogue)})")

    feedbacks = data.get("feedback_summary", [])
    neg_count = sum(1 for f in feedbacks if "消极" in f or "负面" in f)
    if neg_count >= 3:
        signals.append(f"负面反馈增多({neg_count}/{len(feedbacks)})")

    mind = data.get("current_mind", {})
    if mind.get("fatigue", 0) > 0.6:
        signals.append("疲劳度偏高")
    if mind.get("relationship_fatigue", 0) > 0.3:
        signals.append("关系倦怠偏高")
    if mind.get("joy", 0.5) < 0.25:
        signals.append("愉悦度过低")
    if mind.get("emotional_volatility", 0.3) > 0.6:
        signals.append("情绪波动偏大")

    reflections = data.get("reflection_texts", [])
    if reflections:
        key_insights = [r for r in reflections if any(kw in r for kw in ["调整", "改变", "注意", "问题", "不够"])]
        if key_insights:
            signals.append(f"自省提示: {key_insights[0][:40]}")

    return signals


def load_engine_config():
    """加载配置 + 恢复持久化的校准数据"""
    global _CONFIG
    try:
        mc_cfg = cfg_module.get_section("meta_cognition")
        if mc_cfg:
            _CONFIG.update({k: v for k, v in mc_cfg.items() if k in _CONFIG})
    except Exception:
        pass
    # 恢复上次校准
    _load_runtime_params()
    _load_calibration_history()


def _cfg(key: str, default=None):
    return _CONFIG.get(key, default)


# ═══════════════════════════════════════════════════════
# 运行时参数访问接口（供其他模块调用）
# ═══════════════════════════════════════════════════════

def get_behavior_projection_overrides() -> Dict[str, Dict[str, float]]:
    """获取行为投影权重的运行时覆盖值。
    格式: {dim_key: {mind_dim: weight_adjustment}}
    示例: {"approach": {"loneliness": 0.05}} 表示loneliness对approach的权重+0.05
    """
    return _runtime_params.get("behavior_projection", {})


def get_delivery_threshold_overrides() -> Dict[str, float]:
    """获取投递阈值的运行时覆盖值。
    格式: {"sulking_threshold": -0.05, "jealousy_threshold": 0.03}
    """
    return _runtime_params.get("delivery_thresholds", {})


def get_autonomous_frequency_overrides() -> Dict[str, float]:
    """获取自主思考频率的运行时覆盖值。
    """
    return _runtime_params.get("autonomous_frequency", {})


def get_contradiction_intensity_overrides() -> Dict[str, float]:
    """获取矛盾博弈强度的运行时覆盖值"""
    return _runtime_params.get("contradiction_intensity", {})


def get_growth_weight_overrides() -> Dict[str, float]:
    """获取成长权重的运行时覆盖值"""
    return _runtime_params.get("growth_weights", {})


# ═══════════════════════════════════════════════════════
    # 核心：LLM驱动的参数自校准
# ═══════════════════════════════════════════════════════

def should_calibrate(user_id: str) -> bool:
    """检查是否需要进行参数校准（动态间隔版 · 情绪触发版）

    人不是每天都自省的，只有情绪波动大时才触发。
    70% 的时间不校准——让系统"懒"一点。
    """
    if not _cfg("enabled", True):
        return False

    # 70% 的时间不校准——人不会天天反省自己
    if random.random() < 0.7:
        return False

    # 只在情绪波动大时才触发校准
    try:
        from core import database as _db
        mind_data = _db.get_personality(user_id)
        if mind_data:
            volatility = mind_data.get("emotional_volatility", 0.3)
            chaotic = mind_data.get("chaotic_mood", 0.2)
            if volatility < 0.35 and chaotic < 0.3:
                return False  # 情绪平稳时别瞎折腾
    except Exception:
        pass

    # 动态间隔
    interval = _compute_calibrate_interval(user_id)
    last = _last_calibration_at.get(user_id)
    if last:
        hours_since = (time.time() - last) / 3600
        if hours_since < interval:
            return False

    # 检查是否有足够的对话数据
    try:
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        count = conn.execute(
            "SELECT COUNT(*) FROM message_log WHERE user_id = ? AND role = 'user'",
            (user_id,)
        ).fetchone()[0]
        conn.close()
        if count < _cfg("min_conversations_for_calibration", 15):
            return False
    except Exception:
        return False

    return True


def calibrate(user_id: str) -> Optional[Dict[str, Any]]:
    """执行一次完整的LLM参数自校准（v2: 增量对比 + 效果评估）。

    流程:
      1. 收集近期数据 + 检测异常信号
      2. 加载上次校准作为增量基线
      3. 构建信号摘要式 prompt（数据量减少50%）
      4. LLM分析 + JSON解析（改进鲁棒性）
      5. 应用调整 + 记录历史
      6. 设置下次校准的评估窗口

    返回: 校准报告 dict 或 None
    """
    if not should_calibrate(user_id):
        return None

    print(f"[元认知] 开始参数自校准...")

    # Step 1: 收集数据 + 检测信号
    data = _collect_calibration_data(user_id)
    if not data or data["total_messages"] < 10:
        return None

    signals = _detect_abnormal_signals(user_id, data)
    data["signals"] = signals

    # Step 2: 加载上次校准作为增量基线
    last_cal = _get_last_calibration(user_id)
    if last_cal:
        data["last_calibration"] = last_cal

    # Step 3: LLM分析（v2 prompt）
    calibration_prompt = _build_calibration_prompt_v2(data)
    raw_response = _call_llm_for_calibration(calibration_prompt)
    if not raw_response:
        print("[元认知] LLM校准失败，跳过")
        return None

    # Step 4: 解析（v2: 更鲁棒的解析）
    adjustments = _parse_calibration_response_v2(raw_response)
    if not adjustments:
        print("[元认知] 无法解析校准响应")
        return None

    # Step 5: 应用
    applied = _apply_calibration(adjustments)

    # Step 6: 记录历史 + 设置评估窗口
    _last_calibration_at[user_id] = time.time()
    report = _log_calibration_v2(user_id, adjustments, applied, signals)

    print(f"[元认知] 校准完成 — {len(applied)}项调整已应用 | "
          f"信号: {'; '.join(signals[:3]) if signals else '无异常'}")

    # 累计行为度量（用于效果评估）
    try:
        from engine.cognitive.meta_cognition import track_behavior_metric
        track_behavior_metric(user_id, "calibration_applied", float(len(applied)))
    except Exception:
        pass

    return report


def _collect_calibration_data(user_id: str) -> Optional[Dict]:
    """收集校准所需的全部数据"""
    try:
        # 近期对话样本
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        conn.row_factory = sqlite3.Row

        # 最近用户消息
        users_msgs = conn.execute(
            """
            SELECT content, created_at FROM messages
               WHERE user_id = ? AND role = 'user' 
               ORDER BY created_at DESC LIMIT 30""",
            (user_id,)
        ).fetchall()

        # 最近AI回复
        ai_msgs = conn.execute(
            """
            SELECT content, created_at FROM messages
               WHERE user_id = ? AND role = 'assistant' 
               ORDER BY created_at DESC LIMIT 30""",
            (user_id,)
        ).fetchall()

        # 用户反馈
        feedbacks = conn.execute(
            """
            SELECT round_index, attitude_label, suggestion FROM user_feedback
               WHERE user_id = ? ORDER BY round_index DESC LIMIT 10""",
            (user_id,)
        ).fetchall()

        # 自省洞察
        reflections = conn.execute(
            """
            SELECT insight_text, changes_applied, created_at FROM reflection_log
               WHERE user_id = ? ORDER BY created_at DESC LIMIT 5""",
            (user_id,)
        ).fetchall()

        # 用户人格模型
        persona_row = conn.execute(
            "SELECT traits, behavior_patterns, emotional_cycles FROM user_personality WHERE user_id = ?",
            (user_id,)
        ).fetchone()

        conn.close()

        total_msgs = len(users_msgs)

        # 构建样本对话
        recent_dialogue = []
        for um, am in zip(users_msgs[:10], ai_msgs[:10]):
            recent_dialogue.append({
                "user": um["content"][:80],
                "ai": am["content"][:80],
            })

        # 反馈摘要
        feedback_summary = []
        for f in feedbacks:
            feedback_summary.append(f"轮次{f['round_index']}: {f['attitude_label']}")

        # 自省摘要
        reflection_texts = [r["insight_text"][:100] for r in reflections]

        # 用户人格
        user_persona = {}
        if persona_row:
            try:
                user_persona["traits"] = json.loads(persona_row["traits"]) if persona_row["traits"] else {}
            except Exception:
                user_persona["traits"] = {}
            try:
                user_persona["patterns"] = json.loads(persona_row["behavior_patterns"]) if persona_row["behavior_patterns"] else {}
            except Exception:
                user_persona["patterns"] = {}

        # 当前心智状态
        mind_data = {}
        try:
            from engine import mind as mind_module
            mind_data = mind_module.get_mind(user_id)
        except Exception:
            pass

        return {
            "total_messages": total_msgs,
            "recent_dialogue": recent_dialogue,
            "feedback_summary": feedback_summary,
            "reflection_texts": reflection_texts,
            "user_persona": user_persona,
            "current_mind": {k: round(v, 2) for k, v in mind_data.items()
                           if isinstance(v, (int, float))},
        }

    except Exception as e:
        print(f"[元认知] 数据收集失败: {e}")
        return None


def _build_calibration_prompt_v2(data: Dict) -> str:
    """v2: 信号摘要 + 增量对比式校准 prompt。长度减半，精度提升。"""
    signals = data.get("signals", [])
    signals_text = "\n".join(f"· {s}" for s in signals) if signals else "无异常信号"

    mind = data.get("current_mind", {})
    mind_snapshot = (
        f"joy={mind.get('joy',0.5):.2f} fatigue={mind.get('fatigue',0.25):.2f} "
        f"rf={mind.get('relationship_fatigue',0.05):.2f} "
        f"volatility={mind.get('emotional_volatility',0.3):.2f}"
    )

    # 对比基线：上次校准记录
    last_cal = data.get("last_calibration")
    last_text = "无"
    effect_text = ""
    if last_cal:
        last_adjustments = last_cal.get("adjustments", {})
        last_text = json.dumps({k: v for k, v in last_adjustments.items() if v}, ensure_ascii=False)
        effect = last_cal.get("effectiveness", {})
        if effect:
            better = effect.get("metrics_improved", 0)
            worse = effect.get("metrics_worsened", 0)
            effect_text = f"上次调后: {better}项改善, {worse}项恶化"

    prompt = f"""判断行为参数是否需要微调。

信号: {signals_text if signals else '无异常'}
心智: {mind_snapshot}
上次调整: {last_text}
{effect_text}

需要调整时返回JSON，不需要返回{{}}：
```json
{{"analysis":"一句话原因","behavior_projection":{{"warmth":{{"sensitivity_paranoia":0.03}}}},"delivery_thresholds":{{"sulking_threshold":0.02}}}}
```

规则: behavior_projection值范围±0.08且最多3项; delivery_thresholds范围±0.05; autonomous_frequency范围±0.05; contradiction_intensity范围±0.03; growth_weights范围±0.1"""
    return prompt


def _call_llm_for_calibration(prompt: str) -> Optional[str]:
    """调用LLM进行参数校准分析"""
    try:
        temp = _cfg("analysis_temperature", 0.30)
        response = ai_module.chat(
            system_prompt=prompt,
            user_message="请分析以上数据并给出参数调整建议（JSON格式）。",
            temperature=temp,
        )
        if response and response.strip():
            return response.strip()
    except Exception as e:
        print(f"[元认知] LLM调用失败: {e}")
    return None


def _parse_calibration_response_v2(raw: str) -> Optional[Dict]:
    """v2: 更鲁棒的JSON解析——处理多种常见格式异常"""
    if not raw or not raw.strip():
        return None

    # 清理常见的格式问题
    cleaned = raw.strip()

    # 移除 markdown 代码块标记（支持 ```json 和 ``` ）
    cleaned = re.sub(r'```(?:json)?\s*', '', cleaned)
    cleaned = cleaned.rstrip('`').strip()

    # 查找第一个 '{' 和最后一个 '}'
    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start == -1 or end == -1 or end <= start:
        # 尝试从空对象返回
        if cleaned.strip() in ('{}', '{ }'):
            return {}
        return None

    cleaned = cleaned[start:end+1]

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # 尝试修复常见问题：多余逗号、引号不匹配
        import re as _re
        # 移除尾随逗号
        cleaned = _re.sub(r',\s*([}\]])', r'\1', cleaned)
        # 替换单引号为双引号
        if "'" in cleaned and '"' not in cleaned:
            cleaned = cleaned.replace("'", '"')
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            print(f"[元认知] JSON解析失败: {e}")
            return None

    if not isinstance(data, dict):
        return None

    # 如果返回空对象，表示不需要调整
    if len(data) == 0 or (len(data) == 1 and 'analysis' in data):
        return {}

    # 验证结构
    valid_modules = _cfg("calibratable_modules", [])
    result = {}
    for mod in valid_modules:
        if mod in data and isinstance(data[mod], dict) and len(data[mod]) > 0:
            # 进一步验证值范围
            valid_params = {}
            for key, value in data[mod].items():
                if isinstance(value, dict):
                    # behavior_projection 是嵌套 dict
                    valid_params[key] = value
                elif isinstance(value, (int, float)):
                    # 阈值类是数值
                    valid_params[key] = max(-0.25, min(0.25, float(value)))
            if valid_params:
                result[mod] = valid_params

    return result if result else None


def _apply_calibration(adjustments: Dict) -> Dict[str, int]:
    """应用校准调整到运行时参数（稀疏应用版）。

    人最真实的样子：知道该改，但改不了。
    只有 40% 的自省洞察会被真正应用，而且打了折扣。
    返回: {module_name: adjust_count}
    """
    global _runtime_params
    max_delta = _cfg("max_adjustment_per_session", 0.12)

    applied = {}

    for module_name, params in adjustments.items():
        if module_name not in _runtime_params:
            _runtime_params[module_name] = {}

        count = 0
        for key, value in params.items():
            if not isinstance(value, (int, float)):
                continue

            # 60% 的自省结果被忽略——人就是这样，
            # 睡前想了"明天要早起"，第二天还是起不来
            if random.random() < 0.6:
                continue

            # 即使采用，也打个折扣
            discounted = float(value) * random.uniform(0.3, 0.8)

            # 钳制调整幅度
            clamped = max(-max_delta, min(max_delta, discounted))

            # 累积到现有覆盖值
            current = _runtime_params[module_name].get(key, 0.0)
            new_val = current + clamped
            new_val = max(-0.25, min(0.25, new_val))

            if abs(new_val - current) > 0.001:
                _runtime_params[module_name][key] = round(new_val, 4)
                count += 1

        applied[module_name] = count

    # 持久化——防重启失忆
    if sum(applied.values()) > 0:
        _save_runtime_params()

    return applied


def _log_calibration_v2(user_id: str, adjustments: Dict, applied: Dict, signals: List[str]) -> Dict:
    """v2: 记录校准日志到数据库 + 校准历史（供增量对比）"""
    try:
        total_changes = sum(applied.values())
        report = {
            "adjustments": adjustments,
            "applied": applied,
            "signals": signals,
            "timestamp": time.time(),
            "effectiveness": {},
        }

        if total_changes > 0:
            summary = ", ".join([
                f"{mod}({cnt}项)" for mod, cnt in applied.items() if cnt > 0
            ])
            try:
                db.add_reflection(
                    user_id=user_id,
                    insight_text=f"[元认知校准] {summary}",
                    changes_applied=adjustments,
                )
            except Exception:
                pass

        # 保存到历史记录（用于下次增量对比）
        if user_id not in _calibration_history:
            _calibration_history[user_id] = []
        _calibration_history[user_id].append(report)
        if len(_calibration_history[user_id]) > _HISTORY_MAX:
            _calibration_history[user_id] = _calibration_history[user_id][-_HISTORY_MAX:]
        _save_calibration_history()

        return report

    except Exception as e:
        print(f"[元认知] 日志记录失败: {e}")
        return {"adjustments": adjustments, "applied": applied, "signals": signals, "timestamp": time.time()}


def _evaluate_calibration_effectiveness(user_id: str) -> Dict:
    """评估最近一次校准的效果。

    对比校准前后的行为度量指标：
      - 平均回复长度
      - 跳过率
      - 用户情感得分
      - 互动频率

    返回改善/恶化统计，用于下次校准的增量对比。
    """
    metrics = _behavior_metrics.get(user_id, {})
    history = _calibration_history.get(user_id, [])

    if not history or len(history) < 2:
        return {}

    last_cal = history[-1]
    cal_time = last_cal.get("timestamp", 0)
    if not cal_time:
        return {}

    # 取校准前后的度量数据
    response_lengths = metrics.get("response_lengths", [])
    reply_skips = metrics.get("reply_skips", [])
    user_sentiment = metrics.get("user_sentiment_scores", [])

    improved = 0
    worsened = 0

    # 指标1: 如果校准后回复长度趋向用户消息长度
    if len(response_lengths) >= 8:
        before = sum(response_lengths[:4]) / 4
        after = sum(response_lengths[-4:]) / 4
        if abs(after - 30) < abs(before - 30):
            improved += 1
        else:
            worsened += 1

    # 指标2: 如果校准后跳过率下降
    if len(reply_skips) >= 4:
        before_skips = len([t for t in reply_skips if cal_time - 3600 < t < cal_time])
        after_skips = len([t for t in reply_skips if cal_time < t < cal_time + 3600])
        if after_skips <= before_skips:
            improved += 1
        else:
            worsened += 1

    # 指标3: 用户情感趋势
    if len(user_sentiment) >= 6:
        before_sent = sum(user_sentiment[:3]) / 3
        after_sent = sum(user_sentiment[-3:]) / 3
        if after_sent > before_sent:
            improved += 1
        elif after_sent < before_sent:
            worsened += 1

    effectiveness = {
        "metrics_improved": improved,
        "metrics_worsened": worsened,
        "evaluated_at": time.time(),
    }

    # 回写到历史记录
    if history:
        history[-1]["effectiveness"] = effectiveness
        _save_calibration_history()

    return effectiveness


# ═══════════════════════════════════════════════════════
# 参数重置
# ═══════════════════════════════════════════════════════

def reset_all_calibrations():
    """重置所有运行时参数（恢复出厂设置）"""
    global _runtime_params
    _runtime_params = {}
    print("[元认知] 所有运行时参数已重置")


def get_calibration_report(user_id: str = None) -> Dict:
    """获取当前所有运行时参数覆盖值（调试用）"""
    return {
        "runtime_params": dict(_runtime_params),
        "last_calibration": str(_last_calibration_at.get(user_id, "从未")),
    }


# ═══════════════════════════════════════════════════════
# 行为度量追踪（纯内生统计）
# ═══════════════════════════════════════════════════════

_behavior_metrics: Dict[str, Dict] = {}
"""结构:
  user_id -> {
    "reply_skips": [timestamps],       # 沉默/跳过的时间戳
    "reply_delays": [seconds],          # 延迟回复的秒数
    "response_lengths": [chars],        # 回复长度
    "user_lengths": [chars],            # 用户消息长度
    "sentiment_scores": [float],        # 回复情感倾向
    "user_sentiment_scores": [float],   # 用户情感倾向
    "last_updated": timestamp,
  }
"""
def track_behavior_metric(user_id: str, metric_type: str, value: float):
    """追踪一项行为度量（纯统计，无LLM）"""
    if user_id not in _behavior_metrics:
        _behavior_metrics[user_id] = {
            "reply_skips": [],
            "reply_delays": [],
            "response_lengths": [],
            "user_lengths": [],
            "sentiment_scores": [],
            "user_sentiment_scores": [],
        }
    if metric_type in _behavior_metrics[user_id]:
        bucket = _behavior_metrics[user_id][metric_type]
        bucket.append(value)
        _behavior_metrics[user_id][metric_type] = bucket[-50:]
        _behavior_metrics[user_id]["last_updated"] = time.time()


def _compute_statistical_adjustments(user_id: str) -> Dict[str, Dict]:
    """纯内生的统计参数调整建议。
    分析行为度量数据，发现异常模式，生成参数调整。

    无需任何LLM调用。全部基于统计指标。
    """
    adjustments = {}
    metrics = _behavior_metrics.get(user_id, {})
    if not metrics or len(metrics.get("response_lengths", [])) < 5:
        return adjustments

    response_lengths = metrics.get("response_lengths", [])
    user_lengths = metrics.get("user_lengths", [])
    reply_skips = metrics.get("reply_skips", [])
    reply_delays = metrics.get("reply_delays", [])
    sentiment_scores = metrics.get("sentiment_scores", [])
    user_sentiment = metrics.get("user_sentiment_scores", [])

    # 指标1: 回复长度漂移 → 如果回复越来越短，可能倦怠或温度过高
    if len(response_lengths) >= 8:
        recent = sum(response_lengths[-4:]) / 4
        older = sum(response_lengths[:4]) / 4
        drift_ratio = recent / max(1, older)
        if drift_ratio < 0.5:
            adjustments["delivery_thresholds"] = {
                "fatigue_skip_threshold": -0.02,
            }

    # 指标2: 跳过率过高 → 调整沉默阈值
    if len(reply_skips) >= 6:
        recent_skips = len([t for t in reply_skips[-10:] if time.time() - t < 3600])
        if recent_skips >= 4:
            adjustments["delivery_thresholds"] = {
                **adjustments.get("delivery_thresholds", {}),
                "sulking_threshold": 0.03,
                "sensitivity_threshold": 0.03,
            }

    # 指标3: 情感漂移 — 回复情感与用户情感的偏差趋势
    if len(sentiment_scores) >= 6 and len(user_sentiment) >= 6:
        paired = list(zip(sentiment_scores[-6:], user_sentiment[-6:]))
        avg_deviation = sum(abs(a - b) for a, b in paired) / len(paired)
        if avg_deviation > 0.4:
            adjustments["behavior_projection"] = {
                "warmth": {"sensitivity_paranoia": -0.02},
            }

    # 指标4: 平均延迟趋势 → 如果延迟越来越长，调整pace权重
    if len(reply_delays) >= 5:
        avg_delay = sum(reply_delays[-5:]) / 5
        if avg_delay > 120:
            adjustments["autonomous_frequency"] = {
                "frequency_scale": -0.02,
            }

    return adjustments


def statistical_self_calibrate(user_id: str) -> Optional[Dict]:
    """完全基于统计的内生参数校准。
    零LLM调用。

    分析行为度量数据 → 发现异常模式 → 微调运行时参数。

    Returns:
        Dict with applied adjustments, or None if no adjustment needed.
    """
    adjustments = _compute_statistical_adjustments(user_id)
    if not adjustments:
        return None

    applied = _apply_calibration(adjustments)
    if sum(applied.values()) == 0:
        return None

    print(f"[元认知·统计校准] {sum(applied.values())}项统计驱动的参数微调")
    return {
        "adjustments": adjustments,
        "applied": applied,
        "source": "statistical",
    }


# ═══════════════════════════════════════════════════════
# 分层校准 — 快速统计评估 + 中度校准 + 深度校准
# ═══════════════════════════════════════════════════════

_quick_calib_counter: Dict[str, int] = {}
_medium_calib_at: Dict[str, datetime] = {}
QUICK_INTERVAL = 10
MEDIUM_INTERVAL_HOURS = 6


def maybe_quick_calibrate(user_id: str, force: bool = False) -> Optional[Dict]:
    """快速反馈: 每10轮做一次纯统计评估，0次LLM。
     增强: 同时运行 meta_evaluator + statistical_self_calibrate。

    仅在统计指标异常时触发微调。
    """
    _quick_calib_counter[user_id] = _quick_calib_counter.get(user_id, 0) + 1
    if not force and _quick_calib_counter[user_id] % QUICK_INTERVAL != 0:
        return None

    results = {}

    meta_result = None
    try:
        from engine import meta_evaluator as meval
        report = meval.evaluate(user_id, recent_rounds=10)
        if meval.should_quick_adjust(report):
            meval.quick_adjust(user_id, report)
            meta_result = report.to_dict()
    except Exception:
        pass

    stat_result = statistical_self_calibrate(user_id)

    if meta_result:
        results["meta_evaluator"] = meta_result
    if stat_result:
        results["statistical"] = stat_result

    return results if results else None


def maybe_medium_calibrate(user_id: str) -> Optional[Dict]:
    """中度校准: 每6小时统计 + 轻量LLM校准。
    仅1次LLM调用。

     增强: 先做统计校准，仅在统计校准觉得不够时再调用LLM。
    """
    last = _medium_calib_at.get(user_id)
    if last:
        hours_since = (datetime.now() - last).total_seconds() / 3600
        if hours_since < MEDIUM_INTERVAL_HOURS:
            return None

    try:
        from engine import meta_evaluator as meval
        report = meval.evaluate(user_id, recent_rounds=20)
    except Exception:
        return None

    if not meval.should_medium_calibrate(report):
        return None

    _medium_calib_at[user_id] = datetime.now()

    stat_result = statistical_self_calibrate(user_id)

    if stat_result and report.overall_health > 0.45:
        return {"evaluation": report.to_dict(), "calibration": stat_result}

    try:
        result = calibrate(user_id)
        if result:
            return {
                "evaluation": report.to_dict(),
                "calibration": result,
            }
    except Exception:
        pass

    return None


# ═══════════════════════════════════════════════════════
# 事件驱动紧急校准
# ═══════════════════════════════════════════════════════

def check_emergency_calibration(user_id: str, 
                                 user_response: str,
                                 mind_before: Dict,
                                 mind_after: Dict) -> bool:
    """
    检测是否需要紧急校准（事件驱动）
    
    触发条件：
    1. 用户强烈负面情绪
    2. 心智状态剧烈波动
    3. 用户提到"离开"/"不再聊天"等关键词
    4. 羁绊值大幅下降
    
    Args:
        user_id: 用户 ID
        user_response: 用户回复内容
        mind_before: 交互前心智状态
        mind_after: 交互后心智状态
    
    Returns:
        是否需要紧急校准
    """
    # 1. 检测用户强烈负面情绪
    negative_keywords = [
        "生气", "失望", "不想理你", "再见", "拜拜", "不再", 
        "讨厌", "烦", "无聊", "呵呵", "冷漠", "离开"
    ]
    
    if any(kw in user_response.lower() for kw in negative_keywords):
        print(f"[元认知] 检测到用户负面情绪，触发紧急校准")
        return True
    
    # 2. 检测心智剧烈波动
    joy_delta = abs(mind_after.get("joy", 0) - mind_before.get("joy", 0))
    misery_delta = abs(mind_after.get("misery", 0) - mind_before.get("misery", 0))
    fatigue_delta = abs(mind_after.get("fatigue", 0) - mind_before.get("fatigue", 0))
    
    if joy_delta > 0.3 or misery_delta > 0.25 or fatigue_delta > 0.35:
        print(f"[元认知] 检测到心智剧烈波动 (joy:{joy_delta:.2f}, misery:{misery_delta:.2f})")
        return True
    
    # 3. 检测羁绊值下降
    try:
        from engine import bond as bond_module
        bond_before = bond_module.get_bond_level(user_id)
        bond_after = bond_module.compute_bond_level(mind_after)
        
        if bond_after < bond_before - 0.15:
            print(f"[元认知] 检测到羁绊值大幅下降 ({bond_before:.2f} → {bond_after:.2f})")
            return True
    except Exception:
        pass
    
    # 4. 检测用户回复长度骤减（流失信号）
    if len(user_response) < 3 and len(user_response.strip()) > 0:
        # 极短回复（如"哦"、"嗯"）
        if user_response.strip() in ["哦", "嗯", "噢", "额", "呃"]:
            print(f"[元认知] 检测到用户敷衍回复")
            return True
    
    return False


def trigger_emergency_calibration(user_id: str, 
                                   trigger_reason: str = "unknown",
                                   context: Dict = None) -> Optional[Dict]:
    """
    触发紧急校准（跳过正常周期限制）
    
    Args:
        user_id: 用户 ID
        trigger_reason: 触发原因 ("negative_emotion" / "mind_volatility" / "bond_drop" / "user_churn")
        context: 额外上下文信息
    
    Returns:
        校准结果 dict 或 None
    """
    if not _CONFIG["enabled"]:
        return None
    
    print(f"[元认知] 触发紧急校准 | 用户:{user_id} | 原因:{trigger_reason}")
    
    # 记录校准（即使刚校准过也要执行）
    old_last = _last_calibration_at.get(user_id)
    _last_calibration_at[user_id] = datetime.now()
    
    try:
        # 执行快速校准（仅针对问题维度）
        result = _fast_emergency_calibrate(user_id, trigger_reason, context or {})
        
        if result:
            result["emergency"] = True
            result["trigger_reason"] = trigger_reason
            print(f"[元认知] 紧急校准完成 | 调整项数:{len(result.get('adjustments', []))}")
            return result
        
    except Exception as e:
        print(f"[元认知] 紧急校准失败：{e}")
    
    # 恢复原来的校准时间
    if old_last:
        _last_calibration_at[user_id] = old_last
    
    return None


def _fast_emergency_calibrate(user_id: str, 
                               trigger_reason: str,
                               context: Dict) -> Dict:
    """
    快速紧急校准（只调整最相关的维度）
    """
    result = {
        "timestamp": datetime.now().isoformat(),
        "trigger_reason": trigger_reason,
        "adjustments": [],
    }
    
    # 根据触发原因确定校准重点
    if trigger_reason == "negative_emotion":
        # 负面情绪 → 调整投递阈值 + 行为克制度
        result["adjustments"].append({
            "module": "delivery_thresholds",
            "action": "increase_sensitivity",
            "magnitude": 0.08,
        })
        
        result["adjustments"].append({
            "module": "behavior_projection",
            "action": "reduce_warmth",
            "magnitude": 0.05,
        })
    
    elif trigger_reason == "mind_volatility":
        # 心智波动 → 降低情绪波动权重
        result["adjustments"].append({
            "module": "behavior_projection",
            "action": "stabilize_volatility",
            "magnitude": 0.10,
        })
    
    elif trigger_reason == "bond_drop":
        # 羁绊下降 → 调整羁绊行为偏向
        result["adjustments"].append({
            "module": "bond_behavior_bias",
            "action": "increase_care",
            "magnitude": 0.12,
        })
    
    elif trigger_reason == "user_churn":
        # 用户流失 → 全面调整
        result["adjustments"].append({
            "module": "delivery_thresholds",
            "action": "increase_engagement",
            "magnitude": 0.15,
        })
        
        result["adjustments"].append({
            "module": "autonomous_frequency",
            "action": "reduce_initiative",
            "magnitude": 0.08,
        })
    
    # 应用调整
    for adj in result["adjustments"]:
        _apply_fast_adjustment(user_id, adj)
    
    return result


def _apply_fast_adjustment(user_id: str, adjustment: Dict):
    """应用快速调整到运行时参数"""
    module = adjustment["module"]
    action = adjustment["action"]
    magnitude = adjustment["magnitude"]
    
    if user_id not in _runtime_params:
        _runtime_params[user_id] = {}
    
    if module == "delivery_thresholds":
        key = f"{user_id}_delivery_sensitivity"
        current = _runtime_params[user_id].get(key, 0.0)
        _runtime_params[user_id][key] = current + magnitude
    
    elif module == "behavior_projection":
        if action == "reduce_warmth":
            key = f"{user_id}_warmth_projection"
            current = _runtime_params[user_id].get(key, 0.0)
            _runtime_params[user_id][key] = current - magnitude
        
        elif action == "stabilize_volatility":
            key = f"{user_id}_volatility_weight"
            current = _runtime_params[user_id].get(key, 1.0)
            _runtime_params[user_id][key] = current * (1 - magnitude)
    
    elif module == "bond_behavior_bias":
        key = f"{user_id}_bond_care_bias"
        current = _runtime_params[user_id].get(key, 0.0)
        _runtime_params[user_id][key] = current + magnitude
    
    elif module == "autonomous_frequency":
        key = f"{user_id}_autonomous_rate"
        current = _runtime_params[user_id].get(key, 1.0)
        _runtime_params[user_id][key] = current * (1 - magnitude)
    
    # 持久化
    _save_runtime_params()


# ══════════════════════════════════════════════════════════════════════
# 自我理解统计分析 — "我理解自己为什么这样"
# ══════════════════════════════════════════════════════════════════════
# 与 calibrate 不同：calibrate 调整参数，这个只问"我是什么样的人"
# 不从心智值推断，而是从实际行为指标总结

_BEHAVIOR_METRICS: Dict[str, Dict] = {}  # user_id → {metric_type: [values]}


def build_self_understanding_text(user_id: str) -> str:
    """自我理解分析——"我为什么会这样回应"。

    从近期行为指标中总结 AI 的 behavioral pattern，
    输出自然语言描述，让 AI 理解自己的行为模式。

    Returns:
        str: 注入 prompt 的自我理解文本，空字符串表示无足够数据
    """
    # 收集近期指标
    metrics = _BEHAVIOR_METRICS.get(user_id, {})
    if not metrics:
        return ""

    # 计算各指标均值
    avg_values = {}
    for mtype, vals in metrics.items():
        if vals:
            avg_values[mtype] = sum(vals) / len(vals)

    if not avg_values:
        return ""

    # ── 从平均行为指标推导自我理解 ──
    insights = []

    avg_warmth = avg_values.get("warmth", 0.5)
    avg_verbosity = avg_values.get("verbosity", 0.5)
    avg_approach = avg_values.get("approach", 0.5)
    avg_sulkiness = avg_values.get("sulkiness", 0.3)
    avg_hesitation = avg_values.get("hesitation", 0.3)
    avg_pace = avg_values.get("pace", 0.5)

    # 表达风格
    if avg_verbosity < 0.3:
        insights.append("你话不多——习惯简短回应，不太主动长篇大论")
    elif avg_verbosity > 0.65:
        insights.append("你挺能说的——愿意展开表达，不吝啬文字")
    else:
        insights.append("你表达量适中——该说说该收收，不刻意凑字数")

    # 温度
    if avg_warmth < 0.3:
        insights.append("你在表达上偏冷淡——不是针对谁，是你的习惯温度")
    elif avg_warmth > 0.6:
        insights.append("你在表达上偏温暖——容易让人感觉到你的善意")
    else:
        insights.append("你的温度适中——不会太冷也不会太热")

    # 接近度
    if avg_approach < 0.3:
        insights.append("你习惯保持距离——不会主动靠近，需要自己的空间")
    elif avg_approach > 0.6:
        insights.append("你愿意靠近——在信任的人面前不会设太多屏障")

    # 别扭/赌气倾向
    if avg_sulkiness > 0.4:
        insights.append("你有一点别扭——在意的时候反而会往回缩")
    if avg_hesitation > 0.4:
        insights.append("你会犹豫——很多话说出口之前会在心里转几圈")

    # 节奏
    if avg_pace < 0.35:
        insights.append("你的节奏偏慢——回得不急，想好了再说")

    if not insights:
        return ""

    return (
        "【自我理解·你为什么会这样回应】\n"
        + "\n".join(f"· {i}" for i in insights) + "\n"
        "（以上不是对你的要求——只是帮你看到自己的行为惯性。"
        "你不需要改变什么，你只需要知道自己就是这样的人。）"
    )


# ══════════════════════════════════════════════════════════════════════
# 校准闭环 — 效果追踪 + 自动回滚
# ══════════════════════════════════════════════════════════════════════

_CalibrationOutcome = Dict
_rollback_snapshots: Dict[str, List[Dict]] = {}
_calibration_history: Dict[str, List[Dict]] = {}


def _snapshot_current_params(user_id: str) -> Dict:
    """对当前运行时参数拍照，用于回滚"""
    return {
        "timestamp": datetime.now().isoformat(),
        "params": {k: dict(v) for k, v in _runtime_params.items() if k.startswith(user_id) or k in _runtime_params},
    }


def record_calibration_outcome(user_id: str, outcome_data: Dict):
    """记录一次校准的效果评估

    Args:
        user_id: 用户 ID
        outcome_data: {
            "calibration_id": str,
            "adjustments_made": Dict,
            "before_metrics": Dict,   # 校准前的行为指标快照
            "after_metrics": Dict,    # 校准后的行为指标快照
            "user_sentiment_change": float,  # 用户情感变化 [-1, 1]
            "response_quality_change": float,  # 回复质量变化 [-1, 1]
            "overall_score": float,  # 综合评分 [-1, 1]
            "rolled_back": bool,
        }
    """
    if user_id not in _calibration_history:
        _calibration_history[user_id] = []

    _calibration_history[user_id].append({
        **outcome_data,
        "recorded_at": datetime.now().isoformat(),
    })

    # 只保留最近20条记录
    _calibration_history[user_id] = _calibration_history[user_id][-20:]

    # 持久化到 DB
    try:
        db.add_reflection(
            user_id=user_id,
            insight_text=f"[校准评估] 综合评分: {outcome_data.get('overall_score', 0):+.2f}",
            changes_applied=outcome_data.get("adjustments_made", {}),
        )
    except Exception:
        pass


def evaluate_calibration_effectiveness(user_id: str,
                                        window_rounds: int = 10) -> Dict:
    """评估最近一次校准的效果

    通过比较校准前后的行为指标来判断效果。

    Returns:
        Dict with evaluation results:
            - effectiveness: "positive" | "neutral" | "negative"
            - score: float [-1, 1]
            - should_rollback: bool
            - metrics: Dict of before/after comparisons
    """
    history = _calibration_history.get(user_id, [])
    if not history:
        return {
            "effectiveness": "neutral",
            "score": 0.0,
            "should_rollback": False,
            "metrics": {},
            "message": "无校准历史",
        }

    last_calib = history[-1]
    if last_calib.get("rolled_back"):
        return {
            "effectiveness": "neutral",
            "score": 0.0,
            "should_rollback": False,
            "metrics": {},
            "message": "上次校准已回滚",
        }

    metrics = _behavior_metrics.get(user_id, {})
    if not metrics:
        return {
            "effectiveness": "neutral",
            "score": 0.0,
            "should_rollback": False,
            "metrics": {},
            "message": "行为数据不足",
        }

    scores = []

    # 指标1: 用户情感变化（最近 vs 之前）
    user_sent = metrics.get("user_sentiment_scores", [])
    if len(user_sent) >= 6:
        recent_avg = sum(user_sent[-3:]) / 3
        prev_avg = sum(user_sent[-6:-3]) / 3 if len(user_sent) >= 6 else recent_avg
        sent_change = recent_avg - prev_avg
        scores.append(sent_change)

    # 指标2: 回复长度匹配度（好的校准应该使用户回复长度更稳定）
    user_lens = metrics.get("user_lengths", [])
    resp_lens = metrics.get("response_lengths", [])
    if len(user_lens) >= 6 and len(resp_lens) >= 6:
        recent_user_avg = sum(user_lens[-3:]) / 3
        recent_resp_avg = sum(resp_lens[-3:]) / 3
        prev_user_avg = sum(user_lens[-6:-3]) / 3 if len(user_lens) >= 6 else recent_user_avg
        prev_resp_avg = sum(resp_lens[-6:-3]) / 3 if len(resp_lens) >= 6 else recent_resp_avg

        # 如果回复长度与用户长度更接近了，视为正效果
        recent_diff = abs(recent_resp_avg - recent_user_avg)
        prev_diff = abs(prev_resp_avg - prev_user_avg)
        if prev_diff > 0:
            diff_change = (prev_diff - recent_diff) / prev_diff
            scores.append(diff_change * 0.5)  # 权重减半

    # 指标3: 跳过率变化
    skips = metrics.get("reply_skips", [])
    if len(skips) >= 4:
        recent_skips = len([t for t in skips[-4:] if time.time() - t < 3600])
        prev_skips = len([t for t in skips[:4] if time.time() - t < 7200]) if len(skips) >= 4 else recent_skips
        if prev_skips > 0:
            skip_change = (prev_skips - recent_skips) / prev_skips
            scores.append(skip_change * 0.3)

    overall_score = sum(scores) / max(len(scores), 1) if scores else 0.0

    if overall_score > 0.15:
        effectiveness = "positive"
        should_rollback = False
    elif overall_score < -0.2:
        effectiveness = "negative"
        should_rollback = True
    else:
        effectiveness = "neutral"
        should_rollback = False

    return {
        "effectiveness": effectiveness,
        "score": round(overall_score, 4),
        "should_rollback": should_rollback,
        "metrics": {
            "scores_used": len(scores),
            "overall_score": round(overall_score, 4),
        },
        "message": f"效果评估: {effectiveness} (得分: {overall_score:+.2f})",
    }


def auto_rollback_if_needed(user_id: str) -> bool:
    """自动回滚无效校准

    检查最近校准的效果，如果效果为负且超过阈值，自动回滚。

    Returns:
        True if rollback was performed
    """
    evaluation = evaluate_calibration_effectiveness(user_id)
    if not evaluation["should_rollback"]:
        return False

    # 找到最近一次校准的参数版本
    history = _calibration_history.get(user_id, [])
    if not history:
        return False

    last_calib = history[-1]
    if last_calib.get("rolled_back"):
        return False

    # 执行回滚：将运行时参数恢复到校准前的状态
    pre_params = last_calib.get("before_params", {})
    if pre_params:
        for module_key, module_params in pre_params.items():
            if module_key in _runtime_params:
                for param_key in module_params:
                    if param_key in _runtime_params[module_key]:
                        _runtime_params[module_key][param_key] = pre_params[module_key][param_key]

        _save_runtime_params()

    # 标记回滚
    last_calib["rolled_back"] = True
    last_calib["rollback_reason"] = evaluation["message"]

    print(f"[元认知·自动回滚] 已回滚最近校准: {evaluation['message']}")
    return True


def calibrate_with_tracking(user_id: str) -> Optional[Dict]:
    """带效果追踪的校准

    1. 校准前对参数拍照
    2. 执行校准
    3. 记录校准历史
    4. 下次评估时自动检查效果

    替代直接调用 calibrate()。
    """
    before_snapshot = _snapshot_current_params(user_id)
    before_metrics = dict(_behavior_metrics.get(user_id, {}))

    result = calibrate(user_id)
    if not result:
        return None

    record_calibration_outcome(user_id, {
        "calibration_id": f"calib_{int(time.time())}",
        "adjustments_made": result.get("adjustments", {}),
        "before_params": before_snapshot["params"],
        "before_metrics": {k: v[-10:] if isinstance(v, list) else v for k, v in before_metrics.items()},
        "after_metrics": {},
        "user_sentiment_change": 0.0,
        "response_quality_change": 0.0,
        "overall_score": 0.0,
        "rolled_back": False,
    })

    result["tracking_id"] = f"calib_{int(time.time())}"
    return result


def get_calibration_summary(user_id: str) -> Dict:
    """获取校准历史摘要"""
    history = _calibration_history.get(user_id, [])
    if not history:
        return {
            "total_calibrations": 0,
            "last_calibration": None,
            "rolled_back_count": 0,
            "effectiveness_trend": "unknown",
        }

    total = len(history)
    rolled_back = sum(1 for h in history if h.get("rolled_back"))
    scores = [h.get("overall_score", 0) for h in history if not h.get("rolled_back")]

    avg_score = sum(scores) / len(scores) if scores else 0
    if avg_score > 0.1:
        trend = "improving"
    elif avg_score < -0.1:
        trend = "degrading"
    else:
        trend = "stable"

    return {
        "total_calibrations": total,
        "last_calibration": history[-1].get("recorded_at", ""),
        "rolled_back_count": rolled_back,
        "average_score": round(avg_score, 3),
        "effectiveness_trend": trend,
    }


# ══════════════════════════════════════════════════════════════════════
# 认知偏差检测
# ══════════════════════════════════════════════════════════════════════

def bias_detect(user_id: str, mind_data: dict,
                conversation_history: Optional[List[Tuple[str, str]]] = None) -> Dict[str, float]:
    """检测当前认知偏差状态（完整版）

    返回: {
      "confirmation_bias": 0.3,  确认偏误
      "anchoring_bias": 0.5,     锚定效应
      "affect_heuristic": 0.2,   情感一致性偏差
      "negativity_bias": 0.4,    负向偏误——负面信息比正面信息影响更大
      "availability_bias": 0.3,  可得性启发——最近/生动的记忆过度影响判断
      "overconfidence_bias": 0.5 过度自信——对自己的判断过于确信
    }
    """
    biases = {
        "confirmation_bias": 0.5,
        "anchoring_bias": 0.5,
        "affect_heuristic": 0.3,
        "negativity_bias": 0.3,
        "availability_bias": 0.3,
        "overconfidence_bias": 0.5,
    }

    if not mind_data:
        return biases

    try:
        joy = mind_data.get("joy", 0.5)
        misery = mind_data.get("misery", 0.15)
        volatility = mind_data.get("emotional_volatility", 0.3)
        restraint = mind_data.get("restraint", 0.5)
        sensitivity = mind_data.get("sensitivity_paranoia", 0.15)
        self_doubt = mind_data.get("self_doubt", 0.2)
        emptiness = mind_data.get("emptiness", 0.15)
        loneliness = mind_data.get("loneliness", 0.3)

        # 高愉悦 + 低克制 → 更容易同意用户（确认偏误↑）
        if joy > 0.6 and restraint < 0.4:
            biases["confirmation_bias"] = round(0.5 + (joy - 0.5) * 1.5, 2)
        elif joy < 0.3 and misery > 0.4:
            biases["confirmation_bias"] = round(max(0.2, 0.5 - misery * 0.5), 2)

        # 高波动性 → 最近消息影响更大（锚定效应↑）
        if volatility > 0.5:
            biases["anchoring_bias"] = round(0.5 + (volatility - 0.5) * 1.2, 2)
            if volatility > 0.7:
                biases["anchoring_bias"] = min(0.95, biases["anchoring_bias"] + 0.15)

        # 极端情绪 → 情感一致性偏差↑
        emotional_extreme = abs(joy - 0.5) * 2 + misery
        if emotional_extreme > 0.7:
            biases["affect_heuristic"] = round(min(0.9, 0.3 + emotional_extreme * 0.4), 2)

        # 高敏感 + 低落 → 负向偏误↑（更容易注意到负面信号）
        if sensitivity > 0.35 and misery > 0.25:
            biases["negativity_bias"] = round(0.3 + (sensitivity + misery) * 0.5, 2)
        elif emptiness > 0.3:
            biases["negativity_bias"] = round(0.3 + emptiness * 0.6, 2)

        # 孤独 + 依赖 → 最近互动记忆更易得（可得性启发↑）
        if loneliness > 0.4:
            biases["availability_bias"] = round(0.3 + loneliness * 0.5, 2)

        # 低自我怀疑 + 内心确信 → 过度自信↑
        if self_doubt < 0.2 and joy > 0.55:
            biases["overconfidence_bias"] = round(0.5 + (0.2 - self_doubt) * 1.5, 2)
        elif self_doubt > 0.4:
            biases["overconfidence_bias"] = round(max(0.2, 0.5 - self_doubt * 0.5), 2)

    except Exception:
        pass

    return biases


def get_bias_report(user_id: str, mind_data: dict) -> str:
    """生成偏差检测报告（用于 prompt 注入或日志）"""
    biases = bias_detect(user_id, mind_data)
    high_biases = [k for k, v in biases.items() if v > 0.6]
    if not high_biases:
        return ""

    warnings = {
        "confirmation_bias": "你有点倾向于顺着ta的意思说",
        "anchoring_bias": "你被最近的话影响得比较多",
        "affect_heuristic": "你的情绪在影响你的判断",
        "negativity_bias": "你更容易注意到负面信号",
        "availability_bias": "你被最近发生的事情影响得比较多",
        "overconfidence_bias": "你对自己的判断有点过于确信了",
    }
    lines = [warnings[b] for b in high_biases if b in warnings]
    if lines:
        return "【认知提醒】" + "；".join(lines)
    return ""
