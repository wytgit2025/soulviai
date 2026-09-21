#!/bin/sh
# soulviai · 一键启动（macOS / Linux）
#
# 在 Finder 里**双击本文件**即可，不需要任何命令行基础。
#
# 本文件只是 run.sh 的「双击外壳」：环境准备、解释器探测、依赖安装全部交给
# run.sh，这里只做三件命令行外壳做不了的事：
#   1) 把工作目录切回本文件所在目录（Finder 双击时的 cwd 是 $HOME）
#   2) 摆一个菜单（双击时没法传参数）
#   3) 出错时留住窗口（双击起的终端一退出就关掉，用户连错误都看不到）
#
# 想用命令行就直接用 run.sh，参数完全一样。

set -u

# ── 1. 切回本文件所在目录 ──
# Finder 双击启动时的工作目录是 $HOME，不是脚本所在目录。不切回来，
# 下面所有相对路径都会找错地方。这是双击型脚本最容易踩的坑。
cd "$(dirname "$0")" 2>/dev/null || {
    echo "[启动] 无法进入本文件所在目录。"
    printf '按回车键关闭...'
    read _ 2>/dev/null
    exit 1
}
HERE=$(pwd)
RUN="$HERE/run.sh"

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
      或手动：./run.sh setup --minimal

  · 浏览器模式的端口被占
      macOS 的 AirPlay 接收器会占 5000。本脚本已默认换到 5001；
      若 5001 也被占，换个号：./run.sh web --port 5005

  · 想自己排查
      双击本文件选 [4] 环境自检，或看同目录 README.md 第五节「常见问题」。
────────────────────────────────────────────────
EOF
}

# run.sh 丢了执行位时用 sh 跑 —— zip 解压、U 盘、网盘同步都可能把权限位抹掉
_run() {
    if [ -x "$RUN" ]; then "$RUN" "$@"; else sh "$RUN" "$@"; fi
}

[ -f "$RUN" ] || {
    echo "[启动] 同目录下没找到 run.sh。"
    echo "       本文件要和 run.sh、run.cmd、engine/、scripts/ 放在一起（独立包根目录）。"
    _pause
    exit 1
}

# 交付包模板目录（variants/standalone-app/）里跑不了：同级没有 engine/ 和 scripts/。
# 不在这里拦住的话，会一路掉进 run.sh 的「环境准备失败」，然后上面 _hint 给出
# 「没填 key / 依赖没装完」那套 —— 把「你还没组装」误诊成「你配错了」。
if [ ! -d "$HERE/engine" ] || [ ! -f "$HERE/scripts/soulviaictl.py" ]; then
    cat <<'EOF'

[启动] 这个目录不是组装好的独立包，不能直接双击运行。

       这里是「交付包模板」（variants/standalone-app/）—— 模板不是拿来直接跑的，
       它同级没有 engine/ 和 scripts/，只有组装之后才有。

       组装（在仓库根目录执行，<目标> 换成你想放的位置）：

         cp -r engine scripts config.yaml VERSION LICENSE DISCLAIMER.md \
               variants/standalone-app/run.sh \
               variants/standalone-app/启动-mac.command <目标>/
         chmod +x <目标>/run.sh <目标>/启动-mac.command

       然后去 <目标>/ 里双击「启动-mac.command」。

       完整清单与各形态说明见 variants/README.md。
EOF
    _pause
    exit 1
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

# 渠道模式走 main.py —— soulviaictl 没有 wx/qq 子命令，run.sh 也就转发不到。
_CHANNEL_PY="$HERE/engine/.venv/bin/python"

# 渠道绕过了 run.sh 的首次环境准备，所以这里自己兜一次：第一次就选微信/QQ 的话，
# venv 还没建，直接调 main.py 只会报「找不到文件」。放在菜单前，选什么都成立。
if [ ! -x "$_CHANNEL_PY" ]; then
    echo "[启动] 首次运行，先准备环境（只装对话必需依赖，约 42MB，几分钟）..."
    echo "       没有进度条是正常的，请别关窗口。"
    echo
    if ! _run setup --minimal; then
        echo "[启动] 环境准备失败。"
        _hint
        _pause
        exit 1
    fi
    echo
fi

# ── 2. 菜单 ──
echo
echo "  ╔══════════════════════════════════════════╗"
echo "  ║        ✦  soulviai · 数字生命  ✦         ║"
echo "  ╚══════════════════════════════════════════╝"
echo
echo "    [1] 终端对话      直接开始聊天（推荐，回车即此）"
echo "    [2] 浏览器对话    会自动打开浏览器（手机上也能用）"
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

# ── 3. 分发 ──
# 注：渠道会自动复用常驻服务（main.py 的 _resolve_backend），不需要先停掉它。
RC=0
case "$CHOICE" in
    2) _run web --port 5001 || RC=$? ;;
    3) echo "[启动] 微信登录：稍后会显示二维码并自动打开扫码页面，用手机微信扫一下即可。"
       echo "       凭证会自动保存，下次不用再扫。"
       echo
       "$_CHANNEL_PY" "$HERE/engine/main.py" wx || RC=$? ;;
    4) if _qq_ready; then
           "$_CHANNEL_PY" "$HERE/engine/main.py" qq || RC=$?
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
    5) _run serve           || RC=$? ;;
    6) _run doctor --check-api || RC=$? ;;
    7) _run state --friendly || RC=$? ;;
    *) _run                 || RC=$? ;;
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
