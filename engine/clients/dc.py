# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""Discord Bot 客户端
通过 discord.py Gateway 实现，后台线程运行 asyncio 事件循环
消息通过线程安全队列传递给主线程
"""
import json
import time
import os
import threading
import queue
import asyncio

_config: dict = {}
_lock = threading.Lock()

_bot_token: str = ""
_allowed_channel_ids: list = []
_allowed_user_ids: list = []
_message_queue: queue.Queue = queue.Queue()
_config_path: str = "config.json"

_discord_bot = None
_asyncio_loop = None
_ready = False
_bot_name: str = ""
_own_id: int = 0


def load_config(config_path: str = "config.json"):
    global _config, _config_path, _bot_token, _allowed_channel_ids, _allowed_user_ids
    _config_path = config_path

    try:
        from core import config as shared_cfg
        shared_cfg.load(config_path)
        dc_cfg = shared_cfg.get_section("discord")
        _config = dc_cfg
        _bot_token = dc_cfg.get("bot_token", "")
        _allowed_channel_ids = dc_cfg.get("allowed_channel_ids", [])
        _allowed_user_ids = dc_cfg.get("allowed_user_ids", [])
        return
    except Exception:
        pass

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    dc_cfg = cfg.get("discord", {})
    _config = dc_cfg
    _bot_token = os.getenv("DC_BOT_TOKEN", dc_cfg.get("bot_token", ""))


def _start_discord_bot():
    """在独立线程的事件循环中运行 discord bot"""
    global _asyncio_loop, _discord_bot, _ready

    try:
        import discord
        from discord import Intents
    except ImportError:
        print("[Discord] 请先安装 discord.py: pip install discord.py")
        return

    _asyncio_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_asyncio_loop)

    intents = Intents.default()
    intents.message_content = True

    class SoulviaiDiscordBot(discord.Client):
        async def on_ready(self):
            global _ready, _bot_name, _own_id
            _ready = True
            _bot_name = self.user.name
            _own_id = self.user.id
            print(f"[Discord] Bot 已登录: {self.user} (ID: {self.user.id})")

        async def on_message(self, message):
            if message.author.bot:
                return
            if message.author.id == self.user.id:
                return

            channel_id = str(message.channel.id)
            user_id = str(message.author.id)
            content = message.content.strip()

            if not content:
                return

            if _allowed_channel_ids and channel_id not in _allowed_channel_ids:
                return
            if _allowed_user_ids and user_id not in _allowed_user_ids:
                return

            is_dm = isinstance(message.channel, discord.DMChannel)
            from_user = channel_id
            context = {
                "channel_id": channel_id,
                "guild_id": str(message.guild.id) if message.guild else "",
                "author_id": user_id,
                "author_name": str(message.author),
            }

            msg = {
                "from_user": from_user,
                "user_id": user_id,
                "content": content,
                "msg_type": "c2c" if is_dm else "group",
                "msg_id": str(message.id),
                "platform": "discord",
                "_context": context,
            }
            _message_queue.put(msg)

        async def on_error(self, event, *args, **kwargs):
            print(f"[Discord] 事件错误: {event}")

    _discord_bot = SoulviaiDiscordBot(intents=intents)

    try:
        _asyncio_loop.run_until_complete(_discord_bot.start(_bot_token))
    except Exception as e:
        print(f"[Discord] 运行异常: {e}")
        _ready = False


def get_updates() -> list:
    msgs = []
    while not _message_queue.empty():
        try:
            msgs.append(_message_queue.get_nowait())
        except queue.Empty:
            break
    return msgs


async def _async_send_message(channel_id: str, text: str) -> bool:
    """异步发送消息到 Discord 频道/私信"""
    if not _discord_bot:
        return False
    try:
        channel = _discord_bot.get_channel(int(channel_id))
        if not channel:
            try:
                user = await _discord_bot.fetch_user(int(channel_id))
                await user.send(text)
                return True
            except Exception:
                return False
        await channel.send(text)
        return True
    except Exception as e:
        print(f"[Discord] 发送失败: {e}")
        return False


async def _async_send_typing(channel_id: str):
    if not _discord_bot:
        return
    try:
        channel = _discord_bot.get_channel(int(channel_id))
        if channel:
            await channel.typing()
    except Exception:
        pass


def send_message(channel_id: str, text: str) -> bool:
    """线程安全的发送（跨线程提交 async 任务）"""
    if not _asyncio_loop or not _discord_bot:
        return False
    future = asyncio.run_coroutine_threadsafe(
        _async_send_message(channel_id, text), _asyncio_loop
    )
    try:
        return future.result(timeout=15)
    except Exception as e:
        print(f"[Discord] 发送超时/失败: {e}")
        return False


def send_typing(channel_id: str, start: bool = True):
    if not _asyncio_loop or not _discord_bot:
        return
    asyncio.run_coroutine_threadsafe(
        _async_send_typing(channel_id), _asyncio_loop
    )


def check_login() -> bool:
    return _ready


def wait_login(timeout: int = 120) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _ready:
            return True
        time.sleep(1)
    return _ready


class DcBot:
    """Discord Bot 高级封装（同 WxBot/QQBot/TgBot 风格）"""
    def __init__(self, config_path: str = "config.json"):
        load_config(config_path)
        self._bot_thread: threading.Thread = None

    def wait_login(self, timeout: int = 120) -> bool:
        """启动 Discord Bot 线程并等待就绪"""
        self._bot_thread = threading.Thread(target=_start_discord_bot, daemon=True)
        self._bot_thread.start()

        deadline = time.time() + timeout
        while time.time() < deadline:
            if _ready:
                print("[Discord] Bot 就绪")
                return True
            time.sleep(1.5)

        return _ready

    def poll_messages(self) -> list:
        return get_updates()

    def reply(self, to_user: str, text: str) -> bool:
        return send_message(to_user, text)

    def send_typing(self, to_user: str, start: bool = True):
        send_typing(to_user, start)
