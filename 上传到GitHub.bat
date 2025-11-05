@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
echo ============================================
echo 上传代码到 GitHub 仓库
echo ============================================
echo.

cd /d "%~dp0"

REM 检查Git是否安装
git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Git，请先安装 Git for Windows
    echo 下载地址：https://git-scm.com/download/win
    pause
    exit /b 1
)

echo [步骤1] 检查Git仓库状态
echo.

REM 检查是否在Git仓库中
git rev-parse --git-dir >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 当前目录不是Git仓库，正在初始化...
    git init
    if %errorlevel% neq 0 (
        echo [错误] Git初始化失败
        pause
        exit /b 1
    )
    echo [成功] Git仓库已初始化
    echo.
)

REM 检查是否有远程仓库
git remote | findstr /C:"origin" >nul
if %errorlevel% neq 0 (
    echo [步骤2] 配置GitHub远程仓库
    echo.
    echo 正在添加远程仓库：https://github.com/linmiaoyan/WzkjgzHomePage.git
    git remote add origin https://github.com/linmiaoyan/WzkjgzHomePage.git
    if %errorlevel% neq 0 (
        echo [警告] 添加远程仓库失败，可能已经存在
        echo 尝试更新远程仓库URL...
        git remote set-url origin https://github.com/linmiaoyan/WzkjgzHomePage.git
    )
    echo [成功] 远程仓库已配置
    echo.
) else (
    echo [步骤2] 检查远程仓库配置
    echo.
    git remote get-url origin
    echo.
    set /p confirm="是否要更新远程仓库URL为 https://github.com/linmiaoyan/WzkjgzHomePage.git? (Y/N): "
    if /i "!confirm!"=="Y" (
        git remote set-url origin https://github.com/linmiaoyan/WzkjgzHomePage.git
        echo [成功] 远程仓库URL已更新
        echo.
    )
)

echo [步骤3] 添加文件到暂存区
echo.
git add .
if %errorlevel% neq 0 (
    echo [错误] 添加文件失败
    pause
    exit /b 1
)

REM 检查是否有变更
git diff --cached --quiet
if %errorlevel% equ 0 (
    echo [提示] 没有需要提交的变更
    git status
    echo.
) else (
    echo [步骤4] 提交更改
    echo.
    set /p commit_msg="请输入提交信息（直接回车使用默认信息）: "
    if "!commit_msg!"=="" set commit_msg=Initial commit: 上传项目代码
    git commit -m "!commit_msg!"
    if %errorlevel% neq 0 (
        echo [错误] 提交失败
        pause
        exit /b 1
    )
    echo [成功] 代码已提交
    echo.
)

echo [步骤5] 检查分支名称
echo.
git branch --show-current >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 当前没有分支，创建主分支...
    git branch -M main
    echo [成功] 已创建主分支 main
    echo.
)

echo [步骤6] 推送到GitHub
echo.
echo 正在推送到 https://github.com/linmiaoyan/WzkjgzHomePage.git
echo.
echo [提示] 如果是第一次推送，可能需要输入GitHub用户名和密码
echo       如果启用了双因素认证，需要使用Personal Access Token代替密码
echo       获取Token：https://github.com/settings/tokens
echo.

REM 检查是否已经推送过
git ls-remote --heads origin main >nul 2>&1
if %errorlevel% equ 0 (
    echo [提示] 远程仓库已有main分支，使用强制推送...
    set /p force_confirm="是否强制推送（会覆盖远程代码）? (Y/N): "
    if /i "!force_confirm!"=="Y" (
        git push -u origin main --force
    ) else (
        echo [提示] 尝试普通推送...
        git push -u origin main
    )
) else (
    echo [提示] 首次推送...
    git push -u origin main
)

if %errorlevel% equ 0 (
    echo.
    echo ============================================
    echo [成功] 代码已成功上传到GitHub！
    echo ============================================
    echo.
    echo 仓库地址：https://github.com/linmiaoyan/WzkjgzHomePage
    echo.
    echo 可以在浏览器中访问查看你的代码
    echo.
) else (
    echo.
    echo ============================================
    echo [错误] 推送失败
    echo ============================================
    echo.
    echo 可能的原因：
    echo 1. 网络连接问题
    echo 2. 认证失败（用户名/密码错误）
    echo 3. 权限不足
    echo.
    echo 解决方案：
    echo 1. 检查网络连接
    echo 2. 使用Personal Access Token代替密码
    echo   获取地址：https://github.com/settings/tokens
    echo 3. 确认GitHub仓库权限
    echo.
)

pause

