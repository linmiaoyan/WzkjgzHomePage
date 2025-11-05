# 代码同步方案说明

## 🚀 快速开始

### 方案一：使用 rsync 脚本（最简单）

1. **配置服务器信息**
   - 编辑 `sync_config.bat`
   - 修改服务器用户名、IP、路径等信息

2. **运行同步脚本**
   - 双击 `同步到服务器.bat`
   - 自动同步所有文件

### 方案二：使用 Git（推荐）

1. **初始化 Git 仓库**（首次使用）
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   ```

2. **配置远程仓库**
   - 方式A：使用 GitHub/Gitee
   - 方式B：在服务器上创建 Git 仓库

3. **同步代码**
   - 双击 `push_to_server.bat`
   - 自动提交并推送

### 方案三：使用 PowerShell 脚本

1. **修改脚本配置**
   - 编辑 `快速同步.ps1`
   - 修改服务器信息

2. **运行脚本**
   ```powershell
   .\快速同步.ps1
   ```

---

## 📋 各方案对比

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **rsync 脚本** | 简单直接、增量同步 | 需要安装工具 | ⭐⭐⭐⭐ |
| **Git 方案** | 版本控制、可回滚 | 需要学习Git | ⭐⭐⭐⭐⭐ |
| **PowerShell** | Windows原生、功能强大 | 需要PowerShell | ⭐⭐⭐ |

---

## 🔧 详细配置步骤

### rsync 方案配置

1. **安装工具**
   - 安装 Git for Windows（包含 rsync 和 scp）
   - 或安装 cwRsync

2. **配置 sync_config.bat**
   ```batch
   set SERVER_USER=root
   set SERVER_HOST=192.168.1.100
   set SERVER_PORT=22
   set SERVER_PATH=/var/www/WzkjHomepage
   ```

3. **运行同步**
   - 双击 `同步到服务器.bat`

### Git 方案配置

1. **本地初始化**
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   ```

2. **配置远程仓库**

   **方式A：使用 GitHub/Gitee**
   ```bash
   git remote add origin https://github.com/your-repo.git
   git push -u origin main
   ```

   **方式B：服务器 Git 仓库**
   ```bash
   # 服务器上
   cd /path/to
   git init --bare WzkjHomepage.git
   
   # 本地
   git remote add server user@server:/path/to/WzkjHomepage.git
   ```

3. **使用脚本同步**
   - 双击 `push_to_server.bat`

---

## 🎯 推荐工作流程

### 日常开发流程

```bash
# 1. 本地编辑代码
# 2. 测试功能
# 3. 同步到服务器

# 方式A：使用 rsync（快速）
双击 "同步到服务器.bat"

# 方式B：使用 Git（推荐）
双击 "push_to_server.bat"
# 然后在服务器上执行: git pull
```

### 服务器端部署脚本

在服务器上创建 `deploy.sh`：

```bash
#!/bin/bash
cd /path/to/WzkjHomepage

# 拉取最新代码
git pull origin main

# 重启服务（根据实际情况选择）
# sudo systemctl restart wzkjhomepage
# 或
# sudo supervisorctl restart wzkjhomepage
```

---

## ⚙️ 高级配置

### SSH 密钥认证（免密码）

```bash
# 1. 本地生成密钥（如果还没有）
ssh-keygen -t rsa -b 4096

# 2. 复制公钥到服务器
ssh-copy-id user@server-ip

# 3. 测试连接
ssh user@server-ip
```

### 排除文件配置

在 `.gitignore` 或 rsync 排除列表中配置：
- `__pycache__/` - Python缓存
- `*.db` - 数据库文件
- `*.log` - 日志文件
- `uploads/` - 上传文件

---

## 🔍 常见问题

### 1. 提示找不到 scp/rsync

**解决方案：**
- 安装 Git for Windows
- 或安装 OpenSSH for Windows

### 2. 连接被拒绝

**检查：**
- 服务器IP和端口是否正确
- SSH服务是否运行
- 防火墙是否开放端口

### 3. 权限被拒绝

**解决方案：**
- 使用SSH密钥认证
- 或检查服务器用户权限

### 4. 同步后服务未更新

**解决方案：**
- 手动重启服务
- 或配置自动部署脚本

---

## 📝 使用示例

### 示例1：快速同步（rsync）

```batch
# 1. 编辑 sync_config.bat
set SERVER_USER=root
set SERVER_HOST=192.168.1.100
set SERVER_PATH=/var/www/WzkjHomepage

# 2. 双击运行
同步到服务器.bat
```

### 示例2：Git 同步

```bash
# 本地
git add .
git commit -m "修复bug"
git push server main

# 服务器上
cd /var/www/WzkjHomepage
git pull
sudo systemctl restart wzkjhomepage
```

---

## 🎁 额外工具

### 自动部署脚本（服务器端）

创建 `auto_deploy.sh`：

```bash
#!/bin/bash
cd /path/to/WzkjHomepage

# 拉取代码
git pull origin main

# 备份数据库
cp QuickForm/quickform.db QuickForm/quickform.db.backup.$(date +%Y%m%d_%H%M%S)

# 重启服务
sudo systemctl restart wzkjhomepage

echo "部署完成！"
```

然后配置 Git Hook 自动触发（可选）。

---

## 📞 需要帮助？

如果遇到问题，请检查：
1. 服务器连接是否正常
2. SSH密钥是否正确配置
3. 文件路径是否正确
4. 权限是否足够

