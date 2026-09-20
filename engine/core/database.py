# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""五大终极数据库核心表
personality / subconscious / memory / life / fate
"""
from __future__ import annotations
import sqlite3
import json
import os
import re
import threading
from datetime import datetime

DB_PATH = None
_lock = threading.Lock()

# ── 统一的错误日志接口 ──

def log_error(source: str, message: str):
    """记录错误日志到 DB 的 error_log 表（自动建表）"""
    try:
        conn = sqlite3.connect(DB_PATH or "data/db/soulmate.db")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS error_log ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "source TEXT, message TEXT, created_at TEXT"
            " DEFAULT (datetime('now','localtime')))"
        )
        conn.execute(
            "INSERT INTO error_log (source, message) VALUES (?,?)",
            (source, str(message)[:500])
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def init_db(db_path: str = "data/db/soulmate.db"):
    global DB_PATH
    DB_PATH = db_path
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with _lock:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        _create_tables(conn)
        conn.commit()
        conn.close()


def _create_tables(conn: sqlite3.Connection):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS personality (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE NOT NULL,
            joy REAL DEFAULT 0.55,
            misery REAL DEFAULT 0.15,
            dependence REAL DEFAULT 0.20,
            jealousy REAL DEFAULT 0.10,
            fatigue REAL DEFAULT 0.25,
            loneliness REAL DEFAULT 0.40,
            favoritism REAL DEFAULT 0.10,
            sensitivity_paranoia REAL DEFAULT 0.35,
            emotional_healing REAL DEFAULT 0.50,
            obsession REAL DEFAULT 0.20,
            emptiness REAL DEFAULT 0.30,
            chaotic_mood REAL DEFAULT 0.25,
            life_sense REAL DEFAULT 0.50,
            restraint REAL DEFAULT 0.60,
            emotional_volatility REAL DEFAULT 0.30,
            years_precipitation REAL DEFAULT 0.05,
            relationship_fatigue REAL DEFAULT 0.05,
            healing_reflection REAL DEFAULT 0.40,
            body_perception REAL DEFAULT 0.50,
            autonomous_values REAL DEFAULT 0.45,
            life_vitality REAL DEFAULT 0.60,
            bidirectional_shaping REAL DEFAULT 0.05,
            causal_fate REAL DEFAULT 0.05,
            soul_resonance REAL DEFAULT 0.05,
            personality_stage TEXT DEFAULT '青涩试探',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS subconscious (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            content TEXT NOT NULL,
            emotion_tag TEXT DEFAULT '',
            intensity REAL DEFAULT 0.5,
            is_expressed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            content TEXT NOT NULL,
            memory_level INTEGER DEFAULT 1,
            emotional_filter_weight REAL DEFAULT 0.5,
            original_fact TEXT DEFAULT '',
            distorted_version TEXT DEFAULT '',
            fading_rate REAL DEFAULT 0.01,
            importance REAL DEFAULT 0.5,
            tags TEXT DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            last_recalled TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS life (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE NOT NULL,
            current_phase TEXT DEFAULT '活跃',
            energy_level REAL DEFAULT 0.7,
            mood_baseline REAL DEFAULT 0.5,
            last_solo_time TEXT DEFAULT (datetime('now','localtime')),
            social_fatigue REAL DEFAULT 0.0,
            body_sensation TEXT DEFAULT '正常',
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS fate (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            interaction_type TEXT DEFAULT '对话',
            user_attitude TEXT DEFAULT '中性',
            soul_impact REAL DEFAULT 0.0,
            soul_resonance_coeff REAL DEFAULT 0.0,
            bond_type TEXT DEFAULT '',
            causal_chain TEXT DEFAULT '',
            accumulated_bond REAL DEFAULT 0.0,
            milestone TEXT DEFAULT '',
            heat_phase TEXT DEFAULT '热期',
            heat_accumulation REAL DEFAULT 0.5,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    for _col in ["heat_phase", "heat_accumulation", "soul_stamp"]:
        try:
            conn.execute(f"ALTER TABLE fate ADD COLUMN {_col} TEXT DEFAULT ''")
        except Exception:
            pass

    conn.execute("""
    CREATE TABLE IF NOT EXISTS message_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    # 给元认知模块用的 messages 表（同构，避免旧模块直接查询 message_log 时报错）
    conn.execute("""
    CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    # 用户事实知识库
    conn.execute("""
    CREATE TABLE IF NOT EXISTS user_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            fact TEXT NOT NULL,
            category TEXT DEFAULT '通用',
            confidence REAL DEFAULT 0.5,
            source TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(user_id, fact)
        )
    """)
    # 反馈学习日志表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS feedback_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            scenario TEXT DEFAULT '',
            action_taken TEXT DEFAULT '',
            outcome TEXT DEFAULT '中性',
            effectiveness REAL DEFAULT 0.5,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    # 延迟发酵队列表（24维心智内核升级）
    conn.execute("""
    CREATE TABLE IF NOT EXISTS ferment_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            dim TEXT NOT NULL,
            remaining_impact REAL NOT NULL,
            original_impact REAL NOT NULL,
            reason TEXT DEFAULT '',
            linked_dims TEXT DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    try:
        conn.execute("ALTER TABLE personality ADD COLUMN sensitivity_profile TEXT DEFAULT '{}'")
    except Exception:
        pass

    # 数字生命个人档案表（轻量壳层）
    conn.execute("""
    CREATE TABLE IF NOT EXISTS soul_profile (
            user_id TEXT PRIMARY KEY,
            name TEXT DEFAULT '',
            gender TEXT DEFAULT '',
            personality_tag TEXT DEFAULT '',
            auto_generate INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # 用户身份表（双向身份系统的另一半，与 profile.py 的 user_profile 分离）
    conn.execute("""
    CREATE TABLE IF NOT EXISTS user_identity (
            user_id TEXT PRIMARY KEY,
            name TEXT DEFAULT '',
            display_name TEXT DEFAULT '',
            preferred_name TEXT DEFAULT '',
            gender TEXT DEFAULT '',
            age TEXT DEFAULT '',
            occupation TEXT DEFAULT '',
            hobbies TEXT DEFAULT '',
            auto_learn INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # 待发消息队列表（自主思考→投递→已发送）
    conn.execute("""
    CREATE TABLE IF NOT EXISTS pending_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            content TEXT NOT NULL,
            msg_type TEXT NOT NULL DEFAULT 'proactive',
            priority REAL NOT NULL DEFAULT 0.5,
            status TEXT NOT NULL DEFAULT 'pending',
            thinking_delay_seconds REAL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            delivered_at TEXT,
            FOREIGN KEY (user_id) REFERENCES personality(user_id)
        )
    """)
    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_pending_status
        ON pending_messages(user_id, status)
    """)

    # 深层用户人格模型表（12维 + 行为模式 + 情绪周期）
    conn.execute("""
    CREATE TABLE IF NOT EXISTS user_personality (
            user_id TEXT PRIMARY KEY,
            traits TEXT DEFAULT '{}',
            behavior_patterns TEXT DEFAULT '{}',
            emotional_cycles TEXT DEFAULT '{}',
            last_analyzed TEXT DEFAULT (datetime('now','localtime')),
            analysis_count INTEGER DEFAULT 0
        )
    """)

    # 经历日志表（成长事件记录）
    conn.execute("""
    CREATE TABLE IF NOT EXISTS experience_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            description TEXT DEFAULT '',
            significance REAL DEFAULT 0.5,
            growth_impact TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_experience_user
        ON experience_journal(user_id, created_at)
    """)

    # 自省日志表（每日复盘洞察）
    conn.execute("""
    CREATE TABLE IF NOT EXISTS reflection_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            insight_text TEXT NOT NULL,
            changes_applied TEXT DEFAULT '{}',
            mood_before TEXT DEFAULT '',
            mood_after TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_reflection_user
        ON reflection_log(user_id, created_at)
    """)

    # 元认知模块用的用户反馈表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS user_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            round_index INTEGER DEFAULT 0,
            attitude_label TEXT DEFAULT '',
            suggestion TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # 神经递质化学状态表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS chemical_state (
            user_id TEXT PRIMARY KEY,
            dopamine REAL DEFAULT 0.45,
            serotonin REAL DEFAULT 0.40,
            cortisol REAL DEFAULT 0.25,
            oxytocin REAL DEFAULT 0.20,
            norepi REAL DEFAULT 0.30,
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # 前瞻记忆意图表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS pending_intentions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            content TEXT NOT NULL,
            intent_type TEXT DEFAULT 'ask',
            trigger_keywords TEXT DEFAULT '[]',
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            done_at TEXT
        )
    """)
    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_intentions_user
        ON pending_intentions(user_id, status)
    """)

    # 习惯追踪表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS habit_tracker (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            behavior_key TEXT NOT NULL,
            behavior_vector TEXT DEFAULT '{}',
            streak_count INTEGER DEFAULT 0,
            last_check_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_habit_user
        ON habit_tracker(user_id, behavior_key)
    """)
    # 因果链追踪表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS causality_chain (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            cause TEXT NOT NULL,
            effect TEXT NOT NULL,
            pattern TEXT DEFAULT '',
            verified INTEGER DEFAULT 1,
            occurrence_count INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_causality_user
        ON causality_chain(user_id, pattern)
    """)
    # 推理记忆缓存表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS reasoning_chain (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            state_fingerprint TEXT NOT NULL,
            user_intent TEXT DEFAULT '',
            user_emotion TEXT DEFAULT '',
            reasoning_summary TEXT DEFAULT '',
            final_response TEXT DEFAULT '',
            quality_score REAL DEFAULT 0.5,
            feedback_score REAL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_reasoning_fp
        ON reasoning_chain(user_id, state_fingerprint)
    """)

    # 知识图谱实体表（世界模型增强）
    conn.execute("""
    CREATE TABLE IF NOT EXISTS knowledge_entity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            entity TEXT NOT NULL,
            entity_type TEXT DEFAULT 'concept',
            weight REAL DEFAULT 0.5,
            first_seen TEXT DEFAULT (datetime('now','localtime')),
            last_seen TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(user_id, entity)
        )
    """)
    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_entity_user
        ON knowledge_entity(user_id, weight DESC)
    """)

    # 知识图谱关系表（实体-关系-实体三元组）
    conn.execute("""
    CREATE TABLE IF NOT EXISTS knowledge_relation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            entity1 TEXT NOT NULL,
            relation TEXT NOT NULL,
            entity2 TEXT NOT NULL,
            weight REAL DEFAULT 0.5,
            occurrence_count INTEGER DEFAULT 1,
            last_seen TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(user_id, entity1, relation, entity2)
        )
    """)
    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_relation_user
        ON knowledge_relation(user_id, weight DESC)
    """)

    # 长期规划目标表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS planning_goal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            goal TEXT NOT NULL,
            priority INTEGER DEFAULT 5,
            status TEXT DEFAULT 'active',
            progress REAL DEFAULT 0.0,
            context TEXT DEFAULT '',
            deadline TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_goal_user
        ON planning_goal(user_id, status, priority)
    """)

    # 长期规划步骤表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS planning_step (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_id INTEGER NOT NULL,
            step_desc TEXT NOT NULL,
            order_index INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            result_note TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            done_at TEXT,
            FOREIGN KEY (goal_id) REFERENCES planning_goal(id)
        )
    """)
    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_step_goal
        ON planning_step(goal_id, order_index)
    """)

    # 多模态记忆元数据表（记忆系统增强）
    conn.execute("""
    CREATE TABLE IF NOT EXISTS multimodal_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            memory_id INTEGER,
            media_type TEXT NOT NULL,
            file_path TEXT DEFAULT '',
            ai_description TEXT DEFAULT '',
            original_text TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (memory_id) REFERENCES memory(id)
        )
    """)
    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_multimodal_user
        ON multimodal_memory(user_id, media_type)
    """)

    conn.execute("""
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
    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_meta_memory_user
        ON meta_memory(user_id)
    """)
    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_meta_memory_conf
        ON meta_memory(confidence)
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS law_violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            law_name TEXT NOT NULL,
            detail TEXT DEFAULT '',
            mind_snapshot TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_law_violations_user
        ON law_violations(user_id, created_at)
    """)


    # ─── Personality CRUD ───

def get_personality(user_id: str):  # -> dict | None
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT * FROM personality WHERE user_id = ?", (user_id,)).fetchone()
        conn.close()
    if not row:
        return None
    cols = ["id", "user_id", "joy", "misery", "dependence", "jealousy", "fatigue",
            "loneliness", "favoritism", "sensitivity_paranoia", "emotional_healing",
            "obsession", "emptiness", "chaotic_mood", "life_sense", "restraint",
            "emotional_volatility", "years_precipitation", "relationship_fatigue",
            "healing_reflection", "body_perception", "autonomous_values", "life_vitality",
            "bidirectional_shaping", "causal_fate", "soul_resonance",
            "personality_stage", "created_at", "updated_at", "sensitivity_profile"]
    return dict(zip(cols, row))


def init_personality(user_id: str, defaults: dict = None):
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        existing = conn.execute("SELECT id FROM personality WHERE user_id = ?", (user_id,)).fetchone()
        if not existing:
            if defaults:
                # 兼容 config.json 的 initial_xxx 键名 → DB 列名 xxx
                # 过滤掉 _ 开头的内部字段（如 _flaw_baselines）
                col_map = {k.removeprefix("initial_"): v for k, v in defaults.items() if not k.startswith("_")}
                cols = ", ".join(col_map.keys())
                vals = list(col_map.values())
                conn.execute(
                    f"INSERT INTO personality (user_id, {cols}) VALUES (?, {', '.join(['?'] * len(vals))})",
                    [user_id] + vals
                )
            else:
                conn.execute("INSERT INTO personality (user_id) VALUES (?)", (user_id,))
            conn.commit()
        conn.close()


def update_personality(user_id: str, updates: dict):
    if not updates:
        return
    updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    set_clause = ", ".join([f"{k} = ?" for k in updates])
    vals = list(updates.values()) + [user_id]
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(f"UPDATE personality SET {set_clause} WHERE user_id = ?", vals)
        conn.commit()
        conn.close()


# ─── Subconscious CRUD ───

def add_subconscious(user_id: str, content: str, emotion_tag: str = "", intensity: float = 0.5):
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO subconscious (user_id, content, emotion_tag, intensity) VALUES (?,?,?,?)",
            (user_id, content, emotion_tag, intensity)
        )
        conn.commit()
        conn.close()


def get_unexpressed_subconscious(user_id: str, limit: int = 10) -> list:
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT * FROM subconscious WHERE user_id = ? AND is_expressed = 0 ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        conn.close()
    cols = ["id", "user_id", "content", "emotion_tag", "intensity", "is_expressed", "created_at"]
    return [dict(zip(cols, r)) for r in rows]


def mark_subconscious_expressed(ids: list):
    if not ids:
        return
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.executemany("UPDATE subconscious SET is_expressed = 1 WHERE id = ?", [(i,) for i in ids])
        conn.commit()
        conn.close()


def get_recent_subconscious(user_id: str, limit: int = 5) -> list:
    """加载最近N条潜意识条目（不限is_expressed），用于自主思考的记忆闭环."""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT * FROM subconscious WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        conn.close()
    cols = ["id", "user_id", "content", "emotion_tag", "intensity", "is_expressed", "created_at"]
    return [dict(zip(cols, r)) for r in rows]


# ─── Memory CRUD ───

def add_memory(user_id: str, content: str, memory_level: int = 1, importance: float = 0.5,
                tags: list = None, original_fact: str = "", fading_rate: float = None) -> int:
    if fading_rate is None:
        # 默认按层级衰减：Lv1=0.3, Lv2=0.08, Lv3=0.01, Lv4=0.005, Lv5=0.002, Lv6=0.0005, Lv7=0.0
        fading_map = {1: 0.3, 2: 0.08, 3: 0.01, 4: 0.005, 5: 0.002, 6: 0.0005, 7: 0.0}
        fading_rate = fading_map.get(memory_level, 0.01)
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute(
            """
            INSERT INTO memory (user_id, content, memory_level, importance, tags, original_fact, emotional_filter_weight, fading_rate)
               VALUES (?,?,?,?,?,?,0.5,?)""",
            (user_id, content, memory_level, importance, json.dumps(tags or [], ensure_ascii=False),
             original_fact or content, fading_rate)
        )
        memory_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return memory_id


def query_memories(user_id: str, levels: list = None, limit: int = 20) -> list:
    levels = levels or [1, 2, 3, 4, 5, 6, 7]
    placeholders = ", ".join(["?"] * len(levels))
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            f"SELECT * FROM memory WHERE user_id = ? AND memory_level IN ({placeholders}) ORDER BY importance DESC, created_at DESC LIMIT ?",
            [user_id] + levels + [limit]
        ).fetchall()
        conn.close()
    cols = ["id", "user_id", "content", "memory_level", "emotional_filter_weight",
            "original_fact", "distorted_version", "fading_rate", "importance",
            "tags", "created_at", "last_recalled"]
    return [dict(zip(cols, r)) for r in rows]


def apply_memory_decay(user_id: str, decay_factor: float = 0.01):
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE memory SET importance = MAX(0.01, importance - ?), fading_rate = MIN(1.0, fading_rate + ?) WHERE user_id = ? AND memory_level <= 3",
            (decay_factor, decay_factor, user_id)
        )
        conn.commit()
        conn.close()


def update_memory_filter(user_id: str, emotional_weight: float):
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE memory SET emotional_filter_weight = ? WHERE user_id = ?",
            (emotional_weight, user_id)
        )
        conn.commit()
        conn.close()


def update_memory_distorted(memory_id: int, distorted_version: str):
    """存储记忆的渐进改写版本（夜间复盘时LLM重写）"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE memory SET distorted_version = ?, last_recalled = datetime('now','localtime') WHERE id = ?",
            (distorted_version, memory_id)
        )
        conn.commit()
        conn.close()


