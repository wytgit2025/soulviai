#!/bin/sh
# soul-skill · 独立运行版启动壳（不需要任何 Agent 工具）
#
#   ./run.sh                       进入终端对话（引擎自带交互式 CLI）
#   ./run.sh web                   在浏览器里对话
#   ./run.sh serve                 常驻到内存（含自主思考引擎，推荐长期开着）
#   ./run.sh chat --text "今天有点累" --plain
#   ./run.sh state                 看 ta 现在什么状态
#   ./run.sh doctor                环境自检
#
# 首次运行会自动建 engine/.venv 并装对话必需依赖（约 42MB，几分钟）。
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
CTL="$HERE/scripts/soulctl.py"

PY=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        PY="$cand"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "[soul] 没找到 python3。请先装 Python 3.10 或更高版本。" >&2
    exit 1
fi

# Windows 上的 Git Bash / MSYS 用 Scripts\python.exe，其余用 bin/python
case "$(uname -s 2>/dev/null || echo unknown)" in
    MINGW*|MSYS*|CYGWIN*) VENV_PY="$HERE/engine/.venv/Scripts/python.exe" ;;
    *)                    VENV_PY="$HERE/engine/.venv/bin/python" ;;
esac

if [ ! -x "$VENV_PY" ]; then
    echo "[soul] 首次运行：正在准备环境（只装对话必需依赖，约 42MB）..." >&2
    if ! "$PY" "$CTL" setup --minimal >/dev/null; then
        echo "[soul] 环境准备失败。手动重试：$PY \"$CTL\" setup" >&2
        exit 1
    fi
fi

if [ "$#" -eq 0 ]; then
    exec "$VENV_PY" "$HERE/engine/main.py" cli
fi
exec "$PY" "$CTL" "$@"
