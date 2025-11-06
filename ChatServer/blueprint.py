import os
import csv
import threading
import jieba
from flask import Blueprint, render_template, request, jsonify, current_app, redirect, url_for
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

chat_server_bp = Blueprint(
    'chat_server',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/chat_server/static'
)

# CSV 存储（与独立服务保持一致）
CSV_FILE = os.path.join(os.path.dirname(__file__), 'questions.csv')
_csv_lock = threading.Lock()

if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['IP', '总提问次数'])

def _read_all_csv():
    with _csv_lock:
        with open(CSV_FILE, 'r', encoding='utf-8') as f:
            rows = list(csv.reader(f))
    return rows

def _write_all_csv(rows):
    with _csv_lock:
        with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerows(rows)

@chat_server_bp.route('/')
def index():
    # 默认直接进入聊天界面
    return redirect(url_for('chat_server.chat'))

@chat_server_bp.route('/chat')
def chat():
    # 渲染已有的 chat.html 模板
    return render_template('chat.html')

@chat_server_bp.route('/view')
def view():
    # 渲染教师端监控与词云页面
    return render_template('view.html')

@chat_server_bp.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.get_json() or {}
    messages = data.get('messages') or []

    # 统一对接配置（外部大模型服务地址）
    api_url = (current_app.config.get('CHAT_SERVER_API_URL', '') or '').strip()
    api_token = (current_app.config.get('CHAT_SERVER_API_TOKEN', '') or '').strip()
    # 未来域名（wzkjgz.site）示例：
    # api_url = 'https://wzkjgz.site/api/chat'  # TODO: 启用后取消注释
    # api_token = 'YOUR_DEFAULT_TOKEN'          # TODO: 启用后取消注释

    # 强制要求已配置上游API与token
    if not api_url or not api_token:
        response = jsonify({'error': '未配置上游API或Token，请联系管理员配置 CHAT_SERVER_API_URL/CHAT_SERVER_API_TOKEN'})
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response, 500

    try:
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_token}'
        }
        # 带重试的 Session，提高调用稳定性
        session = requests.Session()
        retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["POST"]) 
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        # 分离连接/读取超时
        resp = session.post(api_url, json={'messages': messages}, headers=headers, timeout=(5, 60))
        try:
            data = resp.json()
        except ValueError:
            data = {'error': '上游返回非JSON响应', 'raw': (resp.text[:500] if resp.text else '')}
        return jsonify(data), resp.status_code
    except requests.Timeout as e:
        response = jsonify({'error': '上游超时', 'message': str(e)})
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response, 504
    except requests.RequestException as e:
        response = jsonify({'error': '上游网络错误', 'message': str(e)})
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response, 502

# 兼容独立服务的其余 API（HTTP 版本，无 SocketIO）
@chat_server_bp.route('/api/ask', methods=['POST'])
def api_ask():
    data = request.get_json() or {}
    question = (data.get('question') or '').strip()
    if not question:
        response = jsonify({'msg': '问题不能为空'})
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response, 400
    ip = request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or request.remote_addr

    rows = _read_all_csv()
    header = rows[0]
    user_row = None
    for row in rows[1:]:
        if row[0] == ip:
            user_row = row
            break
    if user_row:
        user_row[1] = str(int(user_row[1]) + 1)
        user_row.append(question)
    else:
        user_row = [ip, '1', question]
        rows.append(user_row)
    _write_all_csv([header] + rows[1:])
    response = jsonify({'msg': '提交成功'})
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    return response

@chat_server_bp.route('/api/newtopic', methods=['POST'])
def api_newtopic():
    ip = request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or request.remote_addr
    rows = _read_all_csv()
    header = rows[0]
    user_index = None
    for i, row in enumerate(rows[1:], start=1):
        if row[0] == ip:
            user_index = i
            break
    if user_index:
        rows[user_index] = [ip, '0']
    else:
        rows.append([ip, '0'])
    _write_all_csv(rows)
    response = jsonify({'msg': '新话题已开启'})
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    return response

