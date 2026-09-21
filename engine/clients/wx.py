# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""微信 iLink Bot 客户端
直接对接微信官方 iLink Bot API (https://ilinkai.weixin.qq.com)

扫码登录 → 长轮询收消息 → 发送消息 → 状态管理
"""
import json
import time
import os
import base64
import random
import struct
import threading
import requests

# ── 配置 ──
_config: dict = {}
_base_url: str = "https://ilinkai.weixin.qq.com"
_lock = threading.Lock()

# ── 登录凭证（持久化在 config.json 的 wx_bot 段）──
_bot_token: str = ""
_ilink_bot_id: str = ""
_ilink_user_id: str = ""
_config_path: str = "config.json"

# ── 每个用户的 context_token 缓存（收发消息必须原样回传）─
_user_context: dict = {}
# ── 长轮询游标 ──
_get_updates_buf: str = ""


# ═══════════════════════════════════════════
# 加载配置
# ═══════════════════════════════════════════

def load_config(config_path: str = "config.json"):
    global _config, _config_path, _bot_token, _ilink_bot_id, _ilink_user_id
    _config_path = config_path

    # 优先用共享配置模块（支持 .env 覆盖）
    try:
        from core import config as shared_cfg
        shared_cfg.load(config_path)
        wx_cfg = shared_cfg.get_section("wx_bot")
        _config = wx_cfg
        _bot_token = wx_cfg.get("bot_token", "")
        _ilink_bot_id = wx_cfg.get("ilink_bot_id", "")
        _ilink_user_id = wx_cfg.get("ilink_user_id", "")
        return
    except Exception as e:
        print(f"[Client] 共享配置加载失败，回退直接读取: {e}")

    # 回退：直接读 config.json + .env
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    wx_cfg = cfg.get("wx_bot", {})
    _config = wx_cfg
    # 尝试从环境变量覆盖
    import os
    _bot_token = os.getenv("WX_BOT_TOKEN", wx_cfg.get("bot_token", ""))
    _ilink_bot_id = os.getenv("WX_ILINK_BOT_ID", wx_cfg.get("ilink_bot_id", ""))
    _ilink_user_id = os.getenv("WX_ILINK_USER_ID", wx_cfg.get("ilink_user_id", ""))


# ═══════════════════════════════════════════
# 请求工具
# ═══════════════════════════════════════════

def _random_uin() -> str:
    """生成随机 X-WECHAT-UIN"""
    raw = struct.pack("<I", random.randint(1, 0xFFFFFFFF))
    return base64.b64encode(raw).decode()


def _headers() -> dict:
    h = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": _random_uin(),
    }
    if _bot_token:
        h["Authorization"] = f"Bearer {_bot_token}"
    return h


def _get(endpoint: str, params: dict = None) -> dict:
    try:
        r = requests.get(f"{_base_url}{endpoint}", headers=_headers(),
                         params=params or {}, timeout=30)
        return r.json() if r.text else {"error": "empty response"}
    except Exception as e:
        return {"error": str(e)}


def _post(endpoint: str, data: dict = None, timeout: int = 30) -> dict:
    body = {"base_info": {"channel_version": "2.0.0"}}
    if data:
        body.update(data)
    try:
        r = requests.post(f"{_base_url}{endpoint}", headers=_headers(),
                          json=body, timeout=timeout)
        if r.text:
            try:
                return r.json()
            except Exception:
                return {"error": f"json parse: {r.text[:100]}"}
        return {"ret": 0, "msgs": []}  # 空响应 = 无消息
    except requests.exceptions.Timeout:
        return {"ret": 0, "msgs": []}  # 长轮询超时 = 无新消息
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════
# 登录
# ═══════════════════════════════════════════

def _save_creds():
    """将凭证持久化到单独的文件（不污染 config.json）"""
    creds_path = "data/wx_creds.json"
    try:
        os.makedirs(os.path.dirname(creds_path), exist_ok=True)
        with open(creds_path, "w", encoding="utf-8") as f:
            json.dump({
                "bot_token": _bot_token,
                "ilink_bot_id": _ilink_bot_id,
                "ilink_user_id": _ilink_user_id,
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[微信] 保存凭证失败: {e}")


def _load_creds() -> bool:
    """从持久化文件加载凭证"""
    creds_path = "data/wx_creds.json"
    if os.path.exists(creds_path):
        try:
            with open(creds_path, "r", encoding="utf-8") as f:
                creds = json.load(f)
            global _bot_token, _ilink_bot_id, _ilink_user_id
            _bot_token = creds.get("bot_token", _bot_token)
            _ilink_bot_id = creds.get("ilink_bot_id", _ilink_bot_id)
            _ilink_user_id = creds.get("ilink_user_id", _ilink_user_id)
        except Exception as e:
            print(f"[微信] 读取凭证失败: {e}")
    return bool(_bot_token)


def check_login() -> bool:
    """检查是否有有效 token（快速本地检测，实际验证在首次 poll 时进行）"""
    return bool(_bot_token)


def login_qrcode() -> str:
    """获取登录二维码 → 浏览器打开扫码链接
    返回 qrcode 标识（用于轮询状态）
    """
    r = _get("/ilink/bot/get_bot_qrcode", {"bot_type": "3"})
    if r.get("ret") != 0:
        print(f"[微信] 获取二维码失败: {r}")
        return ""

    qr_id = r.get("qrcode", "")           # 轮询用的标识
    qr_url = r.get("qrcode_img_content", "")  # 扫码链接

    if qr_url and qr_url.startswith("http"):
        print(f"[微信] 正在打开扫码页面...")
        import webbrowser
        webbrowser.open(qr_url)
        print(f"  如未自动打开，请手动访问:")
        print(f"  {qr_url}")
    elif qr_id:
        # fallback: 终端 ASCII 二维码
        print("[微信] 请在手机微信扫描以下二维码：")
        _print_terminal_qr(qr_id)

    return qr_id


def _print_terminal_qr(data: str):
    """终端 ASCII 二维码"""
    try:
        import qrcode
        qr = qrcode.QRCode(border=2)
        qr.add_data(data)
        qr.make()
        qr.print_ascii(invert=True)
    except ImportError:
        print(f"  (二维码数据: {data})")


def wait_login(timeout: int = 120) -> bool:
    """等待扫码登录
    返回 True 表示登录成功
    """
    global _bot_token, _ilink_bot_id, _ilink_user_id

    # 先尝试加载已有凭证
    if _load_creds():
        print("[微信] 发现已保存的登录凭证，尝试验证...")
        if check_login():
            print("[微信] 登录凭证有效，跳过扫码")
            return True
        else:
            print("[微信] 凭证已过期，重新扫码登录")
            _bot_token = ""
            _ilink_bot_id = ""
            _ilink_user_id = ""

    # 获取二维码
    for retry in range(3):
        qrcode_data = login_qrcode()
        if not qrcode_data:
            time.sleep(2)
            continue

        # 轮询扫码状态
        start = time.time()
        expired = False
        while time.time() - start < timeout:
            r = _get("/ilink/bot/get_qrcode_status", {"qrcode": qrcode_data})
            status = r.get("status", r.get("state", "wait"))

            if status in ("confirmed", "login"):
                _bot_token = r.get("bot_token", r.get("token", ""))
                _ilink_bot_id = r.get("ilink_bot_id", "")
                _ilink_user_id = r.get("ilink_user_id", "")
                if _bot_token:
                    _save_creds()
                    print("[微信] 登录成功！")
                    return True

            elif status == "expired":
                print("[微信] 二维码过期，重新获取...")
                expired = True
                break

            elif status == "scaned":
                print("[微信] 已扫码，请在手机上确认登录...")

            time.sleep(2)

        if expired:
            continue
        break

    print("[微信] 登录超时")
    return False


# ═══════════════════════════════════════════
# 消息轮询
# ═══════════════════════════════════════════

def get_updates() -> list:
    """长轮询获取新消息
    返回消息列表，每条格式: {"from_user": "wxid_xxx", "content": "文本", "context_token": "..."}
    """
    global _get_updates_buf
    data = {"get_updates_buf": _get_updates_buf}
    # 长轮询 40 秒超时（API 服务端 hold ~35 秒）
    r = _post("/ilink/bot/getupdates", data, timeout=40)

    if r.get("error"):
        # 网络/超时异常，静默重试
        return []

    if r.get("ret", 0) != 0:  # 默认 0，处理 {} 空响应
        if r.get("errcode") == -14 or r.get("ret") == -14:
            print("[微信] 会话过期，清除凭证并需重新登录")
            global _bot_token
            _bot_token = ""
            _get_updates_buf = ""
            _save_creds()
        return []

    # 更新游标
    new_buf = r.get("get_updates_buf", "")
    if new_buf:
        _get_updates_buf = new_buf

    # iLink 返回字段: msgs (列表), sync_buf
    messages = r.get("msgs", r.get("messages", r.get("data", [])))
    if not isinstance(messages, list):
        return []

    result = []
    for msg in messages:
        # iLink 字段: from_user_id, message_id, seq
        from_user = msg.get("from_user_id", msg.get("from_user", msg.get("userId", "")))
        content = msg.get("content", msg.get("text", msg.get("msg", "")))
        ctx_token = msg.get("context_token", "")

        if not content:
            # 尝试从 item_list 提取文本
            items = msg.get("item_list", [])
            for item in items:
                text_item = item.get("text_item", {})
                if text_item.get("text"):
                    content = text_item["text"]
                    break

        if from_user and content:
            if ctx_token:
                _user_context[from_user] = ctx_token
            result.append({"from_user": from_user, "content": content, "context_token": ctx_token})

    return result


# ═══════════════════════════════════════════
# 发送消息
# ═══════════════════════════════════════════

def send_message(to_user: str, text: str) -> dict:
    """发送文字消息（iLink 标准格式）"""
    ctx_token = _user_context.get(to_user, "")
    client_id = f"py-{random.randint(100000, 999999)}"
    msg = {
        "to_user_id": to_user,
        "client_id": client_id,
        "message_type": 2,       # 2 = Bot 发消息
        "message_state": 2,      # 2 = 完成
        "item_list": [{"type": 1, "text_item": {"text": text}}],
    }
    if ctx_token:
        msg["context_token"] = ctx_token
    return _post("/ilink/bot/sendmessage", {"msg": msg})


def send_typing(to_user: str, start: bool = True):
    """发送/停止「正在输入」状态"""# 先获取 typing_ticket
    cfg = _post("/ilink/bot/getconfig")
    typing_ticket = cfg.get("typing_ticket", "")
    if not typing_ticket:
        return
    _post("/ilink/bot/sendtyping", {
        "to_user": to_user,
        "status": 1 if start else 2,
        "typing_ticket": typing_ticket,
    })


# ═══════════════════════════════════════════
# 用户信息
# ═══════════════════════════════════════════

def get_self_info() -> dict:
    cfg = _post("/ilink/bot/getconfig")
    return {
        "bot_id": _ilink_bot_id,
        "nickname": cfg.get("nickname", cfg.get("name", "")),
        "avatar": cfg.get("avatar", ""),
    }


# ═══════════════════════════════════════════
# WxBot 高级封装
# ═══════════════════════════════════════════

class WxBot:
    """微信 Bot 高级封装"""
    def __init__(self, config_path: str = "config.json"):
        load_config(config_path)

    def poll_messages(self) -> list:
        """轮询获取新消息"""
        return get_updates()

    def reply(self, to_user: str, text: str) -> bool:
        """回复消息"""
        r = send_message(to_user, text)
        # iLink sendmessage 成功返回 {} 或 {\"ret\":0}，失败返回 {\"ret\":-2,...}
        return r.get("ret", 0) == 0  # 默认 0 因为 {} 表示成功

    def wait_login(self, timeout: int = 120) -> bool:
        """等待登录完成"""
        return wait_login(timeout)

    def send_typing(self, to_user: str, start: bool = True):
        """发送「正在输入」状态"""
        send_typing(to_user, start)
