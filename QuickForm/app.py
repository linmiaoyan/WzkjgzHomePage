"""精简版 QuickForm 应用 - 从原 app.py 精简而来，保留所有功能"""
import os
import json
import re
import pandas as pd
import io
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, make_response, send_file, send_from_directory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from datetime import datetime, timedelta
from dotenv import load_dotenv
import logging
from functools import wraps
import math

# 导入模型和工具
from models import Base, User, Task, Submission, AIConfig
from utils import (
    save_uploaded_file, read_file_content, generate_analysis_prompt,
    call_ai_model, save_analysis_report, timeout, analysis_progress,
    progress_lock, completed_reports, analysis_results
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()

# 配置
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
if not os.path.exists(os.path.join(UPLOAD_FOLDER, 'reports')):
    os.makedirs(os.path.join(UPLOAD_FOLDER, 'reports'))

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev_secret_key')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# 初始化数据库
DATABASE_URL = 'sqlite:///quickform.db'

# SQLite连接配置，启用外键约束
def _fk_pragma_on_connect(dbapi_con, connection_record):
    """在SQLite连接时启用外键约束"""
    dbapi_con.execute('PRAGMA foreign_keys=ON')

engine = create_engine(
    DATABASE_URL, 
    connect_args={'check_same_thread': False}
)
# 注册事件监听器，确保每次连接都启用外键约束
from sqlalchemy import event
event.listen(engine, 'connect', _fk_pragma_on_connect)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(engine)

# 数据库迁移
def migrate_user_table():
    try:
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('user')]
        with engine.begin() as conn:
            if 'school' not in columns:
                conn.execute(text("ALTER TABLE user ADD COLUMN school VARCHAR(200)"))
            if 'phone' not in columns:
                conn.execute(text("ALTER TABLE user ADD COLUMN phone VARCHAR(20)"))
            if 'role' not in columns:
                conn.execute(text("ALTER TABLE user ADD COLUMN role VARCHAR(20) DEFAULT 'user'"))
                conn.execute(text("UPDATE user SET role = 'user' WHERE role IS NULL"))
    except Exception as e:
        logger.warning(f"数据库迁移警告: {str(e)}")

try:
    migrate_user_table()
except Exception as e:
    logger.warning(f"数据库迁移警告: {str(e)}")

# 初始化Flask扩展
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
bcrypt = Bcrypt(app)

# 初始化管理员账号
def init_admin_account():
    db = SessionLocal()
    try:
        admin_username = 'wzkjgz'
        admin_user = db.query(User).filter_by(username=admin_username).first()
        if not admin_user:
            hashed_password = bcrypt.generate_password_hash('wzkjgz123!').decode('utf-8')
            admin_user = User(
                username=admin_username, email='wzlinmiaoyan@163.com',
                password=hashed_password, role='admin',
                school='温州科技高级中学', phone='13736354694'
            )
            db.add(admin_user)
            db.commit()
            logger.info("成功创建管理员账号")
        elif admin_user.role != 'admin':
            admin_user.role = 'admin'
            admin_user.password = bcrypt.generate_password_hash('wzkjgz123!').decode('utf-8')
            db.commit()
            logger.info("成功更新管理员账号")
    except Exception as e:
        logger.error(f"初始化管理员账号失败: {str(e)}")
    finally:
        db.close()

try:
    init_admin_account()
except Exception as e:
    logger.warning(f"初始化管理员账号警告: {str(e)}")

