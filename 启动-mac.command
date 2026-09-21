#!/bin/sh
# soulviai · 一键启动（macOS / Linux）—— 仓库 / 技能根目录版
#
# 在 Finder 里双击本文件即可，不需要任何命令行基础。
#
# 和 variants/standalone-app/启动-mac.command 的关系（两者不要混用）：
#   · 那份是**独立分发包**用的：双击后调同级的 run.sh
#   · 本文件放在**仓库根 / 技能根**（agent-full 形态）：同级没有 run.sh，
#     直接调 scripts/soulviaictl.py，因此自带一小段环境准备
# 两者的对外行为刻意保持一致：切回自身目录、摆菜单、出错留住窗口。
#
# 想用命令行就直接用 scripts/soulviaictl.py，参数更全。

set -u

# ── 1. 切回本文件所在目录 ──
# Finder 双击启动时的工作目录是 $HOME，不是脚本所在目录。不切回来，
# 下面所有相对路径都会找错地方。这是双击型脚本最常见的坑。
cd "$(dirname "$0")" 2>/dev/null || {
    echo "[启动] 无法进入本文件所在目录。"
    printf '按回车键关闭...'
    read _ 2>/dev/null
    exit 1
}
HERE=$(pwd)
CTL="$HERE/scripts/soulviaictl.py"

_pause() {
    echo
    printf '按回车键关闭这个窗口...'
    read _ 2>/dev/null || true
}

_hint() {
    cat <<'EOF'

────────────────────────────────────────────────
之前那条命令没能正常结束。常见原因：

  · 还没填模型 key（最常见）
      编辑 engine/.env（没有就从 engine/.env.example 复制一份），最少两行：
        AI_PROVIDER=deepseek
        AI_API_KEY=sk-xxxxxx
      本地 Ollama / vLLM 这类 OpenAI 兼容服务也能用，key 随便填。

  · 依赖没装完
      重新双击本文件即可（它会自动续装）。
      或手动：python3 scripts/soulviaictl.py setup --minimal

  · 浏览器模式的端口被占
      macOS 的 AirPlay 接收器会占 5000。端口被占时会自动往后顺延，
      窗口里打印的那个地址才是真的；想指定端口：
      python3 scripts/soulviaictl.py web --port 5005

  · 想自己排查
      双击本文件选 [6] 环境自检，或看同目录 README.md。
────────────────────────────────────────────────
EOF
}

# ── 2. 位置自检 ──
# 放错目录时要说清「放错地方了」，而不是让人一路掉进环境准备失败，
# 再收到一套「没填 key / 依赖没装完」的提示 —— 那是误诊。
if [ ! -f "$CTL" ]; then
    cat <<'EOF'

[启动] 没找到 scripts/soulviaictl.py —— 本文件不在 soulviai 仓库/技能根目录里。

       本文件要和 scripts/、engine/、config.yaml 同级（即仓库根）。
       如果你要跑的是「独立分发包」，用那份：
         variants/standalone-app/启动-mac.command
EOF
    _pause
    exit 1
fi

# ── 3. 首次运行：准备环境 ──
# run.sh（独立包那份）里的同样逻辑；这里不能复用，因为仓库根没有 run.sh。
VENV_PY="$HERE/engine/.venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
    PY=""
    for cand in python3 python; do
        command -v "$cand" >/dev/null 2>&1 && { PY="$cand"; break; }
    done
    if [ -z "$PY" ]; then
        echo "[启动] 没找到 python3。请先安装 Python 3.10 或更高版本。"
        echo "       macOS 可以从 https://www.python.org/downloads/ 下载。"
        _pause
        exit 1
    fi
    echo "[启动] 首次运行：正在准备环境（只装对话必需依赖，约 42MB）..."
    echo "       下面会实时显示安装进度；慢的话等几分钟，期间别关窗口。"
    echo
    # 不静音：这是一次性、可能几分钟的下载，静音会让「正在装」和「卡死了」无法区分
    if ! "$PY" "$CTL" setup --minimal; then
        echo
        echo "[启动] 环境准备失败。"
        _hint
        _pause
        exit 1
    fi
    echo
fi

