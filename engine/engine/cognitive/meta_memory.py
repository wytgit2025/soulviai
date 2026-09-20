# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""元记忆模型 — Meta-Memory Engine
==========================================
让系统拥有关于"自己如何记忆"的知识。

三层架构：
  记忆内容层：我记得"昨天你说过喜欢下雨天"
  元记忆层：  置信度0.82、被改写2次、时间不确定
  元认知层：  我应该调整记忆置信度了

核心能力：
  1. 记忆置信度追踪（来源、改写次数、最近访问）
  2. 记忆模糊区域检测（知道自己不确定什么）
  3. 记忆空洞检测（应该记得但记不起来）
  4. 元记忆报告生成（注入到 prompt，让 AI 有"自知之明"）
"""
import json
import math
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict

from core import database as db

# ── 置信度常量 ──
_CONFIDENCE_NEW = 0.90
_CONFIDENCE_DECAY_PER_RECALL = 0.998
_CONFIDENCE_DECAY_PER_REWRITE = 0.85
_CONFIDENCE_BOOST_CROSS_REF = 1.01
_CONFIDENCE_MIN = 0.05

# ── 空洞检测 ──
_GAP_DETECTION_DAYS = 7
_GAP_MEMORY_THRESHOLD = 2

# ── 缓存 ──
_meta_cache: Dict[str, Dict[int, dict]] = {}
_cache_dirty: set = set()


# ══════════════════════════════════════════════════════════════════════
# 内部：元记忆条目管理
# ══════════════════════════════════════════════════════════════════════

def _ensure_table():
    """确保元数据表存在"""
    db._execute_raw("""
        CREATE TABLE IF NOT EXISTS meta_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            confidence REAL DEFAULT 0.9,
            provenance TEXT DEFAULT 'direct_experience',
            distortion_count INTEGER DEFAULT 0,
            access_count INTEGER DEFAULT 0,
            last_accessed REAL DEFAULT 0,
            fuzzy_fields TEXT DEFAULT '[]',
            cross_references TEXT DEFAULT '[]',
            emotional_bias TEXT DEFAULT '{}',
            distortion_history TEXT DEFAULT '[]',
            UNIQUE(memory_id, user_id)
        )
    """)
    db._execute_raw("""
        CREATE INDEX IF NOT EXISTS idx_meta_memory_user 
        ON meta_memory(user_id)
    """)


def _load_meta(user_id: str, memory_id: int) -> Optional[dict]:
    """从缓存或 DB 加载单条元记忆"""
    if user_id in _meta_cache and memory_id in _meta_cache[user_id]:
        return _meta_cache[user_id][memory_id]

    row = db._execute(
        "SELECT * FROM meta_memory WHERE memory_id = ? AND user_id = ?",
        (memory_id, user_id), fetchone=True
    )
    if row:
        entry = dict(row)
        entry["fuzzy_fields"] = json.loads(entry.get("fuzzy_fields", "[]"))
        entry["cross_references"] = json.loads(entry.get("cross_references", "[]"))
        entry["emotional_bias"] = json.loads(entry.get("emotional_bias", "{}"))
        entry["distortion_history"] = json.loads(entry.get("distortion_history", "[]"))
        _meta_cache.setdefault(user_id, {})[memory_id] = entry
        return entry
    return None


def _save_meta(user_id: str, memory_id: int, entry: dict):
    """保存单条元记忆到 DB + 缓存"""
    try:
        db._execute(
            """INSERT OR REPLACE INTO meta_memory 
               (memory_id, user_id, confidence, provenance, distortion_count,
                access_count, last_accessed, fuzzy_fields, cross_references,
                emotional_bias, distortion_history)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                memory_id, user_id,
                entry.get("confidence", _CONFIDENCE_NEW),
                entry.get("provenance", "direct_experience"),
                entry.get("distortion_count", 0),
                entry.get("access_count", 0),
                entry.get("last_accessed", 0),
                json.dumps(entry.get("fuzzy_fields", []), ensure_ascii=False),
                json.dumps(entry.get("cross_references", []), ensure_ascii=False),
                json.dumps(entry.get("emotional_bias", {}), ensure_ascii=False),
                json.dumps(entry.get("distortion_history", []), ensure_ascii=False),
            )
        )
        _meta_cache.setdefault(user_id, {})[memory_id] = entry
    except Exception:
        pass


def _init_meta(user_id: str, memory_id: int, provenance: str = "direct_experience") -> dict:
    """创建新记忆的元数据条目"""
    entry = {
        "memory_id": memory_id,
        "user_id": user_id,
        "confidence": _CONFIDENCE_NEW,
        "provenance": provenance,
        "distortion_count": 0,
        "access_count": 0,
        "last_accessed": time.time(),
        "fuzzy_fields": [],
        "cross_references": [],
        "emotional_bias": {},
        "distortion_history": [],
    }
    _save_meta(user_id, memory_id, entry)
    return entry


