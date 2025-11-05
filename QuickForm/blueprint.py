"""
QuickForm Blueprint
将QuickForm改造为Blueprint，可以整合到主应用中
"""
import os
import json
import requests
import threading
import time
import urllib.parse
import traceback
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, make_response, send_file, send_from_directory, current_app
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
import uuid
from datetime import datetime
import pandas as pd
import io
import base64
import matplotlib
matplotlib.use('Agg')  # 使用非交互式后端
import matplotlib.pyplot as plt
from dotenv import load_dotenv
import logging
from functools import wraps

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

# 允许的文件扩展名
ALLOWED_EXTENSIONS = {'pdf', 'html', 'htm', 'jpg', 'zip'}

# 数据库配置（相对于QuickForm目录）
DATABASE_URL = f'sqlite:///{os.path.join(QUICKFORM_DIR, "quickform.db")}'

# 初始化SQLAlchemy
engine = create_engine(DATABASE_URL, connect_args={'check_same_thread': False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 用于存储分析任务进度的字典
analysis_progress = {}
analysis_results = {}
completed_reports = set()
progress_lock = threading.Lock()

# 全局变量（将在init函数中设置）
bcrypt = None
login_manager = None

# 数据库模型
class User(UserMixin, Base):
    __tablename__ = 'user'
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    password = Column(String(200), nullable=False)
    school = Column(String(200))
    phone = Column(String(20))
    role = Column(String(20), default='user')
    created_at = Column(DateTime, default=datetime.now)
    tasks = relationship('Task', back_populates='author')
    ai_config = relationship('AIConfig', back_populates='user', uselist=False)
    
    def is_admin(self):
        """检查用户是否为管理员"""
        return self.role == 'admin'

class Task(Base):
    __tablename__ = 'task'
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    user_id = Column(Integer, ForeignKey('user.id'))
    author = relationship('User', back_populates='tasks')
    submission = relationship('Submission', back_populates='task', cascade='all, delete-orphan')
    file_name = Column(String(200))
    file_path = Column(String(500))
    task_id = Column(String(50), unique=True, default=lambda: str(uuid.uuid4()))
    analysis_report = Column(Text)
    report_file_path = Column(String(500))
    report_generated_at = Column(DateTime)

class Submission(Base):
    __tablename__ = 'submission'
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey('task.id'))
    task = relationship('Task', back_populates='submission')
    data = Column(Text, nullable=False)
    submitted_at = Column(DateTime, default=datetime.now)

class AIConfig(Base):
    __tablename__ = 'ai_config'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'), unique=True)
    user = relationship('User', back_populates='ai_config')
    selected_model = Column(String(50), default='deepseek')
    deepseek_api_key = Column(String(200))
    doubao_api_key = Column(String(200))
    doubao_secret_key = Column(String(200))
    qwen_api_key = Column(String(200))
    # 硅基流动（ChatServer）配置
    chat_server_api_url = Column(String(200))
    chat_server_api_token = Column(String(200))

# 创建Blueprint
quickform_bp = Blueprint(
    'quickform',
    __name__,
    template_folder='templates',
    static_folder='../static'  # 指向主应用的static目录
)

# 创建数据库表
Base.metadata.create_all(engine)

# 数据库迁移函数
def migrate_user_table():
    """为现有User表添加school、phone和role字段"""
    try:
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('user')]
        ai_cfg_cols = [col['name'] for col in inspector.get_columns('ai_config')]
        
        with engine.begin() as conn:
            if 'school' not in columns:
                try:
                    conn.execute(text("ALTER TABLE user ADD COLUMN school VARCHAR(200)"))
                    logger.info("成功添加school字段到user表")
                except Exception as e:
                    logger.warning(f"添加school字段失败（可能已存在）: {str(e)}")
            
            if 'phone' not in columns:
                try:
                    conn.execute(text("ALTER TABLE user ADD COLUMN phone VARCHAR(20)"))
                    logger.info("成功添加phone字段到user表")
                except Exception as e:
                    logger.warning(f"添加phone字段失败（可能已存在）: {str(e)}")
            
            if 'role' not in columns:
                try:
                    conn.execute(text("ALTER TABLE user ADD COLUMN role VARCHAR(20) DEFAULT 'user'"))
                    conn.execute(text("UPDATE user SET role = 'user' WHERE role IS NULL"))
                    logger.info("成功添加role字段到user表")
                except Exception as e:
                    logger.warning(f"添加role字段失败（可能已存在）: {str(e)}")
            # ai_config 新增 chat_server 字段
            if 'chat_server_api_url' not in ai_cfg_cols:
                try:
                    conn.execute(text("ALTER TABLE ai_config ADD COLUMN chat_server_api_url VARCHAR(200)"))
                    logger.info("成功为ai_config添加chat_server_api_url")
                except Exception as e:
                    logger.warning(f"添加chat_server_api_url失败（可能已存在）: {str(e)}")
            if 'chat_server_api_token' not in ai_cfg_cols:
                try:
                    conn.execute(text("ALTER TABLE ai_config ADD COLUMN chat_server_api_token VARCHAR(200)"))
                    logger.info("成功为ai_config添加chat_server_api_token")
                except Exception as e:
                    logger.warning(f"添加chat_server_api_token失败（可能已存在）: {str(e)}")
    except Exception as e:
        logger.error(f"数据库迁移失败: {str(e)}")

