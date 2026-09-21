#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""soulviai · 各形态共用的客户端薄层（纯标准库，无第三方依赖）

「本体只有一个」的落点就在这里：本层**不重新实现**任何定位项目、探测解释器、
常驻优先、token 鉴权、退出码归一化的逻辑，只把 `soulviaictl.py` 已经写好的那套借出来用。

两条路径
--------
  进程内（数据类命令：chat / state / pending / drain / ack / tick / init）
      import soulviaictl → Ctx → _dispatch(...)
      只调用**不会 sys.exit** 的函数，避免把宿主进程（MCP server）一起带走。

  子进程（控制类命令：doctor / setup / serve / stop / selftest / install / autoconfig）
      用 soulviaictl.py 自己的 CLI 跑，解析 stdout 末行 JSON。
      这些命令天生就是在「启动另一个进程 / 改本机环境」，进程内复现等于把日志裁剪、
      pidfile、软链安装那一整套再抄一遍 —— 直接复用 CLI 更安全也更省事。

调用方
------
  scripts/soulviai_mcp.py   MCP server（把本层的方法暴露成 MCP 工具）
  scripts/soulviaictl.py    更底层的那一层（本层的依赖）
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
SOULVIAICTL = os.path.join(HERE, "soulviaictl.py")

_MODULE = None


def soulviaictl():
    """惰性导入同目录的 soulviaictl（它是纯标准库脚本，顶层无副作用）。"""
    global _MODULE
    if _MODULE is None:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import soulviaictl as mod
        _MODULE = mod
    return _MODULE


def load_config(config_path=None):
    """读取 config.yaml（优先级：参数 > $SOULVIAI_CONFIG > 技能内 config.yaml）。"""
    mod = soulviaictl()
    path = config_path or os.environ.get("SOULVIAI_CONFIG") or mod.CONFIG_PATH
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return mod.parse_flat_yaml(fh.read())
    except Exception as exc:
        print("[soulviai_client] 读取配置失败 %s: %s" % (path, exc), file=sys.stderr)
        return {}


def _last_json(text):
    """从 soulviaictl 的 stdout 里取出那条 JSON 结果。

    soulviaictl 用的是 `json.dumps(..., indent=2)`，所以结果块是**多行**的：
    首行是顶格的 `{`，末行是 `}`。因此不能只按「单行以 { 开头」去找 ——
    先整体试解析，再从后往前按顶格 `{` 切片，最后才退化成全文扫描。
    """
    text = (text or "").strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    lines = text.splitlines()
    decoder = json.JSONDecoder()
    for strict in (True, False):
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i]
            if not (line.startswith("{") if strict else line.lstrip().startswith("{")):
                continue
            chunk = "\n".join(lines[i:])
            try:
                obj = json.loads(chunk)
            except Exception:
                try:                      # 同一行后面还挂着别的输出
                    obj, _end = decoder.raw_decode(chunk)
                except Exception:
                    continue
            if isinstance(obj, dict):
                return obj

    idx = text.rfind("{")                  # 兜底：全文里最后一个能解析的对象
    while idx != -1:
        try:
            obj, _end = decoder.raw_decode(text[idx:])
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
        idx = text.rfind("{", 0, idx)
    return None


def _tail(text, lines=12):
    return "\n".join((text or "").strip().splitlines()[-lines:])


