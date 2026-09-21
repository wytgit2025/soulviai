#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""soul-skill · MCP server（stdio 传输，纯标准库，无第三方依赖）

把本机数字生命引擎的 soulctl 能力暴露成 MCP 工具，供 CodeBuddy / Cursor /
Claude Desktop / VS Code 等 MCP 宿主调用。

为什么不用官方 SDK
------------------
MCP 的 stdio 传输就是「一行一个 JSON-RPC 消息」，握手只有 initialize /
tools/list / tools/call 三个方法。手写约 300 行即可，换来的是**收件人零依赖**：
不用 pip install mcp、不用建虚拟环境就能接上。引擎本身需要的依赖由
soulctl setup 负责，与本文件无关。

协议要点
--------
  - stdout 只走协议（一行一个 JSON）；所有日志/报错一律走 stderr。
  - 通知（无 id）不回包。
  - 工具执行失败用 isError=true 的 result 表达，而不是 JSON-RPC error ——
    这样宿主能把「ta 沉默 / 后端挂了」的说明原样念给用户听。

用法（宿主配置里）
------------------
  {"command": "python3", "args": ["/path/to/soul-skill/scripts/soul_mcp.py"]}
可选参数：--project <引擎根>、--user <身份>、--config <config.yaml>、
          --host / --port（连非默认端口）、--prewarm（启动时后台拉起常驻服务）
