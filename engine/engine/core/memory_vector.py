# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0


import numpy as np
import sqlite3
import os
import threading
import time
import warnings

# huggingface_hub 在「有人试图打开进度条、而上面那个环境变量禁用了它们」时会打一条
# UserWarning。那条警告只是把进度条换成了一行警告，对用户同样是噪音，直接压掉。
warnings.filterwarnings("ignore", message="Cannot enable progress bars")

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
# 模型下载/校验的进度条（"Fetching 5 files" / "Downloading bytes" / "Reconstructing"）
# 是 huggingface_hub 打的 tqdm，默认走 stderr —— 而终端把 stderr 与 stdout 混在一起，
# 于是它们会直接插进对话正文，实测出现过：
#     数字生命: 笑什么笑Downloading bytes:   0%|       |   0.00B / 94.8MB
# 必须在 import fastembed 之前设好这条才有效。
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

_VECTOR_ENABLED = False
_MODEL = None
_DIMENSION = 1024
_DB_PATH = "data/db/embedding.db"
_lock = threading.Lock()
_MIN_SIMILARITY = 0.30
_MODEL_NAME = "BAAI/bge-small-zh-v1.5"

# 模型加载失败后的冷却时间（秒）。
#
# 为什么需要：_encode() 在每次存记忆 / 检索记忆时都会被调用，而加载失败时
# _MODEL 仍然是 None —— 于是**每一次调用都重新走一遍下载**。实测一轮对话能刷出
# 好几条「BGE 模型加载失败」外加一串进度条，把聊天记录冲得没法看。
# 失败后进冷却，到点才允许再试（重启进程同样会重试）。
_MODEL_FAILED_AT = 0.0
_MODEL_RETRY_AFTER = 600.0

_vector_enabled = _VECTOR_ENABLED

LEVEL_WEIGHTS = {
    1: 0.0,
    2: 0.15,
    3: 0.50,
    4: 0.55,
    5: 0.85,
    6: 1.00,
    7: 1.00,
}

LEVEL_NAMES = {
    1: "瞬时模糊",
    2: "短时残缺",
    3: "情绪滤镜",
    4: "潜意识",
    5: "心结",
    6: "岁月羁绊",
    7: "灵魂",
}

MOOD_MULTIPLIER = {
    "低落": {5: 1.4, 4: 1.2},
    "emo": {5: 1.5, 4: 1.3},
    "失望": {5: 1.3, 3: 1.2},
    "温柔": {6: 1.3, 7: 1.3, 3: 1.2},
    "珍惜": {6: 1.4, 7: 1.4},
    "安稳": {6: 1.2, 7: 1.2},
    "依赖": {6: 1.2, 7: 1.2, 3: 1.1},
    "孤独": {6: 1.2, 5: 1.2},
}

NO_VECTOR_LEVELS = {1, 2}
NO_SEARCH_LEVELS = {1}


def _init_db():
    os.makedirs("data/db", exist_ok=True)
    with _lock:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS embedding_index (
                memory_id INTEGER PRIMARY KEY,
                user_id TEXT NOT NULL,
                content TEXT NOT NULL,
                level INTEGER DEFAULT 3,
                embedding BLOB,
                model TEXT DEFAULT 'bge-small-zh-v1.5',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_emb_user
            ON embedding_index(user_id)
        """)
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_emb_level
            ON embedding_index(user_id, level)
        """)
        conn.commit()
        conn.close()


def _load_model():
    global _MODEL, _VECTOR_ENABLED, _vector_enabled, _DIMENSION, _MODEL_FAILED_AT
    if _MODEL is not None:
        return _MODEL
    # 刚失败过就不要再试（见 _MODEL_FAILED_AT 的说明）：否则每一次存记忆/检索记忆
    # 都会重新走一遍下载，一轮对话刷出好几条失败与一串进度条。
    if _MODEL_FAILED_AT and (time.time() - _MODEL_FAILED_AT) < _MODEL_RETRY_AFTER:
        return None
    try:
        from fastembed import TextEmbedding
        _MODEL = TextEmbedding(
            model_name=_MODEL_NAME,
            max_length=512,
        )
        try:
            _DIMENSION = len(next(_MODEL.embed(["test"])))
        except Exception:
            _DIMENSION = 512
        _VECTOR_ENABLED = True
        _vector_enabled = True
        _MODEL_FAILED_AT = 0.0
        print(f"[向量记忆] BGE 模型加载完成 (dim={_DIMENSION})")
        return _MODEL
    except Exception as e:
        _MODEL_FAILED_AT = time.time()
        print(f"[向量记忆] BGE 模型加载失败: {e}")
        print("[向量记忆] 已降级为关键词检索（记忆本身不受影响，只是少了语义召回）；"
              "%d 分钟内不再重试。要启用需本机能下载 %s"
              % (int(_MODEL_RETRY_AFTER / 60), _MODEL_NAME))
        _VECTOR_ENABLED = False
        _vector_enabled = False
        return None


def _encode(text: str) -> np.ndarray | None:
    model = _load_model()
    if model is None:
        return None
    emb = next(model.embed([text]))
    norm = np.linalg.norm(emb)
    if norm > 0:
        emb = emb / norm
    return np.asarray(emb, dtype=np.float32)


def load_engine_config():
    _init_db()
    _load_model()
    status = "已启用(BGE)" if _VECTOR_ENABLED else "降级"
    print(f"[向量记忆] 初始化完毕，状态: {status}")