# 装饰器
def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin():
            flash('您没有权限访问此页面', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@login_manager.user_loader
def load_user(user_id):
    db = SessionLocal()
    try:
        return db.query(User).get(int(user_id))
    finally:
        db.close()

# ==================== 路由 ====================

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        school = request.form.get('school', '').strip()
        phone = request.form.get('phone', '').strip()
        
        if not all([username, email, password, school, phone]):
            flash('请填写所有必填字段', 'danger')
            return redirect(url_for('register'))
        
        if not re.match(r'^1[3-9]\d{9}$', phone):
            flash('请输入正确的11位手机号码', 'danger')
            return redirect(url_for('register'))
        
        db = SessionLocal()
        try:
            if db.query(User).filter((User.username == username) | (User.email == email)).first():
                flash('用户名或邮箱已存在', 'danger')
                return redirect(url_for('register'))
            
            user = User(
                username=username, email=email,
                password=bcrypt.generate_password_hash(password).decode('utf-8'),
                school=school, phone=phone
            )
            ai_config = AIConfig(user=user, selected_model='deepseek')
            db.add(user)
            db.commit()
            flash('注册成功，请登录', 'success')
            return redirect(url_for('login'))
        finally:
            db.close()
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(username=username).first()
            if user and bcrypt.check_password_hash(user.password, password):
                login_user(user)
                next_page = request.args.get('next')
                return redirect(next_page) if next_page else redirect(url_for('dashboard'))
            else:
                flash('用户名或密码错误', 'danger')
        finally:
            db.close()
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    # 查询加精的任务（通常是通过html_approved字段判断）
    db = SessionLocal()
    try:
        # 查询已审核通过且有HTML文件的任务作为加精项目
        featured_tasks = db.query(Task).filter(
            Task.html_approved.isnot(None),
            Task.html_approved == True
        ).order_by(Task.created_at.desc()).limit(3).all()
        
        # 构建featured_data列表
        featured_data = []
        for task in featured_tasks:
            if task.file_path and os.path.exists(task.file_path):
                # 构建文件URL
                file_url = url_for('uploaded_file', filename=os.path.basename(task.file_path), _external=True)
                featured_data.append({
                    'task': task,
                    'file_url': file_url
                })
        
        # 确保至少有3个元素（可能为空）
        while len(featured_data) < 3:
            featured_data.append(None)
            
    except Exception as e:
        logger.error(f"获取加精任务失败: {str(e)}")
        featured_data = [None, None, None]
    finally:
        db.close()
    
    return render_template('home.html', featured_data=featured_data)

@app.route('/dashboard')
@login_required
def dashboard():
    db = SessionLocal()
    try:
        tasks = db.query(Task).filter_by(user_id=current_user.id).order_by(Task.created_at.desc()).all()
        user_record = db.query(User).get(current_user.id)
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
            task_count=len(tasks),
            task_limit=task_limit,
            is_certified=is_certified
        )
    finally:
        db.close()

@app.route('/generate_report/<int:task_id>', methods=['GET', 'POST'])
@login_required
def generate_report(task_id):
    db = SessionLocal()
    try:
        task = db.query(Task).filter_by(id=task_id, user_id=current_user.id).first()
        if not task:
            return render_template('generate_report.html', error='任务不存在或无权访问')
        
        ai_config = db.query(AIConfig).filter_by(user_id=current_user.id).first()
        if not ai_config or not ai_config.selected_model:
            return render_template('generate_report.html', error="请先在配置页面设置AI模型和API密钥", ai_config=ai_config)
        
        # 验证API密钥
        if (ai_config.selected_model == 'deepseek' and not ai_config.deepseek_api_key) or \
           (ai_config.selected_model == 'doubao' and not ai_config.doubao_api_key) or \
           (ai_config.selected_model == 'qwen' and not ai_config.qwen_api_key):
            return render_template('generate_report.html', error="请先配置API密钥", ai_config=ai_config)
        
        custom_prompt = request.args.get('prompt') or request.form.get('custom_prompt')
        if not custom_prompt:
            submission = db.query(Submission).filter_by(task_id=task_id).all()
            file_content = read_file_content(task.file_path) if task.file_path and os.path.exists(task.file_path) else None
            custom_prompt = generate_analysis_prompt(task, submission, file_content, SessionLocal)
        
        if not custom_prompt or not custom_prompt.strip():
            return render_template('generate_report.html', task=task, error="提示词不能为空", ai_config=ai_config)
        
        try:
            timeout_seconds = 300
            
            @timeout(seconds=timeout_seconds, error_message=f"调用{ai_config.selected_model}模型超时")
            def call_ai_with_timeout(prompt, config):
                return call_ai_model(prompt, config)
            
            analysis_report = call_ai_with_timeout(custom_prompt, ai_config)
            save_analysis_report(task_id, analysis_report, SessionLocal, UPLOAD_FOLDER)
            
            return render_template('generate_report.html', task=task, report=analysis_report,
                                 preview_prompt=custom_prompt, ai_config=ai_config)
        except Exception as e:
            logger.error(f"生成报告失败: {str(e)}")
            return render_template('generate_report.html', task=task, error=f'生成报告失败: {str(e)}',
                                 preview_prompt=custom_prompt, ai_config=ai_config)
    except Exception as e:
        logger.error(f"访问生成报告页面失败: {str(e)}")
        flash('生成报告时出现错误', 'danger')
        return redirect(url_for('task_detail', task_id=task_id))
    finally:
        db.close()

