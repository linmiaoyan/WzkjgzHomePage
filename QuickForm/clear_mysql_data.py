"""
清理MySQL数据库数据
⚠️ 警告：此脚本会删除数据库中的所有数据，请谨慎使用！
"""
import os
import sys
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 加载环境变量
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(project_root, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    load_dotenv()

# MySQL配置
MYSQL_HOST = os.getenv('MYSQL_HOST', '')
MYSQL_PORT = os.getenv('MYSQL_PORT', '3306')
MYSQL_USER = os.getenv('MYSQL_USER', '')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')
MYSQL_DATABASE = os.getenv('MYSQL_DATABASE', 'quickform')

def get_table_counts(mysql_session):
    """获取所有表的数据量"""
    inspector = inspect(mysql_session.bind)
    tables = inspector.get_table_names()
    
    counts = {}
    for table in tables:
        try:
            count = mysql_session.execute(text(f"SELECT COUNT(*) FROM `{table}`")).fetchone()[0]
            counts[table] = count
        except Exception as e:
            logger.warning(f"无法获取表 {table} 的记录数: {str(e)}")
            counts[table] = -1
    
    return counts

def clear_all_tables(mysql_session, confirm=False):
    """清理所有表的数据"""
    if not confirm:
        logger.error("需要确认参数才能执行清理操作")
        return False
    
    inspector = inspect(mysql_session.bind)
    tables = inspector.get_table_names()
    
    # 按照外键依赖顺序删除（先删除子表，再删除父表）
    # 通常的顺序：submission -> task -> user, ai_config, certification_request
    table_order = ['submission', 'task', 'certification_request', 'ai_config', 'user']
    
    # 确保所有表都在列表中
    for table in tables:
        if table not in table_order:
            table_order.append(table)
    
    total_deleted = 0
    
    try:
        for table in table_order:
            if table not in tables:
                continue
            
            try:
                # 获取删除前的记录数
                count = mysql_session.execute(text(f"SELECT COUNT(*) FROM `{table}`")).fetchone()[0]
                
                if count > 0:
                    # 禁用外键检查（MySQL）
                    mysql_session.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
                    
                    # 删除所有数据
                    mysql_session.execute(text(f"DELETE FROM `{table}`"))
                    
                    # 重新启用外键检查
                    mysql_session.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
                    
                    mysql_session.commit()
                    logger.info(f"✓ 已清理表 {table}: 删除了 {count:,} 条记录")
                    total_deleted += count
                else:
                    logger.info(f"  表 {table}: 无数据")
                    
            except Exception as e:
                logger.error(f"清理表 {table} 失败: {str(e)}")
                mysql_session.rollback()
                continue
        
        logger.info(f"\n清理完成！总共删除了 {total_deleted:,} 条记录")
        return True
        
    except Exception as e:
        logger.error(f"清理过程出错: {str(e)}", exc_info=True)
        mysql_session.rollback()
        return False

def clear_specific_table(mysql_session, table_name, confirm=False):
    """清理指定表的数据"""
    if not confirm:
        logger.error("需要确认参数才能执行清理操作")
        return False
    
    inspector = inspect(mysql_session.bind)
    tables = inspector.get_table_names()
    
    if table_name not in tables:
        logger.error(f"表 {table_name} 不存在")
        return False
    
    try:
        # 获取删除前的记录数
        count = mysql_session.execute(text(f"SELECT COUNT(*) FROM `{table_name}`")).fetchone()[0]
        
        if count == 0:
            logger.info(f"表 {table_name} 无数据")
            return True
        
        # 禁用外键检查（MySQL）
        mysql_session.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        
        # 删除所有数据
        mysql_session.execute(text(f"DELETE FROM `{table_name}`"))
        
        # 重新启用外键检查
        mysql_session.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        
        mysql_session.commit()
        logger.info(f"✓ 已清理表 {table_name}: 删除了 {count:,} 条记录")
        return True
        
    except Exception as e:
        logger.error(f"清理表 {table_name} 失败: {str(e)}", exc_info=True)
        mysql_session.rollback()
        return False

def main():
    """主函数"""
    if not MYSQL_HOST or not MYSQL_USER or not MYSQL_PASSWORD:
        logger.error("请先配置MySQL环境变量：MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE")
        return
    
    logger.info(f"连接MySQL: {MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}")
    
    try:
        mysql_url = f'mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4'
        mysql_engine = create_engine(mysql_url, pool_pre_ping=True)
        mysql_session = sessionmaker(bind=mysql_engine)()
        
        # 测试连接
        mysql_session.execute(text("SELECT 1"))
        logger.info("MySQL连接成功")
        
        # 显示当前数据量
        logger.info("\n" + "=" * 60)
        logger.info("当前数据库数据量：")
        logger.info("=" * 60)
        counts = get_table_counts(mysql_session)
        for table, count in counts.items():
            if count >= 0:
                logger.info(f"  {table}: {count:,} 条记录")
            else:
                logger.info(f"  {table}: 无法获取")
        
        total = sum(c for c in counts.values() if c >= 0)
        logger.info(f"\n总计: {total:,} 条记录")
        logger.info("=" * 60)
        
        # 检查命令行参数
        if len(sys.argv) > 1:
            command = sys.argv[1].lower()
            
            if command == '--all' or command == 'all':
                # 清理所有表
                if len(sys.argv) > 2 and sys.argv[2] == '--confirm':
                    logger.warning("\n⚠️  警告：即将删除所有数据！")
                    clear_all_tables(mysql_session, confirm=True)
                else:
                    logger.error("\n⚠️  危险操作！需要确认参数")
                    logger.error("使用方法: python clear_mysql_data.py all --confirm")
                    logger.error("这将删除所有表的数据，请谨慎操作！")
            
            elif command.startswith('--table=') or command.startswith('table='):
                # 清理指定表
                table_name = command.split('=')[1] if '=' in command else sys.argv[2]
                if len(sys.argv) > 2 and '--confirm' in sys.argv:
                    logger.warning(f"\n⚠️  警告：即将删除表 {table_name} 的所有数据！")
                    clear_specific_table(mysql_session, table_name, confirm=True)
                else:
                    logger.error(f"\n⚠️  危险操作！需要确认参数")
                    logger.error(f"使用方法: python clear_mysql_data.py --table={table_name} --confirm")
                    logger.error(f"这将删除表 {table_name} 的所有数据，请谨慎操作！")
            
            else:
                logger.error(f"未知命令: {command}")
                show_usage()
        else:
            show_usage()
        
        mysql_session.close()
        
    except Exception as e:
        logger.error(f"MySQL连接失败: {str(e)}", exc_info=True)
        if 'cryptography' in str(e).lower():
            logger.error("提示: 需要安装cryptography包: pip install cryptography")

def show_usage():
    """显示使用说明"""
    logger.info("\n" + "=" * 60)
    logger.info("使用说明：")
    logger.info("=" * 60)
    logger.info("1. 查看当前数据量（不执行删除）：")
    logger.info("   python clear_mysql_data.py")
    logger.info("")
    logger.info("2. 清理所有表的数据：")
    logger.info("   python clear_mysql_data.py all --confirm")
    logger.info("")
    logger.info("3. 清理指定表的数据：")
    logger.info("   python clear_mysql_data.py --table=submission --confirm")
    logger.info("   python clear_mysql_data.py --table=task --confirm")
    logger.info("")
    logger.info("⚠️  警告：此操作不可逆，请谨慎使用！")
    logger.info("=" * 60)

if __name__ == '__main__':
    main()
