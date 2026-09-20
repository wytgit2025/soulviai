#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""soul-skill · 混淆发布构建脚本（纯标准库）

把技能打包成「别人拿到也读不懂源码」的发布版本，用于提高逆向与抄袭成本。

流程
----
  1. 用 package_skill.py 生成一份干净的技能副本（剔除密钥/环境/运行数据）
  2. 注入水印：把 --watermark 的值写进 engine/core/watermark.py 的 _RECIPIENT
  3. 用 PyArmor 混淆三个核心包：core / engine / clients
  4. 打成 zip，文件名带上 watermark，便于事后追溯泄漏来源

用法
----
    python3 scripts/dev/build_release.py                        # 默认不加水印
    python3 scripts/dev/build_release.py --watermark 20260920-0001
    python3 scripts/dev/build_release.py --dry-run              # 只看会做什么
    python3 scripts/dev/build_release.py --install              # 先自动装 PyArmor
    python3 scripts/dev/build_release.py --expired 2027-01-01   # 加有效期
    python3 scripts/dev/build_release.py --bind-device <MAC/IPv4/硬盘序列号>

前置条件
--------
  - 引擎虚拟环境（engine/.venv）已建好：python3 scripts/soulctl.py setup --minimal
  - PyArmor >= 8（`pip install pyarmor`，脚本会定位到引擎 venv 里）

关于 PyArmor 许可
-----------------
  - 试用版（trial）对「混淆脚本总量」有上限，本项目约 120 个模块、单文件最大 85KB，
    **会中途报 `out of license`**。
  - 正式使用需购买 PyArmor 商业许可（basic / pro），本项目规模建议 basic 起步。
  - 若不想付费，可改用替代方案：只对最核心的少数模块混淆，或改用
    `package_skill.py` 仅做文件级分发（不防逆向）。

重要限制（PyArmor 的固有约束）
------------------------------
  - **平台绑定**：含二进制扩展，只能在同操作系统运行
  - **Python 版本绑定**：3.13 混淆的产物不能用 3.12 跑
  - 因此「给谁发、对方什么系统什么 Python」要在构建时就想清楚