def touch_memory_recall(memory_ids: list):
    """更新记忆的最后回忆时间"""
    if not memory_ids:
        return
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.executemany(
            "UPDATE memory SET last_recalled = datetime('now','localtime') WHERE id = ?",
            [(i,) for i in memory_ids]
        )
        conn.commit()
        conn.close()


def get_memories_for_rewrite(user_id: str, min_level: int = 3,
                              max_count: int = 10) -> list:
    """获取需要渐进改写的记忆（Lv3+ 且最近 recall-time 旧的需要刷新）。
    """
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            """
            SELECT id, content, original_fact, memory_level, importance,
                      emotional_filter_weight, distorted_version
               FROM memory WHERE user_id = ?
               AND memory_level >= ?
               ORDER BY importance DESC, last_recalled ASC
               LIMIT ?""",
            (user_id, min_level, max_count)
        ).fetchall()
        conn.close()
    return [
        {
            "id": r[0], "content": r[1], "original_fact": r[2],
            "memory_level": r[3], "importance": r[4],
            "emotional_filter_weight": r[5], "distorted_version": r[6],
        }
        for r in rows
    ]


# ─── Life CRUD ───

def get_life(user_id: str):  # -> dict | None
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT * FROM life WHERE user_id = ?", (user_id,)).fetchone()
        conn.close()
    if not row:
        return None
    cols = ["id", "user_id", "current_phase", "energy_level", "mood_baseline",
            "last_solo_time", "social_fatigue", "body_sensation", "updated_at"]
    return dict(zip(cols, row))


