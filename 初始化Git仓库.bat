@echo off
chcp 65001 >nul
echo ============================================
echo 初始化 Git 仓库
echo ============================================
echo.

cd /d "%~dp0"

REM 检查是否已经是Git仓库
git rev-parse --git-dir >nul 2>&1
if %errorlevel% equ 0 (
    echo [信息] 当前目录已经是 Git 仓库
    echo.
    git remote -v
    echo.
    echo 是否要重新初始化？(Y/N)
    set /p reinit=
    if /i not "%reinit%"=="Y" (
        echo 已取消
        pause
        exit /b 0
    )
    echo.
)

echo [步骤1] 初始化 Git 仓库...
git init
if %errorlevel% neq 0 (
    echo [错误] Git 初始化失败！
    pause
    exit /b 1
)
echo [完成] Git 仓库已初始化
echo.

echo [步骤2] 创建 .gitignore 文件...
if not exist .gitignore (
    (
        echo # Python
        echo __pycache__/
        echo *.py[cod]
        echo *$py.class
        echo *.so
        echo .Python
        echo.
        echo # 数据库文件
        echo *.db
        echo *.sqlite
        echo *.sqlite3
        echo.
        echo # 日志文件
        echo *.log
        echo.
        echo # 环境变量
        echo .env
        echo .venv/
        echo venv/
        echo ENV/
        echo.
        echo # IDE
        echo .vscode/
        echo .idea/
        echo *.swp
        echo *.swo
        echo.
        echo # 上传文件
        echo uploads/
        echo QuickForm/uploads/
        echo Votesite/instance/
        echo.
        echo # 系统文件
        echo .DS_Store
        echo Thumbs.db
        echo.
        echo # 临时文件
        echo *.tmp
        echo *.bak
        echo *.swp
    ) > .gitignore
    echo [完成] .gitignore 文件已创建
) else (
    echo [跳过] .gitignore 文件已存在
)
echo.

echo [步骤3] 添加所有文件到暂存区...
git add .
if %errorlevel% neq 0 (
    echo [错误] 添加文件失败！
    pause
    exit /b 1
)
echo [完成] 文件已添加到暂存区
echo.

echo [步骤4] 创建初始提交...
git commit -m "Initial commit: WzkjHomepage项目初始化"
if %errorlevel% neq 0 (
    echo [错误] 提交失败！
    pause
    exit /b 1
)
echo [完成] 初始提交已创建
echo.

echo ============================================
echo Git 仓库初始化完成！
echo ============================================
echo.
echo 接下来请配置远程仓库：
echo.
echo 方式1：使用 GitHub/Gitee
echo   git remote add origin https://github.com/your-username/your-repo.git
echo   git push -u origin main
echo.
echo 方式2：使用服务器 Git 仓库
echo   在服务器上创建裸仓库后，执行：
echo   git remote add server user@server:/path/to/WzkjHomepage.git
echo   git push -u server main
echo.
echo 详细说明请查看：README_同步方案.md
echo.
pause

