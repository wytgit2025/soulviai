# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""版权与溯源水印。

用途
----
每个分发副本可以注入一个唯一的 recipient 标识，用于在源码泄漏时
追溯来源。构建脚本 `scripts/dev/build_release.py --watermark <ID>` 会覆写
下面的 `_RECIPIENT`，生成带唯一标记的副本。

追溯方法
--------
拿到疑似泄漏的副本后，执行：

    grep -rn "SOULSIG" <泄漏目录>

即可读出该副本的 `_RECIPIENT`，从而定位是发给谁的那一份。

注意
----
本文件属于版权声明的一部分。MIT 许可证要求保留版权声明与许可声明，移除即违反许可条款。
"""

# ── 固定标识（不要改动，这是版权溯源的主键）──
_MARKER = "SOULSIG"
_PROJECT = "soul-skill"
_OWNER = "soul-skill 项目作者"

# ── 分发标识：构建时由 build_release.py 注入，形如 "20260920-0001" ──
# 源码库中保持为空字符串。
_RECIPIENT = ""


def watermark() -> str:
    """返回可被 grep 的水印串。"""
    return "%s:%s:%s:%s" % (_MARKER, _PROJECT, _OWNER, _RECIPIENT or "unassigned")


def recipient() -> str:
    """返回本次分发标识（源码库中为空）。"""
    return _RECIPIENT


def banner_line() -> str:
    """一行版权说明，可挂到 doctor / serve 的输出里。"""
    return "soul-skill · %s · MIT License" % _OWNER
