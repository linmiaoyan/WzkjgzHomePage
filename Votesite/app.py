from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, current_user
from datetime import datetime, timedelta
import qrcode
from io import BytesIO
import pandas as pd
import os
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
from PIL import Image, ImageDraw, ImageFont
import math
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfutils import ImageReader
from reportlab.lib.pagesizes import A4, portrait
import time
import threading
import queue
import atexit
from sqlalchemy.orm import scoped_session, sessionmaker
import logging

logger = logging.getLogger(__name__)
import json

PUBLIC_HOST = "http://wzkjgz.site/"

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_fixed_secret_key_here' # 将此值替换为实际的固定密钥
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///votes.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['ADMIN_GATE_KEY'] = 'wzkjgz'

# 设置时区为北京时间
def get_current_time():
    return datetime.utcnow() + timedelta(hours=8)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'index'

# 数据模型
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    qr_code = db.Column(db.String(200), unique=True)
    votes = db.relationship('Vote', backref='user', lazy=True)
    subjective_answers = db.relationship(
        'SubjectiveAnswer',
        backref='user',
        lazy=True,
        cascade="all, delete-orphan"
    )

class Survey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # 'single_choice' 或 'table'
    introduction = db.Column(db.Text, nullable=True)  # 保留：问卷简介
    subjective_question_prompt = db.Column(db.Text, nullable=True) # 新增：主观题说明文字
    created_at = db.Column(db.DateTime, default=get_current_time)
    is_active = db.Column(db.Boolean, default=True)
    option_limits = db.Column(db.JSON, nullable=True)  # 新增：选项限制，格式为 {"A": 7, "B": 7, ...}
    table_option_count = db.Column(db.Integer, default=3)  # 新增：表格问卷选项数量，默认3
    questions = db.relationship('Question', backref='survey', lazy=True)
    qr_codes = db.relationship('QRCode', backref='survey', lazy=True)

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('survey.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    option_count = db.Column(db.Integer, nullable=True)  # 单选题的选项数量
    created_at = db.Column(db.DateTime, default=get_current_time)
    votes = db.relationship('Vote', backref='question', lazy=True)

class TableRespondent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('survey.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=get_current_time)
    survey = db.relationship('Survey', backref='table_respondents', lazy=True)

class QRCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('survey.id'), nullable=False)
    token = db.Column(db.String(200), unique=True, nullable=False)
    is_used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=get_current_time)

class Vote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    table_respondent_id = db.Column(db.Integer, db.ForeignKey('table_respondent.id'), nullable=True)
    score = db.Column(db.Text, nullable=False)  # 改为Text以支持长文本回答
    created_at = db.Column(db.DateTime, default=get_current_time)
    table_respondent = db.relationship('TableRespondent', backref='votes', lazy=True)

class SubjectiveAnswer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    survey_id = db.Column(db.Integer, db.ForeignKey('survey.id'), nullable=False)
    content = db.Column(db.Text, nullable=True) # 主观回答内容，可以为空
    created_at = db.Column(db.DateTime, default=get_current_time)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# 路由
@app.route('/')
def index():
    if current_user.is_authenticated and current_user.is_admin:
        surveys = Survey.query.filter_by(is_active=True).all()
        return render_template('admin.html', surveys=surveys)
    surveys = Survey.query.filter_by(is_active=True).all()
    return render_template('index.html', surveys=surveys)

@app.route('/admin_login', methods=['GET'])
def admin_login():
    # 通过 GET 参数密钥校验，仅持有密钥者可进入后台，无需 POST 账号密码
    provided_key = request.args.get('k', '')
    if not provided_key or provided_key != app.config['ADMIN_GATE_KEY']:
        flash('非法访问', 'danger')
        return redirect(url_for('thank_you'))
    session['is_admin'] = True
    return redirect(url_for('admin'))

def ensure_admin_session():
    if not session.get('is_admin'):
        return redirect(url_for('thank_you'))
    return None


@app.route('/admin')
def admin():
    guard = ensure_admin_session()
    if guard:
        return guard
    surveys = Survey.query.filter_by(is_active=True).all()
    return render_template('admin.html', surveys=surveys)

