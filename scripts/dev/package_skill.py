#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""soul-skill · 打包器（纯标准库，无第三方依赖）

把整个 soul-skill/ 打成一个「干净」的分发包，自动剔除不该外发的东西：

  1) 密钥凭证   engine/.env、*.env        ← 含真实 API Key，绝不能外发
  2) 运行环境   .venv/ venv/ node_modules/ ← 几十 MB，收件人自己建
  3) 运行数据   遗留的 engine/data/、memory/ ← ta 的记忆 / 状态 / 日志（含纯提示词版）
  4) 字节码缓存 __pycache__/ *.pyc *.pyo   ← 首次运行会自动重生成
  5) 系统垃圾   .DS_Store、.soul-daemon.log / .pid
  6) 版本控制   .git/
  7) 构建工具   scripts/dev/ ← 只在开发者本机跑，收件人用不上

并把 engine/config.json 里的 api_key / bot token 清空成模板（收件人自己填 key）。
记忆现在默认住在数据家目录（~/.soul-skill），不在技能树里；下面针对 engine/data
的规则是**防御性**的：万一有旧版遗留没迁移，也绝不能被发出去。写出之前还有一道
`assert_no_runtime_state()` 兜底断言 —— 规则写错时会构建失败，而不是悄悄漏出去。

用法：
    python3 scripts/dev/package_skill.py                # → dist/soul-skill-<版本>.zip
    python3 scripts/dev/package_skill.py --dir          # → dist/soul-skill/（未压缩目录）
    python3 scripts/dev/package_skill.py --dry-run      # 只预览，不落盘
    python3 scripts/dev/package_skill.py --out /tmp/x   # 指定输出目录
    python3 scripts/dev/package_skill.py --no-sanitize  # 不动 config.json
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

# 包内根目录名 = 技能身份（SKILL.md frontmatter 的 name / slug），不是本地文件夹名。
# 跟本地目录名走有两个后果：仓库被 clone 成别的名字，包内目录就跟着变（构建不可复现）；
# 而且它和 frontmatter 的声明、和 zip 名（soul-skill-<版本>.zip）三者互相都对不上。
SKILL_NAME = "soul-skill"

# ────────────────────────────────────────────────────────────
# 排除规则
# ────────────────────────────────────────────────────────────
# 任意层级命中即整棵剪掉的目录名
PRUNE_DIR_NAMES = {".venv", "venv", "__pycache__", ".git", "node_modules", "dist"}

# 相对技能根、整棵剪掉的目录
PRUNE_REL_DIRS = (
    "engine/data",          # 运行数据：记忆 / 状态 / 日志，属 ta 的私产
    "memory",                # 纯提示词版的记忆（markdown），同样是 ta 的私产
)

# 构建期工具：只在开发者本机跑，收件人拿到没有用处，且会把构建链暴露出去
# （scripts/dev 里的脚本会读写技能根布局，留在包里只会误导使用者去改它）
DEV_REL_DIRS = ("scripts/dev",)

# 文件名命中即删
PRUNE_FILE_NAMES = {".DS_Store", ".soul-daemon.log", ".soul-daemon.pid"}

# 后缀命中即删（.env 自身及其变体都会被匹配）
PRUNE_FILE_SUFFIX = (".pyc", ".pyo", ".env")

# 打包后按「空目录」重建（引擎首次运行要求目录存在）
# 数据家目录（默认 ~/.soul-skill）由引擎首次运行时自建，包里不需要预留空目录
KEEP_EMPTY_DIRS = ()

# 需要清空敏感字段的配置文件
SANITIZE_FILE = "engine/config.json"
SANITIZE_KEYS = (
    ("ai", "api_key"),
    ("wx_bot", "bot_token"),
    ("wx_bot", "ilink_bot_id"),
    ("wx_bot", "ilink_user_id"),
    # 开发者本机的授权码：留着会把「自己的码」连同包一起发出去
    ("license", "key"),
)

# 排除原因（用于报告）
REASON_SECRET = "密钥凭证"
REASON_ENV = "运行环境"
REASON_DATA = "运行数据"
REASON_CACHE = "字节码缓存"
REASON_JUNK = "系统垃圾"
REASON_DEV = "构建工具"