# 工具函数
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_uploaded_file(file):
    """保存上传的文件"""
    try:
        if file and allowed_file(file.filename):
            unique_filename = str(uuid.uuid4()) + '_' + file.filename
            filepath = os.path.join(UPLOAD_FOLDER, unique_filename)
            file.save(filepath)
            return unique_filename, filepath
    except Exception as e:
        logger.error(f"保存文件失败: {str(e)}")
    return None, None

def read_file_content(file_path):
    """读取文件内容"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
                return f"二进制文件 (大小: {len(content)} 字节)"
        except Exception as e:
            logger.error(f"读取文件内容失败: {str(e)}")
            return f"无法读取文件内容: {str(e)}"
    except Exception as e:
        logger.error(f"读取文件内容失败: {str(e)}")
        return f"无法读取文件内容: {str(e)}"

def generate_analysis_prompt(task, submission=None, file_content=None):
    """根据任务信息生成分析提示词（优化版）"""
    if not submission:
        db = SessionLocal()
        try:
            submission = db.query(Submission).filter_by(task_id=task.id).all()
        finally:
            db.close()
    
    prompt = f"""你是一个数据分析专家，请基于以下表单数据提供详细的分析报告：

任务标题：{task.title}
任务描述：{task.description or '无'}

提交数据信息：
"""
    
    if submission:
        total_count = len(submission)
        prompt += f"总提交数量：{total_count} 条\n\n"
        
        # 解析所有数据
        all_data = []
        field_types = {}  # 字段类型统计
        field_values = {}  # 字段值统计
        
        for sub in submission:
            try:
                data = json.loads(sub.data)
                all_data.append(data)
                
                # 统计字段类型和值
                for key, value in data.items():
                    if key not in field_types:
                        field_types[key] = []
                        field_values[key] = []
                    
                    # 判断字段类型
                    if isinstance(value, (int, float)):
                        field_types[key].append('numeric')
                        field_values[key].append(value)
                    elif isinstance(value, bool):
                        field_types[key].append('boolean')
                        field_values[key].append(value)
                    else:
                        field_types[key].append('text')
                        field_values[key].append(str(value))
            except:
                pass
        
        # 添加字段统计信息
        if all_data and len(all_data) > 0:
            prompt += "数据字段统计：\n"
            for field in all_data[0].keys():
                field_type_list = field_types.get(field, [])
                if not field_type_list:
                    continue
                
                # 判断主要类型
                is_numeric = field_type_list.count('numeric') > len(field_type_list) * 0.8
                is_boolean = field_type_list.count('boolean') > len(field_type_list) * 0.8
                
                prompt += f"  - {field}: "
                if is_numeric:
                    values = [v for v in field_values[field] if isinstance(v, (int, float))]
                    if values:
                        prompt += f"数值型，范围: {min(values)} - {max(values)}，平均值: {sum(values)/len(values):.2f}\n"
                    else:
                        prompt += "数值型\n"
                elif is_boolean:
                    values = field_values[field]
                    true_count = sum(1 for v in values if v is True or str(v).lower() in ['true', '1', 'yes', '是'])
                    prompt += f"布尔型，是: {true_count}，否: {len(values)-true_count}\n"
                else:
                    # 文本型，统计常见值
                    values = field_values[field]
                    from collections import Counter
                    value_counts = Counter(values)
                    top_values = value_counts.most_common(5)
                    if len(top_values) > 0:
                        prompt += f"文本型，常见值: {', '.join([f'{k}({v}次)' for k, v in top_values[:3]])}\n"
                    else:
                        prompt += "文本型\n"
            
            prompt += "\n"
        
        # 智能采样：根据数据量决定显示多少条
        sample_size = min(20, total_count)  # 最多显示20条
        if total_count > 3:
            # 如果有大量数据，均匀采样（首、中、尾）
            if total_count <= sample_size:
                sample_indices = list(range(total_count))
            else:
                # 均匀采样：取前几条、中间几条、后几条
                sample_indices = list(range(0, min(5, total_count)))  # 前5条
                if total_count > 10:
                    mid_start = total_count // 2 - 3
                    mid_end = total_count // 2 + 3
                    sample_indices.extend(range(mid_start, mid_end))
                sample_indices.extend(range(max(0, total_count - 5), total_count))  # 后5条
                sample_indices = sorted(list(set(sample_indices)))[:sample_size]
            
            prompt += f"数据样例（共显示 {len(sample_indices)} 条，占总数的 {len(sample_indices)/total_count*100:.1f}%）：\n"
            for idx, i in enumerate(sample_indices, 1):
                try:
                    data = all_data[i]
                    prompt += f"\n样例 #{idx} (第 {i+1} 条记录):\n"
                    for key, value in data.items():
                        # 限制单个值长度，避免过长
                        value_str = str(value)
                        if len(value_str) > 100:
                            value_str = value_str[:100] + "...[截断]"
                        prompt += f"  - {key}: {value_str}\n"
                except:
                    if i < len(submission):
                        prompt += f"\n样例 #{idx}: {submission[i].data[:100]}...\n"
        else:
            # 数据量少，全部显示
            prompt += "完整数据：\n"
            for i, data in enumerate(all_data, 1):
                prompt += f"\n提交 #{i}:\n"
                for key, value in data.items():
                    value_str = str(value)
                    if len(value_str) > 100:
                        value_str = value_str[:100] + "...[截断]"
                    prompt += f"  - {key}: {value_str}\n"
    else:
        prompt += "暂无提交数据\n"
    

    prompt += """

