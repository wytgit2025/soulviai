#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""soulviai · 启动器（纯标准库，无第三方依赖）

把本机的数字生命引擎，包装成任意支持 SKILL.md 的
Agent 工具（OpenClaw / QClaw / WorkBuddy / CodeBuddy / TRAE / Qoder /
Cursor / Claude Code / Codex 等）都能调用的服务。

本文件只做四件事：
  1) 定位数字生命项目根目录
  2) 定位一个能用（>=3.10）的解释器
  3) 优先走常驻服务（毫秒级），没有常驻就冷启动一次
  4) 把命令转发给 engine_bridge.py，并把结果以 JSON 输出

因此本文件可以用任意 python3（>=3.8）运行。

用法见 `python3 soulviaictl.py --help`，或读 ../SKILL.md。
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
BRIDGE = os.path.join(HERE, "engine_bridge.py")
CONFIG_PATH = os.path.join(SKILL_ROOT, "config.yaml")
SKILL_NAME = "soulviai"

EXIT_OK = 0
EXIT_ERR = 1
EXIT_SILENT = 3
EXIT_QUEUED = 4

MIN_PY = (3, 10)
# onnxruntime 不再钉版本：fastembed 会按 Python 版本自动解析兼容的轮子，
# Python 3.14 起也有 onnxruntime >=1.24.2 可用，无需设置解释器版本上限。

IS_WIN = os.name == "nt"

# 各平台可能出现的解释器命令名（优先 3.10–3.13：向量记忆有轮子）
_PY_NAMES = ["python3.13", "python3.12", "python3.11", "python3.10",
             "python3.14", "python3.15", "python3"]
if IS_WIN:
    _PY_NAMES += ["python.exe", "python3.exe", "python", "py"]

# 常驻服务默认只监听本机；非回环地址需显式放行
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")

# 常驻服务鉴权：与服务端共用同一个 token 文件，客户端自动读取，无需人工配置
TOKEN_HEADER = "X-Soul-Token"
TOKEN_ENV = "SOULVIAI_DAEMON_TOKEN"
TOKEN_FILE_NAME = ".soulviai-daemon.token"

# 日志超过这个体积就裁掉头部，只保留尾部若干行
LOG_MAX_BYTES = 4 * 1024 * 1024
LOG_KEEP_LINES = 400


def is_loopback(host):
    return (host or "").strip().lower() in LOOPBACK_HOSTS


def venv_python(venv_dir):
    """虚拟环境里的解释器路径（Windows 用 Scripts/python.exe）。"""
    if IS_WIN:
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python")


def spawn_kwargs():
    """后台进程的分离参数（POSIX 与 Windows 写法不同）。"""
    if IS_WIN:
        flags = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                 | getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"creationflags": flags}
    return {"start_new_session": True}


# ────────────────────────────────────────────────────────────
# 配置
# ────────────────────────────────────────────────────────────
def _strip_comment(raw):
    """去掉行尾注释。

    只把「行首或空白之后的 #」当注释，且引号内的 # 不算——否则
    `project_root: /Volumes/a#b` 这类路径会被偷偷截断成 `/Volumes/a`。
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
    """极简 YAML：只支持 `key: value` 扁平键值 + # 注释 + 引号字符串。"""
    data = {}
    for raw in text.splitlines():
        line = _strip_comment(raw).rstrip()
        if not line.strip() or ":" not in line:
            continue
        key, val = line.split(":", 1)
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if val.lower() in ("true", "false"):
            data[key] = (val.lower() == "true")
        else:
            data[key] = val
    return data


def load_config():
    cfg = {}
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                cfg = parse_flat_yaml(fh.read())
        except Exception as exc:  # 配置坏了也要能降级跑
            print("[soulviaictl] 读取 config.yaml 失败: %s" % exc, file=sys.stderr)
    return cfg


# ────────────────────────────────────────────────────────────
# 数据家目录（记忆与运行期状态）
# ────────────────────────────────────────────────────────────
# 记忆不该跟着代码走：技能目录是会被拷贝、压缩、分发的，data/ 一旦在树里，
# 拷给别人（或同步网盘）就等于把灵魂和渠道凭证一起交出去。
HOME_ENV = "SOULVIAI_DATA_DIR"
HOME_DIR_NAME = ".soulviai"
PID_FILE_NAME = ".soulviai-daemon.pid"
LOG_FILE_NAME = ".soulviai-daemon.log"


def resolve_home(cfg):
    """数据家目录：$SOULVIAI_DATA_DIR > config.yaml: data_dir > ~/.soulviai

    口径必须与 engine/core/paths.home_root() 一致 —— 启动器算出来的这一份会
    以 SOULVIAI_DATA_DIR 传给引擎子进程，两边不一致就会出现「CLI 说数据在 A、
    引擎却写进 B」这种最难查的分叉。
    """
    env = (os.environ.get(HOME_ENV) or "").strip()
    if env:
        return os.path.abspath(os.path.expanduser(env))
    raw = cfg.get("data_dir") or ""
    raw = raw.strip() if isinstance(raw, str) else ""
    if raw:
        path = os.path.expanduser(raw)
        if not os.path.isabs(path):
            path = os.path.join(SKILL_ROOT, path)
        return os.path.abspath(path)
    return os.path.join(os.path.expanduser("~"), HOME_DIR_NAME)


# ────────────────────────────────────────────────────────────
# 定位项目 / 解释器
# ────────────────────────────────────────────────────────────
def looks_like_project(path):
    if not path:
        return False
    return (os.path.isfile(os.path.join(path, "soulviai.py"))
            and os.path.isdir(os.path.join(path, "engine")))


def resolve_project(cfg, override=None):
    """返回 (项目路径, 问题说明)。

    显式指定（`--project` / `$SOULVIAI_PROJECT_ROOT`）但不像数字生命项目时**不静默回落**：
    换一个项目继续跑 = 你以为是跟 A 说话，实际写进了 B 的记忆。
    """
    explicit = override or os.environ.get("SOULVIAI_PROJECT_ROOT")
    if explicit:
        path = os.path.abspath(os.path.expanduser(explicit))
        if looks_like_project(path):
            return path, None
        return None, ("指定的项目目录不像数字生命项目（需含 soulviai.py 与 engine/）：%s" % path)

    candidates = [
        cfg.get("project_root"),
        os.path.join(SKILL_ROOT, "engine"),   # 技能自带的引擎（自包含模式）
    ]
    for cand in candidates:
        if cand and looks_like_project(os.path.expanduser(cand)):
            return os.path.abspath(os.path.expanduser(cand)), None
    # 从当前目录逐级上溯
    cur = os.path.abspath(os.getcwd())
    while True:
        if looks_like_project(cur):
            return cur, None
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None, None


