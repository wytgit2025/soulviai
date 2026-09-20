# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""常驻服务联动：让各入口复用同一个引擎，避免多写者。

为什么需要
----------
引擎的 SQLite 是**单写者**模型 —— 两个进程同时写会撞 `database is locked`，
更麻烦的是心智状态会分叉（各自缓存一份、互相覆盖）。

所以除了常驻服务本身，其它入口（聊天渠道 / Web 终端 / CLI）都不该各自
`SoulEngine()`，而应把请求转发给已经在跑的那个常驻服务。

用法
----
    from core import daemon_link

    backend = daemon_link.get_backend()      # 拿不到返回 None
    if backend is not None:
        text = backend.chat("default_user", "在吗")     # 复用常驻服务
    else:
        text = engine.chat("default_user", "在吗")      # 回退本地引擎

`get_backend()` 的顺序：
  1. 端口上已有 soul-skill 常驻服务 → 直接连上（复用，不新建写者）
  2. 没有 → 就地拉起一个（后台常驻），再连上
  3. 拉不起来（无权限 / 端口被别的程序占用 / bridge 不存在）→ 返回 None，
     调用方回退本地引擎（行为与从前一致）

设 `SOUL_NO_DAEMON=1` 可强制走本地引擎，不走联动。

配置与 scripts/soulctl.py 保持同一套（同一份 config.yaml、同一个 token 文件）：
    daemon_host / daemon_port / daemon_token_file
    $SOUL_DAEMON_TOKEN / $SOUL_DAEMON_TOKEN_FILE 优先级更高
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

TOKEN_HEADER = "X-Soul-Token"
TOKEN_ENV = "SOUL_DAEMON_TOKEN"
TOKEN_ENV_FILE = "SOUL_DAEMON_TOKEN_FILE"
NO_DAEMON_ENV = "SOUL_NO_DAEMON"

SERVICE_NAME = "soul-skill"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

STARTUP_TIMEOUT = 60.0          # 拉起后等待就绪的上限（秒）
_CHAT_TIMEOUT = 300.0           # 对话要等大模型，给足


