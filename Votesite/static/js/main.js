document.addEventListener('DOMContentLoaded', function() {
    // 表单验证
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(event) {
            if (!form.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
            }
            form.classList.add('was-validated');
        });
    });

    // 评分按钮组交互
    const btnGroups = document.querySelectorAll('.btn-group');
    btnGroups.forEach(group => {
        const buttons = group.querySelectorAll('.btn-outline-primary');
        buttons.forEach(button => {
            button.addEventListener('click', function() {
                const radio = this.previousElementSibling;
                if (radio) {
                    radio.checked = true;
                    // 手动触发 change 事件
                    radio.dispatchEvent(new Event('change', { bubbles: true }));
                }
            });
        });
    });

    // 自动隐藏提示消息
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            alert.style.opacity = '0';
            alert.style.transition = 'opacity 0.5s ease';
            setTimeout(() => alert.remove(), 500);
        }, 3000);
    });
}); 