def add_memory(user_id: str, memory_id: int, content: str, level: int = 3):
    if not content or not content.strip():
        return
    if level in NO_VECTOR_LEVELS:
        return
    emb = _encode(content)
    if emb is None:
        return
    _init_db()
    with _lock:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute(
            """
            INSERT OR REPLACE INTO embedding_index
               (memory_id, user_id, content, level, embedding)
               VALUES (?, ?, ?, ?, ?)""",
            (memory_id, user_id, content, level, emb.tobytes())
        )
        conn.commit()
        conn.close()


def _get_weight(level: int, context_mood: str = "") -> float:
    w = LEVEL_WEIGHTS.get(level, 0.5)
    mood_boost = MOOD_MULTIPLIER.get(context_mood, {})
    w *= mood_boost.get(level, 1.0)
    return w


def _load_user_vectors(user_id: str, context_mood: str = "") -> tuple:
    mids = []
    matrix_rows = []
    weights = []
    _init_db()
    with _lock:
        conn = sqlite3.connect(_DB_PATH)
        rows = conn.execute(
            "SELECT memory_id, content, level, embedding FROM embedding_index WHERE user_id = ? ORDER BY memory_id",
            (user_id,)
        ).fetchall()
        conn.close()
    for mid, content, level, blob in rows:
        if level in NO_SEARCH_LEVELS:
            continue
        vec = np.frombuffer(blob, dtype=np.float32)
        if vec.shape[0] == _DIMENSION:
            mids.append((mid, content, level))
            matrix_rows.append(vec)
            weights.append(_get_weight(level, context_mood))
    if not matrix_rows:
        return [], np.array([]), np.array([])
    return mids, np.array(matrix_rows, dtype=np.float32), np.array(weights, dtype=np.float32)


def search_memory(user_id: str, query: str, top_k: int = 3, context_mood: str = "") -> list:
    if not _VECTOR_ENABLED:
        return []
    query_vec = _encode(query)
    if query_vec is None:
        return []
    mids, matrix, weights = _load_user_vectors(user_id, context_mood)
    if not mids:
        return []
    scores = (matrix @ query_vec) * weights
    top_idx = np.argsort(scores)[-top_k:][::-1]
    results = []
    for idx in top_idx:
        sim = float(scores[idx])
        if sim < _MIN_SIMILARITY:
            continue
        mid, content, level = mids[idx]
        results.append({
            "memory_id": mid,
            "content": content,
            "similarity": round(sim, 3),
            "level": level,
            "level_name": LEVEL_NAMES.get(level, ""),
        })
    return results


def get_relevant_memory_context(user_id: str, query: str, max_chars: int = 500,
                                context_mood: str = "") -> str:
    memories = search_memory(user_id, query, top_k=5, context_mood=context_mood)
    if not memories:
        return ""
    lines = []
    total = 0
    for m in memories[:4]:
        lv = m.get("level_name", "")
        tag = f"[{lv}]" if lv else ""
        snippet = m["content"].strip()[:100]
        line = f"{tag} {snippet}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    if not lines:
        return ""
    return "【相关记忆】\n" + "\n".join(lines)


def remove_memory(memory_id: int):
    with _lock:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute("DELETE FROM embedding_index WHERE memory_id = ?", (memory_id,))
        conn.commit()
        conn.close()


def rebuild_index(user_id: str = None):
    """重建向量索引：从 memory 表读取所有记忆并重新编码。
    
    在系统启动后调用，确保向量索引与 memory 表同步。
    
    Args:
        user_id: 可选，指定用户。None = 重建所有用户。
    """
    model = _load_model()
    if model is None:
        print("[向量重建] 模型不可用，跳过")
        return 0

    try:
        conn_main = sqlite3.connect("data/db/soulmate.db")
        if user_id:
            rows = conn_main.execute(
                "SELECT id, user_id, content, memory_level FROM memory WHERE user_id = ? AND memory_level > 2 ORDER BY id",
                (user_id,)
            ).fetchall()
        else:
            rows = conn_main.execute(
                "SELECT id, user_id, content, memory_level FROM memory WHERE memory_level > 2 ORDER BY id"
            ).fetchall()
        conn_main.close()
    except Exception as e:
        print(f"[向量重建] 读取 memory 表失败: {e}")
        return 0

    count = 0
    for mid, uid, content, level in rows:
        if not content or not content.strip():
            continue
        if level in NO_VECTOR_LEVELS:
            continue
        emb = _encode(content)
        if emb is None:
            continue
        with _lock:
            conn = sqlite3.connect(_DB_PATH)
            conn.execute(
                """
                INSERT OR REPLACE INTO embedding_index
                   (memory_id, user_id, content, level, embedding)
                   VALUES (?, ?, ?, ?, ?)""",
                (mid, uid, content[:200], level, emb.tobytes())
            )
            conn.commit()
            conn.close()
        count += 1

    print(f"[向量重建] 完成: {count} 条记忆已索引")
    return count


def get_index_stats(user_id: str = None) -> dict:
    """获取向量索引统计信息"""
    _init_db()
    with _lock:
        conn = sqlite3.connect(_DB_PATH)
        if user_id:
            total = conn.execute(
                "SELECT COUNT(*) FROM embedding_index WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
        else:
            total = conn.execute("SELECT COUNT(*) FROM embedding_index").fetchone()[0]
        conn.close()
    return {
        "enabled": _VECTOR_ENABLED,
        "total_vectors": total,
        "dimension": _DIMENSION,
        "model": _MODEL_NAME,
        "min_similarity": _MIN_SIMILARITY,
    }






