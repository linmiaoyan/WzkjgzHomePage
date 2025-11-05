# PowerShell 快速同步脚本
# 使用方法: .\快速同步.ps1

# 配置区域 - 请修改为你的服务器信息
$ServerUser = "root"
$ServerHost = "your-server-ip-or-domain"
$ServerPort = 22
$ServerPath = "/path/to/WzkjHomepage"
$LocalPath = $PSScriptRoot

# 排除的文件和目录
$ExcludePatterns = @(
    "__pycache__",
    "*.pyc",
    "*.db",
    "*.log",
    ".git",
    "node_modules",
    "uploads",
    "instance"
)

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "快速同步代码到云服务器" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# 检查配置
if ($ServerHost -eq "your-server-ip-or-domain") {
    Write-Host "[错误] 请先修改脚本中的服务器配置！" -ForegroundColor Red
    Write-Host "需要修改的变量："
    Write-Host "  - `$ServerUser: 服务器用户名"
    Write-Host "  - `$ServerHost: 服务器IP或域名"
    Write-Host "  - `$ServerPort: SSH端口"
    Write-Host "  - `$ServerPath: 服务器项目路径"
    Write-Host ""
    Read-Host "按回车退出"
    exit 1
}

Write-Host "[信息] 服务器: ${ServerUser}@${ServerHost}:${ServerPort}" -ForegroundColor Yellow
Write-Host "[信息] 目标路径: $ServerPath" -ForegroundColor Yellow
Write-Host "[信息] 本地路径: $LocalPath" -ForegroundColor Yellow
Write-Host ""

# 检查是否有 scp
$scpPath = Get-Command scp -ErrorAction SilentlyContinue
if (-not $scpPath) {
    Write-Host "[错误] 未找到 scp 命令！" -ForegroundColor Red
    Write-Host ""
    Write-Host "请安装以下工具之一："
    Write-Host "  1. Git for Windows (推荐)"
    Write-Host "  2. OpenSSH for Windows"
    Write-Host ""
    Read-Host "按回车退出"
    exit 1
}

Write-Host "[执行] 开始同步..." -ForegroundColor Green
Write-Host ""

# 同步主要文件
$filesToSync = @(
    "main.py",
    "requirements.txt",
    "QuickForm",
    "Votesite",
    "ChatServer",
    "templates",
    "static"
)

$successCount = 0
$failCount = 0

foreach ($item in $filesToSync) {
    $localItem = Join-Path $LocalPath $item
    if (Test-Path $localItem) {
        Write-Host "同步: $item" -ForegroundColor Cyan
        try {
            # 使用 scp 同步
            $scpArgs = @(
                "-P", $ServerPort,
                "-r",
                $localItem,
                "${ServerUser}@${ServerHost}:${ServerPath}/"
            )
            & scp $scpArgs 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  ✓ 成功" -ForegroundColor Green
                $successCount++
            } else {
                Write-Host "  ✗ 失败 (退出码: $LASTEXITCODE)" -ForegroundColor Red
                $failCount++
            }
        } catch {
            Write-Host "  ✗ 错误: $_" -ForegroundColor Red
            $failCount++
        }
    } else {
        Write-Host "跳过: $item (文件不存在)" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
if ($failCount -eq 0) {
    Write-Host "同步完成！成功: $successCount 个文件/目录" -ForegroundColor Green
} else {
    Write-Host "同步完成，但有错误。成功: $successCount, 失败: $failCount" -ForegroundColor Yellow
}
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "提示：如需重启服务，请在服务器上执行相应命令" -ForegroundColor Yellow
Write-Host ""
Read-Host "按回车退出"

