# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""反馈学习闭环
评估每轮对话的质量，调整后续互动策略。
- 用户连续追问/纠正 → 上次回复质量差 → 调整
- 用户接着聊很开心 → 上次回复好 → 强化
- 用户沉默/冷淡 → 需要调整方式
"""
from core import database as db
from core import ai as ai_module

# ── 反馈分析 Prompt ──
_ANALYZE_PROMPT = """你是对话质量分析器。根据上下文判断上次回复的效果。

【输入】
- 上一轮AI回复 + 用户的新消息

【分析】
1. 用户的反应是正向还是负向？
2. 是否需要调整回复策略？

仅输出JSON：
{"outcome":"正向/负向/中性","reason":"简短原因(15字内)","adjustment_hint":"改进建议或保持提示(20字内)"}

判断标准：
- 用户接着追问/纠正/否定 → 负向
- 用户开心继续/赞同/表白 → 正向
- 用户普通回应/新话题 → 中性"""
def load_engine_config():
    pass


def analyze_round(user_id: str, my_last_response: str,
                  user_next_message: str, comprehension: dict = None):
    """分析本轮对话质量，存入反馈日志。
    在下次回复生成前调用。
    """
    if not my_last_response or not user_next_message:
        return

    # 快速规则判定（省LLM调用）
    quick = _quick_analyze(user_next_message, comprehension)
    if quick is not None:
        db.add_feedback(user_id, "对话", my_last_response[:50],
                        quick[0], quick[1])
        return

    # LLM 深度分析（消息较长时）
    if len(user_next_message) > 15 and len(my_last_response) > 10:
        try:
            context = (
                f"我的回复: {my_last_response[:80]}\n"
                f"对方新消息: {user_next_message[:80]}"
            )
            raw = ai_module.chat(
                system_prompt=_ANALYZE_PROMPT,
                user_message=context,
                temperature=0.2,
            )
            import json, re
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                outcome = data.get("outcome", "中性")
                reason = data.get("reason", "")
                eff = {"正向": 0.7, "负向": 0.3, "中性": 0.5}.get(outcome, 0.5)
                db.add_feedback(user_id, reason[:30], my_last_response[:50],
                                outcome, eff)
        except Exception:
            pass  # 静默失败


def _quick_analyze(user_msg: str, comprehension: dict = None):
    """快速规则判定反馈，返回 (outcome, effectiveness) 或 None"""
    msg = user_msg.strip()

    # 正向
    positive_signals = ["哈哈", "好好笑", "你真好", "爱了", "感动", "谢谢",
                        "想你了", "开心", "喜欢你", "好温暖"]
    for s in positive_signals:
        if s in msg:
            return ("正向", 0.75)

    # 负向
    negative_signals = ["不是", "不对", "算了", "不用了", "没意思", "随便",
                        "你听不懂", "别说了", "行吧", "哦"]
    for s in negative_signals:
        if s in msg:
            return ("负向", 0.3)

    # 用户追问（说明上次回复不够好）
    if len(msg) > 10 and ("?" in msg or "吗" in msg or "呢" in msg):
        if comprehension and comprehension.get("intent") == "提问":
            if "追问" in str(comprehension.get("depth", "")):
                return ("负向", 0.35)

    return None


def get_adjustment_hint(user_id: str) -> str:
    """基于历史反馈，给出策略调整提示。
    用于注入推理层 System Prompt。
    """
    try:
        stats = db.get_feedback_stats(user_id)
        if stats["total"] < 3:
            return ""

        rate = stats["positive_rate"]

        if rate > 0.8:
            return "最近的互动反馈很好——继续保持当前的表达风格。"

        if rate < 0.3 and stats["total"] > 5:
            return (
                "最近几轮对话对方反应不太好。可以试试："
                "少给建议多倾听、语气再柔软一点、适当追问ta的感受。"
            )
    except Exception:
        pass
    return ""
