# ==================== 数据库配置 ====================
# 选择数据库类型: 'sqlite' 或 'mysql'
# 'sqlite' - 使用SQLite数据库（quickform.db文件）
# 'mysql' - 使用MySQL数据库（需要配置环境变量：MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE）
# 
# 回滚说明：
# 如果MySQL相关功能出错，只需将下面的值改回 'sqlite' 即可回滚到SQLite数据库
# 修改后重启应用即可，无需其他操作
# 
QUICKFORM_DATABASE_TYPE = 'mysql'  # 默认使用SQLite
# ====================================================

from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, make_response
from flask_socketio import SocketIO
import datetime
import random
import os
import sys
import secrets
import logging
from functools import lru_cache

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # 设置session密钥
# 设置最大文件上传大小为16MB
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
socketio = SocketIO(app, cors_allowed_origins="*")

# 添加全局响应头处理器，确保所有响应都使用UTF-8编码
@app.after_request
def after_request(response):
    # 确保所有响应都包含正确的字符集信息
    if 'Content-Type' in response.headers:
        content_type = response.headers['Content-Type']
        if content_type.startswith('text/') or content_type.startswith('application/json'):
            if 'charset' not in content_type:
                response.headers['Content-Type'] = content_type + '; charset=utf-8'
    else:
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response

# 添加QuickForm路径到sys.path
quickform_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'QuickForm')
if quickform_path not in sys.path:
    sys.path.insert(0, quickform_path)

# 初始化Flask-Login（在主应用层面统一管理）
from flask_login import LoginManager
login_manager = LoginManager()
login_manager.init_app(app)

# 导入并注册QuickForm Blueprint
from QuickForm.blueprint import quickform_bp, init_quickform
init_quickform(app, login_manager, database_type=QUICKFORM_DATABASE_TYPE)
# 在init之后导入User和SessionLocal
from QuickForm.blueprint import SessionLocal, User as QuickFormUser

# 添加VoteSite路径到sys.path
votesite_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Votesite')
if votesite_path not in sys.path:
    sys.path.insert(0, votesite_path)

# 导入并注册VoteSite Blueprint
from blueprint import votesite_bp, init_votesite
init_votesite(app, login_manager)
# 添加ChatServer路径到sys.path
chatserver_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ChatServer')
if chatserver_path not in sys.path:
    sys.path.insert(0, chatserver_path)

# 导入并注册ChatServer Blueprint
from ChatServer.blueprint import chat_server_bp, register_socketio
app.register_blueprint(chat_server_bp, url_prefix='/chat_server')
# 注册 ChatServer 的 SocketIO 事件
register_socketio(socketio)

# ChatServer 默认配置（可通过环境变量覆盖）
app.config.setdefault('CHAT_SERVER_API_URL', os.environ.get('CHAT_SERVER_API_URL', ''))
app.config.setdefault('CHAT_SERVER_API_TOKEN', os.environ.get('CHAT_SERVER_API_TOKEN', ''))
# 未来正式域名配置（启用后取消注释）
# app.config['CHAT_SERVER_API_URL'] = 'https://wzkjgz.site/api/chat'
# app.config['CHAT_SERVER_API_TOKEN'] = 'YOUR_DEFAULT_TOKEN'

# 确保有默认 Token（从独立服务迁移），避免未配置导致调用失败
default_token = 'sk-umilnkttpklmtmhflxkhhdhcyvmexzkszqltioezntndywhd'
if not app.config.get('CHAT_SERVER_API_TOKEN'):
    # 独立服务中的默认 Token（如需更换请在环境变量或此处配置）
    app.config['CHAT_SERVER_API_TOKEN'] = default_token
# 同时设置到环境变量，确保后台线程也能访问
if not os.environ.get('CHAT_SERVER_API_TOKEN'):
    os.environ['CHAT_SERVER_API_TOKEN'] = default_token


# 获取VoteSite的User模型（需要在init_votesite之后）
from blueprint import User as VoteSiteUser, db as votesite_db

# 设置统一的user_loader，支持两个系统的用户
@login_manager.user_loader
def load_user(user_id):
    """
    统一的user_loader，尝试从QuickForm和VoteSite两个系统加载用户
    优先检查QuickForm，如果不存在则检查VoteSite
    """
    try:
        # 首先尝试从QuickForm加载
        db = SessionLocal()
        try:
            user = db.get(QuickFormUser, int(user_id))
            if user:
                return user
        finally:
            db.close()
        
        # 如果QuickForm中没有，尝试从VoteSite加载
        try:
            user = votesite_db.session.get(VoteSiteUser, int(user_id))
            if user:
                return user
        except:
            pass
    except:
        pass
    return None

# 注册Blueprint
app.register_blueprint(quickform_bp, url_prefix='/quickform')
app.register_blueprint(votesite_bp, url_prefix='/votesite')
# ScoreAnalysis已在init_score_analysis中注册

# 确保templates文件夹存在
templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
if not os.path.exists(templates_dir):
    os.makedirs(templates_dir)

# 确保static文件夹存在
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

# 确保static子目录存在
static_css_dir = os.path.join(static_dir, 'css')
static_js_dir = os.path.join(static_dir, 'js')
if not os.path.exists(static_css_dir):
    os.makedirs(static_css_dir)
