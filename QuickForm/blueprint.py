"""
QuickForm Blueprint
将QuickForm改造为Blueprint，可以整合到主应用中
"""
import os
import json
import math
import random
import re
import threading
import html
import base64
import uuid
from urllib.parse import unquote_plus
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, make_response, send_file, send_from_directory, current_app
from sqlalchemy import create_engine, or_, text
from sqlalchemy.orm import sessionmaker
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from datetime import datetime
import pandas as pd
import io
import matplotlib
matplotlib.use('Agg')  # 使用非交互式后端
import matplotlib.pyplot as plt
from dotenv import load_dotenv
import logging
from functools import wraps
from collections import deque
from typing import Deque

# 导入分离的模块
from models import Base, User, Task, Submission, AIConfig, migrate_database, CertificationRequest
from file_service import save_uploaded_file, read_file_content, ALLOWED_EXTENSIONS, allowed_file, CERTIFICATION_ALLOWED_EXTENSIONS
from ai_service import call_ai_model, generate_analysis_prompt, analyze_html_file
from report_service import (
    save_analysis_report, generate_report_image, perform_analysis_with_custom_prompt,
    analysis_progress, analysis_results, completed_reports, progress_lock, timeout
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()

# 获取QuickForm目录路径
QUICKFORM_DIR = os.path.dirname(os.path.abspath(__file__))

# 创建上传文件目录（相对于QuickForm目录）
UPLOAD_FOLDER = os.path.join(QUICKFORM_DIR, 'uploads')
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

CERTIFICATION_FOLDER = os.path.join(UPLOAD_FOLDER, 'certifications')
if not os.path.exists(CERTIFICATION_FOLDER):
    os.makedirs(CERTIFICATION_FOLDER)

# 允许的文件扩展名（仅HTML格式）
ALLOWED_EXTENSIONS = {'html', 'htm'}

def parse_urlencoded(raw_data):
    """手动解析URL编码的表单数据，避免Flask自动解析导致的问题"""
    result = {}
    if not raw_data:
        return result
    
    try:
        # 将bytes转为字符串
        if isinstance(raw_data, bytes):
            data_str = raw_data.decode('utf-8', errors='ignore')
        else:
            data_str = raw_data
        
        # 按&分割字段
        for pair in data_str.split('&'):
            if '=' in pair:
                key, value = pair.split('=', 1)
                key = unquote_plus(key)
                value = unquote_plus(value)
                result[key] = value
    except Exception as e:
        logger.error(f"解析URL编码数据失败: {str(e)}")
    
    return result

# 数据库配置（相对于QuickForm目录）
# 默认从环境变量读取，但可以通过init_quickform的参数强制指定
_database_type = None  # 将在init_quickform中设置

def _init_database(database_type=None):
    """初始化数据库连接"""
    global DATABASE_URL, engine, SessionLocal
    
    # 如果指定了数据库类型，使用指定的类型
    if database_type:
        if database_type.lower() == 'mysql':
            # 强制使用MySQL
            MYSQL_HOST = os.getenv('MYSQL_HOST', '')
            MYSQL_PORT = os.getenv('MYSQL_PORT', '3306')
            MYSQL_USER = os.getenv('MYSQL_USER', '')
            MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')
            MYSQL_DATABASE = os.getenv('MYSQL_DATABASE', 'quickform')
            
            if MYSQL_HOST and MYSQL_USER and MYSQL_PASSWORD:
                DATABASE_URL = f'mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4'
                logger.info(f"强制使用MySQL数据库: {MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}")
            else:
                logger.error("指定使用MySQL但环境变量未配置，回退到SQLite")
                DATABASE_URL = f'sqlite:///{os.path.join(QUICKFORM_DIR, "quickform.db")}'
                logger.info("使用SQLite数据库（MySQL配置缺失）")
        else:
            # 强制使用SQLite
            DATABASE_URL = f'sqlite:///{os.path.join(QUICKFORM_DIR, "quickform.db")}'
            logger.info("强制使用SQLite数据库")
    else:
        # 自动选择：优先使用环境变量中的MySQL配置，如果没有则使用SQLite
        MYSQL_HOST = os.getenv('MYSQL_HOST', '')
        MYSQL_PORT = os.getenv('MYSQL_PORT', '3306')
        MYSQL_USER = os.getenv('MYSQL_USER', '')
        MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')
        MYSQL_DATABASE = os.getenv('MYSQL_DATABASE', 'quickform')
        
        if MYSQL_HOST and MYSQL_USER and MYSQL_PASSWORD:
            # 使用MySQL
            DATABASE_URL = f'mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4'
            logger.info(f"使用MySQL数据库: {MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}")
        else:
            # 使用SQLite（向后兼容）
            DATABASE_URL = f'sqlite:///{os.path.join(QUICKFORM_DIR, "quickform.db")}'
            logger.info("使用SQLite数据库（向后兼容模式）")
    
    # 初始化SQLAlchemy引擎
    mysql_connection_failed = False
    if DATABASE_URL.startswith('mysql'):
        # MySQL连接配置
        try:
            engine = create_engine(
                DATABASE_URL,
                pool_pre_ping=True,  # 自动重连
                pool_recycle=3600,   # 连接回收时间
                echo=False
            )
            # 测试连接是否可用
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("MySQL连接测试成功")
        except Exception as e:
            logger.error(f"MySQL连接失败: {str(e)}，自动回退到SQLite")
            mysql_connection_failed = True
            # 回退到SQLite
            DATABASE_URL = f'sqlite:///{os.path.join(QUICKFORM_DIR, "quickform.db")}'
    
    # 如果MySQL连接失败或使用SQLite，初始化SQLite引擎
    if mysql_connection_failed or DATABASE_URL.startswith('sqlite'):
        # SQLite连接配置，启用外键约束
        def _fk_pragma_on_connect(dbapi_con, connection_record):
            """在SQLite连接时启用外键约束"""
            dbapi_con.execute('PRAGMA foreign_keys=ON')
        
        engine = create_engine(
            DATABASE_URL, 
            connect_args={'check_same_thread': False},
            poolclass=None  # SQLite不需要连接池
        )
        # 注册事件监听器，确保每次连接都启用外键约束
        from sqlalchemy import event
        event.listen(engine, 'connect', _fk_pragma_on_connect)
        if mysql_connection_failed:
            logger.info("已回退到SQLite数据库")
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 初始化数据库（默认行为，向后兼容）
_init_database()

MODEL_LABELS = {
    'chat_server': '硅基流动',
    'deepseek': 'DeepSeek',
    'doubao': '豆包',
    'qwen': '阿里云百炼'
}

# 注意：engine和SessionLocal现在在_init_database()函数中初始化

# 全局变量（将在init函数中设置）
bcrypt = None
login_manager = None

# 创建Blueprint
quickform_bp = Blueprint(
    'quickform',
    __name__,
    template_folder='templates',
    static_folder='../static'  # 指向主应用的static目录
)

# 创建数据库表
Base.metadata.create_all(engine)

# 权限检查装饰器
def admin_required(f):
    """管理员权限检查装饰器"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin():
            flash('您没有权限访问此页面', 'danger')
            return redirect(url_for('quickform.dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# 路由函数
@quickform_bp.route('/')
def index():
    """QuickForm首页"""
    if current_user.is_authenticated:
        return redirect(url_for('quickform.dashboard'))
    
    # 获取加精项目（已通过审核且有文件的任务）
    db = SessionLocal()
    try:
        featured_tasks = db.query(Task).filter(
            Task.is_featured == True,
            Task.html_approved == 1,
            Task.file_path.isnot(None),
            Task.file_path != ''
        ).order_by(Task.created_at.desc()).limit(10).all()
        
        # 随机选择3个加精项目
        if len(featured_tasks) >= 3:
            featured_tasks = random.sample(featured_tasks, 3)
        elif len(featured_tasks) > 0:
            # 如果不足3个，重复使用已有的
            while len(featured_tasks) < 3:
                featured_tasks.append(random.choice(featured_tasks))
        
        # 为每个任务生成文件URL
        featured_data = []
        for task in featured_tasks:
            if task.file_path:
                filename = task.file_path.replace('\\', '/').split('/')[-1]
                file_url = url_for('quickform.uploaded_file', filename=filename, _external=True)
                featured_data.append({
                    'task': task,
                    'file_url': file_url,
                    'filename': filename
                })
        
        # 确保有3个数据（如果不足，用None填充）
        while len(featured_data) < 3:
            featured_data.append(None)
            
    except Exception as e:
        logger.error(f"获取加精项目失败: {str(e)}")
        featured_data = [None, None, None]
    finally:
        db.close()
    
    return render_template('home.html', featured_data=featured_data)

@quickform_bp.route('/register', methods=['GET', 'POST'])
def register():
    """注册"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        school = request.form.get('school', '').strip()
        phone = request.form.get('phone', '').strip()
        
        if not username or not email or not password or not school or not phone:
            flash('请填写所有必填字段', 'danger')
            return redirect(url_for('quickform.register'))
        
        import re
        if not re.match(r'^1[3-9]\d{9}$', phone):
            flash('请输入正确的11位手机号码', 'danger')
            return redirect(url_for('quickform.register'))
        
        db = SessionLocal()
        try:
            existing_user = db.query(User).filter(
                (User.username == username) | (User.email == email)
            ).first()
            
            if existing_user:
                flash('用户名或邮箱已存在', 'danger')
                return redirect(url_for('quickform.register'))
            
            hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
            user = User(username=username, email=email, password=hashed_password, 
                       school=school, phone=phone)
            
            ai_config = AIConfig(user=user, selected_model='chat_server')
            
            db.add(user)
            db.commit()
            
            flash('注册成功，请登录', 'success')
            return redirect(url_for('quickform.login'))
        finally:
            db.close()
    
    return render_template('register.html')

@quickform_bp.route('/login', methods=['GET', 'POST'])
def login():
    """登录"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = request.form.get('remember') == 'on'
        
        db = SessionLocal()
        try:
            # 尝试多种方式查找用户：用户名、邮箱、手机号、昵称
            user = db.query(User).filter(
                (User.username == username) | 
                (User.email == username) | 
                (User.phone == username)
            ).first()
            
            if user and bcrypt.check_password_hash(user.password, password):
                # 登录成功，清除失败次数
                from flask import session
                session.pop('login_fail_count', None)
                login_user(user, remember=remember)
                next_page = request.args.get('next')
                return redirect(next_page) if next_page else redirect(url_for('quickform.dashboard'))
            else:
                # 登录失败，检查失败次数
                from flask import session
                fail_count = session.get('login_fail_count', 0) + 1
                session['login_fail_count'] = fail_count
                
                # 如果连续失败3次或以上，给出提示
                if fail_count >= 3:
                    flash('账号密码无特殊限制，您的账号可能为手机号或邮箱或昵称或姓名', 'info')
                else:
                    flash('用户名或密码错误', 'danger')
        finally:
            db.close()
    
    return render_template('login.html')

@quickform_bp.route('/logout')
def logout():
    """登出"""
    logout_user()
    return redirect(url_for('quickform.login'))

@quickform_bp.route('/dashboard')
@login_required
def dashboard():
    """仪表盘"""
    db = SessionLocal()
    try:
        tasks = db.query(Task).filter_by(user_id=current_user.id).order_by(Task.created_at.desc()).all()
        user_record = db.get(User, current_user.id)
        task_count = len(tasks)
        task_limit = None
        is_certified = False
        if user_record:
            task_limit = user_record.task_limit
            is_certified = bool(user_record.is_certified)
        else:
            task_limit = getattr(current_user, 'task_limit', None)
            is_certified = bool(getattr(current_user, 'is_certified', False))
        return render_template(
            'dashboard.html',
            tasks=tasks,
            task_count=task_count,
            task_limit=task_limit,
            is_certified=is_certified
        )
    finally:
        db.close()

@quickform_bp.route('/create_task', methods=['GET', 'POST'])
@login_required
def create_task():
    """创建任务"""
    db = SessionLocal()
    try:
        if not current_user.is_admin():
            if not current_user.can_create_task(SessionLocal, Task):
                task_limit = current_user.task_limit if current_user.task_limit != -1 else "无限制"
                task_count = db.query(Task).filter_by(user_id=current_user.id).count()
                flash(f'您已达到任务数量上限（{task_limit}个，当前{task_count}个）。如需创建更多任务，请联系管理员：wzlinmiaoyan@163.com', 'warning')
                return redirect(url_for('quickform.dashboard'))
        
        if request.method == 'POST':
            title = request.form.get('title')
            description = request.form.get('description')
            
            task = Task(title=title, description=description, user_id=current_user.id)
            
            # 优先检查Base64上传（用于公网环境）
            file_content_base64 = request.form.get('file_content_base64')
            file_name_base64 = request.form.get('file_name')
            
            if file_content_base64 and file_name_base64:
                # Base64上传方式
                try:
                    # 解码Base64
                    file_content = base64.b64decode(file_content_base64).decode('utf-8')
                    
                    # 验证文件扩展名
                    if not allowed_file(file_name_base64, ALLOWED_EXTENSIONS):
                        flash('文件上传失败或格式不支持，请重试。允许的格式：HTML/HTM，最大16MB。', 'danger')
                        return redirect(url_for('quickform.create_task'))
                    
                    # 保存文件
                    unique_filename = str(uuid.uuid4()) + '_' + file_name_base64
                    filepath = os.path.join(UPLOAD_FOLDER, unique_filename)
                    
                    if not os.path.exists(UPLOAD_FOLDER):
                        os.makedirs(UPLOAD_FOLDER)
                    
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(file_content)
                    
                    task.file_name = file_name_base64
                    task.file_path = filepath
                    
                    # 如果是HTML文件，设置审核状态
                    if filepath.lower().endswith(('.html', '.htm')):
                        if current_user.is_admin() or getattr(current_user, 'is_certified', False):
                            task.html_approved = 1
                            task.html_approved_by = current_user.id
                            task.html_approved_at = datetime.now()
                            task.html_review_note = None
                        else:
                            task.html_approved = 0
                            task.html_approved_by = None
                            task.html_approved_at = None
                            task.html_review_note = None
                except Exception as e:
                    logger.error(f"Base64文件上传失败: {str(e)}", exc_info=True)
                    flash('文件上传失败，请重试。', 'danger')
                    return redirect(url_for('quickform.create_task'))
            else:
                # 传统文件上传方式（向后兼容）
                file = request.files.get('file')
                if file and file.filename.strip():
                    unique_filename, filepath = save_uploaded_file(file, UPLOAD_FOLDER)
                    if not unique_filename:
                        flash('文件上传失败或格式不支持，请重试。允许的格式：HTML/HTM，最大16MB。', 'danger')
                        return redirect(url_for('quickform.create_task'))
                    
                    task.file_name = file.filename
                    task.file_path = filepath
                    
                    # 如果是HTML文件，设置审核状态
                    if filepath.lower().endswith(('.html', '.htm')):
                        if current_user.is_admin() or getattr(current_user, 'is_certified', False):
                            task.html_approved = 1
                            task.html_approved_by = current_user.id
                            task.html_approved_at = datetime.now()
                            task.html_review_note = None
                        else:
                            task.html_approved = 0
                            task.html_approved_by = None
                            task.html_approved_at = None
                            task.html_review_note = None
            
            db.add(task)
            db.commit()
            
            # 如果是HTML文件，在任务保存后自动在后台分析
            if task.file_path and task.file_path.lower().endswith(('.html', '.htm')):
                try:
                    analyze_html_file(task.id, current_user.id, task.file_path, SessionLocal, Task, AIConfig, read_file_content, call_ai_model)
                except Exception as e:
                    logger.error(f"启动HTML文件分析失败: {str(e)}", exc_info=True)
            
            flash('数据任务创建成功', 'success')
            return redirect(url_for('quickform.task_detail', task_id=task.id))
        
        # GET 渲染创建页面
        user_record = db.get(User, current_user.id)
        task_count = db.query(Task).filter_by(user_id=current_user.id).count()
        task_limit = None
        is_certified = False
        if user_record:
            task_limit = user_record.task_limit
            is_certified = bool(user_record.is_certified)
        else:
            task_limit = getattr(current_user, 'task_limit', None)
            is_certified = bool(getattr(current_user, 'is_certified', False))

        return render_template('create_task.html', task_limit=task_limit, is_certified=is_certified, task_count=task_count)
    finally:
        db.close()

@quickform_bp.route('/task/<int:task_id>')
@login_required
def task_detail(task_id):
    """任务详情"""
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if not task:
            flash('任务不存在', 'danger')
            return redirect(url_for('quickform.dashboard'))
        # 管理员可以查看所有任务，普通用户只能查看自己的任务
        if task.user_id != current_user.id and not current_user.is_admin():
            flash('无权访问此任务', 'danger')
            return redirect(url_for('quickform.dashboard'))
        
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        if page < 1:
            page = 1
        if per_page < 1:
            per_page = 20
        elif per_page > 200:
            per_page = 200

        submission_query = (
            db.query(Submission)
            .filter_by(task_id=task.id)
            .order_by(Submission.submitted_at.desc())
        )
        total_submissions = submission_query.count()
        total_pages = max(math.ceil(total_submissions / per_page), 1) if total_submissions else 1
        if page > total_pages:
            page = total_pages

        submissions = (
            submission_query
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        saved_filename = None
        try:
            if task.file_path:
                saved_filename = os.path.basename(task.file_path)
        except Exception:
            saved_filename = None

        pagination = {
            'page': page,
            'per_page': per_page,
            'pages': total_pages
        }

        return render_template(
            'task_detail.html',
            task=task,
            submissions=submissions,
            total_submissions=total_submissions,
            pagination=pagination,
            saved_filename=saved_filename
        )
    finally:
        db.close()

@quickform_bp.route('/edit_task/<int:task_id>', methods=['GET', 'POST'])
@login_required
def edit_task(task_id):
    """编辑任务"""
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if not task:
            flash('任务不存在', 'danger')
            return redirect(url_for('quickform.dashboard'))
        if task.user_id != current_user.id:
            flash('无权编辑此任务', 'danger')
            return redirect(url_for('quickform.dashboard'))
        
        if request.method == 'POST':
            title = request.form.get('title')
            description = request.form.get('description')
            remove_file = request.form.get('remove_file')
            
            task.title = title
            task.description = description
            
            # 优先检查Base64上传（用于公网环境）
            file_content_base64 = request.form.get('file_content_base64')
            file_name_base64 = request.form.get('file_name')
            
            if file_content_base64 and file_name_base64:
                # Base64上传方式
                try:
                    # 解码Base64
                    file_content = base64.b64decode(file_content_base64).decode('utf-8')
                    
                    # 验证文件扩展名
                    if not allowed_file(file_name_base64, ALLOWED_EXTENSIONS):
                        flash('文件上传失败或格式不支持，请重试。允许的格式：HTML/HTM，最大16MB。', 'danger')
                        return redirect(url_for('quickform.edit_task', task_id=task.id))
                    
                    # 删除旧文件
                    if task.file_path and os.path.exists(task.file_path):
                        os.remove(task.file_path)
                    
                    # 保存文件
                    unique_filename = str(uuid.uuid4()) + '_' + file_name_base64
                    filepath = os.path.join(UPLOAD_FOLDER, unique_filename)
                    
                    if not os.path.exists(UPLOAD_FOLDER):
                        os.makedirs(UPLOAD_FOLDER)
                    
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(file_content)
                    
                    task.file_name = file_name_base64
                    task.file_path = filepath
                    
                    # 如果是HTML文件，设置审核状态
                    if filepath.lower().endswith(('.html', '.htm')):
                        if current_user.is_admin() or getattr(current_user, 'is_certified', False):
                            task.html_approved = 1
                            task.html_approved_by = current_user.id
                            task.html_approved_at = datetime.now()
                            task.html_review_note = None
                        else:
                            task.html_approved = 0
                            task.html_approved_by = None
                            task.html_approved_at = None
                            task.html_review_note = None
                        task.html_analysis = None  # 清空旧的分析结果
                        
                        # 后台分析（不影响上传成功）
                        try:
                            analyze_html_file(task.id, current_user.id, filepath, SessionLocal, Task, AIConfig, read_file_content, call_ai_model)
                        except Exception as e:
                            logger.error(f"启动HTML文件分析失败(编辑): {str(e)}", exc_info=True)
                except Exception as e:
                    logger.error(f"Base64文件上传失败: {str(e)}", exc_info=True)
                    flash('文件上传失败，请重试。', 'danger')
                    return redirect(url_for('quickform.edit_task', task_id=task.id))
            else:
                # 传统文件上传方式（向后兼容）
                file = request.files.get('file')
                if file and file.filename.strip():
                    unique_filename, filepath = save_uploaded_file(file, UPLOAD_FOLDER)
                    if not unique_filename:
                        flash('文件上传失败或格式不支持，请重试。允许的格式：HTML/HTM，最大16MB。', 'danger')
                        return redirect(url_for('quickform.edit_task', task_id=task.id))
                    
                    # 删除旧文件
                    if task.file_path and os.path.exists(task.file_path):
                        os.remove(task.file_path)
                    
                    task.file_name = file.filename
                    task.file_path = filepath
                    
                    # 如果是HTML文件，设置审核状态
                    if filepath.lower().endswith(('.html', '.htm')):
                        if current_user.is_admin() or getattr(current_user, 'is_certified', False):
                            task.html_approved = 1
                            task.html_approved_by = current_user.id
                            task.html_approved_at = datetime.now()
                            task.html_review_note = None
                        else:
                            task.html_approved = 0
                            task.html_approved_by = None
                            task.html_approved_at = None
                            task.html_review_note = None
                        task.html_analysis = None  # 清空旧的分析结果
                        
                        # 后台分析（不影响上传成功）
                        try:
                            analyze_html_file(task.id, current_user.id, filepath, SessionLocal, Task, AIConfig, read_file_content, call_ai_model)
                        except Exception as e:
                            logger.error(f"启动HTML文件分析失败(编辑): {str(e)}", exc_info=True)
            if remove_file:
                if task.file_path and os.path.exists(task.file_path):
                    os.remove(task.file_path)
                task.file_name = None
                task.file_path = None
                task.html_review_note = None
            
            db.commit()
            
            flash('任务更新成功', 'success')
            return redirect(url_for('quickform.task_detail', task_id=task.id))
        
        saved_filename = None
        try:
            if task.file_path:
                saved_filename = os.path.basename(task.file_path)
        except Exception:
            saved_filename = None
        return render_template('edit_task.html', task=task, saved_filename=saved_filename)
    finally:
        db.close()

@quickform_bp.route('/delete_task/<int:task_id>', methods=['POST'])
@login_required
def delete_task(task_id):
    """删除任务，同时删除所有相关的提交数据"""
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if not task:
            flash('任务不存在', 'danger')
            return redirect(url_for('quickform.dashboard'))
        if task.user_id != current_user.id:
            flash('无权删除此任务', 'danger')
            return redirect(url_for('quickform.dashboard'))
        
        # 显式删除所有相关的提交数据
        submissions = db.query(Submission).filter_by(task_id=task.id).all()
        submission_count = len(submissions)
        
        for submission in submissions:
            db.delete(submission)
        
        # 删除任务文件（如果存在）
        if task.file_path and os.path.exists(task.file_path):
            try:
                os.remove(task.file_path)
                logger.info(f"已删除任务文件: {task.file_path}")
            except Exception as e:
                logger.warning(f"删除任务文件失败: {task.file_path}, 错误: {str(e)}")
        
        # 删除任务
        db.delete(task)
        db.commit()
        
        if submission_count > 0:
            flash(f'任务已删除，同时删除了 {submission_count} 条提交数据', 'success')
            logger.info(f"用户 {current_user.id} 删除了任务 {task_id}，同时删除了 {submission_count} 条提交数据")
        else:
            flash('任务已删除', 'success')
            logger.info(f"用户 {current_user.id} 删除了任务 {task_id}")
        
        return redirect(url_for('quickform.dashboard'))
    except Exception as e:
        db.rollback()
        logger.error(f"删除任务失败: {str(e)}", exc_info=True)
        flash(f'删除任务失败: {str(e)}', 'danger')
        return redirect(url_for('quickform.dashboard'))
    finally:
        db.close()

@quickform_bp.route('/ai_test')
@login_required
def ai_test_page():
    """AI模型测试页面"""
    return render_template('ai_test.html')

SUBMIT_RATE_LIMIT_WINDOW = 10  # seconds
SUBMIT_RATE_LIMIT_THRESHOLD = 50
SUBMIT_BLACKLIST_DURATION = 300  # seconds

rate_limit_cache = {}


@quickform_bp.route('/api/submit/<string:task_id>', methods=['GET', 'POST', 'OPTIONS'])
def submit_form(task_id):
    """表单提交API - 支持GET查询和POST提交"""
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        response.headers['Content-Type'] = 'text/plain; charset=utf-8'
        return response
        
    db = SessionLocal()
    try:
        task = db.query(Task).filter_by(task_id=task_id).first()
        if not task:
            response = jsonify({'error': '任务不存在', 'task_id': task_id, 'message': f'未找到ID为 {task_id} 的任务'})
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
            logger.warning(f"请求失败: 任务不存在 - task_id: {task_id}")
            return response, 404
        
        # GET方法：返回任务数据统计（只返回最新的3条）
        if request.method == 'GET':
            # 只获取最新的3条数据
            submissions = db.query(Submission).filter_by(task_id=task.id).order_by(Submission.submitted_at.desc()).limit(3).all()
            total_count = db.query(Submission).filter_by(task_id=task.id).count()
            data_list = []
            for sub in submissions:
                try:
                    # 尝试解析JSON数据
                    data = json.loads(sub.data)
                    # 如果解析后是字符串，可能是双重编码，再解析一次
                    if isinstance(data, str):
                        try:
                            data = json.loads(data)
                        except:
                            pass
                    data['submitted_at'] = sub.submitted_at.strftime('%Y-%m-%d %H:%M:%S')
                    data_list.append(data)
                except (json.JSONDecodeError, TypeError):
                    # 如果解析失败，返回原始数据作为raw_data
                    data_list.append({
                        'submitted_at': sub.submitted_at.strftime('%Y-%m-%d %H:%M:%S'),
                        'raw_data': sub.data
                    })
            
            response = jsonify({
                'task_id': task.task_id,
                'task_title': task.title,
                'total_submissions': total_count,
                'submissions': data_list
            })
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
            return response, 200
        
        # POST方法：提交数据
        client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        now_ts = datetime.utcnow().timestamp()

        ip_info = rate_limit_cache.setdefault(client_ip, {
            'events': deque(),
            'blacklist_until': 0,
            'blocked_tasks': {}
        })

        # 检查黑名单
        if ip_info['blacklist_until'] and now_ts < ip_info['blacklist_until']:
            logger.warning(f"IP {client_ip} 正在黑名单中，拒绝 task_id={task_id} 的提交")
            return _rate_limit_response(task_id, client_ip, now_ts, db)
        
        # 获取提交的数据
        try:
            if request.is_json:
                form_data = request.get_json()
            else:
                form_data = request.form.to_dict()
        except Exception as e:
            logger.error(f"解析请求数据失败: {str(e)}")
            response = jsonify({'error': '数据格式错误', 'message': str(e)})
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
            return response, 400
        
        # 速率限制处理
        events: Deque = ip_info['events']
        while events and now_ts - events[0] > SUBMIT_RATE_LIMIT_WINDOW:
            events.popleft()
        events.append(now_ts)

        if len(events) > SUBMIT_RATE_LIMIT_THRESHOLD:
            ip_info['blacklist_until'] = now_ts + SUBMIT_BLACKLIST_DURATION
            ip_info['blocked_tasks'][task.id] = now_ts
            logger.warning(
                f"IP {client_ip} 在 {SUBMIT_RATE_LIMIT_WINDOW}s 内提交 {len(events)} 次，已加入黑名单 {SUBMIT_BLACKLIST_DURATION}s"
            )
            return _rate_limit_response(task_id, client_ip, now_ts, db)
        
        # 将数据转换为JSON字符串存储
        try:
            submission = Submission(task_id=task.id, data=json.dumps(form_data, ensure_ascii=False))
            db.add(submission)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"保存提交数据失败: {str(e)}")
            response = jsonify({'error': '保存失败', 'message': str(e)})
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
            return response, 500
        
        response = jsonify({'message': '提交成功', 'status': 'success'})
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response, 200
    except Exception as e:
        logger.error(f"API异常: {str(e)}", exc_info=True)
        response = jsonify({'error': '服务器错误', 'message': str(e)})
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response, 500
    finally:
        db.close()


def _rate_limit_response(task_id, client_ip, ts, db):
    if db:
        task = db.query(Task).filter_by(task_id=task_id).first()
        if task:
            notice = f"IP {client_ip} 在 {SUBMIT_RATE_LIMIT_WINDOW}s 内多次提交，已暂时封禁 {SUBMIT_BLACKLIST_DURATION // 60} 分钟"
            log_entry = f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] {notice}"
            existing = task.rate_limit_log or ''
            if existing:
                task.rate_limit_log = existing + '\n' + log_entry
            else:
                task.rate_limit_log = log_entry
            try:
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(f"记录限流日志失败: {str(e)}")
 
    response = jsonify({'error': 'rate_limit', 'message': '提交过于频繁，请稍后再试'})
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response, 429

@quickform_bp.route('/api/submit/<string:task_id>/all', methods=['GET', 'OPTIONS'])
def submit_form_all(task_id):
    """获取任务的全部提交数据"""
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        response.headers['Content-Type'] = 'text/plain; charset=utf-8'
        return response
    
    db = SessionLocal()
    try:
        task = db.query(Task).filter_by(task_id=task_id).first()
        if not task:
            response = jsonify({'error': '任务不存在', 'task_id': task_id, 'message': f'未找到ID为 {task_id} 的任务'})
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
            logger.warning(f"请求失败: 任务不存在 - task_id: {task_id}")
            return response, 404
        
        # 返回全部数据
        submissions = db.query(Submission).filter_by(task_id=task.id).order_by(Submission.submitted_at.desc()).all()
        data_list = []
        for sub in submissions:
            try:
                # 尝试解析JSON数据
                data = json.loads(sub.data)
                # 如果解析后是字符串，可能是双重编码，再解析一次
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except:
                        pass
                data['submitted_at'] = sub.submitted_at.strftime('%Y-%m-%d %H:%M:%S')
                data_list.append(data)
            except (json.JSONDecodeError, TypeError):
                # 如果解析失败，返回原始数据作为raw_data
                data_list.append({
                    'submitted_at': sub.submitted_at.strftime('%Y-%m-%d %H:%M:%S'),
                    'raw_data': sub.data
                })
        
        response = jsonify({
            'task_id': task.task_id,
            'task_title': task.title,
            'total_submissions': len(data_list),
            'submissions': data_list
        })
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response, 200
    except Exception as e:
        logger.error(f"API异常: {str(e)}", exc_info=True)
        response = jsonify({'error': '服务器错误', 'message': str(e)})
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response, 500
    finally:
        db.close()

@quickform_bp.route('/api/tasks', methods=['GET'])
def list_tasks():
    """返回最近的任务列表，便于获取 task_id 进行API测试"""
    db = SessionLocal()
    try:
        tasks = db.query(Task).order_by(Task.created_at.desc()).limit(20).all()
        data = [
            {
                'id': t.id,
                'title': t.title,
                'task_id': t.task_id,
                'created_at': t.created_at.strftime('%Y-%m-%d %H:%M:%S') if t.created_at else ''
            }
            for t in tasks
        ]
        response = jsonify({'items': data, 'count': len(data)})
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response, 200
    except Exception as e:
        response = jsonify({'error': '服务器错误', 'message': str(e)})
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response, 500
    finally:
        db.close()

@quickform_bp.route('/export/<int:task_id>')
@login_required
def export_data(task_id):
    """导出数据"""
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if not task or task.user_id != current_user.id:
            flash('无权访问此数据', 'danger')
            return redirect(url_for('quickform.dashboard'))
        
        submission = db.query(Submission).filter_by(task_id=task.id).all()
        
        if not submission:
            flash('没有可导出的数据', 'info')
            return redirect(url_for('quickform.task_detail', task_id=task_id))
        
        data_list = []
        for sub in submission:
            try:
                data = json.loads(sub.data)
                data['submitted_at'] = sub.submitted_at.strftime('%Y-%m-%d %H:%M:%S')
                data_list.append(data)
            except:
                data_list.append({
                    'submitted_at': sub.submitted_at.strftime('%Y-%m-%d %H:%M:%S'),
                    'raw_data': sub.data
                })
        
        df = pd.DataFrame(data_list)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='提交数据')
        output.seek(0)
        
        filename = f"{task.title}_数据导出_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        try:
            return send_file(output, download_name=filename, as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        except TypeError:
            return send_file(output, attachment_filename=filename, as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        flash(f'导出数据时出错: {str(e)}', 'danger')
        return redirect(url_for('quickform.task_detail', task_id=task_id))
    finally:
        db.close()

@quickform_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """个人设置"""
    db = SessionLocal()
    try:
        ai_config = db.query(AIConfig).filter_by(user_id=current_user.id).first()
        user_record = db.get(User, current_user.id)
        pending_cert_request = db.query(CertificationRequest).filter_by(user_id=current_user.id, status=0).order_by(CertificationRequest.created_at.desc()).first()
        last_cert_request = db.query(CertificationRequest).filter_by(user_id=current_user.id).order_by(CertificationRequest.created_at.desc()).first()
        
        if request.method == 'POST':
            if 'selected_model' in request.form:
                selected_model = request.form.get('selected_model')
                deepseek_api_key = request.form.get('deepseek_api_key', '')
                doubao_api_key = request.form.get('doubao_api_key', '')
                qwen_api_key = request.form.get('qwen_api_key', '')
                chat_server_api_url = request.form.get('chat_server_api_url', '')
                chat_server_api_token = request.form.get('chat_server_api_token', '')
                
                if ai_config:
                    ai_config.selected_model = selected_model
                    ai_config.deepseek_api_key = deepseek_api_key
                    ai_config.doubao_api_key = doubao_api_key
                    ai_config.qwen_api_key = qwen_api_key
                    ai_config.chat_server_api_url = chat_server_api_url
                    ai_config.chat_server_api_token = chat_server_api_token
                else:
                    ai_config = AIConfig(
                        user_id=current_user.id,
                        selected_model=selected_model,
                        deepseek_api_key=deepseek_api_key,
                        doubao_api_key=doubao_api_key,
                        qwen_api_key=qwen_api_key,
                        chat_server_api_url=chat_server_api_url,
                        chat_server_api_token=chat_server_api_token
                    )
                    db.add(ai_config)
                
                db.commit()
                flash('AI配置更新成功', 'success')
            
            elif 'current_password' in request.form:
                current_password = request.form.get('current_password')
                new_password = request.form.get('new_password')
                confirm_password = request.form.get('confirm_password', '')
                
                if not bcrypt.check_password_hash(current_user.password, current_password):
                    flash('当前密码错误', 'danger')
                elif new_password != confirm_password:
                    flash('新密码与确认密码不匹配', 'danger')
                elif len(new_password) < 6:
                    flash('密码长度至少为6个字符', 'danger')
                else:
                    hashed = bcrypt.generate_password_hash(new_password).decode('utf-8')
                    current_user.password = hashed
                    if user_record:
                        user_record.password = hashed
                    db.commit()
                    flash('密码修改成功', 'success')
            
            elif 'update_profile' in request.form:
                # 修改个人信息
                username = request.form.get('username', '').strip()
                email = request.form.get('email', '').strip()
                school = request.form.get('school', '').strip()
                phone = request.form.get('phone', '').strip()
                
                if not username or not email or not school or not phone:
                    flash('请填写所有必填字段', 'danger')
                    return redirect(url_for('quickform.profile'))
                
                import re
                if not re.match(r'^1[3-9]\d{9}$', phone):
                    flash('请输入正确的11位手机号码', 'danger')
                    return redirect(url_for('quickform.profile'))
                
                # 检查用户名和邮箱是否已被其他用户使用
                existing_user = db.query(User).filter(
                    (User.username == username) | (User.email == email)
                ).filter(User.id != current_user.id).first()
                
                if existing_user:
                    flash('用户名或邮箱已被其他用户使用', 'danger')
                    return redirect(url_for('quickform.profile'))
                
                # 更新用户信息
                if user_record:
                    user_record.username = username
                    user_record.email = email
                    user_record.school = school
                    user_record.phone = phone
                else:
                    current_user.username = username
                    current_user.email = email
                    current_user.school = school
                    current_user.phone = phone
                
                db.commit()
                flash('个人信息更新成功', 'success')
            
            return redirect(url_for('quickform.profile'))
        
        return render_template(
            'profile.html',
            user=user_record or current_user,
            ai_config=ai_config,
            pending_cert_request=pending_cert_request,
            last_cert_request=last_cert_request
        )
    finally:
        db.close()

@quickform_bp.route('/certification/request', methods=['GET', 'POST'])
@login_required
def certification_request():
    """教师认证申请"""
    db = SessionLocal()
    try:
        user = db.get(User, current_user.id)
        if not user:
            flash('用户不存在', 'danger')
            return redirect(url_for('quickform.dashboard'))

        pending_request = db.query(CertificationRequest).filter_by(user_id=user.id, status=0).order_by(CertificationRequest.created_at.desc()).first()
        requests = db.query(CertificationRequest).filter_by(user_id=user.id).order_by(CertificationRequest.created_at.desc()).all()

        if request.method == 'POST':
            if user.is_certified:
                flash('您已完成认证，无需重复提交。', 'info')
                return redirect(url_for('quickform.profile'))
            if pending_request:
                flash('您已有待审核的认证申请，请耐心等待结果。', 'warning')
                return redirect(url_for('quickform.certification_request'))

            file = request.files.get('certificate_file')
            if not file or not file.filename.strip():
                flash('请上传能够证明教师身份的材料（允许图片或PDF）。', 'danger')
                return redirect(url_for('quickform.certification_request'))

            unique_filename, filepath = save_uploaded_file(file, CERTIFICATION_FOLDER, CERTIFICATION_ALLOWED_EXTENSIONS)
            if not unique_filename:
                flash('文件上传失败或格式不支持，请重试。支持 PNG / JPG / JPEG / PDF 格式。', 'danger')
                return redirect(url_for('quickform.certification_request'))

            cert_request = CertificationRequest(
                user_id=user.id,
                file_name=file.filename,
                file_path=filepath,
                status=0,
                created_at=datetime.now()
            )
            db.add(cert_request)
            db.commit()
            flash('认证申请已提交，请等待管理员审核。', 'success')
            return redirect(url_for('quickform.profile'))

        return render_template('certification_request.html', user=user, requests=requests, pending_request=pending_request)
    finally:
        db.close()

@quickform_bp.route('/api/test_ai', methods=['POST'])
@login_required
def test_ai_api():
    """测试当前用户的AI配置是否可用"""
    db = SessionLocal()
    try:
        ai_config = db.query(AIConfig).filter_by(user_id=current_user.id).first()
        if not ai_config or not ai_config.selected_model:
            return jsonify({'success': False, 'message': '请先保存AI配置后再测试'}), 400

        payload = request.get_json(silent=True) or {}
        test_prompt = (payload.get('prompt') or '这是一次连通性测试，请简短回复“OK”。').strip()
        if not test_prompt:
            test_prompt = '这是一次连通性测试，请简短回复“OK”。'

        try:
            response_text = call_ai_model(test_prompt, ai_config)
        except Exception as e:
            logger.error(f"AI配置测试失败: {str(e)}")
            return jsonify({'success': False, 'message': str(e)}), 500

        preview = (response_text or '').strip()
        if len(preview) > 200:
            preview = preview[:200] + '...'

        model_label = MODEL_LABELS.get(ai_config.selected_model, ai_config.selected_model)
        return jsonify({
            'success': True,
            'message': '调用成功，请确认响应内容是否符合预期',
            'model': ai_config.selected_model,
            'model_label': model_label,
            'response_preview': preview
        })
    finally:
        db.close()

@quickform_bp.route('/analyze/<int:task_id>/smart_analyze', methods=['GET', 'POST'])
@login_required
def smart_analyze(task_id):
    """智能分析"""
    db = SessionLocal()
    try:
        task = db.query(Task).filter_by(id=task_id, user_id=current_user.id).first()
        if not task:
            flash('任务不存在', 'danger')
            return redirect(url_for('quickform.dashboard'))
        
        ai_config = db.query(AIConfig).filter_by(user_id=current_user.id).first()
        
        if not ai_config or not ai_config.selected_model:
            return render_template('smart_analyze.html', task=task, error="请先在配置页面设置AI模型和API密钥", ai_config=ai_config, now=datetime.now(), model_label=None)
        
        model_label = MODEL_LABELS.get(ai_config.selected_model, ai_config.selected_model)
        
        if ai_config.selected_model == 'chat_server':
            if not current_app.config.get('CHAT_SERVER_API_TOKEN'):
                flash('当前使用默认 ChatServer 调用，建议在配置中设置专属 API Token（非必填）。', 'warning')
        elif ai_config.selected_model == 'deepseek' and not ai_config.deepseek_api_key:
            return render_template('smart_analyze.html', task=task, error="请先配置DeepSeek API密钥", ai_config=ai_config, now=datetime.now(), model_label=model_label)
        elif ai_config.selected_model == 'doubao' and not ai_config.doubao_api_key:
            return render_template('smart_analyze.html', task=task, error="请先配置豆包API密钥", ai_config=ai_config, now=datetime.now(), model_label=model_label)
        
        # 如果是提交生成请求，则同步生成并返回同页结果
        if request.method == 'POST':
            # 检查是仅保存模板还是生成报告
            action = request.form.get('action', 'generate')  # 'save_template' 或 'generate'
            
            # 获取用户提示词模板（不包含数据部分）
            user_prompt_template = request.form.get('user_prompt_template', '').strip()
            if user_prompt_template:
                # 保存用户模板
                task.user_prompt_template = user_prompt_template
                db.commit()
            
            # 如果只是保存模板，直接返回
            if action == 'save_template':
                flash('提示词模板已保存', 'success')
                return redirect(url_for('quickform.smart_analyze', task_id=task.id))
            
            # 生成报告的逻辑
            # 获取提交数据并生成完整提示词
            submission_for_prompt = db.query(Submission).filter_by(task_id=task_id).all()
            file_content_for_prompt = None
            if task.file_path and os.path.exists(task.file_path):
                file_content_for_prompt = read_file_content(task.file_path)
            
            # 检查是否有自定义的完整提示词（用户可能直接编辑了完整提示词）
            custom_prompt = request.form.get('custom_prompt', '').strip()
            if custom_prompt:
                # 用户直接编辑了完整提示词，使用它
                pass
            else:
                # 使用用户模板（如果有）生成完整提示词
                user_template = task.user_prompt_template if task.user_prompt_template else None
                custom_prompt = generate_analysis_prompt(task, submission_for_prompt, file_content_for_prompt, SessionLocal, Submission, user_template=user_template)
            
            # 保存完整提示词（用于兼容旧代码）
            task.custom_prompt = custom_prompt
            db.commit()
            
            try:
                # 后台线程执行，避免阻塞主请求线程
                t = threading.Thread(target=perform_analysis_with_custom_prompt, args=(
                    task_id, current_user.id, ai_config.id, custom_prompt,
                    SessionLocal, Task, Submission, AIConfig,
                    read_file_content, call_ai_model, save_analysis_report
                ), daemon=True)
                t.start()
                # 跳转到本页并标记运行中，前端据此开始轮询
                return redirect(url_for('quickform.smart_analyze', task_id=task.id, running=1))
            except Exception as e:
                return render_template('smart_analyze.html', task=task, error=f'生成报告失败: {str(e)}', ai_config=ai_config, now=datetime.now(), model_label=model_label)
        
        # GET 或 POST 完成后，准备页面所需数据
        # 刷新task对象以获取最新的html_analysis和custom_prompt
        db.refresh(task)
        submission = db.query(Submission).filter_by(task_id=task_id).all()
        current_submission_count = len(submission)
        file_content = None
        if task.file_path and os.path.exists(task.file_path):
            file_content = read_file_content(task.file_path)
        
        # 检查保存的提示词中的数据条数是否与当前实际数据条数一致
        should_regenerate_prompt = False
        if task.custom_prompt and task.custom_prompt.strip():
            # 尝试从提示词中提取数据条数
            # 匹配 "总提交数量：X 条" 或 "共有 X 条提交记录"
            count_patterns = [
                r'总提交数量[：:]\s*(\d+)\s*条',
                r'共有\s*(\d+)\s*条提交记录',
                r'总提交数量[：:]\s*(\d+)',
            ]
            saved_count = None
            for pattern in count_patterns:
                match = re.search(pattern, task.custom_prompt)
                if match:
                    saved_count = int(match.group(1))
                    break
            
            # 如果提取到数量且与当前数量不一致，需要重新生成
            if saved_count is not None and saved_count != current_submission_count:
                should_regenerate_prompt = True
                logger.info(f"任务 {task_id} 的数据条数已更新：{saved_count} -> {current_submission_count}，重新生成提示词")
        else:
            # 如果没有保存的提示词，需要生成
            should_regenerate_prompt = True
        
        # 根据检查结果决定使用保存的提示词还是重新生成
        # 使用用户模板（如果有）生成预览提示词
        user_template = task.user_prompt_template if task.user_prompt_template else None
        if should_regenerate_prompt:
            preview_prompt = generate_analysis_prompt(task, submission, file_content, SessionLocal, Submission, user_template=user_template)
            # 更新保存的提示词（但不立即提交，让用户可以选择是否保存）
        else:
            # 如果数据条数没有变化，但用户模板可能已更新，使用用户模板重新生成
            if user_template:
                preview_prompt = generate_analysis_prompt(task, submission, file_content, SessionLocal, Submission, user_template=user_template)
            else:
                preview_prompt = task.custom_prompt
        
        report = task.analysis_report if task and task.analysis_report else None
        user_prompt_template = task.user_prompt_template if task.user_prompt_template else ''

        running_flag = request.args.get('running') == '1'
        should_redirect = False
        if running_flag:
            with progress_lock:
                prog = analysis_progress.get(task.id)
            if prog and prog.get('status') == 'completed':
                should_redirect = True
        if should_redirect:
            return redirect(url_for('quickform.smart_analyze', task_id=task.id))
        
        return render_template('smart_analyze.html', 
                             task=task, 
                             report=report,
                             preview_prompt=preview_prompt,
                             user_prompt_template=user_prompt_template,
                             ai_config=ai_config,
                             now=datetime.now(),
                             model_label=model_label)
    finally:
        db.close()

@quickform_bp.route('/download_report/<int:task_id>')
@login_required
def download_report(task_id):
    """下载报告 - 图片格式（PNG）"""
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if not task:
            flash('任务不存在', 'danger')
            return redirect(url_for('quickform.dashboard'))
        if task.user_id != current_user.id:
            flash('无权访问此任务', 'danger')
            return redirect(url_for('quickform.dashboard'))
        
        # 获取报告内容
        report_content = task.analysis_report or "暂无报告内容"
        
        # 使用report_service中的函数生成图片
        buffer, encoded_filename = generate_report_image(task, report_content)
        
        # 返回图片文件
        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'image/png'
        # 使用RFC 2231编码处理文件名，避免latin-1编码错误
        response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{encoded_filename}"
        return response
        
    except Exception as e:
        logger.error(f"生成图片报告失败: {str(e)}", exc_info=True)
        flash(f'生成图片报告时出错: {str(e)}', 'danger')
        return redirect(url_for('quickform.dashboard'))
    finally:
        db.close()

@quickform_bp.route('/uploads/<path:filename>')
def uploaded_file(filename):
    """上传文件访问 - HTML文件需要审核通过才能访问"""
    try:
        # 检查文件扩展名，如果是HTML文件需要检查审核状态
        if filename.lower().endswith(('.html', '.htm')):
            db = SessionLocal()
            try:
                # 查找包含此文件名的任务
                task = db.query(Task).filter(Task.file_path.like(f'%{filename}')).first()
                if task:
                    # 管理员可直接访问原始文件
                    if current_user.is_authenticated and current_user.is_admin():
                        return send_from_directory(UPLOAD_FOLDER, filename)
                    # 检查审核状态
                    if task.html_approved != 1:
                        if task.html_approved == -1:
                            reason = html.escape(task.html_review_note or '管理员未提供原因')
                            title_text = '审核未通过'
                            message = f"页面未通过审核，原因：{reason}"
                            status_icon = '❌'
                        else:
                            title_text = '审核中'
                            message = '该页面正在等待管理员审核，审核通过后即可访问。'
                            status_icon = '⏳'

                        html_content = f"""
<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
    <meta charset=\"UTF-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
    <title>{title_text}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background-color: #f5f5f5;
            padding: 16px;
        }}
        .container {{
            max-width: 520px;
            text-align: center;
            padding: 40px;
            background: white;
            border-radius: 12px;
            box-shadow: 0 12px 32px rgba(15, 23, 42, 0.1);
        }}
        h1 {{ color: #333; margin-bottom: 16px; font-size: 24px; }}
        p {{ color: #555; margin-top: 12px; line-height: 1.6; }}
    </style>
</head>
<body>
    <div class=\"container\">
        <h1>{status_icon} {title_text}</h1>
        <p>{message}</p>
    </div>
</body>
</html>
                        """
                        response = make_response(html_content)
                        response.headers['Content-Type'] = 'text/html; charset=utf-8'
                        return response
                # 如果找不到任务或已审核通过，允许访问
            finally:
                db.close()
            return send_from_directory(UPLOAD_FOLDER, filename)
        else:
            # TXT 文件开放访问，便于公网直接查看
            if filename.lower().endswith('.txt'):
                return send_from_directory(UPLOAD_FOLDER, filename)
            # 其他非 HTML 文件仍需登录保护
            if not current_user.is_authenticated:
                flash('请先登录', 'warning')
                return redirect(url_for('quickform.login'))
            return send_from_directory(UPLOAD_FOLDER, filename)
    except FileNotFoundError:
        flash('文件不存在', 'danger')
        return redirect(request.referrer or url_for('quickform.dashboard'))

@quickform_bp.route('/generate_report/<int:task_id>', methods=['GET', 'POST'])
@login_required
def generate_report(task_id):
    """兼容旧链接：重定向到智能分析页面"""
    return redirect(url_for('quickform.smart_analyze', task_id=task_id))

@quickform_bp.route('/api/report_status/<int:task_id>', methods=['GET'])
@login_required
def report_status(task_id):
    """查询报告生成进度/结果（供前端轮询）"""
    try:
        with progress_lock:
            prog = analysis_progress.get(task_id)
            if prog:
                # 如果已完成且内存中有报告，直接返回报告
                if prog.get('status') == 'completed':
                    rep = analysis_results.get(task_id)
                    return jsonify({'status': 'completed', 'report': rep or prog.get('report', '')}), 200
                if prog.get('status') == 'error':
                    return jsonify({'status': 'error', 'message': prog.get('message', '未知错误')}), 200
                # 进行中
                return jsonify({'status': 'in_progress', 'progress': prog.get('progress', 0), 'message': prog.get('message', '')}), 200
        # 兜底：查数据库是否已有报告
        db = SessionLocal()
        try:
            task = db.get(Task, task_id)
            if task and task.analysis_report:
                return jsonify({'status': 'completed', 'report': task.analysis_report}), 200
        finally:
            db.close()
        return jsonify({'status': 'not_started'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@quickform_bp.route('/admin')
@admin_required
def admin_panel():
    """管理员面板"""
    db = SessionLocal()
    try:
        from datetime import timedelta
        
        today = datetime.now().date()
        today_start = datetime.combine(today, datetime.min.time())
        
        # 获取当前标签页
        current_tab = request.args.get('tab', 'users')
        
        # 用户列表分页
        user_page = request.args.get('user_page', 1, type=int)
        if not user_page or user_page < 1:
            user_page = 1
        user_per_page = 20
        search_keyword = (request.args.get('q') or '').strip()

        user_query = db.query(User)
        if search_keyword:
            like_pattern = f"%{search_keyword}%"
            user_query = user_query.filter(
                or_(
                    User.username.ilike(like_pattern),
                    User.email.ilike(like_pattern),
                    User.school.ilike(like_pattern),
                    User.phone.ilike(like_pattern)
                )
            )

        total_filtered_users = user_query.count()
        user_total_pages = max(math.ceil(total_filtered_users / user_per_page), 1) if total_filtered_users else 1
        if user_page > user_total_pages:
            user_page = user_total_pages

        users = (
            user_query
            .order_by(User.created_at.desc())
            .offset((user_page - 1) * user_per_page)
            .limit(user_per_page)
            .all()
        )
        
        # 任务列表分页
        task_page = request.args.get('task_page', 1, type=int)
        if not task_page or task_page < 1:
            task_page = 1
        task_per_page = 20
        
        task_query = db.query(Task)
        total_tasks = task_query.count()
        task_total_pages = max(math.ceil(total_tasks / task_per_page), 1) if total_tasks else 1
        if task_page > task_total_pages:
            task_page = task_total_pages
        
        all_tasks = (
            task_query
            .order_by(Task.created_at.desc())
            .offset((task_page - 1) * task_per_page)
            .limit(task_per_page)
            .all()
        )
        
        # HTML审核数据
        html_review_page = request.args.get('html_review_page', 1, type=int)
        if not html_review_page or html_review_page < 1:
            html_review_page = 1
        html_review_per_page = 20
        
        # 查询所有HTML任务 - 使用file_name字段匹配更可靠
        html_tasks_query = db.query(Task).filter(
            Task.file_path.isnot(None),
            Task.file_name.isnot(None),
            (Task.file_name.like('%.html') | Task.file_name.like('%.htm'))
        )
        total_html_tasks = html_tasks_query.count()
        html_review_total_pages = max(math.ceil(total_html_tasks / html_review_per_page), 1) if total_html_tasks else 1
        if html_review_page > html_review_total_pages:
            html_review_page = html_review_total_pages
        
        html_tasks = (
            html_tasks_query
            .order_by(Task.created_at.desc())
            .offset((html_review_page - 1) * html_review_per_page)
            .limit(html_review_per_page)
            .all()
        )
        
        html_tasks_with_review = []
        pending_html_count = 0
        for task in html_tasks:
            author = db.get(User, task.user_id)
            approver = db.get(User, task.html_approved_by) if task.html_approved_by else None
            html_tasks_with_review.append({
                'task': task,
                'author': author,
                'approver': approver
            })
            if task.html_approved != 1:
                pending_html_count += 1
        
        # 认证审核数据
        cert_review_page = request.args.get('cert_review_page', 1, type=int)
        if not cert_review_page or cert_review_page < 1:
            cert_review_page = 1
        cert_review_per_page = 20
        
        cert_requests_query = db.query(CertificationRequest)
        total_cert_requests = cert_requests_query.count()
        cert_review_total_pages = max(math.ceil(total_cert_requests / cert_review_per_page), 1) if total_cert_requests else 1
        if cert_review_page > cert_review_total_pages:
            cert_review_page = cert_review_total_pages
        
        cert_requests = (
            cert_requests_query
            .order_by(CertificationRequest.created_at.desc())
            .offset((cert_review_page - 1) * cert_review_per_page)
            .limit(cert_review_per_page)
            .all()
        )
        pending_cert_count = sum(1 for req in cert_requests if req.status == 0)
        
        total_users = db.query(User).count()
        admin_users = db.query(User).filter_by(role='admin').count()
        normal_users = db.query(User).filter_by(role='user').count()
        new_users_today = db.query(User).filter(User.created_at >= today_start).count()
        
        total_tasks = db.query(Task).count()
        new_tasks_today = db.query(Task).filter(Task.created_at >= today_start).count()
        avg_tasks_per_user = total_tasks / total_users if total_users > 0 else 0
        
        total_submissions = db.query(Submission).count()
        new_submissions_today = db.query(Submission).filter(Submission.submitted_at >= today_start).count()
        avg_submissions_per_task = total_submissions / total_tasks if total_tasks > 0 else 0
        
        tasks_with_reports = db.query(Task).filter(Task.analysis_report.isnot(None)).count()
        report_generation_rate = (tasks_with_reports / total_tasks * 100) if total_tasks > 0 else 0
        
        stats = {
            'total_users': total_users,
            'admin_users': admin_users,
            'normal_users': normal_users,
            'new_users_today': new_users_today,
            'total_tasks': total_tasks,
            'new_tasks_today': new_tasks_today,
            'avg_tasks_per_user': avg_tasks_per_user,
            'total_submissions': total_submissions,
            'new_submissions_today': new_submissions_today,
            'avg_submissions_per_task': avg_submissions_per_task,
            'tasks_with_reports': tasks_with_reports,
            'report_generation_rate': report_generation_rate
        }
        
        return render_template(
            'admin.html',
            users=users,
            all_tasks=all_tasks,
            stats=stats,
            user_search=search_keyword,
            user_page=user_page,
            user_pages=user_total_pages,
            user_total=total_filtered_users,
            user_per_page=user_per_page,
            task_page=task_page,
            task_pages=task_total_pages,
            task_total=total_tasks,
            task_per_page=task_per_page,
            html_tasks_with_review=html_tasks_with_review,
            pending_html_count=pending_html_count,
            html_review_page=html_review_page,
            html_review_pages=html_review_total_pages,
            html_review_total=total_html_tasks,
            html_review_per_page=html_review_per_page,
            cert_requests=cert_requests,
            pending_cert_count=pending_cert_count,
            cert_review_page=cert_review_page,
            cert_review_pages=cert_review_total_pages,
            cert_review_total=total_cert_requests,
            cert_review_per_page=cert_review_per_page,
            current_tab=current_tab
        )
    finally:
        db.close()

@quickform_bp.route('/admin/change_role/<int:user_id>', methods=['POST'])
@admin_required
def admin_change_role(user_id):
    """修改用户角色"""
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            flash('用户不存在', 'danger')
            return redirect(url_for('quickform.admin_panel', tab='users'))
        
        if user.id == current_user.id:
            flash('不能修改自己的角色', 'warning')
            return redirect(url_for('quickform.admin_panel', tab='users'))
        
        if user.role == 'admin':
            user.role = 'user'
            flash(f'已将用户 {user.username} 的权限改为普通用户', 'success')
        else:
            user.role = 'admin'
            flash(f'已将用户 {user.username} 的权限改为管理员', 'success')
        
        db.commit()
    finally:
        db.close()
    
    return redirect(url_for('quickform.admin_panel', tab='users'))

@quickform_bp.route('/admin/set_task_limit/<int:user_id>', methods=['POST'])
@admin_required
def admin_set_task_limit(user_id):
    """设置用户任务创建上限为无限制"""
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            flash('用户不存在', 'danger')
            return redirect(url_for('quickform.admin_panel', tab='users'))
        
        if user.id == current_user.id:
            flash('不能修改自己的任务上限', 'warning')
            return redirect(url_for('quickform.admin_panel', tab='users'))
        
        if user.role == 'admin':
            flash('管理员用户无需设置任务上限', 'warning')
            return redirect(url_for('quickform.admin_panel', tab='users'))
        
        user.task_limit = -1  # -1表示无限制
        db.commit()
        flash(f'已将用户 {user.username} 的任务创建上限调整为无限制', 'success')
    finally:
        db.close()
    
    return redirect(url_for('quickform.admin_panel', tab='users'))

@quickform_bp.route('/admin/reset_password', methods=['POST'])
@admin_required
def admin_reset_password():
    """管理员重置用户密码为123456"""
    user_id = request.form.get('user_id', type=int)
    if not user_id:
        return jsonify({'success': False, 'message': '缺少用户ID'}), 400
    
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        if user.id == current_user.id:
            return jsonify({'success': False, 'message': '不能重置自己的密码'}), 400
        
        # 重置密码为123456
        hashed_password = bcrypt.generate_password_hash('123456').decode('utf-8')
        user.password = hashed_password
        db.commit()
        
        return jsonify({
            'success': True,
            'message': f'用户 {user.username} 的密码已重置为 123456',
            'username': user.username
        })
    except Exception as e:
        db.rollback()
        logger.error(f"重置密码失败: {str(e)}")
        return jsonify({'success': False, 'message': f'重置失败: {str(e)}'}), 500
    finally:
        db.close()

@quickform_bp.route('/admin/review_html')
@admin_required
def admin_review_html():
    """审核中心：HTML页面审核（仅HTML，认证审核已分离）"""
    db = SessionLocal()
    try:
        page = request.args.get('page', 1, type=int)
        if not page or page < 1:
            page = 1
        per_page = 20
        
        # 查询所有HTML任务 - 使用file_name字段匹配更可靠
        tasks_query = db.query(Task).filter(
            Task.file_path.isnot(None),
            Task.file_name.isnot(None),
            (Task.file_name.like('%.html') | Task.file_name.like('%.htm'))
        )
        
        total_tasks = tasks_query.count()
        total_pages = max(math.ceil(total_tasks / per_page), 1) if total_tasks else 1
        if page > total_pages:
            page = total_pages
        
        tasks = (
            tasks_query
            .order_by(Task.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        
        tasks_with_review = []
        pending_html_count = 0
        for task in tasks:
            author = db.get(User, task.user_id)
            approver = db.get(User, task.html_approved_by) if task.html_approved_by else None
            tasks_with_review.append({
                'task': task,
                'author': author,
                'approver': approver
            })
            if task.html_approved != 1:
                pending_html_count += 1

        return render_template(
            'admin_review_html.html',
            tasks_with_review=tasks_with_review,
            pending_html_count=pending_html_count,
            page=page,
            pages=total_pages,
            total=total_tasks,
            per_page=per_page
        )
    finally:
        db.close()

@quickform_bp.route('/admin/review_html/batch', methods=['POST'])
@admin_required
def admin_review_html_batch():
    """批量通过HTML审核"""
    db = SessionLocal()
    try:
        raw_ids = request.form.getlist('task_ids')
        task_ids = []
        for value in raw_ids:
            try:
                task_ids.append(int(value))
            except (TypeError, ValueError):
                continue

        if not task_ids:
            flash('请选择至少一个待审核的任务', 'warning')
            return redirect(url_for('quickform.admin_panel', tab='html-review'))

        tasks = db.query(Task).filter(Task.id.in_(task_ids)).all()
        if not tasks:
            flash('未找到所选任务', 'warning')
            return redirect(url_for('quickform.admin_panel', tab='html-review'))

        updated_count = 0
        for task in tasks:
            if task.html_approved == 1:
                continue
            task.html_approved = 1
            task.html_approved_by = current_user.id
            task.html_approved_at = datetime.now()
            task.html_review_note = None
            updated_count += 1

        if updated_count:
            db.commit()
            flash(f'成功通过 {updated_count} 个任务的HTML页面审核', 'success')
        else:
            db.rollback()
            flash('所选任务均已通过审核，无需重复操作', 'info')
    except Exception as e:
        db.rollback()
        logger.error(f"批量HTML审核失败: {str(e)}")
        flash(f'批量审核失败：{str(e)}', 'danger')
    finally:
        db.close()
    
    return redirect(url_for('quickform.admin_review_html'))


@quickform_bp.route('/admin/certification/<int:request_id>/file')
@admin_required
def admin_view_certification_file(request_id):
    """管理员查看认证材料"""
    db = SessionLocal()
    try:
        cert_request = db.get(CertificationRequest, request_id)
        if not cert_request or not cert_request.file_path or not os.path.exists(cert_request.file_path):
            flash('认证材料不存在或已被删除。', 'danger')
            return redirect(url_for('quickform.admin_panel'))
        filename = os.path.basename(cert_request.file_path)
        try:
            return send_file(cert_request.file_path, download_name=filename, as_attachment=False)
        except TypeError:
            return send_file(cert_request.file_path, attachment_filename=filename, as_attachment=False)
    finally:
        db.close()


@quickform_bp.route('/admin/review_certification')
@admin_required
def admin_review_certification():
    """审核中心：教师认证审核（仅认证，HTML审核已分离）"""
    db = SessionLocal()
    try:
        page = request.args.get('page', 1, type=int)
        if not page or page < 1:
            page = 1
        per_page = 20
        
        cert_requests_query = db.query(CertificationRequest)
        total_requests = cert_requests_query.count()
        total_pages = max(math.ceil(total_requests / per_page), 1) if total_requests else 1
        if page > total_pages:
            page = total_pages
        
        cert_requests = (
            cert_requests_query
            .order_by(CertificationRequest.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        pending_cert_count = sum(1 for req in cert_requests if req.status == 0)

        return render_template(
            'admin_review_certification.html',
            cert_requests=cert_requests,
            pending_cert_count=pending_cert_count,
            page=page,
            pages=total_pages,
            total=total_requests,
            per_page=per_page
        )
    finally:
        db.close()

@quickform_bp.route('/admin/certification/<int:request_id>', methods=['POST'])
@admin_required
def admin_handle_certification(request_id):
    """管理员审核教师认证申请"""
    action = request.form.get('action')
    note = (request.form.get('note') or '').strip()

    db = SessionLocal()
    try:
        cert_request = db.get(CertificationRequest, request_id)
        if not cert_request:
            flash('认证申请不存在', 'danger')
            return redirect(url_for('quickform.admin_panel', tab='cert-review'))

        user = cert_request.user
        if not user:
            flash('无法找到申请人信息', 'danger')
            return redirect(url_for('quickform.admin_panel', tab='cert-review'))

        if action == 'approve':
            if cert_request.status == 1:
                flash('该认证申请已通过审核', 'info')
                return redirect(url_for('quickform.admin_panel', tab='cert-review'))

            cert_request.status = 1
            cert_request.reviewed_at = datetime.now()
            cert_request.reviewed_by = current_user.id
            cert_request.review_note = note

            user.is_certified = True
            user.certified_at = datetime.now()
            user.certification_note = note
            if user.task_limit != -1:
                user.task_limit = -1

            # 自动通过该用户所有待审核的HTML任务
            pending_tasks = db.query(Task).filter(Task.user_id == user.id, Task.html_approved != 1).all()
            for task in pending_tasks:
                task.html_approved = 1
                task.html_approved_by = current_user.id
                task.html_approved_at = datetime.now()
                task.html_review_note = None

            db.commit()
            flash(f'已通过 {user.username} 的认证申请，任务上限已调整为无限制。', 'success')
        elif action == 'reject':
            if cert_request.status == -1:
                flash('该认证申请已被拒绝', 'info')
                return redirect(url_for('quickform.admin_panel', tab='cert-review'))

            cert_request.status = -1
            cert_request.reviewed_at = datetime.now()
            cert_request.reviewed_by = current_user.id
            cert_request.review_note = note
            db.commit()
            flash('已拒绝该认证申请。', 'warning')
        else:
            flash('无效的操作类型', 'danger')
    except Exception as e:
        db.rollback()
        logger.error(f"认证审核处理失败: {str(e)}")
        flash(f'处理失败：{str(e)}', 'danger')
    finally:
        db.close()

    return redirect(url_for('quickform.admin_panel', tab='cert-review'))

@quickform_bp.route('/admin/review_html/<int:task_id>', methods=['POST'])
@admin_required
def admin_review_html_action(task_id):
    """HTML文件审核操作"""
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if not task:
            flash('任务不存在', 'danger')
            return redirect(url_for('quickform.admin_panel', tab='html-review'))
        
        action = request.form.get('action')
        note = (request.form.get('note') or '').strip()
        
        # 处理加精/取消加精操作
        if action == 'feature' or action == 'unfeature':
            if action == 'feature':
                task.is_featured = True
                flash('已标记为加精项目', 'success')
            else:
                task.is_featured = False
                flash('已取消加精标记', 'info')
            db.commit()
            return redirect(url_for('quickform.admin_panel', tab='html-review'))
        
        if action == 'approve':
            task.html_approved = 1
            task.html_approved_by = current_user.id
            task.html_approved_at = datetime.now()
            task.html_review_note = note if note else None
            db.commit()
            flash(f'已通过任务 "{task.title}" 的HTML文件审核', 'success')
        elif action == 'reject':
            if not note:
                flash('拒绝审核时需要填写原因。', 'danger')
                return redirect(url_for('quickform.admin_panel', tab='html-review'))
            task.html_approved = -1
            task.html_approved_by = current_user.id
            task.html_approved_at = datetime.now()
            task.html_review_note = note
            db.commit()
            flash(f'已拒绝任务 "{task.title}" 的HTML文件审核', 'warning')
        else:
            flash('无效的操作', 'danger')
    finally:
        db.close()
    
    return redirect(url_for('quickform.admin_panel', tab='html-review'))

@quickform_bp.route('/task/<int:task_id>/submission/remove', methods=['GET'])
@login_required
def remove_submission(task_id):
    """删除单条提交数据（支持DELETE与GET降级）"""
    db = SessionLocal()
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    submission_id = request.args.get('submission_id', type=int)

    def make_response(payload, status_code=200):
        resp = jsonify(payload)
        resp.status_code = status_code
        resp.headers['Cache-Control'] = 'no-store'
        return resp

    logger.info(
        f"[remove_submission] GET user={getattr(current_user, 'id', None)} "
        f"task={task_id} submission={submission_id} ip={client_ip}"
    )
    try:
        task = db.get(Task, task_id)
        if not task or task.user_id != current_user.id:
            logger.warning(
                f"[remove_submission] forbidden user={getattr(current_user, 'id', None)} task={task_id}"
            )
            return make_response({'success': False, 'message': '无权访问此任务'}, 403)
        if not submission_id:
            logger.warning(f"[remove_submission] missing submission_id task={task_id}")
            return make_response({'success': False, 'message': '缺少提交ID'}, 400)
        
        submission = db.query(Submission).filter_by(id=submission_id, task_id=task_id).first()
        if not submission:
            logger.warning(
                f"[remove_submission] submission_not_found task={task_id} submission={submission_id}"
            )
            return make_response({'success': False, 'message': '提交不存在'}, 404)
        
        db.delete(submission)
        db.commit()
        logger.info(
            f"[remove_submission] success user={getattr(current_user, 'id', None)} task={task_id} submission={submission_id}"
        )
        return make_response({'success': True, 'message': '删除成功'})
    except Exception as e:
        db.rollback()
        logger.error(
            f"[remove_submission] error task={task_id} submission={submission_id} err={str(e)}",
            exc_info=True
        )
        return make_response({'success': False, 'message': f'删除失败: {str(e)}'}, 500)
    finally:
        db.close()


@quickform_bp.route('/task/<int:task_id>/submissions/clear', methods=['GET'])
@login_required
def clear_all_submissions(task_id):
    """删除任务的所有提交数据（支持DELETE与GET降级）"""
    db = SessionLocal()
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)

    def make_response(payload, status_code=200):
        resp = jsonify(payload)
        resp.status_code = status_code
        resp.headers['Cache-Control'] = 'no-store'
        return resp

    logger.info(
        f"[clear_all_submissions] GET user={getattr(current_user, 'id', None)} task={task_id} ip={client_ip}"
    )
    try:
        task = db.get(Task, task_id)
        if not task or task.user_id != current_user.id:
            logger.warning(
                f"[clear_all_submissions] forbidden user={getattr(current_user, 'id', None)} task={task_id}"
            )
            return make_response({'success': False, 'message': '无权访问此任务'}, 403)
        
        submissions = db.query(Submission).filter_by(task_id=task_id).all()
        count = len(submissions)
        logger.info(
            f"[clear_all_submissions] deleting count={count} user={getattr(current_user, 'id', None)} task={task_id}"
        )
        for submission in submissions:
            db.delete(submission)
        
        db.commit()
        logger.info(
            f"[clear_all_submissions] success user={getattr(current_user, 'id', None)} task={task_id} deleted={count}"
        )
        return make_response({'success': True, 'message': f'成功删除 {count} 条数据'})
    except Exception as e:
        db.rollback()
        logger.error(
            f"[clear_all_submissions] error task={task_id} err={str(e)}",
            exc_info=True
        )
        return make_response({'success': False, 'message': f'删除失败: {str(e)}'}, 500)
    finally:
        db.close()


def init_quickform(app, login_manager_instance=None, database_type=None):
    """
    初始化QuickForm Blueprint
    在主应用中调用此函数来设置LoginManager、Bcrypt等
    
    参数:
        app: Flask应用实例
        login_manager_instance: LoginManager实例（可选）
        database_type: 数据库类型，'sqlite' 或 'mysql'（可选，如果指定则强制使用该类型）
    """
    global bcrypt, login_manager, _database_type
    
    # 如果指定了数据库类型，重新初始化数据库
    if database_type:
        _database_type = database_type.lower()
        logger.info(f"重新初始化数据库，使用类型: {_database_type}")
        _init_database(_database_type)
    
    # 初始化Flask-Bcrypt
    bcrypt = Bcrypt(app)
    
    # 使用传入的LoginManager实例，如果没有则创建新的
    if login_manager_instance:
        login_manager = login_manager_instance
        login_manager.login_view = 'quickform.login'
    else:
        login_manager = LoginManager()
        login_manager.init_app(app)
        login_manager.login_view = 'quickform.login'
    
    # 注意：user_loader将在主应用中统一设置，支持多系统用户
    
    # 执行数据库迁移
    try:
        migrate_database(engine)
    except Exception as e:
        logger.warning(f"数据库迁移警告: {str(e)}")
    
    # 初始化管理员账号
    def init_admin_account():
        db = SessionLocal()
        try:
            admin_username = 'wzkjgz'
            admin_user = db.query(User).filter_by(username=admin_username).first()
            if not admin_user:
                hashed_password = bcrypt.generate_password_hash('wzkjgz123!').decode('utf-8')
                admin_user = User(
                    username=admin_username,
                    email='wzlinmiaoyan@163.com',
                    password=hashed_password,
                    role='admin',
                    school='温州科技高级中学',
                    phone='00000000000'
                )
                db.add(admin_user)
                db.commit()
                logger.info("成功创建管理员账号：wzkjgz")
            elif admin_user.role != 'admin':
                admin_user.role = 'admin'
                admin_user.password = bcrypt.generate_password_hash('wzkjgz123!').decode('utf-8')
                db.commit()
                logger.info("成功更新管理员账号：wzkjgz")
        except Exception as e:
            logger.error(f"初始化管理员账号失败: {str(e)}")
        finally:
            db.close()
    
    try:
        init_admin_account()
    except Exception as e:
        logger.warning(f"初始化管理员账号警告: {str(e)}")
    
    # 确保uploads目录存在
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    if not os.path.exists(os.path.join(UPLOAD_FOLDER, 'reports')):
        os.makedirs(os.path.join(UPLOAD_FOLDER, 'reports'))
    if not os.path.exists(CERTIFICATION_FOLDER):
        os.makedirs(CERTIFICATION_FOLDER)
    
    logger.info("QuickForm Blueprint 初始化完成")

