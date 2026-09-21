@echo off
rem soulviai · 一键启动（Windows）
rem
rem 双击本文件即可，不需要任何命令行基础。
rem
rem 本文件只是 run.cmd 的「双击外壳」：环境准备、解释器探测、依赖安装全部交给
rem run.cmd，这里只做三件命令行外壳做不了的事：
rem   1) 把工作目录切回本文件所在目录（双击时的 cwd 不一定是这里）
rem   2) 摆一个菜单（双击时没法传参数）
rem   3) 出错时留住窗口（双击起的控制台一退出就关掉，用户连错误都看不到）
rem
rem 想用命令行就直接用 run.cmd，参数完全一样。

rem 让中文正常显示。若你的机器上中文仍是乱码，把本文件另存为 ANSI/GBK 编码即可。
chcp 65001 >nul 2>nul
setlocal

rem 双击启动时的工作目录不是本文件所在目录，必须切回来
cd /d "%~dp0"

set "HERE=%~dp0"
set "RUN=%HERE%run.cmd"
rem 渠道模式走 main.py —— run.cmd 转发的是 soulviaictl，它没有 wx/qq 子命令
set "PYEXE=%HERE%engine\.venv\Scripts\python.exe"

if not exist "%RUN%" (
    echo [启动] 同目录下没找到 run.cmd
    echo        本文件要和 run.sh、run.cmd、engine\、scripts\ 放在一起（独立包根目录）。
    echo.
    pause
    exit /b 1
)

rem 交付包模板目录（variants\standalone-app\）里跑不了：同级没有 engine\ 和 scripts\。
rem 不在这里拦住，会一路掉进 run.cmd 的「环境准备失败」，然后 :HINT 给出
rem 「没填 key / 依赖没装完」那套 —— 把「你还没组装」误诊成「你配错了」。
if not exist "%HERE%engine\" goto :TEMPLATE
if not exist "%HERE%scripts\soulviaictl.py" goto :TEMPLATE

rem 渠道模式走 main.py，绕过了 run.cmd 的首次环境准备；先把环境备好，菜单里选什么都成立。
if not exist "%PYEXE%" goto :ENSURE_VENV
goto :MENU

:ENSURE_VENV
echo [启动] 首次运行，先准备环境（只装对话必需依赖，约 42MB，几分钟）...
echo        没有进度条是正常的，请别关窗口。
echo.
call "%RUN%" setup --minimal
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

:CHAT
call "%RUN%"
set "RC=%ERRORLEVEL%"
goto :DONE

:WEB
call "%RUN%" web --port 5001
set "RC=%ERRORLEVEL%"
goto :DONE

:WX
echo [启动] 微信登录：稍后会显示二维码并自动打开扫码页面，用手机微信扫一下即可。
echo        凭证会自动保存，下次不用再扫。
echo.
"%PYEXE%" "%HERE%engine\main.py" wx
set "RC=%ERRORLEVEL%"
goto :DONE

:QQ
call :CHECK_QQ
if not defined QQ_OK goto :QQ_NEED
"%PYEXE%" "%HERE%engine\main.py" qq
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

rem QQ 需要预先填 AppID + AppSecret；微信不需要（扫码登录）。
rem 不预检的话 wait_login 只会打一句「获取 AccessToken 失败」，
rem 用户完全看不出是「没配」还是「配错了」。
:CHECK_QQ
if defined QQ_OK goto :EOF
if defined QQ_APP_ID if defined QQ_CLIENT_SECRET set "QQ_OK=1"
if defined QQ_OK goto :EOF
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

:SERVE
call "%RUN%" serve
set "RC=%ERRORLEVEL%"
goto :DONE

:DOCTOR
call "%RUN%" doctor --check-api
set "RC=%ERRORLEVEL%"
goto :DONE

:STATE
call "%RUN%" state --friendly
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
echo       或手动：run.cmd setup --minimal
echo.
echo   · 浏览器模式的端口被占
echo       本脚本已默认用 5001；若也被占，换个号：run.cmd web --port 5005
echo.
echo   · 想自己排查
echo       双击本文件选 [4] 环境自检，或看同目录 README.md 第五节「常见问题」。
echo ────────────────────────────────────────────────
goto :EOF

:TEMPLATE
echo.
echo [启动] 这个目录不是组装好的独立包，不能直接双击运行。
echo.
echo        这里是「交付包模板」（variants\standalone-app\）—— 模板不是拿来直接跑的，
echo        它同级没有 engine\ 和 scripts\，只有组装之后才有。
echo.
echo        组装（在仓库根目录执行，^<目标^> 换成你想放的位置）：
echo.
echo          xcopy /E /I engine ^<目标^>\engine
echo          xcopy /E /I scripts ^<目标^>\scripts
echo          copy config.yaml VERSION LICENSE DISCLAIMER.md ^<目标^>\
echo          copy variants\standalone-app\run.cmd ^<目标^>\
echo          copy variants\standalone-app\启动-win.cmd ^<目标^>\
echo.
echo        然后去 ^<目标^>\ 里双击「启动-win.cmd」。
echo        完整清单与各形态说明见 variants\README.md。
echo.
pause
exit /b 1