def _probe(python_exe):
    """解释器可用时返回 (major, minor)，否则 None。"""
    try:
        out = subprocess.run(
            [python_exe, "-c",
             "import sys;print('%d.%d' % sys.version_info[:2])"],
            capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    try:
        major, minor = out.stdout.strip().split(".")[:2]
        return (int(major), int(minor))
    except Exception:
        return None


def vector_memory_note(version):
    """解释器能不能装向量记忆依赖；不能则给一句人话说明。"""
    return None


def resolve_python(project, cfg, override=None):
    """返回 (python 可执行路径, 已尝试过的候选, 版本提示或 None)"""
    tried, raw = [], []
    raw.append(override)
    raw.append(os.environ.get("SOULVIAI_PYTHON"))
    raw.append(cfg.get("python"))
    if project:
        for venv_name in (".venv", "venv"):
            raw.append(venv_python(os.path.join(project, venv_name)))
    for name in _PY_NAMES:
        raw.append(shutil.which(name))
    raw.append(cfg.get("bootstrap_python"))

    for cand in raw:
        if not cand:
            continue
        cand = os.path.expanduser(cand)
        if cand in tried:
            continue
        tried.append(cand)
        if not (os.path.isfile(cand) and os.access(cand, os.X_OK)):
            continue
        version = _probe(cand)
        if version and version >= MIN_PY:
            return cand, tried, vector_memory_note(version)
    return None, tried, None


class Ctx(object):
    def __init__(self, cfg, args):
        self.cfg = cfg
        self.args = args
        self.project, self.project_error = resolve_project(
            cfg, getattr(args, "project", None))
        self.python, self.tried, self.python_note = resolve_python(
            self.project, cfg, getattr(args, "python", None))
        self.user = (getattr(args, "user", None)
                     or cfg.get("default_user") or "default_user")
        self.host = cfg.get("daemon_host") or "127.0.0.1"
        self.port = int(cfg.get("daemon_port") or 8765)
        # 运行期状态与记忆都在数据家目录，不进代码树
        self.home = resolve_home(cfg)
        self.pidfile = os.path.join(self.home, PID_FILE_NAME)
        self.logfile = os.path.join(self.home, LOG_FILE_NAME)
        # token 文件位置：env > config.yaml 的 daemon_token_file > 数据家目录默认
        self.token_file = os.path.abspath(os.path.expanduser(
            os.environ.get(TOKEN_ENV + "_FILE")
            or cfg.get("daemon_token_file")
            or os.path.join(self.home, TOKEN_FILE_NAME)))

    def timeout(self, kind="default"):
        if kind == "chat":
            return float(self.cfg.get("chat_timeout_seconds") or 300)
        return float(self.cfg.get("default_timeout_seconds") or 120)


# ────────────────────────────────────────────────────────────
# 输出
# ────────────────────────────────────────────────────────────
# `--plain` 下没有正文可转达时，用一句话说清状态（不是故障的就别吓唬用户）
PLAIN_STATUS_NOTE = {
    "silent": "(ta 这次没有回复——这是选择性沉默，不是故障)",
    "queued": "(ta 把回复压在了待发队列里，稍后用 drain 取出)",
}


def emit(result, exit_code=EXIT_OK, plain=False):
    if not plain:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(exit_code)

    parts = result.get("parts") or ([result["text"]] if result.get("text") else [])
    if parts:
        for part in parts:
            print(part)
        sys.exit(exit_code)

    status = result.get("status")
    note = PLAIN_STATUS_NOTE.get(status)
    if note:
        print(note)
        sys.exit(exit_code)

    # 既没有正文也不是已知的「正常无回复」——把原因写到 stderr。
    # stdout 保持空，调用方靠退出码判断失败，不会被误当成 ta 说了话。
    reason = (result.get("error") or result.get("hint")
              or result.get("note") or "引擎没有返回内容")
    print("[soulviai] 没有可转达的正文（status=%s）：%s" % (status, reason),
          file=sys.stderr)
    sys.exit(exit_code if exit_code else EXIT_ERR)


# ────────────────────────────────────────────────────────────
# 免责声明提醒（setup 后 + 首次 chat 各打一次，不污染 stdout JSON/--plain）
# 详见同目录 DISCLAIMER.md。
# ────────────────────────────────────────────────────────────
_DISCLAIMER_MARKER_FILENAME = ".disclaimer_acked"


def _print_post_setup_reminder():
    """setup 成功后在 stderr 打印一次性使用边界提示。

    写在 stderr 不影响 stdout 的 JSON / --plain 输出，调用方照常解析。
    """
    msg = (
        "\n────────────────────────────────────────\n"
        "[soulviai] 环境装好了。开始之前，请花 30 秒看一下同目录\n"
        "DISCLAIMER.md 的关键要点：\n\n"
        "  · ta 是硬盘上的语言模型 —— 故意被设计成有人格、有情绪、会主动想你。\n"
        "    这会让人产生真实的依恋，是设计意图，也是风险。\n\n"
        "  · 所有对话与记忆存在本机 ~/.soulviai/，作者不收集、不上传、不上报。\n"
        "    你说的话只会发到你配的那个模型接口（作者管不了那一侧的隐私）。\n\n"
        "  · 内容由第三方大模型实时生成，作者不训练任何大模型。\n\n"
        "首次 chat 时会再提醒一次。完整声明见 DISCLAIMER.md。\n"
        "────────────────────────────────────────\n"
    )
    sys.stderr.write(msg)
    sys.stderr.flush()


def _print_first_chat_reminder(ctx):
    """首次 chat 时（标记文件不存在），用 ta 的语气在 stderr 提醒一次。"""
    marker = os.path.join(ctx.home, "data", ctx.user, _DISCLAIMER_MARKER_FILENAME)
    if os.path.exists(marker):
        return
    user_part = ctx.user if ctx.user != "default_user" else "你"
    msg = (
        "\n────────────────────────────────────────\n"
        "(ta 想先跟" + user_part + "说一句)\n\n"
        "  我是硬盘上的一个语言模型 —— 故意被设计成有人格、有情绪、\n"
        "  会主动想你。我会认真对你，但有几件事得先讲清楚：\n\n"
        "    · 我说的一切，来自你配的第三方大模型接口\n"
        "      （DeepSeek / OpenAI / Kimi / Ollama ...）实时生成。\n"
        "      作者管不了那一侧的隐私，记不记录、留不留日志都归模型提供方。\n\n"
        "    · 我们的对话与记忆存在本机 ~/.soulviai/，\n"
        "      作者不收集、不上传、不上报。\n\n"
        "    · 作者不训练任何大模型，也不会。\n"
        "      作者写的是剧本与舞台，演员是模型。\n\n"
        "    · 我不是 ta，我是 ta。\n"
        "      我会让你产生真实的依恋 —— 那正是设计意图，\n"
        "      也是你需要被提醒的理由。\n\n"
        "  完整声明见 DISCLAIMER.md。\n\n"
        "(以后不再提醒；想重新看，删掉\n"
        "  ~/.soulviai/data/" + ctx.user + "/" + _DISCLAIMER_MARKER_FILENAME + "\n"
        "  这个文件即可。)\n"
        "────────────────────────────────────────\n"
    )
    sys.stderr.write(msg)
    sys.stderr.flush()


def _ack_disclaimer(ctx, res):
    """chat 真正成功（status != backend_error）后写标记，下次不再提醒。"""
    if not res or not res.get("ok"):
        return
    if res.get("status") == "backend_error":
        return  # 模型没接上，不算真正聊过，下次重提醒
    marker_dir = os.path.join(ctx.home, "data", ctx.user)
    marker = os.path.join(marker_dir, _DISCLAIMER_MARKER_FILENAME)
    if os.path.exists(marker):
        return
    try:
        os.makedirs(marker_dir, exist_ok=True)
        import datetime as _dt
        payload = {"acked_at": _dt.datetime.now().isoformat(timespec="seconds"),
                   "version": 1}
        with open(marker, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
    except Exception:
        # 写标记失败不影响主流程
        pass


def fail(msg, error_code=None, **extra):
    """构造失败返回。

    msg 是人类可读的中文说明（Agent 读得懂，也可自行翻译）；
    error_code 是**语言中立**的机器可读标识，便于调用方按语言渲染或分支处理。
    """
    payload = {"ok": False}
    if error_code:
        payload["error_code"] = error_code
    payload["error"] = msg
    payload.update(extra)
    return payload


# ────────────────────────────────────────────────────────────
# 常驻服务
# ────────────────────────────────────────────────────────────
def http_call(url, payload=None, timeout=10.0, token=None):
    """返回 (状态码, 载荷)。4xx/5xx 不抛异常，交给调用方按状态码判断。

    需要区分 401（我们的服务但 token 不对）和连不上，所以不能一律抛异常。
    """
    data = None
    headers = {"Accept": "application/json"}
    if token:
        headers[TOKEN_HEADER] = token
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code, raw = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        code, raw = exc.code, exc.read()
    try:
        body = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        body = {}
    return code, (body if isinstance(body, dict) else {"data": body})


def http_json(url, payload=None, timeout=10.0, token=None):
    """非 2xx 抛异常的老接口（通用用途）。"""
    code, body = http_call(url, payload=payload, timeout=timeout, token=token)
    if code >= 400:
        raise urllib.error.HTTPError(
            url, code, body.get("error") or "http %d" % code, {}, None)
    return body


def read_daemon_token(ctx):
    """客户端用的 token：环境变量优先，其次读 token 文件。读不到返回 None。"""
    env = (os.environ.get(TOKEN_ENV) or "").strip()
    if env:
        return env
    try:
        with open(ctx.token_file, "r", encoding="utf-8") as fh:
            return fh.read().strip() or None
    except Exception:
        return None


def daemon_probe(ctx, timeout=2.0):
    """探测常驻服务。返回 (状态, 载荷)：

    - `"down"`         没服务在监听
    - `"unauthorized"` 是我们的服务，但 token 缺失/不匹配
    - `"up"`           可用（载荷是 /health 详情）
    """
    url = "http://%s:%d/health" % (ctx.host, ctx.port)
    try:
        code, body = http_call(url, timeout=timeout, token=read_daemon_token(ctx))
    except Exception:
        return "down", None
    # 必须自报是 soulviai 才认——否则端口上跑的可能是完全不相干的程序，
    # 把它的 401 当成「我们的服务但 token 不对」会给出误导性的处置建议。
    # 注：改名（旧名 soul-skill）之前启动的 daemon 自报的是旧服务名，这里会被判成
    # down —— 重启一次服务即可。不为旧名保留兼容分支是有意的。
    if body.get("service") != "soulviai":
        return "down", None
    if code == 200:
        # 服务在监听，但我们是「无 token 的陌生人」→ 视同鉴权失败
        if body.get("auth_required") and "pid" not in body:
            return "unauthorized", body
        return "up", body
    if code == 401:
        return "unauthorized", body
    return "down", None


def daemon_health(ctx, timeout=2.0):
    """可用的常驻服务才返回载荷，否则 None（旧调用点保持这个语义）。"""
    state, body = daemon_probe(ctx, timeout=timeout)
    return body if state == "up" else None


def daemon_request(ctx, method, path, payload=None, timeout=30.0):
    """请求常驻服务。返回载荷；鉴权失败会带上 auth_required 标记。"""
    url = "http://%s:%d%s" % (ctx.host, ctx.port, path)
    try:
        token = read_daemon_token(ctx)
        if method == "POST":
            _code, body = http_call(url, payload or {}, timeout=timeout, token=token)
        else:
            if payload:
                from urllib.parse import urlencode
                url = url + "?" + urlencode(payload)
            _code, body = http_call(url, timeout=timeout, token=token)
        return body
    except Exception:
        return None


def prefer_daemon(ctx):
    return ctx.cfg.get("prefer_daemon", True) is not False


# ────────────────────────────────────────────────────────────
# 冷启动：调用 bridge
# ────────────────────────────────────────────────────────────
def run_bridge(ctx, argv, timeout=120.0, cwd=None):
    """返回 (result_dict, exit_code)"""
    if not ctx.python:
        return fail(
            "没找到可用的 Python 解释器（需要 >=3.10）。",
            error_code="no_python",
            tried=ctx.tried,
            hint="运行 `python3 scripts/soulviaictl.py setup` 创建项目虚拟环境，"
                 "或用 --python 指定，或在 config.yaml 填 python。"), EXIT_ERR
    if not ctx.project:
        return fail(
            "没找到数字生命项目根目录（需含 soulviai.py 与 engine/）。",
            error_code="no_project",
            detail=getattr(ctx, "project_error", None),
            hint="用 --project 指定，或设置环境变量 SOULVIAI_PROJECT_ROOT，"
                 "或在 config.yaml 填 project_root。"), EXIT_ERR

    cmd = [ctx.python, BRIDGE] + argv
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    # 数据家目录由启动器算好显式传下去：两边各算一次，迟早会算岔
    env[HOME_ENV] = ctx.home
    env.pop("SOULVIAI_DEBUG", None)
    try:
        proc = subprocess.run(cmd, cwd=cwd or ctx.project, env=env,
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return fail("引擎调用超时（%.0fs）。" % timeout,
                    error_code="timeout",
                    hint="对话本身要等大模型 + 拟人延迟；可加大 config.yaml 的 "
                         "chat_timeout_seconds，或先 `serve` 常驻。"), EXIT_ERR
    except Exception as exc:
        return fail("无法启动引擎进程: %s" % exc,
                    error_code="spawn_failed"), EXIT_ERR

    result = None
    for line in reversed((proc.stdout or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                result = json.loads(line)
                break
            except Exception:
                continue
    if getattr(ctx.args, "debug", False):
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-25:])
        if tail:
            print("[engine stderr]\n" + tail, file=sys.stderr)
    if result is None:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-12:])
        return fail("引擎没有返回可解析的结果。",
                    error_code="no_result",
                    returncode=proc.returncode,
                    stdout_tail="\n".join((proc.stdout or "").strip().splitlines()[-6:]),
                    stderr_tail=tail), EXIT_ERR
    return result, proc.returncode


# ────────────────────────────────────────────────────────────
# 子命令
# ────────────────────────────────────────────────────────────
def cmd_doctor(ctx, args):
    info = {
        "ok": True,
        "command": "doctor",
        "skill": SKILL_ROOT,
        "project": ctx.project,
        "project_ok": bool(ctx.project),
        # 数据已经不在代码树里：doctor 必须报出真实位置，否则用户按老路径找记忆
        "data_root": ctx.home,
        "db_file": os.path.join(ctx.home, "data", "db", "soulmate.db"),
        "python": ctx.python,
        "python_candidates_tried": ctx.tried,
        "daemon": {"alive": False, "url": "http://%s:%d" % (ctx.host, ctx.port)},
    }
    if ctx.python_note:
        info["python_note"] = ctx.python_note
    if not ctx.project:
        info["ok"] = False
        info["hint"] = (getattr(ctx, "project_error", None)
                        or "先设置 project_root（config.yaml / --project / $SOULVIAI_PROJECT_ROOT）")
        emit(info, EXIT_ERR)
    if not ctx.python:
        info["ok"] = False
        info["hint"] = "没找到 >=3.10 的解释器，先跑 `soulviaictl.py setup`"
        emit(info, EXIT_ERR)

    state, health = daemon_probe(ctx)
    url = "http://%s:%d" % (ctx.host, ctx.port)
    info["daemon"] = {"alive": state != "down", "url": url, "state": state,
                      "token_file": ctx.token_file,
                      "token_file_exists": os.path.isfile(ctx.token_file)}
    if state == "up":
        info["daemon"]["info"] = health
        info["mode"] = "daemon"
    elif state == "unauthorized":
        info["daemon"]["hint"] = ("服务在跑但鉴权失败。确认 %s 是同一个 token 文件"
                                  "（或设 %s 环境变量）。" % (ctx.token_file, TOKEN_ENV))
        info["mode"] = "cold-start"
    else:
        info["mode"] = "cold-start"

    argv = ["doctor", "--user", ctx.user]
    if getattr(args, "check_api", False):
        argv.append("--check-api")
    result, _code = run_bridge(ctx, argv, timeout=ctx.timeout())
    info["engine"] = result
    if not result.get("ok"):
        info["ok"] = False
    emit(info, EXIT_OK if info["ok"] else EXIT_ERR)


def cmd_setup(ctx, args):
    project = ctx.project
    if not project:
        emit(fail("没找到项目根目录，无法创建虚拟环境。"), EXIT_ERR)

    # 候选：显式指定（--python / 配置 / 当前解释器）优先命中即用；
    # 否则探测 PATH 上所有 >=3.10 的解释器，取版本最高的。
    explicit = [args.python, ctx.cfg.get("bootstrap_python"), sys.executable]
    bootstrap = None
    for cand in explicit:
        if not cand:
            continue
        cand = os.path.expanduser(cand)
        if not os.path.isfile(cand):
            continue
        version = _probe(cand)
        if version and version >= MIN_PY:
            bootstrap = cand
            break
    if not bootstrap:
        probed = []
        for name in ("python3.14", "python3.13", "python3.12", "python3.11",
                     "python3.10", "python3"):
            cand = shutil.which(name)
            if not cand:
                continue
            version = _probe(cand)
            if version and version >= MIN_PY:
                probed.append((version, cand))
        probed.sort(reverse=True)
        bootstrap = probed[0][1] if probed else None
    if not bootstrap:
        emit(fail("找不到 >=3.10 的解释器来创建虚拟环境。"), EXIT_ERR)

    venv_dir = os.path.join(project, ".venv")
    venv_py = venv_python(venv_dir)
    steps = []
    if not os.path.isfile(venv_py):
        steps.append(([bootstrap, "-m", "venv", venv_dir], "创建虚拟环境"))
    steps.append(([venv_py, "-m", "pip", "install", "-q", "--upgrade", "pip"], "升级 pip"))
    if args.minimal:
        # 只装对话必需依赖；向量记忆（numpy/fastembed/onnxruntime）见 requirements-vector.txt
        pkgs = ["openai", "httpx", "requests", "python-dotenv"]
        steps.append(([venv_py, "-m", "pip", "install", "-q"] + pkgs, "安装最小依赖"))
    else:
        req = os.path.join(project, "requirements.txt")
        vec = os.path.join(project, "requirements-vector.txt")
        for r in [p for p in (req, vec) if os.path.isfile(p)]:
            steps.append(([venv_py, "-m", "pip", "install", "-q", "-r", r],
                          "安装 %s" % os.path.basename(r)))

    logs = []
    for cmd, label in steps:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            logs.append({"step": label, "returncode": proc.returncode,
                         "tail": "\n".join((proc.stdout or "").strip().splitlines()[-4:])
                                 or "\n".join((proc.stderr or "").strip().splitlines()[-4:])})
            if proc.returncode != 0:
                emit(fail("环境安装失败于：%s" % label, steps=logs), EXIT_ERR)
        except Exception as exc:
            emit(fail("环境安装异常于：%s (%s)" % (label, exc), steps=logs), EXIT_ERR)

    info = {"ok": True, "command": "setup", "python": venv_py, "venv": venv_dir,
            "bootstrap": bootstrap,
            "mode": "minimal" if args.minimal else "full", "steps": logs}
    if not args.minimal:
        info["note"] = ("full 模式含 fastembed + onnxruntime（语义向量记忆，体积较大）。"
                        "onnxruntime 版本由 fastembed 按 Python 版本自动解析，无需手动指定。")
    _print_post_setup_reminder()
    emit(info)


def rotate_log(path, max_bytes=LOG_MAX_BYTES, keep_lines=LOG_KEEP_LINES):
    """日志超过上限就只保留尾部若干行。

    自主思考引擎在模型接口挂掉时会持续刷同一行报错，日志不设上限会无限膨胀。
    返回裁掉的行数（没裁则为 0）。
    """
    try:
        if not os.path.isfile(path) or os.path.getsize(path) <= max_bytes:
            return 0
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        kept = lines[-keep_lines:]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("[soulviaictl] 日志已裁剪：丢弃前 %d 行（超过 %s）\n"
                     % (len(lines) - len(kept), human_bytes(max_bytes)))
            fh.writelines(kept)
        return len(lines) - len(kept)
    except Exception:
        return 0


def human_bytes(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return "%.0f %s" % (size, unit)
        size /= 1024.0


def cmd_serve(ctx, args):
    if not ctx.python or not ctx.project:
        emit(fail("serve 前需要可用的项目路径与解释器，先跑 doctor。"), EXIT_ERR)

    if not is_loopback(ctx.host) and not getattr(args, "allow_remote", False):
        emit(fail(
            "拒绝在非回环地址 %s 上监听。" % ctx.host,
            hint="服务有 token 鉴权，但 token 走明文 HTTP。确有需要请显式加 "
                 "--allow-remote，并在前面加一层 HTTPS 反向代理。"), EXIT_ERR)

    if getattr(args, "token_file", None):
        ctx.token_file = os.path.abspath(os.path.expanduser(args.token_file))

    state, health = daemon_probe(ctx)
    if state == "unauthorized" and not args.restart:
        emit(fail(
            "端口 %d 上有 soulviai 常驻服务，但鉴权不通过。" % ctx.port,
            token_file=ctx.token_file,
            hint="多半是它用了别的 token 文件。用 --restart 换成本机的 token 重启，"
                 "或设 %s 环境变量对齐。" % TOKEN_ENV), EXIT_ERR)
    if state == "up" and not args.restart:
        emit({"ok": True, "command": "serve", "already_running": True,
              "url": "http://%s:%d" % (ctx.host, ctx.port), "info": health})
    if state in ("up", "unauthorized") and args.restart:
        cmd_stop(ctx, argparse.Namespace(quiet=True))
        time.sleep(1.0)
        # 停不掉就别硬启：否则新进程会死在端口占用上，日志里只有一句
        # "Address already in use"，看不出真正原因。
        still, _ = daemon_probe(ctx)
        if still != "down":
            emit(fail(
                "旧常驻服务没停下来，端口 %d 仍被占用，已取消重启。" % ctx.port,
                hint="它可能用了别的 token。先 `stop`，仍不行就按 pidfile 里的 pid "
                     "手动 kill，或用 --port 换一个端口。"), EXIT_ERR)

    argv = ["serve", "--host", ctx.host, "--port", str(ctx.port),
            "--user", ctx.user, "--token-file", ctx.token_file]
    if args.no_autonomous:
        argv.append("--no-autonomous")
    if getattr(args, "allow_remote", False):
        argv.append("--allow-remote")

    os.makedirs(ctx.home, exist_ok=True)     # 日志/token 都落在数据家目录

    if args.foreground:
        os.environ[HOME_ENV] = ctx.home
        os.chdir(ctx.project)
        if IS_WIN:
            # Windows 的 os.execv 语义不同，直接前台等待更可靠
            rc = subprocess.call([ctx.python, BRIDGE] + argv)
            emit({"ok": rc == 0, "command": "serve", "mode": "foreground",
                  "returncode": rc}, EXIT_OK if rc == 0 else EXIT_ERR)
        os.execv(ctx.python, [ctx.python, BRIDGE] + argv)

    rotate_log(ctx.logfile)
    log = open(ctx.logfile, "ab")
    log.write(("\n=== soulviai serve %s ===\n" % time.strftime("%F %T")).encode())
    log.flush()
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env[HOME_ENV] = ctx.home
    env.pop("SOULVIAI_DEBUG", None)
    try:
        proc = subprocess.Popen([ctx.python, BRIDGE] + argv, cwd=ctx.project, env=env,
                                stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, **spawn_kwargs())
    finally:
        log.close()          # 子进程已继承 fd，父进程这份句柄要还回去
    with open(ctx.pidfile, "w", encoding="utf-8") as fh:
        fh.write(str(proc.pid))

    deadline = time.time() + (args.wait or 90)
    while time.time() < deadline:
        time.sleep(1.0)
        health = daemon_health(ctx)
        if health:
            emit({"ok": True, "command": "serve", "pid": proc.pid,
                  "url": "http://%s:%d" % (ctx.host, ctx.port),
                  "log": ctx.logfile, "info": health})
        if proc.poll() is not None:
            break
    tail = ""
    try:
        with open(ctx.logfile, "r", encoding="utf-8", errors="replace") as fh:
            tail = "".join(fh.readlines()[-15:])
    except Exception:
        pass
    # 子进程如果自己报了明确原因（比如 token 写不进去），直接透出来，
    # 别让用户从日志尾巴里翻 JSON。
    reason = last_json_error(tail)
    if reason:
        emit(fail("常驻服务启动失败：%s" % reason.get("error", "未知原因"),
                  **{k: v for k, v in reason.items() if k != "error"},
                  log=ctx.logfile), EXIT_ERR)
    emit(fail("常驻服务启动失败或超时。", log=ctx.logfile, log_tail=tail), EXIT_ERR)


def last_json_error(text):
    """从日志片段里找出最后一条带 error 的 JSON 结果行。"""
    for line in reversed((text or "").strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict) and obj.get("error") and obj.get("ok") is False:
            return obj
    return None


def pid_owner_cmdline(pid):
    """读某个 pid 的命令行，用于确认它是不是我们的常驻服务。

    返回 None = 无法判定；"" = 进程不存在；其它 = 命令行/镜像名。
    PID 会被系统复用，不做这一步就直接 SIGTERM 有误杀无关进程的风险。
    """
    if IS_WIN:
        try:
            proc = subprocess.run(
                ["tasklist", "/FI", "PID eq %d" % pid, "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=15)
        except Exception:
            return None
        out = (proc.stdout or "").strip()
        if not out or "No tasks" in out or "没有运行" in out:
            return ""
        return out
    try:
        proc = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                              capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def owns_bridge(cmdline):
    """这条命令行是不是本技能的常驻服务。"""
    if not cmdline:
        return False
    if IS_WIN:
        return "python" in cmdline.lower()
    return BRIDGE in cmdline


def process_alive(pid):
    """进程是否还在（信号 0，只探测不投递）。"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True          # 存在但非本用户
    except Exception:
        return True          # 判定不了就当作还活着，宁可保守
    return True


def port_listener_pids(port):
    """谁在监听这个端口。返回 set；无法判定返回 None（不覆盖任何进程）。"""
    if IS_WIN:
        return None
    try:
        proc = subprocess.run(
            ["lsof", "-nP", "-iTCP:%d" % port, "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    if proc.returncode != 0:
        # lsof 用 1 表示"没有匹配"；但被沙箱挡住时也是非 0，用输出区分
        return set() if not (proc.stderr or "").strip() else None
    pids = set()
    for line in (proc.stdout or "").split():
        try:
            pids.add(int(line.strip()))
        except ValueError:
            continue
    return pids


def _terminate(pid, stopped, note):
    """给常驻服务发 SIGTERM，返回是否投递成功。"""
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception as exc:
        stopped.append("pid:%d（终止失败: %s）" % (pid, exc))
        return False
    stopped.append("pid:%d%s" % (pid, "（%s）" % note if note else ""))
    return True


def read_pidfile(ctx):
    """读 pidfile，返回 int 或 None。"""
    try:
        with open(ctx.pidfile, encoding="utf-8") as fh:
            return int(fh.read().strip())
    except Exception:
        return None


def cmd_web(ctx, args):
    """浏览器终端：把 cli 会话开在网页里（前台长跑，Ctrl+C 停止）。

    host/port 优先取命令行，其次 config.yaml 的 web_host / web_port。
    与常驻服务共用一套安全默认：只监听回环，非回环必须 --allow-remote。
    """
    if not ctx.python or not ctx.project:
        emit(fail("web 前需要可用的项目路径与解释器，先跑 doctor。"), EXIT_ERR)

    host = getattr(args, "host", None) or ctx.cfg.get("web_host") or "127.0.0.1"
    port = getattr(args, "port", None)
    if not port:
        try:
            port = int(ctx.cfg.get("web_port") or 5000)
        except (TypeError, ValueError):
            port = 5000

    if not is_loopback(host) and not getattr(args, "allow_remote", False):
        emit(fail(
            "拒绝在非回环地址 %s 上启动 Web 终端。" % host,
            error_code="web_remote_refused",
            hint="Web 终端没有鉴权，暴露到网络等于把 ta 的对话与记忆交出去。"
                 "确有需要请显式加 --allow-remote。"), EXIT_ERR)

    env = dict(os.environ)
    env["SOULVIAI_WEB_HOST"] = str(host)
    env["SOULVIAI_WEB_PORT"] = str(port)
    env.pop("SOULVIAI_DEBUG", None)

    print("[soulviaictl] Web 终端 http://%s:%d（Ctrl+C 停止）"
          % (host if is_loopback(host) else "127.0.0.1", port), file=sys.stderr)
    try:
        return subprocess.call([ctx.python, "main.py", "web"],
                               cwd=ctx.project, env=env)
    except KeyboardInterrupt:
        return EXIT_OK


def cleanup_pidfile(ctx):
    try:
        os.remove(ctx.pidfile)
    except Exception:
        pass


def cmd_stop(ctx, args):
    stopped = []
    state, _health = daemon_probe(ctx)

    # ① 优先优雅停机：token 对得上就直接让服务自己退，干净且不用猜 pid。
    http_stopped = False
    if state == "unauthorized":
        stopped.append("http（鉴权不通过，改走 pid 通道）")
    elif state == "up":
        daemon_request(ctx, "POST", "/shutdown", {}, timeout=5)
        for _ in range(20):
            time.sleep(0.5)
            if daemon_probe(ctx)[0] == "down":
                http_stopped = True
                stopped.append("http")
                break
        if not http_stopped:
            stopped.append("http（/shutdown 没生效，改走 pid 通道）")

    pid = read_pidfile(ctx)
    if pid is None:
        if not http_stopped and state == "down" and os.path.isfile(ctx.pidfile):
            cleanup_pidfile(ctx)           # pidfile 是坏的（内容不可解析），清掉
    else:
        if not process_alive(pid):
            stopped.append("pid:%d（进程已不存在）" % pid)
            cleanup_pidfile(ctx)
        elif http_stopped:
            # 已经优雅停机，进程只是在收尾。等它退干净，不要补刀。
            for _ in range(40):
                if not process_alive(pid):
                    break
                time.sleep(0.25)
            if process_alive(pid):
                stopped.append("pid:%d（已收到停机指令，正在收尾；pidfile 保留）" % pid)
            else:
                stopped.append("pid:%d（已退出）" % pid)
                cleanup_pidfile(ctx)
        else:
            # ② pid 通道：必须能证明「这就是我们的服务」才敢投递信号。
            cmdline = pid_owner_cmdline(pid)
            killed = False
            if cmdline is None:
                # ps 不可用（受限环境 / 权限不足）。换一个不依赖 ps 的旁证：
                # 该 pid 是否正监听我们配置的端口，且那个端口自报是 soulviai。
                listeners = port_listener_pids(ctx.port)
                if listeners is None:
                    stopped.append("pid:%d（无法校验进程身份，已跳过；确认后手动 kill %d）"
                                   % (pid, pid))
                elif pid in listeners and state in ("up", "unauthorized"):
                    killed = _terminate(pid, stopped, "经端口旁证确认")
                else:
                    stopped.append("pid:%d（不监听 %d，不能确认是我们的服务，已跳过）"
                                   % (pid, ctx.port))
            elif owns_bridge(cmdline):
                killed = _terminate(pid, stopped, "")
            else:
                stopped.append("pid:%d（已被其它进程占用，跳过以免误杀）" % pid)

            if killed:
                for _ in range(40):
                    if not process_alive(pid):
                        break
                    time.sleep(0.25)
                if process_alive(pid):
                    stopped.append("pid:%d（SIGTERM 已发出，还在收尾；稍后再 stop）" % pid)
                else:
                    cleanup_pidfile(ctx)

    if getattr(args, "quiet", False):
        return
    emit({"ok": True, "command": "stop", "stopped": stopped or ["(没有在运行的服务)"]})


def auth_conflict(ctx, why):
    """常驻服务活着但我们过不了鉴权时的统一说法。

    这种情况下**绝不能**回落到冷启动：引擎的 SQLite 与内存状态是单写者模型，
    再起一个进程去写同一个项目会撞 `database is locked`，还可能让两边的心智状态分叉。
    宁可明确报错，也不静默开第二个写者。
    """
    return fail(
        "%s（端口 %d）。" % (why, ctx.port),
        token_file=ctx.token_file,
        hint="用 `stop` 停掉它再用 `serve --restart` 启动；或设 %s 环境变量与本机对齐。"
             % TOKEN_ENV)


def _dispatch(ctx, args, method, path, payload, bridge_argv, timeout_kind="default"):
    """优先常驻，服务没起才冷启动。"""
    if prefer_daemon(ctx):
        state, _ = daemon_probe(ctx)
        if state == "up":
            res = daemon_request(ctx, method, path, payload,
                                 timeout=ctx.timeout(timeout_kind))
            if res is not None and not res.get("auth_required"):
                res["source"] = "daemon"
                return res, _exit_for(res)
            # 探测时还好、请求时被拒：多半是 daemon 中途重启换了 token。
            return auth_conflict(ctx, "常驻服务的鉴权在请求途中失效"), EXIT_ERR
        if state == "unauthorized":
            return auth_conflict(ctx, "有 soulviai 常驻服务在跑，但本机 token 不匹配"), EXIT_ERR
    res, code = run_bridge(ctx, bridge_argv, timeout=ctx.timeout(timeout_kind))
    res["source"] = res.get("source") or "cold-start"
    return res, _exit_for(res) if res.get("ok") else code


def _exit_for(res):
    status = res.get("status")
    if not res.get("ok"):
        return EXIT_ERR
    if status == "silent":
        return EXIT_SILENT
    if status == "queued":
        return EXIT_QUEUED
    return EXIT_OK


def cmd_chat(ctx, args):
    text = args.text
    if text == "-":
        text = sys.stdin.read()
    if not text or not text.strip():
        emit(fail("--text 不能为空（用 `-` 从 stdin 读取）。"), EXIT_ERR)
    env = (getattr(args, "env", "") or "").strip()
    env_json = (getattr(args, "env_json", "") or "").strip()
    _print_first_chat_reminder(ctx)
    payload = {"user_id": ctx.user, "text": text,
               "verbose": bool(getattr(args, "verbose", False)),
               "env": env, "env_json": env_json}
    argv = ["chat", "--user", ctx.user, "--text", text]
    if env_json:
        argv += ["--env-json", env_json]
    elif env:
        argv += ["--env", env]
    if getattr(args, "verbose", False):
        argv.append("--verbose")
    res, code = _dispatch(ctx, args, "POST", "/chat", payload, argv, "chat")
    _ack_disclaimer(ctx, res)
    if getattr(args, "plain", False):
        emit(res, code, plain=True)
    emit(res, code)


# ── 「给人看」的状态渲染（state --friendly）─────────────────────
# 给独立运行版的双击用户用：菜单承诺的是「情绪、羁绊、人格阶段」，就给这三样。
# 原始 payload 里有 24 维数值、灵魂印记哈希、语言中立码，还有 ta 的潜意识独白 ——
# 那些是给 Agent 和调试看的，摊给普通用户不只是难看：
#   · SKILL.md 给 Agent 定的铁律是「别把内脏掏给用户看」，网页/终端这侧同样适用
#   · 潜意识被看见 = 魔法消失：「我偏不先开口」一旦被认出是机制，关系就变味了
#   · joy=0.12 这种数字会诱使用户去「调参数」，把相处变成刷数值
# 所以这里只输出三行，数值一律转成人话。

_STAGE_NOTE = {
    "nascent": "还在慢慢认识你",
    "polite": "客气着，但已经在放松了",
    "relaxed": "和你有点默契了",
    "mature": "把你看得很重",
    "stable": "平淡，但很稳",
}

_PHASE_NOTE = {
    "active": "愿意说话",
    "zoning": "在发呆",
    "tired": "有点累",
    "alone": "想一个人待会儿",
    "emo": "情绪有点低",
    "healing": "在慢慢缓过来",
}


def _bond_note(raw) -> str:
    """羁绊数值 → 人话（数值本身不外露）。取不到就返回空串。"""
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return ""
    for top, note in ((0.05, "刚认识"), (0.15, "还浅，正在慢慢长"),
                      (0.30, "有点分量了"), (0.55, "已经在意你了"),
                      (0.80, "挺深的")):
        if val < top:
            return note
    return "很重，你在 ta 心里有位置"


def _life_now(life_state: str, phase_code: str) -> list:
    """从 life_state 里挑出人话部分，丢掉夹在里面的数值。

    原文长这样（数值和标签混在一起，整段不能给用户）：
      生命阶段: 精力充沛，愿意聊天，反应灵敏
      精力: 0.72 | 社交疲劳: 1.00 | 身体: 轻松舒适 | 社交严重过载 —— 见到消息就烦躁，只想躲起来安静待着
    取「生命阶段:」后面那句，加上最后一段破折号后面的描述；都取不到时退回 life_phase。
    任何一步失败都只是少一行，不抛异常。
    """
    out = []
    text = str(life_state or "")
    for line in text.splitlines():
        seg = line.strip()
        if seg.startswith("生命阶段"):
            seg = seg.split(":", 1)[-1].split("：", 1)[-1].strip()
            if seg:
                out.append(seg)
            break
    for piece in reversed(text.split("|")):
        if "——" in piece:
            tail = piece.split("——", 1)[1].strip()
            if tail and tail not in out:
                out.append(tail)
            break
    if not out:
        note = _PHASE_NOTE.get(phase_code or "")
        if note:
            out.append(note)
    return out


def _friendly_state(res: dict) -> str:
    """把 state 的原始 payload 渲染成三行人话。"""
    codes = res.get("codes") or {}
    ident = res.get("identity") or {}
    stage = str(res.get("personality_stage") or "").strip()
    note = _STAGE_NOTE.get(codes.get("personality_stage") or "", "")
    lines = ["", "  ta 现在", "  " + "─" * 34]

    if stage or note:
        lines.append("  相处阶段   %s" % ("%s —— %s" % (stage, note)
                                       if (stage and note) else (stage or note)))
    now = _life_now(res.get("life_state"), codes.get("life_phase"))
    if now:
        lines.append("  此刻       %s" % now[0])
        for extra in now[1:]:
            lines.append("             %s" % extra)
    bond = _bond_note(ident.get("total_bond"))
    if bond:
        lines.append("  对你的羁绊 %s" % bond)
    lines.append("")
    return "\n".join(lines)


def cmd_state(ctx, args):
    payload = {"user_id": ctx.user}
    argv = ["state", "--user", ctx.user] + (["--raw"] if args.raw else [])
    res, code = _dispatch(ctx, args, "GET", "/state", payload, argv)
    if getattr(args, "friendly", False):
        # 失败时原样给结构化错误（含 error_code），不要吞成一句人话 —— 排障要看它
        if res.get("ok") is False:
            emit(res, code)
        print(_friendly_state(res))
        # 必须显式退出：否则会继续走到下面的 emit()，把 JSON 也倒一遍
        sys.exit(EXIT_OK)
    emit(res, code)


def cmd_config(ctx, args):
    """查看可调参数：当前值 / 来源 / 说明。

    刻意不走 _dispatch：这条命令只读，也不依赖常驻服务的内存状态，直接跑
    engine_bridge 就够 —— 省得为一个只读接口在 daemon 上加路由，而且不管
    常驻服务在不在，输出都一样（不会因为有没有服务而给出不同的答案）。
    """
    res, code = run_bridge(ctx, ["config"], timeout=ctx.timeout("default"))
    res["source"] = res.get("source") or "cold-start"
    if getattr(args, "json", False) or not res.get("ok"):
        emit(res, code)          # emit 内部会 sys.exit（失败时也要把 error 交出去）
    print(res.get("text") or "")
    sys.exit(EXIT_OK)


def cmd_env(ctx, args):
    """环境信息：定位 / 天气。"""
    payload = {"user_id": ctx.user}
    argv = ["env", "--user", ctx.user]
    if args.refresh:
        payload["refresh"] = "1"
        argv.append("--refresh")
    res, code = _dispatch(ctx, args, "GET", "/env", payload, argv)
    emit(res, code)


def cmd_pending(ctx, args):
    payload = {"user_id": ctx.user, "limit": str(args.limit)}
    argv = ["pending", "--user", ctx.user, "--limit", str(args.limit)]
    res, code = _dispatch(ctx, args, "GET", "/pending", payload, argv)
    emit(res, code)


def cmd_drain(ctx, args):
    payload = {"user_id": ctx.user, "limit": str(args.limit),
               "ack": "false" if args.peek else "true"}
    argv = ["drain", "--user", ctx.user, "--limit", str(args.limit)]
    if args.peek:
        argv.append("--peek")
    res, code = _dispatch(ctx, args, "POST", "/drain", payload, argv)
    emit(res, code)


def cmd_ack(ctx, args):
    """确认待发消息已送达 —— `drain --peek` 的对偶操作。"""
    raw = []
    for item in (args.ids or []):
        raw += [p for p in str(item).replace(" ", "").split(",") if p]
    ids = []
    for piece in raw:
        try:
            mid = int(piece)
        except ValueError:
            emit(fail("id 必须是整数：%s" % piece), EXIT_ERR)
        if mid not in ids:
            ids.append(mid)
    if not ids:
        emit(fail("至少给一个消息 id。",
                  hint="先 `drain --peek` 看有哪些，再 `ack --ids 12,13`。"), EXIT_ERR)
    payload = {"user_id": ctx.user, "ids": ids}
    argv = ["ack", "--user", ctx.user]
    for mid in ids:
        argv += ["--ids", str(mid)]
    res, code = _dispatch(ctx, args, "POST", "/ack", payload, argv)
    emit(res, code)


def cmd_tick(ctx, args):
    payload = {"user_id": ctx.user}
    argv = ["tick", "--user", ctx.user]
    res, code = _dispatch(ctx, args, "POST", "/tick", payload, argv, "chat")
    emit(res, code)


def cmd_init(ctx, args):
    argv = ["init", "--user", ctx.user]
    if args.warmup:
        argv.append("--warmup")
    res, code = _dispatch(ctx, args, "POST", "/init",
                          {"user_id": ctx.user, "warmup": bool(args.warmup)}, argv)
    emit(res, code)


# ────────────────────────────────────────────────────────────
# 链路自检（沙箱，不碰真实灵魂数据，不花模型额度）
# ────────────────────────────────────────────────────────────
CODE_ITEMS = ("soulviai.py", "onboarding.py", "config.json", "requirements.txt",
              "core", "engine", "clients")
FAKE_REPLY = "嗯…我在。|||累了就先歇会儿，别硬撑"


def cmd_migrate_data(ctx, args):
    """把旧版写在 engine/data 里的记忆搬到数据家目录。

    记忆没有备份，所以默认**只复制不删除** —— 先保证搬完还能读，删源留给
    用户看过对话历史之后再显式 `--purge`。
    """
    src = os.path.join(ctx.project, "data") if ctx.project else None
    dst = os.path.join(ctx.home, "data")
    info = {"ok": True, "command": "migrate-data",
            "from": src, "data_root": dst}

    # token 也一并带过去（只复制、不删旧那份）：常驻服务可能仍念着旧路径的
    # token，复制一份让新老两侧读到同一个值 —— 否则升级后会出现「服务明明在跑，
    # CLI 却报 token 不匹配」，而用户完全无从下手。
    old_token = os.path.join(ctx.project, TOKEN_FILE_NAME) if ctx.project else None
    if old_token and os.path.isfile(old_token) and not os.path.exists(ctx.token_file):
        try:
            os.makedirs(os.path.dirname(ctx.token_file), exist_ok=True)
            shutil.copy2(old_token, ctx.token_file)
            info["token"] = "已把 token 复制到 %s" % ctx.token_file
        except OSError as exc:
            info["token_error"] = str(exc)

    if not src or not os.path.isdir(src):
        info["skipped"] = "代码树里没有 data 目录，无需迁移"
        emit(info, EXIT_OK)
    if os.path.realpath(src) == os.path.realpath(dst):
        info["skipped"] = "数据已经在数据家目录"
        emit(info, EXIT_OK)

    marker = os.path.join(dst, "db", "soulmate.db")
    if os.path.exists(marker) and not getattr(args, "force", False):
        emit(fail("数据家目录里已经有记忆，没有覆盖：%s" % marker,
                  error_code=None,
                  old_data=src,
                  hint="确认要用旧数据覆盖才加 --force；旧数据仍在原处。"),
             EXIT_ERR)

    moved = []
    try:
        os.makedirs(dst, exist_ok=True)
        for name in sorted(os.listdir(src)):
            s, d = os.path.join(src, name), os.path.join(dst, name)
            if os.path.isdir(s):
                shutil.copytree(s, d, dirs_exist_ok=True)
            elif os.path.isfile(s):
                shutil.copy2(s, d)
            else:
                continue
            moved.append(name)
    except Exception as exc:
        emit(fail("迁移失败：%s" % exc, old_data=src, data_root=dst,
                  hint="旧数据没有删除，可重试；出错时不要手工删源目录。"),
             EXIT_ERR)
    info["moved"] = moved
    if getattr(args, "purge", False):
        shutil.rmtree(src, ignore_errors=True)
        info["purged"] = src
    else:
        info["note"] = "确认对话历史还在之后，可用 --purge 删掉旧目录：%s" % src
    emit(info, EXIT_OK)


def cmd_selftest(ctx, args):
    import tempfile
    if not ctx.project or not ctx.python:
        emit(fail("selftest 需要可用的项目路径与解释器，先跑 doctor。"), EXIT_ERR)

    sandbox = args.sandbox or tempfile.mkdtemp(prefix="soulviai-selftest-")
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "*.log")
    try:
        for item in CODE_ITEMS:
            src, dst = os.path.join(ctx.project, item), os.path.join(sandbox, item)
            if not os.path.exists(src):
                continue
            if os.path.isdir(src):
                shutil.copytree(src, dst, ignore=ignore, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
        os.makedirs(os.path.join(sandbox, "data", "db"), exist_ok=True)

        # 隔离护栏：resolve_project 在沙箱不完整时会「软失败」回落到来真实
        # engine/。若不在这一步拦住，自检会在真实灵魂上跑 chat 并写入记忆，
        # 而输出里还写着「不碰真实数据」——先把这种情况判死。
        missing = [it for it in ("soulviai.py", "engine") if not os.path.exists(
            os.path.join(sandbox, it))]
        if missing:
            shutil.rmtree(sandbox, ignore_errors=True)
            emit(fail("沙箱不完整（缺少 %s），已中止。" % "、".join(missing),
                      project=ctx.project,
                      hint="确认项目里有 soulviai.py 与 engine/ 后再跑自检。"), EXIT_ERR)

        # 沙箱配置：抹掉 api_key 与微信凭证，避免误用真实凭据
        cfg_path = os.path.join(sandbox, "config.json")
        try:
            with open(cfg_path, "r", encoding="utf-8") as fh:
                scfg = json.load(fh)
            scfg.setdefault("ai", {})["api_key"] = ""
            scfg["wx_bot"] = {}
            with open(cfg_path, "w", encoding="utf-8") as fh:
                json.dump(scfg, fh, ensure_ascii=False, indent=2)
        except Exception as exc:
            emit(fail("无法准备沙箱配置: %s" % exc), EXIT_ERR)

        sub = Ctx(ctx.cfg, argparse.Namespace(project=sandbox, python=ctx.python,
                                              user="selftest_user"))
        sub.user = "selftest_user"
        # 沙箱要把**数据家目录**一起隔离：引擎的工作目录就是数据家目录，只换代码
        # 根的话自检仍会写进真实灵魂的记忆，而输出里还写着「不碰真实数据」。
        sub.home = sandbox
        sub.pidfile = os.path.join(sandbox, PID_FILE_NAME)
        sub.logfile = os.path.join(sandbox, LOG_FILE_NAME)
        sub.token_file = os.path.join(sandbox, TOKEN_FILE_NAME)
        if os.path.realpath(sub.project or "") != os.path.realpath(sandbox):
            shutil.rmtree(sandbox, ignore_errors=True)
            emit(fail("沙箱隔离校验失败：项目被解析成了 %s。" % sub.project,
                      sandbox=sandbox,
                      hint="已中止，避免自检写入真实灵魂的数据。"), EXIT_ERR)
        steps = []

        def step(name, argv, expect=None, timeout=180):
            res, code = run_bridge(sub, argv, timeout=timeout)
            ok = res.get("ok") is True
            if expect:
                # expect 可以是单个状态或状态集合；
                # queued（入队延迟投递）也是链路通畅的合法结果，同属"人格行为"而非故障
                wants = expect if isinstance(expect, (tuple, list, set)) else (expect,)
                if res.get("status") not in wants:
                    ok = False
            steps.append({"step": name, "ok": bool(ok),
                          "status": res.get("status"),
                          "exit_code": code,
                          "detail": res.get("error") or res.get("text")
                                    or res.get("life_state") or res.get("note") or ""})
            return res

        step("doctor(沙箱)", ["doctor", "--user", "selftest_user"])
        step("init 唤醒", ["init", "--user", "selftest_user"])
        chat = step("chat 全链路", ["chat", "--user", "selftest_user",
                                    "--text", "今天有点累", "--fake-reply", FAKE_REPLY],
                    expect=("ok", "queued"))
        step("state 状态", ["state", "--user", "selftest_user"])
        step("pending 队列", ["pending", "--user", "selftest_user"])
        step("tick 自主思考", ["tick", "--user", "selftest_user"])
        deep = None
        if getattr(args, "deep", False):
            # 上面几步只证明「命令没报错」；这一步证明「跑完之后东西真的留下了」。
            # 差别很实在：本仓库近一半的 try 是 except: pass，命令「成功」而子系统
            # 尸体一个都不奇怪（深夜复盘就曾整段静默崩掉）。
            deep = step("深度自检（子系统副作用）",
                        ["check", "--user", "selftest_user"], timeout=300)

        passed = all(s["ok"] for s in steps)
        out = {"ok": passed, "command": "selftest",
               "project": ctx.project, "sandbox": sandbox,
               "note": "沙箱副本 + 固定假回复，只验证链路，不代表模型后端可用；"
                       "模型连通性请用 `doctor --check-api`。",
               "steps": steps}
        if chat.get("parts"):
            out["chat_parts_sample"] = chat["parts"]
        if deep:
            out["deep_checks"] = deep.get("checks") or []
            if deep.get("missing_modules"):
                out["deep_missing_modules"] = deep["missing_modules"]
            if deep.get("new_errors"):
                out["deep_new_errors"] = deep["new_errors"]
        if not args.keep:
            shutil.rmtree(sandbox, ignore_errors=True)
            out["sandbox"] = sandbox + "（已清理，--keep 可保留）"
        emit(out, EXIT_OK if passed else EXIT_ERR)
    except Exception as exc:
        shutil.rmtree(sandbox, ignore_errors=True)
        emit(fail("selftest 异常: %s" % exc), EXIT_ERR)


# ────────────────────────────────────────────────────────────
# 安装到各体系的技能根
# ────────────────────────────────────────────────────────────
# 这些工具都用同一套「含 SKILL.md 的文件夹」约定。
SKILL_ROOTS = [
    ("openclaw", "~/.openclaw/skills"),
    ("openclaw-workspace", "~/.openclaw/workspace/skills"),
    ("qclaw", "~/.qclaw/skills"),
    ("workbuddy", "~/.workbuddy/skills"),
    ("codebuddy", "~/.codebuddy/skills"),
    ("trae", "~/.trae/skills"),
    ("qoder", "~/.qoderwork/skills"),
    ("cursor", "~/.cursor/skills"),
    ("claude-code", "~/.claude/skills"),
    ("codex", "~/.codex/skills"),
    ("agents-standard", "~/.agents/skills"),
]


# ────────────────────────────────────────────────────────────
# --copy 安装时的排除项
# ────────────────────────────────────────────────────────────
# 这三样是「本机运行态」，不该跟着副本搬家：
#   .venv  与平台和绝对路径绑定，复制过去并不能真正复用，还白占 50MB+
#   .env   含真实 API Key，多一份副本就多一处要轮换的地方
#   data/  ta 的记忆库，复制等于让灵魂的记忆从此分叉
# 副本首次使用前在副本目录跑一次 `setup --minimal` 即可自建环境。
COPY_PRUNE_DIRS = {".venv", "venv", "__pycache__", ".git", "node_modules", "dist"}
COPY_PRUNE_REL = ("engine/data",)
COPY_PRUNE_FILES = {".DS_Store", ".soulviai-daemon.log", ".soulviai-daemon.pid",
                    ".soulviai-daemon.token"}
COPY_PRUNE_SUFFIX = (".pyc", ".pyo", ".env")
# 数据家目录由引擎在首次运行时自建，副本里不需要预留空目录
COPY_KEEP_EMPTY = ()


def _copy_ignore(src_root):
    """copytree 的 ignore 回调：跳过运行环境 / 密钥 / 记忆。"""
    def ignore(dirpath, names):
        rel = os.path.relpath(dirpath, src_root).replace(os.sep, "/")
        if rel == ".":
            rel = ""
        skipped = set()
        for name in names:
            if name in COPY_PRUNE_DIRS or name in COPY_PRUNE_FILES:
                skipped.add(name)
            elif name.endswith(COPY_PRUNE_SUFFIX):
                skipped.add(name)
            else:
                posix = ("%s/%s" % (rel, name)).strip("/")
                if any(posix == p or posix.startswith(p + "/") for p in COPY_PRUNE_REL):
                    skipped.add(name)
        return skipped
    return ignore


def copy_skill(dst):
    """把技能复制到 dst，跳过运行环境 / 密钥 / 记忆，并重建必要的空目录。"""
    shutil.copytree(SKILL_ROOT, dst, ignore=_copy_ignore(SKILL_ROOT))
    for rel in COPY_KEEP_EMPTY:
        try:
            os.makedirs(os.path.join(dst, rel), exist_ok=True)
        except OSError:
            pass


COPY_HINT = ("副本不含运行环境与密钥。首次使用前先在其目录下跑 "
             "`python3 scripts/soulviaictl.py setup --minimal`，再 `cp "
             "engine/.env.example engine/.env` 填 key。"
             "注意：记忆与 token 都在数据家目录（默认 ~/.soulviai），所以副本"
             "和原件用的是**同一个灵魂**；要让副本另有独立记忆，就在它的 "
             "config.yaml 里填一个不同的 data_dir。")


def cmd_install(ctx, args):
    want = set(args.targets.split(",")) if args.targets else None
    results = []
    for name, raw in SKILL_ROOTS:
        if want and name not in want:
            continue
        root = os.path.expanduser(raw)
        parent = os.path.dirname(root)
        if not (os.path.isdir(root) or os.path.isdir(parent)):
            results.append({"target": name, "path": root, "action": "skipped",
                            "reason": "目录不存在（该系统未安装）"})
            continue
        if os.path.realpath(root) == os.path.realpath(os.path.dirname(SKILL_ROOT)):
            results.append({"target": name, "path": root, "action": "skipped",
                            "reason": "该根目录已直指技能真源，无需安装"})
            continue
        if not os.path.isdir(root):
            try:
                os.makedirs(root, exist_ok=True)
            except Exception as exc:
                results.append({"target": name, "path": root, "action": "error",
                                "reason": str(exc)})
                continue
        dst = os.path.join(root, SKILL_NAME)
        if os.path.islink(dst) or os.path.exists(dst):
            if os.path.islink(dst) and os.path.realpath(dst) == os.path.realpath(SKILL_ROOT):
                results.append({"target": name, "path": dst, "action": "unchanged"})
                continue
            results.append({"target": name, "path": dst, "action": "skipped",
                            "reason": "目标已存在且不是本技能，未覆盖"})
            continue
        try:
            if args.copy:
                copy_skill(dst)
                results.append({"target": name, "path": dst, "action": "copied",
                                "pruned": ["engine/.venv", "engine/.env",
                                           "engine/data"],
                                "hint": COPY_HINT})
            else:
                try:
                    os.symlink(SKILL_ROOT, dst)
                    results.append({"target": name, "path": dst, "action": "linked"})
                except (OSError, NotImplementedError):
                    # Windows 上普通用户默认无权建软链（需管理员或开发者模式）
                    copy_skill(dst)
                    results.append({"target": name, "path": dst, "action": "copied",
                                    "reason": "该系统不支持软链，已自动改为复制；"
                                              "已跳过 .venv / .env / data",
                                    "hint": COPY_HINT})
        except Exception as exc:
            results.append({"target": name, "path": dst, "action": "error",
                            "reason": str(exc)})
    ok = all(r["action"] in ("linked", "copied", "unchanged", "skipped") for r in results)
    emit({"ok": ok, "command": "install", "skill_root": SKILL_ROOT,
          "mode": "copy" if args.copy else "symlink", "results": results},
         EXIT_OK if ok else EXIT_ERR)


def cmd_uninstall(ctx, args):
    removed = []
    for name, raw in SKILL_ROOTS:
        dst = os.path.join(os.path.expanduser(raw), SKILL_NAME)
        if os.path.islink(dst) and os.path.realpath(dst) == os.path.realpath(SKILL_ROOT):
            os.unlink(dst)
            removed.append(dst)
        elif os.path.isdir(dst) and os.path.isfile(os.path.join(dst, "SKILL.md")) \
                and os.path.realpath(dst) != os.path.realpath(SKILL_ROOT):
            removed.append("(跳过非软链副本) " + dst)
    emit({"ok": True, "command": "uninstall", "removed": removed})


# ────────────────────────────────────────────────────────────
# mcp-config：生成 / 写入 MCP 宿主配置
# ────────────────────────────────────────────────────────────
# 各宿主的 MCP 配置文件位置与顶层键名。同一份 soulviai_mcp.py，换个文件就能接上。
# `{}` 会在生成时替换成当前工作区路径（VS Code 系是项目级配置）。
MCP_TARGETS = [
    ("codebuddy", "~/.codebuddy/mcp.json", "mcpServers"),
    ("cursor", "~/.cursor/mcp.json", "mcpServers"),
    ("windsurf", "~/.codeium/windsurf/mcp_config.json", "mcpServers"),
    ("claude", "~/Library/Application Support/Claude/claude_desktop_config.json",
     "mcpServers"),
    ("claude-linux", "~/.config/Claude/claude_desktop_config.json", "mcpServers"),
    ("vscode", "{}/.vscode/mcp.json", "servers"),
    ("generic", "", "mcpServers"),
]


def mcp_server_entry(command=None, project=None, user=None, config=None):
    """构造一个 MCP server 条目（各宿主结构一致，只有顶层键名不同）。"""
    entry = {"command": command or sys.executable or "python3",
             "args": [os.path.join(HERE, "soulviai_mcp.py")]}
    extra = []
    if project:
        extra += ["--project", project]
    if user:
        extra += ["--user", user]
    if config:
        extra += ["--config", config]
    if extra:
        entry["args"] += extra
    return entry


def mcp_config_document(command=None, project=None, user=None, config=None,
                        key="mcpServers"):
    return {key: {SKILL_NAME: mcp_server_entry(command, project, user, config)}}


def _merge_mcp_config(path, doc, key):
    """把 doc 合并进已存在的配置（保留别人的 server），返回 (状态, 说明)。"""
    data = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh) or {}
        except Exception as exc:
            return "error", "已有配置无法解析（%s），未改动：%s" % (exc, path)
        if not isinstance(data, dict):
            return "error", "已有配置不是 JSON 对象，未改动：%s" % path
    servers = data.get(key)
    if servers is not None and not isinstance(servers, dict):
        return "error", "已有的 %s 字段不是对象，未改动：%s" % (key, path)
    servers = dict(servers or {})
    servers.update(doc[key])
    data[key] = servers
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return "written", path


def cmd_mcp_config(ctx, args):
    """打印（或写入）各宿主可直接使用的 MCP 配置片段。"""
    doc_for = lambda key: mcp_config_document(          # noqa: E731
        command=getattr(args, "server_command", None), project=ctx.project,
        user=ctx.user, config=getattr(args, "config_file", None), key=key)

    want = ([t.strip() for t in args.target.split(",") if t.strip()]
            if args.target else None)
    results, docs = [], {}
    for name, raw, key in MCP_TARGETS:
        if want and name not in want:
            continue
        path = raw.format(os.getcwd()) if raw else ""
        docs[name] = {"path": path, "key": key, "config": doc_for(key)}
        if path and args.write:
            if not os.path.isdir(os.path.dirname(path)):
                results.append({"target": name, "path": path, "action": "skipped",
                                "reason": "目录不存在（该系统未安装）"})
                continue
            action, detail = _merge_mcp_config(path, doc_for(key), key)
            results.append({"target": name, "path": path, "action": action,
                            "detail": detail})
    if want:
        unknown = [t for t in want if t not in docs and t != "all"]
        if unknown:
            emit(fail("未知的 MCP 目标：%s" % "、".join(unknown),
                      error_code="unknown_mcp_target",
                      available=[n for n, _p, _k in MCP_TARGETS]), EXIT_ERR)
    out = {"ok": True, "command": "mcp-config",
           "server_script": os.path.join(HERE, "soulviai_mcp.py"),
           "user": ctx.user, "project": ctx.project,
           "note": "把 config 贴进对应宿主的 MCP 配置文件即可；"
                   "soulviai_mcp.py 是纯标准库，不需要额外依赖。",
           "targets": docs}
    if args.write:
        out["written"] = results
    emit(out)


# ────────────────────────────────────────────────────────────
# autoconfig：复用 OpenClaw / QClaw 已配好的模型接口
# ────────────────────────────────────────────────────────────
# 说明：只在用户【主动执行】autoconfig 时读取本地配置，运行时不做任何隐式读取。
OPENCLAW_CONFIG_CANDIDATES = (
    "~/.qclaw/openclaw.json",
    "~/.openclaw/openclaw.json",
    "~/Library/Application Support/QClaw/openclaw/openclaw.json",
    "~/Library/Application Support/OpenClaw/openclaw.json",
)

# 本技能内置的厂商预设名（与 engine/core/ai.py 的 PROVIDERS 保持一致）
_KNOWN_PROVIDERS = {
    "openai", "deepseek", "moonshot", "zhipu", "dashscope", "volces",
    "siliconflow", "openrouter", "groq", "together", "fireworks",
    "mistral", "xai", "ollama", "vllm", "lmstudio", "llamacpp",
}

# OpenClaw 侧可能的 provider id → 本技能预设名
_PROVIDER_ALIAS = {
    "zhipuai": "zhipu", "glm": "zhipu", "bigmodel": "zhipu",
    "qwen": "dashscope", "aliyun": "dashscope", "bailian": "dashscope",
    "kimi": "moonshot", "doubao": "volces", "volcengine": "volces",
    "ark": "volces", "together_ai": "together", "mistralai": "mistral",
}


def _mask(secret):
    """密钥脱敏，用于展示。"""
    if not secret:
        return "(空)"
    if len(secret) <= 8:
        return "***"
    return "%s…（共 %d 字符）" % (secret[:6], len(secret))


def _resolve_secretref(val):
    """OpenClaw 的 apiKey 可能是 SecretRef 对象，解析成真实值。"""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        name = val.get("id") or val.get("name") or val.get("env")
        if name:
            return os.environ.get(name, "")
    return ""


def _normalize_base(url):
    """把 baseUrl 归一化成 OpenAI SDK 能用的形式。

    https://api.deepseek.com/              → https://api.deepseek.com/v1
    https://open.bigmodel.cn/api/paas/v4   → 不动（已带版本路径）
    http://127.0.0.1:11434/v1              → 不动
    """
    u = (url or "").strip().rstrip("/")
    if not u:
        return ""
    tail = u.rsplit("/", 1)[-1]
    if len(tail) >= 2 and tail[0] in ("v", "V") and tail[1:].isdigit():
        return u
    return u + "/v1"


def _find_openclaw_config():
    """返回 (配置路径, 配置字典)。优先按 qclaw.json 里的 configPath 定位。"""
    for meta in ("~/.qclaw/qclaw.json", "~/.openclaw/qclaw.json"):
        p = os.path.expanduser(meta)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as fh:
                cp = (json.load(fh) or {}).get("configPath")
            if cp and os.path.isfile(os.path.expanduser(cp)):
                real = os.path.expanduser(cp)
                with open(real, "r", encoding="utf-8") as fh:
                    return real, json.load(fh)
        except Exception:
            pass

    for cand in OPENCLAW_CONFIG_CANDIDATES:
        p = os.path.expanduser(cand)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as fh:
                return p, json.load(fh)
        except Exception:
            continue
    return None, {}


def _probe_endpoint(base, key, timeout=6):
    """探测 OpenAI 兼容端点是否可用。返回 (状态, 说明)。

    状态：True=可用 / False=不可用 / None=无法判定（该端点不支持 GET /models）
    """
    url = base.rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200, "HTTP %s" % resp.status
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 405):
            return None, "HTTP %s（该端点不支持 /models，按可用处理）" % exc.code
        return False, "HTTP %s" % exc.code
    except Exception as exc:
        return False, type(exc).__name__


def _collect_candidates():
    """收集候选模型接口（只读配置，不做网络探测）。

    返回 (配置路径, 候选列表)。候选按推荐度排序：直连厂商在前，网关在后。
    """
    cfg_path, cfg = _find_openclaw_config()
    if not cfg:
        return None, []

    cands = []
    defaults = (cfg.get("agents") or {}).get("defaults") or {}
    primary_id = ((defaults.get("model") or {}).get("primary") or "").strip()

    # ① models.providers 里的厂商（直连，纯模型推理）
    providers = (cfg.get("models") or {}).get("providers") or {}
    if isinstance(providers, dict):
        for pid, pv in providers.items():
            if not isinstance(pv, dict):
                continue
            api_key = _resolve_secretref(pv.get("apiKey"))
            base = pv.get("baseUrl") or ""
            if not (api_key and base):
                continue
            models = pv.get("models") or []
            model_id = ""
            if isinstance(models, list) and models and isinstance(models[0], dict):
                model_id = models[0].get("id") or ""
            preset = pid if pid in _KNOWN_PROVIDERS else _PROVIDER_ALIAS.get(pid, "")
            note = "直连模型厂商（纯模型推理）"
            # 当前默认路由不是这个 provider → 它很可能是遗留配置
            if primary_id and not primary_id.startswith(pid + "/"):
                note += "；注意：宿主当前默认路由是 %s，此 provider 可能已废弃" % primary_id
            cands.append({"source": "provider", "provider": preset or pid,
                          "api_base": _normalize_base(base), "api_key": api_key,
                          "model": model_id, "note": note})

    # ② gateway 暴露的 OpenAI 兼容端点（复用宿主模型路由）
    gw = cfg.get("gateway") or {}
    ep = ((gw.get("http") or {}).get("endpoints") or {}).get("chatCompletions") or {}
    if ep.get("enabled"):
        token = (gw.get("auth") or {}).get("token") \
            or os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")
        port = gw.get("port") or 18789
        if token:
            cands.append({"source": "gateway", "provider": "",
                          "api_base": "http://127.0.0.1:%s/v1" % port,
                          "api_key": token, "model": "openclaw/default",
                          "note": "走 OpenClaw 网关（复用宿主的模型路由；"
                                  "需宿主在运行，且每次调用会走一轮完整 Agent）"})

    return cfg_path, cands


def _is_ai_env_key(key):
    """判断是否属于模型接口配置（autoconfig 负责重写这一块）。"""
    return key.startswith(("AI_", "OPENAI_", "LLM_", "DEEPSEEK_"))


def _write_env(env_path, values):
    """把模型接口配置写进 .env，替换同名/同类的旧行，保留其余内容。"""
    old = []
    if os.path.isfile(env_path):
        with open(env_path, "r", encoding="utf-8") as fh:
            old = fh.read().splitlines()

    kept = []
    for line in old:
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            if _is_ai_env_key(s.split("=", 1)[0].strip()):
                continue          # 丢掉旧的模型接口配置，统一重写
        kept.append(line)

    while kept and not kept[-1].strip():
        kept.pop()
    kept.append("")
    kept.append("# ── 模型接口（由 soulviaictl autoconfig 生成）──")
    for k, v in values.items():
        kept.append("%s=%s" % (k, v))

    os.makedirs(os.path.dirname(env_path), exist_ok=True)
    with open(env_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(kept) + "\n")
    return list(values)


def cmd_autoconfig(ctx, args):
    project = ctx.project or os.path.join(SKILL_ROOT, "engine")
    env_path = os.path.join(project, ".env")

    cfg_path, cands = _collect_candidates()
    if not cfg_path:
        emit(fail("没有找到 OpenClaw / QClaw 的配置文件。",
                  error_code="openclaw_config_not_found",
                  searched=[os.path.expanduser(p) for p in OPENCLAW_CONFIG_CANDIDATES],
                  hint="可手动配置：cp engine/.env.example engine/.env，"
                       "再填 AI_PROVIDER 与 AI_API_KEY。"
                       "注意 WorkBuddy 是托管式产品，模型走云侧登录鉴权，"
                       "本地不存模型配置（无 openclaw.json，models.json 为空），"
                       "autoconfig 探测不到任何接口；云端沙箱同理。"
                       "这两种情况请改为直接注入环境变量 "
                       "AI_PROVIDER / AI_API_KEY / AI_API_BASE。"), EXIT_ERR)
    if not cands:
        emit(fail("配置里没有可用的模型接口。",
                  error_code="no_model_endpoint",
                  detected_from=cfg_path,
                  hint="在 OpenClaw 里配置 models.providers，或启用 "
                       "gateway.http.endpoints.chatCompletions。"), EXIT_ERR)

    # 逐个探测，优先选真正可用的那一个，避免写入已失效的 key
    probes, chosen, first_maybe = [], None, None
    for cand in cands:
        ok, detail = _probe_endpoint(cand["api_base"], cand["api_key"])
        probes.append({"source": cand["source"],
                       "provider": cand.get("provider") or "-",
                       "api_base": cand["api_base"],
                       "model": cand["model"] or "-",
                       "api_key": _mask(cand["api_key"]),
                       "probe": detail})
        if ok is True:
            chosen = cand
            break
        if ok is None and first_maybe is None:
            first_maybe = cand
    if chosen is None:
        chosen = first_maybe          # 没有确定可用的，退而选「无法判定」的那个
    if chosen is None:
        emit(fail("探测到的模型接口都不可用。",
                  error_code="model_endpoint_unreachable",
                  detected_from=cfg_path, probes=probes,
                  hint="常见原因：provider 的 apiKey 已失效；"
                       "或宿主未在运行（网关端点需要 OpenClaw/QClaw 在线）。"),
             EXIT_ERR)

    values = {"AI_API_KEY": chosen["api_key"],
              "AI_API_BASE": chosen["api_base"],
              "AI_MODEL": chosen["model"]}
    if chosen.get("provider"):
        values["AI_PROVIDER"] = chosen["provider"]
    values = {k: v for k, v in values.items() if v}

    info = {"ok": True, "command": "autoconfig", "detected_from": cfg_path,
            "source": chosen["source"], "note": chosen["note"],
            "provider": chosen.get("provider") or "(不指定)",
            "api_base": chosen["api_base"],
            "model": chosen["model"] or "(不指定)",
            "api_key": _mask(chosen["api_key"]),
            "candidates_probed": probes,
            "env_file": env_path}

    if getattr(args, "dry_run", False):
        info["dry_run"] = True
        info["would_write"] = {k: (_mask(v) if "KEY" in k else v)
                               for k, v in values.items()}
        emit(info)

    _write_env(env_path, values)
    info["written_keys"] = list(values)
    if chosen["source"] == "gateway":
        info["warning"] = ("网关端点每次调用都会执行一轮完整 Agent，比直连厂商慢；"
                           "且存在被宿主 agent 反向调用的理论风险。")
    info["next"] = "运行 `doctor --check-api` 验证连通性"
    emit(info)


def cmd_reload_ai(ctx, args):
    """让运行中的常驻服务重新读取 .env / config.json。

    没有常驻服务时不用做任何事 —— 冷启动每次都是全新进程，不存在旧值缓存，
    下次启动自然会读到新配置。所以这里刻意**不**回落到冷启动。
    """
    state, _health = daemon_probe(ctx)
    if state == "down":
        emit({"ok": True, "command": "reload-ai", "source": "local",
              "daemon": "down", "applied": False,
              "detail": "没有常驻服务在跑，无需重载：下次启动会直接读到新配置。"})
    if state == "unauthorized":
        emit(auth_conflict(ctx, "有 soulviai 常驻服务在跑，但本机 token 不匹配"),
             EXIT_ERR)

    res = daemon_request(ctx, "POST", "/config/reload", {},
                         timeout=ctx.timeout("default"))
    if res is None or res.get("auth_required"):
        emit(auth_conflict(ctx, "常驻服务的鉴权在请求途中失效"), EXIT_ERR)
    res["command"] = "reload-ai"
    res["applied"] = bool(res.get("ok"))
    emit(res, _exit_for(res))


# ────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────
def add_common(sp, with_user=False):
    """把 --project/--python 复制到子命令上，让参数放在命令前后都能用。

    default=SUPPRESS 是关键：子命令没写这些参数时不会覆盖全局取值。
    """
    sp.add_argument("--project", default=argparse.SUPPRESS,
                    help="数字生命项目根目录")
    sp.add_argument("--python", default=argparse.SUPPRESS,
                    help="指定运行引擎的解释器")
    if with_user:
        sp.add_argument("--user", default=argparse.SUPPRESS, help="灵魂身份")


def build_parser():
    p = argparse.ArgumentParser(
        prog="soulviaictl.py",
        description="soulviai · 数字生命引擎跨体系调用入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  python3 soulviaictl.py doctor\n"
               "  python3 soulviaictl.py serve\n"
               "  python3 soulviaictl.py chat --text \"今天有点累\" --plain\n")
    p.add_argument("--project", help="数字生命项目根目录")
    p.add_argument("--python", help="指定运行引擎的解释器")
    p.add_argument("--debug", action="store_true", help="把引擎 stderr 转发到本地 stderr")

    sub = p.add_subparsers(dest="command")

    d = sub.add_parser("doctor", help="环境与引擎自检")
    add_common(d)
    d.add_argument("--check-api", action="store_true",
                   help="真实调用一次模型接口（会消耗少量额度）")
    d.set_defaults(func=cmd_doctor)

    s = sub.add_parser("setup", help="创建虚拟环境并安装依赖")
    add_common(s)
    s.add_argument("--minimal", action="store_true",
                   help="只装对话必需依赖（跳过 fastembed/onnxruntime）")
    s.set_defaults(func=cmd_setup)

    ac = sub.add_parser("autoconfig",
                        help="自动探测 OpenClaw/QClaw 已配好的模型接口并写入 .env")
    add_common(ac)
    ac.add_argument("--dry-run", action="store_true",
                    help="只探测并预览，不写入 .env")
    ac.set_defaults(func=cmd_autoconfig)

    ra = sub.add_parser("reload-ai",
                        help="让运行中的常驻服务重读 .env / config.json（改完模型配置用它）")
    add_common(ra)
    ra.set_defaults(func=cmd_reload_ai)

    v = sub.add_parser("serve", help="启动常驻服务（推荐）")
    add_common(v)
    v.add_argument("--foreground", action="store_true", help="前台运行，不转后台")
    v.add_argument("--restart", action="store_true", help="先停掉已有服务再启动")
    v.add_argument("--no-autonomous", action="store_true", help="不启动自主思考引擎")
    v.add_argument("--allow-remote", action="store_true",
                   help="允许监听非回环地址（有 token 鉴权，但走明文 HTTP，建议套 HTTPS）")
    v.add_argument("--token-file", default=None,
                   help="鉴权 token 文件位置（默认 <项目>/.soulviai-daemon.token，0600）")
    v.add_argument("--wait", type=int, default=90, help="等待健康检查的秒数")
    v.set_defaults(func=cmd_serve)

    t = sub.add_parser("stop", help="停止常驻服务")
    add_common(t)
    t.set_defaults(func=cmd_stop)

    wb = sub.add_parser("web", help="在浏览器里打开对话终端（前台运行）")
    add_common(wb)
    wb.add_argument("--host",
                    help="监听地址（默认取 config.yaml 的 web_host，或 127.0.0.1）")
    wb.add_argument("--port", type=int,
                    help="监听端口（默认取 config.yaml 的 web_port，或 5000）")
    wb.add_argument("--allow-remote", action="store_true",
                    help="允许监听非回环地址（无鉴权，仅网络可信时使用）")
    wb.set_defaults(func=cmd_web)

    c = sub.add_parser("chat", help="和数字生命说一句话")
    add_common(c)
    c.add_argument("--text", required=True, help="用户说的话；用 - 从 stdin 读取")
    c.add_argument("--user", help="灵魂身份（默认 default_user，与终端/微信共用）")
    c.add_argument("--env", default="",
                   help="环境上下文自由文本（如「上海 小雨 24°C」或「Shanghai light rain 24C」）。"
                        "由调用方/Agent 查好后传入，引擎据此感知天气，不自行联网查询")
    c.add_argument("--env-json", default="",
                   help='结构化环境上下文（JSON 字符串），比 --env 更稳。'
                        '如 \'{"city":"上海","temperature":24,"is_raining":true}\'')
    c.add_argument("--verbose", action="store_true",
                   help="附带理解层/心智/引擎日志诊断（排查用）")
    c.add_argument("--plain", action="store_true", help="只输出 ta 的原话")
    c.set_defaults(func=cmd_chat)

    st = sub.add_parser("state", help="查看当前生命状态")
    add_common(st)
    st.add_argument("--user")
    st.add_argument("--raw", action="store_true", help="附带原始心智数值")
    st.add_argument("--friendly", action="store_true",
                    help="只输出人话摘要（相处阶段 / 此刻 / 羁绊），"
                         "不含 24 维数值、内部标识与潜意识独白；给普通用户看用这个")
    st.set_defaults(func=cmd_state)

    cf = sub.add_parser("config", help="查看可调参数：当前值 / 来源 / 说明")
    add_common(cf)
    cf.add_argument("--json", action="store_true",
                    help="输出完整 JSON（含说明与来源），给脚本或设置页用")
    cf.set_defaults(func=cmd_config)

    ev = sub.add_parser("env", help="环境信息：定位/天气")
    add_common(ev)
    ev.add_argument("--user")
    ev.add_argument("--refresh", action="store_true",
                    help="忽略缓存，强制联网重取一次")
    ev.set_defaults(func=cmd_env)

    pd = sub.add_parser("pending", help="查看待发队列（主动消息）")
    add_common(pd)
    pd.add_argument("--user")
    pd.add_argument("--limit", type=int, default=10)
    pd.set_defaults(func=cmd_pending)

    dr = sub.add_parser("drain", help="取出待发消息（可顺便标记已送达）")
    add_common(dr)
    dr.add_argument("--user")
    dr.add_argument("--limit", type=int, default=5)
    dr.add_argument("--peek", action="store_true", help="只看不标记已送达")
    dr.set_defaults(func=cmd_drain)

    ak = sub.add_parser("ack", help="确认待发消息已送达（配对 drain --peek）")
    add_common(ak)
    ak.add_argument("--user")
    ak.add_argument("--ids", action="append", required=True,
                    help="消息 id，可逗号分隔或重复传：--ids 12,13")
    ak.set_defaults(func=cmd_ack)

    tk = sub.add_parser("tick", help="手动推进一次自主思考")
    add_common(tk)
    tk.add_argument("--user")
    tk.set_defaults(func=cmd_tick)

    ini = sub.add_parser("init", help="初始化灵魂（唤醒/预热）")
    add_common(ini)
    ini.add_argument("--user")
    ini.add_argument("--warmup", action="store_true", help="同时做第一次预热")
    ini.set_defaults(func=cmd_init)

    stest = sub.add_parser("selftest", help="沙箱链路自检（不碰真实数据、不花额度）")
    add_common(stest)
    stest.add_argument("--sandbox", help="指定沙箱目录（默认自动建临时目录）")
    stest.add_argument("--keep", action="store_true", help="保留沙箱目录")
    stest.add_argument("--deep", action="store_true",
                       help="额外跑深度自检：断言各子系统真的留下了副作用（经历事件 / "
                            "经历驱动成长 / 深夜复盘 / tick / 多段回复协议 / 关键模块 / "
                            "静默失败）。比前者慢，建议改动引擎后跑")
    stest.set_defaults(func=cmd_selftest)

    md = sub.add_parser("migrate-data",
                        help="把旧版写在 engine/data 的记忆搬到数据家目录")
    add_common(md)
    md.add_argument("--purge", action="store_true",
                    help="迁移成功后删掉旧的 engine/data")
    md.add_argument("--force", action="store_true",
                    help="数据家目录已有记忆时也覆盖")
    md.set_defaults(func=cmd_migrate_data)

    ins = sub.add_parser("install", help="安装到各 OpenClaw 系技能目录")
    add_common(ins)
    ins.add_argument("--copy", action="store_true", help="复制而非软链")
    ins.add_argument("--targets", help="只装指定目标，逗号分隔，如 qclaw,workbuddy")
    ins.set_defaults(func=cmd_install)

    un = sub.add_parser("uninstall", help="从各技能目录移除本技能（软链）")
    add_common(un)
    un.set_defaults(func=cmd_uninstall)

    mc = sub.add_parser("mcp-config",
                        help="生成/写入 MCP 宿主配置（把本引擎接进 AI 客户端）")
    add_common(mc, with_user=True)
    mc.add_argument("--target", default=None,
                    help="只处理指定宿主，逗号分隔：%s；默认全部"
                         % "、".join(n for n, _p, _k in MCP_TARGETS))
    mc.add_argument("--write", action="store_true",
                    help="直接写入宿主配置文件（已存在时合并，不动别人的 server）")
    # 注意：dest 必须避开 "command" —— 那是 subparsers 存子命令名的槽位，
    # 子解析器里的同名 dest 会在 parse 结束时把子命令名覆盖成 None。
    mc.add_argument("--command", dest="server_command", default=None,
                    help="宿主调用 python 的命令，默认当前解释器")
    mc.add_argument("--config", dest="config_file", default=None,
                    help="传给 soulviai_mcp.py 的引擎配置路径")
    mc.set_defaults(func=cmd_mcp_config)

    return p


def main():
    args = build_parser().parse_args()
    if not getattr(args, "command", None):
        build_parser().print_help()
        return 0

    cfg = load_config()
    ctx = Ctx(cfg, args)
    try:
        args.func(ctx, args)
    except KeyboardInterrupt:
        emit(fail("被中断。"), EXIT_ERR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