@chat_server_bp.route('/api/view_data')
def api_view_data():
    rows = _read_all_csv()
    header = rows[0]
    data = []
    for row in rows[1:]:
        ip = row[0]
        count = row[1] if len(row) > 1 else '0'
        last_q = row[-1] if len(row) > 2 else ''
        data.append({'ip': ip, 'count': count, 'last': last_q})
    response = jsonify({'users': data})
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    return response

@chat_server_bp.route('/api/wordcloud_data')
def api_wordcloud_data():
    rows = _read_all_csv()
    all_words = []
    for row in rows[1:]:
        for sent in row[2:]:
            sent = (sent or '').strip()
            if sent:
                words = [w for w in jieba.cut(sent, cut_all=False) if len(w.strip()) > 1]
                all_words.extend(words)
    response = jsonify({'words': all_words})
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    return response

@chat_server_bp.route('/api/reset_csv', methods=['POST'])
def reset_csv():
    header = ['IP', '总提问次数', '问题1']
    demo_row = ['192.168.0.87', '1', '算法']
    _write_all_csv([header, demo_row])
    response = jsonify({'msg': '重置完成'})
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    return response

# ============ SocketIO 事件注册（流式输出） ============
def register_socketio(socketio):
    # 改为直接HTTP调用硅基流动，避免SDK依赖导致的Token配置误判

    @socketio.on('ask')
    def on_ask(data):
        from flask_socketio import emit
        user_question = (data.get('message') if isinstance(data, dict) else '') or ''
        use_model = (data.get('model') if isinstance(data, dict) else '') or 'deepseek-ai/DeepSeek-V2.5'
        ip = request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or request.remote_addr

        # 写CSV
        rows = _read_all_csv()
        header = rows[0]
        user_row = None
        for row in rows[1:]:
            if row[0] == ip:
                user_row = row
                break
        if user_row:
            user_row[1] = str(int(user_row[1]) + 1)
            user_row.append(user_question)
        else:
            user_row = [ip, '1', user_question]
            rows.append(user_row)
        _write_all_csv([header] + rows[1:])

        # 构造多轮历史
        rows = _read_all_csv()
        user_row = None
        for row in rows[1:]:
            if row[0] == ip:
                user_row = row
                break
        history_questions = user_row[2:] if user_row else []
        messages = []
        teacher_prompt = (current_app.config.get('CHAT_SERVER_TEACHER_PROMPT') or '')
        if teacher_prompt:
            messages.append({"role": "system", "content": teacher_prompt})
        for q in history_questions:
            messages.append({"role": "user", "content": q})
        messages.append({"role": "user", "content": user_question})

        # 走硅基流动 API（HTTP）
        api_key = (current_app.config.get('CHAT_SERVER_API_TOKEN') or os.environ.get('CHAT_SERVER_API_TOKEN') or '').strip()
        if not api_key:
            emit('bot_stream', {'token': '错误：未配置硅基流动 API Token，请联系管理员完成配置。'})
            emit('bot_stream', {'token': '[END]'})
            return
        try:
            import requests as _requests
            url = 'https://api.siliconflow.cn/v1/chat/completions'
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}'
            }
            payload = {
                'model': use_model,
                'messages': messages
            }
            resp = _requests.post(url, headers=headers, json=payload, timeout=(5, 120))
            if resp.status_code != 200:
                emit('bot_stream', {'token': f"[API错误 HTTP {resp.status_code}] {resp.text[:200]}"})
                emit('bot_stream', {'token': '[END]'})
                return
            data = resp.json()
            content = ''
            if isinstance(data, dict) and data.get('choices'):
                choice = data['choices'][0]
                content = (choice.get('message') or {}).get('content') or choice.get('text') or ''
            if content:
                emit('bot_stream', {'token': content})
            else:
                emit('bot_stream', {'token': '[空响应]'} )
            emit('bot_stream', {'token': '[END]'})
        except Exception as e:
            emit('bot_stream', {'token': f"\n[API错误: {e} ]"})
            emit('bot_stream', {'token': '[END]'})