if not os.path.exists(static_js_dir):
    os.makedirs(static_js_dir)

# 提供favicon.ico
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

# 模拟数据库存储每日安保码
daily_security_code = {}

# 生成今日的安保码（添加缓存）
@lru_cache(maxsize=1)
def get_today_security_code():
    today = datetime.date.today().isoformat()
    # 检查是否已为今天生成了安保码
    if today not in daily_security_code:
        # 生成6位随机数字码
        daily_security_code[today] = ''.join([str(random.randint(0, 9)) for _ in range(6)])
    return daily_security_code[today]

@app.route('/')
def index():
    return render_template('index.html')

# QuickForm主页路由 - 重定向到Blueprint的首页
@app.route('/quickform')
def quickform():
    """QuickForm主页路由（重定向）"""
    return redirect(url_for('quickform.index'))

# VoteSite主页路由 - 进入首页（会自动跳转到管理员页面如果是管理员）
@app.route('/votesite')
def votesite():
    """VoteSite主页路由"""
    return redirect(url_for('votesite.index'))

# 新增anfang路由，直接提供安保码
@app.route('/anfang')
def anfang():
    # 首次部署随机生成安保码（32位）
    key = secrets.token_urlsafe(32)
    response = make_response(key)
    response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    return response

# 配置日志过滤器，过滤掉常见的扫描和攻击尝试
class SecurityScanFilter(logging.Filter):
    """过滤掉常见的端口扫描和安全扫描日志"""
    def filter(self, record):
        # 过滤掉常见的扫描请求
        if hasattr(record, 'getMessage'):
            msg = record.getMessage()
            # 过滤RTSP协议请求
            if 'RTSP/1.0' in msg or 'Bad request version' in msg:
                return False
            # 过滤无效HTTP请求
            if 'Bad HTTP/0.9 request type' in msg:
                return False
            # 过滤TLS/SSL握手尝试（二进制数据）
            if 'Bad request version' in msg and '\\x' in msg:
                return False
        return True

# 配置Flask的日志，过滤掉扫描请求
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.addFilter(SecurityScanFilter())

# 全局错误处理
@app.errorhandler(400)
def bad_request(error):
    """处理400错误，静默处理扫描请求"""
    # 检查是否是常见的扫描请求
    if request and hasattr(request, 'environ'):
        user_agent = request.environ.get('HTTP_USER_AGENT', '')
        # 如果是明显的扫描工具，返回简单响应
        if not user_agent or len(user_agent) < 5:
            return '', 400
    return 'Bad Request', 400

@app.errorhandler(413)
def request_entity_too_large(error):
    """处理413错误（请求实体过大）- 通常是反向代理限制"""
    app.logger.warning(f"413错误 - 请求实体过大，路径: {request.path if request else '未知'}, "
                     f"Content-Length: {request.headers.get('Content-Length', '未知') if request else '未知'}")
    if request and request.path.startswith('/quickform'):
        from flask import flash, redirect, url_for
        flash('文件上传失败：文件大小超过服务器限制。请检查反向代理（如Nginx）的client_max_body_size配置，建议设置为至少20M。', 'danger')
        if request.path.startswith('/quickform/create_task'):
            return redirect(url_for('quickform.create_task'))
        elif '/edit_task' in request.path:
            # 尝试从路径中提取task_id
            try:
                task_id = int(request.path.split('/edit_task/')[1].split('/')[0])
                return redirect(url_for('quickform.edit_task', task_id=task_id))
            except:
                return redirect(url_for('quickform.dashboard'))
    return 'Request Entity Too Large', 413

@app.errorhandler(404)
def not_found(error):
    """处理404错误，避免后台线程中的静态文件请求错误"""
    # 检查是否在请求上下文中
    try:
        if request and hasattr(request, 'path'):
            path = request.path
            # 如果是静态文件请求但文件不存在，静默处理
            if path.startswith('/static/') or path.startswith('/favicon.ico'):
                return '', 404
            # 如果是其他404，静默处理
            if not path.startswith('/quickform/api/'):  # API请求的404不记录
                pass
    except RuntimeError:
        # 在请求上下文外（如后台线程），静默处理
        pass
    return 'Not Found', 404

@app.errorhandler(ConnectionResetError)
def handle_connection_reset(error):
    """处理连接重置错误，静默记录"""
    # 连接重置通常是客户端断开，不需要记录为错误
    return '', 200

@app.errorhandler(Exception)
def handle_exception(error):
    """全局异常处理"""
    # 检查是否是404错误（NotFound）
    from werkzeug.exceptions import NotFound
    if isinstance(error, NotFound):
        # 404错误已经在not_found处理器中处理，这里静默处理
        try:
            if request and hasattr(request, 'path'):
                path = request.path
                # 静态文件或favicon的404不记录为错误
                if path.startswith('/static/') or path.startswith('/favicon.ico'):
                    return '', 404
        except RuntimeError:
            # 在请求上下文外，静默处理
            pass
        return 'Not Found', 404
    
    # 记录真正的错误
    app.logger.error(f'未处理的异常: {str(error)}', exc_info=True)
    return 'Internal Server Error', 500

if __name__ == '__main__':
    # 生产环境配置
    #debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'false'

    socketio.run(app, host='0.0.0.0', port=80, debug=debug_mode)