# ────────────────────────────────────────────────────────────
# 内容级密钥扫描
# ────────────────────────────────────────────────────────────
# 按文件名剔除只能挡住「已知的敏感文件」。真正的兜底是看内容：
# key 被顺手写进 README、示例配置或某个 .py 里时，只有扫描能发现。
SECRET_PATTERNS = (
    ("大模型 API Key (sk-)", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")),
    ("Anthropic API Key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}")),
    ("GitHub Token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("AWS Access Key ID", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Google API Key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    ("Slack Token", re.compile(r"\bxox[baprs]-[0-9A-Za-z\-]{10,}")),
    ("私钥文件内容", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
)

SCAN_SUFFIXES = (".py", ".md", ".json", ".yaml", ".yml", ".txt", ".cfg", ".ini",
                 ".js", ".ts", ".sh", ".env", ".example", ".toml", ".properties")
SCAN_MAX_BYTES = 2 * 1024 * 1024


def _is_scan_candidate(path):
    name = os.path.basename(path).lower()
    if name.endswith(SCAN_SUFFIXES):
        return True
    return ".env" in name          # .env.example 这类变体


def _looks_binary(path):
    try:
        with open(path, "rb") as fh:
            return b"\x00" in fh.read(8192)
    except OSError:
        return True


def _mask(text):
    text = text.strip()
    return text[:8] + "…" if len(text) > 8 else text


def scan_secrets(kept):
    """扫描将要打进包里的文件内容，返回命中列表。

    只读、不改；命中即说明「按文件名剔除」漏掉了东西。
    """
    hits = []
    for src, arc in kept:
        if not _is_scan_candidate(src):
            continue
        try:
            if os.path.getsize(src) > SCAN_MAX_BYTES or _looks_binary(src):
                continue
            with open(src, "r", encoding="utf-8", errors="replace") as fh:
                for lineno, line in enumerate(fh, 1):
                    for kind, pattern in SECRET_PATTERNS:
                        m = pattern.search(line)
                        if m:
                            hits.append({"file": arc, "line": lineno, "kind": kind,
                                         "sample": _mask(m.group(0))})
        except OSError:
            continue
    return hits


def classify_dir(rel_dir, name):
    """整棵目录被剪掉时返回原因，否则 None。"""
    if name in PRUNE_DIR_NAMES:
        if name in (".venv", "venv", "node_modules"):
            return REASON_ENV
        return REASON_CACHE if name == "__pycache__" else REASON_JUNK
    posix = (rel_dir.replace(os.sep, "/").strip("/") + "/" + name).strip("/")
    for pre in DEV_REL_DIRS:
        if posix == pre or posix.startswith(pre + "/"):
            return REASON_DEV
    for pre in PRUNE_REL_DIRS:
        if posix == pre or posix.startswith(pre + "/"):
            return REASON_DATA
    return None


def classify_file(name):
    """单个文件被跳过时返回原因，否则 None。"""
    if name.endswith(".env"):
        return REASON_SECRET
    # 常驻服务鉴权 token：拿到它就能读收件人的全部记忆，绝不能进包
    if name.endswith(".soul-daemon.token") or name == ".soul-daemon.token":
        return REASON_SECRET
    if name in PRUNE_FILE_NAMES:
        return REASON_JUNK
    if name.endswith(PRUNE_FILE_SUFFIX):
        return REASON_CACHE
    return None


# ────────────────────────────────────────────────────────────
# 扫描
# ────────────────────────────────────────────────────────────
def assert_no_runtime_state(kept):
    """构建期护栏：交付包里绝不允许出现记忆、运行期状态或构建工具。

    排除规则写在扫描阶段，命中判断却取决于「规则有没有写全」—— 靠这个保证不漏
    是不够的（实测漏过）。所以在**最终文件清单**上再断言一次，命中就中止构建：
    交付契约宁可在构建期炸掉，也不要让用户的记忆被发出去。
    """
    bad = []
    for _src, arc in kept:
        rel = arc.replace("\\", "/")
        if rel == "data" or rel.endswith("/data") or "/data/" in rel \
                or rel.startswith("data/") or rel.startswith("memory/") \
                or rel == "memory":
            bad.append(rel)
        elif rel.startswith("scripts/dev/") or "/scripts/dev/" in rel:
            bad.append(rel)
        elif os.path.basename(rel).startswith(".soul-daemon."):
            bad.append(rel)
    if bad:
        raise SystemExit(
            "[soul-skill] 打包中止：交付包里出现记忆、运行期状态或构建工具 —— %s\n"
            "[soul-skill] 这些不该外发；请检查排除规则。"
            % ", ".join(sorted(bad)[:8]))
    return True


def scan():
    """遍历技能根，返回 (保留文件列表, 排除统计, 排除样例)。"""
    kept, dropped, samples = [], {}, []
    for dirpath, dirnames, filenames in os.walk(SKILL_ROOT):
        rel = os.path.relpath(dirpath, SKILL_ROOT)
        rel = "" if rel == "." else rel
        keep_dirs = []
        for d in sorted(dirnames):
            reason = classify_dir(rel, d)
            if reason:
                dropped[reason] = dropped.get(reason, 0) + 1
                samples.append((reason, os.path.join(rel, d) if rel else d))
            else:
                keep_dirs.append(d)
        dirnames[:] = keep_dirs

        for fn in sorted(filenames):
            src = os.path.join(dirpath, fn)
            arc = os.path.join(SKILL_NAME, rel, fn) if rel else os.path.join(SKILL_NAME, fn)
            if os.path.relpath(src, SKILL_ROOT).replace(os.sep, "/") == SANITIZE_FILE:
                continue  # config.json 单独处理（清空后写入）
            reason = classify_file(fn)
            if reason:
                dropped[reason] = dropped.get(reason, 0) + 1
                samples.append((reason, os.path.join(rel, fn) if rel else fn))
            else:
                kept.append((src, arc))
    assert_no_runtime_state(kept)
    return kept, dropped, samples


def sanitized_config():
    """读取 config.json，清空 api_key / bot token，返回 bytes。"""
    path = os.path.join(SKILL_ROOT, SANITIZE_FILE)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    for section, key in SANITIZE_KEYS:
        if isinstance(data.get(section), dict):
            data[section][key] = ""
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


def read_version():
    path = os.path.join(SKILL_ROOT, "VERSION")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def human(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return "%.1f %s" % (size, unit)
        size /= 1024.0


# ────────────────────────────────────────────────────────────
# 输出
# ────────────────────────────────────────────────────────────
def build_zip(out_path, kept, cfg_bytes):
    total = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, arc in kept:
            zf.write(src, arc)
            total += os.path.getsize(src)
        for d in KEEP_EMPTY_DIRS:
            zf.writestr("%s/%s/" % (SKILL_NAME, d), "")
        if cfg_bytes is not None:
            zf.writestr("%s/%s" % (SKILL_NAME, SANITIZE_FILE), cfg_bytes)
            total += len(cfg_bytes)
    return total


def build_dir(out_dir, kept, cfg_bytes):
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    total = 0
    for src, arc in kept:
        dst = os.path.join(os.path.dirname(out_dir), arc)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        total += os.path.getsize(src)
    for d in KEEP_EMPTY_DIRS:
        os.makedirs(os.path.join(os.path.dirname(out_dir), SKILL_NAME, d), exist_ok=True)
    if cfg_bytes is not None:
        dst = os.path.join(os.path.dirname(out_dir), SKILL_NAME, SANITIZE_FILE)
        with open(dst, "wb") as fh:
            fh.write(cfg_bytes)
        total += len(cfg_bytes)
    return total


def report(kept, dropped, samples, dry_run, secret_hits=None):
    print("[soul-skill] 技能根: %s" % SKILL_ROOT)
    print("[soul-skill] 保留文件: %d 个" % len(kept))
    if dropped:
        print("[soul-skill] 已排除:")
        for reason in (REASON_SECRET, REASON_ENV, REASON_DATA, REASON_CACHE,
                       REASON_JUNK, REASON_DEV):
            if dropped.get(reason):
                print("    - %s: %d 项" % (reason, dropped[reason]))
        show = [s for s in samples if s[0] == REASON_SECRET][:3]
        if show:
            print("[soul-skill] ⚠️  密钥类文件已剔除（确认它们不会进包）:")
            for reason, p in show:
                print("    - %s" % p)
    else:
        print("[soul-skill] 已排除: 无")

    if secret_hits:
        print("[soul-skill] ")
        print("[soul-skill] 🚨 保留下来的文件里扫描到 %d 处疑似密钥：" % len(secret_hits))
        for h in secret_hits[:15]:
            print("    - %s:%d  [%s]  %s" % (h["file"], h["line"], h["kind"], h["sample"]))
        if len(secret_hits) > 15:
            print("    - …其余 %d 处省略" % (len(secret_hits) - 15))
        print("[soul-skill]    请先清干净再分发；确认是误报可用 --no-secret-scan 跳过。")
    else:
        print("[soul-skill] 内容密钥扫描: 通过")

    if dry_run:
        print("[soul-skill] 干跑模式，未落盘")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="package_skill.py",
        description="把 soul-skill 打成干净的分发包（自动剔除密钥/环境/数据/字节码）")
    ap.add_argument("--out", default=os.path.join(SKILL_ROOT, "dist"),
                    help="输出目录（默认 <技能根>/dist）")
    ap.add_argument("--dir", action="store_true",
                    help="输出未压缩目录而不是 zip")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不写文件")
    ap.add_argument("--no-sanitize", action="store_true",
                    help="不清空 config.json 的 api_key / bot token")
    ap.add_argument("--no-secret-scan", action="store_true",
                    help="跳过内容级密钥扫描")
    ap.add_argument("--strict", action="store_true",
                    help="扫描到疑似密钥时直接失败（适合发布流水线）")
    args = ap.parse_args(argv)

    kept, dropped, samples = scan()
    hits = [] if args.no_secret_scan else scan_secrets(kept)
    report(kept, dropped, samples, args.dry_run, hits)
    if hits and args.strict:
        print("[soul-skill] ❌ --strict 下存在疑似密钥，已中止打包。")
        return 2
    if args.dry_run:
        return 0

    cfg = None if args.no_sanitize else sanitized_config()
    os.makedirs(args.out, exist_ok=True)
    version = read_version()

    if args.dir:
        target = os.path.join(args.out, SKILL_NAME)
        total = build_dir(target, kept, cfg)
        print("[soul-skill] 输出目录: %s" % target)
    else:
        target = os.path.join(args.out, "%s-%s.zip" % (SKILL_NAME, version))
        total = build_zip(target, kept, cfg)
        print("[soul-skill] 输出压缩包: %s" % target)

    print("[soul-skill] 体积: %s · 版本 %s" % (human(total), version))
    if cfg is not None:
        print("[soul-skill] config.json 的 api_key / bot token 已清空（收件人自填）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