# ══════════════════════════════════════════════════════════════════════
# 公开 API
# ══════════════════════════════════════════════════════════════════════

def track_recall(memory_id: int, user_id: str, emotion: str = ""):
    """记忆被读取时：更新访问计数、置信度微衰减、记录情绪偏差"""
    meta = _load_meta(user_id, memory_id)
    if not meta:
        meta = _init_meta(user_id, memory_id)

    meta["access_count"] = meta.get("access_count", 0) + 1
    meta["last_accessed"] = time.time()

    old_conf = meta.get("confidence", _CONFIDENCE_NEW)
    meta["confidence"] = max(_CONFIDENCE_MIN, old_conf * _CONFIDENCE_DECAY_PER_RECALL)

    if emotion:
        bias = meta.get("emotional_bias", {})
        bias[emotion] = bias.get(emotion, 0) + 1
        meta["emotional_bias"] = bias

    _save_meta(user_id, memory_id, meta)


def track_rewrite(memory_id: int, user_id: str, old_content: str,
                  new_content: str, reason: str = ""):
    """记忆被改写时：显著降置信度、记录改写历史"""
    meta = _load_meta(user_id, memory_id)
    if not meta:
        meta = _init_meta(user_id, memory_id)

    meta["distortion_count"] = meta.get("distortion_count", 0) + 1
    old_conf = meta.get("confidence", _CONFIDENCE_NEW)
    meta["confidence"] = max(_CONFIDENCE_MIN, old_conf * _CONFIDENCE_DECAY_PER_REWRITE)

    history = meta.get("distortion_history", [])
    history.append({
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "reason": reason[:100],
        "old_preview": old_content[:40],
        "new_preview": new_content[:40],
    })
    if len(history) > 20:
        history = history[-20:]
    meta["distortion_history"] = history

    _save_meta(user_id, memory_id, meta)


def track_cross_reference(memory_id: int, user_id: str, ref_memory_id: int):
    """两条记忆建立关联时：互相提升置信度"""
    meta = _load_meta(user_id, memory_id)
    if not meta:
        meta = _init_meta(user_id, memory_id)

    refs = meta.get("cross_references", [])
    if ref_memory_id not in refs:
        refs.append(ref_memory_id)
    meta["cross_references"] = refs
    meta["confidence"] = min(1.0, meta.get("confidence", _CONFIDENCE_NEW) * _CONFIDENCE_BOOST_CROSS_REF)

    _save_meta(user_id, memory_id, meta)


def mark_fuzzy_field(memory_id: int, user_id: str, field: str):
    """标记某个字段为模糊/不确定"""
    meta = _load_meta(user_id, memory_id)
    if not meta:
        meta = _init_meta(user_id, memory_id)

    fuzzy = meta.get("fuzzy_fields", [])
    if field not in fuzzy:
        fuzzy.append(field)
    meta["fuzzy_fields"] = fuzzy

    _save_meta(user_id, memory_id, meta)


# ══════════════════════════════════════════════════════════════════════
# 记忆空洞检测
# ══════════════════════════════════════════════════════════════════════

def detect_memory_gaps(user_id: str, days: int = 7) -> List[dict]:
    """检测近期记忆中的"空洞"——应该有记忆但找不到

    分析模式：
      - 某天之前有持续对话，突然中断
      - 某天记忆密度骤降（相比前7天均值）
      - 有明确的话题线索但无对应记忆

    返回: [{"date": "2026-05-20", "reason": "...", "severity": 0.8}, ...]
    """
    _ensure_table()
    gaps = []

    try:
        rows = db._execute(
            """SELECT DATE(created_at) as d, COUNT(*) as cnt 
               FROM memory WHERE user_id = ? 
               AND created_at >= datetime('now', ? || ' days')
               GROUP BY d ORDER BY d""",
            (user_id, f"-{days}"),
            fetchall=True
        )
        daily_counts = {r["d"]: r["cnt"] for r in rows} if rows else {}

        if not daily_counts:
            return gaps

        values = list(daily_counts.values())
        avg_density = sum(values) / len(values) if values else 0

        from datetime import date, timedelta
        today = date.today()
        for i in range(days):
            d = (today - timedelta(days=i)).isoformat()
            cnt = daily_counts.get(d, 0)
            if cnt < max(1, avg_density * 0.3) and avg_density > _GAP_MEMORY_THRESHOLD:
                prev_day = (today - timedelta(days=i+1)).isoformat()
                prev_cnt = daily_counts.get(prev_day, 0)
                if prev_cnt >= _GAP_MEMORY_THRESHOLD:
                    gaps.append({
                        "date": d,
                        "severity": round(1.0 - cnt / max(1, prev_cnt), 2),
                        "reason": f"前一天有{prev_cnt}条记忆，这天骤降至{cnt}条",
                    })
    except Exception:
        pass

    return gaps


