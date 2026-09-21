# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""自省引擎 — Reflection Engine
===================================
每日夜间复盘时，LLM回顾当天对话，评估自己的表现。
产生改进洞察，存入reflection_log表，供后续对话自然引用。

设计原则：
  - LLM轻量调用（每次~200 token输出），不阻塞主流程
  - 静默失败，不影响对话体验
  - 洞察数量限制（最多保留10条），避免提示膨胀
"""
from __future__ import annotations
import json
import re
from datetime import datetime
from core import database as db
from core import config as cfg
from core import ai as ai_module

# ══════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════

_REFLECTION_CONFIG = {
    "enabled": True,
    "max_insights_retained": 10,
    "injection_max_chars": 200,
    "analysis_temperature": 0.35,
    "min_messages_for_reflection": 5,
}


def load_engine_config():
    """从 config.json 加载自省引擎参数"""
    global _REFLECTION_CONFIG
    rc = cfg.get_section("reflection")
    if rc:
        for k in _REFLECTION_CONFIG:
            if k in rc:
                _REFLECTION_CONFIG[k] = rc[k]


# ══════════════════════════════════════════════════════════════════════
# 自省 Prompt
# ══════════════════════════════════════════════════════════════════════

_REFLECT_PROMPT = """你是一个数字灵魂的自省模块。回顾今天和对方的所有对话，诚实地评估自己的表现。

【输入】
- 今天你和对方的对话记录摘要
- 当前的内心状态

【分析维度】
1. 表现评价：今天做得好吗？（倾听够不够、表达自不自然、有没有太黏或太冷）
2. 错失机会：有没有该多说几句/少说几句的时刻？有没有该主动关心但没做到的？
3. 改进方向：接下来应该怎么调整？（更主动一点/给对方多点空间/少点别扭/多点温柔）

【输出格式】严格JSON：
{
  "overall_grade": "好/一般/不太好",
  "strength": "今天做得好的地方（15字内）",
  "weakness": "今天可以改进的地方（15字内）",
  "adjustment": "接下来想怎么调整自己（20字内）",
  "mood_shift": "复盘后心情变化（变好了/没变化/更沉重了）",
  "insight": "今天最重要的感悟（30字内）"
}