请提供一个全面的数据分析报告，包括但不限于：
1. 数据概览：总提交量、关键数据分布、字段类型统计
2. 主要发现：数据中的趋势、模式、异常和相关性
3. 深入分析：基于数据的详细洞察，包括分布特征、集中趋势、离散程度等
4. 建议和结论：基于分析结果的实用建议和改进方向

请以中文撰写报告，使用Markdown格式，包括适当的标题、列表和表格来增强可读性。
"""
    
    return prompt

def call_ai_model(prompt, ai_config):
    """调用AI模型生成分析报告"""
    if ai_config.selected_model == 'deepseek':
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ai_config.deepseek_api_key}"
        }
        data = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "你是一个专业的数据分析助手。请基于用户提供的数据，生成一份详细、专业、有洞察力的分析报告。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 4000
        }
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=60)
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"DeepSeek API调用失败: {str(e)}")
            raise Exception(f"DeepSeek API调用失败: {str(e)}")
    
    elif ai_config.selected_model == 'doubao':
        url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ai_config.doubao_api_key}"
        }
        data = {
            "model": "doubao-seed-1-6-251015",
            "messages": [
                {"role": "system", "content": "你是一个专业的数据分析助手。请基于用户提供的数据，生成一份详细、专业、有洞察力的分析报告。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 4000
        }
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=120)
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"豆包API调用失败: {str(e)}")
            raise Exception(f"豆包API调用失败: {str(e)}")
    
    elif ai_config.selected_model == 'qwen':
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ai_config.qwen_api_key}"
        }
        data = {
            "model": "qwen-plus",
            "input": {
                "messages": [
                    {"role": "system", "content": "你是一个专业的数据分析助手。请基于用户提供的数据，生成一份详细、专业、有洞察力的分析报告。"},
                    {"role": "user", "content": prompt}
                ]
            },
            "parameters": {
                "temperature": 0.7,
                "max_tokens": 4000
            }
        }
        
        try:
            logger.info(f"调用阿里云百炼API，模型: qwen-plus")
            response = requests.post(url, headers=headers, json=data, timeout=120)
            
            if response.status_code != 200:
                raise Exception(f"阿里云百炼API调用失败，状态码: {response.status_code}，响应: {response.text[:200]}")
            
            if not response.text:
                raise Exception("阿里云百炼API返回空响应")
            
            try:
                result = response.json()
            except ValueError as ve:
                raise Exception(f"阿里云百炼API返回非JSON响应: {response.text[:200]}")
            
            if isinstance(result, dict) and "code" in result and result["code"] != "200":
                raise Exception(f"阿里云百炼API调用失败: {result.get('message', '未知错误')} (错误码: {result.get('code')})")
            
            if isinstance(result, dict):
                if "output" in result and "text" in result["output"]:
                    return result["output"]["text"]
                elif "choices" in result and len(result["choices"]) > 0:
                    choice = result["choices"][0]
                    if "message" in choice and "content" in choice["message"]:
                        return choice["message"]["content"]
                    elif "text" in choice:
                        return choice["text"]
                elif "data" in result and "choices" in result["data"] and len(result["data"]["choices"]) > 0:
                    choice = result["data"]["choices"][0]
                    if "message" in choice and "content" in choice["message"]:
                        return choice["message"]["content"]
            
            raise Exception(f"阿里云百炼API返回未知格式的响应: {str(result)[:200]}")
        except requests.exceptions.RequestException as re:
            logger.error(f"阿里云百炼API网络请求异常: {str(re)}")
            raise Exception(f"阿里云百炼API网络请求异常: {str(re)}")
        except Exception as e:
            logger.error(f"阿里云百炼API调用失败: {str(e)}")
            raise Exception(f"阿里云百炼API调用失败: {str(e)}")
    
    elif ai_config.selected_model == 'chat_server':
        # 直接调用硅基流动 OpenAI 兼容接口，避免依赖本地 HTTP 转发
        import os
        try:
            from openai import OpenAI
        except Exception:
            OpenAI = None
        # 优先使用用户配置的token，其次使用应用配置的默认token，最后使用环境变量
        api_key = ai_config.chat_server_api_token or ''
        if not api_key:
            # 尝试从应用配置获取默认token（需要在请求上下文中）
            try:
                api_key = current_app.config.get('CHAT_SERVER_API_TOKEN', '') or ''
            except RuntimeError:
                # 不在请求上下文中，无法访问current_app，跳过
                pass
        if not api_key:
            # 最后尝试从环境变量获取
            api_key = os.environ.get('CHAT_SERVER_API_TOKEN', '') or ''
        api_key = api_key.strip()
        if not OpenAI or not api_key:
            raise Exception('硅基流动未配置，请设置 CHAT_SERVER_API_TOKEN 或在配置页填写 Token')
        client = OpenAI(base_url='https://api.siliconflow.cn/v1', api_key=api_key)
        msgs = [
            {"role": "system", "content": "你是一个专业的数据分析助手。请基于用户提供的数据输出报告。"},
            {"role": "user", "content": prompt}
        ]
        try:
            result = client.chat.completions.create(
                model='deepseek-ai/DeepSeek-V2.5',
                messages=msgs
            )
            choice = result.choices[0]
            if hasattr(choice, 'message') and getattr(choice.message, 'content', None):
                return choice.message.content
            return str(result)
        except Exception as e:
            logger.error(f"硅基流动调用失败: {str(e)}")
            raise Exception(f"硅基流动调用失败: {str(e)}")
    else:
        raise Exception(f"不支持的AI模型: {ai_config.selected_model}")

def save_analysis_report(task_id, report_content):
    """保存分析报告到文件系统和数据库"""
    db = SessionLocal()
    try:
        task = db.query(Task).filter_by(id=task_id).first()
        if task:
            if not report_content or not report_content.strip():
                report_content = "<div class='alert alert-info' role='alert'><h4>报告内容为空</h4><p>本次分析未能生成有效内容。可能是由于以下原因：</p><ul><li>提交的数据量不足</li><li>数据质量问题</li><li>AI模型处理异常</li></ul><p>请尝试提交更多数据或修改提示词后重新分析。</p></div>"
            
            html_report = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>分析报告 - {task.title}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 40px 20px;
            background-color: #f8f9fa;
        }}
        .container {{
            background-color: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }}
        .markdown-body {{
            font-size: 16px;
        }}
        .markdown-body h1, .markdown-body h2, .markdown-body h3 {{
            color: #2c3e50;
        }}
        .markdown-body pre {{
            background-color: #f6f8fa;
            border-radius: 6px;
        }}
        .footer {{
            text-align: center;
            margin-top: 40px;
            padding: 20px;
            color: #6c757d;
            font-size: 0.9rem;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1 class="mb-4">数据分析报告</h1>
        <p><strong>任务标题：</strong>{task.title}</p>
        <p><strong>创建时间：</strong>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        
        <div class="markdown-body">
            {report_content}
        </div>
        
        <div class="footer">
            <p>由 QuickForm 智能分析功能生成</p>
        </div>
    </div>
</body>
</html>
            """
            
            report_dir = os.path.join(UPLOAD_FOLDER, 'reports')
            if not os.path.exists(report_dir):
                os.makedirs(report_dir)
            
            report_filename = f"report_{task_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            report_path = os.path.join(report_dir, report_filename)
            
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(html_report)
            
            task.analysis_report = report_content
            task.report_file_path = report_path
            task.report_generated_at = datetime.now()
            db.commit()
            
            with progress_lock:
                completed_reports.add(task_id)
            
            logger.info(f"任务 {task_id} 的分析报告已保存")
    except Exception as e:
        logger.error(f"保存分析报告失败: {str(e)}")
    finally:
        db.close()