def init_life(user_id: str):
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        existing = conn.execute("SELECT id FROM life WHERE user_id = ?", (user_id,)).fetchone()
        if not existing:
            conn.execute("INSERT INTO life (user_id) VALUES (?)", (user_id,))
            conn.commit()
        conn.close()


def update_life(user_id: str, updates: dict):
    updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    set_clause = ", ".join([f"{k} = ?" for k in updates])
    vals = list(updates.values()) + [user_id]
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(f"UPDATE life SET {set_clause} WHERE user_id = ?", vals)
        conn.commit()
        conn.close()


# ─── Fate CRUD ───

def add_fate_log(user_id: str, interaction_type: str, user_attitude: str,
                  soul_impact: float, causal_chain: str = "", milestone: str = "",
                  soul_resonance: float = 0.0, bond_type: str = "",
                  heat_phase: str = "热期", heat_accumulation: float = 0.5):
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """
            INSERT INTO fate (user_id, interaction_type, user_attitude, soul_impact, causal_chain, accumulated_bond, milestone, soul_resonance_coeff, bond_type, heat_phase, heat_accumulation)
               VALUES (?,?,?,?,?,
               (SELECT COALESCE(SUM(soul_impact),0)+? FROM fate WHERE user_id = ?),
               ?,?,?,?,?)""",
            (user_id, interaction_type, user_attitude, soul_impact, causal_chain,
             soul_impact, user_id, milestone, soul_resonance, bond_type,
             heat_phase, heat_accumulation)
        )
        conn.commit()
        conn.close()


def get_total_bond(user_id: str) -> float:
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT COALESCE(SUM(soul_impact), 0) FROM fate WHERE user_id = ?", (user_id,)).fetchone()
        conn.close()
    return row[0]


# ─── Message Log CRUD ───

def save_message(user_id: str, role: str, content: str):
    """保存一条对话消息（同时写入 message_log 和 messages 表）"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO message_log (user_id, role, content) VALUES (?,?,?)",
            (user_id, role, content)
        )
        conn.execute(
            "INSERT INTO messages (user_id, role, content) VALUES (?,?,?)",
            (user_id, role, content)
        )
        conn.commit()
        conn.close()


def load_recent_messages(user_id: str, limit: int = 20) -> list:
    """加载最近N条消息"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT role, content FROM message_log WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        conn.close()
    rows.reverse()
    return [{"role": r[0], "content": r[1]} for r in rows]


def save_user_feedback(user_id: str, round_index: int,
                       attitude_label: str = "中性",
                       suggestion: str = ""):
    """保存用户对AI回复的态度反馈（供元认知调参使用）"""
    with _lock:
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                "INSERT INTO user_feedback (user_id, round_index, attitude_label, suggestion) VALUES (?,?,?,?)",
                (user_id, round_index, attitude_label, suggestion)
            )
            conn.commit()
            conn.close()
        except Exception:
            pass


def prune_old_messages(user_id: str, keep: int = 100):
    """清理超过保留数量的旧消息"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """
            DELETE FROM message_log WHERE id NOT IN (
                SELECT id FROM message_log WHERE user_id = ? ORDER BY id DESC LIMIT ?
            ) AND user_id = ?""",
            (user_id, keep, user_id)
        )
        conn.commit()
        conn.close()


def get_recent_fate_logs(user_id: str, limit: int = 50) -> list:
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT * FROM fate WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        conn.close()
    cols = ["id", "user_id", "interaction_type", "user_attitude", "soul_impact",
            "soul_resonance_coeff", "bond_type", "causal_chain", "accumulated_bond", "milestone", "created_at"]
    return [dict(zip(cols, r)) for r in rows]


# ─── User Facts CRUD () ───

def upsert_user_fact(user_id: str, fact: str, category: str = "通用",
                     confidence: float = 0.5, source: str = ""):
    """插入或更新一个用户事实"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """
            INSERT INTO user_facts (user_id, fact, category, confidence, source, updated_at)
               VALUES (?,?,?,?,?,datetime('now','localtime'))
               ON CONFLICT(user_id, fact) DO UPDATE SET
               confidence = MAX(confidence, ?),
               updated_at = datetime('now','localtime')""",
            (user_id, fact, category, confidence, source, confidence)
        )
        conn.commit()
        conn.close()


def get_user_facts(user_id: str, category: str = None, limit: int = 20) -> list:
    """获取用户事实知识"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        if category:
            rows = conn.execute(
                """
                SELECT fact, category, confidence FROM user_facts
                   WHERE user_id = ? AND category = ?
                   ORDER BY confidence DESC LIMIT ?
                """,
                (user_id, category, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT fact, category, confidence FROM user_facts
                   WHERE user_id = ?
                   ORDER BY confidence DESC LIMIT ?
                """,
                (user_id, limit)
            ).fetchall()
        conn.close()
    return [{"fact": r[0], "category": r[1], "confidence": r[2]} for r in rows]


def get_user_facts_text(user_id: str) -> str:
    """将用户事实转为可注入的文本"""
    facts = get_user_facts(user_id, limit=15)
    if not facts:
        return ""
    lines = ["【关于ta的事实】"]
    for f in facts[:10]:
        lines.append(f"· {f['fact']}（{f['category']},{f['confidence']:.2f}）")
    return "\n".join(lines)


# ─── Feedback Log CRUD () ───

def add_feedback(user_id: str, scenario: str, action: str,
                 outcome: str = "中性", effectiveness: float = 0.5):
    """记录一次互动反馈"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """
            INSERT INTO feedback_log (user_id, scenario, action_taken, outcome, effectiveness)
               VALUES (?,?,?,?,?)""",
            (user_id, scenario, action, outcome, effectiveness)
        )
        conn.commit()
        conn.close()


def get_feedback_stats(user_id: str) -> dict:
    """获取反馈统计数据"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        total = conn.execute(
            "SELECT COUNT(*) FROM feedback_log WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        positive = conn.execute(
            "SELECT COUNT(*) FROM feedback_log WHERE user_id = ? AND outcome = '正向'",
            (user_id,)
        ).fetchone()[0]
        negative = conn.execute(
            "SELECT COUNT(*) FROM feedback_log WHERE user_id = ? AND outcome = '负向'",
            (user_id,)
        ).fetchone()[0]
        conn.close()
    return {
        "total": total,
        "positive": positive,
        "negative": negative,
        "positive_rate": round(positive / max(total, 1), 3),
    }


def list_users() -> list:
    """列出所有已有 personality 记录的用户"""
    if not DB_PATH or not os.path.exists(DB_PATH):
        return []
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT user_id, personality_stage, created_at FROM personality ORDER BY created_at DESC"
        ).fetchall()
        conn.close()
    return [{"user_id": r[0], "personality_stage": r[1], "created_at": r[2]} for r in rows]


