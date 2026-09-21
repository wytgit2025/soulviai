# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""承诺追踪引擎 — Commitment Tracker
让系统记住"对用户承诺过什么"，跨会话追踪兑现状态。

核心能力:
  1. record_commitment — 记录AI对用户的承诺
  2. check_overdue — 夜间检查超期未兑现的承诺
  3. get_pending_text — 注入prompt，让AI记得"还欠用户什么"
  4. mark_fulfilled — 兑现标记
"""
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from core import database as db

_COMMITMENT_TABLE = "commitment"
_OVERDUE_DAYS = 3


def _ensure_table():
    db._execute_raw(f"""
        CREATE TABLE IF NOT EXISTS {_COMMITMENT_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            content TEXT NOT NULL,
            context TEXT DEFAULT '',
            promise_type TEXT DEFAULT 'promise',
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            deadline TEXT DEFAULT '',
            fulfilled_at TEXT,
            bond_boost REAL DEFAULT 0.0
        )
    """)
    db._execute_raw(f"""
        CREATE INDEX IF NOT EXISTS idx_commit_user
        ON {_COMMITMENT_TABLE}(user_id, status)
    """)


def record_commitment(user_id: str, content: str,
                      context: str = "",
                      promise_type: str = "promise",
                      deadline: str = "") -> Optional[int]:
    """记录一条承诺（由 chat_pipeline 或 intention 调用）

    promise_type: 'promise' 答应的事, 'share' 下次分享, 'care' 关心对方
    """
    _ensure_table()
    try:
        row = db._execute(
            f"INSERT INTO {_COMMITMENT_TABLE} "
            f"(user_id, content, context, promise_type, deadline) "
            f"VALUES (?,?,?,?,?)",
            (user_id, content[:200], context[:100], promise_type, deadline),
            fetchone=True
        )
        return row["id"] if row and "id" in row else None
    except Exception:
        return None


def check_overdue(user_id: str, days: int = _OVERDUE_DAYS) -> List[dict]:
    """检查超期未兑现的承诺"""
    _ensure_table()
    try:
        rows = db._execute(
            f"SELECT * FROM {_COMMITMENT_TABLE} "
            f"WHERE user_id = ? AND status = 'pending' "
            f"AND datetime(created_at) < datetime('now', ? || ' days') "
            f"ORDER BY created_at ASC",
            (user_id, f"-{days}"),
            fetchall=True
        )
        return [dict(r) for r in rows] if rows else []
    except Exception:
        return []


def get_pending_commitments(user_id: str, max_count: int = 5) -> List[dict]:
    """获取待兑现的承诺列表"""
    _ensure_table()
    try:
        rows = db._execute(
            f"SELECT * FROM {_COMMITMENT_TABLE} "
            f"WHERE user_id = ? AND status = 'pending' "
            f"ORDER BY deadline ASC, created_at ASC LIMIT ?",
            (user_id, max_count),
            fetchall=True
        )
        return [dict(r) for r in rows] if rows else []
    except Exception:
        return []


def get_pending_text(user_id: str) -> str:
    """构建承诺注入文本（用于 prompt 注入）"""
    items = get_pending_commitments(user_id, 3)
    if not items:
        return ""

    lines = []
    for item in items:
        content = item.get("content", "")
        days_old = _days_since(item.get("created_at", ""))
        prefix = "你答应过"
        if item.get("promise_type") == "share":
            prefix = "你说下次要"
        elif item.get("promise_type") == "care":
            prefix = "你想着要"
        tag = f"(已经{days_old}天了)" if days_old > 1 else ""
        lines.append(f"  · {prefix}{content} {tag}")

    return "【你还记得答应过的事吗】\n" + "\n".join(lines)


def _days_since(created_str: str) -> int:
    try:
        created = datetime.strptime(created_str, "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - created).days
    except Exception:
        return 0


def mark_fulfilled(commitment_id: int, bond_boost: float = 0.05):
    """标记承诺已兑现"""
    try:
        db._execute(
            f"UPDATE {_COMMITMENT_TABLE} SET status = 'done', "
            f"fulfilled_at = datetime('now','localtime'), "
            f"bond_boost = ? WHERE id = ?",
            (bond_boost, commitment_id)
        )
    except Exception:
        pass


def get_goal_status_text(user_id: str) -> str:
    """获取目标进展文本（用于 prompt 注入）"""
    try:
        goals = db._execute(
            "SELECT id, goal, progress, priority FROM planning_goal "
            "WHERE user_id = ? AND status = 'active' ORDER BY priority DESC LIMIT 3",
            (user_id,),
            fetchall=True
        )
        if not goals:
            return ""

        lines = []
        for g in goals:
            pct = int((g.get("progress", 0) or 0) * 100)
            lines.append(f"  · {g['goal'][:40]} ({pct}%)")

        return "【你正在努力的事】\n" + "\n".join(lines)
    except Exception:
        return ""
