#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""soul-skill · 五形态统一构建器（纯标准库，无第三方依赖）

同一份引擎（本体：`engine/` + `scripts/` + `config.yaml`），组装成五种交付形态：

    skill       自带引擎的完整技能      → 给支持 SKILL.md 的 Agent 用（现状形态）
    standalone  独立运行版              → 不装任何 Agent，./run.sh 直接对话
    mcp         MCP 版                  → 宿主里多出 13 个 soul_* 工具
    md          纯文档版（无引擎）      → 本机已有服务在跑，只用 shell + HTTP
    prompt-md   纯提示词版（无引擎）    → 谁都不靠：宿主模型自己就是 ta，记忆写在 memory/

最后一个是特例：它连「本体」都不需要，纯粹是提示词 + markdown 记忆，
因此也是唯一一个不共享引擎、没有 HTTP 契约可核对的形态。

为什么要一个统一构建器，而不是五份源码
--------------------------------------
各形态的差异只有「薄壳」：入口脚本、SKILL.md、README、配置文件。引擎本身完全共享
（`prompt-md` 更进一步，连引擎都不带）。
把差异集中在 `variants/<key>/` 下，构建时组装，可以避免多份引擎各自漂移 ——
这是多形态项目最大的维护成本。

剔除规则（密钥 / 虚拟环境 / 记忆数据 / 字节码 / 构建工具）直接复用
`package_skill.py`，不在这里重写一遍：那是安全边界，只能有一个实现。

同时做五件防漂移的检查（`--strict` 下失败即中止）：
  1. 契约完整性：技能根 / 纯文档版 / MCP 版的文档必须覆盖引擎真实存在的端点、状态、
     错误码；端点本身从 `engine_bridge.py` 的路由里抠出来当基准，两个方向都核对。
  2. 版本一致性：`VERSION` 与**每一份** SKILL.md（技能根那份 + 各薄壳那份，
     后者才是真正发出去的技能定义）的 frontmatter `version:` 必须相同；
     没有 version 字段同样算漂移。
  3. 铁律完整性：技能根 / MCP 版 / 纯文档版三份各写一份七条铁律，措辞按形态定制
     （那是接口不同，该不同），但任何一条被漏改或整条丢掉都会改变 ta 的性格 ——
     按 `RULES_ANCHORS` 的核心短语逐条核对。
  4. 规模数字：文档里「119 个模块 / 约 1.9MB」这类数字，基准由源码算出，两边对不上
     即报错 —— 手抄的数字没人对账，只会悄悄腐烂（曾漂到 117 / 3.6MB 而无人发现）。
  5. 路径引用：文档里反引号引用的 `engine/…`、`scripts/…` 等仓库内路径必须真实存在 ——
     `references/project-overview.md` 的八子层表格就曾整列少写一层（`engine/social/`）。

用法：
    python3 scripts/dev/build_variants.py                    # 五形态全出，落 dist/*.zip
    python3 scripts/dev/build_variants.py --only md,mcp      # 只出指定形态
    python3 scripts/dev/build_variants.py --dir              # 出未压缩目录（调试用）
    python3 scripts/dev/build_variants.py --dry-run          # 只预览与检查
    python3 scripts/dev/build_variants.py --list             # 看形态清单
    python3 scripts/dev/build_variants.py --strict           # 契约/文档/密钥有问题即失败（发布用）