def timeout(seconds, error_message="函数执行超时"):
    """超时装饰器"""
    import threading
    from functools import wraps
    
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = [None]
            exception = [None]
            
            def target():
                try:
                    result[0] = func(*args, **kwargs)
                except Exception as e:
                    exception[0] = e
            
            thread = threading.Thread(target=target)
            thread.daemon = True
            thread.start()
            thread.join(seconds)
            
            if thread.is_alive():
                raise TimeoutError(error_message)
            elif exception[0]:
                raise exception[0]
            else:
                return result[0]
        
        return wrapper
    
    return decorator

def perform_analysis_with_custom_prompt(task_id, user_id, ai_config_id, custom_prompt):
    """使用自定义提示词执行分析任务"""
    db = SessionLocal()
    try:
        task = db.query(Task).filter_by(id=task_id, user_id=user_id).first()
        if not task:
            with progress_lock:
                analysis_progress[task_id] = {
                    'status': 'error',
                    'message': '任务不存在'
                }
            return
        
        submission = db.query(Submission).filter_by(task_id=task_id).all()
        
        file_content = None
        if task.file_path and os.path.exists(task.file_path):
            file_content = read_file_content(task.file_path)
        
        ai_config = db.query(AIConfig).filter_by(id=ai_config_id).first()
        if not ai_config:
            with progress_lock:
                analysis_progress[task_id] = {
                    'status': 'error',
                    'message': 'AI配置不存在'
                }
            return
        
        if ai_config.selected_model == 'deepseek' and not ai_config.deepseek_api_key:
            with progress_lock:
                analysis_progress[task_id] = {
                    'status': 'error',
                    'message': 'DeepSeek API密钥未配置'
                }
            logging.error(f"任务 {task_id}：DeepSeek API密钥未配置")
            return
        elif ai_config.selected_model == 'doubao' and not ai_config.doubao_api_key:
            with progress_lock:
                analysis_progress[task_id] = {
                    'status': 'error',
                    'message': '豆包API密钥未配置完整'
                }
            logging.error(f"任务 {task_id}：豆包API密钥未配置完整")
            return
        
        logging.info(f"任务 {task_id}：使用模型 {ai_config.selected_model}")
        
        with progress_lock:
            analysis_progress[task_id] = {
                'status': 'in_progress',
                'progress': 0,
                'message': '正在生成提示词...'
            }
        
        prompt = custom_prompt
        
        with progress_lock:
            analysis_progress[task_id] = {
                'status': 'in_progress',
                'progress': 1,
                'message': '大模型分析中，这可能需要几分钟时间...'
            }
        logging.info(f"任务 {task_id}：调用AI模型进行分析")
        
        # 调整各模型超时，避免后端刚返回而前端已判定超时的情况
        timeout_seconds = 180 if ai_config.selected_model == 'chat_server' else (120 if ai_config.selected_model in ['deepseek', 'qwen'] else 90)
        
        @timeout(seconds=timeout_seconds, error_message=f"调用{ai_config.selected_model}模型超时（{timeout_seconds}秒）")
        def call_ai_with_timeout(prompt, config):
            logging.info(f"开始调用 {config.selected_model} API，提示词长度: {len(prompt)} 字符，超时设置: {timeout_seconds}秒")
            return call_ai_model(prompt, config)
        
        try:
            analysis_report = call_ai_with_timeout(prompt, ai_config)
            logging.info(f"成功获取 {ai_config.selected_model} API 响应，报告长度: {len(analysis_report)} 字符")
        except TimeoutError as timeout_error:
            error_msg = str(timeout_error)
            logging.error(f"任务 {task_id}：{error_msg}")
            with progress_lock:
                analysis_progress[task_id] = {
                    'status': 'error',
                    'message': f"分析超时：{error_msg}，请检查网络连接或稍后重试"
                }
            return
        except Exception as api_error:
            logging.error(f"任务 {task_id}：AI模型调用失败: {str(api_error)}")
            logging.error(f"详细错误堆栈: {traceback.format_exc()}")
            with progress_lock:
                analysis_progress[task_id] = {
                    'status': 'error',
                    'message': f'API调用失败: {str(api_error)}'
                }
            return
        
        if analysis_report.startswith("错误：") or \
           (analysis_report.startswith("DeepSeek API调用") and "失败" in analysis_report) or \
           (analysis_report.startswith("豆包API调用") and "失败" in analysis_report):
            logging.error(f"任务 {task_id}：AI模型返回错误: {analysis_report}")
            raise Exception(analysis_report)
        
        with progress_lock:
            # 先保存到内存，确保状态查询能立即获取
            analysis_results[task_id] = analysis_report
            analysis_progress[task_id] = {
                'status': 'completed',
                'progress': 100,
                'message': '分析完成，请查看报告',
                'report': analysis_report  # 直接包含在progress中，确保前端能获取
            }
            logger.info(f"任务 {task_id} 报告已保存到内存，长度: {len(analysis_report)} 字符")
        
        # 保存到数据库（在锁外执行，避免阻塞状态查询）
        try:
            save_analysis_report(task_id, analysis_report)
            logger.info(f"任务 {task_id} 报告已保存到数据库")
        except Exception as e:
            logger.error(f"保存报告到数据库失败 - Task ID: {task_id}, 错误: {str(e)}")
            # 即使数据库保存失败，内存中已有报告，不影响用户查看
            
    except Exception as e:
        with progress_lock:
            analysis_progress[task_id] = {
                'status': 'error',
                'message': f'分析过程中出错: {str(e)}'
            }
    finally:
        db.close()

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
    return render_template('home.html')

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
        
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(username=username).first()
            
            if user and bcrypt.check_password_hash(user.password, password):
                login_user(user)
                next_page = request.args.get('next')
                return redirect(next_page) if next_page else redirect(url_for('quickform.dashboard'))
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
        task_count = len(tasks)
        return render_template('dashboard.html', tasks=tasks, task_count=task_count)
    finally:
        db.close()

