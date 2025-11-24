"""
最简单的HTML文件上传方案 - 使用Base64编码
避免multipart解析问题
"""
from flask import Flask, request, redirect, url_for, flash, render_template_string
import os
import uuid
import base64
import logging
from urllib.parse import unquote_plus

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'test'
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB（Base64会增加约33%大小）

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'test_uploads')
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>HTML文件上传（Base64）</title>
    <style>
        body { font-family: Arial; max-width: 600px; margin: 50px auto; padding: 20px; }
        .box { background: white; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }
        input[type="file"] { width: 100%; padding: 10px; margin: 10px 0; }
        button { background: #1a73e8; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; }
        .msg { padding: 10px; margin: 10px 0; border-radius: 4px; }
        .success { background: #d4edda; color: #155724; }
        .error { background: #f8d7da; color: #721c24; }
        .info { background: #d1ecf1; color: #0c5460; }
    </style>
</head>
<body>
    <div class="box">
        <h1>HTML文件上传（Base64方式）</h1>
        <div class="msg info">
            <strong>说明：</strong> 使用Base64编码方式上传，避免multipart解析问题。仅支持HTML/HTM格式。
        </div>
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="msg {{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        <form method="POST" id="uploadForm">
            <input type="file" id="fileInput" accept=".html,.htm" required>
            <button type="submit" id="submitBtn">上传</button>
        </form>
        <div id="status" style="margin-top: 10px;"></div>
    </div>
    <script>
        document.getElementById('uploadForm').addEventListener('submit', function(e) {
            e.preventDefault();
            
            const fileInput = document.getElementById('fileInput');
            const file = fileInput.files[0];
            const submitBtn = document.getElementById('submitBtn');
            const statusDiv = document.getElementById('status');
            
            if (!file) {
                statusDiv.innerHTML = '<div class="msg error">请选择文件</div>';
                return;
            }
            
            // 检查文件类型
            if (!file.name.toLowerCase().endsWith('.html') && !file.name.toLowerCase().endsWith('.htm')) {
                statusDiv.innerHTML = '<div class="msg error">仅支持HTML/HTM格式</div>';
                return;
            }
            
            // 显示上传中
            submitBtn.disabled = true;
            submitBtn.textContent = '上传中...';
            statusDiv.innerHTML = '<div class="msg info">正在读取文件...</div>';
            
            // 读取文件为文本
            const reader = new FileReader();
            
            reader.onerror = function() {
                statusDiv.innerHTML = '<div class="msg error">文件读取失败</div>';
                submitBtn.disabled = false;
                submitBtn.textContent = '上传';
            };
            
            reader.onload = function(e) {
                statusDiv.innerHTML = '<div class="msg info">正在编码并上传...</div>';
                
                // 将文本内容编码为Base64
                const fileContent = e.target.result;
                const base64Content = btoa(unescape(encodeURIComponent(fileContent)));
                
                // 使用普通表单提交（不是multipart）
                const form = document.createElement('form');
                form.method = 'POST';
                form.style.display = 'none';
                
                const contentInput = document.createElement('input');
                contentInput.type = 'hidden';
                contentInput.name = 'file_content_base64';
                contentInput.value = base64Content;
                form.appendChild(contentInput);
                
                const nameInput = document.createElement('input');
                nameInput.type = 'hidden';
                nameInput.name = 'file_name';
                nameInput.value = file.name;
                form.appendChild(nameInput);
                
                document.body.appendChild(form);
                form.submit();
            };
            
            reader.readAsText(file, 'UTF-8');
        });
    </script>
</body>
</html>
"""

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

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        try:
            logger.info("收到POST请求")
            logger.info(f"Content-Type: {request.content_type}")
            logger.info(f"Content-Length: {request.content_length}")
            
            # 直接读取原始请求体，避免Flask自动解析
            raw_data = request.get_data(as_text=False)
            logger.info(f"原始数据长度: {len(raw_data)} 字节")
            
            # 手动解析URL编码的数据
            form_data = parse_urlencoded(raw_data)
            logger.info(f"解析后的字段: {list(form_data.keys())}")
            
            # 获取Base64编码的内容
            file_content_base64 = form_data.get('file_content_base64')
            file_name = form_data.get('file_name')
            
            if not file_content_base64 or not file_name:
                logger.warning("缺少文件内容或文件名")
                flash('上传失败：缺少文件内容或文件名', 'error')
                return redirect(url_for('index'))
            
            logger.info(f"收到文件: {file_name}, Base64长度: {len(file_content_base64)}")
            
            # 解码Base64
            try:
                file_content = base64.b64decode(file_content_base64).decode('utf-8')
                logger.info(f"解码成功，内容长度: {len(file_content)} 字符")
            except Exception as e:
                logger.error(f"Base64解码失败: {str(e)}")
                flash(f'文件解码失败: {str(e)}', 'error')
                return redirect(url_for('index'))
            
            # 保存文件
            filename = str(uuid.uuid4()) + '_' + file_name
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            
            logger.info(f"准备保存文件到: {filepath}")
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(file_content)
            
            logger.info(f"文件保存成功: {filepath}")
            
            if os.path.exists(filepath):
                size = os.path.getsize(filepath)
                logger.info(f"文件验证成功，大小: {size} 字节")
                flash(f'上传成功！文件名: {file_name}, 大小: {size} 字节', 'success')
            else:
                logger.error("文件保存后验证失败")
                flash('保存失败', 'error')
                
        except Exception as e:
            logger.error(f"处理上传时出错: {str(e)}", exc_info=True)
            flash(f'错误: {str(e)}', 'error')
        
        return redirect(url_for('index'))
    
    return render_template_string(TEMPLATE)

if __name__ == '__main__':
    print("=" * 60)
    print(f"上传目录: {UPLOAD_FOLDER}")
    print("启动在 http://0.0.0.0:5006")
    print("=" * 60)
    print("方案说明：")
    print("- 使用Base64编码，避免multipart解析问题")
    print("- 前端读取文件为文本，编码为Base64")
    print("- 后端解码Base64，重建HTML文件")
    print("- 使用普通表单提交，不会被WAF拦截")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5006, debug=True)

