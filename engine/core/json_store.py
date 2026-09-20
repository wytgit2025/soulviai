# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""线程安全的 JSON 持久化存储
解决全系统 JSON 文件并发读写冲突问题。
使用文件锁 + 内存缓存双重保障。

用法:
  from core.json_store import JsonStore

  store = JsonStore("data/json/my_data.json")
  data = store.read()          # 线程安全读
  store.write({"key": "val"})  # 线程安全写
  store.update(lambda d: d.update({"key": "new"}))  # 原子更新
"""
import os
import json
import time
import threading
from typing import Any, Callable, Optional

# 跨平台文件锁：Unix 用 fcntl，Windows 用 msvcrt
import platform
if platform.system() == "Windows":
    import msvcrt
    def _lock_file(file_obj):
        try:
            msvcrt.locking(file_obj.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except (IOError, OSError):
            return False
    def _unlock_file(file_obj):
        try:
            msvcrt.locking(file_obj.fileno(), msvcrt.LK_UNLCK, 1)
        except (IOError, OSError):
            pass
else:
    import fcntl
    def _lock_file(file_obj):
        try:
            fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (IOError, OSError):
            return False
    def _unlock_file(file_obj):
        try:
            fcntl.flock(file_obj.fileno(), fcntl.LOCK_UN)
        except (IOError, OSError):
            pass

_RETRY_COUNT = 3
_RETRY_DELAY = 0.05  # 50ms


class JsonStore:
    """线程安全的 JSON 文件持久化存储"""

    def __init__(self, path: str, default: Any = None, auto_save: bool = True):
        self.path = path
        self.default = default if default is not None else {}
        self.auto_save = auto_save
        self._lock = threading.Lock()
        self._cache: Optional[Any] = None
        self._cache_dirty: bool = False
        self._cache_version: int = 0

    def _ensure_dir(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def _acquire_file_lock(self, file_obj) -> bool:
        """获取文件锁（非阻塞），重试多次"""
        for attempt in range(_RETRY_COUNT):
            if _lock_file(file_obj):
                return True
            if attempt < _RETRY_COUNT - 1:
                time.sleep(_RETRY_DELAY * (attempt + 1))
        return False

    def _release_file_lock(self, file_obj):
        _unlock_file(file_obj)

    def read(self) -> Any:
        """线程安全读取"""
        with self._lock:
            if self._cache is not None and not self._cache_dirty:
                return self._cache

            self._ensure_dir()
            if not os.path.exists(self.path):
                self._cache = self._deep_copy(self.default)
                return self._cache

            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    if not self._acquire_file_lock(f):
                        self._cache = self._deep_copy(self.default)
                        return self._cache
                    try:
                        self._cache = json.load(f)
                    finally:
                        self._release_file_lock(f)
                self._cache_dirty = False
                return self._cache
            except (json.JSONDecodeError, IOError, OSError):
                self._cache = self._deep_copy(self.default)
                return self._cache

    def write(self, data: Any):
        """线程安全写入"""
        with self._lock:
            self._cache = self._deep_copy(data)
            self._cache_dirty = False
            self._cache_version += 1
            self._flush()

    def update(self, updater: Callable[[Any], None]):
        """原子更新：读取→更新→写回"""
        with self._lock:
            data = self.read()
            updater(data)
            self._cache = data
            self._cache_dirty = False
            self._cache_version += 1
            self._flush()

    def _flush(self):
        """写入磁盘"""
        self._ensure_dir()
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                if not self._acquire_file_lock(f):
                    return
                try:
                    json.dump(self._cache, f, ensure_ascii=False, indent=2)
                finally:
                    self._release_file_lock(f)
        except (IOError, OSError) as e:
            print(f"[JsonStore] 写入失败 {self.path}: {e}")

    def append(self, key: str, value: Any, max_len: int = None):
        """向列表类型的 key 追加元素"""
        def _updater(data):
            if key not in data:
                data[key] = []
            data[key].append(value)
            if max_len and len(data[key]) > max_len:
                data[key] = data[key][-max_len:]
        self.update(_updater)

    def clear_cache(self):
        with self._lock:
            self._cache = None

    @staticmethod
    def _deep_copy(obj: Any) -> Any:
        try:
            return json.loads(json.dumps(obj))
        except Exception:
            return obj


# ── 便捷工厂 ──
_stores: dict = {}
_stores_lock = threading.Lock()


def get_store(path: str, default: Any = None) -> JsonStore:
    """获取 JsonStore 单例（按路径缓存）"""
    abs_path = os.path.abspath(path)
    with _stores_lock:
        if abs_path not in _stores:
            _stores[abs_path] = JsonStore(abs_path, default)
        return _stores[abs_path]