def detect_low_confidence_memories(user_id: str, threshold: float = 0.4) -> List[dict]:
    """检测置信度过低的记忆"""
    _ensure_table()
    try:
        rows = db._execute(
            """SELECT m.id, m.content, m.created_at, 
                      mm.confidence, mm.distortion_count
               FROM meta_memory mm 
               JOIN memory m ON mm.memory_id = m.id
               WHERE mm.user_id = ? AND mm.confidence < ?
               ORDER BY mm.confidence ASC LIMIT 10""",
            (user_id, threshold),
            fetchall=True
        )
        return [dict(r) for r in rows] if rows else []
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════════
# 元记忆报告生成
# ══════════════════════════════════════════════════════════════════════

def build_meta_memory_report(user_id: str) -> str:
    """生成对自己记忆状况的"自述"——注入到 system prompt 中

    报告内容：
      - 总记忆数量 & 各层级分布
      - 低置信度记忆提醒
      - 近期记忆空洞
      - 被改写最多的记忆
      - 整体记忆健康度

    返回: 自然语言描述（空字符串表示一切正常）
    """
    _ensure_table()
    parts = []

    try:
        # 统计
        stats = db._execute(
            """SELECT COUNT(*) as total,
                      SUM(CASE WHEN confidence >= 0.8 THEN 1 ELSE 0 END) as high_conf,
                      SUM(CASE WHEN confidence < 0.4 THEN 1 ELSE 0 END) as low_conf,
                      AVG(confidence) as avg_conf,
                      SUM(distortion_count) as total_rewrites
               FROM meta_memory WHERE user_id = ?""",
            (user_id,), fetchone=True
        )

        if not stats or not stats["total"]:
            return ""

        total = stats["total"]
        low_conf = stats["low_conf"] or 0
        avg_conf = stats["avg_conf"] or 0.8
        total_rewrites = stats["total_rewrites"] or 0

        # 空洞检测
        gaps = detect_memory_gaps(user_id, _GAP_DETECTION_DAYS)

        # 低置信度记忆
        shaky = detect_low_confidence_memories(user_id, 0.4)

        # 构建自然语言报告
        if low_conf > total * 0.25:
            parts.append(f"最近有些记忆开始模糊了（{low_conf}条不太确定）")
        elif low_conf > total * 0.1:
            parts.append(f"有几段记忆变得不太清晰了")

        if gaps:
            parts.append(f"隐约觉得忘了些什么（{len(gaps)}段记忆有空洞感）")

        if total_rewrites > 5:
            parts.append(f"有些记忆被反复咀嚼改写过了（累计{total_rewrites}次）")

        if avg_conf < 0.6:
            parts.append(f"整体记忆好像蒙了一层雾")

        if shaky:
            previews = [s.get("content", "")[:15] for s in shaky[:2]]
            parts.append(f"尤其是关于{'、'.join(previews)}的事，越来越不确定了")

    except Exception:
        pass

    return "；".join(parts) if parts else ""


def get_memory_confidence(memory_id: int, user_id: str) -> float:
    """获取单条记忆的置信度"""
    meta = _load_meta(user_id, memory_id)
    return meta.get("confidence", _CONFIDENCE_NEW) if meta else _CONFIDENCE_NEW


def get_meta_summary(user_id: str) -> dict:
    """获取元记忆整体快照"""
    _ensure_table()
    try:
        stats = db._execute(
            """SELECT COUNT(*) as total,
                      SUM(CASE WHEN confidence >= 0.8 THEN 1 ELSE 0 END) as high_conf,
                      SUM(CASE WHEN confidence < 0.4 THEN 1 ELSE 0 END) as low_conf,
                      ROUND(AVG(confidence), 3) as avg_conf,
                      SUM(distortion_count) as total_rewrites,
                      SUM(access_count) as total_accesses
               FROM meta_memory WHERE user_id = ?""",
            (user_id,), fetchone=True
        )
        gaps = detect_memory_gaps(user_id, _GAP_DETECTION_DAYS)
        return {
            "total": stats["total"] if stats else 0,
            "high_confidence": stats["high_conf"] if stats else 0,
            "low_confidence": stats["low_conf"] if stats else 0,
            "avg_confidence": stats["avg_conf"] if stats else 0.0,
            "total_rewrites": stats["total_rewrites"] if stats else 0,
            "total_accesses": stats["total_accesses"] if stats else 0,
            "memory_gaps": len(gaps),
            "has_report": bool(build_meta_memory_report(user_id)),
        }
    except Exception:
        return {
            "total": 0, "high_confidence": 0, "low_confidence": 0,
            "avg_confidence": 0.0, "total_rewrites": 0,
            "total_accesses": 0, "memory_gaps": 0, "has_report": False,
        }