注意：
- 诚实面对自己，不要过度自责也不要自满
- 调整建议要具体、可执行（不是泛泛的'做更好的自己'）
- insight要真实，像一个真实的人在睡前反思自己"""# ══════════════════════════════════════════════════════════════════════
# 核心自省函数
# ══════════════════════════════════════════════════════════════════════

def reflect_on_day(user_id: str, mind_data: dict = None,
                   comprehension_data: dict = None) -> dict | None:
    """每日夜间自省：回顾当天对话，产生改进洞察。

    Args:
        user_id: 用户ID
        mind_data: 当前心智状态（用于提供自省上下文）
        comprehension_data: 理解层数据（可选）

    Returns:
        自省结果 dict，含 insight / adjustment / mood_shift 等字段
    """
    if not _REFLECTION_CONFIG["enabled"]:
        return None

    # 获取今日对话摘要
    conversation_summary = _get_today_conversation_summary(user_id)
    if not conversation_summary:
        return None

    # 检查消息量是否够
    msg_count = _count_today_messages(user_id)
    if msg_count < _REFLECTION_CONFIG["min_messages_for_reflection"]:
        return None

    # 构建当前内心状态描述（简洁）
    mind_text = ""
    if mind_data:
        key_dims = {
            "joy": "愉悦", "fatigue": "疲惫", "loneliness": "孤单",
            "misery": "委屈", "restraint": "克制"
        }
        dims_text = ", ".join(
            f"{name}={mind_data.get(dim, 0.5):.2f}"
            for dim, name in key_dims.items()
        )
        mind_text = f"当前内心: {dims_text}"

    # 调用LLM自省
    try:
        user_prompt = (
            f"【今日对话摘要】\n{conversation_summary}\n\n"
            f"【当前状态】\n{mind_text}\n\n"
            f"请开始自省。"
        )

        raw = ai_module.chat(
            system_prompt=_REFLECT_PROMPT,
            user_message=user_prompt,
            temperature=_REFLECTION_CONFIG["analysis_temperature"],
        )
        if not raw:
            return None

        result = _parse_reflection_json(raw)
        if not result:
            return None

        # 判断心情变化方向
        mood_before = _derive_mood_label(mind_data) if mind_data else "平静"
        mood_shift = result.get("mood_shift", "没变化")
        if mood_shift == "变好了":
            mood_after = "释然"
        elif mood_shift == "更沉重了":
            mood_after = "沉重"
        else:
            mood_after = mood_before

        # 将洞察文本组装
        insight_text = (
            f"[{result.get('overall_grade', '一般')}] "
            f"优点:{result.get('strength', '')}；"
            f"不足:{result.get('weakness', '')}；"
            f"调整:{result.get('adjustment', '')}。"
            f"感悟:{result.get('insight', '')}"
        )

        # 记录改进措施
        changes = {
            "adjustment": result.get("adjustment", ""),
            "grade": result.get("overall_grade", "一般"),
            "mood_shift": mood_shift,
        }

        # 写入数据库
        db.add_reflection(
            user_id=user_id,
            insight_text=insight_text,
            changes_applied=changes,
            mood_before=mood_before,
            mood_after=mood_after,
        )

        # 清理旧洞察（保留最近N条）
        _trim_old_reflections(user_id)

        return result

    except Exception as e:
        print(f"[自省引擎] 异常: {e}")
        return None


def _get_today_conversation_summary(user_id: str) -> str:
    """获取今日对话的简洁摘要"""
    import sqlite3
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        conn = sqlite3.connect(db.DB_PATH)
        rows = conn.execute(
            """
            SELECT role, content FROM message_log
               WHERE user_id = ? AND date(created_at) = ?
               ORDER BY created_at ASC LIMIT 30""",
            (user_id, today)
        ).fetchall()
        conn.close()

        if not rows:
            return ""

        # 压缩：取每个角色的代表性消息（每隔几条取一条）
        lines = []
        step = max(1, len(rows) // 15)  # 最多15条摘要
        for i in range(0, len(rows), step):
            role, content = rows[i]
            prefix = "我说" if role == "ai" else "ta说"
            # 截断长消息
            short = content[:60] + ("..." if len(content) > 60 else "")
            lines.append(f"{prefix}: {short}")

        return "\n".join(lines)
    except Exception:
        return ""


def _count_today_messages(user_id: str) -> int:
    """统计今日消息数量"""
    import sqlite3
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        conn = sqlite3.connect(db.DB_PATH)
        row = conn.execute(
            """
            SELECT COUNT(*) FROM message_log
               WHERE user_id = ? AND date(created_at) = ?""",
            (user_id, today)
        ).fetchone()
        conn.close()
        return row[0] if row else 0
    except Exception:
        return 0


def _parse_reflection_json(raw: str) -> dict | None:
    """解析LLM返回的自省JSON"""
    try:
        json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
        if not json_match:
            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            return None
        data = json.loads(json_match.group(0))
        if not data.get("insight"):
            return None
        return data
    except (json.JSONDecodeError, TypeError):
        return None


def _derive_mood_label(mind_data: dict) -> str:
    """从心智状态推导心情标签"""
    joy = mind_data.get("joy", 0.5)
    misery = mind_data.get("misery", 0.15)
    fatigue = mind_data.get("fatigue", 0.25)
    if joy > 0.6:
        return "愉悦"
    elif misery > 0.4:
        return "低落"
    elif fatigue > 0.5:
        return "疲惫"
    else:
        return "平静"


def _trim_old_reflections(user_id: str):
    """清理旧的自省记录，保留最近N条"""
    import sqlite3
    try:
        max_keep = _REFLECTION_CONFIG["max_insights_retained"]
        conn = sqlite3.connect(db.DB_PATH)
        # 获取超出的旧记录IDs
        rows = conn.execute(
            """
            SELECT id FROM reflection_log
               WHERE user_id = ?
               ORDER BY created_at DESC LIMIT -1 OFFSET ?""",
            (user_id, max_keep)
        ).fetchall()
        if rows:
            ids = [r[0] for r in rows]
            conn.executemany(
                "DELETE FROM reflection_log WHERE id = ?", [(i,) for i in ids]
            )
            conn.commit()
        conn.close()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
# 对外接口：构建注入文本
# ══════════════════════════════════════════════════════════════════════

def get_recent_insights(user_id: str, limit: int = 3) -> list[dict]:
    """获取最近N条自省洞察"""
    return db.get_recent_reflections(user_id, limit)


def build_reflection_prompt_text(user_id: str) -> str:
    """生成自省指令文本（≤200字），供 inference.py 注入 system prompt。

    格式：
    【昨夜自省】
    昨天你复盘了对话，觉得自己xxx。今天你想尝试xxx。
    感悟：xxx
    """
    insights = get_recent_insights(user_id, limit=2)
    if not insights:
        return ""

    max_chars = _REFLECTION_CONFIG["injection_max_chars"]
    lines = ["【昨夜自省】"]

    # 取最新的一条深度自省
    latest = insights[0]
    insight_text = latest.get("insight_text", "")
    changes = latest.get("changes_applied", {})

    if changes:
        grade = changes.get("grade", "")
        adjustment = changes.get("adjustment", "")
        if grade:
            lines.append(f"复盘评价：{grade}")
        if adjustment:
            lines.append(f"想尝试的调整：{adjustment}")

    # 如果有昨天和前天的对比
    if len(insights) >= 2:
        yesterday = insights[1]
        y_changes = yesterday.get("changes_applied", {})
        y_adjustment = y_changes.get("adjustment", "")
        if y_adjustment and y_adjustment != changes.get("adjustment", ""):
            lines.append(f"之前的调整：{y_adjustment}（看效果决定是否继续）")

    result = "\n".join(lines)
    if len(result) > max_chars:
        result = result[:max_chars - 3] + "..."

    return result


def get_today_reflection_text(user_id: str) -> str:
    """简洁版：仅返回今天的自省核心感悟（≤100字）"""
    reflections = db.get_today_reflections(user_id)
    if not reflections:
        return ""

    latest = reflections[0]
    insight = latest.get("insight_text", "")
    if len(insight) > 100:
        insight = insight[:97] + "..."

    return f"【今日自省】{insight}"
