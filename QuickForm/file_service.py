"""文件处理服务"""
import os
import uuid
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# 允许的文件扩展名
ALLOWED_EXTENSIONS = {'pdf', 'html', 'htm', 'jpg', 'jpeg', 'png', 'zip', 'txt'}


def allowed_file(filename):
    """检查文件扩展名是否允许"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_uploaded_file(file, upload_folder):
    """保存上传的文件"""
    try:
        if not file:
            logger.warning("save_uploaded_file: file对象为空")
            return None, None
        
        if not file.filename:
            logger.warning("save_uploaded_file: 文件名为空")
            return None, None
        
        if not allowed_file(file.filename):
            file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else '无扩展名'
            logger.warning(f"save_uploaded_file: 不支持的文件格式 - {file.filename}, 扩展名: {file_ext}, 允许的格式: {ALLOWED_EXTENSIONS}")
            return None, None
        
        unique_filename = str(uuid.uuid4()) + '_' + file.filename
        filepath = os.path.join(upload_folder, unique_filename)
        
        # 确保上传目录存在
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
            logger.info(f"创建上传目录: {upload_folder}")
        
        file.save(filepath)
        logger.info(f"文件保存成功: {file.filename} -> {unique_filename}")
        return unique_filename, filepath
    except Exception as e:
        logger.error(f"保存文件失败: {str(e)}, 文件名: {file.filename if file else 'None'}", exc_info=True)
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


def extract_useful_text_from_html(html_content):
    """解析HTML，保留主要可读文本（去掉脚本/样式/导航），尽量按段落输出。"""
    try:
        soup = BeautifulSoup(html_content or '', 'lxml')
        # 去除明显无用的标签
        for tag in soup(['script', 'style', 'noscript', 'template']):
            tag.decompose()
        for tag in soup.find_all(True):
            # 删除常见导航/页脚/广告区域（通过tag名粗略过滤）
            if tag.name in ['header', 'footer', 'nav', 'aside']:
                tag.decompose()
        # 提取纯文本，保留换行以形成段落
        raw_text = soup.get_text('\n', strip=True)
        # 归一化空白与段落：
        lines = [ln.strip() for ln in raw_text.split('\n')]
        lines = [ln for ln in lines if ln]  # 去掉空行
        # 过滤纯符号/过短噪声，但不过度删减
        filtered = []
        for ln in lines:
            # 去掉只有标点或长度极短的行，但保留标题等短句
            if len(ln) == 1 and not ln.isalnum():
                continue
            filtered.append(ln)
        # 合并相邻重复行，避免模板重复
        merged = []
        prev = None
        for ln in filtered:
            if ln != prev:
                merged.append(ln)
            prev = ln
        # 限制总长度，避免提示词过长
        text = '\n'.join(merged)
        if len(text) > 20000:
            text = text[:20000]
        return text
    except Exception:
        try:
            return BeautifulSoup(html_content or '', 'lxml').get_text('\n', strip=True)
        except Exception:
            return ''