@quickform_bp.route('/create_task', methods=['GET', 'POST'])
@login_required
def create_task():
    """创建任务"""
    db = SessionLocal()
    try:
        if not current_user.is_admin():
            task_count = db.query(Task).filter_by(user_id=current_user.id).count()
            if task_count >= 3:
                flash(f'您已达到任务数量上限（3个）。如需创建更多任务，请联系管理员：wzlinmiaoyan@163.com', 'warning')
                return redirect(url_for('quickform.dashboard'))
        
        if request.method == 'POST':
            title = request.form.get('title')
            description = request.form.get('description')
            
            task = Task(title=title, description=description, user_id=current_user.id)
            
            if 'file' in request.files and request.files['file'].filename != '':
                file = request.files['file']
                unique_filename, filepath = save_uploaded_file(file)
                if unique_filename:
                    task.file_name = file.filename
                    task.file_path = filepath
            
            db.add(task)
            db.commit()
            
            flash('数据任务创建成功', 'success')
            return redirect(url_for('quickform.task_detail', task_id=task.id))
        
        # GET 渲染创建页面
        return render_template('create_task.html')
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
        if task.user_id != current_user.id:
            flash('无权访问此任务', 'danger')
            return redirect(url_for('quickform.dashboard'))
        
        submission = db.query(Submission).filter_by(task_id=task.id).order_by(Submission.submitted_at.desc()).all()
        saved_filename = None
        try:
            if task.file_path:
                saved_filename = os.path.basename(task.file_path)
        except Exception:
            saved_filename = None
        return render_template('task_detail.html', task=task, submission=submission, saved_filename=saved_filename)
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
            
            if 'file' in request.files and request.files['file'].filename != '':
                file = request.files['file']
                unique_filename, filepath = save_uploaded_file(file)
                if unique_filename:
                    if task.file_path and os.path.exists(task.file_path):
                        os.remove(task.file_path)
                    task.file_name = file.filename
                    task.file_path = filepath
            elif remove_file:
                if task.file_path and os.path.exists(task.file_path):
                    os.remove(task.file_path)
                task.file_name = None
                task.file_path = None
            
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
    """删除任务"""
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if not task:
            flash('任务不存在', 'danger')
            return redirect(url_for('quickform.dashboard'))
        if task.user_id != current_user.id:
            flash('无权删除此任务', 'danger')
            return redirect(url_for('quickform.dashboard'))
        
        db.delete(task)
        db.commit()
        flash('任务已删除', 'success')
        return redirect(url_for('quickform.dashboard'))
    finally:
        db.close()

