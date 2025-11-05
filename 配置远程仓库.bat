@echo off
chcp 65001 >nul
echo ============================================
echo 配置 Git 远程仓库
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

echo 请选择远程仓库配置方式：
echo.
echo 1. 使用 GitHub/Gitee/GitLab 等在线仓库
echo 2. 直接使用服务器上的 Git 仓库
echo 3. 查看当前已配置的远程仓库
echo 4. 删除远程仓库配置
echo.
set /p choice=请输入选项 (1-4): 

if "%choice%"=="1" goto :online_repo
if "%choice%"=="2" goto :server_repo
if "%choice%"=="3" goto :show_remotes
if "%choice%"=="4" goto :remove_remote
goto :invalid_choice

:online_repo
echo.
echo ============================================
echo 配置在线仓库 (GitHub/Gitee/GitLab)
echo ============================================
echo.
echo 请选择仓库平台：
echo 1. GitHub
echo 2. Gitee (码云)
echo 3. GitLab
echo 4. 自定义URL
echo.
set /p platform=请选择 (1-4): 

if "%platform%"=="1" (
    echo 请输入 GitHub 仓库URL（例如：https://github.com/username/repo.git）
    set /p repo_url=仓库URL: 
    set remote_name=origin
) else if "%platform%"=="2" (
    echo 请输入 Gitee 仓库URL（例如：https://gitee.com/username/repo.git）
    set /p repo_url=仓库URL: 
    set remote_name=origin
) else if "%platform%"=="3" (
    echo 请输入 GitLab 仓库URL
    set /p repo_url=仓库URL: 
    set remote_name=origin
) else if "%platform%"=="4" (
    echo 请输入仓库URL
    set /p repo_url=仓库URL: 
    echo 请输入远程仓库名称（默认：origin）
    set /p remote_name=远程名称: 
    if "!remote_name!"=="" set remote_name=origin
) else (
    goto :invalid_choice
)

REM 检查是否已存在同名远程仓库
git remote get-url %remote_name% >nul 2>&1
if %errorlevel% equ 0 (
    echo.
    echo [警告] 远程仓库 '%remote_name%' 已存在
    git remote get-url %remote_name%
    echo.
    set /p replace=是否替换？(Y/N): 
    if /i not "!replace!"=="Y" (
        echo 已取消
        pause
        exit /b 0
    )
    git remote remove %remote_name%
)

git remote add %remote_name% %repo_url%
if %errorlevel% equ 0 (
    echo.
    echo [完成] 远程仓库已配置！
    echo.
    echo 远程仓库信息：
    git remote -v
    echo.
    echo 下一步：推送代码到远程仓库
    set /p push_now=是否立即推送？(Y/N): 
    if /i "!push_now!"=="Y" (
        echo.
        echo 正在推送...
        git branch -M main 2>nul
        git push -u %remote_name% main
        if %errorlevel% equ 0 (
            echo.
            echo [完成] 代码已推送到远程仓库！
        ) else (
            echo.
            echo [错误] 推送失败，请检查：
            echo   1. 仓库URL是否正确
            echo   2. 是否有推送权限
            echo   3. 是否需要配置SSH密钥或访问令牌
        )
    )
) else (
    echo [错误] 配置失败！
)
goto :end

:server_repo
echo.
echo ============================================
echo 配置服务器 Git 仓库
echo ============================================
echo.
echo 请输入服务器信息：
echo.
set /p server_user=服务器用户名（例如：root）: 
set /p server_host=服务器IP或域名: 
set /p server_path=服务器Git仓库路径（例如：/var/git/WzkjHomepage.git）: 
set /p remote_name=远程仓库名称（默认：server）: 
if "!remote_name!"=="" set remote_name=server

echo.
echo [提示] 如果服务器上还没有创建 Git 仓库，请先在服务器上执行：
echo   ssh %server_user%@%server_host%
echo   cd /var/git
echo   git init --bare WzkjHomepage.git
echo.
set /p continue=是否继续配置？(Y/N): 
if /i not "!continue!"=="Y" (
    echo 已取消
    pause
    exit /b 0
)

REM 检查是否已存在同名远程仓库
git remote get-url %remote_name% >nul 2>&1
if %errorlevel% equ 0 (
    echo.
    echo [警告] 远程仓库 '%remote_name%' 已存在
    git remote get-url %remote_name%
    echo.
    set /p replace=是否替换？(Y/N): 
    if /i not "!replace!"=="Y" (
        echo 已取消
        pause
        exit /b 0
    )
    git remote remove %remote_name%
)

set repo_url=%server_user%@%server_host%:%server_path%
git remote add %remote_name% %repo_url%
if %errorlevel% equ 0 (
    echo.
    echo [完成] 远程仓库已配置！
    echo.
    echo 远程仓库信息：
    git remote -v
    echo.
    echo 下一步：推送代码到服务器
    set /p push_now=是否立即推送？(Y/N): 
    if /i "!push_now!"=="Y" (
        echo.
        echo 正在推送...
        git branch -M main 2>nul
        git push -u %remote_name% main
        if %errorlevel% equ 0 (
            echo.
            echo [完成] 代码已推送到服务器！
            echo.
            echo [提示] 在服务器上，需要将代码检出到工作目录：
            echo   cd /path/to/WzkjHomepage
            echo   git clone %repo_url% .
            echo   或
            echo   git pull %remote_name% main
        ) else (
            echo.
            echo [错误] 推送失败，请检查：
            echo   1. 服务器路径是否正确
            echo   2. SSH连接是否正常
            echo   3. 是否有推送权限
        )
    )
) else (
    echo [错误] 配置失败！
)
goto :end

:show_remotes
echo.
echo ============================================
echo 当前远程仓库配置
echo ============================================
echo.
git remote -v
if %errorlevel% neq 0 (
    echo [信息] 当前没有配置远程仓库
)
goto :end

:remove_remote
echo.
echo ============================================
echo 删除远程仓库配置
echo ============================================
echo.
git remote -v
echo.
set /p remote_name=请输入要删除的远程仓库名称: 
if "!remote_name!"=="" (
    echo 已取消
    goto :end
)
git remote remove %remote_name%
if %errorlevel% equ 0 (
    echo [完成] 远程仓库 '%remote_name%' 已删除
) else (
    echo [错误] 删除失败，可能不存在该远程仓库
)
goto :end

:invalid_choice
echo [错误] 无效的选项！
goto :end

:end
echo.
pause

