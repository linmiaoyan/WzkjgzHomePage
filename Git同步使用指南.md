# Git 同步方案使用指南

## 📋 快速开始

### 第一步：初始化 Git 仓库

**方法1：使用脚本（推荐）**
1. 双击运行 `初始化Git仓库.bat`
2. 脚本会自动：
   - 初始化 Git 仓库
   - 创建 .gitignore 文件
   - 添加所有文件
   - 创建初始提交

**方法2：手动执行**
```bash
cd D:\OneDrive\09教育技术处\WzkjHomepage
git init
git add .
git commit -m "Initial commit"
```

### 第二步：配置远程仓库

**方法1：使用脚本（推荐）**
1. 双击运行 `配置远程仓库.bat`
2. 选择配置方式（在线仓库或服务器仓库）
3. 按提示输入信息

**方法2：手动配置**

#### 方式A：使用 GitHub/Gitee（推荐新手）

**步骤：**
1. 在 GitHub/Gitee 上创建新仓库
2. 复制仓库URL（例如：`https://github.com/username/WzkjHomepage.git`）
3. 执行以下命令：
```bash
git remote add origin https://github.com/username/WzkjHomepage.git
git branch -M main
git push -u origin main
```

#### 方式B：使用服务器 Git 仓库（推荐部署）

**步骤：**

**1. 在服务器上创建 Git 仓库**
```bash
# SSH连接到服务器
ssh root@your-server-ip

# 创建Git仓库目录
mkdir -p /var/git
cd /var/git

# 创建裸仓库
git init --bare WzkjHomepage.git

# 设置权限（如果需要）
chown -R www-data:www-data WzkjHomepage.git
```

**2. 在本地配置远程仓库**
```bash
# 在本地项目目录执行
git remote add server root@your-server-ip:/var/git/WzkjHomepage.git
git branch -M main
git push -u server main
```

**3. 在服务器上检出代码**
```bash
# SSH连接到服务器
ssh root@your-server-ip

# 进入项目目录
cd /var/www/WzkjHomepage  # 或你的实际项目路径

# 克隆代码（首次）
git clone /var/git/WzkjHomepage.git .

# 或如果目录已存在，直接拉取
git pull server main
```

---

## 🚀 日常使用

### 同步代码到服务器

**方法1：使用脚本（最简单）**
1. 修改代码后，双击运行 `push_to_server.bat`
2. 脚本会自动：
   - 检测未提交的更改
   - 提示是否提交
   - 推送到远程仓库

**方法2：手动命令**
```bash
# 1. 添加更改
git add .

# 2. 提交更改
git commit -m "描述你的改动"

# 3. 推送到服务器
git push server main
```

### 在服务器上更新代码

```bash
# SSH连接到服务器
ssh root@your-server-ip

# 进入项目目录
cd /var/www/WzkjHomepage

# 拉取最新代码
git pull server main

# 重启服务（根据实际情况）
# sudo systemctl restart wzkjhomepage
# 或
# sudo supervisorctl restart wzkjhomepage
```

---

## 🔧 服务器端自动部署配置

### 方案1：Git Hook 自动部署（推荐）

**在服务器上配置：**

```bash
# 1. 进入Git仓库目录
cd /var/git/WzkjHomepage.git

# 2. 创建 post-receive hook
cat > hooks/post-receive << 'EOF'
#!/bin/bash
WORK_TREE=/var/www/WzkjHomepage
GIT_DIR=/var/git/WzkjHomepage.git

cd $WORK_TREE || exit
unset GIT_DIR
git checkout -f

# 重启服务
# sudo systemctl restart wzkjhomepage
# 或
# sudo supervisorctl restart wzkjhomepage

echo "部署完成！"
EOF

# 3. 设置执行权限
chmod +x hooks/post-receive

# 4. 设置工作目录权限
chown -R www-data:www-data /var/www/WzkjHomepage
```

**配置后，每次推送代码会自动部署！**

### 方案2：手动部署脚本

在服务器上创建 `deploy.sh`：

