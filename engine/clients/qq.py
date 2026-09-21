# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""QQ Bot 客户端
直接对接 QQ 官方 Bot API v2
  - OAuth 2.0 获取 AccessToken
  - WebSocket Gateway 接收事件（私聊/群聊 @）
  - REST API 发送消息

和微信 iLink Bot 客户端相同风格，同一套集成模式。
"""
import json
import time
import os
import random
import threading
import queue

import requests

# ── 配置 ──
_config: dict = {}
_lock = threading.Lock()

# ── OAuth 凭证 ──
_app_id: str = ""
_client_secret: str = ""
_access_token: str = ""
_token_expires_at: float = 0.0

# ── WebSocket 状态 ──
_ws_url: str = "wss://api.sgroup.qq.com/websocket/"
_ws = None
_ws_thread: threading.Thread = None
_ws_running = False
_session_id: str = ""
_seq: int = 0
_heartbeat_interval: int = 45000  # 默认 45s，Hello 会覆盖
_last_heartbeat_ack: float = 0.0

# ── 消息队列 ──
_message_queue: queue.Queue = queue.Queue()

# ── 配置路径 ──
_config_path: str = "config.json"

# ── 常量 ──
_API_BASE: str = "https://api.sgroup.qq.com"
_OAUTH_URL: str = "https://bots.qq.com/app/getAppAccessToken"

# Intents: GROUP_AND_C2C_EVENT = 1 << 25 = 33554432
_INTENTS: int = 1 << 25


# ═══════════════════════════════════════════
# 加载配置
# ═══════════════════════════════════════════

def load_config(config_path: str = "config.json"):
    global _config, _config_path, _app_id, _client_secret
    _config_path = config_path

    try:
        from core import config as shared_cfg
        shared_cfg.load(config_path)
        qq_cfg = shared_cfg.get_section("qq_bot")
        _config = qq_cfg
        _app_id = qq_cfg.get("app_id", "")
        _client_secret = qq_cfg.get("client_secret", "")
        return
    except Exception as e:
        pass

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    qq_cfg = cfg.get("qq_bot", {})
    _config = qq_cfg
    _app_id = os.getenv("QQ_APP_ID", qq_cfg.get("app_id", ""))
    _client_secret = os.getenv("QQ_CLIENT_SECRET", qq_cfg.get("client_secret", ""))


# ═══════════════════════════════════════════
# OAuth 2.0 — Access Token 管理
# ═══════════════════════════════════════════

def _get_access_token() -> str:
    """获取/刷新 AccessToken（7200s 有效期，提前 60s 刷新）"""
    global _access_token, _token_expires_at

    now = time.time()
    if _access_token and now < _token_expires_at - 60:
        return _access_token

    try:
        r = requests.post(_OAUTH_URL, json={
            "appId": _app_id,
            "clientSecret": _client_secret,
        }, timeout=10)
        data = r.json()
        _access_token = data.get("access_token", "")
        expires_in = int(data.get("expires_in", 7200))
        _token_expires_at = now + expires_in
        return _access_token
    except Exception as e:
        print(f"[QQ OAuth] 获取 token 失败: {e}")
        return _access_token if _access_token else ""


def _save_creds():
    """持久化配置（app_id, client_secret 等）"""
    if not os.path.exists(_config_path):
        return
    with open(_config_path, "r+", encoding="utf-8") as f:
        cfg = json.load(f)
        cfg.setdefault("qq_bot", {})
        cfg["qq_bot"]["app_id"] = _app_id
        cfg["qq_bot"]["client_secret"] = _client_secret
        f.seek(0)
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.truncate()


# ═══════════════════════════════════════════
# 发送消息 REST API
# ═══════════════════════════════════════════

def _api_headers() -> dict:
    token = _get_access_token()
    return {
        "Content-Type": "application/json",
        "Authorization": f"QQBot {token}",
        "X-Union-Appid": _app_id,
    }


def send_c2c_message(openid: str, content: str, msg_id: str = "") -> dict:
    """发送私聊消息（被动回复需传 msg_id）"""
    token = _get_access_token()
    url = f"{_API_BASE}/v2/users/{openid}/messages"
    body = {"content": content, "msg_type": 0}
    if msg_id:
        body["msg_id"] = msg_id
        body["msg_seq"] = 1
    try:
        r = requests.post(url, json=body, headers=_api_headers(), timeout=10)
        return r.json() if r.text else {}
    except Exception as e:
        return {"error": str(e)}


def send_group_message(group_openid: str, content: str, msg_id: str = "") -> dict:
    """发送群聊消息（被动回复需传 msg_id）"""
    url = f"{_API_BASE}/v2/groups/{group_openid}/messages"
    body = {"content": content, "msg_type": 0}
    if msg_id:
        body["msg_id"] = msg_id
        body["msg_seq"] = 1
    try:
        r = requests.post(url, json=body, headers=_api_headers(), timeout=10)
        return r.json() if r.text else {}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════
# 图片/媒体 发送
# ═══════════════════════════════════════════

def upload_c2c_media(openid: str, file_path: str) -> dict:
    """上传媒体文件到 C2C 频道，返回 file_uuid"""
    url = f"{_API_BASE}/v2/users/{openid}/files"
    try:
        with open(file_path, "rb") as f:
            files = {"file": (file_path, f, "image/png")}
            data = {"srv_send_msg": "0"}
            r = requests.post(url, files=files, data=data, headers={
                "Authorization": _api_headers()["Authorization"],
                "X-Union-Appid": _app_id,
            }, timeout=30)
        return r.json() if r.text else {}
    except Exception as e:
        return {"error": str(e)}


def upload_group_media(group_openid: str, file_path: str) -> dict:
    """上传媒体文件到群频道，返回 file_uuid"""
    url = f"{_API_BASE}/v2/groups/{group_openid}/files"
    try:
        with open(file_path, "rb") as f:
            files = {"file": (file_path, f, "image/png")}
            data = {"srv_send_msg": "0"}
            r = requests.post(url, files=files, data=data, headers={
                "Authorization": _api_headers()["Authorization"],
                "X-Union-Appid": _app_id,
            }, timeout=30)
        return r.json() if r.text else {}
    except Exception as e:
        return {"error": str(e)}


def send_c2c_image(openid: str, file_uuid: str, msg_id: str = "") -> dict:
    """发送私聊图片消息"""
    url = f"{_API_BASE}/v2/users/{openid}/messages"
    body = {"msg_type": 2, "media": {"file_uuid": file_uuid}}
    if msg_id:
        body["msg_id"] = msg_id
        body["msg_seq"] = 1
    try:
        r = requests.post(url, json=body, headers=_api_headers(), timeout=10)
        return r.json() if r.text else {}
    except Exception as e:
        return {"error": str(e)}


def send_group_image(group_openid: str, file_uuid: str, msg_id: str = "") -> dict:
    """发送群聊图片消息"""
    url = f"{_API_BASE}/v2/groups/{group_openid}/messages"
    body = {"msg_type": 2, "media": {"file_uuid": file_uuid}}
    if msg_id:
        body["msg_id"] = msg_id
        body["msg_seq"] = 1
    try:
        r = requests.post(url, json=body, headers=_api_headers(), timeout=10)
        return r.json() if r.text else {}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════
# WebSocket Gateway — 接收事件
# ═══════════════════════════════════════════

def _on_ws_message(ws, message: str):
    """WebSocket 收到消息"""
    global _seq
    try:
        payload = json.loads(message)
    except Exception:
        return

    op = payload.get("op", -1)
    s = payload.get("s", 0)
    t = payload.get("t", "")
    d = payload.get("d", {})

    if s:
        _seq = s

    if op == 10:
        _on_hello(d)
    elif op == 0:
        _on_dispatch(t, d, payload.get("id", ""))
    elif op == 11:
        _on_heartbeat_ack()
    elif op == 7:
        _on_reconnect()
    elif op == 9:
        print(f"[QQ WS] Invalid Session, 重新 Identify")
        _send_identify()


def _on_hello(data: dict):
    """OpCode 10 Hello — 获取心跳间隔"""
    global _heartbeat_interval, _last_heartbeat_ack
    _heartbeat_interval = data.get("heartbeat_interval", 45000)
    _last_heartbeat_ack = time.time()
    _send_identify()


def _send_identify():
    """OpCode 2 Identify — 登录鉴权"""
    token = _get_access_token()
    if not token:
        print("[QQ WS] 无 AccessToken，无法鉴权")
        return
    identify = {
        "op": 2,
        "d": {
            "token": f"QQBot {token}",
            "intents": _INTENTS,
            "shard": [0, 1],
            "properties": {
                "$os": "linux",
                "$browser": "soul_engine",
                "$device": "soul_engine",
            },
        },
    }
    _ws_send(identify)


def _send_resume():
    """OpCode 6 Resume — 恢复连接"""
    token = _get_access_token()
    if not token:
        return
    resume = {
        "op": 6,
        "d": {
            "token": f"QQBot {token}",
            "session_id": _session_id,
            "seq": _seq,
        },
    }
    _ws_send(resume)


def _on_dispatch(t: str, data: dict, event_id: str):
    """OpCode 0 Dispatch — 事件分发"""
    if t == "READY":
        global _session_id
        _session_id = data.get("session_id", "")
        user = data.get("user", {})
        print(f"[QQ] Bot 已就绪 — ID: {user.get('id', '?')}, session: {_session_id}")
        return

    if t == "RESUMED":
        print("[QQ] 连接已恢复")
        return

    _ATTACH_TYPE_NAMES = {
        1: "[图片]", 2: "[视频]", 3: "[语音]", 4: "[文件]",
    }

    def _describe_attachments(attachments: list) -> str:
        """将 attachments 数组转为文字描述"""
        if not attachments:
            return ""
        parts = []
        for att in attachments:
            ct = att.get("content_type", 0)
            parts.append(_ATTACH_TYPE_NAMES.get(ct, "[附件]"))
        return " ".join(parts) if parts else "[附件]"

    if t == "C2C_MESSAGE_CREATE":
        content = data.get("content", "")
        author = data.get("author", {})
        openid = author.get("id", "")
        attachments = data.get("attachments", [])
        if not content and attachments:
            content = _describe_attachments(attachments)
        if content and openid:
            _message_queue.put({
                "type": "c2c",
                "from_user": openid,
                "content": content,
                "event_id": event_id,
                "msg_id": data.get("id", ""),
                "timestamp": time.time(),
            })
        return

    if t == "GROUP_AT_MESSAGE_CREATE":
        content = data.get("content", "")
        author = data.get("author", {})
        member_openid = author.get("id", "")
        group_openid = data.get("group_openid", "")
        attachments = data.get("attachments", [])
        if not content and attachments:
            content = _describe_attachments(attachments)
        if content and member_openid:
            _message_queue.put({
                "type": "group",
                "from_user": member_openid,
                "group_openid": group_openid,
                "content": content,
                "event_id": event_id,
                "msg_id": data.get("id", ""),
                "timestamp": time.time(),
            })
        return


# ── 重连状态 ──
_ws_reconnecting: bool = False
_heartbeat_thread: threading.Thread = None


def _on_heartbeat_ack():
    """OpCode 11 Heartbeat ACK"""
    global _last_heartbeat_ack
    _last_heartbeat_ack = time.time()


def _on_reconnect():
    """OpCode 7 Reconnect"""
    print("[QQ WS] 服务端要求重连")
    _ws_running = False


def _send_heartbeat():
    """OpCode 1 Heartbeat"""
    _ws_send({"op": 1, "d": _seq})


def _ws_send(data: dict):
    """发送 WebSocket 消息（线程安全）"""
    global _ws
    if _ws:
        try:
            _ws.send(json.dumps(data))
        except Exception:
            pass


def _ws_close():
    """主动关闭 WebSocket 连接"""
    global _ws
    if _ws:
        try:
            _ws.close()
        except Exception:
            pass


def _start_heartbeat():
    """启动心跳线程（确保旧的已停止）"""
    global _heartbeat_thread
    if _heartbeat_thread and _heartbeat_thread.is_alive():
        return
    _heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True, name="qq-hb")
    _heartbeat_thread.start()


def _heartbeat_loop():
    """心跳线程"""
    global _ws_running
    while _ws_running:
        _send_heartbeat()
        now = time.time()
        if now - _last_heartbeat_ack > _heartbeat_interval / 1000 * 3:
            print("[QQ WS] 心跳超时，主动断连重连")
            _ws_running = False
            _ws_close()
            break
        time.sleep(_heartbeat_interval / 1000)


def _ws_connect(url: str = None) -> bool:
    """建立 WebSocket 连接"""
    global _ws, _ws_running

    target = url or _ws_url

    try:
        import websocket
    except ImportError:
        print("[QQ WS] 请安装 websocket-client: pip install websocket-client")
        return False

    ws = websocket.WebSocketApp(
        target,
        on_message=lambda ws, msg: _on_ws_message(ws, msg),
        on_error=lambda ws, err: _on_ws_error(ws, err),
        on_close=lambda ws, code, msg: _on_ws_close(ws, code, msg),
        on_open=lambda ws: _on_ws_open(ws),
    )
    _ws = ws

    wst = threading.Thread(
        target=ws.run_forever,
        daemon=True,
        name="qq-ws",
    )
    wst.start()
    _ws_running = True

    return True


def _on_ws_open(ws):
    print("[QQ WS] 连接已建立")


def _on_ws_error(ws, error):
    print(f"[QQ WS] 错误: {error}")


def _on_ws_close(ws, code, msg):
    global _ws_running, _ws_reconnecting
    _ws_running = False
    if _ws_reconnecting:
        return
    if code and code != 1000:
        _ws_reconnecting = True
        print(f"[QQ WS] 连接关闭 (code={code}), 5s 后重连...")
        time.sleep(5)
        _start_ws_with_reconnect(_session_id)
        _ws_reconnecting = False


def _start_ws_with_reconnect(session_id: str = ""):
    """带重连机制的 WebSocket 启动"""
    retry = 0
    max_retry = 50
    while retry < max_retry:
        if not _get_access_token():
            time.sleep(3)
            retry += 1
            continue

        if not _ws_connect():
            time.sleep(3)
            retry += 1
            continue

        # 等待 Ready（最多 10s）
        for _ in range(50):
            time.sleep(0.2)
            if _session_id or not _ws_running:
                break

        if _session_id:
            print(f"[QQ WS] 连接就绪, session: {_session_id}")
            _start_heartbeat()
            return True

        retry += 1
        time.sleep(1)

    print("[QQ WS] 连接失败，已达到最大重试次数")
    return False


# ═══════════════════════════════════════════
# 高级接口 — 类似 WxBot 风格
# ═══════════════════════════════════════════

def check_login() -> bool:
    """检查是否已配置凭证"""
    return bool(_app_id and _client_secret)


def get_updates() -> list:
    """从内部队列获取消息（类似微信 get_updates 的非阻塞轮询）
    返回消息列表，格式同微信 client:
      {"from_user": "openid", "content": "文本"}
    """
    msgs = []
    while not _message_queue.empty():
        try:
            msgs.append(_message_queue.get_nowait())
        except queue.Empty:
            break
    return msgs


def send_message(to_user: str, text: str, msg_type: str = "c2c", event_id: str = "") -> dict:
    """发送消息（自动区分私聊/群聊）"""
    if msg_type == "group":
        return send_group_message(to_user, text, event_id)
    return send_c2c_message(to_user, text, event_id)


def send_image(to_user: str, file_uuid: str, msg_type: str = "c2c") -> dict:
    """发送图片消息（自动区分私聊/群聊）"""
    if msg_type == "group":
        return send_group_image(to_user, file_uuid)
    return send_c2c_image(to_user, file_uuid)


class QQBot:
    """QQ Bot 高级封装（同 WxBot 风格）
    自动跟踪每个用户的对话上下文（私聊/群聊），reply 时自动使用正确的 API。
    """
    def __init__(self, config_path: str = "config.json"):
        load_config(config_path)
        self._user_context: dict = {}

    def wait_login(self, timeout: int = 120) -> bool:
        """获取 AccessToken + 建立 WebSocket 连接
        阻塞直到 Ready 或超时
        """
        print("[QQ Bot] 正在获取 AccessToken...")
        token = _get_access_token()
        if not token:
            print("[QQ Bot] ❌ 获取 AccessToken 失败")
            return False
        print("[QQ Bot] ✅ AccessToken 获取成功")

        print("[QQ Bot] 正在连接 WebSocket Gateway...")
        ok = _start_ws_with_reconnect()
        if not ok:
            print("[QQ Bot] ❌ WebSocket 连接失败")
            return False

        # 启动心跳线程
        _start_heartbeat()

        print("[QQ Bot] ✅ 连接就绪，等待消息...")
        return True

    def poll_messages(self) -> list:
        """获取新消息并缓存用户上下文"""
        msgs = get_updates()
        for m in msgs:
            self._user_context[m["from_user"]] = {
                "type": m.get("type", "c2c"),
                "group_openid": m.get("group_openid", ""),
                "msg_id": m.get("msg_id", ""),
            }
        return msgs

    def reply(self, to_user: str, text: str) -> bool:
        """回复消息（自动匹配私聊/群聊上下文）"""
        ctx = self._user_context.get(to_user, {"type": "c2c", "group_openid": "", "msg_id": ""})
        msg_type = ctx["type"]
        msg_id = ctx.get("msg_id", "")

        if msg_type == "group":
            group_openid = ctx.get("group_openid", "")
            if not group_openid:
                print(f"[QQ Bot] 无群聊上下文，无法回复 {to_user}")
                return False
            r = send_group_message(group_openid, text, msg_id)
        else:
            r = send_c2c_message(to_user, text, msg_id)

        err = r.get("error", "")
        if err:
            print(f"[QQ Bot] 发送失败: {err}")
            return False
        code = r.get("code", 0)
        if code:
            print(f"[QQ Bot] API 返回错误: code={code} msg={r.get('message', '')}")
            return False
        return True

    def send_typing(self, to_user: str, start: bool = True):
        """模拟「正在输入」状态 — QQ Bot API 不支持此功能，静默跳过"""

    def reply_image(self, to_user: str, file_uuid: str) -> bool:
        """回复图片消息（自动匹配私聊/群聊上下文）"""
        ctx = self._user_context.get(to_user, {"type": "c2c", "group_openid": "", "msg_id": ""})
        msg_type = ctx["type"]

        if msg_type == "group":
            group_openid = ctx.get("group_openid", "")
            if not group_openid:
                print(f"[QQ Bot] 无群聊上下文，无法回复图片 {to_user}")
                return False
            r = send_group_image(group_openid, file_uuid)
        else:
            r = send_c2c_image(to_user, file_uuid)

        err = r.get("error", "")
        if err:
            print(f"[QQ Bot] 图片发送失败: {err}")
            return False
        code = r.get("code", 0)
        if code:
            print(f"[QQ Bot] 图片API错误: code={code} msg={r.get('message', '')}")
            return False
        return True