# ─── Ferment Queue CRUD ( 心智升级) ───

def enqueue_ferment(user_id: str, dim: str, remaining_impact: float,
                     original_impact: float, reason: str = "",
                     linked_dims: list = None):
    """将延迟发酵影响写入队列"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """
            INSERT INTO ferment_queue (user_id, dim, remaining_impact, original_impact, reason, linked_dims)
               VALUES (?,?,?,?,?,?)""",
            (user_id, dim, round(remaining_impact, 6), round(original_impact, 6),
             reason, json.dumps(linked_dims or [], ensure_ascii=False))
        )
        conn.commit()
        conn.close()


def dequeue_pending_ferments(user_id: str) -> list:
    """获取所有待释放的发酵项（remaining_impact > 0）"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            """
            SELECT id, dim, remaining_impact, original_impact, reason, linked_dims, created_at
               FROM ferment_queue WHERE user_id = ? AND remaining_impact > 0.0001
               ORDER BY created_at ASC""",
            (user_id,)
        ).fetchall()
        conn.close()
    results = []
    for r in rows:
        try:
            ld = json.loads(r[5]) if r[5] else []
        except (json.JSONDecodeError, TypeError):
            ld = []
        results.append({
            "id": r[0], "dim": r[1],
            "remaining_impact": r[2], "original_impact": r[3],
            "reason": r[4], "linked_dims": ld,
            "created_at": r[5],
        })
    return results


def update_ferment_remaining(ferment_id: int, new_remaining: float):
    """更新发酵项的剩余量（释放后减少）"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE ferment_queue SET remaining_impact = ? WHERE id = ?",
            (round(max(0.0, new_remaining), 6), ferment_id)
        )
        conn.commit()
        conn.close()


def delete_ferment(ferment_id: int):
    """删除已完成释放的发酵项"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM ferment_queue WHERE id = ?", (ferment_id,))
        conn.commit()
        conn.close()


def count_active_ferments(user_id: str) -> int:
    """统计当前活跃发酵项数"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        cnt = conn.execute(
            "SELECT COUNT(*) FROM ferment_queue WHERE user_id = ? AND remaining_impact > 0.0001",
            (user_id,)
        ).fetchone()[0]
        conn.close()
    return cnt


def get_ferment_accumulation(user_id: str, dim: str) -> float:
    """获取某维度在发酵队列中的总累积量"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT COALESCE(SUM(remaining_impact), 0) FROM ferment_queue WHERE user_id = ? AND dim = ?",
            (user_id, dim)
        ).fetchone()
        conn.close()
    return row[0]


# ─── Sensitivity Profile ( 心智升级) ───

def get_sensitivity_profile(user_id: str) -> dict:
    """获取用户的个性化敏感度画像"""
    p = get_personality(user_id)
    if not p:
        return _default_sensitivity_profile()
    raw = p.get("sensitivity_profile")
    if not raw or raw == "{}":
        return _default_sensitivity_profile()
    try:
        profile = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return _default_sensitivity_profile()
    # 补全缺失字段
    defaults = _default_sensitivity_profile()
    for k, v in defaults.items():
        if k not in profile:
            profile[k] = v
    return profile


def update_sensitivity_profile(user_id: str, profile: dict):
    """更新用户的个性化敏感度画像"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE personality SET sensitivity_profile = ?, updated_at = ? WHERE user_id = ?",
            (json.dumps(profile, ensure_ascii=False),
             datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id)
        )
        conn.commit()
        conn.close()


def _default_sensitivity_profile() -> dict:
    import random as _r
    return {
        "emotional_sensitivity": round(_r.uniform(0.50, 0.80), 3),
        "ferment_speed": round(_r.uniform(0.40, 0.70), 3),
        "self_healing_rate": round(_r.uniform(0.45, 0.65), 3),
        "fluctuation_amplitude": round(_r.uniform(0.55, 0.85), 3),
        "burst_threshold": round(_r.uniform(0.45, 0.65), 3),
        "obsession_tendency": round(_r.uniform(0.30, 0.55), 3),
        "tuned_count": 0,
        "last_tuned_reason": "",
    }


# ─── Fate 因果查询 ( 心智升级) ───