@app.route('/admin/create_survey', methods=['POST'])
def create_survey():
    guard = ensure_admin_session()
    if guard:
        return guard
    
    survey_type = request.form.get('survey_type')
    survey_name = request.form.get('survey_name')
    survey_introduction = request.form.get('survey_introduction')
    subjective_question_prompt = request.form.get('subjective_question_prompt')
    table_option_count = int(request.form.get('table_option_count', 3))
    
    if not survey_name or not survey_type:
        flash('请填写问卷名称并选择类型', 'danger')
        return redirect(url_for('admin'))
    
    survey = Survey(
        name=survey_name, 
        type=survey_type, 
        introduction=survey_introduction, 
        subjective_question_prompt=subjective_question_prompt,
        table_option_count=table_option_count if survey_type == 'table' else None
    )
    db.session.add(survey)
    db.session.commit()

    if survey_type == 'single_choice':
        return redirect(url_for('create_single_choice_questions', survey_id=survey.id))
    else:
        return redirect(url_for('create_table_questions', survey_id=survey.id))

@app.route('/admin/create_single_choice_questions/<int:survey_id>', methods=['GET', 'POST'])
def create_single_choice_questions(survey_id):
    guard = ensure_admin_session()
    if guard:
        return guard
    
    survey = Survey.query.get_or_404(survey_id)
    
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add_single':
            content = request.form.get('content')
            option_count = int(request.form.get('option_count', 4))
            
            if content:
                question = Question(
                    survey_id=survey_id,
                    content=content,
                    option_count=option_count
                )
                db.session.add(question)
                db.session.commit()
                flash('问题添加成功', 'success')
            else:
                flash('问题内容不能为空', 'danger')
        elif action == 'import_list':
            question_list_text = request.form.get('question_list')
            option_count_batch = int(request.form.get('option_count_batch', 4))
            
            if question_list_text:
                questions_content = [q.strip() for q in question_list_text.split('\n') if q.strip()]
                for content in questions_content:
                    question = Question(
                        survey_id=survey.id,
                        content=content,
                        option_count=option_count_batch
                    )
                    db.session.add(question)
                db.session.commit()
                flash(f'{len(questions_content)}个问题已成功导入', 'success')
            else:
                flash('导入列表不能为空', 'danger')
    
    questions = Question.query.filter_by(survey_id=survey_id).all()
    return render_template('create_single_choice.html', survey=survey, questions=questions)

@app.route('/admin/create_table_questions/<int:survey_id>', methods=['GET', 'POST'])
def create_table_questions(survey_id):
    guard = ensure_admin_session()
    if guard:
        return guard
    
    survey = Survey.query.get_or_404(survey_id)
    
    if request.method == 'POST':
        content = request.form.get('content')
        
        if content:
            question = Question(
                survey_id=survey_id,
                content=content,
                option_count=None
            )
            db.session.add(question)
            db.session.commit()
            flash('问题添加成功', 'success')
    
    questions = Question.query.filter_by(survey_id=survey_id).all()
    return render_template('create_table.html', survey=survey, questions=questions)

@app.route('/admin/manage_table_respondents/<int:survey_id>', methods=['GET', 'POST'])
def manage_table_respondents(survey_id):
    guard = ensure_admin_session()
    if guard:
        return guard

    survey = Survey.query.get_or_404(survey_id)

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add_single':
            name = request.form.get('name')
            if name:
                respondent = TableRespondent(survey_id=survey_id, name=name)
                db.session.add(respondent)
                db.session.commit()
                flash('人名添加成功', 'success')
            else:
                flash('人名不能为空', 'danger')
        elif action == 'import_list':
            name_list_text = request.form.get('name_list')
            if name_list_text:
                names = [n.strip() for n in name_list_text.split('\n') if n.strip()]
                for name in names:
                    respondent = TableRespondent(survey_id=survey_id, name=name)
                    db.session.add(respondent)
                db.session.commit()
                flash(f'{len(names)}个人名已成功导入', 'success')
            else:
                flash('导入列表不能为空', 'danger')

    respondents = TableRespondent.query.filter_by(survey_id=survey_id).all()
    return render_template('manage_table_respondents.html', survey=survey, respondents=respondents)

