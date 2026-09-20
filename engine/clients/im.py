# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""iMessage Bot 客户端
通过 BlueBubbles Server HTTP API 实现
需要 macOS 上运行 BlueBubbles 服务端: https://bluebubbles.app
"""
import json
import time
import os
import threading
import queue

import httpx

_config: dict = {}
_lock = threading.Lock()

_bluebubbles_url: str = "http://localhost:1234"
_api_key: str = ""
_server_password: str = ""
_message_queue: queue.Queue = queue.Queue()
_poll_thread: threading.Thread = None
_connected: bool = False
_config_path: str = "config.json"
_last_message_id: str = ""


def load_config(config_path: str = "config.json"):
    global _config, _config_path, _bluebubbles_url, _api_key, _server_password
    _config_path = config_path

    try:
        from core import config as shared_cfg
        shared_cfg.load(config_path)
        im_cfg = shared_cfg.get_section("imessage")
        _config = im_cfg
        _bluebubbles_url = im_cfg.get("bluebubbles_url", "http://localhost:1234")
        _api_key = im_cfg.get("api_key", "")
        _server_password = im_cfg.get("server_password", "")
        return
    except Exception:
        pass

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    im_cfg = cfg.get("imessage", {})
    _config = im_cfg
    _bluebubbles_url = os.getenv("BB_URL", im_cfg.get("bluebubbles_url", "http://localhost:1234"))
    _api_key = os.getenv("BB_API_KEY", im_cfg.get("api_key", ""))


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if _api_key:
        h["Authorization"] = f"Bearer {_api_key}"
    if _server_password and not _api_key:
        h["password"] = _server_password
    return h


def _api_get(path: str, params: dict = None, timeout: int = 15) -> dict:
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(f"{_bluebubbles_url}{path}", headers=_headers(), params=params or {})
            return r.json()
    except Exception as e:
        return {"error": str(e)}


def _api_post(path: str, data: dict = None, timeout: int = 15) -> dict:
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(f"{_bluebubbles_url}{path}", headers=_headers(), json=data or {})
            return r.json()
    except Exception as e:
        return {"error": str(e)}


def _poll_messages_loop():
    """后台轮询 BlueBubbles 新消息"""
    global _last_message_id, _connected

    while True:
        try:
            r = _api_get("/api/message/recent", params={"limit": 10})
            if "error" in r:
                _connected = False
                time.sleep(10)
                continue

            _connected = True
            messages = r if isinstance(r, list) else r.get("data", r.get("messages", []))

            for msg in messages:
                msg_id = msg.get("guid", msg.get("id", ""))
                if not msg_id:
                    continue
                if msg_id == _last_message_id:
                    break

                text = msg.get("text", "")
                is_from_me = msg.get("isFromMe", False)
                if is_from_me or not text:
                    continue

                address = msg.get("handle", {}).get("id", "") or msg.get("sender", "")
                chat_guid = msg.get("chatGuid", msg.get("chat", {}).get("guid", ""))
                chat_name = msg.get("chatName", msg.get("chat", {}).get("displayName", ""))

                if not address:
                    continue

                entry = {
                    "from_user": chat_guid or address,
                    "user_id": address,
                    "content": text,
                    "msg_type": "c2c",
                    "msg_id": msg_id,
                    "platform": "imessage",
                    "_context": {
                        "address": address,
                        "chat_name": chat_name,
                    },
                }
                _message_queue.put(entry)

            if messages:
                _last_message_id = messages[0].get("guid", messages[0].get("id", ""))

        except Exception as e:
            _connected = False

        time.sleep(5)


def get_updates() -> list:
    msgs = []
    while not _message_queue.empty():
        try:
            msgs.append(_message_queue.get_nowait())
        except queue.Empty:
            break
    return msgs


def send_message(to: str, text: str) -> bool:
    """发送 iMessage"""
    r = _api_post("/api/message/send", {
        "chatGuid": to,
        "text": text,
    })
    status = r.get("status", 200)
    return status == 200 or r.get("success", False)


def send_typing(to: str, start: bool = True):
    """发送 typing 指示"""
    _api_post("/api/message/typing", {
        "chatGuid": to,
        "typing": start,
    })


def check_connection() -> bool:
    r = _api_get("/api/ping", timeout=5)
    return "error" not in r


def wait_login(timeout: int = 120) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check_connection():
            print(f"[iMessage] ✅ BlueBubbles 服务器连接成功 ({_bluebubbles_url})")
            global _poll_thread
            _poll_thread = threading.Thread(target=_poll_messages_loop, daemon=True)
            _poll_thread.start()
            print("[iMessage] 后台消息轮询已启动")
            return True
        print("[iMessage] 等待 BlueBubbles 服务器...")
        time.sleep(5)
    return False


class ImBot:
    """iMessage (BlueBubbles) Bot 高级封装（同 WxBot 风格）"""
    def __init__(self, config_path: str = "config.json"):
        load_config(config_path)

    def wait_login(self, timeout: int = 120) -> bool:
        return wait_login(timeout)

    def poll_messages(self) -> list:
        return get_updates()

    def reply(self, to_user: str, text: str) -> bool:
        return send_message(to_user, text)

    def send_typing(self, to_user: str, start: bool = True):
        send_typing(to_user, start)