```bash
#!/bin/bash
cd /var/www/WzkjHomepage

# 备份数据库（可选）
cp QuickForm/quickform.db QuickForm/quickform.db.backup.$(date +%Y%m%d_%H%M%S)

# 拉取最新代码
git pull server main

# 重启服务
sudo systemctl restart wzkjhomepage

echo "部署完成！"
```

使用：
```bash
chmod +x deploy.sh
./deploy.sh
```

---

## 📝 完整工作流程示例

### 场景：修复一个bug

```bash
# 1. 本地修改代码
# ... 编辑文件 ...

# 2. 提交更改
git add .
git commit -m "修复数据分析报告生成问题"

# 3. 推送到服务器（或远程仓库）
git push server main

# 4. 在服务器上更新（如果使用手动部署）
ssh root@server
cd /var/www/WzkjHomepage
git pull server main
sudo systemctl restart wzkjhomepage
```

---

## 🔐 SSH 密钥配置（免密码）

### 生成SSH密钥（如果还没有）

```bash
# 在本地执行
ssh-keygen -t rsa -b 4096 -C "your_email@example.com"

# 按回车使用默认路径
# 可以设置密码或留空
```

### 复制公钥到服务器

```bash
# 方法1：使用 ssh-copy-id（推荐）
ssh-copy-id root@your-server-ip

# 方法2：手动复制
# 1. 查看公钥
cat ~/.ssh/id_rsa.pub

# 2. SSH到服务器
ssh root@your-server-ip

# 3. 添加到 authorized_keys
mkdir -p ~/.ssh
echo "你的公钥内容" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

### 测试连接

```bash
# 测试SSH连接（应该不需要密码）
ssh root@your-server-ip

# 测试Git连接
git ls-remote server
```

---

## 🎯 推荐配置方案

### 方案A：GitHub + 服务器自动部署（最佳）

**架构：**
```
本地 → GitHub → 服务器（自动拉取）
```

**优点：**
- ✅ 代码有备份
- ✅ 可以查看历史
- ✅ 支持多人协作
- ✅ 服务器自动部署

**配置步骤：**
1. 在 GitHub 创建仓库
2. 本地推送到 GitHub
3. 服务器定期拉取或使用 Webhook 自动部署

### 方案B：服务器Git仓库（最简单）

**架构：**
```
本地 → 服务器Git仓库 → 服务器工作目录
```

**优点：**
- ✅ 配置简单
- ✅ 直接推送
- ✅ 无需第三方服务

**配置步骤：**
1. 服务器创建裸仓库
2. 本地配置远程仓库
3. 服务器检出代码

---

## ⚠️ 注意事项

1. **不要提交敏感信息**
   - 密码、API密钥等
   - 数据库文件
   - 使用 `.gitignore` 排除

2. **数据库文件处理**
   - 数据库文件已配置在 `.gitignore` 中
   - 服务器上的数据库不会被子覆盖

3. **文件权限**
   - 确保服务器上的文件权限正确
   - 上传目录需要有写权限

4. **备份**
   - 部署前建议备份数据库
   - 重要更改前创建分支

---

## 🆘 常见问题

### Q1: 推送时提示权限被拒绝

**解决方案：**
- 配置SSH密钥
- 检查服务器用户权限
- 检查Git仓库权限

### Q2: 服务器上代码冲突

**解决方案：**
```bash
# 在服务器上
cd /var/www/WzkjHomepage
git stash
git pull server main
git stash pop
```

### Q3: 想回退到之前的版本

**解决方案：**
```bash
# 查看历史
git log

# 回退到指定提交
git reset --hard <commit-hash>

# 强制推送（谨慎使用）
git push server main --force
```

---

## 📞 快速命令参考

```bash
# 初始化仓库
git init

# 添加文件
git add .

# 提交更改
git commit -m "提交信息"

# 查看状态
git status

# 查看历史
git log

# 添加远程仓库
git remote add server user@server:/path/to/repo.git

# 推送代码
git push server main

# 拉取代码
git pull server main

# 查看远程仓库
git remote -v

# 删除远程仓库
git remote remove server
```

