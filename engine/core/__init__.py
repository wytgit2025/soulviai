# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

#  soulviai — 基础设施核心包
# database / ai / client

import sys


class _SafeStdout:
    """安全 stdout 包装器 — 在 Windows GBK 终端下自动替换不可编码字符"""

    def __init__(self, original):
        self._original = original

    def write(self, text):
        try:
            self._original.write(text)
        except UnicodeEncodeError:
            self._original.write(text.encode('ascii', 'replace').decode('ascii'))

    def flush(self):
        self._original.flush()

    def __getattr__(self, name):
        return getattr(self._original, name)


sys.stdout = _SafeStdout(sys.stdout)
sys.stderr = _SafeStdout(sys.stderr)