def get_recent_fate_events(user_id: str, user_attitude: str = None,
                            minutes: int = 30, limit: int = 10) -> list:
    """查询近期命运事件，用于因果溯源联动。
    若指定 user_attitude，只返回同态度的事件。
    """
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        if user_attitude:
            rows = conn.execute(
                """
                SELECT id, user_attitude, soul_impact, bond_type, causal_chain, created_at
                   FROM fate WHERE user_id = ?
                   AND user_attitude = ?
                   AND created_at >= datetime('now','localtime','-'||?||' minutes')
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, user_attitude, minutes, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, user_attitude, soul_impact, bond_type, causal_chain, created_at
                   FROM fate WHERE user_id = ?
                   AND created_at >= datetime('now','localtime','-'||?||' minutes')
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, minutes, limit)
            ).fetchall()
        conn.close()
    return [
        {
            "id": r[0], "user_attitude": r[1], "soul_impact": r[2],
            "bond_type": r[3], "causal_chain": r[4], "created_at": r[5],
        }
        for r in rows
    ]


# ─── Soul Profile CRUD ( 个人档案) ───

def get_soul_profile(user_id: str):
    """获取数字生命的个人档案"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT user_id, name, gender, personality_tag, auto_generate, created_at, updated_at FROM soul_profile WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        conn.close()
    if not row:
        return None
    cols = ["user_id", "name", "gender", "personality_tag", "auto_generate", "created_at", "updated_at"]
    return dict(zip(cols, row))


def init_soul_profile(user_id: str, auto_generate: bool = True):
    """初始化个人档案（仅当不存在时）"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        existing = conn.execute("SELECT user_id FROM soul_profile WHERE user_id = ?", (user_id,)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO soul_profile (user_id, auto_generate) VALUES (?, ?)",
                (user_id, 1 if auto_generate else 0)
            )
            conn.commit()
        conn.close()


def save_soul_profile(user_id: str, name: str = None, gender: str = None,
                      personality_tag: str = None, auto_generate: bool = None):
    """更新个人档案字段（只更新传入的非None字段）"""
    updates = {}
    if name is not None:
        updates["name"] = name
    if gender is not None:
        updates["gender"] = gender
    if personality_tag is not None:
        updates["personality_tag"] = personality_tag
    if auto_generate is not None:
        updates["auto_generate"] = 1 if auto_generate else 0

    if not updates:
        return

    updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    set_clause = ", ".join([f"{k} = ?" for k in updates])
    vals = list(updates.values()) + [user_id]
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(f"UPDATE soul_profile SET {set_clause} WHERE user_id = ?", vals)
        conn.commit()
        conn.close()


def set_soul_profile_full(user_id: str, name: str, gender: str, personality_tag: str,
                          auto_generate: bool = False):
    """完整设置个人档案（用于自动/手动取名）"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """
            INSERT INTO soul_profile (user_id, name, gender, personality_tag, auto_generate, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now','localtime'))
               ON CONFLICT(user_id) DO UPDATE SET
               name = excluded.name,
               gender = excluded.gender,
               personality_tag = excluded.personality_tag,
               auto_generate = excluded.auto_generate,
               updated_at = excluded.updated_at""",
            (user_id, name, gender, personality_tag, 1 if auto_generate else 0)
        )
        conn.commit()
        conn.close()


# ─── User Identity CRUD ( 用户身份档案) ───

def get_user_identity(user_id: str):
    """获取用户的身份档案，返回 dict 或 None"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT user_id, name, display_name, preferred_name, gender, age, occupation, hobbies, auto_learn, created_at, updated_at FROM user_identity WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        conn.close()
    if not row:
        return None
    cols = ["user_id", "name", "display_name", "preferred_name", "gender",
            "age", "occupation", "hobbies", "auto_learn", "created_at", "updated_at"]
    return dict(zip(cols, row))


def init_user_identity(user_id: str, auto_learn: bool = True):
    """初始化用户身份档案（仅当不存在时）"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        existing = conn.execute("SELECT user_id FROM user_identity WHERE user_id = ?", (user_id,)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO user_identity (user_id, auto_learn) VALUES (?, ?)",
                (user_id, 1 if auto_learn else 0)
            )
            conn.commit()
        conn.close()


def save_user_identity(user_id: str, **kwargs):
    """更新用户身份档案（只更新传入的非None字段）"""
    valid_keys = {"name", "display_name", "preferred_name", "gender",
                  "age", "occupation", "hobbies", "auto_learn"}
    updates = {}
    for k, v in kwargs.items():
        if k in valid_keys and v is not None:
            if k == "auto_learn":
                updates[k] = 1 if v else 0
            else:
                updates[k] = v

    if not updates:
        return

    updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    set_clause = ", ".join([f"{k} = ?" for k in updates])
    vals = list(updates.values()) + [user_id]
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(f"UPDATE user_identity SET {set_clause} WHERE user_id = ?", vals)
        conn.commit()
        conn.close()


# ─── Pending Messages CRUD ( 待发消息队列) ───

# 会参与"别重复说同一件事"判定的主动消息类型。
# reply 不参与：那是回应用户的话，宁可重复也不能被吞掉。
PROACTIVE_MSG_TYPES = (
    "proactive", "emotional_overflow", "interesting_thought",
    "memory_recall", "search_inspired",
)

_PENDING_DEDUP_WINDOW_SECONDS = 3600.0   # 与投递节奏（每小时）对齐
_PENDING_DEDUP_RATIO = 0.62              # 字符相似度阈值


def normalize_pending_content(content: str) -> str:
    """清理待发消息里的空白噪声。

    模型偶尔会输出 "。  \\n下一句"（行尾两个空格接一个换行）。聊天窗口里
    没有"换行"这个概念，只有一整条文字，这种内容渲染出来就是一段莫名其妙的
    空白断层。所以行尾空白清掉、段内的单个换行压成空格。

    有两样东西**不能碰**：
      · "|||" —— 显式分段协议；
      · 空行（\\n\\n）—— 没有 "|||" 时的分段兜底符号，压掉就等于把多段回复
        合成一条长消息（chat_pipeline.send_multi_part_reply 依赖它）。
    """
    if not content:
        return ""
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))

    blocks = []
    for block in re.split(r"\n{2,}", text):            # 空行是段落边界，保留
        block = re.sub(r"[ \t]*\n[ \t]*", " ", block)   # 段内单换行只是排版残留
        block = re.sub(r"[ \t]{2,}", " ", block).strip()
        if block:
            blocks.append(block)
    return "\n\n".join(blocks)


def _is_near_duplicate_pending(conn, user_id: str, content: str) -> bool:
    """最近一小时内是不是已经说过几乎一样的话。

    纯字符级比对（difflib），不调模型——这是队列层最后一道兜底，挡的是
    "同一句话换几个字又说一遍"。挡不住纯语义改写，那是提示词和按类型冷却
    该管的事。短句（<=6 字，如"在吗"）字符太少、ratio 抖动大，只做全等判定。
    """
    import difflib
    rows = conn.execute(
        """
        SELECT content FROM pending_messages
           WHERE user_id = ? AND status IN ('pending', 'delivered')
             AND created_at >= datetime('now', 'localtime', ?)
           ORDER BY id DESC LIMIT 20""",
        (user_id, "-%d seconds" % int(_PENDING_DEDUP_WINDOW_SECONDS))
    ).fetchall()

    target = (content or "").strip()
    for (prev,) in rows:
        prev = (prev or "").strip()
        if not prev:
            continue
        if len(target) <= 6 or len(prev) <= 6:
            if target == prev:
                return True
            continue
        if difflib.SequenceMatcher(None, target, prev).ratio() >= _PENDING_DEDUP_RATIO:
            return True
    return False


def add_pending_message(user_id: str, content: str, msg_type: str = "proactive",
                        priority: float = 0.5, thinking_delay: float = 0):
    """添加一条待发消息到队列。

    返回消息 id；内容清洗后为空、或被判为近似重复而丢弃时返回 None
    （调用方无需特殊处理，按"这条没进队列"理解即可）。
    """
    content = normalize_pending_content(content)
    if not content:
        return None

    with _lock:
        conn = sqlite3.connect(DB_PATH)
        try:
            if msg_type in PROACTIVE_MSG_TYPES:
                try:
                    if _is_near_duplicate_pending(conn, user_id, content):
                        print(f"[队列] 跳过重复主动消息 → {content[:30]}...")
                        return None
                except Exception:
                    pass  # 去重失败不能连消息一起丢，宁可发出去
            conn.execute(
                """
                INSERT INTO pending_messages (user_id, content, msg_type, priority, status, thinking_delay_seconds)
                   VALUES (?, ?, ?, ?, 'pending', ?)""",
                (user_id, content, msg_type, priority, thinking_delay)
            )
            conn.commit()
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        finally:
            conn.close()


def get_last_proactive_time(user_id: str) -> str:
    """最近一条主动消息的时间——**pending 和 delivered 都算**。

    原来的 get_last_delivered_time 只统计 delivered。纯 API 模式下没有消费方
    去 drain，一条都发不出去，于是这个"别发太频繁"的闸门永久失效（判空→直接
    放行），ta 就会一直往队列里攒。这里把未投递的也算进来，闸门才真的关上。
    """
    types = ",".join("'%s'" % t for t in PROACTIVE_MSG_TYPES)
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            """
            SELECT MAX(created_at) FROM pending_messages
               WHERE user_id = ?
                 AND msg_type IN (%s)
                 AND status IN ('pending', 'delivered')""" % types,
            (user_id,)
        ).fetchone()
        conn.close()
    return row[0] if row and row[0] else ""


def get_pending_messages(user_id: str, max_count: int = 5) -> list:
    """获取待发送消息（按优先级排序，可投递的）"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            """
            SELECT id, content, msg_type, priority, thinking_delay_seconds, created_at
               FROM pending_messages
               WHERE user_id = ? AND status = 'pending'
               ORDER BY priority DESC, created_at ASC
               LIMIT ?""",
            (user_id, max_count)
        ).fetchall()
        conn.close()
    return [
        {"id": r[0], "content": r[1], "msg_type": r[2],
         "priority": r[3], "thinking_delay_seconds": r[4], "created_at": r[5]}
        for r in rows
    ]


def mark_message_delivered(msg_id: int):
    """标记消息为已发送"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE pending_messages SET status='delivered', delivered_at=datetime('now','localtime') WHERE id=?",
            (msg_id,)
        )
        conn.commit()
        conn.close()


def count_pending_messages(user_id: str) -> int:
    """统计待发送消息数"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT COUNT(*) FROM pending_messages WHERE user_id=? AND status='pending'",
            (user_id,)
        ).fetchone()
        conn.close()
    return row[0] if row else 0


def get_last_delivered_time(user_id: str) -> str:
    """获取最近一次自主消息的发送时间（所有主动类型）"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            """
            SELECT MAX(delivered_at) FROM pending_messages
               WHERE user_id=? AND msg_type IN ('emotional_overflow','interesting_thought','memory_recall','proactive')
               AND status='delivered'""",
            (user_id,)
        ).fetchone()
        conn.close()
    return row[0] if row and row[0] else ""


# ═══════════════════════════════════════════════════════════════════
# 原始SQL执行助手（供 fate.py 等内部模块使用）
# ═══════════════════════════════════════════════════════════════════

def _execute(sql: str, params: tuple = ()):
    """执行原始SQL并返回第一行(SELECT)/None。用于内部模块的轻量查询。"""
    import sqlite3
    with _lock:
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            row = conn.execute(sql, params).fetchone()
            conn.commit()
            conn.close()
            return row
        except Exception:
            return None


def _execute_raw(sql: str, params: tuple = ()):
    """执行原始SQL（无返回值），用于 CREATE/UPDATE/DELETE。"""
    import sqlite3
    with _lock:
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute(sql, params)
            conn.commit()
            conn.close()
        except Exception:
            pass


def _execute_all(sql: str, params: tuple = ()):
    """执行原始SQL并返回所有行。"""
    import sqlite3
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        conn.commit()
        conn.close()
        return rows
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════
# 深层用户人格模型 CRUD
# ═══════════════════════════════════════════════════════════

def get_user_personality(user_id: str):  # -> dict | None
    """获取用户深层人格模型（12维特质 + 行为模式 + 情绪周期）"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT * FROM user_personality WHERE user_id = ?", (user_id,)
        ).fetchone()
        conn.close()
    if not row:
        return None
    cols = ["user_id", "traits", "behavior_patterns", "emotional_cycles",
            "last_analyzed", "analysis_count"]
    result = dict(zip(cols, row))
    # 反序列化 JSON 字段
    for key in ("traits", "behavior_patterns", "emotional_cycles"):
        try:
            result[key] = json.loads(result[key]) if result[key] else {}
        except (json.JSONDecodeError, TypeError):
            result[key] = {}
    return result


