# GitHub 上传指南

## 📍 你的GitHub仓库

**仓库地址：** https://github.com/linmiaoyan/WzkjgzHomePage

## 🚀 快速上传方法

### 方法1：使用脚本（最简单）

**双击运行：** `上传到GitHub.bat`

这个脚本会自动完成：
1. ✅ 检查并初始化Git仓库
2. ✅ 配置GitHub远程仓库
3. ✅ 添加所有文件
4. ✅ 提交更改
5. ✅ 推送到GitHub

---

## 📋 手动上传步骤

### 步骤1：检查Git是否安装

```bash
git --version
```

如果没有安装，请下载：https://git-scm.com/download/win

---

### 步骤2：进入项目目录

```bash
cd D:\OneDrive\09教育技术处\WzkjHomepage
```

---

### 步骤3：初始化Git仓库（如果还没有）

```bash
# 检查是否已经是Git仓库
git status

# 如果不是，初始化
git init
```

---

### 步骤4：配置GitHub远程仓库

```bash
# 添加远程仓库
git remote add origin https://github.com/linmiaoyan/WzkjgzHomePage.git

# 如果已经存在，更新URL
git remote set-url origin https://github.com/linmiaoyan/WzkjgzHomePage.git

# 查看配置
git remote -v
```

---

### 步骤5：添加文件并提交

```bash
# 添加所有文件
git add .

# 提交更改
git commit -m "Initial commit: 上传项目代码"
```

---

### 步骤6：推送到GitHub

```bash
# 首次推送
git push -u origin main
```

---

## 🔐 认证问题

### 如果推送时要求输入密码

GitHub已经不再支持密码认证，需要使用以下方式之一：

#### 方式1：使用Personal Access Token（推荐）

1. **生成Token**
   - 访问：https://github.com/settings/tokens
   - 点击 "Generate new token" → "Generate new token (classic)"
   - 选择权限：至少勾选 `repo`
   - 生成并复制Token

2. **使用Token**
   - 用户名：输入你的GitHub用户名
   - 密码：输入刚才生成的Token（不是GitHub密码）

#### 方式2：使用SSH密钥（更安全）

1. **生成SSH密钥**
   ```bash
   ssh-keygen -t ed25519 -C "your_email@example.com"
   ```

2. **复制公钥**
   ```bash
   cat ~/.ssh/id_ed25519.pub
   ```

3. **添加到GitHub**
   - 访问：https://github.com/settings/keys
   - 点击 "New SSH key"
   - 粘贴公钥内容

4. **修改远程仓库URL为SSH**
   ```bash
   git remote set-url origin git@github.com:linmiaoyan/WzkjgzHomePage.git
   ```

---

## 🔍 常见问题

### Q1: 提示 "fatal: not a git repository"

**解决方案：**
```bash
git init
```

---

### Q2: 提示 "remote origin already exists"

**解决方案：**
```bash
# 查看现有配置
git remote -v

# 如果需要更新
git remote set-url origin https://github.com/linmiaoyan/WzkjgzHomePage.git
```

---

### Q3: 提示 "failed to push some refs"

**可能原因：**
- 远程仓库已有代码（README.md等）
- 本地和远程历史不一致

**解决方案：**

**方案A：强制推送（会覆盖远程代码）**
```bash
git push -u origin main --force
```

**方案B：先拉取再推送（推荐）**
```bash
# 拉取远程代码
git pull origin main --allow-unrelated-histories

# 解决冲突后
git push -u origin main
```

---

### Q4: 提示 "Authentication failed"

**解决方案：**
1. 使用Personal Access Token代替密码
2. 或配置SSH密钥

---

## 📝 后续更新代码

### 每次修改代码后，使用以下命令：

```bash
# 1. 添加更改
git add .

# 2. 提交更改
git commit -m "描述你的更改"

# 3. 推送到GitHub
git push origin main
```

---

## 🎁 快速脚本

我已经为你创建了 `上传到GitHub.bat`，双击运行即可自动完成所有步骤！

---

## 🔗 相关链接

- **GitHub仓库：** https://github.com/linmiaoyan/WzkjgzHomePage
- **生成Token：** https://github.com/settings/tokens
- **SSH密钥设置：** https://github.com/settings/keys
- **Git下载：** https://git-scm.com/download/win

---

## 💡 提示

1. **首次推送可能需要认证**，准备好GitHub用户名和Token
2. **如果远程仓库已有文件**（如README），可能需要先拉取或强制推送
3. **建议使用SSH方式**，更安全且无需每次输入密码
4. **定期推送**，保持代码同步

