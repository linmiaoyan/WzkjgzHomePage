/**
 * 共享JavaScript函数
 * 用于所有页面的通用功能
 */

// 设置免注册AI问答链接
function setupAiChatLink() {
    const aiChatLink = document.getElementById('ai-chat-link');
    if (aiChatLink) {
        aiChatLink.href = '/chat_server';
    }
}

// 设置当前年份
function setupFooterYear() {
    const yearElement = document.querySelector('footer p');
    if (yearElement) {
        const currentYear = new Date().getFullYear();
        yearElement.innerHTML = yearElement.innerHTML.replace('{{ year }}', currentYear);
        yearElement.innerHTML = yearElement.innerHTML.replace(/\d{4}/, currentYear);
    }
}

// 复制到剪贴板（用于input元素）
function copyToClipboard(elementId) {
    const element = document.getElementById(elementId);
    if (!element) return;
    
    element.select();
    element.setSelectionRange(0, 99999);
    document.execCommand('copy');
    
    // 显示复制成功提示
    const btn = element.nextElementSibling;
    if (btn) {
        const originalText = btn.innerHTML;
        btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-check" viewBox="0 0 16 16"><path d="M10.97 4.97a.75.75 0 0 1 1.07 1.05l-3.99 4.99a.75.75 0 0 1-1.08.02L4.324 8.384a.75.75 0 1 1 1.06-1.06l2.094 2.093 3.473-4.425a.267.267 0 0 1 .02-.022z"/></svg> 已复制';
        
        setTimeout(() => {
            btn.innerHTML = originalText;
        }, 2000);
    }
}

// 复制文本内容到剪贴板（用于textarea元素）
function copyToClipboardText(textareaId) {
    const textarea = document.getElementById(textareaId);
    if (!textarea) return;
    
    textarea.select();
    textarea.setSelectionRange(0, 99999);
    document.execCommand('copy');
    
    // 显示复制成功提示
    const btn = textarea.nextElementSibling;
    if (btn) {
        const originalText = btn.innerHTML;
        btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-check-circle" viewBox="0 0 16 16"><path d="M8 15A7 7 0 1 1 8 1a7 7 0 0 1 0 14zm0 1A8 8 0 1 0 8 0a8 8 0 0 0 0 16z"/><path d="M10.97 4.97a.235.235 0 0 0-.02.022L7.477 9.417 2.3 6.896a.235.235 0 0 0-.307.01l-.89.89a.5.5 0 0 0 .696.697l1.656-1.656a.235.235 0 0 0 .022-.023l3.473-4.425a.5.5 0 0 1 .703-.03l3.5 3.5a.5.5 0 0 1 .03.703z"/></svg> 已复制';
        
        if (btn.classList.contains('btn-primary')) {
            btn.classList.remove('btn-primary');
            btn.classList.add('btn-success');
        }
        
        setTimeout(() => {
            btn.innerHTML = originalText;
            if (btn.classList.contains('btn-success')) {
                btn.classList.remove('btn-success');
                btn.classList.add('btn-primary');
            }
        }, 2000);
    }
}

// 复制折叠区域中的提示词
function copyPromptText(collapseId) {
    const collapse = document.getElementById(collapseId);
    if (!collapse) return;
    
    const textarea = collapse.querySelector('textarea');
    if (!textarea) return;
    
    textarea.select();
    textarea.setSelectionRange(0, 99999);
    document.execCommand('copy');
    
    // 显示复制成功提示
    const btn = collapse.querySelector('button.btn-primary');
    if (btn) {
        const originalText = btn.innerHTML;
        btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" fill="currentColor" class="bi bi-check-circle" viewBox="0 0 16 16" style="margin-right: 3px;"><path d="M8 15A7 7 0 1 1 8 1a7 7 0 0 1 0 14zm0 1A8 8 0 1 0 8 0a8 8 0 0 0 0 16z"/><path d="M10.97 4.97a.235.235 0 0 0-.02.022L7.477 9.417 2.3 6.896a.235.235 0 0 0-.307.01l-.89.89a.5.5 0 0 0 .696.697l1.656-1.656a.235.235 0 0 0 .022-.023l3.473-4.425a.5.5 0 0 1 .703-.03l3.5 3.5a.5.5 0 0 1 .03.703z"/></svg> 已复制';
        btn.classList.remove('btn-primary');
        btn.classList.add('btn-success');
        
        setTimeout(() => {
            btn.innerHTML = originalText;
            btn.classList.remove('btn-success');
            btn.classList.add('btn-primary');
        }, 2000);
    }
}

// 页面加载时初始化
document.addEventListener('DOMContentLoaded', function() {
    setupAiChatLink();
    setupFooterYear();
});

