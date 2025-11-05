from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit
import csv
import os
from threading import Lock
import jieba
#https://cloud.siliconflow.cn/me/models
# 教师预设提示词，可以用于所有API或问答前缀！！！！！！！！！！！！！！！！！！！！！！！！！！
TEACHER_PROMPT = ""#"不要直接生成代码，引导学生设计代码思路"
api_key = "sk-umilnkttpklmtmhflxkhhdhcyvmexzkszqltioezntndywhd"  # 你的token
model="deepseek-ai/DeepSeek-V2.5"
#model="Qwen/Qwen2.5-Coder-7B-Instruct"
#deepseek-ai/DeepSeek-R1-0528-Qwen3-8B
# 教师预设提示词，可以用于所有API或问答前缀！！！！！！！！！！！！！！！！！！！！！！！！！！
from openai import OpenAI
app = Flask(__name__, static_folder='static', template_folder='templates')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")
csv_lock = Lock()

CSV_FILE = 'questions.csv'

# 确保CSV存在且有表头
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['IP', '总提问次数'])


def get_user_ip():
    if request.headers.get('X-Forwarded-For'):
        ip = request.headers.get('X-Forwarded-For').split(',')[0].strip()
    else:
        ip = request.remote_addr
    return ip

# 辅助: 读写csv，线程安全

def read_all_csv():
    with csv_lock:
        with open(CSV_FILE, 'r', encoding='utf-8') as f:
            csv_reader = list(csv.reader(f))
    return csv_reader

def write_all_csv(rows):
    with csv_lock:
        with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerows(rows)

@app.route('/')
def chat():
    return render_template('chat.html')

@app.route('/view')
def view():
    return render_template('view.html')

@app.route('/api/ask', methods=['POST'])
def api_ask():
    data = request.get_json()
    question = data.get('question', '').strip()
    if not question:
        return jsonify({'msg': '问题不能为空'}), 400
    ip = get_user_ip()

    rows = read_all_csv()
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
    write_all_csv([header] + rows[1:])
    return jsonify({'msg': '提交成功'})

@app.route('/api/newtopic', methods=['POST'])
def api_newtopic():
    ip = get_user_ip()
    rows = read_all_csv()
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
    write_all_csv(rows)
    return jsonify({'msg': '新话题已开启'})

@app.route('/api/view_data')
def api_view_data():
    rows = read_all_csv()
    header = rows[0]
    data = []
    for row in rows[1:]:
        ip = row[0]
        count = row[1] if len(row)>1 else '0'
        last_q = row[-1] if len(row)>2 else ''
        data.append({'ip':ip, 'count':count, 'last':last_q})
    return jsonify({'users': data})

@app.route('/api/wordcloud_data')
def api_wordcloud_data():
    rows = read_all_csv()
    all_words = []
    for row in rows[1:]:
        for sent in row[2:]:
            sent = sent.strip()
            if sent:
                # 精确分词，排除长度为1的词
                words = [w for w in jieba.cut(sent, cut_all=False) if len(w.strip()) > 1]
                all_words.extend(words)
    return jsonify({'words': all_words})

@app.route('/api/reset_csv', methods=['POST'])
def reset_csv():
    header = ['IP', '总提问次数', '问题1']
    demo_row = ['192.168.0.87', '1', '算法']
    write_all_csv([header, demo_row])
    return jsonify({'msg': '重置完成'})

@socketio.on('ask')
def on_ask(data):
    user_question = data.get('message', '')
    use_model = data.get('model') or model
    ip = request.remote_addr

    # 写入CSV（与 /api/ask 同步）
    rows = read_all_csv()
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
    write_all_csv([header] + rows[1:])

    # 简化多轮：检索历史所有问题
    user_row = None
    for row in rows[1:]:
        if row[0] == ip:
            user_row = row
            break
    history_questions = user_row[2:] if user_row else []
    messages = [{"role": "system", "content": TEACHER_PROMPT}]
    for q in history_questions:
        messages.append({"role": "user", "content": q})
    messages.append({"role": "user", "content": user_question})
    client = OpenAI(
        base_url='https://api.siliconflow.cn/v1',
        api_key=api_key
    )
    try:
        response = client.chat.completions.create(
            model=use_model,
            messages=messages,
            stream=True
        )
        for chunk in response:
            if not chunk.choices:
                continue
            if chunk.choices[0].delta.content:
                emit('bot_stream', {'token': chunk.choices[0].delta.content}, namespace='/', broadcast=False)
            if getattr(chunk.choices[0].delta, "reasoning_content", None):
                emit('bot_stream', {'token': chunk.choices[0].delta.reasoning_content}, namespace='/', broadcast=False)
        emit('bot_stream', {'token': '[END]'}, namespace='/', broadcast=False)
    except Exception as e:
        emit('bot_stream', {'token': f"\n[API错误: {e} ]"}, namespace='/', broadcast=False)
        emit('bot_stream', {'token': '[END]'}, namespace='/', broadcast=False)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
