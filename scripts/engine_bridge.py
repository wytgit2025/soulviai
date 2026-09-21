#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""soulviai · 引擎执行体

必须由「数字生命项目」自己的解释器运行，且工作目录 = 项目根目录
（项目的数据全部是相对路径 data/...）。soulviaictl.py 会自动处理这两件事。

一次调用只做一件事，最后把结果以单行 JSON 打到真实 stdout。
引擎内部所有 print（启动横幅、模块日志、调试输出）都会被改道到 stderr，
所以 stdout 永远是干净可解析的。

同时提供 `serve` 模式：把引擎常驻在内存里 + 跑自主思考引擎，
通过 127.0.0.1 上的 HTTP 提供服务。常驻后每次对话不再重复冷启动。
"""
import argparse
import hmac
import json
import os
import secrets
import sys
import threading
import time
import traceback

_REAL_OUT = sys.stdout

# 引擎 print 的环形缓冲（按行），用来解释"为什么没回复"。
# _NOISE_TOTAL 是历史累计行数：run_chat 用它做水位线，保证只分析「本次请求」
# 产生的输出，不会被自主思考引擎刷出的历史报错污染（否则静默会被误判成后端故障）。
_NOISE = []
_NOISE_TOTAL = 0
_NOISE_LIMIT = 800


def _noise_append(lines):
    """把若干行追加进环形缓冲，并推进历史行号。"""
    global _NOISE_TOTAL
    for line in lines:
        _NOISE.append(line)
        _NOISE_TOTAL += 1
    if len(_NOISE) > _NOISE_LIMIT:
        del _NOISE[:len(_NOISE) - _NOISE_LIMIT]


def noise_mark():
    """记录当前水位（历史行号）。"""
    return _NOISE_TOTAL


def _noise_since(mark):
    """返回水位之后新产生的引擎输出行。

    mark 早于缓冲起点时（缓冲已被环形覆盖）退化为整个缓冲，不会更糟。
    """
    start = max(0, int(mark or 0) - (_NOISE_TOTAL - len(_NOISE)))
    return list(_NOISE[start:])


class _NoiseTee(object):
    """把引擎的 print 改道到 stderr，同时维护一份「最近输出」的按行缓冲。

    连续重复的行会被折叠成一行 + 重复次数：模型接口持续失败时引擎会每秒/每分钟
    刷同样的报错，不折叠会把日志文件和内存缓冲一起撑爆。
    """

    def __init__(self, stream, limit=_NOISE_LIMIT):
        self._stream = stream
        self._limit = limit
        self._carry = ""      # 未以换行结束的残段，留到下次 write
        self._last = None
        self._repeat = 0

    def _push(self, line):
        if line == self._last:
            self._repeat += 1
            return
        self._flush_repeat()
        self._last = line
        self._write(line)

    def _flush_repeat(self):
        if self._repeat:
            self._write("    … 上一行重复 %d 次" % self._repeat)
            self._repeat = 0

    def _write(self, line):
        try:
            self._stream.write(line + "\n")
        except Exception:
            pass
        _noise_append([line])

    def write(self, data):
        if not data:
            return 0
        text = self._carry + (data if isinstance(data, str) else str(data))
        parts = text.split("\n")
        self._carry = parts.pop()
        for line in parts:
            self._push(line)
        return len(data)

    def flush(self):
        self._flush_repeat()
        try:
            self._stream.flush()
        except Exception:
            pass

    def isatty(self):
        return False

    def fileno(self):
        raise OSError("no fileno")


# 引擎噪音全部改道 stderr —— 必须在 import soulviai 之前完成
sys.stdout = _NoiseTee(sys.stderr)

EXIT_OK, EXIT_ERR, EXIT_SILENT, EXIT_QUEUED = 0, 1, 3, 4

_SILENCE_MARKERS = ("[LifeGate]", "[情绪沉默]", "[投递控制]", "[跳过", "[沉默")
_API_FAIL_MARKERS = ("API 调用失败", "Authentication Fails", "invalid_api_key",
                     "api key:", "401", "Connection error", "RateLimitError",
                     "APIConnectionError", "Insufficient Balance",
                     "AI 未初始化")

# ── 模型接口环境变量优先级链（与 engine/core/config.py 保持一致）──
# 通用名 AI_* 优先，其次 OpenAI SDK 惯例名，最后兼容旧版 DEEPSEEK_*。
_AI_KEY_ENVS = ("AI_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY")
_AI_BASE_ENVS = ("AI_API_BASE", "AI_BASE_URL", "OPENAI_BASE_URL",
                 "OPENAI_API_BASE", "DEEPSEEK_API_BASE")
_AI_MODEL_ENVS = ("AI_MODEL", "OPENAI_MODEL", "DEEPSEEK_MODEL")
_AI_PROVIDER_ENVS = ("AI_PROVIDER", "LLM_PROVIDER")


def _first_env(names):
    """返回 names 中第一个已设置且非空的环境变量值。"""
    for n in names:
        v = os.environ.get(n)
        if v and v.strip():
            return v.strip()
    return ""


# ── 语言中立的枚举代码（Agent 可据此用任意语言渲染，无需翻译表）──
_STAGE_CODES = {
    "青涩试探": "nascent", "拘谨礼貌": "polite", "松弛默契": "relaxed",
    "成熟珍惜": "mature", "平淡安稳": "stable",
}
_PHASE_CODES = {
    "活跃": "active", "发呆": "zoning", "疲惫": "tired",
    "独处": "alone", "emo": "emo", "自愈": "healing",
}


def _api_error_code(msg):
    """把模型后端报错归类成语义化代码，便于调用方按语言渲染。"""
    m = (msg or "").lower()
    if any(k in m for k in ("401", "authentication", "invalid_api_key", "api key:")):
        return "api_auth"
    if any(k in m for k in ("429", "rate limit", "ratelimit")):
        return "api_rate_limit"
    if any(k in m for k in ("insufficient balance", "quota", "402")):
        return "api_quota"
    if any(k in m for k in ("connection", "timeout", "timed out",
                            "unreachable", "connect")):
        return "api_unreachable"
    if "未初始化" in (msg or "") or "not initialized" in m:
        return "api_not_configured"
    return "api_error"


def _noise_tail(lines=8):
    """最近若干行引擎输出（诊断用）。"""
    return [l.strip() for l in _NOISE if l.strip()][-lines:]


def _silence_reason(lines):
    """从本轮引擎输出里找出"这次为什么没回复"的那一行。"""
    for line in reversed(lines or []):
        if any(mark in line for mark in _SILENCE_MARKERS):
            return line.strip()
    return None


def _api_error(lines):
    """模型后端失败会被内核吞掉成"空回复"。这里把它捞出来，避免误导成"人格沉默"。

    lines 必须只包含「本轮请求」的输出，否则历史残留的报错会把人格沉默误判为故障。
    """
    lines = lines or []
    for line in reversed(lines):
        if "API 调用失败" in line:
            return line.strip()
    for line in reversed(lines):
        if any(mark in line for mark in _API_FAIL_MARKERS):
            return line.strip()
    return None


def _emit(payload, exit_code=EXIT_OK):
    print(json.dumps(payload, ensure_ascii=False), file=_REAL_OUT)
    _REAL_OUT.flush()
    return exit_code


def _split_parts(text):
    return [p.strip() for p in (text or "").split("|||") if p.strip()]


# ────────────────────────────────────────────────────────────
# 项目加载
# ────────────────────────────────────────────────────────────
def bootstrap(project=None):
    """代码根挂进 sys.path，工作目录切到**数据家目录**。

    这两件事现在指向不同地方：project 是代码（engine/），cwd 是数据
    （~/.soulviai，可用 SOULVIAI_DATA_DIR / config.yaml:data_dir 改）。引擎里
    大量 `data/...` 相对路径都以 cwd 为基准，所以必须切过去；只挂 sys.path
    不切 cwd，就会在启动目录旁边长出一份新的空记忆。
    """
    project = os.path.abspath(project or os.getcwd())
    if project not in sys.path:
        sys.path.insert(0, project)
    import core.paths as paths       # project 进 sys.path 之后才 import 得到
    paths.chdir_home()
    return project


def config_path(project, explicit=None):
    if explicit and os.path.isfile(explicit):
        return explicit
    env = os.environ.get("SOULVIAI_CONFIG")
    if env and os.path.isfile(env):
        return env
    return os.path.join(project, "config.json")


def load_engine(user_id, project=None, config=None, warmup=False):
    project = bootstrap(project)
    cfg_file = config_path(project, config)
    if not os.path.isfile(cfg_file):
        raise RuntimeError("找不到配置文件：%s（用 --config 指定，或放到项目根目录）" % cfg_file)
    import soulviai
    # SoulEngine 会把 config_path 透传给各子模块，非默认文件名同样有效
    engine = soulviai.SoulEngine(cfg_file)
    engine.ensure_user(user_id)
    if warmup:
        try:
            engine.warmup(user_id)
        except Exception:
            pass
    return engine


# ────────────────────────────────────────────────────────────
# 各命令
# ────────────────────────────────────────────────────────────
def cmd_doctor(args):
    project = os.path.abspath(args.project or os.getcwd())
    info = {"ok": True, "command": "doctor", "project": project,
            "cwd": os.getcwd(), "python": sys.executable,
            "python_version": "%d.%d.%d" % sys.version_info[:3]}

    deps = {}
    for mod in ("openai", "httpx", "requests", "dotenv", "numpy",
                "fastembed", "onnxruntime"):
        try:
            __import__(mod)
            deps[mod] = True
        except Exception:
            deps[mod] = False
    info["deps"] = deps
    # numpy 仅为向量记忆（memory_vector）所用，缺失时自动降级，不算必需
    info["deps_required_ok"] = all(deps[m] for m in
                                   ("openai", "httpx", "requests", "dotenv"))
    info["vector_memory"] = bool(deps["fastembed"] and deps["onnxruntime"])

    cfg_file = config_path(project, args.config)
    info["config_file"] = cfg_file
    # 让 .env 生效（与运行时行为一致），否则会把「key 配在 .env 里」误报成未配置
    try:
        from dotenv import load_dotenv
        for _p in (os.path.join(project, ".env"),):
            if os.path.isfile(_p):
                load_dotenv(_p)
                break
    except Exception:
        pass
    if os.path.isfile(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as fh:
                cfg = json.load(fh)
            ai = cfg.get("ai", {}) or {}
            env_key = _first_env(_AI_KEY_ENVS)
            env_base = _first_env(_AI_BASE_ENVS)
            env_model = _first_env(_AI_MODEL_ENVS)
            info["ai"] = {"provider": ai.get("provider") or _first_env(_AI_PROVIDER_ENVS),
                          "model": ai.get("model") or env_model,
                          "api_base": ai.get("api_base") or env_base,
                          "api_key_configured": bool(ai.get("api_key") or env_key),
                          "api_key_source": ("config.json" if ai.get("api_key")
                                             else (".env/环境变量" if env_key else None))}
            info["onboarding_done"] = bool(cfg.get("_onboarding_done"))
        except Exception as exc:
            info["ok"] = False
            info["config_error"] = str(exc)
    else:
        info["ok"] = False
        info["config_error"] = "找不到 config.json"

    # 数据位置以 core.paths 为准：记忆已经不在代码树里了
    if project not in sys.path:
        sys.path.insert(0, project)
    try:
        import core.paths as _paths
        home, data_dir = _paths.home_root(), _paths.data_root()
    except Exception:
        home, data_dir = project, os.path.join(project, "data")
    info["data_root"] = home
    info["db_file"] = os.path.join(data_dir, "db", "soulmate.db")
    info["db_exists"] = os.path.isfile(info["db_file"])
    # 顺着上层找最近的**已存在**目录再判可写。os.access 对不存在的路径恒返回
    # False，而新手第一次 doctor 时数据目录还没被创建 —— 那份「数据目录不可写」
    # 的假警报刚好出现在最不能出错的时候：看着像权限问题，实际只是还没建，
    # 会把人引去 chmod。X_OK 是必需的：往目录里写文件需要可进入该目录。
    probe = data_dir
    while not os.path.isdir(probe) and os.path.dirname(probe) != probe:
        probe = os.path.dirname(probe)
    info["data_writable"] = os.access(probe, os.W_OK | os.X_OK)

    if not info["deps_required_ok"]:
        info["ok"] = False
        info["hint"] = "缺少必需依赖，运行 `soulviaictl.py setup`"
        return _emit(info, EXIT_ERR)

    # 真正把引擎 import 起来（模块级，不启动后台线程）
    t0 = time.time()
    try:
        bootstrap(project)
        import soulviai  # noqa: F401
        info["engine_import"] = "ok"
        info["engine_import_ms"] = int((time.time() - t0) * 1000)
    except Exception as exc:
        info["ok"] = False
        info["engine_import"] = "failed"
        info["engine_error"] = "%s: %s" % (type(exc).__name__, exc)
        info["traceback_tail"] = traceback.format_exc().strip().splitlines()[-6:]
        return _emit(info, EXIT_ERR)

    # 真实打一次模型接口（默认不做，避免每次自检都花额度）
    if getattr(args, "check_api", False):
        try:
            from core import ai as ai_module
            ai_module.load_config(cfg_file)
            ai_module.init_client()
            mark = noise_mark()
            reply = ai_module.chat(system_prompt="你是连通性探针，只回复两个字：正常",
                                   user_message="连通性测试")
            probe_err = _api_error(_noise_since(mark))
            if probe_err:
                info["ok"] = False
                info["api_probe"] = {"ok": False, "error": probe_err}
            else:
                info["api_probe"] = {"ok": True, "reply": (reply or "")[:80]}
        except Exception as exc:
            info["ok"] = False
            info["api_probe"] = {"ok": False,
                                 "error": "%s: %s" % (type(exc).__name__, exc)}
        if not info.get("api_probe", {}).get("ok"):
            info["hint"] = ("模型后端不可用：检查 ai.api_key / ai.api_base / ai.model"
                            "（或环境变量 AI_API_KEY / AI_API_BASE / AI_MODEL / AI_PROVIDER；"
                            "401 多为 key 失效或额度耗尽）。")
    return _emit(info, EXIT_OK if info["ok"] else EXIT_ERR)


def cmd_init(args):
    engine = load_engine(args.user, args.project, args.config, warmup=args.warmup)
    state = engine.get_state(args.user)
    return _emit({"ok": True, "command": "init", "user_id": args.user,
                  "warmed_up": bool(args.warmup),
                  "personality_stage": state.get("personality_stage"),
                  "life_state": state.get("life_state"),
                  "mind_summary": state.get("mind_summary")})


def cmd_check(args):
    """深度自检：把子系统真跑一遍，断言它们真的留下了副作用。

    与 `selftest` 的分工：selftest 验「命令 → 引擎 → 管道」这条链路通不通；
    这里验「跑完之后该有的东西有没有留下」。之所以需要，是因为本仓库近一半的
    try 块是 `except: pass` —— 子系统可以静默变成尸体而没有任何症状（实测深夜
    复盘曾因一句多余的局部 import 崩在第二步，此后所有日级成长一次没跑过）。

    全程用假模型，不花额度、不依赖外网。检查清单见 engine.core.selfcheck。
    """
    engine = load_engine(args.user, args.project, args.config)
    install_fake_ai(args.fake_reply or "嗯…我在。")
    from engine.core import selfcheck
    result = selfcheck.run(engine, args.user)
    result["command"] = "check"
    result["user_id"] = args.user
    result["note"] = ("假模型下的深度自检：只验证各子系统是否真的产生了副作用，"
                      "不代表回复质量；模型连通性请用 `doctor --check-api`。")
    return _emit(result, EXIT_OK if result.get("ok") else EXIT_ERR)


def install_fake_ai(text):
    """把模型后端替换成固定回复。

    只用于 `selftest` 之类不花额度、不依赖外网的链路自检：
    验证"命令 → 引擎 → 管道 → 多段回复"这条通路是否通畅，
    而不去验证模型本身。生产调用绝不使用。
    """
    from core import ai as ai_module

    def _fake_chat(system_prompt, user_message, temperature=None,
                   conversation_history=None):
        return text

    def _fake_stream(system_prompt, user_message, temperature=None,
                     conversation_history=None):
        yield text

    ai_module.chat = _fake_chat
    ai_module.chat_stream = _fake_stream
    return True


def run_chat(engine, user, text, verbose=False, env="", env_json=""):
    """执行一轮对话，返回 (payload, exit_code)。冷启动与常驻服务共用。

    env:      环境上下文自由文本（如「上海 小雨 24°C」），可为空。
    env_json: 结构化环境上下文（JSON 字符串或 dict），优先于 env。
    """
    t0 = time.time()
    try:
        # 每轮开头把环境来源重置为「引擎可写」。不重置会有个隐性锁死：某一轮
        # 调用方注入过 env，来源就一直停在 caller，env_source.apply() 之后永远
        # 让步，引擎自采的天气再也进不来。
        # 代价是「上一轮说过、这一轮没说」的显式位置会被引擎自采覆盖 —— 这是
        # 有意的：--env 的契约本来就是「每轮注入」，否则没法区分用户是不是走开了。
        from engine.social import sensors as _sensors
        _sensors.reset_origin()
    except Exception:
        pass
    if env or env_json:
        try:
            from engine.social import sensors
            applied = False
            if env_json:
                try:
                    data = json.loads(env_json) if isinstance(env_json, str) else env_json
                    applied = sensors.set_external_context_json(data, origin="caller")
                except Exception:
                    applied = False
            if not applied and env:
                sensors.set_external_context(env, origin="caller")
        except Exception:
            pass
    from engine.core.chat_pipeline import ChatPipeline
    pipeline = ChatPipeline(engine)
    mark = noise_mark()          # 本轮水位：只认这次请求产生的引擎输出
    try:
        response = pipeline.run(user, text)
    except Exception as exc:
        return ({"ok": False, "command": "chat", "status": "error", "user_id": user,
                 "error_code": "engine_exception",
                 "error": "%s: %s" % (type(exc).__name__, exc),
                 "traceback_tail": traceback.format_exc().strip().splitlines()[-6:]},
                EXIT_ERR)

    elapsed = int((time.time() - t0) * 1000)
    lines = _noise_since(mark)
    api_err = _api_error(lines)
    diag = {
        "silence_reason": _silence_reason(lines),
        "api_error": api_err,
        "stage_errors": list(getattr(pipeline, "_stage_errors", []) or []),
        "recovery_mode": bool(getattr(pipeline, "_recovery_mode", False)),
        "user_attitude": getattr(pipeline, "user_attitude", "") or "",
    }
    if verbose:
        diag["comprehension"] = getattr(pipeline, "comprehension", {}) or {}
        diag["mind"] = getattr(pipeline, "mind_data", {}) or {}
        diag["engine_log_tail"] = [l.strip() for l in lines if l.strip()][-20:]

    if (response is None or response == "") and api_err:
        # 空回复来自模型后端失败，不是人格沉默 —— 必须如实报错
        return ({"ok": False, "command": "chat", "status": "backend_error",
                 "user_id": user, "parts": [], "text": "",
                 "elapsed_ms": elapsed, "error_code": _api_error_code(api_err),
                 "error": api_err, "diagnostics": diag,
                 "hint": "模型后端调用失败（多为 ai.api_key 失效或 ai.api_base / "
                         "ai.model 配置错误）。修好后 `doctor --check-api` 复验。"},
                EXIT_ERR)

    if response is None or response == "":
        return ({"ok": True, "command": "chat", "status": "silent", "user_id": user,
                 "parts": [], "text": "", "elapsed_ms": elapsed,
                 "diagnostics": diag,
                 "note": "ta 这次选择不回复（生命门控/情绪沉默/选择性回复），"
                         "这是人格的一部分，不是故障。"}, EXIT_SILENT)
    if response == "__QUEUED__":
        return ({"ok": True, "command": "chat", "status": "queued", "user_id": user,
                 "parts": [], "text": "", "elapsed_ms": elapsed,
                 "diagnostics": diag,
                 "note": "回复已入待发队列，用 `drain` 取出。"}, EXIT_QUEUED)

    parts = _split_parts(response)
    payload = {"ok": True, "command": "chat", "status": "ok", "user_id": user,
               "parts": parts, "text": "\n".join(parts), "elapsed_ms": elapsed}
    if verbose:
        payload["diagnostics"] = diag
    return payload, EXIT_OK


def cmd_chat(args):
    engine = load_engine(args.user, args.project, args.config)
    if args.fake_reply:
        install_fake_ai(args.fake_reply)
    payload, code = run_chat(engine, args.user, args.text, verbose=args.verbose,
                             env=getattr(args, "env", ""),
                             env_json=getattr(args, "env_json", ""))
    return _emit(payload, code)


def _state_payload(engine, user):
    """state 的统一 payload —— 冷启动与常驻服务共用，避免两处实现漂移。"""
    state = engine.get_state(user)

    stage = state.get("personality_stage") or ""
    phase = ""
    try:
        from core import database as db
        phase = (db.get_life(user) or {}).get("current_phase", "") or ""
    except Exception:
        pass
    try:
        from engine.social import sensors
        weather = sensors.get_external_flags()
    except Exception:
        weather = {}

    return {
        "user_id": user,
        # ── 人类可读（中文）──
        "personality_stage": state.get("personality_stage"),
        "life_state": state.get("life_state"),
        "mind_summary": state.get("mind_summary"),
        "fate_summary": state.get("fate_summary"),
        "recent_memories": state.get("recent_memories"),
        "identity": state.get("identity"),
        # ── 语言中立代码（Agent 可据此用任意语言渲染，无需翻译表）──
        "codes": {
            "personality_stage": _STAGE_CODES.get(stage, ""),
            "life_phase": _PHASE_CODES.get(phase, ""),
            "env": weather,
        },
    }


def cmd_state(args):
    engine = load_engine(args.user, args.project, args.config)
    payload = {"ok": True, "command": "state"}
    payload.update(_state_payload(engine, args.user))
    if args.raw:
        try:
            from engine import mind as mind_module
            payload["mind_raw"] = mind_module.get_mind(args.user)
        except Exception as exc:
            payload["mind_raw_error"] = str(exc)
        try:
            from engine import life as life_module
            payload["life_raw"] = life_module.get_life_state_text(args.user)
        except Exception:
            pass
    return _emit(payload)


def cmd_env(args):
    """查看 / 刷新环境信息（定位、天气）。

    默认读缓存（命中 TTL 就不联网）；--refresh 强制重取一次并注入 sensors。
    数据源与开关见 engine/engine/social/env_source.py 与 config.json:env_auto。
    """
    bootstrap(args.project)
    payload = {"ok": True, "command": "env", "user": args.user}
    try:
        from engine.social import env_source
    except Exception as exc:
        payload["ok"] = False
        payload["error"] = "环境模块加载失败：%s" % exc
        return _emit(payload)

    try:
        if getattr(args, "refresh", False):
            env_source.apply(env_source.refresh(), force=True)
        else:
            env_source.ensure()
    except Exception as exc:
        payload["ok"] = False
        payload["error"] = str(exc)
        return _emit(payload)

    payload.update(env_source.status())
    payload["text"] = env_source.text()
    return _emit(payload)


# ── 可调参数总览（soulviaictl config）─────────────────────────
def _config_cell(value) -> str:
    """把任意配置值渲染成单行短文本。"""
    if isinstance(value, bool):
        return "开" if value else "关"
    if isinstance(value, (int, float)):
        return "%g" % value
    if isinstance(value, str):
        return value or "（空）"
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _config_sections(cfg_module, raw):
    """按元数据清单组装「当前值 + 来源 + 说明」。

    来源分三种，它决定用户该去哪儿改：
      config.json          写在这个文件里，删掉就回默认
      .env / 环境变量       优先级高于 config.json
      默认                 代码里的默认值，想改就在 config.json 里显式写一个
    清单本身在 core/config.py 的 TUNABLES —— 说明文字只有那一份。
    """
    merged = cfg_module.get_section("")
    out = []
    for section, spec in cfg_module.TUNABLES.items():
        cur = merged if section == "" else (merged.get(section) or {})
        exp = raw if section == "" else (raw.get(section) or {})
        items = []
        for key, meta in spec.items():
            if key.startswith("_"):
                continue
            env_hit = ""
            for name in (meta.get("env") or ()):
                if os.environ.get(name):
                    env_hit = name
                    break
            explicit = key in exp and exp.get(key) not in (None, "", {}, [])
            if env_hit:
                source = ".env/%s" % env_hit
            elif explicit:
                source = "config.json"
            else:
                source = "默认"
            if meta.get("secret"):
                # 密钥只报「有没有」，绝不回显 —— 这个视图可能被截图、被贴群里
                shown = "已设置" if (env_hit or explicit) else "未设置"
            else:
                shown = _config_cell(cur.get(key, meta.get("default")))
            items.append({"key": key, "value": shown, "source": source,
                          "desc": meta.get("desc", ""),
                          "secret": bool(meta.get("secret"))})
        out.append({"section": section, "title": spec.get("_title") or section,
                    "items": items})
    return out


def _render_config(sections, cfg_file) -> str:
    lines = ["", "  soulviai · 可调参数", "  " + "─" * 60,
             "  配置文件  %s" % cfg_file,
             "  只列「用户 / 运维值得动」的键；引擎内部算法参数不在内。", ""]
    for sec in sections:
        # 顶层段的 section 是空串，标题本身就是「基本」，别打成【基本】基本
        lines.append("【%s】" % sec["title"] if not sec["section"]
                     else "【%s】%s" % (sec["section"], sec["title"]))
        for it in sec["items"]:
            # 键名都是 ASCII，所以这一列能对齐；值可能出现中文（不保证对齐）
            lines.append("  %-22s = %s（%s）  %s"
                         % (it["key"], it["value"], it["source"], it["desc"]))
        lines.append("")
    lines.append("  改完不必重启：常驻服务跑 `soulviaictl reload-ai`，"
                 "其它入口重启即可。")
    lines.append("")
    return "\n".join(lines)


def cmd_config(args):
    """列出可调参数：当前值、来源、说明。只读，不动任何文件。"""
    bootstrap(args.project)
    payload = {"ok": True, "command": "config"}
    try:
        from core import config as cfg_module
        from core import paths as _paths
    except Exception as exc:
        payload["ok"] = False
        payload["error"] = "配置模块加载失败：%s" % exc
        return _emit(payload)

    # reload 而不是 load：常驻服务进程里 load() 只跑一次，不停一下会读到启动时那份
    try:
        cfg_module.reload()
    except Exception:
        pass

    cfg_file = _paths.config_json_path()
    payload["config_file"] = cfg_file
    raw = {}
    try:
        with open(cfg_file, encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        raw = {}

    try:
        sections = _config_sections(cfg_module, raw)
    except Exception as exc:
        payload["ok"] = False
        payload["error"] = "组装参数清单失败：%s" % exc
        return _emit(payload)

    payload["sections"] = sections
    payload["text"] = _render_config(sections, cfg_file)
    return _emit(payload)


def cmd_pending(args):
    bootstrap(args.project)
    from core import database as db
    db.init_db()
    rows = db.get_pending_messages(args.user, max_count=args.limit)
    items = []
    for row in rows or []:
        items.append({
            "id": row.get("id"),
            "content": row.get("content"),
            "msg_type": row.get("msg_type"),
            "created_at": row.get("created_at"),
            "thinking_delay_seconds": row.get("thinking_delay_seconds", 0),
        })
    return _emit({"ok": True, "command": "pending", "user_id": args.user,
                  "count": len(items),
                  "total": db.count_pending_messages(args.user),
                  "messages": items})


def cmd_drain(args):
    bootstrap(args.project)
    from core import database as db
    db.init_db()
    rows = db.get_pending_messages(args.user, max_count=args.limit) or []
    items = []
    for row in rows:
        content = row.get("content") or ""
        items.append({
            "id": row.get("id"),
            "msg_type": row.get("msg_type"),
            "created_at": row.get("created_at"),
            # 与 /drain 端点、pending 保持一致：投递方要靠它判断「延迟还没到」，
            # 少了这个字段冷启动路径会把该等的消息立刻发出去。
            "thinking_delay_seconds": row.get("thinking_delay_seconds", 0),
            "parts": _split_parts(content),
            "text": "\n".join(_split_parts(content)),
        })
        if not args.peek:
            try:
                db.mark_message_delivered(row.get("id"))
            except Exception:
                pass
    return _emit({"ok": True, "command": "drain", "user_id": args.user,
                  "delivered": 0 if args.peek else len(items),
                  "acked": not args.peek,
                  "remaining": db.count_pending_messages(args.user),
                  "messages": items})


def cmd_ack(args):
    """确认指定待发消息已送达（配对 `drain --peek` 用）。

    `drain --peek` 只看不标记，方便调用方自己判断哪些真的发出去了；确认由本
    命令补上，这样「延迟未到」「发送失败」的消息会留在队列里等待重试，而不是
    像直接 `drain` 那样一取走就丢。
    """
    bootstrap(args.project)
    from core import database as db
    db.init_db()
    ids = _parse_ids(getattr(args, "ids", None) or [])
    if not ids:
        return _emit({"ok": False, "command": "ack",
                      "error": "没有可确认的消息 id",
                      "hint": "用法：ack --ids 12,13（id 从 drain --peek 的输出里取）"},
                     EXIT_ERR)
    acked = []
    for mid in ids:
        try:
            db.mark_message_delivered(mid)
            acked.append(mid)
        except Exception as exc:
            print("[soulviai] ack 失败 id=%s: %s" % (mid, exc), file=sys.stderr)
    return _emit({"ok": True, "command": "ack", "user_id": args.user,
                  "acked": len(acked), "ids": acked,
                  "remaining": db.count_pending_messages(args.user)})


def _parse_ids(raw):
    """把 ["12,13", "14"] 或 [12, 13] 统一成 [12, 13]（去重保序）。"""
    out = []
    for item in raw:
        for piece in str(item).replace(" ", "").split(","):
            if not piece:
                continue
            try:
                mid = int(piece)
            except ValueError:
                continue
            if mid not in out:
                out.append(mid)
    return out


def cmd_tick(args):
    engine = load_engine(args.user, args.project, args.config)
    from core import database as db
    from engine.behavior import autonomous as autonomous_module
    before = db.count_pending_messages(args.user)
    autonomous_module.load_engine_config()
    triggered = []
    try:
        for uid in [args.user]:
            autonomous_module._try_generate_thoughts(uid)
    except Exception as exc:
        return _emit({"ok": False, "command": "tick", "error": str(exc),
                      "traceback_tail": traceback.format_exc().strip().splitlines()[-6:]},
                     EXIT_ERR)
    after = db.count_pending_messages(args.user)
    rows = db.get_pending_messages(args.user, max_count=5) or []
    for row in rows:
        triggered.append({"id": row.get("id"), "msg_type": row.get("msg_type"),
                          "text": "\n".join(_split_parts(row.get("content") or ""))})
    return _emit({"ok": True, "command": "tick", "user_id": args.user,
                  "pending_before": before, "pending_after": after,
                  "new_thoughts": max(0, after - before),
                  "pending_preview": triggered})


# ────────────────────────────────────────────────────────────
# 常驻服务
# ────────────────────────────────────────────────────────────
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
AUTONOMOUS_TRIP_FAILS = 6      # 窗口内模型失败达到这个数就暂停自主思考
AUTONOMOUS_TRIP_WINDOW = 900   # 失败统计窗口（秒）

# ── 鉴权 ──
# 常驻服务能读 ta 的全部记忆、能发消息，必须挡一道。这里用共享 token：
# 首次启动生成并落到 0600 的文件里，客户端自动读取，不需要人工配置。
TOKEN_HEADER = "X-Soul-Token"
TOKEN_ENV = "SOULVIAI_DAEMON_TOKEN"
TOKEN_FILE_NAME = ".soulviai-daemon.token"


def token_file_path(project, explicit=None):
    """token 文件位置：显式 > config.yaml 的 daemon_token_file > 项目内默认。"""
    cand = explicit or os.environ.get(TOKEN_ENV + "_FILE")
    if cand:
        return os.path.abspath(os.path.expanduser(cand))
    return os.path.join(project, TOKEN_FILE_NAME)


def load_or_create_token(project, explicit=None):
    """读出已有 token；没有就生成一个并写成 0600。失败返回 (None, 路径, 原因)。"""
    path = token_file_path(project, explicit)
    # 环境变量优先：客户端也认它，服务端不认就会两边不一致（客户端 401 而用户
    # 明明"配好了"）。设了就直接用，不碰文件。
    env_tok = (os.environ.get(TOKEN_ENV) or "").strip()
    if env_tok:
        return env_tok, path, None
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                tok = fh.read().strip()
        except Exception as exc:
            return None, path, "读取 token 文件失败: %s" % exc
        if tok:
            # 已有文件也要收权限：可能是别的方式（cp / git / 手动 echo）建出来的
            try:
                if os.stat(path).st_mode & 0o077:
                    os.chmod(path, 0o600)
            except Exception:
                pass
            return tok, path, None
        # 空文件=上次写坏，重新生成
    tok = secrets.token_urlsafe(32)
    parent = os.path.dirname(path)
    try:
        if parent:
            os.makedirs(parent, exist_ok=True)
        # 先按 0600 建文件再写，避免出现「已存在但全局可读」的时间窗
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(tok + "\n")
    except Exception as exc:
        return None, path, "写入 token 文件失败（%s）: %s" % (path, exc)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass
    return tok, path, None


def request_token(headers):
    """从请求头里取 token：X-Soul-Token 优先，兼容 Authorization: Bearer。"""
    tok = (headers.get(TOKEN_HEADER) or "").strip()
    if tok:
        return tok
    auth = (headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""

# 这几类不是「偶发抖动」而是配置/额度问题，重试一万次也不会好，立刻停
FATAL_BACKEND_MARKERS = ("Authentication Fails", "invalid_api_key",
                         "Insufficient Balance", "401")


def _is_loopback(host):
    return (host or "").strip().lower() in LOOPBACK_HOSTS


def _backend_breaker():
    """读取 ai 层的全局熔断状态，供 /health 展示。

    熔断器在 core/ai.py：它挡的是**所有**后台调用方（调度器里 5 个任务及其内部触发
    的博弈/复盘）。本文件的 watchdog 只负责停自主思考引擎并记录人类可读的归因。
    两者互补——熔断让调用立刻停、日志立刻静，watchdog 让人看得懂发生了什么。
    """
    try:
        from core import ai as ai_module
        return ai_module.backend_breaker()
    except Exception:
        return {"tripped": False, "reason": "", "since": 0.0, "suppressed": 0}


class _BackendWatchdog(threading.Thread):
    """模型接口持续失败时，自动停掉自主思考引擎。

    自主思考是后台定时任务：key 失效时它会一直调用、一直报 401，既刷爆日志，
    也让「这次没回复到底是人格沉默还是后端挂了」无法归因。这里只看新产生的输出，
    认证/额度类错误立即停，其余错误达到阈值再停，并把结论记进 /health。
    """

    def __init__(self, status):
        threading.Thread.__init__(self, daemon=True, name="soulviai-backend-watchdog")
        self.status = status
        self._stop = threading.Event()
        self._fails = []

    def run(self):
        from engine.behavior import autonomous as autonomous_module
        mark = noise_mark()
        while not self._stop.wait(30):
            new = _noise_since(mark)
            mark = noise_mark()
            fails = [ln for ln in new
                     if "API 调用失败" in ln or "background_chat 失败" in ln]
            if not fails:
                continue
            fatal = any(m in ln for ln in fails for m in FATAL_BACKEND_MARKERS)
            now = time.time()
            self._fails = [t for t in self._fails if now - t < AUTONOMOUS_TRIP_WINDOW]
            self._fails += [now] * len(fails)
            if not fatal and len(self._fails) < AUTONOMOUS_TRIP_FAILS:
                continue
            try:
                autonomous_module.stop_thought_engine()
            except Exception:
                pass
            self.status["autonomous"] = False
            self.status["suspended_reason"] = (
                "模型接口不可用（%s），已暂停自主思考引擎；"
                "其余后台任务的 LLM 调用已由 core.ai 熔断器一并短路，不再刷日志。"
                "修好 ai.api_key / ai.model 后跑 `soulviaictl reload-ai` 就地恢复，"
                "不必重启整个服务。"
                % ("认证或额度错误" if fatal
                   else "%d 秒内失败 %d 次" % (AUTONOMOUS_TRIP_WINDOW, len(self._fails))))
            print("[soulviai] ⚠️  %s" % self.status["suspended_reason"], file=sys.stderr)
            return

    def stop(self):
        self._stop.set()


def cmd_serve(args):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse, parse_qs

    if not _is_loopback(args.host) and not getattr(args, "allow_remote", False):
        return _emit({"ok": False, "command": "serve",
                      "error": "拒绝监听非回环地址 %s。" % args.host,
                      "hint": "确有需要请显式加 --allow-remote；token 是明文 HTTP 传输，"
                              "对外暴露请再加一层 HTTPS 反向代理。"}, EXIT_ERR)

    project = bootstrap(args.project)

    # 鉴权是 fail-closed：拿不到 token 就不启动，绝不允许「静默无鉴权」。
    token, token_path, token_err = load_or_create_token(
        project, getattr(args, "token_file", None))
    if token_err:
        return _emit({"ok": False, "command": "serve",
                      "error": "无法准备鉴权 token：%s" % token_err,
                      "hint": "指定可写路径：serve --token-file <路径>，"
                              "或用环境变量 %s 直接给定 token。" % TOKEN_ENV},
                     EXIT_ERR)

    engine = load_engine(args.user, project, args.config)
    cfg_file = config_path(project, getattr(args, "config", None))
    lock = threading.Lock()
    started_at = time.time()
    status = {"autonomous": False, "suspended_reason": None}
    _auto = {"module": None}

    def start_autonomous():
        """启动（或重启）自主思考引擎与它的 watchdog。

        抽出来是因为 /config/reload 也要用它：watchdog 在模型接口持续失败时
        会把引擎停掉、自己也退出，reload 修好接口后得能重新拉起来，
        否则就是「配置改好了、服务还在停摆，只能重启」。
        """
        if args.no_autonomous:
            return False
        try:
            if _auto["module"] is None:
                from engine.behavior import autonomous as auto_module
                _auto["module"] = auto_module
            auto_module = _auto["module"]
            auto_module.load_engine_config()
            auto_module.start_thought_engine()
            status["autonomous"] = True
            status["suspended_reason"] = None
            _BackendWatchdog(status).start()
            return True
        except Exception as exc:
            print("[soulviai] 自主思考引擎启动失败: %s" % exc, file=sys.stderr)
            return False

    start_autonomous()

    print("[soulviai] 常驻服务已就绪 http://%s:%d  (project=%s, user=%s, autonomous=%s, "
          "auth=token@%s)" % (args.host, args.port, project, args.user,
                              status["autonomous"], token_path), file=sys.stderr)

    class Handler(BaseHTTPRequestHandler):
        server_version = "soulviai/" + ("1.0")

        def log_message(self, fmt, *a):  # 降噪，交给 stderr → 日志文件
            pass

        def _valid_token(self):
            """常量时间比较，避免用响应耗时逐字节猜 token。"""
            got = request_token(self.headers)
            return bool(got) and hmac.compare_digest(got, token)

        def _deny(self):
            """鉴权失败。故意回 401 而非 404——让调用方能区分
            「端口被别的程序占了」和「是我们的服务但 token 不对」。"""
            return self._send({"ok": False, "service": "soulviai",
                               "error": "unauthorized", "auth_required": True,
                               "hint": "带上 %s 头，或 Authorization: Bearer <token>；"
                                       "token 由启动时生成，落在项目目录下的 %s（0600）"
                                       % (TOKEN_HEADER, TOKEN_FILE_NAME)}, 401)

        def _send(self, payload, code=200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            raw = self.rfile.read(length)
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception:
                return {}

        # ── GET ──
        def do_GET(self):
            parsed = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            auth_ok = self._valid_token()
            # /health 无 token 也回，但只回「我是谁、要鉴权」；
            # 项目路径 / pid / 沉默原因这些不泄露给同机器的其他用户。
            if parsed.path == "/health" and not auth_ok:
                return self._send({"ok": True, "service": "soulviai",
                                   "auth_required": True})
            if not auth_ok:
                return self._deny()
            try:
                if parsed.path == "/health":
                    return self._send({
                        "ok": True, "service": "soulviai", "pid": os.getpid(),
                        "project": project, "uptime_seconds": int(time.time() - started_at),
                        "autonomous": status["autonomous"],
                        "suspended_reason": status["suspended_reason"],
                        "backend_breaker": _backend_breaker(),
                        "auth_required": True, "default_user": args.user})
                if parsed.path == "/state":
                    with lock:
                        payload = _state_payload(engine, query.get("user_id", args.user))
                    payload["ok"] = True
                    payload["command"] = "state"
                    payload["source"] = "daemon"
                    return self._send(payload)
                if parsed.path == "/env":
                    try:
                        from engine.social import env_source
                        if query.get("refresh") in ("1", "true", "yes"):
                            env_source.apply(env_source.refresh(), force=True)
                        else:
                            env_source.ensure()
                        payload = {"ok": True, "command": "env",
                                   "source": "daemon"}
                        payload.update(env_source.status())
                        payload["text"] = env_source.text()
                    except Exception as exc:
                        payload = {"ok": False, "command": "env",
                                   "error": str(exc)}
                    return self._send(payload)
                if parsed.path == "/pending":
                    from core import database as db
                    user = query.get("user_id", args.user)
                    limit = int(query.get("limit") or 10)
                    rows = db.get_pending_messages(user, max_count=limit) or []
                    return self._send({"ok": True, "command": "pending", "source": "daemon",
                                       "user_id": user, "count": len(rows),
                                       "total": db.count_pending_messages(user),
                                       "messages": rows})
            except Exception as exc:
                return self._send({"ok": False, "error": str(exc)}, 500)
            return self._send({"ok": False, "error": "not found", "path": parsed.path}, 404)

        # ── POST ──
        def do_POST(self):
            path = urlparse(self.path).path
            body = self._body()
            if not self._valid_token():
                # /chat 能读记忆、/shutdown 能停服务、/tick 会真的花模型额度
                return self._deny()
            try:
                if path == "/shutdown":
                    self._send({"ok": True, "command": "shutdown"})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                if path == "/chat":
                    user = body.get("user_id") or args.user
                    text = body.get("text") or ""
                    if not text.strip():
                        return self._send({"ok": False, "error": "text 为空"}, 400)
                    with lock:
                        payload, _code = run_chat(engine, user, text,
                                                  verbose=bool(body.get("verbose")),
                                                  env=body.get("env") or "",
                                                  env_json=body.get("env_json") or "")
                    payload["source"] = "daemon"
                    return self._send(payload)
                if path == "/drain":
                    from core import database as db
                    user = body.get("user_id") or args.user
                    limit = int(body.get("limit") or 5)
                    ack = str(body.get("ack", "true")).lower() != "false"
                    rows = db.get_pending_messages(user, max_count=limit) or []
                    items = []
                    for row in rows:
                        content = row.get("content") or ""
                        items.append({"id": row.get("id"), "msg_type": row.get("msg_type"),
                                      "created_at": row.get("created_at"),
                                      "thinking_delay_seconds":
                                          row.get("thinking_delay_seconds", 0),
                                      "parts": _split_parts(content),
                                      "text": "\n".join(_split_parts(content))})
                        if ack:
                            try:
                                db.mark_message_delivered(row.get("id"))
                            except Exception:
                                pass
                    return self._send({"ok": True, "command": "drain", "source": "daemon",
                                       "user_id": user, "acked": ack,
                                       "delivered": 0 if not ack else len(items),
                                       "remaining": db.count_pending_messages(user),
                                       "messages": items})
                if path == "/ack":
                    # 配合 drain ack=false 用：调用方自己判断哪些消息真的送出去了
                    # （比如延迟未到的要留队），只确认那几条。
                    from core import database as db
                    user = body.get("user_id") or args.user
                    ids = _parse_ids(body.get("ids") or [])
                    acked = 0
                    for mid in ids:
                        try:
                            db.mark_message_delivered(mid)
                            acked += 1
                        except Exception:
                            pass
                    return self._send({"ok": True, "command": "ack", "source": "daemon",
                                       "user_id": user, "acked": acked, "ids": ids,
                                       "remaining": db.count_pending_messages(user)})
                if path == "/tick":
                    from core import database as db
                    from engine.behavior import autonomous as autonomous_module
                    user = body.get("user_id") or args.user
                    before = db.count_pending_messages(user)
                    with lock:
                        autonomous_module._try_generate_thoughts(user)
                    after = db.count_pending_messages(user)
                    return self._send({"ok": True, "command": "tick", "source": "daemon",
                                       "user_id": user, "pending_before": before,
                                       "pending_after": after,
                                       "new_thoughts": max(0, after - before)})
                if path == "/init":
                    user = body.get("user_id") or args.user
                    with lock:
                        engine.ensure_user(user)
                        if body.get("warmup"):
                            try:
                                engine.warmup(user)
                            except Exception:
                                pass
                    return self._send({"ok": True, "command": "init", "source": "daemon",
                                       "user_id": user})
                if path == "/config/reload":
                    # 让运行中的常驻服务重新读 .env / config.json。
                    # 云端部署时注入环境变量、本地换了 key 或改了 .env，都靠它当场
                    # 生效 —— core/config.py 的 load() 只跑一次，不重载的话进程里
                    # 一直是启动时那份配置（典型症状：配置改了照样 401）。
                    from core import ai as ai_module
                    with lock:
                        result = ai_module.reload_ai(cfg_file)
                    if result.get("ok"):
                        result["autonomous_resumed"] = start_autonomous()
                    result["command"] = "config/reload"
                    result["source"] = "daemon"
                    return self._send(result, 200 if result.get("ok") else 500)
            except Exception as exc:
                return self._send({"ok": False, "error": str(exc),
                                   "traceback_tail": traceback.format_exc().strip().splitlines()[-6:]},
                                  500)
            return self._send({"ok": False, "error": "not found", "path": path}, 404)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            autonomous_module_off(status["autonomous"])
        except Exception:
            pass
    return _emit({"ok": True, "command": "serve", "stopped": True})


def autonomous_module_off(_flag):
    try:
        from engine.behavior import autonomous as autonomous_module
        autonomous_module.stop_thought_engine()
    except Exception:
        pass


# ────────────────────────────────────────────────────────────
def build_parser():
    p = argparse.ArgumentParser(prog="engine_bridge.py")
    p.add_argument("--project", help="项目根目录（默认当前目录）")
    p.add_argument("--config", help="配置文件路径（默认 <project>/config.json）")
    sub = p.add_subparsers(dest="command")

    d = sub.add_parser("doctor")
    d.add_argument("--user", default="default_user")
    d.add_argument("--check-api", action="store_true",
                   help="真实调用一次模型接口做连通性探测")
    d.set_defaults(func=cmd_doctor)

    i = sub.add_parser("init")
    i.add_argument("--user", default="default_user")
    i.add_argument("--warmup", action="store_true")
    i.set_defaults(func=cmd_init)

    ck = sub.add_parser("check",
                        help="深度自检：断言各子系统真的产生了副作用（假模型，不花额度）")
    ck.add_argument("--user", default="default_user")
    ck.add_argument("--fake-reply", help="替换模型的固定回复（默认内置一句）")
    ck.set_defaults(func=cmd_check)

    c = sub.add_parser("chat")
    c.add_argument("--user", default="default_user")
    c.add_argument("--text", required=True)
    c.add_argument("--env", default="",
                   help="环境上下文自由文本（如「上海 小雨 24°C」），由调用方注入")
    c.add_argument("--env-json", default="",
                   help="结构化环境上下文（JSON 字符串），优先于 --env")
    c.add_argument("--verbose", action="store_true",
                   help="附带理解层/心智/引擎日志诊断")
    c.add_argument("--fake-reply", help="仅自检用：把模型后端替换成固定回复")
    c.set_defaults(func=cmd_chat)

    cf = sub.add_parser("config")
    cf.set_defaults(func=cmd_config)

    s = sub.add_parser("state")
    s.add_argument("--user", default="default_user")
    s.add_argument("--raw", action="store_true")
    s.set_defaults(func=cmd_state)

    ev = sub.add_parser("env")
    ev.add_argument("--user", default="default_user")
    ev.add_argument("--refresh", action="store_true")
    ev.set_defaults(func=cmd_env)

    pd = sub.add_parser("pending")
    pd.add_argument("--user", default="default_user")
    pd.add_argument("--limit", type=int, default=10)
    pd.set_defaults(func=cmd_pending)

    dr = sub.add_parser("drain")
    dr.add_argument("--user", default="default_user")
    dr.add_argument("--limit", type=int, default=5)
    dr.add_argument("--peek", action="store_true")
    dr.set_defaults(func=cmd_drain)

    ak = sub.add_parser("ack", help="确认待发消息已送达（配对 drain --peek）")
    ak.add_argument("--user", default="default_user")
    ak.add_argument("--ids", action="append", required=True,
                    help="消息 id，可逗号分隔或重复传：--ids 12,13 --ids 14")
    ak.set_defaults(func=cmd_ack)

    t = sub.add_parser("tick")
    t.add_argument("--user", default="default_user")
    t.set_defaults(func=cmd_tick)

    v = sub.add_parser("serve")
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8765)
    v.add_argument("--user", default="default_user")
    v.add_argument("--no-autonomous", action="store_true")
    v.add_argument("--allow-remote", action="store_true",
                   help="允许监听非回环地址（token 走明文 HTTP，建议再套 HTTPS 反代）")
    v.add_argument("--token-file", default=None,
                   help="鉴权 token 文件位置（默认 <项目>/.soulviai-daemon.token）")
    v.set_defaults(func=cmd_serve)

    return p


def main():
    args = build_parser().parse_args()
    if not getattr(args, "command", None):
        build_parser().print_help()
        return EXIT_ERR
    try:
        return args.func(args)
    except Exception as exc:
        return _emit({"ok": False, "command": args.command,
                      "error": "%s: %s" % (type(exc).__name__, exc),
                      "traceback_tail": traceback.format_exc().strip().splitlines()[-8:]},
                     EXIT_ERR)


if __name__ == "__main__":
    sys.exit(main())
