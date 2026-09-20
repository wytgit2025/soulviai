# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""Telegram Bot 客户端
通过官方 Bot API (HTTP) 实现，零额外依赖（仅 httpx）
遵循 soulviai 统一的 Poll-and-Reply 模式
"""
import json
import time
import os
import threading
import queue

import httpx

_config: dict = {}
_lock = threading.Lock()

_bot_token: str = ""
_api_base: str = "https://api.telegram.org"
_allowed_user_ids: list = []
_poll_offset: int = 0
_message_queue: queue.Queue = queue.Queue()
_config_path: str = "config.json"
_own_id: int = 0
_bot_name: str = ""


def load_config(config_path: str = "config.json"):
    global _config, _config_path, _bot_token, _allowed_user_ids
    _config_path = config_path

    try:
        from core import config as shared_cfg
        shared_cfg.load(config_path)
        tg_cfg = shared_cfg.get_section("telegram")
        _config = tg_cfg
        _bot_token = tg_cfg.get("bot_token", "")
        _allowed_user_ids = tg_cfg.get("allowed_user_ids", [])
        return
    except Exception:
        pass

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    tg_cfg = cfg.get("telegram", {})
    _config = tg_cfg
    _bot_token = os.getenv("TG_BOT_TOKEN", tg_cfg.get("bot_token", ""))
    _allowed_user_ids = tg_cfg.get("allowed_user_ids", [])


def _api_url(method: str) -> str:
    return f"{_api_base}/bot{_bot_token}/{method}"


def _api_call(method: str, json_data: dict = None, params: dict = None) -> dict:
    """通用 API 调用"""
    url = _api_url(method)
    try:
        with httpx.Client(timeout=15) as client:
            r = client.post(url, json=json_data or {}, params=params or {})
            return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _process_update(update: dict):
    """将 Telegram Update 转为 soulviai 统一消息格式"""
    msg = update.get("message") or update.get("callback_query", {}).get("message")
    if not msg:
        return None

    chat = msg.get("chat", {})
    chat_id = str(chat.get("id", ""))
    text = msg.get("text", "") or msg.get("caption", "")
    msg_id = msg.get("message_id", 0)
    date = msg.get("date", int(time.time()))
    from_user = msg.get("from", {})
    user_id = str(from_user.get("id", ""))
    is_bot = from_user.get("is_bot", False)

    if is_bot or not text:
        return None

    if _allowed_user_ids and user_id not in _allowed_user_ids and chat_id not in _allowed_user_ids:
        return None

    chat_type = chat.get("type", "private")
    msg_type = "group" if chat_type in ("group", "supergroup") else "c2c"

    return {
        "from_user": chat_id,
        "user_id": user_id,
        "content": text,
        "msg_type": msg_type,
        "msg_id": str(msg_id),
        "date": date,
        "platform": "telegram",
    }


def _poll_updates():
    """后台轮询线程：从 Telegram 拉取更新"""
    global _poll_offset

    while True:
        try:
            params = {
                "offset": _poll_offset,
                "timeout": 30,
                "allowed_updates": json.dumps(["message", "callback_query"]),
            }
            r = _api_call("getUpdates", params=params)
            if not r.get("ok"):
                time.sleep(5)
                continue

            for update in r.get("result", []):
                update_id = update.get("update_id", 0)
                if update_id >= _poll_offset:
                    _poll_offset = update_id + 1

                msg = _process_update(update)
                if msg:
                    _message_queue.put(msg)

        except Exception as e:
            print(f"[Telegram] 轮询异常: {e}")
            time.sleep(5)


def get_updates() -> list:
    """获取队列中的新消息（非阻塞）"""
    msgs = []
    while not _message_queue.empty():
        try:
            msgs.append(_message_queue.get_nowait())
        except queue.Empty:
            break
    return msgs


def send_message(chat_id: str, text: str) -> dict:
    """发送消息到指定 chat"""
    return _api_call("sendMessage", json_data={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    })


def send_typing(chat_id: str, start: bool = True):
    """发送「正在输入」状态"""
    _api_call("sendChatAction", json_data={
        "chat_id": chat_id,
        "action": "typing",
    })


def check_login() -> bool:
    """检查 Bot Token 是否有效"""
    r = _api_call("getMe")
    global _own_id, _bot_name
    if r.get("ok"):
        user = r.get("result", {})
        _own_id = user.get("id", 0)
        _bot_name = user.get("first_name", "")
        print(f"[Telegram] Bot 已登录: @{user.get('username', '')} ({_bot_name})")
        return True
    print(f"[Telegram] 登录失败: {r.get('description', '')}")
    return False


def wait_login(timeout: int = 120) -> bool:
    """等待登录完成"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check_login():
            return True
        time.sleep(3)
    return False


class TgBot:
    """Telegram Bot 高级封装（同 WxBot/QQBot 风格）"""
    def __init__(self, config_path: str = "config.json"):
        load_config(config_path)
        self._poll_thread: threading.Thread = None

    def wait_login(self, timeout: int = 120) -> bool:
        """登录并启动后台轮询"""
        ok = wait_login(timeout)
        if ok:
            self._poll_thread = threading.Thread(target=_poll_updates, daemon=True)
            self._poll_thread.start()
            print("[Telegram] 后台轮询已启动")
        return ok

    def poll_messages(self) -> list:
        return get_updates()

    def reply(self, to_user: str, text: str) -> bool:
        r = send_message(to_user, text)
        if not r.get("ok"):
            print(f"[Telegram] 发送失败: {r.get('description', '')}")
            return False
        return True

    def send_typing(self, to_user: str, start: bool = True):
        send_typing(to_user, start)
