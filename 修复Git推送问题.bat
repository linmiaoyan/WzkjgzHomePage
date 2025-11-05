@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
echo ============================================
echo 修复 Git 推送问题
echo ============================================
echo.

cd /d "%~dp0"

REM 检查Git是否安装
git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Git，请先安装 Git for Windows
    pause
    exit /b 1
)

echo [步骤1] 检查当前Git状态
echo.
git status
echo.

echo [步骤2] 检查当前分支
echo.
git branch
echo.

REM 检查是否有提交
git rev-parse --verify HEAD >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 当前没有任何提交，需要先提交代码
    echo.
    echo [步骤3] 添加文件
    git add .
    echo.
    echo [步骤4] 创建初始提交
    git commit -m "Initial commit: 上传项目代码"
    if %errorlevel% neq 0 (
        echo [错误] 提交失败，请检查是否有文件需要提交
        git status
        pause
        exit /b 1
    )
    echo [成功] 已创建初始提交
    echo.
) else (
    echo [提示] 已有提交记录
    echo.
)

REM 检查当前分支名称
git branch --show-current >nul 2>&1
set current_branch=
for /f "tokens=*" %%a in ('git branch --show-current 2^>nul') do set current_branch=%%a

if "!current_branch!"=="" (
    echo [提示] 当前没有分支，需要创建主分支
    git branch -M main
    echo [成功] 已创建主分支 main
    echo.
) else (
    echo [提示] 当前分支：!current_branch!
    if /i not "!current_branch!"=="main" (
        echo [提示] 当前分支不是 main，正在重命名...
        git branch -M main
        echo [成功] 已重命名为 main
        echo.
    ) else (
        echo [提示] 分支名称正确（main）
        echo.
    )
)

echo [步骤5] 检查远程仓库配置
echo.
git remote -v
echo.

REM 检查远程仓库是否存在
git remote | findstr /C:"origin" >nul
if %errorlevel% neq 0 (
    echo [提示] 远程仓库未配置，正在添加...
    git remote add origin https://github.com/linmiaoyan/WzkjgzHomePage.git
    echo [成功] 远程仓库已配置
    echo.
) else (
    echo [提示] 检查远程仓库URL...
    git remote get-url origin
    echo.
    set current_url=
    for /f "tokens=*" %%a in ('git remote get-url origin 2^>nul') do set current_url=%%a
    if "!current_url!"=="https://github.com/linmiaoyan/WzkjgzHomePage.git" (
        echo [提示] 远程仓库URL正确
    ) else (
        echo [提示] 更新远程仓库URL...
        git remote set-url origin https://github.com/linmiaoyan/WzkjgzHomePage.git
        echo [成功] 远程仓库URL已更新
    )
    echo.
)

echo [步骤6] 推送到GitHub
echo.
echo 正在推送到 https://github.com/linmiaoyan/WzkjgzHomePage.git
echo.
echo [提示] 如果是第一次推送，可能需要输入GitHub用户名和Token
echo.

REM 检查远程是否已有main分支
git ls-remote --heads origin main >nul 2>&1
if %errorlevel% equ 0 (
    echo [提示] 远程仓库已有main分支
    echo 选择推送方式：
    echo 1. 普通推送（如果远程有冲突会失败）
    echo 2. 强制推送（会覆盖远程代码）
    echo.
    set /p push_choice="请选择 (1/2): "
    if "!push_choice!"=="2" (
        echo [提示] 使用强制推送...
        git push -u origin main --force
    ) else (
        echo [提示] 使用普通推送...
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
) else (
    echo.
    echo ============================================
    echo [错误] 推送失败
    echo ============================================
    echo.
    echo 可能的原因：
    echo 1. 认证失败（需要Personal Access Token）
    echo 2. 网络连接问题
    echo 3. 权限不足
    echo.
    echo 解决方案：
    echo 1. 使用Personal Access Token代替密码
    echo   获取地址：https://github.com/settings/tokens
    echo 2. 检查网络连接
    echo 3. 确认GitHub仓库权限
    echo.
)

pause

