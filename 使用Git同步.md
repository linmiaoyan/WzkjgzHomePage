# 使用 Git 同步代码到服务器

## 方案一：Git 同步（推荐）

### 优点
- ✅ 版本控制，可以回滚
- ✅ 只同步改动的文件
- ✅ 支持分支管理
- ✅ 可以查看改动历史

### 步骤

#### 1. 在本地初始化 Git（如果还没有）

```bash
cd D:\OneDrive\09教育技术处\WzkjHomepage
git init
git add .
git commit -m "Initial commit"
```

#### 2. 创建 .gitignore 文件

```
__pycache__/
*.pyc
*.pyo
*.db
*.log
.env
.venv/
venv/
*.bat
*.md
uploads/
instance/
```

#### 3. 在服务器上设置 Git 仓库

**方式A：使用远程仓库（GitHub/Gitee）**

```bash
# 本地
git remote add origin https://your-repo-url.git
git push -u origin main
```

**📌 如何查看上传的代码在哪里？**

**方法1：使用脚本（最简单）**
- 双击运行 `查看Git仓库位置.bat`
- 会显示所有远程仓库的URL

**方法2：命令行查看**
```bash
# 查看所有远程仓库
git remote -v

# 查看特定远程仓库的URL
git remote get-url origin
```

**访问方式：**
- **GitHub/Gitee/GitLab**：直接在浏览器访问显示的URL
- **服务器Git仓库**：SSH连接到服务器，在配置的路径查看

**服务器上**
```bash
cd /path/to/WzkjHomepage
git clone https://your-repo-url.git .
```

**方式B：直接在服务器上创建裸仓库**

```bash
# 服务器上
cd /path/to
git init --bare WzkjHomepage.git

# 本地
git remote add server user@server:/path/to/WzkjHomepage.git
git push server main
```

#### 4. 创建同步脚本

**本地：push_to_server.bat**
```batch
@echo off
chcp 65001 >nul
echo 提交并推送到服务器...
git add .
git commit -m "Update: %date% %time%"
git push server main
echo 完成！
pause
```

**服务器：pull_update.sh**
```bash
#!/bin/bash
cd /path/to/WzkjHomepage
git pull origin main
# 如果需要重启服务
# sudo systemctl restart your-service
```

---

## 方案二：rsync 同步（简单直接）

### 使用步骤

1. **配置 sync_config.bat**
   - 设置服务器信息

2. **运行 同步到服务器.bat**
   - 双击运行即可

### 需要安装的工具

**Windows 上安装 rsync：**
- 方法1：安装 Git for Windows（包含 rsync）
- 方法2：安装 cwRsync
- 方法3：使用 WSL（Windows Subsystem for Linux）

---

## 方案三：使用 SSH + 手动命令

### 创建快速同步脚本

**sync_simple.bat**
```batch
@echo off
set SERVER=user@server-ip
set SERVER_PATH=/path/to/WzkjHomepage

echo 同步 Python 文件...
scp main.py %SERVER%:%SERVER_PATH%/

echo 同步 QuickForm...
scp -r QuickForm\*.py %SERVER%:%SERVER_PATH%/QuickForm/
scp -r QuickForm\templates\*.html %SERVER%:%SERVER_PATH%/QuickForm/templates/

echo 同步完成！
pause
```

---

## 推荐方案对比

| 方案 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| Git | 版本控制、可回滚、专业 | 需要学习Git、需要配置 | 长期项目、多人协作 |
| rsync | 简单、快速、增量同步 | 需要安装工具 | 频繁更新、小改动 |
| scp | 系统自带、无需安装 | 功能有限、不支持增量 | 偶尔更新、简单项目 |

---

## 推荐工作流程

### 使用 Git（最佳实践）

```bash
# 1. 本地修改代码
# 2. 提交更改
git add .
git commit -m "描述改动内容"

# 3. 推送到服务器
git push server main

# 4. 在服务器上拉取（或自动部署）
ssh user@server "cd /path/to/WzkjHomepage && git pull"
```

### 使用 rsync（快速同步）

```bash
# 1. 配置 sync_config.bat
# 2. 双击运行 同步到服务器.bat
```

---

## 自动化部署脚本（服务器端）

在服务器上创建 `deploy.sh`：

```bash
#!/bin/bash
cd /path/to/WzkjHomepage

# 拉取最新代码
git pull origin main

# 重启服务（根据你的部署方式选择）
# 方式1: systemd
# sudo systemctl restart wzkjhomepage

# 方式2: supervisor
# sudo supervisorctl restart wzkjhomepage

# 方式3: 直接运行
# pkill -f "python.*main.py"
# nohup python main.py > /dev/null 2>&1 &

echo "部署完成！"
```

---

## 安全建议

1. **使用 SSH 密钥认证**（避免每次输入密码）
   ```bash
   # 本地生成密钥
   ssh-keygen -t rsa
   
   # 复制到服务器
   ssh-copy-id user@server
   ```

2. **不要在代码中硬编码密码**
   - 使用环境变量
   - 使用配置文件（不提交到Git）

3. **备份数据库**
   - 同步前备份服务器上的数据库文件