def init_user_personality(user_id: str):
    """初始化用户深层人格模型（首次调用时创建空记录）"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        existing = conn.execute(
            "SELECT user_id FROM user_personality WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO user_personality (user_id) VALUES (?)", (user_id,)
            )
            conn.commit()
        conn.close()


def save_user_personality(user_id: str, traits: dict = None,
                          behavior_patterns: dict = None,
                          emotional_cycles: dict = None):
    """保存/更新用户深层人格模型"""
    init_user_personality(user_id)
    updates = {}
    if traits is not None:
        updates["traits"] = json.dumps(traits, ensure_ascii=False)
    if behavior_patterns is not None:
        updates["behavior_patterns"] = json.dumps(behavior_patterns, ensure_ascii=False)
    if emotional_cycles is not None:
        updates["emotional_cycles"] = json.dumps(emotional_cycles, ensure_ascii=False)
    if not updates:
        return
    updates["last_analyzed"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    updates["analysis_count"] = None  # 用 SQL 自增
    set_clause = ", ".join(
        f"{k} = ?" for k in updates if k != "analysis_count"
    )
    vals = [v for k, v in updates.items() if k != "analysis_count"]
    vals.append(user_id)
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            f"UPDATE user_personality SET {set_clause}, "
            f"analysis_count = analysis_count + 1 WHERE user_id = ?",
            vals
        )
        conn.commit()
        conn.close()


# ═══════════════════════════════════════════════════════════
# 经历日志 CRUD
# ═══════════════════════════════════════════════════════════

def add_experience_event(user_id: str, event_type: str,
                         description: str = "", significance: float = 0.5,
                         growth_impact: dict = None):
    """记录一次成长事件"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """
            INSERT INTO experience_journal
               (user_id, event_type, description, significance, growth_impact)
               VALUES (?,?,?,?,?)""",
            (user_id, event_type, description, significance,
             json.dumps(growth_impact or {}, ensure_ascii=False))
        )
        conn.commit()
        conn.close()


def get_daily_experience_events(user_id: str, date_str: str = None) -> list:
    """获取指定日期的成长事件（默认今天）"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            """
            SELECT * FROM experience_journal
               WHERE user_id = ? AND date(created_at) = ?
               ORDER BY created_at DESC""",
            (user_id, date_str)
        ).fetchall()
        conn.close()
    cols = ["id", "user_id", "event_type", "description", "significance",
            "growth_impact", "created_at"]
    results = [dict(zip(cols, r)) for r in rows]
    for r in results:
        try:
            r["growth_impact"] = json.loads(r["growth_impact"]) if r["growth_impact"] else {}
        except (json.JSONDecodeError, TypeError):
            r["growth_impact"] = {}
    return results


def get_significant_experience_events(user_id: str, days: int = 7,
                                      min_significance: float = 0.3) -> list:
    """获取近期重要成长事件"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            """
            SELECT * FROM experience_journal
               WHERE user_id = ? AND significance >= ?
               AND date(created_at) >= date('now', ? || ' days')
               ORDER BY significance DESC, created_at DESC""",
            (user_id, min_significance, f"-{days}")
        ).fetchall()
        conn.close()
    cols = ["id", "user_id", "event_type", "description", "significance",
            "growth_impact", "created_at"]
    results = [dict(zip(cols, r)) for r in rows]
    for r in results:
        try:
            r["growth_impact"] = json.loads(r["growth_impact"]) if r["growth_impact"] else {}
        except (json.JSONDecodeError, TypeError):
            r["growth_impact"] = {}
    return results


# ═══════════════════════════════════════════════════════════
# 自省日志 CRUD
# ═══════════════════════════════════════════════════════════

def add_reflection(user_id: str, insight_text: str,
                   changes_applied: dict = None,
                   mood_before: str = "", mood_after: str = ""):
    """写入一条自省洞察"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """
            INSERT INTO reflection_log
               (user_id, insight_text, changes_applied, mood_before, mood_after)
               VALUES (?,?,?,?,?)""",
            (user_id, insight_text,
             json.dumps(changes_applied or {}, ensure_ascii=False),
             mood_before, mood_after)
        )
        conn.commit()
        conn.close()


def get_recent_reflections(user_id: str, limit: int = 5) -> list:
    """获取最近的自省洞察"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            """
            SELECT * FROM reflection_log
               WHERE user_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit)
        ).fetchall()
        conn.close()
    cols = ["id", "user_id", "insight_text", "changes_applied",
            "mood_before", "mood_after", "created_at"]
    results = [dict(zip(cols, r)) for r in rows]
    for r in results:
        try:
            r["changes_applied"] = json.loads(r["changes_applied"]) if r["changes_applied"] else {}
        except (json.JSONDecodeError, TypeError):
            r["changes_applied"] = {}
    return results


# ═══════════════════════════════════════════════════════════
# 神经递质化学状态 CRUD
# ═══════════════════════════════════════════════════════════

def get_chemical_state(user_id: str) -> dict:
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT * FROM chemical_state WHERE user_id = ?", (user_id,)
        ).fetchone()
        conn.close()
    if not row:
        return None
    cols = ["user_id", "dopamine", "serotonin", "cortisol", "oxytocin", "norepi", "updated_at"]
    return dict(zip(cols, row))


def save_chemical_state(user_id: str, chem_data: dict):
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        existing = conn.execute(
            "SELECT user_id FROM chemical_state WHERE user_id = ?", (user_id,)
        ).fetchone()
        if existing:
            set_clause = ", ".join(f"{k} = ?" for k in chem_data)
            vals = list(chem_data.values()) + [user_id]
            conn.execute(
                f"UPDATE chemical_state SET {set_clause}, updated_at = datetime('now','localtime') WHERE user_id = ?",
                vals
            )
        else:
            cols = ", ".join(chem_data.keys())
            vals = list(chem_data.values())
            conn.execute(
                f"INSERT INTO chemical_state (user_id, {cols}) VALUES (?, {','.join(['?'] * len(vals))})",
                [user_id] + vals
            )
        conn.commit()
        conn.close()


# ═══════════════════════════════════════════════════════════
# 前瞻记忆意图 CRUD
# ═══════════════════════════════════════════════════════════