class SoulClient(object):
    """指向本机某个数字生命引擎的统一客户端。"""

    def __init__(self, project=None, python=None, user=None, config=None,
                 host=None, port=None, debug=False):
        mod = soulviaictl()
        self.mod = mod
        self.cfg = load_config(config)
        self.args = argparse.Namespace(project=project, python=python,
                                       user=user, debug=bool(debug))
        self.ctx = mod.Ctx(self.cfg, self.args)
        if host:
            self.ctx.host = host
        if port:
            self.ctx.port = int(port)

    # ── 环境信息 ─────────────────────────────────────────────
    @property
    def user(self):
        return self.ctx.user

    @property
    def project(self):
        return self.ctx.project

    @property
    def python(self):
        return self.ctx.python

    def cli_python(self):
        """跑 soulviaictl CLI 用的解释器（它只需 >=3.8）。"""
        env = (os.environ.get("SOULVIAICTL_PYTHON") or "").strip()
        if env and os.path.isfile(env):
            return env
        if sys.executable:
            return sys.executable
        return "python3"

    def read_token(self):
        return self.mod.read_daemon_token(self.ctx)

    def daemon_state(self, timeout=2.0):
        """返回 ("up" | "down" | "unauthorized", 载荷)。"""
        return self.mod.daemon_probe(self.ctx, timeout=timeout)

    def describe(self, probe_timeout=2.0):
        """诊断信息：项目/解释器/常驻服务/token 是否就绪。供 MCP 的 doctor 工具用。"""
        state, body = self.daemon_state(probe_timeout)
        info = {
            "ok": bool(self.ctx.project) and bool(self.ctx.python),
            "skill": SKILL_ROOT,
            "project": self.ctx.project,
            "python": self.ctx.python,
            "user": self.ctx.user,
            "daemon": {
                "state": state,
                "url": "http://%s:%d" % (self.ctx.host, self.ctx.port),
                "token_file": self.ctx.token_file,
                "token_file_exists": os.path.isfile(self.ctx.token_file),
                "token_env_set": bool((os.environ.get(self.mod.TOKEN_ENV) or "").strip()),
                "token_available": bool(self.read_token()),
            },
        }
        if body:
            info["daemon"]["info"] = body
        if self.ctx.python_note:
            info["python_note"] = self.ctx.python_note
        if not self.ctx.project:
            info["hint"] = (getattr(self.ctx, "project_error", None)
                            or "没找到引擎项目根目录（需含 soulviai.py 与 engine/）。")
        elif not self.ctx.python:
            info["hint"] = "没找到 >=3.10 的解释器，先跑 setup。"
        elif state == "down":
            info["hint"] = "常驻服务没在跑；命令会自动冷启动（首次约 2s）。"
        elif state == "unauthorized":
            info["hint"] = "常驻服务在跑但 token 不匹配：用 stop 停掉它再 serve --restart。"
        return info

    # ── 统一封套 ─────────────────────────────────────────────
    def _finish(self, res, code):
        if not isinstance(res, dict):
            res = {"ok": False, "error": "引擎返回了非字典结果",
                   "error_code": "bad_result"}
        res.setdefault("ok", False)
        res.setdefault("source", "unknown")
        try:
            res["exit_code"] = int(code or 0)
        except (TypeError, ValueError):
            res["exit_code"] = 0
        return res

    def _fail(self, msg, code="internal", **extra):
        payload = {"ok": False, "error": msg, "error_code": code}
        payload.update(extra)
        return self._finish(payload, self.mod.EXIT_ERR)

    # ── 进程内：数据类命令 ───────────────────────────────────
    def _dispatch(self, method, path, payload, bridge_argv, kind="default"):
        try:
            res, code = self.mod._dispatch(
                self.ctx, self.args, method, path, payload, bridge_argv, kind)
        except Exception as exc:
            return self._fail("引擎调用异常: %s" % exc, "internal")
        return self._finish(res, code)

    def chat(self, text, env="", env_json="", verbose=False):
        text = text or ""
        if not text.strip():
            return self._fail("text 不能为空。", "empty_text")
        payload = {"user_id": self.ctx.user, "text": text, "verbose": bool(verbose),
                   "env": (env or "").strip(), "env_json": (env_json or "").strip()}
        argv = ["chat", "--user", self.ctx.user, "--text", text]
        if payload["env_json"]:
            argv += ["--env-json", payload["env_json"]]
        elif payload["env"]:
            argv += ["--env", payload["env"]]
        if verbose:
            argv.append("--verbose")
        return self._dispatch("POST", "/chat", payload, argv, "chat")

    def state(self):
        return self._dispatch("GET", "/state", {"user_id": self.ctx.user},
                              ["state", "--user", self.ctx.user])

    def pending(self, limit=10):
        limit = int(limit or 10)
        return self._dispatch("GET", "/pending",
                              {"user_id": self.ctx.user, "limit": str(limit)},
                              ["pending", "--user", self.ctx.user,
                               "--limit", str(limit)])

    def drain(self, limit=5, peek=False):
        limit = int(limit or 5)
        payload = {"user_id": self.ctx.user, "limit": str(limit),
                   "ack": "false" if peek else "true"}
        argv = ["drain", "--user", self.ctx.user, "--limit", str(limit)]
        if peek:
            argv.append("--peek")
        return self._dispatch("POST", "/drain", payload, argv)

    def ack(self, ids):
        clean = []
        for item in (ids or []):
            for piece in str(item).replace(" ", "").split(","):
                if not piece:
                    continue
                try:
                    mid = int(piece)
                except ValueError:
                    return self._fail("id 必须是整数：%s" % piece, "bad_id")
                if mid not in clean:
                    clean.append(mid)
        if not clean:
            return self._fail("至少给一个消息 id。", "no_ids")
        argv = ["ack", "--user", self.ctx.user]
        for mid in clean:
            argv += ["--ids", str(mid)]
        return self._dispatch("POST", "/ack",
                              {"user_id": self.ctx.user, "ids": clean}, argv)

    def env(self, refresh=False):
        """环境信息（定位 / 天气）。refresh=True 强制忽略缓存重新采集。"""
        payload = {"user_id": self.ctx.user}
        argv = ["env", "--user", self.ctx.user]
        if refresh:
            payload["refresh"] = "1"
            argv.append("--refresh")
        return self._dispatch("GET", "/env", payload, argv)

    def tick(self):
        return self._dispatch("POST", "/tick", {"user_id": self.ctx.user},
                              ["tick", "--user", self.ctx.user], "chat")

    def init(self, warmup=False):
        argv = ["init", "--user", self.ctx.user]
        if warmup:
            argv.append("--warmup")
        return self._dispatch("POST", "/init",
                              {"user_id": self.ctx.user, "warmup": bool(warmup)}, argv)

    # ── 子进程：控制类命令 ───────────────────────────────────
    def cli(self, argv, timeout=180.0):
        """跑 soulviaictl.py 的 CLI 并返回解析后的 JSON 结果。"""
        cmd = [self.cli_python(), SOULVIAICTL] + list(argv)
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env.pop("SOULVIAI_DEBUG", None)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            return self._fail("soulviaictl 调用超时（%.0fs）。" % timeout, "timeout")
        except Exception as exc:
            return self._fail("无法启动 soulviaictl: %s" % exc, "spawn_failed")
        res = _last_json(proc.stdout)
        if res is None:
            return self._finish(
                {"ok": False, "error": "soulviaictl 没有返回可解析的 JSON",
                 "error_code": "no_result", "returncode": proc.returncode,
                 "stderr_tail": _tail(proc.stderr)},
                proc.returncode or self.mod.EXIT_ERR)
        return self._finish(res, proc.returncode)

    def _base_argv(self):
        argv = []
        if self.ctx.project:
            argv += ["--project", self.ctx.project]
        if self.ctx.python:
            argv += ["--python", self.ctx.python]
        return argv

    def doctor(self, check_api=False, timeout=180.0):
        argv = self._base_argv() + ["doctor", "--user", self.ctx.user]
        if check_api:
            argv.append("--check-api")
        return self.cli(argv, timeout=timeout)

    def setup(self, minimal=True, timeout=3600.0):
        argv = self._base_argv() + ["setup"]
        if minimal:
            argv.append("--minimal")
        return self.cli(argv, timeout=timeout)

    def serve(self, restart=False, no_autonomous=False, wait=90, timeout=None):
        argv = self._base_argv() + ["serve", "--wait", str(int(wait))]
        if restart:
            argv.append("--restart")
        if no_autonomous:
            argv.append("--no-autonomous")
        return self.cli(argv, timeout=timeout or (int(wait) + 60.0))

    def stop(self, timeout=90.0):
        return self.cli(self._base_argv() + ["stop"], timeout=timeout)

    def selftest(self, keep=False, timeout=600.0):
        argv = self._base_argv() + ["selftest"]
        if keep:
            argv.append("--keep")
        return self.cli(argv, timeout=timeout)

    def autoconfig(self, dry_run=False, timeout=180.0):
        argv = self._base_argv() + ["autoconfig"]
        if dry_run:
            argv.append("--dry-run")
        return self.cli(argv, timeout=timeout)

    def reload_ai(self, timeout=180.0):
        return self.cli(self._base_argv() + ["reload-ai"], timeout=timeout)


def client_from_env(**override):
    """按环境变量构造客户端（SOULVIAI_PROJECT_ROOT / SOULVIAI_PYTHON / SOULVIAI_CONFIG）。"""
    kwargs = {
        "project": os.environ.get("SOULVIAI_PROJECT_ROOT") or None,
        "python": os.environ.get("SOULVIAI_PYTHON") or None,
        "config": os.environ.get("SOULVIAI_CONFIG") or None,
    }
    kwargs.update({k: v for k, v in override.items() if v is not None})
    return SoulClient(**kwargs)


if __name__ == "__main__":
    # 自检用：打印当前客户端的诊断信息（不是给 Agent 用的入口）
    print(json.dumps(client_from_env().describe(), ensure_ascii=False, indent=2))
