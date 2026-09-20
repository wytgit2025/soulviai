# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""soulviai 多平台客户端适配器
所有外部通讯平台的统一接入层。

架构：
  clients/
    wx.py         ← 微信 iLink Bot
    qq.py         ← QQ Bot 官方 API
    tg.py         ← Telegram Bot API
    dc.py         ← Discord Gateway
    im.py         ← iMessage BlueBubbles
    web.py        ← Web 终端
"""