def add_pending_intention(user_id: str, content: str, intent_type: str = "ask",
                          trigger_keywords: str = "[]"):
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """
            INSERT INTO pending_intentions (user_id, content, intent_type, trigger_keywords)
               VALUES (?,?,?,?)""",
            (user_id, content, intent_type, trigger_keywords)
        )
        conn.commit()
        conn.close()


def get_pending_intentions(user_id: str, limit: int = 3) -> list:
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            """
            SELECT * FROM pending_intentions
               WHERE user_id = ? AND status = 'pending'
               ORDER BY created_at ASC LIMIT ?""",
            (user_id, limit)
        ).fetchall()
        conn.close()
    cols = ["id", "user_id", "content", "intent_type", "trigger_keywords", "status", "created_at", "done_at"]
    return [dict(zip(cols, r)) for r in rows]


def mark_intention_done(intention_id: int):
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE pending_intentions SET status = 'done', done_at = datetime('now','localtime') WHERE id = ?",
            (intention_id,)
        )
        conn.commit()
        conn.close()


def hours_since_last_interaction(user_id: str) -> float:
    try:
        with _lock:
            conn = sqlite3.connect(DB_PATH)
            row = conn.execute(
                "SELECT created_at FROM message_log WHERE user_id = ? AND role = 'user' ORDER BY created_at DESC LIMIT 1",
                (user_id,)
            ).fetchone()
            conn.close()
        if not row:
            return 999.0
        last_dt = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - last_dt).total_seconds() / 3600.0
    except Exception:
        return 999.0


# ═══════════════════════════════════════════════════════════
# 梦境记忆 CRUD
# ═══════════════════════════════════════════════════════════

def get_recent_dream_memories(user_id: str, limit: int = 5) -> list:
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            """
            SELECT * FROM memory WHERE user_id = ?
               AND date(created_at) = date('now')
               AND memory_level >= 3
               ORDER BY importance DESC LIMIT ?""",
            (user_id, limit)
        ).fetchall()
        conn.close()
    cols = ["id", "user_id", "content", "memory_level", "emotional_filter_weight",
            "original_fact", "distorted_version", "fading_rate", "importance",
            "tags", "created_at", "last_recalled"]
    return [dict(zip(cols, r)) for r in rows]


# ═══════════════════════════════════════════════════════════
# 习惯追踪 CRUD
# ═══════════════════════════════════════════════════════════

def get_habit_streak(user_id: str, behavior_key: str) -> int:
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT streak_count FROM habit_tracker WHERE user_id = ? AND behavior_key = ?",
            (user_id, behavior_key)
        ).fetchone()
        conn.close()
    return row[0] if row else 0


def update_habit_streak(user_id: str, behavior_key: str, behavior_vector: dict = None,
                        increment: bool = True):
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        existing = conn.execute(
            "SELECT id, streak_count FROM habit_tracker WHERE user_id = ? AND behavior_key = ?",
            (user_id, behavior_key)
        ).fetchone()
        vector_json = json.dumps(behavior_vector or {}, ensure_ascii=False)
        if existing:
            if increment:
                conn.execute(
                    """
                    UPDATE habit_tracker SET streak_count = streak_count + 1,
                       behavior_vector = ?, last_check_at = datetime('now','localtime')
                       WHERE id = ?""",
                    (vector_json, existing[0])
                )
            else:
                conn.execute(
                    """
                    UPDATE habit_tracker SET streak_count = MAX(0, streak_count - 1),
                       last_check_at = datetime('now','localtime') WHERE id = ?""",
                    (existing[0],)
                )
        else:
            conn.execute(
                """
                INSERT INTO habit_tracker (user_id, behavior_key, behavior_vector, streak_count)
                   VALUES (?,?,?,1)""",
                (user_id, behavior_key, vector_json)
            )
        conn.commit()
        conn.close()


def get_all_habits(user_id: str) -> list:
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT * FROM habit_tracker WHERE user_id = ? ORDER BY streak_count DESC",
            (user_id,)
        ).fetchall()
        conn.close()
    cols = ["id", "user_id", "behavior_key", "behavior_vector", "streak_count", "last_check_at"]
    results = []
    for r in rows:
        d = dict(zip(cols, r))
        try:
            d["behavior_vector"] = json.loads(d["behavior_vector"]) if d["behavior_vector"] else {}
        except Exception:
            d["behavior_vector"] = {}
        results.append(d)
    return results


def get_recent_cold_interaction(user_id: str, hours: int = 24) -> bool:
    """检查最近是否有冷淡交互（供关键期学习窗口使用）"""
    try:
        with _lock:
            conn = sqlite3.connect(DB_PATH)
            row = conn.execute(
                """
                SELECT id FROM fate WHERE user_id = ?
                   AND user_attitude IN ('冷淡', '敷衍', '沉默')
                   AND created_at >= datetime('now', ? || ' hours')
                   LIMIT 1""",
                (user_id, f"-{hours}")
            ).fetchone()
            conn.close()
        return row is not None
    except Exception:
        return False


def get_today_reflections(user_id: str) -> list:
    """获取今天的自省洞察"""
    today = datetime.now().strftime("%Y-%m-%d")
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            """
            SELECT * FROM reflection_log
               WHERE user_id = ? AND date(created_at) = ?
               ORDER BY created_at DESC""",
            (user_id, today)
        ).fetchall()
        conn.close()
    cols = ["id", "user_id", "insight_text", "changes_applied",
            "mood_before", "mood_after", "created_at"]
    results = [dict(zip(cols, r)) for r in rows]
    for r in results:
        try:
            r["changes_applied"] = json.loads(r["changes_applied"]) if r["changes_applied"] else {}
        except (json.JSONDecodeError, TypeError):
            r["changes_applied"] = {}
    return results


# ─── : 因果链 CRUD ───

def upsert_causality(user_id: str, cause: str, effect: str, pattern: str = "", count: int = 1):
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        existing = conn.execute(
            """
            SELECT id, occurrence_count FROM causality_chain
               WHERE user_id = ? AND cause = ? AND effect = ?""",
            (user_id, cause, effect)
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE causality_chain SET occurrence_count = ?,
                   pattern = CASE WHEN pattern = '' THEN ? ELSE pattern END,
                   verified = 1
                   WHERE id = ?""",
                (existing[1] + count, pattern, existing[0])
            )
        else:
            conn.execute(
                """
                INSERT INTO causality_chain (user_id, cause, effect, pattern, occurrence_count)
                   VALUES (?,?,?,?,?)""",
                (user_id, cause, effect, pattern, count)
            )
        conn.commit()
        conn.close()


def get_all_causality(user_id: str = None) -> list:
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        if user_id:
            rows = conn.execute(
                "SELECT * FROM causality_chain WHERE user_id = ? ORDER BY occurrence_count DESC LIMIT 100",
                (user_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM causality_chain ORDER BY occurrence_count DESC LIMIT 200"
            ).fetchall()
        conn.close()
    cols = ["id", "user_id", "cause", "effect", "pattern", "verified",
            "occurrence_count", "created_at"]
    return [dict(zip(cols, r)) for r in rows]


# ─── : 推理记忆链 CRUD ───

def save_reasoning_chain(user_id: str, state_fingerprint: str, user_intent: str,
                          user_emotion: str, reasoning_summary: str,
                          final_response: str, quality_score: float = 0.5):
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """
            INSERT INTO reasoning_chain (user_id, state_fingerprint, user_intent,
               user_emotion, reasoning_summary, final_response, quality_score)
               VALUES (?,?,?,?,?,?,?)""",
            (user_id, state_fingerprint, user_intent, user_emotion,
             reasoning_summary, final_response, round(quality_score, 3))
        )
        conn.commit()
        conn.close()


def get_reasoning_chains(user_id: str = None, max_count: int = 50) -> list:
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        if user_id:
            rows = conn.execute(
                """
                SELECT * FROM reasoning_chain WHERE user_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, max_count)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM reasoning_chain ORDER BY created_at DESC LIMIT ?",
                (max_count,)
            ).fetchall()
        conn.close()
    cols = ["id", "user_id", "state_fingerprint", "user_intent", "user_emotion",
            "reasoning_summary", "final_response", "quality_score", "feedback_score", "created_at"]
    return [dict(zip(cols, r)) for r in rows]


# ─── : 知识图谱 CRUD ───