@app.route('/admin/generate_qr/<int:survey_id>', methods=['POST'])
def generate_qr(survey_id):
    guard = ensure_admin_session()
    if guard:
        return guard
    
    survey = Survey.query.get_or_404(survey_id)
    num_users = int(request.form.get('num_users', 0))
    
    if num_users <= 0:
        flash('请输入有效的用户数量', 'danger')
        return redirect(url_for('admin'))
    
    # 生成二维码
    qr_codes = []
    for _ in range(num_users):
        token = secrets.token_urlsafe(16)
        qr_code = QRCode(survey_id=survey_id, token=token)
        db.session.add(qr_code)
        qr_codes.append(token)
    
    db.session.commit()
    
    # 生成二维码图片
    qr_images = []
    for token in qr_codes:
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(f"{PUBLIC_HOST}login/{token}")
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        # 添加问卷名称
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("msyh.ttf", 20)
        except IOError:
            try:
                font = ImageFont.truetype("simhei.ttf", 20) # 备用字体
            except IOError:
                font = ImageFont.load_default()
                from flask import current_app
                current_app.logger.warning("无法加载中文字体 (msyh.ttf, simhei.ttf)。问卷名称可能无法正确显示或显示为方框。")

        # 在二维码下方添加问卷名称
        text_width = draw.textlength(survey.name, font=font)
        img_width = img.size[0]
        # Adjust y_pos for text to be slightly above the bottom border
        draw.text(((img_width - text_width) // 2, img.size[1] - 30), 
                 survey.name, font=font, fill='black')
        
        qr_images.append(img)
    
    # 创建PDF文件
    pdf_buffer = BytesIO()
    c = canvas.Canvas(pdf_buffer, pagesize=A4)
    
    # 定义每页的二维码布局
    cols = 4
    rows = 4 # 每页固定显示4x4个二维码
    
    # 计算每个二维码可用的最大正方形尺寸，并考虑页面边距
    margin = 20 # 页面边距
    available_width = A4[0] - 2 * margin
    available_height = A4[1] - 2 * margin
    
    cell_width = available_width / cols
    cell_height = available_height / rows
    qr_size_on_page = min(cell_width, cell_height) # 确保二维码是正方形
    
    for page in range(math.ceil(len(qr_images) / (cols * rows))):
        start_idx = page * (cols * rows)
        end_idx = min((page + 1) * (cols * rows), len(qr_images))
        page_qr_images = qr_images[start_idx:end_idx]
        
        for idx, img in enumerate(page_qr_images):
            row_in_page = idx // cols
            col_in_page = idx % cols
            
            # 计算二维码在页面上的位置，并居中
            x_pos = margin + col_in_page * cell_width + (cell_width - qr_size_on_page) / 2
            y_pos = A4[1] - margin - (row_in_page + 1) * cell_height + (cell_height - qr_size_on_page) / 2
            
            # 将PIL图像转换为PDF可用的格式，并通过ImageReader传递
            img_buffer = BytesIO()
            img.save(img_buffer, format='PNG')
            img_reader = ImageReader(img_buffer)
            
            # 在PDF中放置二维码，保持正方形比例
            c.drawImage(img_reader, 
                       x_pos, 
                       y_pos,
                       width=qr_size_on_page,
                       height=qr_size_on_page)
        
        c.showPage()
    
    c.save()
    pdf_buffer.seek(0)
    
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'qr_codes_{survey.name}.pdf'
    )

@app.route('/login/<token>')
def login_with_qr(token):
    qr = QRCode.query.filter_by(token=token).first()
    if not qr:
        flash('无效的二维码', 'danger')
        return redirect(url_for('thank_you'))
    
    # 查找或创建用户
    user = User.query.filter_by(qr_code=token).first()
    if not user:
        # 创建新用户
        user = User(
            username=f"user_{token[:8]}",
            password_hash=generate_password_hash(token),
            qr_code=token
        )
        db.session.add(user)
        db.session.commit()
    
    login_user(user)
    return redirect(url_for('vote', survey_id=qr.survey_id))

@app.route('/vote/<int:survey_id>')
@login_required
def vote(survey_id):
    survey = Survey.query.get_or_404(survey_id)
    questions = Question.query.filter_by(survey_id=survey_id).all()
    
    respondents = []
    if survey.type == 'table':
        respondents = TableRespondent.query.filter_by(survey_id=survey_id).all()
        
    table_option_count = survey.table_option_count if survey.type == 'table' else None
    
    return render_template(
        'vote.html',
        survey=survey,
        questions=questions,
        respondents=respondents,
        subjective_question_prompt=survey.subjective_question_prompt,
        table_option_count=table_option_count
    )