# QQ 需要预先填凭证（AppID + AppSecret），微信不需要（扫码登录）。
# 不预检的话：wait_login 只会打一句「获取 AccessToken 失败」，
# 用户完全看不出是「没配」还是「配错了」。
_qq_ready() {
    [ -n "${QQ_APP_ID:-}" ] && [ -n "${QQ_CLIENT_SECRET:-}" ] && return 0
    envf="$HERE/engine/.env"
    if [ -f "$envf" ] \
       && grep -qE '^[[:space:]]*QQ_APP_ID[[:space:]]*=[[:space:]]*[^[:space:]]' "$envf" \
       && grep -qE '^[[:space:]]*QQ_CLIENT_SECRET[[:space:]]*=[[:space:]]*[^[:space:]]' "$envf"; then
        return 0
    fi
    cfgj="$HERE/engine/config.json"
    if [ -f "$cfgj" ] && grep -qE '"app_id"[[:space:]]*:[[:space:]]*"[^"]' "$cfgj"; then
        return 0
    fi
    return 1
}

# ── 4. 菜单 ──
echo
echo "  ╔══════════════════════════════════════════╗"
echo "  ║        ✦  soulviai · 数字生命  ✦         ║"
echo "  ╚══════════════════════════════════════════╝"
echo
echo "    [1] 终端对话      直接开始聊天（推荐，回车即此）"
echo "    [2] 浏览器对话    会自动打开浏览器（只监听本机）"
echo "    [3] 微信          扫码登录，让 ta 住进微信"
echo "    [4] QQ            需要 QQ Bot 的 AppID 与密钥"
echo "    [5] 常驻在线      让 ta 一直在，会自己想你、攒主动消息"
echo "    [6] 环境自检      装依赖 / 真的打一次模型接口验证 key"
echo "    [7] 看 ta 的状态  情绪、羁绊、人格阶段"
echo
printf '  选几号？[1] '
CHOICE=""
read CHOICE 2>/dev/null || true
[ -n "$CHOICE" ] || CHOICE=1
echo

# ── 5. 分发 ──
# [1] 走 engine/ 自带的交互式 CLI（与 run.sh 无参数时一致）；
# 渠道与其余命令走 soulviaictl（参数更全，且它会自行解析引擎解释器）。
# 注：渠道会自动复用常驻服务（main.py 的 _resolve_backend），不需要先停掉它。
RC=0
case "$CHOICE" in
    2) "$VENV_PY" "$CTL" web              || RC=$? ;;
    3) echo "[启动] 微信登录：稍后会显示二维码并自动打开扫码页面，用手机微信扫一下即可。"
       echo "       凭证会自动保存，下次不用再扫。"
       echo
       "$VENV_PY" "$HERE/engine/main.py" wx || RC=$? ;;
    4) if _qq_ready; then
           "$VENV_PY" "$HERE/engine/main.py" qq || RC=$?
       else
           cat <<'EOF'

[启动] QQ 模式要先填凭证，现在还没填。

       1. 到 https://q.qq.com 创建机器人，拿到 AppID 与 AppSecret
       2. 编辑 engine/.env（没有就从 engine/.env.example 复制一份），加上两行：
            QQ_APP_ID=你的AppID
            QQ_CLIENT_SECRET=你的AppSecret
       3. 保存后再回来选 [4]

       想省掉这一步就用微信：选 [3] 是扫码登录，不需要填任何东西。
EOF
           # 直接收尾，不设 RC：否则会再触发下面的 _hint，
           # 把原因误归到「没填模型 key」上，两条提示互相打脸
           _pause
           exit 1
       fi ;;
    5) "$VENV_PY" "$CTL" serve             || RC=$? ;;
    6) "$VENV_PY" "$CTL" doctor --check-api || RC=$? ;;
    7) "$VENV_PY" "$CTL" state --friendly  || RC=$? ;;
    *) "$VENV_PY" "$HERE/engine/main.py" cli || RC=$? ;;
esac

if [ "$RC" != "0" ]; then
    # 退出码 >128 是收到信号：Ctrl+C=130、被 kill=143。那是用户主动停的，不是故障，
    # 别拿「没填模型 key / 依赖没装完」去吓他 —— 渠道模式尤其容易撞上：
    # 它本来就该一直开着，用户停掉它是最正常的操作。
    if [ "$RC" -gt 128 ] 2>/dev/null; then
        echo
        echo "[启动] 已停止。"
        _pause
        exit "$RC"
    fi
    _hint
    _pause
elif [ "$CHOICE" = "6" ] || [ "$CHOICE" = "7" ]; then
    # 自检/状态是「打印完就退」的短命令，不留窗口用户根本看不清
    _pause
elif [ "$CHOICE" = "3" ] || [ "$CHOICE" = "4" ]; then
    # 渠道也会很快退出（扫码超时、凭证失效、连不上网关），
    # 而且它们失败时退出码可能是 0 —— 不留窗口就什么都看不到
    _pause
fi

exit "$RC"