@app.route('/create_task', methods=['GET', 'POST'])
@login_required
def create_task():
    db = SessionLocal()
    try:
        if not current_user.is_admin():
            if not current_user.can_create_task(SessionLocal, Task):
                task_count = db.query(Task).filter_by(user_id=current_user.id).count()
                flash('您已达到任务数量上限（3个）。如需创建更多任务，请联系管理员：wzlinmiaoyan@163.com', 'warning')
                return redirect(url_for('dashboard'))
        
        if request.method == 'POST':
            task = Task(
                title=request.form.get('title'),
                description=request.form.get('description'),
                user_id=current_user.id
            )
            
            if 'file' in request.files and request.files['file'].filename:
                file = request.files['file']
                unique_filename, filepath = save_uploaded_file(file, UPLOAD_FOLDER)
                if unique_filename:
                    task.file_name = file.filename
                    task.file_path = filepath
            
            db.add(task)
            db.commit()
            flash('数据任务创建成功', 'success')
            return redirect(url_for('task_detail', task_id=task.id))

        task_count = db.query(Task).filter_by(user_id=current_user.id).count()
        task_limit = getattr(current_user, 'task_limit', None)
        is_certified = bool(getattr(current_user, 'is_certified', False))
    finally:
        db.close()
    return render_template('create_task.html', task_limit=task_limit, is_certified=is_certified, task_count=task_count)

