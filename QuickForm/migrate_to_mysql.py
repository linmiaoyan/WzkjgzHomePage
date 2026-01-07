"""
数据库迁移脚本：从SQLite迁移到MySQL
使用方法：
1. 配置环境变量：MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE
2. 运行此脚本：python migrate_to_mysql.py
"""
import os
import sys
import hashlib
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import logging

# 加载环境变量
# 尝试从项目根目录（WzkjHomepage）加载.env文件
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(project_root, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    # 如果项目根目录没有.env，尝试当前目录
    load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 创建跳过记录的详细日志文件
QUICKFORM_DIR = os.path.dirname(os.path.abspath(__file__))
skip_log_file = os.path.join(QUICKFORM_DIR, 'migration_skipped_records.log')
skip_logger = logging.getLogger('skip_records')
skip_logger.setLevel(logging.INFO)
skip_file_handler = logging.FileHandler(skip_log_file, mode='w', encoding='utf-8')
skip_file_handler.setFormatter(logging.Formatter('%(message)s'))
skip_logger.addHandler(skip_file_handler)
skip_logger.propagate = False  # 避免重复输出到主日志

# 跳过记录的统计
skip_statistics = {
    'duplicate_id': 0,  # ID重复
    'duplicate_business_key': 0,  # 业务唯一键重复
    'orphan_task': 0,  # 任务不存在（孤立记录）
    'duplicate_db': 0,  # 数据库层面重复
    'data_too_long': 0,  # 数据过长
    'foreign_key_error': 0,  # 外键错误
    'other_error': 0  # 其他错误
}

# SQLite数据库路径
QUICKFORM_DIR = os.path.dirname(os.path.abspath(__file__))
SQLITE_DB_PATH = os.path.join(QUICKFORM_DIR, 'quickform.db')

# MySQL配置
MYSQL_HOST = os.getenv('MYSQL_HOST', '')
MYSQL_PORT = os.getenv('MYSQL_PORT', '3306')
MYSQL_USER = os.getenv('MYSQL_USER', '')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')
MYSQL_DATABASE = os.getenv('MYSQL_DATABASE', 'quickform')

def try_single_record_read(sqlite_session, mysql_session, submission_columns, existing_submission_ids, 
                           existing_task_ids_set, start_id, max_id, MAX_TEXT_LENGTH, submission_count, skip_count):
    """尝试逐条读取指定ID范围的记录，用于处理损坏的数据库页面"""
    logger.info(f"开始逐条读取ID范围: {start_id} - {min(start_id + 100, max_id)}")
    success_count = 0
    fail_count = 0
    
    for test_id in range(start_id, min(start_id + 100, max_id + 1)):
        try:
            query = f"SELECT * FROM submission WHERE id = {test_id}"
            result = sqlite_session.execute(text(query)).fetchone()
            
            if result and result[0] not in existing_submission_ids:
                values = dict(zip(submission_columns, result))
                
                if 'data' in values and values['data'] is not None:
                    data_value = str(values['data'])
                    if len(data_value) > MAX_TEXT_LENGTH:
                        truncated = data_value[:MAX_TEXT_LENGTH]
                        logger.warning(f"提交ID={result[0]}的data字段过长，已截断")
                        values['data'] = truncated
                
                task_id = values.get('task_id')
                submitted_at = values.get('submitted_at')
                data = str(values.get('data', '')) if values.get('data') is not None else ''
                
                if task_id is not None and task_id not in existing_task_ids_set:
                    skip_count += 1
                    skip_statistics['orphan_task'] += 1
                    data_preview = data[:100] + '...' if len(data) > 100 else data
                    skip_logger.info(f"[孤立记录-任务不存在] ID={result[0]}, task_id={task_id}, submitted_at={submitted_at}, data_preview={data_preview}")
                    logger.warning(f"跳过提交（任务不存在）: ID={result[0]}, task_id={task_id}")
                    continue
                
                column_names = ', '.join([f'`{col}`' for col in submission_columns])
                placeholders = ', '.join([f':{col}' for col in submission_columns])
                insert_sql = f"INSERT INTO submission ({column_names}) VALUES ({placeholders})"
                
                try:
                    mysql_session.execute(text(insert_sql), values)
                    submission_count += 1
                    existing_submission_ids.add(result[0])
                    success_count += 1
                    if success_count % 10 == 0:
                        mysql_session.commit()
                except Exception as e:
                    error_msg = str(e)
                    skip_count += 1
                    data_preview = data[:100] + '...' if len(data) > 100 else data
                    
                    if 'Duplicate entry' in error_msg or '1062' in error_msg:
                        skip_statistics['duplicate_db'] += 1
                        skip_logger.info(f"[数据库层面重复] ID={result[0]}, task_id={task_id}, submitted_at={submitted_at}, error={error_msg}, data_preview={data_preview}")
                    elif 'Data too long' in error_msg or '1406' in error_msg:
                        skip_statistics['data_too_long'] += 1
                        skip_logger.info(f"[数据过长] ID={result[0]}, task_id={task_id}, submitted_at={submitted_at}, data_length={len(data)}, error={error_msg}")
                    elif 'foreign key' in error_msg.lower() or '1452' in error_msg:
                        skip_statistics['foreign_key_error'] += 1
                        skip_logger.info(f"[外键错误] ID={result[0]}, task_id={task_id}, submitted_at={submitted_at}, error={error_msg}")
                    else:
                        skip_statistics['other_error'] += 1
                        skip_logger.info(f"[其他错误] ID={result[0]}, task_id={task_id}, submitted_at={submitted_at}, error={error_msg}, data_preview={data_preview}")
                        logger.warning(f"插入失败 ID={result[0]}: {error_msg}")
                    
        except Exception as e:
            fail_count += 1
            if fail_count <= 5:  # 只记录前5个错误，避免日志过多
                logger.debug(f"无法读取ID={test_id}: {str(e)}")
            continue
    
    if success_count > 0:
        mysql_session.commit()
        logger.info(f"逐条读取完成: 成功 {success_count} 条，失败 {fail_count} 条")
    
    return submission_count, skip_count

def try_single_record_read_by_offset(sqlite_session, mysql_session, submission_columns, existing_submission_ids,
                                     existing_task_ids_set, offset, batch_size, MAX_TEXT_LENGTH, submission_count, skip_count):
    """尝试逐条读取指定偏移量范围的记录"""
    logger.info(f"开始逐条读取偏移量范围: {offset} - {offset + batch_size}")
    success_count = 0
    fail_count = 0
    
    # 尝试获取这个范围内的ID列表
    try:
        id_query = f"SELECT id FROM submission ORDER BY id LIMIT {batch_size} OFFSET {offset}"
        id_list = [row[0] for row in sqlite_session.execute(text(id_query)).fetchall()]
        
        for record_id in id_list:
            try:
                query = f"SELECT * FROM submission WHERE id = {record_id}"
                result = sqlite_session.execute(text(query)).fetchone()
                
                if result and result[0] not in existing_submission_ids:
                    values = dict(zip(submission_columns, result))
                    
                    if 'data' in values and values['data'] is not None:
                        data_value = str(values['data'])
                        if len(data_value) > MAX_TEXT_LENGTH:
                            truncated = data_value[:MAX_TEXT_LENGTH]
                            values['data'] = truncated
                    
                    task_id = values.get('task_id')
                    submitted_at = values.get('submitted_at')
                    data = str(values.get('data', '')) if values.get('data') is not None else ''
                    
                    if task_id is not None and task_id not in existing_task_ids_set:
                        skip_count += 1
                        skip_statistics['orphan_task'] += 1
                        data_preview = data[:100] + '...' if len(data) > 100 else data
                        skip_logger.info(f"[孤立记录-任务不存在] ID={record_id}, task_id={task_id}, submitted_at={submitted_at}, data_preview={data_preview}")
                        continue
                    
                    column_names = ', '.join([f'`{col}`' for col in submission_columns])
                    placeholders = ', '.join([f':{col}' for col in submission_columns])
                    insert_sql = f"INSERT INTO submission ({column_names}) VALUES ({placeholders})"
                    
                    try:
                        mysql_session.execute(text(insert_sql), values)
                        submission_count += 1
                        existing_submission_ids.add(result[0])
                        success_count += 1
                        if success_count % 10 == 0:
                            mysql_session.commit()
                    except Exception as e:
                        error_msg = str(e)
                        skip_count += 1
                        data_preview = data[:100] + '...' if len(data) > 100 else data
                        
                        if 'Duplicate entry' in error_msg or '1062' in error_msg:
                            skip_statistics['duplicate_db'] += 1
                            skip_logger.info(f"[数据库层面重复] ID={record_id}, task_id={task_id}, submitted_at={submitted_at}, error={error_msg}, data_preview={data_preview}")
                        elif 'Data too long' in error_msg or '1406' in error_msg:
                            skip_statistics['data_too_long'] += 1
                            skip_logger.info(f"[数据过长] ID={record_id}, task_id={task_id}, submitted_at={submitted_at}, data_length={len(data)}, error={error_msg}")
                        elif 'foreign key' in error_msg.lower() or '1452' in error_msg:
                            skip_statistics['foreign_key_error'] += 1
                            skip_logger.info(f"[外键错误] ID={record_id}, task_id={task_id}, submitted_at={submitted_at}, error={error_msg}")
                        else:
                            skip_statistics['other_error'] += 1
                            skip_logger.info(f"[其他错误] ID={record_id}, task_id={task_id}, submitted_at={submitted_at}, error={error_msg}, data_preview={data_preview}")
                            logger.warning(f"插入失败 ID={record_id}: {error_msg}")
                        
            except Exception as e:
                fail_count += 1
                if fail_count <= 5:
                    logger.debug(f"无法读取ID={record_id}: {str(e)}")
                continue
                
    except Exception as e:
        logger.warning(f"无法获取ID列表: {str(e)}")
    
    if success_count > 0:
        mysql_session.commit()
        logger.info(f"逐条读取完成: 成功 {success_count} 条，失败 {fail_count} 条")
    
    return submission_count, skip_count

def migrate_data():
    """迁移数据从SQLite到MySQL"""
    if not MYSQL_HOST or not MYSQL_USER or not MYSQL_PASSWORD:
        logger.error("请先配置MySQL环境变量：MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE")
        logger.error("提示：请确保MySQL服务已启动，并且.env文件中的配置正确")
        return False
    
    # 检查cryptography包（MySQL 8.0的caching_sha2_password认证需要）
    try:
        import cryptography
        logger.debug("cryptography包已安装")
    except ImportError:
        logger.error("=" * 60)
        logger.error("缺少必需的依赖包：cryptography")
        logger.error("MySQL 8.0默认使用caching_sha2_password认证，需要cryptography包")
        logger.error("")
        logger.error("解决方案：")
        logger.error("  方法1（推荐）：安装cryptography包")
        logger.error("    pip install cryptography")
        logger.error("")
        logger.error("  方法2：修改MySQL用户认证方式（需要MySQL管理员权限）")
        logger.error("    ALTER USER 'your_user'@'localhost' IDENTIFIED WITH mysql_native_password BY 'your_password';")
        logger.error("    FLUSH PRIVILEGES;")
        logger.error("=" * 60)
        return False
    
    # 测试MySQL连接
    logger.info(f"尝试连接MySQL: {MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}")
    
    if not os.path.exists(SQLITE_DB_PATH):
        logger.error(f"SQLite数据库文件不存在: {SQLITE_DB_PATH}")
        return False
    
    # 连接SQLite
    sqlite_url = f'sqlite:///{SQLITE_DB_PATH}'
    sqlite_engine = create_engine(sqlite_url, connect_args={'check_same_thread': False})
    sqlite_session = sessionmaker(bind=sqlite_engine)()
    
    # 连接MySQL
    try:
        mysql_url = f'mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4'
        mysql_engine = create_engine(mysql_url, pool_pre_ping=True)
        mysql_session = sessionmaker(bind=mysql_engine)()
        
        # 测试连接
        mysql_session.execute(text("SELECT 1"))
        logger.info("MySQL连接成功")
    except RuntimeError as e:
        if 'cryptography' in str(e).lower():
            logger.error("=" * 60)
            logger.error("MySQL连接失败：缺少cryptography包")
            logger.error("")
            logger.error("解决方案：")
            logger.error("  安装cryptography包：pip install cryptography")
            logger.error("=" * 60)
        else:
            logger.error(f"MySQL连接失败: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"MySQL连接失败: {str(e)}")
        logger.error("请检查：")
        logger.error("  1. MySQL服务是否运行")
        logger.error("  2. 环境变量配置是否正确")
        logger.error("  3. 网络连接是否正常")
        logger.error("  4. 用户权限是否足够")
        return False
    
    try:
        # 创建MySQL数据库表（如果不存在）
        from models import Base
        Base.metadata.create_all(mysql_engine)
        logger.info("MySQL数据库表已创建")
        
        # 迁移用户表
        logger.info("开始迁移用户表...")
        sqlite_users = sqlite_session.execute(text("SELECT * FROM user")).fetchall()
        mysql_users = mysql_session.execute(text("SELECT id, username, email FROM user")).fetchall()
        existing_user_ids = {row[0] for row in mysql_users}
        existing_usernames = {row[1] for row in mysql_users}
        existing_emails = {row[2] for row in mysql_users}
        
        # 获取列名（只获取一次，提高效率）
        columns = [desc[1] for desc in sqlite_session.execute(text("PRAGMA table_info(user)")).fetchall()]
        username_idx = columns.index('username') if 'username' in columns else None
        email_idx = columns.index('email') if 'email' in columns else None
        
        user_count = 0
        skip_count = 0
        for row in sqlite_users:
            user_id = row[0]
            username = row[username_idx] if username_idx is not None else None
            email = row[email_idx] if email_idx is not None else None
            
            # 检查ID、用户名和邮箱是否已存在
            if user_id in existing_user_ids:
                skip_count += 1
                continue
            if username and username in existing_usernames:
                logger.warning(f"跳过用户（用户名已存在）: {username}")
                skip_count += 1
                continue
            if email and email in existing_emails:
                logger.warning(f"跳过用户（邮箱已存在）: {email}")
                skip_count += 1
                continue
            
            # 构建INSERT语句
            values = dict(zip(columns, row))
            
            # 使用字典参数绑定（兼容SQLAlchemy 2.0）
            column_names = ', '.join([f'`{col}`' for col in columns])
            placeholders = ', '.join([f':{col}' for col in columns])
            
            insert_sql = f"INSERT INTO user ({column_names}) VALUES ({placeholders})"
            try:
                mysql_session.execute(text(insert_sql), values)
                user_count += 1
                # 更新已存在的集合，避免后续重复检查
                existing_user_ids.add(user_id)
                if username:
                    existing_usernames.add(username)
                if email:
                    existing_emails.add(email)
            except Exception as e:
                error_msg = str(e)
                if 'Duplicate entry' in error_msg or '1062' in error_msg:
                    logger.warning(f"跳过用户（重复键）: {username or email}, 错误: {error_msg}")
                    skip_count += 1
                else:
                    logger.error(f"插入用户失败: {username or email}, 错误: {error_msg}")
                    raise
        
        mysql_session.commit()
        logger.info(f"用户表迁移完成，新增 {user_count} 条记录，跳过 {skip_count} 条重复记录")
        
        # 迁移任务表
        logger.info("开始迁移任务表...")
        sqlite_tasks = sqlite_session.execute(text("SELECT * FROM task")).fetchall()
        mysql_tasks = mysql_session.execute(text("SELECT id FROM task")).fetchall()
        existing_task_ids = {row[0] for row in mysql_tasks}
        
        # 获取MySQL中所有存在的用户ID，用于外键检查
        mysql_user_ids = mysql_session.execute(text("SELECT id FROM user")).fetchall()
        existing_user_ids_set = {row[0] for row in mysql_user_ids}
        
        # 获取MySQL中所有存在的任务ID，用于submission表的外键检查
        mysql_task_ids = mysql_session.execute(text("SELECT id FROM task")).fetchall()
        existing_task_ids_set = {row[0] for row in mysql_task_ids}
        
        task_count = 0
        skip_count = 0
        # MySQL TEXT类型最大长度约为65535字节（约64KB），为了安全起见，限制为60000字符
        MAX_TEXT_LENGTH = 60000
        
        # 获取列名（只获取一次，提高效率）
        task_columns = [desc[1] for desc in sqlite_session.execute(text("PRAGMA table_info(task)")).fetchall()]
        
        for row in sqlite_tasks:
            if row[0] not in existing_task_ids:
                # PRAGMA table_info 返回格式: (cid, name, type, notnull, dflt_value, pk)
                # 列名在索引1的位置
                values = dict(zip(task_columns, row))
                
                # 检查外键引用：user_id 和 html_approved_by
                user_id = values.get('user_id')
                if user_id is not None and user_id not in existing_user_ids_set:
                    logger.warning(f"跳过任务（用户不存在）: ID={row[0]}, user_id={user_id}")
                    skip_count += 1
                    continue
                
                html_approved_by = values.get('html_approved_by')
                if html_approved_by is not None and html_approved_by not in existing_user_ids_set:
                    logger.warning(f"任务ID={row[0]}的html_approved_by={html_approved_by}不存在，设置为NULL")
                    values['html_approved_by'] = None
                
                # 处理过长的文本字段（特别是rate_limit_log等日志字段）
                text_fields = ['rate_limit_log', 'analysis_report', 'html_analysis', 'custom_prompt', 'user_prompt_template', 'html_review_note']
                for field in text_fields:
                    if field in values and values[field] is not None:
                        field_value = str(values[field])
                        if len(field_value) > MAX_TEXT_LENGTH:
                            # 对于日志字段，保留最后的部分（最新的日志更重要）
                            if field == 'rate_limit_log':
                                truncated = field_value[-MAX_TEXT_LENGTH:]
                                logger.warning(f"任务ID={row[0]}的{field}字段过长（{len(field_value)}字符），已截断为最后{MAX_TEXT_LENGTH}字符")
                            else:
                                # 对于其他字段，保留前面的部分
                                truncated = field_value[:MAX_TEXT_LENGTH]
                                logger.warning(f"任务ID={row[0]}的{field}字段过长（{len(field_value)}字符），已截断为前{MAX_TEXT_LENGTH}字符")
                            values[field] = truncated
                
                # 使用字典参数绑定（兼容SQLAlchemy 2.0）
                column_names = ', '.join([f'`{col}`' for col in task_columns])
                placeholders = ', '.join([f':{col}' for col in task_columns])
                
                insert_sql = f"INSERT INTO task ({column_names}) VALUES ({placeholders})"
                try:
                    mysql_session.execute(text(insert_sql), values)
                    task_count += 1
                    existing_task_ids.add(row[0])
                except Exception as e:
                    error_msg = str(e)
                    if 'Duplicate entry' in error_msg or '1062' in error_msg:
                        logger.warning(f"跳过任务（重复键）: ID={row[0]}, 错误: {error_msg}")
                        skip_count += 1
                    elif 'Data too long' in error_msg or '1406' in error_msg:
                        logger.warning(f"跳过任务（数据过长）: ID={row[0]}, 错误: {error_msg}")
                        skip_count += 1
                    elif 'foreign key' in error_msg.lower() or '1452' in error_msg:
                        logger.warning(f"跳过任务（外键约束失败）: ID={row[0]}, 错误: {error_msg}")
                        skip_count += 1
                    else:
                        logger.error(f"插入任务失败: ID={row[0]}, 错误: {error_msg}")
                        raise
        
        mysql_session.commit()
        logger.info(f"任务表迁移完成，新增 {task_count} 条记录，跳过 {skip_count} 条重复记录")
        
        # 迁移提交表（答案表）
        logger.info("开始迁移提交表（答案表）...")
        
        # 初始化跳过记录日志
        skip_logger.info("=" * 80)
        skip_logger.info("提交表（答案表）迁移 - 跳过记录详细日志")
        skip_logger.info("=" * 80)
        skip_logger.info("格式: [跳过原因] ID=xxx, task_id=xxx, submitted_at=xxx, 详细信息")
        skip_logger.info("")
        
        # 重置跳过统计
        skip_statistics = {
            'duplicate_id': 0,
            'duplicate_business_key': 0,
            'orphan_task': 0,
            'duplicate_db': 0,
            'data_too_long': 0,
            'foreign_key_error': 0,
            'other_error': 0
        }
        
        # 获取MySQL中已存在的提交ID（用于快速检查）
        mysql_submissions = mysql_session.execute(text("SELECT id FROM submission")).fetchall()
        existing_submission_ids = {row[0] for row in mysql_submissions}
        
        # 确保获取MySQL中所有存在的任务ID，用于外键检查
        if 'existing_task_ids_set' not in locals():
            mysql_task_ids = mysql_session.execute(text("SELECT id FROM task")).fetchall()
            existing_task_ids_set = {row[0] for row in mysql_task_ids}
        
        # 验证假设：检查SQLite中是否有指向不存在任务的submission记录
        logger.info("正在检查SQLite中是否存在孤立提交记录（任务已被删除但提交记录仍存在）...")
        sqlite_task_ids = sqlite_session.execute(text("SELECT id FROM task")).fetchall()
        sqlite_task_ids_set = {row[0] for row in sqlite_task_ids}
        
        # 检查submission表中的task_id是否都存在于task表中
        orphan_submissions = sqlite_session.execute(text("""
            SELECT s.task_id, COUNT(*) as count
            FROM submission s
            LEFT JOIN task t ON s.task_id = t.id
            WHERE t.id IS NULL
            GROUP BY s.task_id
        """)).fetchall()
        
        if orphan_submissions:
            total_orphan_count = sum(row[1] for row in orphan_submissions)
            logger.warning(f"发现 {len(orphan_submissions)} 个已删除的任务，共有 {total_orphan_count} 条孤立的提交记录")
            logger.warning("这些提交记录对应的任务在SQLite中已不存在，可能是之前删除任务时未级联删除导致的")
            for row in orphan_submissions[:10]:  # 只显示前10个
                logger.warning(f"  - 任务ID {row[0]} 有 {row[1]} 条孤立提交记录")
            if len(orphan_submissions) > 10:
                logger.warning(f"  ... 还有 {len(orphan_submissions) - 10} 个已删除的任务")
        else:
            logger.info("未发现孤立提交记录，所有提交记录都有对应的任务")
        
        # 获取MySQL中已存在的提交记录的唯一标识（task_id + data + submitted_at）
        # 用于检查真正的重复数据，而不仅仅是ID重复
        logger.info("正在获取MySQL中已存在的提交记录唯一标识...")
        mysql_submission_keys = mysql_session.execute(text("""
            SELECT task_id, data, submitted_at 
            FROM submission
        """)).fetchall()
        # 创建唯一标识集合（使用元组作为键）
        # 对于大数据，使用hash来比较，避免内存占用过大
        existing_submission_keys = set()
        for row in mysql_submission_keys:
            # 将数据转换为字符串进行比较（处理可能的类型差异）
            task_id = row[0]
            data = str(row[1]) if row[1] is not None else ''
            submitted_at = row[2] if row[2] is not None else None
            
            # 对于大数据，使用hash来比较（更节省内存）
            if len(data) > 1000:
                data_hash = hashlib.md5(data.encode('utf-8')).hexdigest()
                key = (task_id, data_hash, submitted_at, len(data))  # 包含长度用于更精确的比较
            else:
                key = (task_id, data, submitted_at)
            existing_submission_keys.add(key)
        logger.info(f"MySQL中已有 {len(existing_submission_keys)} 条唯一提交记录")
        
        # 确保获取MySQL中所有存在的任务ID，用于外键检查
        if 'existing_task_ids_set' not in locals():
            mysql_task_ids = mysql_session.execute(text("SELECT id FROM task")).fetchall()
            existing_task_ids_set = {row[0] for row in mysql_task_ids}
        
        # 获取列名（只获取一次，提高效率）
        try:
            submission_columns = [desc[1] for desc in sqlite_session.execute(text("PRAGMA table_info(submission)")).fetchall()]
            logger.info(f"submission表包含 {len(submission_columns)} 个字段: {', '.join(submission_columns)}")
        except Exception as e:
            logger.error(f"无法获取submission表结构: {str(e)}")
            submission_columns = ['id', 'task_id', 'data', 'submitted_at']  # 使用默认字段
        
        submission_count = 0
        skip_count = 0
        # MySQL TEXT类型最大长度约为65535字节（约64KB），为了安全起见，限制为60000字符
        MAX_TEXT_LENGTH = 60000
        
        # 方法1：尝试获取ID范围，使用基于ID的查询（避免OFFSET导致的损坏页面问题）
        try:
            # 获取最小和最大ID
            min_id_result = sqlite_session.execute(text("SELECT MIN(id) FROM submission")).fetchone()
            max_id_result = sqlite_session.execute(text("SELECT MAX(id) FROM submission")).fetchone()
            
            if min_id_result and max_id_result and min_id_result[0] is not None:
                min_id = min_id_result[0]
                max_id = max_id_result[0]
                logger.info(f"检测到submission表ID范围: {min_id} - {max_id}")
                
                # 使用基于ID的查询方式（更稳定的方法：使用较小的批次，遇到错误时逐条读取）
                batch_size = 100  # 减小批次大小，提高稳定性
                current_id = min_id
                total_processed = 0
                consecutive_errors = 0
                max_consecutive_errors = 5  # 允许更多连续错误，因为会尝试逐条读取
                
                while current_id <= max_id:
                    try:
                        # 使用WHERE id >= current_id ORDER BY id LIMIT的方式，避免OFFSET
                        query = f"SELECT * FROM submission WHERE id >= {current_id} ORDER BY id LIMIT {batch_size}"
                        sqlite_submissions = sqlite_session.execute(text(query)).fetchall()
                        
                        if not sqlite_submissions:
                            break
                        
                        logger.info(f"读取批次: 起始ID={current_id}, 记录数={len(sqlite_submissions)}")
                        consecutive_errors = 0  # 重置错误计数
                        
                        batch_insert_count = 0
                        last_id_in_batch = None  # 记录批次中的最大ID
                        batch_start_id = current_id  # 记录批次起始ID，用于错误恢复
                        
                        for row in sqlite_submissions:
                            record_id = row[0]
                            last_id_in_batch = record_id  # 更新最大ID
                            
                            # 使用之前获取的列名
                            values = dict(zip(submission_columns, row))
                            
                            # 检查是否已存在（先检查ID，再检查业务唯一性）
                            is_duplicate = False
                            
                            # 1. 检查ID是否已存在
                            task_id = values.get('task_id')
                            data = str(values.get('data', '')) if values.get('data') is not None else ''
                            submitted_at = values.get('submitted_at')
                            
                            if record_id in existing_submission_ids:
                                is_duplicate = True
                                skip_statistics['duplicate_id'] += 1
                                skip_logger.info(f"[ID重复] ID={record_id}, task_id={task_id}, submitted_at={submitted_at}, data_length={len(data)}")
                            else:
                                # 2. 检查业务唯一性：task_id + data + submitted_at
                                # 构建唯一标识键（与上面的逻辑保持一致）
                                if len(data) > 1000:
                                    data_hash = hashlib.md5(data.encode('utf-8')).hexdigest()
                                    key = (task_id, data_hash, submitted_at, len(data))
                                else:
                                    key = (task_id, data, submitted_at)
                                
                                if key in existing_submission_keys:
                                    is_duplicate = True
                                    skip_statistics['duplicate_business_key'] += 1
                                    data_preview = data[:100] + '...' if len(data) > 100 else data
                                    skip_logger.info(f"[业务唯一键重复] ID={record_id}, task_id={task_id}, submitted_at={submitted_at}, data_preview={data_preview}")
                            
                            if is_duplicate:
                                skip_count += 1
                                # 每100条才记录一次，避免日志过多
                                if skip_count % 100 == 0:
                                    logger.info(f"已跳过 {skip_count} 条重复提交")
                                continue
                            
                            # 处理过长的文本字段
                            if 'data' in values and values['data'] is not None:
                                data_value = str(values['data'])
                                if len(data_value) > MAX_TEXT_LENGTH:
                                    truncated = data_value[:MAX_TEXT_LENGTH]
                                    logger.warning(f"提交ID={record_id}的data字段过长，已截断")
                                    values['data'] = truncated
                            
                            # 检查外键引用：task_id
                            if task_id is not None and task_id not in existing_task_ids_set:
                                skip_count += 1
                                skip_statistics['orphan_task'] += 1
                                data_preview = data[:100] + '...' if len(data) > 100 else data
                                skip_logger.info(f"[孤立记录-任务不存在] ID={record_id}, task_id={task_id}, submitted_at={submitted_at}, data_preview={data_preview}")
                                # 每100条才记录一次，避免日志过多
                                if skip_count % 100 == 0:
                                    logger.warning(f"已跳过 {skip_count} 条提交（任务不存在，可能是已删除任务的孤立记录）")
                                continue
                            
                            # 使用字典参数绑定（兼容SQLAlchemy 2.0）
                            column_names = ', '.join([f'`{col}`' for col in submission_columns])
                            placeholders = ', '.join([f':{col}' for col in submission_columns])
                            
                            insert_sql = f"INSERT INTO submission ({column_names}) VALUES ({placeholders})"
                            try:
                                mysql_session.execute(text(insert_sql), values)
                                submission_count += 1
                                batch_insert_count += 1
                                existing_submission_ids.add(record_id)
                                
                                # 更新已存在的唯一标识集合（与上面的逻辑保持一致）
                                data = str(values.get('data', '')) if values.get('data') else ''
                                if len(data) > 1000:
                                    data_hash = hashlib.md5(data.encode('utf-8')).hexdigest()
                                    key = (task_id, data_hash, values.get('submitted_at'), len(data))
                                else:
                                    key = (task_id, data, values.get('submitted_at'))
                                existing_submission_keys.add(key)
                                
                            except Exception as e:
                                error_msg = str(e)
                                task_id = values.get('task_id')
                                submitted_at = values.get('submitted_at')
                                data = str(values.get('data', '')) if values.get('data') else ''
                                data_preview = data[:100] + '...' if len(data) > 100 else data
                                
                                if 'Duplicate entry' in error_msg or '1062' in error_msg:
                                    skip_count += 1
                                    skip_statistics['duplicate_db'] += 1
                                    skip_logger.info(f"[数据库层面重复] ID={record_id}, task_id={task_id}, submitted_at={submitted_at}, error={error_msg}, data_preview={data_preview}")
                                    logger.debug(f"数据库层面发现重复: ID={record_id}, 错误: {error_msg}")
                                elif 'Data too long' in error_msg or '1406' in error_msg:
                                    skip_count += 1
                                    skip_statistics['data_too_long'] += 1
                                    skip_logger.info(f"[数据过长] ID={record_id}, task_id={task_id}, submitted_at={submitted_at}, data_length={len(data)}, error={error_msg}")
                                elif 'foreign key' in error_msg.lower() or '1452' in error_msg:
                                    skip_count += 1
                                    skip_statistics['foreign_key_error'] += 1
                                    skip_logger.info(f"[外键错误] ID={record_id}, task_id={task_id}, submitted_at={submitted_at}, error={error_msg}")
                                else:
                                    skip_count += 1
                                    skip_statistics['other_error'] += 1
                                    skip_logger.info(f"[其他错误] ID={record_id}, task_id={task_id}, submitted_at={submitted_at}, error={error_msg}, data_preview={data_preview}")
                                    logger.error(f"插入提交失败: ID={record_id}, 错误: {error_msg}")
                        
                        # 更新current_id为当前批次的最大ID+1（在循环外部更新，避免无限循环）
                        if last_id_in_batch is not None:
                            current_id = last_id_in_batch + 1
                        else:
                            # 如果没有处理任何记录，直接跳过
                            current_id += batch_size
                        
                        total_processed += len(sqlite_submissions)
                        
                        # 每处理一批就提交一次，避免事务过大
                        if batch_insert_count > 0:
                            mysql_session.commit()
                        
                        # 每10000条记录输出一次进度
                        if total_processed % 10000 == 0:
                            logger.info(f"已处理 {total_processed} 条记录，已迁移 {submission_count} 条，跳过 {skip_count} 条")
                        
                        # 如果这一批没有读取到预期的数量，说明可能已经到末尾了
                        if len(sqlite_submissions) < batch_size:
                            break
                            
                    except Exception as e:
                        error_msg = str(e)
                        if 'malformed' in error_msg.lower() or 'database disk image' in error_msg.lower():
                            logger.warning(f"数据库损坏错误（ID={current_id}）: {error_msg}")
                            logger.info(f"尝试逐条读取ID范围 {batch_start_id} - {batch_start_id + batch_size - 1} 的记录...")
                            # 尝试逐条读取该批次范围内的记录
                            submission_count, skip_count = try_single_record_read(
                                sqlite_session, mysql_session, submission_columns,
                                existing_submission_ids, existing_task_ids_set,
                                batch_start_id, max_id, MAX_TEXT_LENGTH,
                                submission_count, skip_count)
                            # 跳过整个批次，继续下一个
                            current_id = batch_start_id + batch_size
                            total_processed += batch_size  # 估算处理数量
                        else:
                            logger.error(f"处理错误（ID={current_id}）: {error_msg}")
                            consecutive_errors += 1
                            if consecutive_errors >= max_consecutive_errors:
                                logger.warning(f"连续错误过多，尝试逐条读取ID范围 {batch_start_id} - {batch_start_id + batch_size - 1}...")
                                submission_count, skip_count = try_single_record_read(
                                    sqlite_session, mysql_session, submission_columns,
                                    existing_submission_ids, existing_task_ids_set,
                                    batch_start_id, max_id, MAX_TEXT_LENGTH,
                                    submission_count, skip_count)
                                consecutive_errors = 0
                                current_id = batch_start_id + batch_size
                                total_processed += batch_size
                            else:
                                # 跳过当前ID，继续下一个
                                current_id += 1
                
                logger.info(f"迁移完成: 已处理 {total_processed} 条记录，已迁移 {submission_count} 条，跳过 {skip_count} 条")
                
            else:
                raise Exception("无法获取ID范围，将使用备用方法")
                
        except Exception as e:
            logger.warning(f"基于ID的查询方式失败: {str(e)}，尝试使用备用方法...")
            # 备用方法：使用更小的批次和OFFSET，但遇到错误时尝试逐条读取
            batch_size = 100
            offset = 0
            total_processed = 0
            
            while True:
                try:
                    query = f"SELECT * FROM submission LIMIT {batch_size} OFFSET {offset}"
                    sqlite_submissions = sqlite_session.execute(text(query)).fetchall()
                    
                    if not sqlite_submissions:
                        break
                    
                    logger.info(f"读取批次（备用方法）: 偏移量={offset}, 记录数={len(sqlite_submissions)}")
                    
                    for row in sqlite_submissions:
                        if row[0] not in existing_submission_ids:
                            values = dict(zip(submission_columns, row))
                    
                            if 'data' in values and values['data'] is not None:
                                data_value = str(values['data'])
                                if len(data_value) > MAX_TEXT_LENGTH:
                                    truncated = data_value[:MAX_TEXT_LENGTH]
                                    logger.warning(f"提交ID={row[0]}的data字段过长（{len(data_value)}字符），已截断为前{MAX_TEXT_LENGTH}字符")
                                    values['data'] = truncated
                            
                            task_id = values.get('task_id')
                            submitted_at = values.get('submitted_at')
                            data = str(values.get('data', '')) if values.get('data') is not None else ''
                            
                            if task_id is not None:
                                if 'existing_task_ids_set' in locals() and task_id not in existing_task_ids_set:
                                    skip_count += 1
                                    skip_statistics['orphan_task'] += 1
                                    data_preview = data[:100] + '...' if len(data) > 100 else data
                                    skip_logger.info(f"[孤立记录-任务不存在] ID={row[0]}, task_id={task_id}, submitted_at={submitted_at}, data_preview={data_preview}")
                                    logger.warning(f"跳过提交（任务不存在）: ID={row[0]}, task_id={task_id}")
                                    continue
                            
                            column_names = ', '.join([f'`{col}`' for col in submission_columns])
                            placeholders = ', '.join([f':{col}' for col in submission_columns])
                            
                            insert_sql = f"INSERT INTO submission ({column_names}) VALUES ({placeholders})"
                            try:
                                mysql_session.execute(text(insert_sql), values)
                                submission_count += 1
                                existing_submission_ids.add(row[0])
                            except Exception as e:
                                error_msg = str(e)
                                data_preview = data[:100] + '...' if len(data) > 100 else data
                                
                                if 'Duplicate entry' in error_msg or '1062' in error_msg:
                                    skip_count += 1
                                    skip_statistics['duplicate_db'] += 1
                                    skip_logger.info(f"[数据库层面重复] ID={row[0]}, task_id={task_id}, submitted_at={submitted_at}, error={error_msg}, data_preview={data_preview}")
                                    logger.warning(f"跳过提交（重复键）: ID={row[0]}, 错误: {error_msg}")
                                elif 'Data too long' in error_msg or '1406' in error_msg:
                                    skip_count += 1
                                    skip_statistics['data_too_long'] += 1
                                    skip_logger.info(f"[数据过长] ID={row[0]}, task_id={task_id}, submitted_at={submitted_at}, data_length={len(data)}, error={error_msg}")
                                    logger.warning(f"跳过提交（数据过长）: ID={row[0]}, 错误: {error_msg}")
                                elif 'foreign key' in error_msg.lower() or '1452' in error_msg:
                                    skip_count += 1
                                    skip_statistics['foreign_key_error'] += 1
                                    skip_logger.info(f"[外键错误] ID={row[0]}, task_id={task_id}, submitted_at={submitted_at}, error={error_msg}")
                                    logger.warning(f"跳过提交（外键约束失败）: ID={row[0]}, 错误: {error_msg}")
                                else:
                                    skip_count += 1
                                    skip_statistics['other_error'] += 1
                                    skip_logger.info(f"[其他错误] ID={row[0]}, task_id={task_id}, submitted_at={submitted_at}, error={error_msg}, data_preview={data_preview}")
                                    logger.error(f"插入提交失败: ID={row[0]}, 错误: {error_msg}")
                                    raise
                    
                    total_processed += len(sqlite_submissions)
                    offset += batch_size
                    
                    if submission_count > 0 and submission_count % 1000 == 0:
                        mysql_session.commit()
                        logger.info(f"已处理 {total_processed} 条记录，已迁移 {submission_count} 条，跳过 {skip_count} 条")
                    
                except Exception as e:
                    error_msg = str(e)
                    if 'malformed' in error_msg.lower() or 'database disk image' in error_msg.lower():
                        logger.error(f"读取submission表时遇到数据库错误（偏移量={offset}）: {error_msg}")
                        # 尝试逐条读取这个范围内的记录
                        logger.info(f"尝试逐条读取偏移量={offset}附近的记录...")
                        submission_count, skip_count = try_single_record_read_by_offset(
                            sqlite_session, mysql_session, submission_columns,
                            existing_submission_ids, existing_task_ids_set,
                            offset, batch_size, MAX_TEXT_LENGTH,
                            submission_count, skip_count)
                        offset += batch_size
                        continue
                    else:
                        logger.error(f"处理submission表时出错（偏移量={offset}）: {error_msg}")
                        offset += batch_size
                        continue
        
        mysql_session.commit()
        logger.info(f"提交表（答案表）迁移完成，新增 {submission_count} 条记录，跳过 {skip_count} 条重复记录")
        
        # 输出跳过记录的统计摘要
        skip_logger.info("")
        skip_logger.info("=" * 80)
        skip_logger.info("跳过记录统计摘要")
        skip_logger.info("=" * 80)
        skip_logger.info(f"ID重复: {skip_statistics['duplicate_id']} 条")
        skip_logger.info(f"业务唯一键重复: {skip_statistics['duplicate_business_key']} 条")
        skip_logger.info(f"孤立记录（任务不存在）: {skip_statistics['orphan_task']} 条")
        skip_logger.info(f"数据库层面重复: {skip_statistics['duplicate_db']} 条")
        skip_logger.info(f"数据过长: {skip_statistics['data_too_long']} 条")
        skip_logger.info(f"外键错误: {skip_statistics['foreign_key_error']} 条")
        skip_logger.info(f"其他错误: {skip_statistics['other_error']} 条")
        total_skipped = sum(skip_statistics.values())
        skip_logger.info(f"总计跳过: {total_skipped} 条")
        skip_logger.info("=" * 80)
        skip_logger.info(f"详细日志已保存到: {skip_log_file}")
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("跳过记录统计摘要：")
        logger.info(f"  ID重复: {skip_statistics['duplicate_id']} 条")
        logger.info(f"  业务唯一键重复: {skip_statistics['duplicate_business_key']} 条")
        logger.info(f"  孤立记录（任务不存在）: {skip_statistics['orphan_task']} 条")
        logger.info(f"  数据库层面重复: {skip_statistics['duplicate_db']} 条")
        logger.info(f"  数据过长: {skip_statistics['data_too_long']} 条")
        logger.info(f"  外键错误: {skip_statistics['foreign_key_error']} 条")
        logger.info(f"  其他错误: {skip_statistics['other_error']} 条")
        logger.info(f"  总计跳过: {total_skipped} 条")
        logger.info(f"详细日志已保存到: {skip_log_file}")
        logger.info("=" * 60)
        
        # 迁移其他表
        for table_name in ['ai_config', 'certification_request']:
            try:
                logger.info(f"开始迁移 {table_name} 表...")
                sqlite_rows = sqlite_session.execute(text(f"SELECT * FROM {table_name}")).fetchall()
                mysql_rows = mysql_session.execute(text(f"SELECT id FROM {table_name}")).fetchall()
                existing_ids = {row[0] for row in mysql_rows}
                
                count = 0
                skip_count = 0
                for row in sqlite_rows:
                    if row[0] not in existing_ids:
                        # PRAGMA table_info 返回格式: (cid, name, type, notnull, dflt_value, pk)
                        # 列名在索引1的位置
                        columns = [desc[1] for desc in sqlite_session.execute(text(f"PRAGMA table_info({table_name})")).fetchall()]
                        values = dict(zip(columns, row))
                        
                        # 使用字典参数绑定（兼容SQLAlchemy 2.0）
                        column_names = ', '.join([f'`{col}`' for col in columns])
                        placeholders = ', '.join([f':{col}' for col in columns])
                        
                        insert_sql = f"INSERT INTO {table_name} ({column_names}) VALUES ({placeholders})"
                        try:
                            mysql_session.execute(text(insert_sql), values)
                            count += 1
                            existing_ids.add(row[0])
                        except Exception as e:
                            error_msg = str(e)
                            if 'Duplicate entry' in error_msg or '1062' in error_msg:
                                logger.warning(f"跳过{table_name}记录（重复键）: ID={row[0]}, 错误: {error_msg}")
                                skip_count += 1
                            else:
                                logger.warning(f"插入{table_name}记录失败: ID={row[0]}, 错误: {error_msg}")
                                skip_count += 1
                
                mysql_session.commit()
                logger.info(f"{table_name} 表迁移完成，新增 {count} 条记录，跳过 {skip_count} 条重复记录")
            except Exception as e:
                logger.warning(f"迁移 {table_name} 表时出错: {str(e)}")
        
        logger.info("数据迁移完成！")
        return True
        
    except Exception as e:
        logger.error(f"迁移失败: {str(e)}", exc_info=True)
        mysql_session.rollback()
        return False
    finally:
        sqlite_session.close()
        mysql_session.close()

if __name__ == '__main__':
    success = migrate_data()
    sys.exit(0 if success else 1)
