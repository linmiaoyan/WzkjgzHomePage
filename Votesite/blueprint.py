"""
VoteSite Blueprint
将投票系统改造为Blueprint，可以整合到主应用中
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, session, current_app
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
from reportlab.lib.pagesizes import A4
import time
import logging

logger = logging.getLogger(__name__)
import threading
import queue
import atexit
from sqlalchemy.orm import scoped_session, sessionmaker

# 获取VoteSite目录路径
VOTESITE_DIR = os.path.dirname(os.path.abspath(__file__))

# 全局变量（将在init函数中设置）
db = None
login_manager = None

# 数据库模型（将在init函数中定义）
User = None
Survey = None
Question = None
TableRespondent = None
QRCode = None
Vote = None
SubjectiveAnswer = None

# 提交队列
submit_queue = queue.Queue()

# 设置时区为北京时间
def get_current_time():
    return datetime.utcnow() + timedelta(hours=8)

# 创建Blueprint
votesite_bp = Blueprint(
    'votesite',
    __name__,
    template_folder='templates',
    static_folder='../static'  # 指向主应用的static目录
)

def ensure_admin_session():
    """确保管理员会话"""
    if not session.get('is_admin'):
        return redirect(url_for('votesite.thank_you'))
    return None

def get_public_host():
    """动态获取PUBLIC_HOST，包含/votesite前缀"""
    return f"{request.host_url}votesite/"

def db_worker(app):
    """数据库写入工作线程"""
    with app.app_context():
        while True:
            try:
                func, args, kwargs = submit_queue.get()
                func(*args, **kwargs)
                submit_queue.task_done()
            except Exception as e:
                logger.error(f"数据库写入失败: {e}", exc_info=True)

def save_vote_to_db(vote_data):
    """保存投票到数据库"""
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
        
        session.commit()
    except Exception as e:
        logger.error(f"数据库写入异常: user_id={vote_data['user_id']}, survey_id={vote_data['survey_id']}, 错误: {e}", exc_info=True)
        submit_queue.put((save_vote_to_db, (vote_data,), {}))
        time.sleep(0.5)
    finally:
        session.close()

def dump_queue_to_log():
    """转储队列到日志"""
    if not submit_queue.empty():
        log_path = os.path.join(VOTESITE_DIR, 'vote_queue_dump.log')
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write('--- Flask 服务重启，未提交队列内容如下 ---\n')
            while not submit_queue.empty():
                try:
                    func, args, kwargs = submit_queue.get_nowait()
                    f.write(str(args) + '\n')
                except Exception as e:
                    f.write(f'队列转储异常: {e}\n')

atexit.register(dump_queue_to_log)

# 路由函数
@votesite_bp.route('/')
def index():
    """首页 - 如果是管理员则进入管理员页面"""
    if current_user.is_authenticated and current_user.is_admin:
        surveys = Survey.query.filter_by(is_active=True).all()
        return redirect(url_for('votesite.admin'))
    surveys = Survey.query.filter_by(is_active=True).all()
    return render_template('index.html', surveys=surveys)

@votesite_bp.route('/admin_login', methods=['GET'])
def admin_login():
    """管理员登录"""
    provided_key = request.args.get('k', '')
    if not provided_key or provided_key != current_app.config.get('VOTESITE_ADMIN_GATE_KEY', 'wzkjgz'):
        flash('非法访问', 'danger')
        return redirect(url_for('votesite.thank_you'))
    session['is_admin'] = True
    return redirect(url_for('votesite.admin'))

@votesite_bp.route('/admin')
def admin():
    """管理员页面"""
    guard = ensure_admin_session()
    if guard:
        return guard
    surveys = Survey.query.filter_by(is_active=True).all()
    # 明确指定使用 VoteSite 的模板，使用完整的模板路径避免与QuickForm冲突
    return render_template('admin.html', surveys=surveys)

@votesite_bp.route('/admin/create_survey', methods=['POST'])
def create_survey():
    """创建问卷"""
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
        return redirect(url_for('votesite.admin'))
    
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
        return redirect(url_for('votesite.create_single_choice_questions', survey_id=survey.id))
    else:
        return redirect(url_for('votesite.create_table_questions', survey_id=survey.id))

@votesite_bp.route('/admin/create_single_choice_questions/<int:survey_id>', methods=['GET', 'POST'])
def create_single_choice_questions(survey_id):
    """创建单选题"""
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

@votesite_bp.route('/admin/create_table_questions/<int:survey_id>', methods=['GET', 'POST'])
def create_table_questions(survey_id):
    """创建表格题"""
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

@votesite_bp.route('/admin/manage_table_respondents/<int:survey_id>', methods=['GET', 'POST'])
def manage_table_respondents(survey_id):
    """管理表格题被评价人"""
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

@votesite_bp.route('/admin/generate_qr/<int:survey_id>', methods=['POST'])
def generate_qr(survey_id):
    """生成二维码"""
    guard = ensure_admin_session()
    if guard:
        return guard
    
    survey = Survey.query.get_or_404(survey_id)
    num_users = int(request.form.get('num_users', 0))
    
    if num_users <= 0:
        flash('请输入有效的用户数量', 'danger')
        return redirect(url_for('votesite.admin'))
    
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
    public_host = get_public_host()
    for token in qr_codes:
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(f"{public_host}login/{token}")
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        # 添加问卷名称
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("msyh.ttf", 20)
        except IOError:
            try:
                font = ImageFont.truetype("simhei.ttf", 20)
            except IOError:
                font = ImageFont.load_default()
                current_app.logger.warning("无法加载中文字体 (msyh.ttf, simhei.ttf)。问卷名称可能无法正确显示或显示为方框。")

        text_width = draw.textlength(survey.name, font=font)
        img_width = img.size[0]
        draw.text(((img_width - text_width) // 2, img.size[1] - 30), 
                 survey.name, font=font, fill='black')
        
        qr_images.append(img)
    
    # 创建PDF文件
    pdf_buffer = BytesIO()
    c = canvas.Canvas(pdf_buffer, pagesize=A4)
    
    cols = 4
    rows = 4
    margin = 20
    available_width = A4[0] - 2 * margin
    available_height = A4[1] - 2 * margin
    cell_width = available_width / cols
    cell_height = available_height / rows
    qr_size_on_page = min(cell_width, cell_height)
    
    for page in range(math.ceil(len(qr_images) / (cols * rows))):
        start_idx = page * (cols * rows)
        end_idx = min((page + 1) * (cols * rows), len(qr_images))
        page_qr_images = qr_images[start_idx:end_idx]
        
        for idx, img in enumerate(page_qr_images):
            row_in_page = idx // cols
            col_in_page = idx % cols
            
            x_pos = margin + col_in_page * cell_width + (cell_width - qr_size_on_page) / 2
            y_pos = A4[1] - margin - (row_in_page + 1) * cell_height + (cell_height - qr_size_on_page) / 2
            
            img_buffer = BytesIO()
            img.save(img_buffer, format='PNG')
            img_reader = ImageReader(img_buffer)
            
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

@votesite_bp.route('/login/<token>')
def login_with_qr(token):
    """通过二维码登录"""
    qr = QRCode.query.filter_by(token=token).first()
    if not qr:
        flash('无效的二维码', 'danger')
        return redirect(url_for('votesite.thank_you'))
    
    # 查找或创建用户
    user = User.query.filter_by(qr_code=token).first()
    if not user:
        user = User(
            username=f"user_{token[:8]}",
            password_hash=generate_password_hash(token),
            qr_code=token
        )
        db.session.add(user)
        db.session.commit()
    
    login_user(user)
    return redirect(url_for('votesite.vote', survey_id=qr.survey_id))

@votesite_bp.route('/vote/<int:survey_id>')
@login_required
def vote(survey_id):
    """投票页面"""
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

@votesite_bp.route('/admin/set_option_limits/<int:survey_id>', methods=['POST'])
def set_option_limits(survey_id):
    """设置选项限制"""
    guard = ensure_admin_session()
    if guard:
        return guard
    
    survey = Survey.query.get_or_404(survey_id)
    
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
                return redirect(url_for('votesite.create_single_choice_questions', survey_id=survey_id))
    
    survey.option_limits = option_limits
    db.session.commit()
    
    flash('选项限制设置已保存', 'success')
    return redirect(url_for('votesite.create_single_choice_questions', survey_id=survey_id))

@votesite_bp.route('/submit_vote/<int:survey_id>', methods=['POST'])
@login_required
def submit_vote(survey_id):
    """提交投票"""
    survey = Survey.query.get_or_404(survey_id)
    
    # 校验逻辑
    if survey.type == 'single_choice':
        questions = Question.query.filter_by(survey_id=survey_id).all()
        for question in questions:
            if f'question_{question.id}' not in request.form or not request.form[f'question_{question.id}']:
                flash('请完成所有问题后再进行提交', 'danger')
                return redirect(url_for('votesite.vote', survey_id=survey_id))
        if survey.option_limits:
            option_counts = {}
            for question_id, score in request.form.items():
                if question_id.startswith('question_'):
                    option = score
                    option_counts[option] = option_counts.get(option, 0) + 1
            for option, limit in survey.option_limits.items():
                if option_counts.get(option, 0) > limit:
                    flash(f'选项 {option} 的选择次数超过了限制 ({limit}次)', 'danger')
                    return redirect(url_for('votesite.vote', survey_id=survey_id))
    elif survey.type == 'table':
        questions = Question.query.filter_by(survey_id=survey_id).all()
        respondents = TableRespondent.query.filter_by(survey_id=survey_id).all()
        for question in questions:
            for respondent in respondents:
                if f'vote_{question.id}_{respondent.id}' not in request.form or not request.form[f'vote_{question.id}_{respondent.id}']:
                    flash('请完成所有问题后再进行提交', 'danger')
                    return redirect(url_for('votesite.vote', survey_id=survey_id))
    
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
    return redirect(url_for('votesite.thank_you'))

@votesite_bp.route('/thank_you')
def thank_you():
    """感谢页面"""
    return render_template('thank_you.html')

@votesite_bp.route('/admin/results/<int:survey_id>')
def results(survey_id):
    """查看结果"""
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
                '问题': vote.question.content.replace(' ', '-'),
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
                '问题': vote.question.content.replace(' ', '-'),
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
                '人名': None,
                '选项': ans.content,
                '时间': ans.created_at
            })

    # 定义DataFrame的列名
    columns = ['用户', '问题', '选项', '时间']
    if survey.type == 'table':
        columns.insert(2, '人名')

    # 创建DataFrame
    df = pd.DataFrame(data, columns=columns)
    
    # 创建Excel文件
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='原始数据', index=False)
        
        if survey.type == 'single_choice':
            sort_cols = []
            if '问题' in df.columns: sort_cols.append('问题')
            if '选项' in df.columns: sort_cols.append('选项')
            df_sorted = df.sort_values(sort_cols) if sort_cols else df
            df_sorted.to_excel(writer, sheet_name='按问题排列', index=False)
            
            questions = df['问题'].unique()
            options = df['选项'].unique()
            
            stats_data = []
            for question in questions:
                row_data = {'问题': question}
                for option in options:
                    count = len(df[(df['问题'] == question) & (df['选项'] == option)])
                    row_data[f'{option}'] = count
                stats_data.append(row_data)
            
            stats_df = pd.DataFrame(stats_data)
            stats_df.to_excel(writer, sheet_name='统计结果', index=False)
            
        elif survey.type == 'table':
            sort_cols = []
            if '问题' in df.columns: sort_cols.append('问题')
            if '人名' in df.columns: sort_cols.append('人名')
            if '选项' in df.columns: sort_cols.append('选项')
            df_sorted = df.sort_values(sort_cols) if sort_cols else df
            df_sorted.to_excel(writer, sheet_name='按问题排列', index=False)
            
            questions = df['问题'].unique()
            respondents = df['人名'].unique()
            options = list('ABCDE')[:survey.table_option_count]
            
            stats_data = []
            for question in questions:
                for respondent in respondents:
                    row_data = {'问题': question, '人名': respondent}
                    for option in options:
                        count = len(df[(df['问题'] == question) & 
                                     (df['人名'] == respondent) & 
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

@votesite_bp.route('/admin/delete_survey/<int:survey_id>', methods=['POST'])
def delete_survey(survey_id):
    """删除问卷"""
    guard = ensure_admin_session()
    if guard:
        return guard
    
    survey = Survey.query.get_or_404(survey_id)
    
    try:
        Vote.query.filter(Vote.question.has(survey_id=survey_id)).delete(synchronize_session='fetch')
        Question.query.filter_by(survey_id=survey_id).delete(synchronize_session='fetch')
        TableRespondent.query.filter_by(survey_id=survey_id).delete(synchronize_session='fetch')
        QRCode.query.filter_by(survey_id=survey_id).delete(synchronize_session='fetch')
        
        db.session.delete(survey)
        db.session.commit()
        flash(f'问卷 "{survey.name}" 及其所有相关数据已删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除问卷失败: {e}', 'danger')
        
    return redirect(url_for('votesite.admin'))

@votesite_bp.route('/admin/edit_survey_title/<int:survey_id>', methods=['POST'])
def edit_survey_title(survey_id):
    """编辑问卷标题"""
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
    return redirect(url_for('votesite.admin'))

@votesite_bp.route('/admin/restart_server', methods=['POST'])
def restart_server():
    """重启服务器"""
    guard = ensure_admin_session()
    if guard:
        return guard
    flash('服务即将重启...', 'info')
    db.session.commit()
    dump_queue_to_log()
    os._exit(1)
    return redirect(url_for('votesite.admin'))


def init_votesite(app, login_manager_instance=None):
    """
    初始化VoteSite Blueprint
    在主应用中调用此函数来设置数据库、LoginManager等
    """
    global db, login_manager, User, Survey, Question, TableRespondent, QRCode, Vote, SubjectiveAnswer
    globals()['login_manager_instance'] = login_manager_instance
    
    # 初始化数据库配置
    database_path = os.path.join(VOTESITE_DIR, 'instance', 'votes.db')
    os.makedirs(os.path.dirname(database_path), exist_ok=True)
    
    app.config.setdefault('SQLALCHEMY_DATABASE_URI', f'sqlite:///{database_path}')
    app.config.setdefault('SQLALCHEMY_TRACK_MODIFICATIONS', False)
    app.config.setdefault('VOTESITE_ADMIN_GATE_KEY', 'wzkjgz')
    
    # 初始化SQLAlchemy
    db = SQLAlchemy(app)
    
    # 定义数据模型
    class User(UserMixin, db.Model):
        __tablename__ = 'user'
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
        __tablename__ = 'survey'
        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(200), nullable=False)
        type = db.Column(db.String(20), nullable=False)
        introduction = db.Column(db.Text, nullable=True)
        subjective_question_prompt = db.Column(db.Text, nullable=True)
        created_at = db.Column(db.DateTime, default=get_current_time)
        is_active = db.Column(db.Boolean, default=True)
        option_limits = db.Column(db.JSON, nullable=True)
        table_option_count = db.Column(db.Integer, default=3)
        questions = db.relationship('Question', backref='survey', lazy=True)
        qr_codes = db.relationship('QRCode', backref='survey', lazy=True)
    
    class Question(db.Model):
        __tablename__ = 'question'
        id = db.Column(db.Integer, primary_key=True)
        survey_id = db.Column(db.Integer, db.ForeignKey('survey.id'), nullable=False)
        content = db.Column(db.Text, nullable=False)
        option_count = db.Column(db.Integer, nullable=True)
        created_at = db.Column(db.DateTime, default=get_current_time)
        votes = db.relationship('Vote', backref='question', lazy=True)
    
    class TableRespondent(db.Model):
        __tablename__ = 'table_respondent'
        id = db.Column(db.Integer, primary_key=True)
        survey_id = db.Column(db.Integer, db.ForeignKey('survey.id'), nullable=False)
        name = db.Column(db.String(100), nullable=False)
        created_at = db.Column(db.DateTime, default=get_current_time)
        survey = db.relationship('Survey', backref='table_respondents', lazy=True)
    
    class QRCode(db.Model):
        __tablename__ = 'qr_code'
        id = db.Column(db.Integer, primary_key=True)
        survey_id = db.Column(db.Integer, db.ForeignKey('survey.id'), nullable=False)
        token = db.Column(db.String(200), unique=True, nullable=False)
        is_used = db.Column(db.Boolean, default=False)
        created_at = db.Column(db.DateTime, default=get_current_time)
    
    class Vote(db.Model):
        __tablename__ = 'vote'
        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
        question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
        table_respondent_id = db.Column(db.Integer, db.ForeignKey('table_respondent.id'), nullable=True)
        score = db.Column(db.Text, nullable=False)
        created_at = db.Column(db.DateTime, default=get_current_time)
        table_respondent = db.relationship('TableRespondent', backref='votes', lazy=True)
    
    class SubjectiveAnswer(db.Model):
        __tablename__ = 'subjective_answer'
        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
        survey_id = db.Column(db.Integer, db.ForeignKey('survey.id'), nullable=False)
        content = db.Column(db.Text, nullable=True)
        created_at = db.Column(db.DateTime, default=get_current_time)
    
    # 将模型赋值给全局变量
    User = User
    Survey = Survey
    Question = Question
    TableRespondent = TableRespondent
    QRCode = QRCode
    Vote = Vote
    SubjectiveAnswer = SubjectiveAnswer
    
    # 使用传入的LoginManager实例（在主应用中统一管理）
    if login_manager_instance:
        login_manager = login_manager_instance
        login_manager.login_view = 'votesite.index'
    else:
        # 如果没有传入，创建新的（向后兼容）
        login_manager = LoginManager()
        login_manager.init_app(app)
        login_manager.login_view = 'votesite.index'
        
        @login_manager.user_loader
        def load_user(user_id):
            return db.session.get(User, int(user_id))
    
    # 注意：user_loader将在主应用中统一设置，支持多系统用户
    
    # 创建数据库表
    with app.app_context():
        db.create_all()
        
        # 创建管理员账号
        if not User.query.filter_by(username='wzkjgz').first():
            admin = User(
                username='wzkjgz',
                password_hash=generate_password_hash('wzkjgz123!'),
                is_admin=True
            )
            db.session.add(admin)
            db.session.commit()
    
    # 启动数据库写入工作线程
    threading.Thread(target=lambda: db_worker(app), daemon=True).start()
    
    logger.info("VoteSite Blueprint 初始化完成")

