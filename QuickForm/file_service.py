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
    if not filename or '.' not in filename:
        logger.warning(f"allowed_file: 文件名无效或没有扩展名 - {filename}")
        return False
    
    # 获取扩展名并转换为小写，去除可能的空白字符
    ext = filename.rsplit('.', 1)[1].lower().strip()
    # 去除可能的BOM或其他隐藏字符
    ext = ext.replace('\ufeff', '').replace('\u200b', '').strip()
    
    result = ext in ALLOWED_EXTENSIONS
    if not result:
        # 记录详细信息，包括文件名的原始字节表示
        filename_bytes = filename.encode('utf-8', errors='replace') if filename else b''
        logger.warning(f"allowed_file: 扩展名不在允许列表中 - 文件名: {filename}, 扩展名: '{ext}' (原始字节: {filename_bytes[-10:]}), 允许的格式: {ALLOWED_EXTENSIONS}")
    else:
        logger.info(f"allowed_file: 文件格式检查通过 - 文件名: {filename}, 扩展名: '{ext}'")
    return result


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
        
        # 处理文件名，确保编码正确
        original_filename = file.filename
        # 如果文件名包含非ASCII字符，尝试安全处理
        try:
            # 确保文件名可以安全保存
            safe_filename = original_filename.encode('utf-8').decode('utf-8')
        except (UnicodeEncodeError, UnicodeDecodeError) as e:
            logger.warning(f"文件名编码问题: {original_filename}, 错误: {str(e)}")
            # 如果编码失败，使用原始文件名
            safe_filename = original_filename
        
        unique_filename = str(uuid.uuid4()) + '_' + safe_filename
        filepath = os.path.join(upload_folder, unique_filename)
        
        # 确保上传目录存在
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
            logger.info(f"创建上传目录: {upload_folder}")
        
        # 记录详细信息用于调试
        logger.info(f"准备保存文件 - 原始文件名: {original_filename}, 安全文件名: {safe_filename}, 扩展名: {original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else '无'}, 目标路径: {filepath}")
        
        file.save(filepath)
        
        # 验证文件是否真的保存成功
        if os.path.exists(filepath):
            file_size = os.path.getsize(filepath)
            logger.info(f"文件保存成功: {original_filename} -> {unique_filename}, 大小: {file_size} 字节")
            return unique_filename, filepath
        else:
            logger.error(f"文件保存后验证失败: 文件不存在于 {filepath}")
            return None, None
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