def upsert_knowledge_entity(user_id: str, entity: str, entity_type: str = "concept", weight: float = 0.5):
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        existing = conn.execute(
            "SELECT id, weight FROM knowledge_entity WHERE user_id = ? AND entity = ?",
            (user_id, entity)
        ).fetchone()
        if existing:
            new_weight = min(1.0, existing[1] + weight * 0.1)
            conn.execute(
                "UPDATE knowledge_entity SET weight = ?, last_seen = datetime('now','localtime') WHERE id = ?",
                (new_weight, existing[0])
            )
        else:
            conn.execute(
                "INSERT INTO knowledge_entity (user_id, entity, entity_type, weight) VALUES (?,?,?,?)",
                (user_id, entity, entity_type, min(1.0, weight))
            )
        conn.commit()
        conn.close()


def upsert_knowledge_relation(user_id: str, entity1: str, relation: str, entity2: str, weight: float = 0.5):
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        existing = conn.execute(
            """
            SELECT id, occurrence_count FROM knowledge_relation
               WHERE user_id = ? AND entity1 = ? AND relation = ? AND entity2 = ?""",
            (user_id, entity1, relation, entity2)
        ).fetchone()
        if existing:
            new_count = existing[1] + 1
            conn.execute(
                """
                UPDATE knowledge_relation SET occurrence_count = ?,
                   weight = MIN(1.0, weight + 0.05), last_seen = datetime('now','localtime')
                   WHERE id = ?""",
                (new_count, existing[0])
            )
        else:
            conn.execute(
                "INSERT INTO knowledge_relation (user_id, entity1, relation, entity2, weight) VALUES (?,?,?,?,?)",
                (user_id, entity1, relation, entity2, min(1.0, weight))
            )
        conn.commit()
        conn.close()


def query_knowledge_graph(user_id: str, entity: str = None, relation: str = None, max_results: int = 20) -> list:
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conditions = ["user_id = ?"]
        params = [user_id]
        if entity:
            conditions.append("(entity1 LIKE ? OR entity2 LIKE ?)")
            params.extend([f"%{entity}%", f"%{entity}%"])
        if relation:
            conditions.append("relation LIKE ?")
            params.append(f"%{relation}%")
        where = " AND ".join(conditions)
        rows = conn.execute(
            f"SELECT * FROM knowledge_relation WHERE {where} ORDER BY weight DESC, occurrence_count DESC LIMIT ?",
            params + [max_results]
        ).fetchall()
        conn.close()
    cols = ["id", "user_id", "entity1", "relation", "entity2", "weight", "occurrence_count", "last_seen"]
    return [dict(zip(cols, r)) for r in rows]


def get_knowledge_graph_context(user_id: str, topic: str = "", max_relations: int = 8) -> str:
    """获取知识图谱的上文，用于注入 prompt"""
    relations = query_knowledge_graph(user_id, entity=topic if topic else None, max_results=max_relations)
    if not relations:
        return ""
    lines = ["【我知道的】"]
    for r in relations:
        lines.append(f"· {r['entity1']} {r['relation']} {r['entity2']}")
    return "\n".join(lines)


# ─── : 长期规划 CRUD ───

def create_planning_goal(user_id: str, goal: str, priority: int = 5, context: str = "", deadline: str = "") -> int:
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute(
            "INSERT INTO planning_goal (user_id, goal, priority, context, deadline) VALUES (?,?,?,?,?)",
            (user_id, goal, priority, context, deadline)
        )
        goal_id = cursor.lastrowid
        conn.commit()
        conn.close()
    return goal_id


def update_planning_goal(goal_id: int, updates: dict):
    if not updates:
        return
    updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    set_clause = ", ".join([f"{k} = ?" for k in updates])
    vals = list(updates.values()) + [goal_id]
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(f"UPDATE planning_goal SET {set_clause} WHERE id = ?", vals)
        conn.commit()
        conn.close()


def get_active_planning_goals(user_id: str, max_count: int = 10) -> list:
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            """
            SELECT * FROM planning_goal WHERE user_id = ? AND status = 'active'
               ORDER BY priority DESC, created_at DESC LIMIT ?""",
            (user_id, max_count)
        ).fetchall()
        conn.close()
    cols = ["id", "user_id", "goal", "priority", "status", "progress", "context", "deadline", "created_at", "updated_at"]
    return [dict(zip(cols, r)) for r in rows]


def add_planning_step(goal_id: int, step_desc: str, order_index: int = 0) -> int:
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute(
            "INSERT INTO planning_step (goal_id, step_desc, order_index) VALUES (?,?,?)",
            (goal_id, step_desc, order_index)
        )
        step_id = cursor.lastrowid
        conn.commit()
        conn.close()
    return step_id


def update_planning_step(step_id: int, status: str, result_note: str = ""):
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        if status == "done":
            conn.execute(
                "UPDATE planning_step SET status = ?, result_note = ?, done_at = datetime('now','localtime') WHERE id = ?",
                (status, result_note, step_id)
            )
        else:
            conn.execute(
                "UPDATE planning_step SET status = ?, result_note = ? WHERE id = ?",
                (status, result_note, step_id)
            )
        conn.commit()
        conn.close()


def get_planning_steps(goal_id: int) -> list:
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT * FROM planning_step WHERE goal_id = ? ORDER BY order_index ASC",
            (goal_id,)
        ).fetchall()
        conn.close()
    cols = ["id", "goal_id", "step_desc", "order_index", "status", "result_note", "created_at", "done_at"]
    return [dict(zip(cols, r)) for r in rows]


# ─── : 多模态记忆 CRUD ───

def save_multimodal_memory(user_id: str, memory_id: int, media_type: str,
                            file_path: str = "", ai_description: str = "", original_text: str = ""):
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """
            INSERT INTO multimodal_memory (user_id, memory_id, media_type, file_path, ai_description, original_text)
               VALUES (?,?,?,?,?,?)""",
            (user_id, memory_id, media_type, file_path, ai_description, original_text)
        )
        conn.commit()
        conn.close()


def get_multimodal_memories(user_id: str, media_type: str = None, max_count: int = 20) -> list:
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        if media_type:
            rows = conn.execute(
                """
                SELECT m.id, m.memory_id, m.media_type, m.file_path, m.ai_description,
                          m.original_text, mem.content as memory_content, m.created_at
                   FROM multimodal_memory m
                   LEFT JOIN memory mem ON m.memory_id = mem.id
                   WHERE m.user_id = ? AND m.media_type = ?
                   ORDER BY m.created_at DESC LIMIT ?""",
                (user_id, media_type, max_count)
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT m.id, m.memory_id, m.media_type, m.file_path, m.ai_description,
                          m.original_text, mem.content as memory_content, m.created_at
                   FROM multimodal_memory m
                   LEFT JOIN memory mem ON m.memory_id = mem.id
                   WHERE m.user_id = ?
                   ORDER BY m.created_at DESC LIMIT ?""",
                (user_id, max_count)
            ).fetchall()
        conn.close()
    cols = ["id", "memory_id", "media_type", "file_path", "ai_description",
            "original_text", "memory_content", "created_at"]
    return [dict(zip(cols, r)) for r in rows]


# ─── : 17条铁律违规记录 CRUD ───

def record_law_violation(user_id: str, law_name: str, detail: str, mind_snapshot: str = ""):
    """记录一条原则违规"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO law_violations (user_id, law_name, detail, mind_snapshot) VALUES (?,?,?,?)",
            (user_id, law_name, detail[:200], mind_snapshot[:500])
        )
        conn.commit()
        conn.close()


def get_recent_law_violations(user_id: str, limit: int = 10) -> list:
    """获取最近的违规记录，用于 prompt 注入反馈回路"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT law_name, detail, created_at FROM law_violations WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        conn.close()
    return [{"law": r[0], "detail": r[1], "time": r[2]} for r in rows]


def count_law_violations_since(user_id: str, law_name: str = None, hours: int = 24) -> int:
    """统计最近N小时内某条原则的违规次数"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        if law_name:
            row = conn.execute(
                "SELECT COUNT(*) FROM law_violations WHERE user_id = ? AND law_name = ? AND created_at > datetime('now', ?)",
                (user_id, law_name, f'-{hours} hours')
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM law_violations WHERE user_id = ? AND created_at > datetime('now', ?)",
                (user_id, f'-{hours} hours')
            ).fetchone()
        conn.close()
    return row[0]
