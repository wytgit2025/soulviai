@echo off
rem soulviai · 一键启动（Windows）—— 仓库 / 技能根目录版
rem
rem 双击本文件即可，不需要任何命令行基础。
rem
rem 和 variants\standalone-app\启动-win.cmd 的关系（两者不要混用）：
rem   · 那份是**独立分发包**用的：双击后调同级的 run.cmd
rem   · 本文件放在**仓库根 / 技能根**（agent-full 形态）：同级没有 run.cmd，
rem     直接调 scripts\soulviaictl.py，因此自带一小段环境准备
rem 两者的对外行为刻意保持一致：切回自身目录、摆菜单、出错留住窗口。
rem
rem 想用命令行就直接用 scripts\soulviaictl.py，参数更全。

rem 让中文正常显示。若你的机器上中文仍是乱码，把本文件另存为 ANSI/GBK 编码即可。
chcp 65001 >nul 2>nul
setlocal

rem 双击启动时的工作目录不是本文件所在目录，必须切回来
cd /d "%~dp0"

set "HERE=%~dp0"
set "CTL=%HERE%scripts\soulviaictl.py"
set "VENV_PY=%HERE%engine\.venv\Scripts\python.exe"

rem ── 位置自检 ──
rem 放错目录时要说清「放错地方了」，而不是让人一路掉进环境准备失败，
rem 再收到一套「没填 key / 依赖没装完」的提示 —— 那是误诊。
if not exist "%CTL%" (
    echo.
    echo [启动] 没找到 scripts\soulviaictl.py —— 本文件不在 soulviai 仓库/技能根目录里。
    echo.
    echo        本文件要和 scripts\  engine\  config.yaml 同级（即仓库根）。
    echo        如果你要跑的是「独立分发包」，用那份：
    echo          variants\standalone-app\启动-win.cmd
    echo.
    pause
    exit /b 1
)

rem ── 首次运行：准备环境 ──
rem run.cmd（独立包那份）里的同样逻辑；这里不能复用，因为仓库根没有 run.cmd。
if not exist "%VENV_PY%" goto :SETUP

rem ── QQ 凭证预检 ──
rem QQ 需要预先填 AppID + AppSecret；微信不需要（扫码登录）。
rem 不预检的话 wait_login 只会打一句「获取 AccessToken 失败」，
rem 用户完全看不出是「没配」还是「配错了」。
set "QQ_OK="
if defined QQ_APP_ID if defined QQ_CLIENT_SECRET set "QQ_OK=1"
if not defined QQ_OK call :CHECK_QQ

:MENU
echo.
echo   ==========================================
echo          soulviai . 数字生命
echo   ==========================================
echo.
echo     [1] 终端对话      直接开始聊天（推荐，回车即此）
echo     [2] 浏览器对话    会自动打开浏览器（手机上也能用）
echo     [3] 微信          扫码登录，让 ta 住进微信
echo     [4] QQ            需要 QQ Bot 的 AppID 与密钥
echo     [5] 常驻在线      让 ta 一直在，会自己想你、攒主动消息
echo     [6] 环境自检      装依赖 / 真的打一次模型接口验证 key
echo     [7] 看 ta 的状态  情绪、羁绊、人格阶段
echo.
set "CHOICE="
set /p "CHOICE=  选几号？[1] "
if not defined CHOICE set "CHOICE=1"
echo.

if "%CHOICE%"=="2" goto :WEB
if "%CHOICE%"=="3" goto :WX
if "%CHOICE%"=="4" goto :QQ
if "%CHOICE%"=="5" goto :SERVE
if "%CHOICE%"=="6" goto :DOCTOR
if "%CHOICE%"=="7" goto :STATE
goto :CHAT

:CHECK_QQ
if not exist "%HERE%engine\.env" goto :CHECK_QQ_JSON
findstr /R /C:"^QQ_APP_ID[ ]*=[ ]*." "%HERE%engine\.env" >nul 2>nul || goto :CHECK_QQ_JSON
findstr /R /C:"^QQ_CLIENT_SECRET[ ]*=[ ]*." "%HERE%engine\.env" >nul 2>nul || goto :CHECK_QQ_JSON
set "QQ_OK=1"
goto :EOF

:CHECK_QQ_JSON
if not exist "%HERE%engine\config.json" goto :EOF
findstr /C:app_id "%HERE%engine\config.json" >nul 2>nul || goto :EOF
set "QQ_OK=1"
goto :EOF