@quickform_bp.route('/ai_test')
@login_required
def ai_test_page():
    """AI模型测试页面"""
    return render_template('ai_test.html')

@quickform_bp.route('/api/submit/<string:task_id>', methods=['POST', 'OPTIONS'])
def submit_form(task_id):
    """表单提交API"""
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response
        
    db = SessionLocal()
    try:
        logger.info(f"收到表单提交请求 - task_id: {task_id}")
        
        task = db.query(Task).filter_by(task_id=task_id).first()
        if not task:
            response = jsonify({'error': '任务不存在', 'task_id': task_id, 'message': f'未找到ID为 {task_id} 的任务'})
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
            logger.warning(f"提交失败: 任务不存在 - task_id: {task_id}")
            return response, 404
        
        # 获取提交的数据
        try:
            if request.is_json:
                form_data = request.get_json()
                logger.info(f"接收到JSON数据: {form_data}")
            else:
                form_data = request.form.to_dict()
                logger.info(f"接收到表单数据: {form_data}")
        except Exception as e:
            logger.error(f"解析请求数据失败: {str(e)}")
            response = jsonify({'error': '数据格式错误', 'message': str(e)})
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
            return response, 400
        
        # 将数据转换为JSON字符串存储
        import json
        try:
            submission = Submission(task_id=task.id, data=json.dumps(form_data, ensure_ascii=False))
            db.add(submission)
            db.commit()
            logger.info(f"数据提交成功 - task_id: {task_id}, task_db_id: {task.id}")
        except Exception as e:
            db.rollback()
            logger.error(f"保存提交数据失败: {str(e)}")
            response = jsonify({'error': '保存失败', 'message': str(e)})
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
            return response, 500
        
        response = jsonify({'message': '提交成功', 'status': 'success'})
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response, 200
    except Exception as e:
        logger.error(f"提交API异常: {str(e)}", exc_info=True)
        response = jsonify({'error': '服务器错误', 'message': str(e)})
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
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
                
                if bcrypt.check_password_hash(current_user.password, current_password):
                    current_user.password = bcrypt.generate_password_hash(new_password).decode('utf-8')
                    db.commit()
                    flash('密码修改成功', 'success')
                else:
                    flash('当前密码错误', 'danger')
            
            return redirect(url_for('quickform.profile'))
        
        return render_template('profile.html', user=current_user, ai_config=ai_config)
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
            return render_template('smart_analyze.html', task=task, error="请先在配置页面设置AI模型和API密钥", ai_config=ai_config, now=datetime.now())
        
        if ai_config.selected_model == 'chat_server':
            if not current_app.config.get('CHAT_SERVER_API_TOKEN'):
                flash('当前使用默认 ChatServer 调用，建议在配置中设置专属 API Token（非必填）。', 'warning')
        elif ai_config.selected_model == 'deepseek' and not ai_config.deepseek_api_key:
            return render_template('smart_analyze.html', task=task, error="请先配置DeepSeek API密钥", ai_config=ai_config, now=datetime.now())
        elif ai_config.selected_model == 'doubao' and not ai_config.doubao_api_key:
            return render_template('smart_analyze.html', task=task, error="请先配置豆包API密钥", ai_config=ai_config, now=datetime.now())
        
        # 如果是提交生成请求，则同步生成并返回同页结果
        if request.method == 'POST':
            custom_prompt = request.form.get('custom_prompt')
            if not custom_prompt or not custom_prompt.strip():
                submission_for_prompt = db.query(Submission).filter_by(task_id=task_id).all()
                file_content_for_prompt = None
                if task.file_path and os.path.exists(task.file_path):
                    file_content_for_prompt = read_file_content(task.file_path)
                custom_prompt = generate_analysis_prompt(task, submission_for_prompt, file_content_for_prompt)
            try:
                # 后台线程执行，避免阻塞主请求线程
                t = threading.Thread(target=perform_analysis_with_custom_prompt, args=(task_id, current_user.id, ai_config.id, custom_prompt), daemon=True)
                t.start()
                # 跳转到本页并标记运行中，前端据此开始轮询
                return redirect(url_for('quickform.smart_analyze', task_id=task.id, running=1))
            except Exception as e:
                return render_template('smart_analyze.html', task=task, error=f'生成报告失败: {str(e)}', ai_config=ai_config, now=datetime.now())
        
        # GET 或 POST 完成后，准备页面所需数据
        submission = db.query(Submission).filter_by(task_id=task_id).all()
        file_content = None
        if task.file_path and os.path.exists(task.file_path):
            file_content = read_file_content(task.file_path)
        preview_prompt = generate_analysis_prompt(task, submission, file_content)
        report = task.analysis_report if task and task.analysis_report else None
        
        return render_template('smart_analyze.html', 
                             task=task, 
                             report=report,
                             preview_prompt=preview_prompt,
                             ai_config=ai_config,
                             now=datetime.now())
    finally:
        db.close()