"""

import argparse
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))    # <技能根>/scripts/dev
SCRIPTS_DIR = os.path.dirname(HERE)                  # <技能根>/scripts
SKILL_ROOT = os.path.dirname(SCRIPTS_DIR)            # 技能根
# 包内根目录名 = 技能身份，与 package_skill.SKILL_NAME 保持一致。
# 不要跟着本地文件夹名走：仓库被 clone 成别的名字时，包名会跟着变（构建不可复现）。
SKILL_NAME = "soul-skill"
IS_WIN = os.name == "nt"

# 需要混淆的核心包（相对 engine/）
OBF_PACKAGES = ("core", "engine", "clients")

# 保持明文的入口（薄胶水层，混淆收益低且易踩坑）
PLAIN_ENTRIES = ("soul.py", "main.py", "onboarding.py")

MIN_PYARMOR_MAJOR = 8


# ────────────────────────────────────────────────────────────
# 工具
# ────────────────────────────────────────────────────────────
def read_version():
    try:
        with open(os.path.join(SKILL_ROOT, "VERSION"), "r", encoding="utf-8") as fh:
            return fh.read().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def engine_python():
    """返回引擎虚拟环境的解释器路径（不存在则 None）。"""
    venv = os.path.join(SKILL_ROOT, "engine", ".venv")
    for rel in (("Scripts", "python.exe"), ("bin", "python")):
        cand = os.path.join(venv, *rel)
        if os.path.isfile(cand):
            return cand
    return None


def find_pyarmor(python_exe):
    """优先找引擎 venv 里的 pyarmor，其次 PATH。"""
    names = ("pyarmor.exe", "pyarmor") if IS_WIN else ("pyarmor",)
    if python_exe:
        bindir = os.path.dirname(python_exe)
        for n in names:
            cand = os.path.join(bindir, n)
            if os.path.isfile(cand):
                return cand
    return shutil.which("pyarmor")


def pyarmor_version(pyarmor):
    try:
        out = subprocess.run([pyarmor, "--version"], capture_output=True,
                             text=True, timeout=60)
    except Exception:
        return None
    text = ((out.stdout or "") + (out.stderr or "")).strip()
    for tok in text.replace("v", " ").split():
        parts = tok.split(".")
        if parts and parts[0].isdigit():
            return tuple(int(p) for p in parts[:3] if p.isdigit())
    return None


def run(cmd, cwd=None, label=None):
    if label:
        print("  → %s" % label)
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=3600)
    if proc.returncode != 0:
        tail = "\n".join(((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()[-15:])
        raise RuntimeError("命令失败（exit %d）:\n%s\n%s" % (proc.returncode, " ".join(cmd), tail))
    return proc


# ────────────────────────────────────────────────────────────
# 各步骤
# ────────────────────────────────────────────────────────────
def step_stage(stage_root):
    """用 package_skill.py 生成干净的技能副本。"""
    out = os.path.dirname(stage_root)
    run([sys.executable, os.path.join(HERE, "package_skill.py"), "--dir", "--out", out],
        label="生成干净副本（剔除密钥 / 环境 / 运行数据）")
    if not os.path.isdir(stage_root):
        raise RuntimeError("打包脚本没有产出目录：%s" % stage_root)


def step_watermark(stage_root, recipient):
    """把分发标识注入 watermark.py。"""
    path = os.path.join(stage_root, "engine", "core", "watermark.py")
    if not os.path.isfile(path):
        raise RuntimeError("找不到 %s" % path)
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    marker = '_RECIPIENT = ""'
    if marker not in text:
        raise RuntimeError("watermark.py 里找不到 _RECIPIENT 占位符，无法注入")
    text = text.replace(marker, '_RECIPIENT = %r' % recipient, 1)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("  → 水印已注入: _RECIPIENT = %r" % recipient)


def step_obfuscate(stage_root, pyarmor, args):
    """混淆 core / engine / clients 三个包。"""
    engine = os.path.join(stage_root, "engine")
    tmp_out = os.path.join(stage_root, "_obf")
    if os.path.isdir(tmp_out):
        shutil.rmtree(tmp_out)
    os.makedirs(tmp_out)

    targets = [os.path.join(engine, p) for p in OBF_PACKAGES
               if os.path.isdir(os.path.join(engine, p))]
    if not targets:
        raise RuntimeError("没有找到可混淆的包（core / engine / clients）")

    cmd = [pyarmor, "gen", "-O", tmp_out, "-r"]
    if args.enable:
        cmd += ["--enable", args.enable]
    if args.expired:
        cmd += ["-e", args.expired]
    if args.bind_device:
        cmd += ["-b", args.bind_device]
    if args.platform:
        cmd += ["--platform", args.platform]
    cmd += targets
    run(cmd, cwd=engine, label="PyArmor 混淆 %s" % ", ".join(OBF_PACKAGES))

    # 混淆产物落回 engine/，运行时会包也一并搬过去
    for item in sorted(os.listdir(tmp_out)):
        src = os.path.join(tmp_out, item)
        dst = os.path.join(engine, item)
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        elif os.path.isfile(dst):
            os.remove(dst)
        shutil.move(src, dst)
        print("  → 已替换: engine/%s" % item)
    shutil.rmtree(tmp_out, ignore_errors=True)

    # 清掉明文残留，确保没有漏网的 .py 源码
    leaked = []
    for pkg in OBF_PACKAGES:
        pkg_dir = os.path.join(engine, pkg)
        for dirpath, _dirnames, filenames in os.walk(pkg_dir):
            if "pyarmor_runtime" in dirpath:
                continue
            for fn in filenames:
                if fn.endswith(".py"):
                    leaked.append(os.path.relpath(os.path.join(dirpath, fn), engine))
    if leaked:
        print("  ⚠️  仍有 %d 个明文 .py 未被混淆（PyArmor 通常会全部覆盖）:" % len(leaked))
        for f in leaked[:10]:
            print("      %s" % f)
    return leaked


def step_zip(stage_root, out_dir, version, recipient):
    """把构建结果打成 zip。"""
    suffix = "-%s" % recipient if recipient else ""
    name = "%s-%s%s-obf.zip" % (SKILL_NAME, version, suffix)
    out_path = os.path.join(out_dir, name)
    os.makedirs(out_dir, exist_ok=True)
    if os.path.isfile(out_path):
        os.remove(out_path)

    total = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _dirnames, filenames in os.walk(stage_root):
            for fn in filenames:
                src = os.path.join(dirpath, fn)
                arc = os.path.join(SKILL_NAME, os.path.relpath(src, stage_root))
                zf.write(src, arc)
                total += os.path.getsize(src)
    return out_path, total


# ────────────────────────────────────────────────────────────
# 主流程
# ────────────────────────────────────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="build_release.py",
        description="混淆发布构建：干净副本 → 注水印 → PyArmor 混淆 → 打 zip")
    ap.add_argument("--out", default=os.path.join(SKILL_ROOT, "dist"),
                    help="输出目录（默认 <技能根>/dist）")
    ap.add_argument("--watermark", default="",
                    help="分发标识（如 20260920-0001），会写进 watermark.py 与 zip 文件名")
    ap.add_argument("--install", action="store_true", help="缺 PyArmor 时自动安装到引擎 venv")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不构建")
    ap.add_argument("--keep-staging", action="store_true", help="保留中间产物 _build/ 目录")
    ap.add_argument("--enable", default="", help="PyArmor 增强特性，如 jit,rft")
    ap.add_argument("--expired", default="", help="有效期，如 2027-01-01 或 30")
    ap.add_argument("--bind-device", default="", help="绑定设备（MAC / IPv4 / 硬盘序列号）")
    ap.add_argument("--platform", default="", help="跨平台混淆目标")
    args = ap.parse_args(argv)

    version = read_version()
    python_exe = engine_python()
    pyarmor = find_pyarmor(python_exe)

    print("[build] 技能: %s · 版本 %s" % (SKILL_NAME, version))
    print("[build] 引擎解释器: %s" % (python_exe or "未找到"))
    print("[build] PyArmor: %s" % (pyarmor or "未找到（需先安装）"))

    stage_root = os.path.join(args.out, "_build", SKILL_NAME)

    if args.dry_run:
        print("[build] 干跑模式，将执行：")
        print("        1. package_skill.py --dir --out %s" % os.path.join(args.out, "_build"))
        print("        2. 注入水印 _RECIPIENT = %r" % (args.watermark or ""))
        print("        3. pyarmor gen -O <tmp> -r engine/{core,engine,clients}")
        print("        4. 打包 zip（文件名含 %s）" % (args.watermark or "无水印"))
        if not python_exe:
            print("[build] ⚠️  引擎虚拟环境不存在，真实构建前需先跑："
                  "python3 scripts/soulctl.py setup --minimal")
        if not pyarmor:
            print("[build] ⚠️  PyArmor 不存在，真实构建前需先安装"
                  "（可用 --install 自动装）")
        return 0

    if not python_exe:
        print("[build] ❌ 引擎虚拟环境不存在，先跑："
              "python3 scripts/soulctl.py setup --minimal")
        return 1

    # ── PyArmor 就绪检查 ──
    if not pyarmor and args.install:
        print("[build] 未找到 PyArmor，尝试安装到引擎 venv ...")
        run([python_exe, "-m", "pip", "install", "-q", "pyarmor"], label="pip install pyarmor")
        pyarmor = find_pyarmor(python_exe)
    if not pyarmor:
        print("[build] ❌ 未找到 PyArmor。")
        print("[build]    安装：  %s -m pip install pyarmor" % python_exe)
        print("[build]    或重跑： python3 scripts/dev/build_release.py --install")
        return 1

    ver = pyarmor_version(pyarmor)
    print("[build] PyArmor: %s (%s)" % (pyarmor, ".".join(map(str, ver)) if ver else "未知"))
    if ver and ver[0] < MIN_PYARMOR_MAJOR:
        print("[build] ❌ PyArmor 版本过低（需 >= %d，当前 %d）。"
              "升级：%s -m pip install -U pyarmor" % (MIN_PYARMOR_MAJOR, ver[0], python_exe))
        return 1

    # 1) 干净副本
    step_stage(stage_root)

    # 2) 水印
    if args.watermark:
        step_watermark(stage_root, args.watermark)

    # 3) 混淆
    leaked = step_obfuscate(stage_root, pyarmor, args)

    # 4) 打包
    out_path, total = step_zip(stage_root, args.out, version, args.watermark)

    print("[build] ✅ 发布包: %s" % out_path)
    print("[build] 体积: %.1f MB" % (total / 1024.0 / 1024.0))
    print("[build] 明文入口（未混淆，属设计预期）: %s" % ", ".join(PLAIN_ENTRIES))
    if leaked:
        print("[build] ⚠️  有 %d 个明文 .py 残留，发布前请抽查！" % len(leaked))
    if not args.keep_staging:
        shutil.rmtree(os.path.join(args.out, "_build"), ignore_errors=True)
    print("[build] 提醒：混淆产物与平台/Python 版本绑定，只能在同环境运行。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[build] 已中断")
        sys.exit(130)
    except Exception as exc:
        print("[build] ❌ 构建失败: %s" % exc)
        print("[build]    中间产物在 dist/_build/，便于排查；清理：rm -rf dist")
        sys.exit(1)