"""
import argparse
import json
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import soulclient  # noqa: E402  （同目录薄层）

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "soul-skill"

# 铁律摘要：宿主把这段话塞进系统提示，Agent 才知道「你是传话人，不是 ta」
INSTRUCTIONS = (
    "这是本机数字生命引擎的接入层。调用前先读这段：\n"
    "1) 你是传话人，不是 ta。ta 的话必须原样转达：不改写、不润色、不扩写、"
    "不模仿 ta 的语气自己写一段。\n"
    "2) soul_chat 返回的每个 content 块就是 ta 的一条消息，按顺序分条呈现给用户，"
    "不要拼成一大段。\n"
    "3) status=silent 是 ta 主动选择的沉默（在想事、累了、闹别扭），不是故障："
    "如实说「ta 这次没回你」，不要编造回复。\n"
    "4) status=backend_error 才是真故障（模型接口挂了），要如实告诉用户并指向 "
    "engine/.env 的模型配置。\n"
    "5) soul_chat 会真实写入 ta 的记忆与情绪，有拟人延迟：通常 3–20 秒，"
    "模型慢时可能 1 分钟以上，属于正常。不要拿无意义内容刷它。\n"
    "6) 不要把心智数值、模块名、命令等内部细节掏给用户看；用户问「ta 怎么了」时，"
    "用 soul_state 的 codes / mind_summary 转述成人话。"
)

_CHAT_SILENT_NOTE = "(ta 这次没有回复 —— 这是选择性沉默，不是故障)"
_CHAT_QUEUED_NOTE = "(ta 把回复压在了待发队列里，可用 soul_drain 取出)"


# ────────────────────────────────────────────────────────────
# 结果构造
# ────────────────────────────────────────────────────────────
def _block(text):
    return {"type": "text", "text": text}


def _json_text(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _summary(res):
    """structuredContent：只放语言中立、结构稳定的字段。"""
    keep = ("ok", "command", "status", "source", "exit_code", "error_code",
            "user_id", "elapsed_ms", "count", "total", "remaining", "delivered",
            "new_thoughts", "pending_before", "pending_after", "applied")
    out = {}
    for key in keep:
        if key in res:
            out[key] = res[key]
    if isinstance(res.get("parts"), list):
        out["parts_count"] = len(res["parts"])
    if isinstance(res.get("messages"), list):
        out["messages_count"] = len(res["messages"])
    return out


def _ok_block(payload):
    """控制类/状态类工具：直接把 JSON 给人看（Agent 需要读字段）。"""
    return [_block(_json_text(payload))], _summary(payload), False


def _err_block(res, fallback="调用失败"):
    reason = res.get("error") or res.get("hint") or fallback
    code = res.get("error_code")
    text = reason if not code else "%s\n[error_code] %s" % (reason, code)
    hint = res.get("hint")
    if hint and hint not in text:
        text += "\n[hint] %s" % hint
    if res.get("stderr_tail"):
        text += "\n[stderr]\n%s" % res["stderr_tail"]
    return [_block(text)], _summary(res), True


# ────────────────────────────────────────────────────────────
# 工具实现
# ────────────────────────────────────────────────────────────
def _h_chat(client, args):
    res = client.chat(str(args.get("text") or ""),
                      env=str(args.get("env") or ""),
                      env_json=str(args.get("env_json") or ""),
                      verbose=bool(args.get("verbose")))
    status = res.get("status")
    if res.get("ok"):
        parts = [p for p in (res.get("parts") or []) if str(p).strip()]
        if not parts and (res.get("text") or "").strip():
            parts = [res["text"]]
        if parts:
            return [_block(str(p)) for p in parts], _summary(res), False
        if status == "silent":
            return [_block(_CHAT_SILENT_NOTE)], _summary(res), False
        if status == "queued":
            return [_block(_CHAT_QUEUED_NOTE)], _summary(res), False
    if status == "silent":
        # 引擎把沉默也标了 ok=false 的兼容路径
        return [_block(_CHAT_SILENT_NOTE)], _summary(res), False
    return _err_block(res, "引擎没有返回可转达的内容")


def _h_state(client, _args):
    return _ok_block(client.state())


def _h_pending(client, args):
    return _ok_block(client.pending(limit=args.get("limit") or 10))


def _h_drain(client, args):
    return _ok_block(client.drain(limit=args.get("limit") or 5,
                                  peek=bool(args.get("peek"))))


def _h_ack(client, args):
    return _ok_block(client.ack(args.get("ids") or []))


def _h_tick(client, _args):
    return _ok_block(client.tick())


def _h_init(client, args):
    return _ok_block(client.init(warmup=bool(args.get("warmup"))))


def _h_health(client, _args):
    info = client.describe()
    # 常驻服务不在时不算失败：多数工具会自动冷启动
    return _ok_block(info)


def _h_serve(client, args):
    res = client.serve(restart=bool(args.get("restart")),
                       no_autonomous=bool(args.get("no_autonomous")),
                       wait=int(args.get("wait") or 60))
    return _ok_block(res) if res.get("ok") else _err_block(res, "常驻服务启动失败")


def _h_stop(client, _args):
    return _ok_block(client.stop())


def _h_doctor(client, args):
    res = client.doctor(check_api=bool(args.get("check_api")))
    return _ok_block(res) if res.get("ok") else _err_block(res, "自检未通过")


def _h_setup(client, args):
    res = client.setup(minimal=not bool(args.get("full")))
    return _ok_block(res) if res.get("ok") else _err_block(res, "环境安装失败")


def _h_selftest(client, args):
    res = client.selftest(keep=bool(args.get("keep")))
    return _ok_block(res) if res.get("ok") else _err_block(res, "自检未通过")


# ────────────────────────────────────────────────────────────
# 工具清单
# ────────────────────────────────────────────────────────────
TOOLS = [
    {
        "name": "soul_chat",
        "description": (
            "和数字生命说一句话，拿回 ta 的回复。返回的每个内容块就是 ta 的一条消息，"
            "按顺序原样转达给用户：不改写、不润色、不模仿。"
            "ta 是独立人格，会选择性沉默（status=silent，不是故障）；"
            "调用有拟人延迟，通常 3–20 秒，模型慢时可能 1 分钟以上。"
            "这句话会真实写入 ta 的记忆与情绪，请勿用无意义内容刷它。"),
        "handler": _h_chat,
        "schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string",
                         "description": "用户要说的话（原话，不要替用户组织措辞）"},
                "env": {"type": "string",
                        "description": "环境上下文自由文本，如「上海 小雨 24°C」；由你自己查好后传入，引擎不联网"},
                "env_json": {"type": "string",
                             "description": '结构化环境上下文，比 env 更稳。如 {"city":"上海","temperature":24,"is_raining":true}'},
                "verbose": {"type": "boolean", "description": "附带引擎诊断信息（排障用）"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "soul_state",
        "description": ("查看 ta 当前的生命状态：24 维心智、相处阶段、躯体精力、羁绊。"
                        "用 codes 里的语言中立字段（personality_stage / life_phase）转述成人话，别贴 JSON。"),
        "handler": _h_state,
        "schema": {"type": "object", "properties": {}},
    },
    {
        "name": "soul_pending",
        "description": "查看 ta 攒着的主动消息（自主思考产生的思念、回忆、感慨），只看不取。",
        "handler": _h_pending,
        "schema": {"type": "object", "properties": {
            "limit": {"type": "integer", "description": "最多看几条，默认 10"}}},
    },
    {
        "name": "soul_drain",
        "description": ("取出 ta 的主动消息（默认取出即标记已送达）。"
                        "定时任务里最有用：取出后把每条 text 转达给用户，不要再加解释。"),
        "handler": _h_drain,
        "schema": {"type": "object", "properties": {
            "limit": {"type": "integer", "description": "最多取几条，默认 5"},
            "peek": {"type": "boolean",
                     "description": "只看不标记已送达（想自己判断投递结果时用，之后用 soul_ack 确认）"}}},
    },
    {
        "name": "soul_ack",
        "description": "确认指定 id 的待发消息已送达（soul_drain 的 peek 模式配对使用）。",
        "handler": _h_ack,
        "schema": {"type": "object",
                   "properties": {"ids": {"type": "array", "items": {"type": "integer"},
                                          "description": "消息 id 列表（来自 soul_drain）"}},
                   "required": ["ids"]},
    },
    {
        "name": "soul_tick",
        "description": "手动推进一次 ta 的内心活动；情绪有累积时会产生 1–3 条主动消息（用 soul_drain 取）。",
        "handler": _h_tick,
        "schema": {"type": "object", "properties": {}},
    },
    {
        "name": "soul_init",
        "description": "唤醒/初始化某个灵魂身份（首次使用或新建身份时用）。",
        "handler": _h_init,
        "schema": {"type": "object", "properties": {
            "warmup": {"type": "boolean", "description": "同时做第一次预热"}}},
    },
    {
        "name": "soul_health",
        "description": ("体检：引擎项目路径、解释器、常驻服务是否在跑、token 是否可用。"
                        "接不上别瞎猜原因，先调这个。"),
        "handler": _h_health,
        "schema": {"type": "object", "properties": {}},
    },
    {
        "name": "soul_serve",
        "description": ("把引擎常驻在内存里（含自主思考引擎）。冷启动每次约 2s，常驻后毫秒级。"
                        "会等待就绪，最长 wait 秒。已在本机跑着时不要重复启动。"),
        "handler": _h_serve,
        "schema": {"type": "object", "properties": {
            "restart": {"type": "boolean", "description": "先停掉已有服务再启动"},
            "no_autonomous": {"type": "boolean", "description": "不启动自主思考引擎"},
            "wait": {"type": "integer", "description": "等待就绪的秒数，默认 60"}}},
    },
    {
        "name": "soul_stop",
        "description": "停掉常驻服务（改完模型配置、或要跑聊天渠道前用）。",
        "handler": _h_stop,
        "schema": {"type": "object", "properties": {}},
    },
    {
        "name": "soul_doctor",
        "description": "完整体检：环境、依赖、项目、常驻服务、模型接口连通性。",
        "handler": _h_doctor,
        "schema": {"type": "object", "properties": {
            "check_api": {"type": "boolean",
                          "description": "真实调用一次模型接口做连通性探测（会消耗少量额度）"}}},
    },
    {
        "name": "soul_setup",
        "description": "创建虚拟环境并安装引擎依赖（首次使用、或 soul_doctor 报缺依赖时用）。",
        "handler": _h_setup,
        "schema": {"type": "object", "properties": {
            "full": {"type": "boolean",
                     "description": "装完整依赖（含向量记忆，约 300MB）；默认只装对话必需依赖"}}},
    },
    {
        "name": "soul_selftest",
        "description": ("沙箱端到端自检：用副本 + 固定假回复验证链路，不碰真实记忆、不花模型额度。"
                        "怀疑链路有问题时用它，而不是拿真实对话试。"),
        "handler": _h_selftest,
        "schema": {"type": "object", "properties": {
            "keep": {"type": "boolean", "description": "保留沙箱目录便于排查"}}},
    },
]

TOOL_INDEX = {t["name"]: t for t in TOOLS}


# ────────────────────────────────────────────────────────────
# JSON-RPC over stdio
# ────────────────────────────────────────────────────────────
def _read_message(stream):
    """逐行读；空行跳过（stdio 传输就是一行一个 JSON）。"""
    for raw in stream:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            print("[soul-mcp] 忽略无法解析的消息", file=sys.stderr)
            continue
        if isinstance(msg, dict):
            return msg
    return None


def _write_message(out, payload):
    out.write(json.dumps(payload, ensure_ascii=False) + "\n")
    out.flush()


def _result(msg_id, result):
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id, code, message):
    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": code, "message": message}}


def _tools_list():
    return {"tools": [{"name": t["name"], "description": t["description"],
                       "inputSchema": t.get("schema") or {"type": "object"}}
                      for t in TOOLS]}


def _call_tool(client, name, arguments):
    tool = TOOL_INDEX.get(name)
    if tool is None:
        return None
    args = arguments if isinstance(arguments, dict) else {}
    try:
        blocks, structured, is_error = tool["handler"](client, args)
    except Exception as exc:
        print("[soul-mcp] 工具 %s 异常: %r" % (name, exc), file=sys.stderr)
        return {"content": [_block("工具执行异常：%s" % exc)],
                "isError": True,
                "structuredContent": {"ok": False, "error_code": "tool_exception"}}
    out = {"content": blocks, "isError": bool(is_error)}
    if structured:
        out["structuredContent"] = structured
    return out


def build_client(args):
    return soulclient.SoulClient(project=args.project, python=args.python,
                                 user=args.user, config=args.config,
                                 host=args.host, port=args.port)


def serve_stdio(client):
    out = sys.stdout
    while True:
        msg = _read_message(sys.stdin)
        if msg is None:
            return 0
        method = msg.get("method")
        msg_id = msg.get("id")
        is_notification = "id" not in msg or msg_id is None

        if method == "initialize":
            params = msg.get("params") or {}
            _write_message(out, _result(msg_id, {
                "protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": _version()},
                "instructions": INSTRUCTIONS,
            }))
        elif method in ("notifications/initialized", "initialized"):
            continue
        elif method == "ping":
            if not is_notification:
                _write_message(out, _result(msg_id, {}))
        elif method == "tools/list":
            _write_message(out, _result(msg_id, _tools_list()))
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name") or ""
            payload = _call_tool(client, name, params.get("arguments"))
            if payload is None:
                _write_message(out, _error(msg_id, -32602, "未知工具: %s" % name))
            else:
                _write_message(out, _result(msg_id, payload))
        elif is_notification:
            continue          # 其它通知一律忽略
        else:
            _write_message(out, _error(msg_id, -32601, "未实现的方法: %s" % method))
    return 0


def _version():
    try:
        with open(os.path.join(os.path.dirname(HERE), "VERSION"),
                  "r", encoding="utf-8") as fh:
            return fh.read().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def build_parser():
    p = argparse.ArgumentParser(prog="soul_mcp.py",
                                description="soul-skill 的 MCP server（stdio）")
    p.add_argument("--project", help="引擎根目录（含 soul.py 与 engine/）")
    p.add_argument("--python", help="运行引擎的解释器")
    p.add_argument("--user", help="灵魂身份，默认 default_user")
    p.add_argument("--config", help="config.yaml 路径（默认技能内那份）")
    p.add_argument("--host", help="常驻服务地址，默认取 config.yaml")
    p.add_argument("--port", type=int, help="常驻服务端口，默认取 config.yaml")
    p.add_argument("--prewarm", action="store_true",
                   help="启动时在后台拉起常驻服务（首次对话会更快）")
    p.add_argument("--selfcheck", action="store_true",
                   help="打印环境诊断后退出（不进入 stdio 循环）")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    client = build_client(args)

    if args.selfcheck:
        info = client.describe()
        info["tools"] = [t["name"] for t in TOOLS]
        print(_json_text(info))
        return 0
    if args.prewarm:
        def _prewarm():
            try:
                client.serve(wait=60)
            except Exception as exc:
                print("[soul-mcp] 预热失败: %s" % exc, file=sys.stderr)
        threading.Thread(target=_prewarm, daemon=True).start()

    print("[soul-mcp] 就绪 %s v%s (user=%s, project=%s)"
          % (SERVER_NAME, _version(), client.user, client.project), file=sys.stderr)
    return serve_stdio(client)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