# ────────────────────────────────────────────────────────────
# 路径与配置
# ────────────────────────────────────────────────────────────
def runtime_root():
    """引擎目录（含 core/ 的那一层），即 engine/。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def skill_root():
    """技能根目录（engine/ 的上一级）。独立部署时可能不存在。"""
    return os.path.dirname(runtime_root())


def config_path():
    """config.yaml 位置：$SOUL_CONFIG > 技能根那份。

    优先级必须与 soulctl / engine_bridge / clients/web 一致。少了 $SOUL_CONFIG
    这一层，用户用备用配置改了 daemon_port 时，CLI 会连新端口，而聊天渠道仍
    固执地去探 8765 —— 两边都以为对方没起服务。
    """
    env = os.environ.get("SOUL_CONFIG")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    return os.path.join(skill_root(), "config.yaml")


def _strip_comment(raw):
    """去掉行尾注释。

    只把「行首或空白之后的 #」当注释，且引号内的 # 不算 —— 否则
    `daemon_token_file: /Volumes/a#b/token` 会被截成 `/Volumes/a`：
    路径静默变错，比直接报错难查得多。
    """
    quote = ""
    for i, ch in enumerate(raw):
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            continue
        if ch == "#" and (i == 0 or raw[i - 1] in " \t"):
            return raw[:i]
    return raw


def parse_flat_yaml(text):
    """极简 YAML：扁平 `key: value` + # 注释 + 引号字符串。

    语义基准是 scripts/soulctl.py 的同名函数（那边是启动器，本模块是引擎侧，
    两者必须能独立运行，所以各留一份实现）。**改这里就要同步改那边**，
    以及与它并列的 engine/clients/web.py:_flat_config。
    """
    cfg = {}
    for raw in text.splitlines():
        line = _strip_comment(raw).rstrip()
        if not line.strip() or ":" not in line:
            continue
        key, val = line.split(":", 1)
        key, val = key.strip(), val.strip()
        # 只有成对的引号才剥：`"it's"` 应得到 `it's`，
        # 贪心地 strip('"').strip("'") 会把它啃成 `its`。
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if val.lower() in ("true", "false"):
            cfg[key] = (val.lower() == "true")
        else:
            cfg[key] = val
    return cfg


def _read_cfg():
    """读 config.yaml（扁平 `key: value`，与 soulctl 同一份、同一语义）。"""
    try:
        with open(config_path(), "r", encoding="utf-8") as fh:
            return parse_flat_yaml(fh.read())
    except Exception:      # 配置坏了也要能降级跑
        return {}


def settings():
    """返回 (host, port, token_file)。"""
    cfg = _read_cfg()
    host = cfg.get("daemon_host") or DEFAULT_HOST
    try:
        port = int(cfg.get("daemon_port") or DEFAULT_PORT)
    except ValueError:
        port = DEFAULT_PORT
    path = (os.environ.get(TOKEN_ENV_FILE) or cfg.get("daemon_token_file") or ""
            or os.path.join(runtime_root(), ".soul-daemon.token"))
    return host, port, os.path.abspath(os.path.expanduser(path))


def read_token(token_file=None):
    """客户端 token：环境变量优先，其次读 token 文件。读不到返回空串。"""
    env = (os.environ.get(TOKEN_ENV) or "").strip()
    if env:
        return env
    try:
        with open(token_file or settings()[2], "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except Exception:
        return ""


# ────────────────────────────────────────────────────────────
# 探测
# ────────────────────────────────────────────────────────────
def _probe(host, port, token, timeout=2.0):
    """返回 (状态, 载荷)：`up` / `unauthorized` / `down`。

    只有自报 `service == soul-skill` 才认 —— 否则端口上跑的可能是
    完全不相干的程序，把它当成「我们的服务」会给出误导性的处置建议。
    """
    req = urllib.request.Request("http://%s:%d/health" % (host, port), method="GET")
    if token:
        req.add_header(TOKEN_HEADER, token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = 200
            body = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        code = exc.code
        try:
            body = json.loads(exc.read().decode("utf-8") or "{}")
        except Exception:
            body = {}
    except Exception:
        return "down", {}

    if body.get("service") != SERVICE_NAME:
        return "down", {}
    if code == 200:
        if body.get("auth_required") and "pid" not in body:
            return "unauthorized", body
        return "up", body
    if code == 401:
        return "unauthorized", body
    return "down", {}


# ────────────────────────────────────────────────────────────
# 轻客户端
# ────────────────────────────────────────────────────────────
class Backend(object):
    """常驻服务轻客户端。

    `chat()` 的签名与返回值刻意与 `SoulEngine.chat()` 对齐
    （空串＝没回，`__QUEUED__`＝已入队列），这样调用方可以无条件替换。
    """

    def __init__(self, host, port, token=""):
        self.host = host
        self.port = port
        self.token = token or ""
        self.base = "http://%s:%d" % (host, port)

    # ── 底层请求 ──
    def _call(self, method, path, payload=None, timeout=30.0):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header(TOKEN_HEADER, self.token)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                return json.loads(exc.read().decode("utf-8") or "{}")
            except Exception:
                return {"ok": False, "error": "HTTP %s" % exc.code}
        except Exception:
            return None

    # ── 对话（与 SoulEngine.chat 同语义）──
    def chat(self, user_id, message, env="", env_json=""):
        body = {"user_id": user_id, "text": message}
        if env:
            body["env"] = env
        if env_json:
            body["env_json"] = env_json
        res = self._call("POST", "/chat", body, timeout=_CHAT_TIMEOUT)
        if not res:
            return ""
        if not res.get("ok"):
            reason = res.get("error") or res.get("hint") or "未知原因"
            print("[联动] 常驻服务返回失败：%s" % str(reason)[:120])
            return ""
        status = res.get("status")
        if status == "silent":
            return ""
        if status == "queued":
            return "__QUEUED__"
        parts = res.get("parts")
        if parts:
            return "\n".join(parts)
        return res.get("text") or ""

    # ── 其它查询 ──
    def health(self, timeout=3.0):
        return self._call("GET", "/health", timeout=timeout)

    def state(self, user_id):
        return self._call("GET", "/state?user_id=%s" % user_id, timeout=60.0)

    def pending(self, user_id, limit=10):
        return self._call("GET", "/pending?user_id=%s&limit=%d" % (user_id, limit),
                          timeout=15.0)

    def pending_count(self, user_id):
        res = self.pending(user_id, limit=1) or {}
        try:
            return int(res.get("count") or 0)
        except (TypeError, ValueError):
            return 0

    def drain(self, user_id, limit=5, ack=True):
        return self._call("POST", "/drain",
                          {"user_id": user_id, "limit": limit, "ack": ack},
                          timeout=30.0)

    def ack(self, ids, user_id="default_user"):
        """把指定消息标记为已送达，返回确认条数。

        配对用法：`ack=False` 的 `drain_messages()` 只取不改，调用方投递成功后
        再用本方法确认。这样「延迟还没到」「发送失败」的消息会留在队列里，
        不会像 `ack=True` 那样一取走就丢。
        """
        ids = [i for i in (ids or []) if i is not None]
        if not ids:
            return 0
        res = self._call("POST", "/ack", {"user_id": user_id, "ids": ids},
                         timeout=15.0) or {}
        try:
            return int(res.get("acked") or 0)
        except (TypeError, ValueError):
            return 0

    def drain_messages(self, user_id, limit=5, ack=True):
        """取出待发消息，返回列表 [{id, msg_type, content, text, parts, ...}, ...]。

        常驻服务把列表放在 `messages` 键下（旧版可能叫 `items`），这里统一；
        并补一个 `content` 别名 —— 本地模式读库拿到的字段是 `content`，
        调用方（CLI / 渠道）按那个名字取，这里对齐以免两边写法分叉。
        """
        res = self.drain(user_id, limit=limit, ack=ack) or {}
        out = []
        for row in (res.get("messages") or res.get("items") or []):
            item = dict(row)
            item.setdefault("content", row.get("text") or "")
            out.append(item)
        return out

    def tick(self, user_id):
        return self._call("POST", "/tick", {"user_id": user_id}, timeout=180.0)

    def init(self, user_id):
        return self._call("POST", "/init", {"user_id": user_id}, timeout=90.0)


# ────────────────────────────────────────────────────────────
# 拉起
# ────────────────────────────────────────────────────────────
def _spawn_kwargs():
    """与 soulctl 一致的「脱离父进程」参数（Windows 上避免弹黑框）。"""
    if os.name != "nt":
        return {"start_new_session": True}
    flags = 0
    for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP",
                 "CREATE_NO_WINDOW"):
        flags |= getattr(subprocess, name, 0)
    return {"creationflags": flags}


def spawn(timeout=STARTUP_TIMEOUT):
    """后台拉起常驻服务，成功返回 Backend，否则 None。"""
    host, port, token_file = settings()
    bridge = os.path.join(skill_root(), "scripts", "engine_bridge.py")
    if not os.path.isfile(bridge):
        return None

    argv = [sys.executable, bridge, "serve",
            "--host", host, "--port", str(port), "--token-file", token_file]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop(NO_DAEMON_ENV, None)          # 别把这个开关传给子进程
    log_path = os.path.join(runtime_root(), ".soul-daemon.log")

    print("[联动] 未发现常驻服务，正在后台拉起（复用同一个引擎）...")
    try:
        with open(log_path, "ab") as log:
            proc = subprocess.Popen(argv, cwd=runtime_root(), env=env,
                                    stdout=log, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, **_spawn_kwargs())
    except Exception as exc:
        print("[联动] 拉起失败：%s" % exc)
        return None

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1.0)
        state, _health = _probe(host, port, read_token(token_file), timeout=2.0)
        if state == "up":
            print("[联动] 常驻服务就绪 http://%s:%d (pid=%s)" % (host, port, proc.pid))
            return Backend(host, port, read_token(token_file))
        if proc.poll() is not None:
            print("[联动] 常驻服务启动即退出，详见 %s" % log_path)
            return None
    print("[联动] 等待常驻服务就绪超时，退回本地引擎")
    return None


# ────────────────────────────────────────────────────────────
# 对外入口
# ────────────────────────────────────────────────────────────
def get_backend(auto_spawn=True):
    """拿到可用的常驻服务客户端；拿不到返回 None（调用方回退本地引擎）。

    auto_spawn=False 时只探测、不拉起。
    """
    if os.environ.get(NO_DAEMON_ENV):
        return None
    host, port, token_file = settings()
    token = read_token(token_file)
    state, _health = _probe(host, port, token)
    if state == "up":
        return Backend(host, port, token)
    if state == "unauthorized":
        # 端口上有 soul-skill，但 token 对不上：多半是另一份副本在跑。
        # 这里**不能**回退本地 —— 否则会开出第二个写者撞库。
        print("[联动] 端口 %d 上已有 soul-skill 常驻服务，但本机 token 不匹配。" % port)
        print("[联动] 可能是另一份副本在跑；先停掉它，或对齐 %s 环境变量。" % TOKEN_ENV)
        return None
    if not auto_spawn:
        return None
    return spawn()


if __name__ == "__main__":
    # 自检：python3 -m core.daemon_link
    b = get_backend()
    if b is None:
        print("常驻服务不可用")
        raise SystemExit(1)
    info = b.health() or {}
    print("service :", info.get("service"))
    print("pid     :", info.get("pid"))
    print("project :", info.get("project"))
    print("autonomous :", info.get("autonomous"))
    print("suspended  :", info.get("suspended_reason"))
