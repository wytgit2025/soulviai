# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""统一启动 Banner 模块 — 所有入口共享同一套视觉风格"""

# 固定宽度，视觉效果更紧凑
W = 50

TL = "┌"; TR = "┐"; BL = "└"; BR = "┘"
H  = "─"; V  = "│"

def _dw(text: str) -> int:
    """计算字符串在终端中的显示宽度（CJK 字符占 2 列）"""
    width = 0
    for ch in text:
        if ord(ch) > 0x2E80:  # CJK 统一表意文字区块起点
            width += 2
        else:
            width += 1
    return width

def _top() -> str:
    return f"{TL}{H * (W - 2)}{TR}"

def _bot() -> str:
    return f"{BL}{H * (W - 2)}{BR}"

def _mid() -> str:
    return f"├{H * (W - 2)}┤"

def _line(text: str = "") -> str:
    pad = W - 2
    if text:
        dw = _dw(text)
        left = (pad - dw) // 2
        right = pad - left - dw
        return f"{V}{' ' * left}{text}{' ' * right}{V}"
    return f"{V}{' ' * pad}{V}"

def _line_left(text: str = "") -> str:
    pad = W - 2
    right = pad - _dw(text)
    return f"{V} {text}{' ' * (right - 1)}{V}"


def banner_menu() -> str:
    lines = [
        _top(),
        _line("✦  soulviai  ✦"),
        _line("数字生命引擎"),
        _line(""),
        _line("生命轨迹 · 情感羁绊 · 自主意识 · 成长"),
        _mid(),
        _line(""),
        _line_left("模式选择:"),
        _line_left("  1. 终端对话（默认）"),
        _line_left("  2. 微信 Bot"),
        _line_left("  3. 查看生命状态"),
        _line(""),
        _bot(),
    ]
    return "\n".join(lines)


def banner_mode(title: str, subtitle: str = "") -> str:
    lines = [
        _top(),
        _line("✦  soulviai  ✦"),
        _line(title),
    ]
    if subtitle:
        lines.append(_line(subtitle))
    lines.append(_bot())
    return "\n".join(lines)


def banner_state() -> str:
    lines = [
        _top(),
        _line("✦  soulviai  ✦"),
        _line("生命状态"),
        _bot(),
    ]
    return "\n".join(lines)