"""
import argparse
import json
import os
import re
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))    # <技能根>/scripts/dev
SCRIPTS_DIR = os.path.dirname(HERE)                  # <技能根>/scripts
SKILL_ROOT = os.path.dirname(SCRIPTS_DIR)            # 技能根
VARIANT_SRC = os.path.join(SKILL_ROOT, "variants")

if HERE not in sys.path:
    sys.path.insert(0, HERE)

import package_skill as pack  # noqa: E402  （复用剔除规则与密钥扫描）

# ────────────────────────────────────────────────────────────
# 契约基准：文档必须与引擎实现对齐
# ────────────────────────────────────────────────────────────
# 端点以 engine_bridge.py 为准：下面 bridge_endpoints() 真的去源码里抠，
# 这份清单是「应该有哪些」的预期，两个方向对不上都报错。
CONTRACT_ENDPOINTS = ("/health", "/state", "/pending", "/chat", "/drain", "/ack",
                      "/tick", "/init", "/config/reload", "/shutdown")
CONTRACT_STATUS = ("silent", "queued", "backend_error")
CONTRACT_ERROR_CODES = ("api_auth", "api_rate_limit", "api_quota",
                        "api_unreachable", "timeout", "no_python", "no_project")
CONTRACT_MISC = ("X-Soul-Token", "parts", "codes.personality_stage",
                 "codes.life_phase")

# ── 七条铁律的锚点（技能根 / MCP 版 / 纯文档版三份各写一份）──
# 这三份的铁律**不是复制粘贴的冗余**：措辞按形态定制（`parts` / content 块、
# `ai.api_key` / `AI_API_KEY`、`/chat` / `soul_chat`），那是接口不同导致的，该不同。
# 真正会漂移的是「某一条在某一形态里被漏改或整条丢掉」—— 而这三份是宿主 Agent
# 每次都要读的行为准则，漏一条就等于「换个形态换了个性格」。
# 锚点取每条的核心短语，与措辞差异无关，只认「这一条在不在」。
RULES_ANCHORS = (
    "你是传话人，不是 ta",
    "多段要分段",
    "没回就是没回",
    "别把内脏掏给用户看",
    "不要绕过它",
    "每一句话都是不可逆的相处",
    "后端报错要如实说",
)


def bridge_endpoints(bridge_text):
    """从 engine_bridge.py 的路由分支里抠出真实端点，返回排序去重后的列表。

    基准必须来自源码：手工清单校验手工文档，两边一起漂了没人发现 ——
    技能根那份 SKILL.md 就是这么漏掉 /ack 与 /config/reload 的。
    抠不到（有人改了路由写法）返回空列表，由 check_contract 退回清单并报警告。
    """
    found = re.findall(r'(?:parsed\.path|path)\s*==\s*"(/[A-Za-z0-9_/\-]+)"',
                       bridge_text)
    return sorted(set(found))


# 每个形态的文档必须覆盖什么。
#   endpoints=True 表示「必须提到源码里真实存在的每一个端点」；
#   技能根那份最常被 Agent 读，所以和纯文档版同一个标准；
#   MCP 版讲的是工具，覆盖率交给工具清单，只需要它讲清「沉默与报错」的区别；
#   纯提示词版没有 HTTP，改核它的状态协议（memory/ 三个文件）与人格骨架。
DOC_CONTRACT = {
    "skill": {
        # from_root：交付的就是技能根那份，不是 variants/skill/ 下的副本。
        "file": "SKILL.md",
        "from_root": True,
        "endpoints": True,
        "tokens": (list(CONTRACT_ERROR_CODES) + list(CONTRACT_MISC)
                   + list(CONTRACT_STATUS)),
        "tools": False,
        "rules": True,
    },
    "md": {
        "file": "SKILL.md",
        "endpoints": True,
        "tokens": (list(CONTRACT_ERROR_CODES) + list(CONTRACT_MISC)
                   + list(CONTRACT_STATUS)),
        "tools": False,
        "rules": True,
    },
    "mcp": {
        "file": "SKILL.md",
        "tokens": ("silent", "backend_error"),
        "tools": True,
        "rules": True,
    },
    "prompt-md": {
        # 无引擎、无 HTTP，没有端点契约可核：改为核对它的「状态协议 + 人格骨架」，
        # 防止以后有人把记忆文件或人格铁律删掉而没人发现。
        "file": "SKILL.md",
        "tokens": ("memory/state.md", "memory/bond.md", "memory/journal.md",
                   "不可逆", "沉默"),
        "tools": False,
    },
}


# ── 文档里的规模数字：基准从源码算，文档只做声明 ──
# 手抄的数字没人对账，只会在某次「怎么对不上」时才被发现；而引擎涨了模块、文档没跟，
# 读者（尤其拿它判断安装体量的人）据此决策，错了就是误导。
# 这里把数字变成一条断言：源码算得出、文档声明得出、两边必须相等。
# 模块数按目录精确比对；体积是连续量，「约 X MB」本就是近似，给 25% 容差。
DOC_NUMBER_CLAIMS = (
    # (文档, 正则, 基准, 基准说明)
    ("SKILL.md", r"(\d+)\s*个模块\s*/\s*约\s*([\d.]+)\s*MB",
     "engine_all", "整个 engine/"),
    ("README.md", r"(\d+)\s*个模块\s*/\s*约\s*([\d.]+)\s*MB",
     "engine_all", "整个 engine/"),
    ("references/setup-guide.md", r"(\d+)\s*个模块\s*/\s*约\s*([\d.]+)\s*MB",
     "engine_all", "整个 engine/"),
    ("references/project-overview.md", r"八大子层（(\d+)\s*个模块）",
     "engine_sublayers", "engine/engine/ 八个子层"),
)

# ── 文档里反引号引用的仓库内路径必须真实存在 ──
# 这类引用是给读者按图索骥的：`engine/social/laws.py` 少写一层，读者就永远打不开
# 那个文件 —— 而 markdown 渲染器不会报错，人眼 review 也极难发现（`engine/core/`
# 恰好存在，却是个同名不同物的基础层，错得最隐蔽）。
# 判定刻意收窄到这些前缀：裸模块名（`mind.py`）与 `~/...` 运行时路径不校验，
# 前者定位不到、后者本就不在源码树里，硬报只会制造噪音、把真问题淹掉。
DOC_REF_PREFIXES = ("engine/", "scripts/", "references/", "variants/", "./")
DOC_REF_FILES = ("SKILL.md", "README.md",
                 "references/engine-api.md", "references/project-overview.md",
                 "references/setup-guide.md")
# 构建期生成的入口脚本：源码树里没有、发布包里才有，文档引用它们不算漂移。
# 与 VARIANTS 里 standalone 的 overrides 对应。
DOC_REF_GENERATED = ("run.sh", "run.cmd")


# ────────────────────────────────────────────────────────────
# 五形态定义（构建脚本即清单：改形态只改这里 + variants/<key>/）
# 形态与槽位目录一一对应，每个 key 都必须有 variants/<key>/（check_shells 会校验）。
# 注：skill 槽位里没有薄壳 —— 它直接以技能根为本体，槽位只放一份说明。
# ────────────────────────────────────────────────────────────
VARIANTS = {
    "skill": {
        "title": "完整技能（自带引擎）",
        "desc": "现状形态：SKILL.md + scripts/ + references/ + engine/，Agent 用 bash 调 soulctl",
        "pkg": pack.SKILL_NAME,
        "zip": "soul-skill",
        "entries": None,                     # None = 技能根全量（自动排除 dist/ 与 variants/）
        "overrides": [],
        "must_exist": ["SKILL.md", "scripts/soulctl.py", "scripts/soul_mcp.py",
                       "engine/soul.py", "config.yaml", "VERSION", "LICENSE",
                       "engine/engine/i18n/strings.json"],
        "must_not_exist": ["variants", "scripts/dev"],
    },
    "standalone": {
        "title": "独立运行版",
        "desc": "不装任何 Agent：./run.sh 直接对话（终端 / 浏览器 / 常驻）",
        "pkg": "soul-standalone",
        "zip": "soul-standalone",
        "entries": ["engine", "scripts", "config.yaml", "VERSION", "LICENSE"],
        "overrides": [("variants/standalone/run.sh", "run.sh"),
                      ("variants/standalone/run.cmd", "run.cmd"),
                      ("variants/standalone/README.md", "README.md")],
        "must_exist": ["run.sh", "run.cmd", "README.md", "engine/soul.py",
                       "scripts/soulctl.py", "config.yaml",
                       "engine/engine/i18n/strings.json"],
        "must_not_exist": ["SKILL.md", "references"],
    },
    "mcp": {
        "title": "MCP 版",
        "desc": "宿主里多出 13 个 soul_* 工具；soul_mcp.py 是纯标准库 stdio server",
        "pkg": pack.SKILL_NAME,
        "zip": "soul-skill-mcp",
        "entries": ["engine", "scripts", "references", "config.yaml", "VERSION",
                    "LICENSE"],
        "overrides": [("variants/mcp/SKILL.md", "SKILL.md"),
                      ("variants/mcp/README.md", "README.md"),
                      ("variants/mcp/mcp.json", "mcp.json")],
        "must_exist": ["SKILL.md", "mcp.json", "scripts/soul_mcp.py",
                       "engine/soul.py", "engine/engine/i18n/strings.json"],
        "must_not_exist": [],
    },
    "md": {
        "title": "纯文档版（无引擎）",
        "desc": "只带 SKILL.md：本机已有常驻服务时，用 shell + HTTP 和 ta 说话",
        "pkg": pack.SKILL_NAME,
        "zip": "soul-skill-md",
        "entries": ["LICENSE", "VERSION"],
        "overrides": [("variants/md/SKILL.md", "SKILL.md"),
                      ("variants/md/README.md", "README.md")],
        "must_exist": ["SKILL.md", "README.md", "LICENSE", "VERSION"],
        "must_not_exist": ["engine", "scripts", "config.yaml"],
    },
    "prompt-md": {
        "title": "纯提示词版（无引擎、无服务）",
        "desc": "只带 SKILL.md：宿主模型自己就是 ta，记忆写在技能目录的 memory/ 下",
        "pkg": pack.SKILL_NAME,
        "zip": "soul-skill-prompt-md",
        "entries": ["LICENSE", "VERSION"],
        "overrides": [("variants/prompt-md/SKILL.md", "SKILL.md"),
                      ("variants/prompt-md/README.md", "README.md")],
        "must_exist": ["SKILL.md", "README.md", "LICENSE", "VERSION"],
        "must_not_exist": ["engine", "scripts", "config.yaml", "memory"],
    },
}


# ────────────────────────────────────────────────────────────
# 组装
# ────────────────────────────────────────────────────────────
def _extra_excludes(spec):
    return [e.strip("/") for e in spec.get("exclude", [])]


def _excluded(rel, excludes):
    posix = rel.replace(os.sep, "/")
    return any(posix == e or posix.startswith(e + "/") for e in excludes)


def collect(spec):
    """按形态清单遍历技能根，返回 (kept, dropped, samples)。

    kept 元素是 (绝对源路径, 包内相对路径)；剔除规则来自 package_skill，
    另外永远排除 variants/（那是构建输入，不是交付物）与 dist/。
    """
    kept, dropped, samples = [], {}, []
    excludes = _extra_excludes(spec) + ["variants", "dist"]

    def add_file(src, rel):
        rel_posix = rel.replace(os.sep, "/")
        if rel_posix == pack.SANITIZE_FILE:
            return                      # config.json 清空敏感字段后单独写入
        reason = pack.classify_file(os.path.basename(src))
        if reason:
            dropped[reason] = dropped.get(reason, 0) + 1
            samples.append((reason, rel_posix))
            return
        kept.append((src, rel_posix))

    def add_dir(root_rel):
        for dirpath, dirnames, filenames in os.walk(os.path.join(SKILL_ROOT, root_rel)):
            rel = os.path.relpath(dirpath, SKILL_ROOT)
            rel = "" if rel == "." else rel
            dirnames[:] = [d for d in sorted(dirnames)
                           if not pack.classify_dir(rel, d)
                           and not _excluded(os.path.join(rel, d), excludes)]
            for fn in sorted(filenames):
                rel_file = os.path.join(rel, fn) if rel else fn
                if _excluded(rel_file, excludes):
                    continue
                add_file(os.path.join(dirpath, fn), rel_file)

    entries = spec.get("entries")
    if entries is None:
        entries = [n for n in sorted(os.listdir(SKILL_ROOT))
                   if not _excluded(n, excludes)]
    for name in entries:
        src = os.path.join(SKILL_ROOT, name)
        if not os.path.exists(src):
            print("[build] ⚠️  形态 %s 声明的 %s 不存在，已跳过" % (spec["pkg"], name))
            continue
        if os.path.isdir(src):
            add_dir(name)
        else:
            add_file(src, name)

    # 薄壳覆盖：同名直接替换（SKILL.md / README.md / run.sh …）
    for src_rel, dest_rel in spec.get("overrides", []):
        src = os.path.join(SKILL_ROOT, src_rel)
        if not os.path.isfile(src):
            raise SystemExit("[build] ❌ 薄壳文件缺失：%s" % src_rel)
        dest_posix = dest_rel.replace(os.sep, "/")
        kept = [(s, a) for s, a in kept if a != dest_posix]
        kept.append((src, dest_posix))
    kept.sort(key=lambda item: item[1])
    return kept, dropped, samples


def extra_payloads(spec, kept):
    """返回 {包内路径: bytes}：需要改写的配置文件与空目录占位。"""
    arcs = {arc for _src, arc in kept}
    payloads = {}
    if pack.SANITIZE_FILE in arcs or any(a.startswith("engine/") for a in arcs):
        cfg = pack.sanitized_config()
        if cfg is not None:
            payloads[pack.SANITIZE_FILE] = cfg
    for empty in pack.KEEP_EMPTY_DIRS:
        if any(a.startswith("engine/") for a in arcs):
            payloads[empty.rstrip("/") + "/"] = b""
    return payloads


# ────────────────────────────────────────────────────────────
# 防漂移检查
# ────────────────────────────────────────────────────────────
def _read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def check_contract():
    """文档 ↔ 引擎实现的契约核对，返回 (errors, warnings)。

    基准是**源码**：端点在 engine_bridge.py，错误码散在 bridge 与 soulctl 两处。
    文档里写了源码里没有的东西 = 文档漂移；源码里改了而文档没跟 = 同样报错。
    """
    errors, warnings = [], []
    bridge = _read(os.path.join(SCRIPTS_DIR, "engine_bridge.py"))
    ctl = _read(os.path.join(SCRIPTS_DIR, "soulctl.py"))
    source = bridge + ctl
    if not bridge:
        warnings.append("读不到 engine_bridge.py，端点基准退化为内置清单")
        endpoints = list(CONTRACT_ENDPOINTS)
    else:
        endpoints = bridge_endpoints(bridge)
        if not endpoints:
            warnings.append("engine_bridge.py 里抠不到端点（路由写法变了？），"
                            "退化为内置清单")
            endpoints = list(CONTRACT_ENDPOINTS)
        else:
            for ep in CONTRACT_ENDPOINTS:
                if ep not in endpoints:
                    errors.append("engine_bridge.py 里找不到端点 %s（契约基准失配）" % ep)
            for ep in endpoints:
                if ep not in CONTRACT_ENDPOINTS:
                    errors.append("engine_bridge.py 的新端点 %s 没登记进 "
                                  "CONTRACT_ENDPOINTS" % ep)
    for code in CONTRACT_ERROR_CODES:
        if code not in source:
            errors.append("引擎里找不到 error_code %s（契约基准失配）" % code)

    tool_names = _mcp_tool_names()
    for key, need in DOC_CONTRACT.items():
        path = doc_source(VARIANTS[key], key, need["file"],
                          root=need.get("from_root"))
        if not os.path.isfile(path):
            errors.append("%s 形态的文档不存在：%s" % (key, path))
            continue
        text = _read(path)
        wanted = list(need["tokens"])
        if need.get("endpoints"):
            wanted += endpoints
        missing = [t for t in wanted if t not in text]
        if missing:
            errors.append("%s 形态的 %s 缺少契约内容：%s"
                          % (key, need["file"], "、".join(missing)))
        if need["tools"] and tool_names:
            missing_tools = [n for n in tool_names if n not in text]
            if missing_tools:
                errors.append("%s 形态的 %s 没提到这些工具：%s"
                              % (key, need["file"], "、".join(missing_tools)))
        if need.get("rules"):
            missing_rules = [a for a in RULES_ANCHORS if a not in text]
            if missing_rules:
                errors.append("%s 形态的 %s 铁律不完整，缺：%s"
                              % (key, need["file"], "、".join(missing_rules)))
    return errors, warnings


def doc_source(spec, key, dest_rel, root=False):
    """文档在包内的路径 → 它的源文件。

    root=True 给 skill 形态用：它没有薄壳，交付的那份就是技能根这份。
    """
    dest_posix = dest_rel.replace(os.sep, "/")
    if root:
        return os.path.join(SKILL_ROOT, dest_posix)
    for src_rel, override_dest in spec.get("overrides", []):
        if override_dest.replace(os.sep, "/") == dest_posix:
            return os.path.join(SKILL_ROOT, src_rel)
    return os.path.join(VARIANT_SRC, key, dest_rel)


def _mcp_tool_names():
    """从 soul_mcp.py 里抠出工具名（不 import，避免构建期副作用）。"""
    text = _read(os.path.join(SCRIPTS_DIR, "soul_mcp.py"))
    names = re.findall(r'"name":\s*"(soul_[a-z_]+)"', text)
    return sorted(set(names))


def skill_md_files():
    """所有会随包发布的 SKILL.md：技能根那份 + 各薄壳里的那份。"""
    files = [os.path.join(SKILL_ROOT, "SKILL.md")]
    if os.path.isdir(VARIANT_SRC):
        for name in sorted(os.listdir(VARIANT_SRC)):
            cand = os.path.join(VARIANT_SRC, name, "SKILL.md")
            if os.path.isfile(cand):
                files.append(cand)
    return files


def check_version():
    """VERSION 与**每一份** SKILL.md 的 frontmatter 必须一致。

    只核对技能根那份是不够的：MCP 版与纯文档版各自带一份 SKILL.md，
    而那一份才是真正发出去的技能定义 —— 漏掉它们，变体就能悄悄停在旧版本
    而 `--strict` 依然全绿，正好绕过这套护栏存在的意义。

    另外，正则匹配不到时**不能**当作通过：frontmatter 里没有 version 字段
    本身就是漂移（宿主无法判断版本），要报出来而不是静默放过。
    """
    errors = []
    version = pack.read_version()
    for path in skill_md_files():
        rel = os.path.relpath(path, SKILL_ROOT).replace(os.sep, "/")
        text = _read(path)
        m = re.search(r"^version:\s*(\S+)\s*$", text, re.M)
        if not m:
            errors.append("%s 的 frontmatter 里没有 version 字段" % rel)
        elif m.group(1) != version:
            errors.append("版本不一致：VERSION=%s，%s 的 frontmatter=%s"
                          % (version, rel, m.group(1)))
    return errors, version


def check_shells():
    """每个形态都必须有 variants/<key>/ 槽位 —— 形态与目录一一对应。

    skill 槽位里只有一份说明（它没有薄壳，本体就是技能根），但目录本身必须存在：
    这样「新加了形态却忘了建目录」会在构建时报出来，而不是等到发现声明的
    薄壳路径找不到。形态清单与磁盘目录是否一致，这道校验是唯一的现场证据。
    """
    errors = []
    for key in VARIANTS:
        shell = os.path.join(VARIANT_SRC, key)
        if not os.path.isdir(shell):
            errors.append("形态 %s 缺少槽位目录 variants/%s/" % (key, key))
    return errors


# 数规模时永远跳过的目录：虚拟环境、字节码、运行时数据。
# 与文档「不含 .venv 与 data/」的口径对齐 —— 否则两边算法不同，门会一直误报。
_NUM_SKIP_DIRS = (".venv", "__pycache__", "data", ".git")


def _module_count(base):
    """数 base 下的 .py 模块。"""
    n = 0
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in _NUM_SKIP_DIRS]
        n += sum(1 for f in filenames if f.endswith(".py"))
    return n


def _tree_bytes(base):
    """base 下所有文件的字节总和。"""
    total = 0
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in _NUM_SKIP_DIRS]
        for name in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    return total


def _number_baselines():
    """算一遍规模基准：{基准名: (模块数, 字节数或 None)}。"""
    engine = os.path.join(SKILL_ROOT, "engine")
    return {
        "engine_all": (_module_count(engine), _tree_bytes(engine)),
        "engine_sublayers": (_module_count(os.path.join(engine, "engine")), None),
    }


def check_doc_numbers():
    """文档里的规模数字必须与源码算出的基准一致，返回错误清单。

    匹配不到声明时**报错而不是放过**：文案一改、正则失配，这道门就静默失效了 ——
    那比数字写错更危险，因为构建看起来一切正常。这与 check_version 对
    「没有 version 字段」的处理是同一个道理：缺失本身就是漂移。
    """
    errors = []
    baselines = _number_baselines()
    for rel, pattern, key, note in DOC_NUMBER_CLAIMS:
        text = _read(os.path.join(SKILL_ROOT, rel))
        if not text:
            errors.append("文档不存在或读不到：%s" % rel)
            continue
        m = re.search(pattern, text)
        if not m:
            errors.append("%s 里找不到规模数字声明（正则失配，文案改了要同步 "
                          "DOC_NUMBER_CLAIMS）：%s" % (rel, pattern))
            continue
        want_modules, want_bytes = baselines[key]
        got_modules = int(m.group(1))
        if got_modules != want_modules:
            errors.append("%s 写「%d 个模块」，源码实为 %d（口径：%s）"
                          % (rel, got_modules, want_modules, note))
        if want_bytes and m.lastindex and m.lastindex >= 2:
            got_mb = float(m.group(2))
            real_mb = want_bytes / 1048576.0
            if real_mb > 0 and abs(got_mb - real_mb) / real_mb > 0.25:
                errors.append("%s 写「约 %sMB」，源码实为 %.1fMB（偏差超 25%%）"
                              % (rel, m.group(2), real_mb))
    return errors


def _doc_refs(text):
    """逐个抠出正文里反引号包裹的仓库内路径，带行号。"""
    for m in re.finditer(r"`([^`\n]+)`", text):
        token = m.group(1).strip()
        if not token.startswith(DOC_REF_PREFIXES):
            continue
        if any(ch in token for ch in "<>* "):
            continue                      # 占位符 / 通配 / 夹带说明的，跳过
        yield text.count("\n", 0, m.start()) + 1, token


def check_doc_refs():
    """技能根文档里反引号引用的仓库内路径必须真实存在，返回错误清单。

    判定范围见 DOC_REF_PREFIXES：收窄是为了不误报，
    误报多了这道门就会被绕过，等于没有。
    """
    errors = []
    for rel in DOC_REF_FILES:
        text = _read(os.path.join(SKILL_ROOT, rel))
        if not text:
            continue
        for lineno, token in _doc_refs(text):
            target = token.rstrip("/")
            if os.path.basename(target) in DOC_REF_GENERATED:
                continue
            if not os.path.exists(os.path.join(SKILL_ROOT, target)):
                errors.append("%s:%d 引用了不存在的路径 `%s`" % (rel, lineno, token))
    return errors


def check_shape(spec, arcs):
    problems = []
    for rel in spec.get("must_exist", []):
        if rel not in arcs:
            problems.append("缺少必需文件 %s" % rel)
    for rel in spec.get("must_not_exist", []):
        if rel in arcs or any(a.startswith(rel + "/") for a in arcs):
            problems.append("不该包含 %s" % rel)
    return problems


# ────────────────────────────────────────────────────────────
# 输出
# ────────────────────────────────────────────────────────────
def build_zip(target, pkg, kept, payloads):
    """打 zip。用 ZipInfo.from_file 带上源文件的权限位 —— 否则解压后
    `run.sh` 没有可执行位，独立运行版的第一步就卡在 permission denied。"""
    total = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, arc in kept:
            zi = zipfile.ZipInfo.from_file(src, "%s/%s" % (pkg, arc))
            zi.compress_type = zipfile.ZIP_DEFLATED
            with open(src, "rb") as fh:
                zf.writestr(zi, fh.read())
            total += os.path.getsize(src)
        for arc, blob in payloads.items():
            zf.writestr("%s/%s" % (pkg, arc), blob)
            total += len(blob)
    return total


def build_dir(target, pkg, kept, payloads):
    if os.path.isdir(target):
        shutil.rmtree(target)
    total = 0
    for src, arc in kept:
        dst = os.path.join(target, pkg, arc)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        total += os.path.getsize(src)
    for arc, blob in payloads.items():
        dst = os.path.join(target, pkg, arc)
        if arc.endswith("/"):
            os.makedirs(dst, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as fh:
            fh.write(blob)
        total += len(blob)
    return total


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="build_variants.py",
        description="把同一份引擎组装成五种交付形态"
                    "（skill / standalone / mcp / md / prompt-md）")
    ap.add_argument("--out", default=os.path.join(SKILL_ROOT, "dist"),
                    help="输出目录（默认 <技能根>/dist）")
    ap.add_argument("--only", default="",
                    help="只构建指定形态，逗号分隔：%s" % "、".join(VARIANTS))
    ap.add_argument("--dir", action="store_true", help="输出目录而不是 zip")
    ap.add_argument("--dry-run", action="store_true", help="只预览与检查，不落盘")
    ap.add_argument("--no-sanitize", action="store_true",
                    help="不清空 config.json 的 api_key / bot token")
    ap.add_argument("--no-secret-scan", action="store_true",
                    help="跳过内容级密钥扫描")
    ap.add_argument("--strict", action="store_true",
                    help="契约/版本/文档/密钥有问题即失败（发布流水线用）")
    ap.add_argument("--list", action="store_true", help="只打印形态清单")
    args = ap.parse_args(argv)

    if args.list:
        for key, spec in VARIANTS.items():
            print("%-11s %-14s %s" % (key, "→ " + spec["pkg"], spec["title"]))
            print("            %s" % spec["desc"])
        return 0

    keys = [k.strip() for k in args.only.split(",") if k.strip()] or list(VARIANTS)
    unknown = [k for k in keys if k not in VARIANTS]
    if unknown:
        print("[build] ❌ 未知形态：%s（可选：%s）"
              % ("、".join(unknown), "、".join(VARIANTS)))
        return 1

    errors, warnings = check_contract()
    ver_errors, version = check_version()
    errors += ver_errors
    errors += check_shells()
    errors += check_doc_numbers()
    errors += check_doc_refs()
    for w in warnings:
        print("[build] ⚠️  %s" % w)
    if errors:
        print("[build] 契约/版本/文档检查：")
        for e in errors:
            print("[build]   ❌ %s" % e)
        if args.strict:
            print("[build] ❌ --strict 下中止。")
            return 2
        print("[build] （未加 --strict，继续构建）")

    if not args.dry_run:
        os.makedirs(args.out, exist_ok=True)

    rc = 0
    for key in keys:
        spec = VARIANTS[key]
        kept, dropped, _samples = collect(spec)
        arcs = {arc for _src, arc in kept}
        payloads = {} if args.no_sanitize else extra_payloads(spec, kept)
        arcs |= set(payloads)

        problems = check_shape(spec, arcs)
        hits = [] if args.no_secret_scan else pack.scan_secrets(kept)

        print("")
        print("[build] ── %s（%s）" % (key, spec["title"]))
        print("[build]    包内根目录: %s/" % spec["pkg"])
        print("[build]    文件数: %d（+%d 个生成项）" % (len(kept), len(payloads)))
        if dropped:
            detail = "、".join("%s×%d" % (r, n) for r, n in sorted(dropped.items()))
            print("[build]    已剔除: %s" % detail)
        if problems:
            rc = 2
            print("[build]    ❌ 结构校验：%s" % "；".join(problems))
        else:
            print("[build]    ✅ 结构校验通过")
        if hits:
            rc = max(rc, 2)
            print("[build]    🚨 扫描到 %d 处疑似密钥：" % len(hits))
            for h in hits[:8]:
                print("[build]       - %s:%d  [%s]  %s"
                      % (h["file"], h["line"], h["kind"], h["sample"]))
        elif not args.no_secret_scan:
            print("[build]    ✅ 内容密钥扫描通过")
        if args.dry_run:
            continue

        if args.dir:
            # 目录模式下 skill / mcp / md 的包内根目录同名，用形态名再分一层避免互相覆盖
            target = os.path.join(args.out, key, spec["pkg"])
            build_dir(target, spec["pkg"], kept, payloads)
            print("[build]    → 目录 %s" % target)
        else:
            target = os.path.join(args.out, "%s-%s.zip" % (spec["zip"], version))
            build_zip(target, spec["pkg"], kept, payloads)
            print("[build]    → 压缩包 %s" % target)
        print("[build]    压缩包 %s · 版本 %s"
              % (pack.human(os.path.getsize(target)), version))

    if args.dry_run:
        print("")
        print("[build] 干跑模式，未落盘。")
    if rc and args.strict:
        return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