@quickform_bp.route('/download_report/<int:task_id>')
@login_required
def download_report(task_id):
    """下载报告"""
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if not task:
            flash('任务不存在', 'danger')
            return redirect(url_for('quickform.dashboard'))
        if task.user_id != current_user.id:
            flash('无权访问此任务', 'danger')
            return redirect(url_for('quickform.dashboard'))
        
        if task.report_file_path and os.path.exists(task.report_file_path):
            import re
            safe_title = re.sub(r'[^a-zA-Z0-9_\u4e00-\u9fa5]', '_', task.title)
            safe_filename = f"{safe_title}_分析报告.html"
            
            try:
                return send_file(
                    task.report_file_path,
                    as_attachment=True,
                    download_name=safe_filename,
                    mimetype='text/html; charset=utf-8'
                )
            except TypeError:
                return send_file(
                    task.report_file_path,
                    as_attachment=True,
                    attachment_filename=safe_filename,
                    mimetype='text/html; charset=utf-8'
                )
        else:
            import re
            safe_title = re.sub(r'[^a-zA-Z0-9_\u4e00-\u9fa5]', '_', task.title)
            safe_filename = f"{safe_title}_分析报告.html"
            
            html_content = render_template('download_report.html', task=task)
            response = make_response(html_content.encode('utf-8'))
            response.headers['Content-Disposition'] = f'attachment; filename="{safe_filename}"'
            response.headers['Content-Type'] = 'text/html; charset=utf-8'
            
            return response
    except Exception as e:
        flash(f'下载报告时出错: {str(e)}', 'danger')
        return redirect(url_for('quickform.dashboard'))
    finally:
        db.close()

@quickform_bp.route('/uploads/<path:filename>')
@login_required
def uploaded_file(filename):
    """上传文件访问"""
    try:
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
        
        users = db.query(User).order_by(User.created_at.desc()).all()
        all_tasks = db.query(Task).order_by(Task.created_at.desc()).all()
        
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
        
        return render_template('admin.html', users=users, all_tasks=all_tasks, stats=stats)
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
            return redirect(url_for('quickform.admin_panel'))
        
        if user.id == current_user.id:
            flash('不能修改自己的角色', 'warning')
            return redirect(url_for('quickform.admin_panel'))
        
        if user.role == 'admin':
            user.role = 'user'
            flash(f'已将用户 {user.username} 的权限改为普通用户', 'success')
        else:
            user.role = 'admin'
            flash(f'已将用户 {user.username} 的权限改为管理员', 'success')
        
        db.commit()
    finally:
        db.close()
    
    return redirect(url_for('quickform.admin_panel'))


def init_quickform(app, login_manager_instance=None):
    """
    初始化QuickForm Blueprint
    在主应用中调用此函数来设置LoginManager、Bcrypt等
    """
    global bcrypt, login_manager
    
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
        migrate_user_table()
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
    
    logger.info("QuickForm Blueprint 初始化完成")