@app.route('/task/<int:task_id>')
@login_required
def task_detail(task_id):
    db = SessionLocal()
    try:
        task = db.query(Task).get(task_id)
        if not task or task.user_id != current_user.id:
            flash('无权访问此任务', 'danger')
            return redirect(url_for('dashboard'))
        
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        if page < 1:
            page = 1
        if per_page < 1:
            per_page = 20
        elif per_page > 200:
            per_page = 200

        query = db.query(Submission).filter_by(task_id=task.id).order_by(Submission.submitted_at.desc())
        total_submissions = query.count()
        total_pages = max(math.ceil(total_submissions / per_page), 1) if total_submissions else 1
        if page > total_pages:
            page = total_pages

        submissions = query.offset((page - 1) * per_page).limit(per_page).all()

        def build_page_links(current_page, total_page, radius=2):
            links = []
            for p in range(1, total_page + 1):
                if p == 1 or p == total_page or abs(p - current_page) <= radius:
                    links.append(p)
                else:
                    if links and links[-1] != '...':
                        links.append('...')
            return links

        page_links = build_page_links(page, total_pages)

        saved_filename = task.file_path
        saved_filename = os.path.basename(saved_filename) if saved_filename else None

        pagination = {
            'page': page,
            'per_page': per_page,
            'pages': total_pages,
            'links': page_links
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

@app.route('/edit_task/<int:task_id>', methods=['GET', 'POST'])
@login_required
def edit_task(task_id):
    db = SessionLocal()
    try:
        task = db.query(Task).get(task_id)
        if not task or task.user_id != current_user.id:
            flash('无权编辑此任务', 'danger')
            return redirect(url_for('dashboard'))
        
        if request.method == 'POST':
            task.title = request.form.get('title')
            task.description = request.form.get('description')
            
            if 'file' in request.files and request.files['file'].filename:
                file = request.files['file']
                unique_filename, filepath = save_uploaded_file(file, UPLOAD_FOLDER)
                if unique_filename:
                    if task.file_path and os.path.exists(task.file_path):
                        os.remove(task.file_path)
                    task.file_name = file.filename
                    task.file_path = filepath
            elif request.form.get('remove_file'):
                if task.file_path and os.path.exists(task.file_path):
                    os.remove(task.file_path)
                task.file_name = None
                task.file_path = None
            
            db.commit()
            flash('任务更新成功', 'success')
            return redirect(url_for('task_detail', task_id=task.id))
        
        return render_template('edit_task.html', task=task)
    finally:
        db.close()

@app.route('/delete_task/<int:task_id>', methods=['POST'])
@login_required
def delete_task(task_id):
    """删除任务，同时删除所有相关的提交数据"""
    db = SessionLocal()
    try:
        task = db.query(Task).get(task_id)
        if not task or task.user_id != current_user.id:
            flash('无权删除此任务', 'danger')
            return redirect(url_for('dashboard'))
        
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
        
        return redirect(url_for('dashboard'))
    except Exception as e:
        db.rollback()
        logger.error(f"删除任务失败: {str(e)}", exc_info=True)
        flash(f'删除任务失败: {str(e)}', 'danger')
        return redirect(url_for('dashboard'))
    finally:
        db.close()

@app.route('/ai_test')
@login_required
def ai_test_page():
    return render_template('ai_test.html')

@app.route('/api/submit/<string:task_id>', methods=['POST', 'OPTIONS'])
def submit_form(task_id):
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response
    
    db = SessionLocal()
    try:
        task = db.query(Task).filter_by(task_id=task_id).first()
        if not task:
            response = jsonify({'error': '任务不存在'})
            response.headers['Access-Control-Allow-Origin'] = '*'
            return response, 404
        
        form_data = request.get_json() or request.form.to_dict()
        submission = Submission(task_id=task.id, data=str(form_data))
        db.add(submission)
        db.commit()
        
        response = jsonify({'message': '提交成功'})
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response, 200
    finally:
        db.close()

@app.route('/export/<int:task_id>')
@login_required
def export_data(task_id):
    db = SessionLocal()
    try:
        task = db.query(Task).get(task_id)
        if not task or task.user_id != current_user.id:
            flash('无权访问此数据', 'danger')
            return redirect(url_for('dashboard'))
        
        submission = db.query(Submission).filter_by(task_id=task.id).all()
        if not submission:
            flash('没有可导出的数据', 'info')
            return redirect(url_for('task_detail', task_id=task_id))
        
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
            return send_file(output, download_name=filename, as_attachment=True,
                           mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        except TypeError:
            return send_file(output, attachment_filename=filename, as_attachment=True,
                           mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        flash(f'导出数据时出错: {str(e)}', 'danger')
        return redirect(url_for('task_detail', task_id=task_id))
    finally:
        db.close()

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    db = SessionLocal()
    try:
        ai_config = db.query(AIConfig).filter_by(user_id=current_user.id).first()
        
        if request.method == 'POST':
            if 'selected_model' in request.form:
                selected_model = request.form.get('selected_model')
                if ai_config:
                    ai_config.selected_model = selected_model
                    ai_config.deepseek_api_key = request.form.get('deepseek_api_key', '')
                    ai_config.doubao_api_key = request.form.get('doubao_api_key', '')
                    ai_config.qwen_api_key = request.form.get('qwen_api_key', '')
                else:
                    ai_config = AIConfig(
                        user_id=current_user.id, selected_model=selected_model,
                        deepseek_api_key=request.form.get('deepseek_api_key', ''),
                        doubao_api_key=request.form.get('doubao_api_key', ''),
                        qwen_api_key=request.form.get('qwen_api_key', '')
                    )
                    db.add(ai_config)
                db.commit()
                flash('AI配置更新成功', 'success')
            elif 'current_password' in request.form:
                if bcrypt.check_password_hash(current_user.password, request.form.get('current_password')):
                    current_user.password = bcrypt.generate_password_hash(request.form.get('new_password')).decode('utf-8')
                    db.commit()
                    flash('密码修改成功', 'success')
                else:
                    flash('当前密码错误', 'danger')
            return redirect(url_for('profile'))
        
        return render_template('profile.html', user=current_user, ai_config=ai_config)
    finally:
        db.close()

@app.route('/analyze/<int:task_id>/smart_analyze', methods=['GET'])
@login_required
def smart_analyze(task_id):
    db = SessionLocal()
    try:
        task = db.query(Task).filter_by(id=task_id, user_id=current_user.id).first()
        if not task:
            flash('任务不存在', 'danger')
            return redirect(url_for('dashboard'))
        
        ai_config = db.query(AIConfig).filter_by(user_id=current_user.id).first()
        if not ai_config or not ai_config.selected_model:
            return render_template('smart_analyze.html', task=task,
                                 error="请先在配置页面设置AI模型和API密钥", ai_config=ai_config, now=datetime.now())
        
        if ((ai_config.selected_model == 'deepseek' and not ai_config.deepseek_api_key) or
            (ai_config.selected_model == 'doubao' and not ai_config.doubao_api_key)):
            return render_template('smart_analyze.html', task=task, error="请先配置API密钥",
                                 ai_config=ai_config, now=datetime.now())
        
        submission = db.query(Submission).filter_by(task_id=task_id).all()
        file_content = read_file_content(task.file_path) if task.file_path and os.path.exists(task.file_path) else None
        preview_prompt = generate_analysis_prompt(task, submission, file_content, SessionLocal)
        
        return render_template('smart_analyze.html', task=task, report=task.analysis_report,
                             preview_prompt=preview_prompt, ai_config=ai_config, now=datetime.now())
    finally:
        db.close()

@app.route('/download_report/<int:task_id>')
@login_required
def download_report(task_id):
    db = SessionLocal()
    try:
        task = db.query(Task).get(task_id)
        if not task or task.user_id != current_user.id:
            flash('无权访问此任务', 'danger')
            return redirect(url_for('dashboard'))
        
        if task.report_file_path and os.path.exists(task.report_file_path):
            safe_title = re.sub(r'[^a-zA-Z0-9_\u4e00-\u9fa5]', '_', task.title)
            safe_filename = f"{safe_title}_分析报告.html"
            try:
                return send_file(task.report_file_path, as_attachment=True, download_name=safe_filename,
                               mimetype='text/html; charset=utf-8')
            except TypeError:
                return send_file(task.report_file_path, as_attachment=True, attachment_filename=safe_filename,
                               mimetype='text/html; charset=utf-8')
        else:
            return render_template('download_report.html', task=task)
    except Exception as e:
        flash(f'下载报告时出错: {str(e)}', 'danger')
        return redirect(url_for('dashboard'))
    finally:
        db.close()

@app.route('/uploads/<path:filename>')
@login_required
def uploaded_file(filename):
    try:
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
    except FileNotFoundError:
        flash('文件不存在', 'danger')
        return redirect(request.referrer or url_for('dashboard'))

@app.route('/admin')
@admin_required
def admin_panel():
    db = SessionLocal()
    try:
        today = datetime.now().date()
        today_start = datetime.combine(today, datetime.min.time())
        
        users = db.query(User).order_by(User.created_at.desc()).all()
        all_tasks = db.query(Task).order_by(Task.created_at.desc()).all()
        
        stats = {
            'total_users': db.query(User).count(),
            'admin_users': db.query(User).filter_by(role='admin').count(),
            'normal_users': db.query(User).filter_by(role='user').count(),
            'new_users_today': db.query(User).filter(User.created_at >= today_start).count(),
            'total_tasks': db.query(Task).count(),
            'new_tasks_today': db.query(Task).filter(Task.created_at >= today_start).count(),
            'avg_tasks_per_user': db.query(Task).count() / db.query(User).count() if db.query(User).count() > 0 else 0,
            'total_submissions': db.query(Submission).count(),
            'new_submissions_today': db.query(Submission).filter(Submission.submitted_at >= today_start).count(),
            'avg_submissions_per_task': db.query(Submission).count() / db.query(Task).count() if db.query(Task).count() > 0 else 0,
            'tasks_with_reports': db.query(Task).filter(Task.analysis_report.isnot(None)).count(),
            'report_generation_rate': (db.query(Task).filter(Task.analysis_report.isnot(None)).count() / db.query(Task).count() * 100) if db.query(Task).count() > 0 else 0
        }
        
        return render_template('admin.html', users=users, all_tasks=all_tasks, stats=stats)
    finally:
        db.close()

@app.route('/admin/change_role/<int:user_id>', methods=['POST'])
@admin_required
def admin_change_role(user_id):
    db = SessionLocal()
    try:
        user = db.query(User).get(user_id)
        if not user:
            flash('用户不存在', 'danger')
            return redirect(url_for('admin_panel'))
        
        if user.id == current_user.id:
            flash('不能修改自己的角色', 'warning')
            return redirect(url_for('admin_panel'))
        
        user.role = 'user' if user.role == 'admin' else 'admin'
        flash(f'已将用户 {user.username} 的权限改为{"普通用户" if user.role == "user" else "管理员"}', 'success')
        db.commit()
    finally:
        db.close()
    return redirect(url_for('admin_panel'))

@app.route('/task/<int:task_id>/submission/remove', methods=['GET'])
@login_required
def delete_submission(task_id):
    db = SessionLocal()
    submission_id = request.args.get('submission_id', type=int)

    def make_response(payload, status=200):
        resp = jsonify(payload)
        resp.status_code = status
        resp.headers['Cache-Control'] = 'no-store'
        return resp

    try:
        task = db.query(Task).get(task_id)
        if not task or task.user_id != current_user.id:
            return make_response({'success': False, 'message': '无权访问此任务'}, 403)
        if not submission_id:
            return make_response({'success': False, 'message': '缺少提交ID'}, 400)

        submission = db.query(Submission).filter_by(id=submission_id, task_id=task_id).first()
        if not submission:
            return make_response({'success': False, 'message': '提交不存在'}, 404)

        db.delete(submission)
        db.commit()
        return make_response({'success': True, 'message': '删除成功'})
    except Exception as e:
        db.rollback()
        return make_response({'success': False, 'message': f'删除失败: {str(e)}'}, 500)
    finally:
        db.close()


@app.route('/task/<int:task_id>/submissions/clear', methods=['GET'])
@login_required
def delete_all_submissions(task_id):
    db = SessionLocal()

    def make_response(payload, status=200):
        resp = jsonify(payload)
        resp.status_code = status
        resp.headers['Cache-Control'] = 'no-store'
        return resp

    try:
        task = db.query(Task).get(task_id)
        if not task or task.user_id != current_user.id:
            return make_response({'success': False, 'message': '无权访问此任务'}, 403)

        submissions = db.query(Submission).filter_by(task_id=task_id).all()
        count = len(submissions)
        for submission in submissions:
            db.delete(submission)

        db.commit()
        return make_response({'success': True, 'message': f'成功删除 {count} 条数据'})
    except Exception as e:
        db.rollback()
        return make_response({'success': False, 'message': f'删除失败: {str(e)}'}, 500)
    finally:
        db.close()

# 注册Blueprint兼容的端点别名，确保模板中的 url_for('quickform.xxx') 可正常解析
# 通过修改Flask的url_map来添加别名endpoint
_endpoint_aliases = {
    'index': 'quickform.index',
    'register': 'quickform.register',
    'login': 'quickform.login',
    'logout': 'quickform.logout',
    'dashboard': 'quickform.dashboard',
    'create_task': 'quickform.create_task',
    'task_detail': 'quickform.task_detail',
    'edit_task': 'quickform.edit_task',
    'delete_task': 'quickform.delete_task',
    'ai_test_page': 'quickform.ai_test_page',
    'submit_form': 'quickform.submit_form',
    'list_tasks': 'quickform.list_tasks',
    'export_data': 'quickform.export_data',
    'profile': 'quickform.profile',
    'certification_request': 'quickform.certification_request',
    'test_ai_api': 'quickform.test_ai_api',
    'smart_analyze': 'quickform.smart_analyze',
    'download_report': 'quickform.download_report',
    'uploaded_file': 'quickform.uploaded_file',
    'generate_report': 'quickform.generate_report',
    'report_status': 'quickform.report_status',
    'admin_panel': 'quickform.admin_panel',
    'admin_change_role': 'quickform.admin_change_role',
    'admin_set_task_limit': 'quickform.admin_set_task_limit',
    'admin_review_html': 'quickform.admin_review_html',
    'admin_review_html_batch': 'quickform.admin_review_html_batch',
    'admin_view_certification_file': 'quickform.admin_view_certification_file',
    'admin_handle_certification': 'quickform.admin_handle_certification',
    'admin_review_html_action': 'quickform.admin_review_html_action',
    'remove_submission': 'quickform.remove_submission',
    'clear_all_submissions': 'quickform.clear_all_submissions',
    'delete_submission': 'quickform.delete_submission',
    'delete_all_submissions': 'quickform.delete_all_submissions',
}

# 为每个原始endpoint创建别名endpoint
for original, alias in _endpoint_aliases.items():
    view_func = app.view_functions.get(original)
    if view_func:
        # 复制视图函数到别名
        app.view_functions[alias] = view_func
        # 为别名endpoint添加路由规则
        for rule in app.url_map.iter_rules():
            if rule.endpoint == original:
                # 创建新的规则，使用别名endpoint
                from werkzeug.routing import Rule
                new_rule = Rule(
                    rule.rule,
                    endpoint=alias,
                    methods=rule.methods,
                    defaults=rule.defaults,
                    subdomain=rule.subdomain,
                    strict_slashes=rule.strict_slashes,
                    redirect_to=rule.redirect_to,
                    alias=rule.alias,
                    host=rule.host
                )
                app.url_map.add(new_rule)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=80)

