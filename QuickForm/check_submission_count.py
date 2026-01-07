"""
快速检查submission表的数据量
支持SQLite和MySQL两种数据库
"""
import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# 加载环境变量
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(project_root, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    load_dotenv()

# SQLite数据库路径
QUICKFORM_DIR = os.path.dirname(os.path.abspath(__file__))
SQLITE_DB_PATH = os.path.join(QUICKFORM_DIR, 'quickform.db')

# MySQL配置
MYSQL_HOST = os.getenv('MYSQL_HOST', '')
MYSQL_PORT = os.getenv('MYSQL_PORT', '3306')
MYSQL_USER = os.getenv('MYSQL_USER', '')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')
MYSQL_DATABASE = os.getenv('MYSQL_DATABASE', 'quickform')

print("=" * 60)
print("检查submission表数据量")
print("=" * 60)

# 检查SQLite
if os.path.exists(SQLITE_DB_PATH):
    print("\n【SQLite数据库】")
    print(f"数据库文件: {SQLITE_DB_PATH}")
    try:
        sqlite_url = f'sqlite:///{SQLITE_DB_PATH}'
        sqlite_engine = create_engine(sqlite_url, connect_args={'check_same_thread': False})
        sqlite_session = sessionmaker(bind=sqlite_engine)()
        
        # 总记录数
        total_count = sqlite_session.execute(text("SELECT COUNT(*) FROM submission")).fetchone()[0]
        print(f"总记录数: {total_count:,}")
        
        # 按task_id分组统计
        task_stats = sqlite_session.execute(text("""
            SELECT task_id, COUNT(*) as count 
            FROM submission 
            GROUP BY task_id 
            ORDER BY count DESC 
            LIMIT 10
        """)).fetchall()
        
        if task_stats:
            print(f"\n前10个任务的提交数量:")
            for task_id, count in task_stats:
                print(f"  任务ID {task_id}: {count:,} 条")
        
        # 检查孤立记录（任务不存在的提交）
        orphan_count = sqlite_session.execute(text("""
            SELECT COUNT(*) 
            FROM submission s
            LEFT JOIN task t ON s.task_id = t.id
            WHERE t.id IS NULL
        """)).fetchone()[0]
        
        if orphan_count > 0:
            print(f"\n⚠️  孤立记录（任务已删除）: {orphan_count:,} 条")
        
        sqlite_session.close()
    except Exception as e:
        print(f"❌ SQLite查询失败: {str(e)}")
else:
    print(f"\n❌ SQLite数据库文件不存在: {SQLITE_DB_PATH}")

# 检查MySQL
if MYSQL_HOST and MYSQL_USER and MYSQL_PASSWORD:
    print("\n【MySQL数据库】")
    print(f"连接: {MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}")
    try:
        mysql_url = f'mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4'
        mysql_engine = create_engine(mysql_url, pool_pre_ping=True)
        mysql_session = sessionmaker(bind=mysql_engine)()
        
        # 总记录数
        total_count = mysql_session.execute(text("SELECT COUNT(*) FROM submission")).fetchone()[0]
        print(f"总记录数: {total_count:,}")
        
        # 按task_id分组统计
        task_stats = mysql_session.execute(text("""
            SELECT task_id, COUNT(*) as count 
            FROM submission 
            GROUP BY task_id 
            ORDER BY count DESC 
            LIMIT 10
        """)).fetchall()
        
        if task_stats:
            print(f"\n前10个任务的提交数量:")
            for task_id, count in task_stats:
                print(f"  任务ID {task_id}: {count:,} 条")
        
        mysql_session.close()
    except Exception as e:
        print(f"❌ MySQL连接失败: {str(e)}")
        if 'cryptography' in str(e).lower():
            print("   提示: 需要安装cryptography包: pip install cryptography")
else:
    print("\n⚠️  MySQL配置未设置，跳过MySQL检查")

print("\n" + "=" * 60)
