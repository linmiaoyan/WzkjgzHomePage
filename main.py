from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
from flask_socketio import SocketIO
import datetime
import random
import os
import sys
from functools import lru_cache

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # 设置session密钥
socketio = SocketIO(app, cors_allowed_origins="*")

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
init_quickform(app, login_manager)
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
    # 直接获取今日安保码并存入session，无需密码验证
    today_code = get_today_security_code()
    session['security_code'] = today_code
    session['access_time'] = datetime.datetime.now().isoformat()
    return render_template('show_security_code.html', security_code=today_code, access_time=session['access_time'])



if __name__ == '__main__':
    # 生产环境配置
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    socketio.run(app, host='0.0.0.0', port=80, debug=debug_mode)