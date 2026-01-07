# MySQL数据库迁移指南

## 概述

本项目已支持从SQLite升级到MySQL。用户表和答案表（submission表）已分离，便于导出查看用户信息。

## 配置步骤

### 1. 安装依赖

确保已安装MySQL驱动：
```bash
pip install pymysql
```

### 2. 配置环境变量

在项目根目录（`WzkjHomepage` 目录，不是 `QuickForm` 目录）创建或编辑 `.env` 文件，添加以下MySQL配置：

```env
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=your_username
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=quickform
```

**注意：** `.env` 文件应该放在 `WzkjHomepage` 目录下，与 `main.py` 同级。

### 3. 创建MySQL数据库

在MySQL中创建数据库：
```sql
CREATE DATABASE quickform CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 4. 迁移数据

运行迁移脚本（可选，如果需要从SQLite迁移现有数据）：
```bash
cd QuickForm
python migrate_to_mysql.py
```

**注意：** 迁移脚本会：
- 自动创建MySQL数据库表
- 从SQLite数据库迁移所有数据到MySQL
- 跳过已存在的记录（避免重复）

### 5. 启动应用

配置完成后，重启应用即可。系统会自动：
- 检测环境变量中的MySQL配置
- 如果配置完整，使用MySQL数据库
- 如果配置不完整，回退到SQLite（向后兼容）

## 数据库表结构

### 用户表（user）
- 存储用户基本信息
- 包含：用户名、邮箱、密码、学校、手机号、角色等

### 答案表（submission）
- 存储用户提交的表单数据
- 与用户表分离，便于单独导出查看
- 包含：任务ID、提交数据、提交时间等

### 其他表
- task：任务表
- ai_config：AI配置表
- certification_request：认证申请表

## 注意事项

1. **数据备份**：迁移前请备份SQLite数据库文件
2. **服务器部署**：确保服务器上已安装MySQL，并配置好环境变量
3. **权限设置**：确保MySQL用户有创建表和插入数据的权限
4. **字符集**：数据库使用utf8mb4字符集，支持中文和emoji

## 故障排查

如果遇到连接问题：
1. 检查MySQL服务是否运行
2. 检查环境变量配置是否正确
3. 检查MySQL用户权限
4. 查看应用日志获取详细错误信息