@app.route('/admin/set_option_limits/<int:survey_id>', methods=['POST'])
def set_option_limits(survey_id):
    guard = ensure_admin_session()
    if guard:
        return guard
    
    survey = Survey.query.get_or_404(survey_id)
    
    # 获取选项限制
    option_limits = {}
    for option in 'ABCDE':
        limit = request.form.get(f'limit_{option}')
        if limit and limit.strip():
            try:
                limit_value = int(limit)
                if limit_value > 0:
                    option_limits[option] = limit_value
            except ValueError:
                flash(f'选项 {option} 的限制值必须是正整数', 'danger')
                return redirect(url_for('create_single_choice_questions', survey_id=survey_id))
    
    # 更新问卷的选项限制
    survey.option_limits = option_limits
    db.session.commit()
    
    flash('选项限制设置已保存', 'success')
    return redirect(url_for('create_single_choice_questions', survey_id=survey_id))



submit_queue = queue.Queue()

def db_worker():
    with app.app_context():
        while True:
            try:
                func, args, kwargs = submit_queue.get()
                func(*args, **kwargs)
                submit_queue.task_done()
            except Exception as e:
                logger.error(f"数据库写入失败: {e}", exc_info=True)

threading.Thread(target=db_worker, daemon=True).start()

def save_vote_to_db(vote_data):
    Session = scoped_session(sessionmaker(bind=db.engine))
    session = Session()
    try:
        survey_id = vote_data['survey_id']
        user_id = vote_data['user_id']
        survey = session.get(Survey, survey_id)
        # 删除旧投票
        question_ids = [q.id for q in session.query(Question).filter_by(survey_id=survey_id).all()]
        session.query(Vote).filter(Vote.user_id == user_id, Vote.question_id.in_(question_ids)).delete(synchronize_session='fetch')
        session.query(SubjectiveAnswer).filter_by(user_id=user_id, survey_id=survey_id).delete(synchronize_session='fetch')
        # 插入新投票
        if survey.type == 'single_choice':
            for q_id, score in vote_data['single_choice_votes']:
                vote = Vote(user_id=user_id, question_id=q_id, score=score)
                session.add(vote)
        elif survey.type == 'table':
            for q_id, respondent_id, score in vote_data['table_votes']:
                vote = Vote(user_id=user_id, question_id=q_id, table_respondent_id=respondent_id, score=score)
                session.add(vote)
        if vote_data.get('subjective_answer'):
            subjective_answer = SubjectiveAnswer(user_id=user_id, survey_id=survey_id, content=vote_data['subjective_answer'])
            session.add(subjective_answer)
        
        # 提交事务
        session.commit()
    except Exception as e:
        logger.error(f"数据库写入异常: user_id={vote_data['user_id']}, survey_id={vote_data['survey_id']}, 错误: {e}", exc_info=True)
        # 遇到异常时尝试重新入队
        submit_queue.put((save_vote_to_db, (vote_data,), {}))
        time.sleep(0.5)
    finally:
        session.close()

