# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""
A2: 结构化 Prompt 块定义
================================
每个模块注入 prompt 的信息统一为 PromptBlock。
builder 按重要性排序 + 按 token budget 截断。
"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class PromptBlock:
    """结构化 prompt 信息块"""
    tag: str           # 区块标记, 如"时间感知"/"羁绊"/"瑕疵"
    content: str       # 核心内容 (≤200字)
    importance: float  # 0~1, 越高越优先保留
    source: str = ""   # 来源模块名, 用于调试/审计


MAX_PROMPT_CHARS = 2500  # 可配置


class PromptBuilder:
    """按重要性排序 + token budget 截断的 prompt 构建器"""
    def __init__(self, max_chars: int = MAX_PROMPT_CHARS):
        self.blocks: List[PromptBlock] = []
        self.max_chars = max_chars
        self._stats = {}  # source → total_chars

    def add(self, tag: str, content: str, importance: float, source: str = ""):
        if not content:
            return
        self.blocks.append(PromptBlock(
            tag=tag, content=content.strip(),
            importance=importance, source=source,
        ))

    def build(self) -> str:
        self.blocks.sort(key=lambda b: b.importance, reverse=True)
        parts = []
        total = 0
        budget = self.max_chars

        for b in self.blocks:
            block_text = f"\n【{b.tag}】\n{b.content}"
            needed = len(block_text)
            if total + needed > budget:
                continue
            parts.append(block_text)
            total += needed
            src = b.source or b.tag
            self._stats[src] = self._stats.get(src, 0) + needed

        return "\n".join(parts)

    def get_stats(self) -> dict:
        """返回每个模块消耗的字符数"""
        return dict(self._stats)