:SETUP
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
    echo [启动] 没找到 Python。请先安装 Python 3.10 或更高版本，
    echo         安装时记得勾选 Add Python to PATH。
    echo         下载：https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)
echo [启动] 首次运行：正在准备环境（只装对话必需依赖，约 42MB）...
echo        期间没有进度条是正常的，请别关窗口。
echo.
rem 不静音：这是一次性、可能几分钟的下载，静音会让「正在装」和「卡死了」无法区分
%PY% "%CTL%" setup --minimal
if errorlevel 1 (
    echo.
    echo [启动] 环境准备失败。
    call :HINT
    echo.
    pause
    exit /b 1
)
echo.
goto :MENU

:CHAT
"%VENV_PY%" "%HERE%engine\main.py" cli
set "RC=%ERRORLEVEL%"
goto :DONE

:WEB
call "%VENV_PY%" "%CTL%" web --port 5001
set "RC=%ERRORLEVEL%"
goto :DONE

:WX
echo [启动] 微信登录：稍后会显示二维码并自动打开扫码页面，用手机微信扫一下即可。
echo        凭证会自动保存，下次不用再扫。
echo.
"%VENV_PY%" "%HERE%engine\main.py" wx
set "RC=%ERRORLEVEL%"
goto :DONE

:QQ
if not defined QQ_OK goto :QQ_NEED
"%VENV_PY%" "%HERE%engine\main.py" qq
set "RC=%ERRORLEVEL%"
goto :DONE

:QQ_NEED
echo.
echo [启动] QQ 模式要先填凭证，现在还没填。
echo.
echo        1. 到 https://q.qq.com 创建机器人，拿到 AppID 与 AppSecret
echo        2. 编辑 engine\.env（没有就从 engine\.env.example 复制一份），加上两行：
echo             QQ_APP_ID=你的AppID
echo             QQ_CLIENT_SECRET=你的AppSecret
echo        3. 保存后再回来选 [4]
echo.
echo        想省掉这一步就用微信：选 [3] 是扫码登录，不需要填任何东西。
echo.
pause
rem 直接收尾，不走 :DONE —— 否则会再触发 :HINT，
rem 把原因误归到「没填模型 key」上，两条提示互相打脸
exit /b 1

:SERVE
call "%VENV_PY%" "%CTL%" serve
set "RC=%ERRORLEVEL%"
goto :DONE

:DOCTOR
call "%VENV_PY%" "%CTL%" doctor --check-api
set "RC=%ERRORLEVEL%"
goto :DONE

:STATE
call "%VENV_PY%" "%CTL%" state --friendly
set "RC=%ERRORLEVEL%"
goto :DONE

:DONE
if not "%RC%"=="0" (
    call :HINT
    echo.
    pause
    exit /b %RC%
)

rem 自检 / 状态是「打印完就退」的短命令，不留窗口用户根本看不清
if "%CHOICE%"=="6" (
    echo.
    pause
)
if "%CHOICE%"=="7" (
    echo.
    pause
)
rem 渠道也会很快退出（扫码超时、凭证失效、连不上网关），
rem 而且它们失败时退出码可能是 0 —— 不留窗口就什么都看不到
if "%CHOICE%"=="3" (
    echo.
    pause
)
if "%CHOICE%"=="4" (
    echo.
    pause
)
exit /b 0

:HINT
echo.
echo ────────────────────────────────────────────────
echo 之前那条命令没能正常结束。常见原因：
echo.
echo   · 还没填模型 key（最常见）
echo       编辑 engine\.env（没有就从 engine\.env.example 复制一份），最少两行：
echo         AI_PROVIDER=deepseek
echo         AI_API_KEY=sk-xxxxxx
echo       本地 Ollama / vLLM 这类 OpenAI 兼容服务也能用，key 随便填。
echo.
echo   · 依赖没装完
echo       重新双击本文件即可（它会自动续装）。
echo       或手动：py -3 scripts\soulviaictl.py setup --minimal
echo.
echo   · 浏览器模式的端口被占
echo       本脚本已默认用 5001；若也被占，换个号：run 时加 --port 5005
echo.
echo   · 想自己排查
echo       双击本文件选 [4] 环境自检，或看同目录 README.md。
echo ────────────────────────────────────────────────
goto :EOF