@app.route('/submit_vote/<int:survey_id>', methods=['POST'])
@login_required
def submit_vote(survey_id):
    survey = Survey.query.get_or_404(survey_id)
    
    # 校验逻辑
    if survey.type == 'single_choice':
        questions = Question.query.filter_by(survey_id=survey_id).all()
        for question in questions:
            if f'question_{question.id}' not in request.form or not request.form[f'question_{question.id}']:
                flash('请完成所有问题后再进行提交', 'danger')
                return redirect(url_for('vote', survey_id=survey_id))
        if survey.option_limits:
            option_counts = {}
            for question_id, score in request.form.items():
                if question_id.startswith('question_'):
                    option = score
                    option_counts[option] = option_counts.get(option, 0) + 1
            for option, limit in survey.option_limits.items():
                if option_counts.get(option, 0) > limit:
                    flash(f'选项 {option} 的选择次数超过了限制 ({limit}次)', 'danger')
                    return redirect(url_for('vote', survey_id=survey_id))
    elif survey.type == 'table':
        questions = Question.query.filter_by(survey_id=survey_id).all()
        respondents = TableRespondent.query.filter_by(survey_id=survey_id).all()
        for question in questions:
            for respondent in respondents:
                if f'vote_{question.id}_{respondent.id}' not in request.form or not request.form[f'vote_{question.id}_{respondent.id}']:
                    flash('请完成所有问题后再进行提交', 'danger')
                    return redirect(url_for('vote', survey_id=survey_id))
    
    # 打包投票数据
    vote_data = {
        'survey_id': survey_id,
        'user_id': current_user.id,
        'single_choice_votes': [],
        'table_votes': [],
        'subjective_answer': None
    }
    
    if survey.type == 'single_choice':
        for question_id, score in request.form.items():
            if question_id.startswith('question_'):
                q_id = int(question_id.split('_')[1])
                vote_data['single_choice_votes'].append((q_id, score))
    elif survey.type == 'table':
        for key, score in request.form.items():
            if key.startswith('vote_'):
                parts = key.split('_')
                q_id = int(parts[1])
                respondent_id = int(parts[2])
                vote_data['table_votes'].append((q_id, respondent_id, score))
    
    if survey.subjective_question_prompt:
        subjective_answer_content = request.form.get('subjective_answer', '').strip()
        if subjective_answer_content:
            vote_data['subjective_answer'] = subjective_answer_content
    
    # 将投票数据入队等待写入数据库
    submit_queue.put((save_vote_to_db, (vote_data,), {}))
    flash('您的投票已排队，稍后会被写入数据库。', 'info')
    return redirect(url_for('thank_you'))

@app.route('/thank_you')
def thank_you():
    return render_template('thank_you.html')

@app.route('/admin/results/<int:survey_id>')
def results(survey_id):
    guard = ensure_admin_session()
    if guard:
        return guard
    
    survey = Survey.query.get_or_404(survey_id)
    
    # 创建原始数据
    data = []
    if survey.type == 'single_choice':
        votes = Vote.query.join(Question).filter(Question.survey_id == survey_id).all()
        for vote in votes:
            data.append({
                '用户': vote.user.username,
                '问题': vote.question.content.replace(' ', '-'),  # 替换空格为连字符
                '选项': vote.score,
                '时间': vote.created_at
            })
    elif survey.type == 'table':
        votes = Vote.query.join(Question).join(TableRespondent).filter(
            Question.survey_id == survey_id, 
            TableRespondent.survey_id == survey_id
        ).all()
        
        for vote in votes:
            data.append({
                '用户': vote.user.username,
                '问题': vote.question.content.replace(' ', '-'),  # 替换空格为连字符
                '人名': vote.table_respondent.name,
                '选项': vote.score,
                '时间': vote.created_at
            })
    
    # 包含主观题回答
    subjective_answers = SubjectiveAnswer.query.filter_by(survey_id=survey_id).all()
    if subjective_answers:
        for ans in subjective_answers:
            data.append({
                '用户': ans.user.username,
                '问题': (survey.subjective_question_prompt if survey.subjective_question_prompt else "主观题回答").replace(' ', '-'),
                '人名': None, # 为主观题回答添加人名，设置为None
                '选项': ans.content,
                '时间': ans.created_at
            })

    # 定义DataFrame的列名，以确保所有类型的数据都有正确的列
    columns = ['用户', '问题', '选项', '时间']
    if survey.type == 'table':
        columns.insert(2, '人名') # 在'问题'和'选项'之间插入'人名'

    # 创建DataFrame
    df = pd.DataFrame(data, columns=columns)
    
    # 创建Excel文件
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # 1. 原始数据（按用户排序）
        df.to_excel(writer, sheet_name='原始数据', index=False)
        
        # 2. 按问题排列的数据
        if survey.type == 'single_choice':
            # 对于单选题，按问题和选项排序
            sort_cols = []
            if '问题' in df.columns: sort_cols.append('问题')
            if '选项' in df.columns: sort_cols.append('选项')
            df_sorted = df.sort_values(sort_cols) if sort_cols else df
            df_sorted.to_excel(writer, sheet_name='按问题排列', index=False)
            
            # 3. 统计结果 - 新的格式
            # 获取所有唯一的问题和选项
            questions = df['问题'].unique()
            options = df['选项'].unique()
            
            # 创建统计结果DataFrame
            stats_data = []
            for question in questions:
                row_data = {'问题': question}
                # 计算每个选项的出现次数
                for option in options:
                    count = len(df[(df['问题'] == question) & (df['选项'] == option)])
                    row_data[f'{option}'] = count
                stats_data.append(row_data)
            
            stats_df = pd.DataFrame(stats_data)
            stats_df.to_excel(writer, sheet_name='统计结果', index=False)
            
        elif survey.type == 'table':
            # 对于表格题，按问题、人名和选项排序
            sort_cols = []
            if '问题' in df.columns: sort_cols.append('问题')
            if '人名' in df.columns: sort_cols.append('人名')
            if '选项' in df.columns: sort_cols.append('选项')
            df_sorted = df.sort_values(sort_cols) if sort_cols else df
            df_sorted.to_excel(writer, sheet_name='按问题排列', index=False)
            
            # 3. 统计结果 - 新的格式
            # 获取所有唯一的问题、人名和选项
            questions = df['问题'].unique()
            respondents = df['人名'].unique()
            options = list('ABCDE')[:survey.table_option_count]
            
            # 创建统计结果DataFrame
            stats_data = []
            for question in questions:
                for respondent in respondents:
                    row_data = {'问题': question, '人名': respondent}
                    # 计算每个选项的出现次数
                    for option in options:
                        count = len(df[(df['问题'] == question) & \
                                     (df['人名'] == respondent) & \
                                     (df['选项'] == option)])
                        row_data[f'{option}'] = count
                    stats_data.append(row_data)
            
            stats_df = pd.DataFrame(stats_data)
            stats_df.to_excel(writer, sheet_name='统计结果', index=False)
    
    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'vote_results_{survey.name}.xlsx'
    )

