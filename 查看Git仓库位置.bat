@echo off
chcp 65001 >nul
echo ============================================
echo 查看 Git 远程仓库位置
echo ============================================
echo.

cd /d "%~dp0"

REM 检查是否在Git仓库中
git rev-parse --git-dir >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 当前目录不是 Git 仓库！
    echo 请先运行 初始化Git仓库.bat
    pause
    exit /b 1
)

echo [当前配置的远程仓库]
echo.
git remote -v
echo.

REM 检查是否有远程仓库
git remote | findstr /C:"." >nul
if %errorlevel% neq 0 (
    echo [提示] 当前没有配置远程仓库
    echo.
    echo 请运行 配置远程仓库.bat 来配置远程仓库
    echo.
    pause
    exit /b 0
)

echo ============================================
echo 远程仓库位置说明
echo ============================================
echo.

REM 检查每个远程仓库
for /f "tokens=1*" %%a in ('git remote') do (
    set remote_name=%%a
    echo 远程仓库: !remote_name!
    git remote get-url !remote_name!
    echo.
)

echo ============================================
echo 如何查看代码
echo ============================================
echo.

echo 方式1：在线仓库（GitHub/Gitee/GitLab）
echo   直接访问上面的URL，在浏览器中查看代码
echo.
echo 方式2：服务器Git仓库
echo   1. SSH连接到服务器
echo   2. 进入项目目录查看
echo   3. 或使用 git clone 克隆到本地
echo.
echo 方式3：查看本地仓库
echo   当前目录就是你的本地仓库
echo   所有文件都在这里
echo.

echo ============================================
echo 查看提交历史
echo ============================================
echo.
echo 最近的5次提交：
echo.
git log --oneline -5
echo.

echo ============================================
echo 查看本地和远程的差异
echo ============================================
echo.
for /f "tokens=1*" %%a in ('git remote') do (
    set remote_name=%%a
    echo 检查 !remote_name! 的同步状态...
    git fetch !remote_name! >nul 2>&1
    git status -sb
    echo.
)

pause

