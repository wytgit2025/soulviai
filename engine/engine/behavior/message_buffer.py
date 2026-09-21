# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""
消息积累器
===========
用户连续发送多条消息时，合并为一条处理，避免 AI 逐条回复。

用法:
  accumulator = MessageAccumulator(idle_timeout=3.0)
  
  # 在消息轮询循环中：
  batch = accumulator.add(user_id, message)
  if batch:
      # batch 是合并后的完整文本，交给 engine.chat()
      ...

  # 或定期调用 check_idle() 处理超时消息
  for batch, uid in accumulator.check_idle():
      engine.chat(uid, batch)
"""
import time
import threading


class MessageAccumulator:
    """消息积累器：用户连续发送的多条消息合并为一条处理"""

    def __init__(self, idle_timeout: float = 3.0, max_batch_size: int = 5):
        """
        Args:
            idle_timeout: 用户停手多少秒后触发合并（默认3秒）
            max_batch_size: 最多累积多少条后强制触发（默认5条）
        """
        self.idle_timeout = idle_timeout
        self.max_batch_size = max_batch_size
        self._buffers: dict[str, list[dict]] = {}  # user_id -> [{msg, ts}, ...]
        self._lock = threading.Lock()

    def add(self, user_id: str, message: str) -> str | None:
        """添加一条消息到缓冲区。
        
        Returns:
            str | None: 如果达到触发条件，返回合并后的完整文本；否则返回 None
        """
        with self._lock:
            if user_id not in self._buffers:
                self._buffers[user_id] = []
            self._buffers[user_id].append({
                "msg": message,
                "ts": time.time(),
            })

            # 达到最大批次 → 立即触发
            if len(self._buffers[user_id]) >= self.max_batch_size:
                return self._flush(user_id)
            
            return None

    def flush(self, user_id: str) -> str | None:
        """手动触发冲洗指定用户的缓冲区"""
        with self._lock:
            return self._flush(user_id)

    def _flush(self, user_id: str) -> str | None:
        """冲洗缓冲区（内部，需持有锁）"""
        entries = self._buffers.pop(user_id, [])
        if not entries:
            return None

        # 单条消息 → 原文返回
        if len(entries) == 1:
            return entries[0]["msg"]

        # 多条消息 → 合并为一段文本
        parts = []
        for e in entries:
            msg = e["msg"]
            parts.append(msg)

        merged = "\n".join(parts)
        # 给 AI 提示这是合并的连续消息
        wrapped = (
            f"【对方连续发了几条消息】\n{merged}\n"
            f"【这些是连续发来的，合在一起回复即可】"
        )
        return wrapped

    def check_idle(self) -> list[tuple[str, str]]:
        """检查是否有超时未冲洗的缓冲区。
        
        Returns:
            list of (user_id, merged_text) 需要处理的批次列表
        """
        results = []
        now = time.time()
        with self._lock:
            expired = []
            for user_id, entries in self._buffers.items():
                last_ts = entries[-1]["ts"]
                if now - last_ts >= self.idle_timeout:
                    expired.append(user_id)
            for uid in expired:
                batch = self._flush(uid)
                if batch:
                    results.append((uid, batch))
        return results

    def is_idle_for(self, user_id: str) -> bool:
        """检查某个用户是否已超过 idle 时间未发消息"""
        with self._lock:
            entries = self._buffers.get(user_id)
            if not entries:
                return True
            return (time.time() - entries[-1]["ts"]) >= self.idle_timeout

    @property
    def active_users(self) -> list[str]:
        """当前缓冲区中有消息的用户列表"""
        with self._lock:
            return list(self._buffers.keys())