@app.route('/admin/delete_survey/<int:survey_id>', methods=['POST'])
def delete_survey(survey_id):
    guard = ensure_admin_session()
    if guard:
        return guard
    
    survey = Survey.query.get_or_404(survey_id)
    
    try:
        # 删除与问卷相关的所有投票记录
        Vote.query.filter(Vote.question.has(survey_id=survey_id)).delete(synchronize_session='fetch')
        # 删除与问卷相关的所有问题
        Question.query.filter_by(survey_id=survey_id).delete(synchronize_session='fetch')
        # 删除与问卷相关的所有人名（如果问卷是表格类型）
        TableRespondent.query.filter_by(survey_id=survey_id).delete(synchronize_session='fetch')
        # 删除与问卷相关的所有二维码
        QRCode.query.filter_by(survey_id=survey_id).delete(synchronize_session='fetch')
        
        # 最后删除问卷本身
        db.session.delete(survey)
        db.session.commit()
        flash(f'问卷 "{survey.name}" 及其所有相关数据已删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除问卷失败: {e}', 'danger')
        
    return redirect(url_for('admin'))

@app.route('/admin/edit_survey_title/<int:survey_id>', methods=['POST'])
def edit_survey_title(survey_id):
    guard = ensure_admin_session()
    if guard:
        return guard
    survey = Survey.query.get_or_404(survey_id)
    new_title = request.form.get('new_title')
    if new_title:
        survey.name = new_title
        db.session.commit()
        flash('问卷标题已更新', 'success')
    else:
        flash('标题不能为空', 'danger')
    return redirect(url_for('admin'))

def dump_queue_to_log():
    if not submit_queue.empty():
        with open('vote_queue_dump.log', 'a', encoding='utf-8') as f:
            f.write('--- Flask 服务重启，未提交队列内容如下 ---\n')
            while not submit_queue.empty():
                try:
                    func, args, kwargs = submit_queue.get_nowait()
                    f.write(str(args) + '\n')
                except Exception as e:
                    f.write(f'队列转储异常: {e}\n')

atexit.register(dump_queue_to_log)

@app.route('/admin/restart_server', methods=['POST'])
def restart_server():
    guard = ensure_admin_session()
    if guard:
        return guard
    flash('服务即将重启...', 'info')
    db.session.commit()
    dump_queue_to_log()  # 重启前主动转储一次
    os._exit(1)  # 让外部守护进程或开发环境自动重启
    return redirect(url_for('admin'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # 创建管理员账号
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                password_hash=generate_password_hash('admin123'),
                is_admin=True
            )
            db.session.add(admin)
            db.session.commit()
    app.run('0.0.0.0',port=80,debug=True, use_reloader=False)