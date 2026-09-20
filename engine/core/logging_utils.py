# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""统一日志与安全执行工具
替代全代码库的 try/except:pass 模式，提供：
1. safe_call() — 安全的函数调用，自动记录异常
2. LogContext — 上下文管理器，自动捕获异常
3. log_error() — 统一错误日志接口
"""
import traceback
import sys
import os
import time
from typing import Callable, Optional, TypeVar, Any
from functools import wraps

T = TypeVar("T")

# ── 调试开关（环境变量 SOUL_DEBUG=1 显示完整 traceback）──
_DEBUG = os.environ.get("SOUL_DEBUG", "")


def _format_exception(e: Exception, context: str = "") -> str:
    """格式化异常信息"""
    tb = traceback.format_exception(type(e), e, e.__traceback__)
    if _DEBUG:
        return f"[{context}] {type(e).__name__}: {e}\n{''.join(tb)}"
    return f"[{context}] {type(e).__name__}: {e}"


def log_error(source: str, message: str, exc_info: bool = False):
    """统一错误日志输出

    Args:
        source: 来源模块标识（如 "mind.spontaneous_fluctuation"）
        message: 日志消息
        exc_info: 是否附加异常堆栈
    """
    if exc_info:
        tb = traceback.format_exc()
        print(f"[ERROR:{source}] {message}\n{tb}", file=sys.stderr)
    else:
        print(f"[ERROR:{source}] {message}", file=sys.stderr)

    # 写入 DB 错误日志（不抛出异常）
    try:
        from core import database as db
        db_path = getattr(db, "DB_PATH", None) or "data/db/soulmate.db"
        import sqlite3
        conn = sqlite3.connect(db_path)
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


def safe_call(fn: Callable[..., T], *args, context: str = "",
              default_return: Any = None, **kwargs) -> T:
    """安全调用函数，异常时记录日志并返回默认值

    Args:
        fn: 要调用的函数
        context: 上下文描述（用于日志标识）
        default_return: 异常时的默认返回值
        args/kwargs: 传递给 fn 的参数

    Returns:
        fn 的返回值，或异常时的 default_return
    """
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        log_error(context or fn.__name__, str(e), exc_info=True)
        return default_return


def safe_method(context: str = ""):
    """装饰器：安全调用方法，异常时记录日志

    Args:
        context: 上下文描述，默认使用方法名

    Usage:
        @safe_method()
        def my_func(...):
            ...

        @safe_method("custom_context")
        def my_func(...):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            ctx = context or f"{func.__module__}.{func.__name__}"
            try:
                return func(*args, **kwargs)
            except Exception as e:
                log_error(ctx, str(e), exc_info=True)
                return None
        return wrapper
    return decorator


class LogContext:
    """上下文管理器：自动捕获并记录异常

    Usage:
        with LogContext("my_module.my_operation"):
            risky_operation()
    """
    def __init__(self, context: str, default_return: Any = None):
        self.context = context
        self.default_return = default_return

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            log_error(self.context, str(exc_val), exc_info=True)
            return True  # 阻止异常传播
        return False
