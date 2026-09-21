@echo off
rem soulviai · 独立运行版启动壳（Windows）
rem
rem   run.cmd                    进入终端对话
rem   run.cmd web                在浏览器里对话
rem   run.cmd serve              常驻到内存（推荐长期开着）
rem   run.cmd chat --text "今天有点累" --plain
rem   run.cmd state              看 ta 现在什么状态
rem   run.cmd doctor             环境自检
rem
rem 首次运行会自动建 engine\.venv 并装对话必需依赖（约 42MB，几分钟）。
setlocal

set "HERE=%~dp0"
set "CTL=%HERE%scripts\soulviaictl.py"
set "VENV_PY=%HERE%engine\.venv\Scripts\python.exe"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
    echo [soul] 没找到 Python。请先安装 Python 3.10 或更高版本，安装时勾选 Add to PATH。
    exit /b 1
)

if not exist "%VENV_PY%" (
    echo [soul] 首次运行：正在准备环境（只装对话必需依赖，约 42MB）...
    %PY% "%CTL%" setup --minimal
    if errorlevel 1 (
        echo [soul] 环境准备失败。手动重试：%PY% "%CTL%" setup
        exit /b 1
    )
)

if "%~1"=="" (
    "%VENV_PY%" "%HERE%engine\main.py" cli
    exit /b %errorlevel%
)

%PY% "%CTL%" %*
exit /b %errorlevel%
