# Git 快速配置指南 - WzkjHomepage

## 🚀 3步完成配置

### 第一步：初始化本地 Git 仓库

**双击运行：** `初始化Git仓库.bat`

这个脚本会自动：
- ✅ 初始化 Git 仓库
- ✅ 创建 .gitignore 文件（排除数据库、缓存等）
- ✅ 添加所有文件
- ✅ 创建初始提交

---

### 第二步：在服务器上创建 Git 仓库

**SSH连接到服务器，执行以下命令：**

```bash
# 1. 创建Git仓库目录
mkdir -p /var/git
cd /var/git

# 2. 初始化裸仓库
git init --bare WzkjHomepage.git

# 3. 设置权限（根据你的Web服务器用户调整）
chown -R www-data:www-data WzkjHomepage.git
# 或者如果是 root 运行
# chown -R root:root WzkjHomepage.git

# 4. 配置项目工作目录（如果还没有）
mkdir -p /var/www/WzkjHomepage
cd /var/www/WzkjHomepage

# 5. 克隆代码（首次）
git clone /var/git/WzkjHomepage.git .

# 6. 配置自动部署（可选，推荐）
cd /var/git/WzkjHomepage.git
cat > hooks/post-receive << 'EOF'
#!/bin/bash
cd /var/www/WzkjHomepage
git checkout -f
chown -R www-data:www-data /var/www/WzkjHomepage
# 如果需要重启服务，取消下面的注释
# systemctl restart wzkjhomepage
EOF
chmod +x hooks/post-receive
```

---

### 第三步：配置本地远程仓库

**双击运行：** `配置远程仓库.bat`

选择 **选项2（服务器Git仓库）**，然后输入：
- 服务器用户名：`root`（或你的用户名）
- 服务器IP或域名：`your-server-ip`
- 服务器Git仓库路径：`/var/git/WzkjHomepage.git`

**或者手动执行命令：**

```bash
cd D:\OneDrive\09教育技术处\WzkjHomepage
git remote add server root@your-server-ip:/var/git/WzkjHomepage.git
git branch -M main
git push -u server main
```

---

## 📝 日常使用

### 修改代码后同步到服务器

**方法1：使用脚本（推荐）**
- 双击运行 `push_to_server.bat`
- 脚本会自动检测更改、提交并推送

**方法2：手动命令**
```bash
git add .
git commit -m "描述你的改动"
git push server main
```

### 在服务器上更新（如果未配置自动部署）

```bash
ssh root@your-server-ip
cd /var/www/WzkjHomepage
git pull server main
# 重启服务（如果需要）
systemctl restart wzkjhomepage
```

---

## 🔐 配置 SSH 密钥（免密码，推荐）

### 1. 在本地生成密钥（如果还没有）

```bash
# Windows PowerShell
ssh-keygen -t rsa -b 4096

# 按回车使用默认路径，可以设置密码或留空
```

### 2. 复制公钥到服务器

```bash
# 方法1：使用 ssh-copy-id（如果可用）
ssh-copy-id root@your-server-ip

# 方法2：手动复制
# 1. 查看公钥
type %USERPROFILE%\.ssh\id_rsa.pub

# 2. 复制输出的内容

# 3. SSH到服务器
ssh root@your-server-ip

# 4. 添加到 authorized_keys
mkdir -p ~/.ssh
echo "粘贴你的公钥内容" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
chmod 700 ~/.ssh
```

### 3. 测试连接

```bash
# 应该不需要密码了
ssh root@your-server-ip
```

---

## 📋 完整示例

假设：
- 服务器IP：`192.168.1.100`
- 服务器用户：`root`
- 项目路径：`/var/www/WzkjHomepage`

### 服务器端（一次性配置）

```bash
# SSH连接
ssh root@192.168.1.100

# 创建Git仓库
mkdir -p /var/git
cd /var/git
git init --bare WzkjHomepage.git
chown -R www-data:www-data WzkjHomepage.git

# 配置项目目录
mkdir -p /var/www/WzkjHomepage
cd /var/www/WzkjHomepage
git clone /var/git/WzkjHomepage.git .

# 配置自动部署
cd /var/git/WzkjHomepage.git
cat > hooks/post-receive << 'EOF'
#!/bin/bash
cd /var/www/WzkjHomepage
git checkout -f
chown -R www-data:www-data /var/www/WzkjHomepage
EOF
chmod +x hooks/post-receive
```

### 本地端（一次性配置）

```bash
# 1. 初始化Git（或运行脚本）
初始化Git仓库.bat

# 2. 配置远程仓库（或运行脚本）
配置远程仓库.bat
# 选择选项2，输入：
#   服务器用户名: root
#   服务器IP: 192.168.1.100
#   仓库路径: /var/git/WzkjHomepage.git

# 3. 推送代码
git push -u server main
```

### 日常使用

```bash
# 修改代码后
push_to_server.bat
# 或
git add .
git commit -m "修复bug"
git push server main
```

---

## ⚙️ 配置说明文件

- `初始化Git仓库.bat` - 初始化本地Git仓库
- `配置远程仓库.bat` - 配置远程仓库连接
- `push_to_server.bat` - 快速同步脚本
- `Git同步使用指南.md` - 详细使用说明
- `服务器端配置说明.md` - 服务器端配置说明

---

## 🎯 推荐配置

### 推荐方案：服务器Git仓库 + 自动部署

**优点：**
- ✅ 配置简单
- ✅ 推送后自动部署
- ✅ 无需第三方服务
- ✅ 代码在服务器上有备份

**配置步骤：**
1. 服务器创建裸仓库
2. 配置自动部署hook
3. 本地配置远程仓库
4. 推送代码即可

---

## ⚠️ 重要提示

1. **数据库文件不会被同步**
   - `.gitignore` 已排除 `*.db` 文件
   - 服务器上的数据库不会被覆盖

2. **上传文件不会被同步**
   - `uploads/` 目录已排除
   - 服务器上的上传文件保留

3. **首次推送后需要配置服务器工作目录**
   - 在服务器上克隆或拉取代码到工作目录

4. **配置SSH密钥后无需每次输入密码**
   - 强烈推荐配置

---

## 🆘 遇到问题？

查看详细文档：
- `Git同步使用指南.md` - 完整使用说明
- `服务器端配置说明.md` - 服务器配置详细步骤

