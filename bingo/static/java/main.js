/* =========================================
   MAIN JS - Lógica de Interfaz y Tema
   ========================================= */



document.addEventListener('DOMContentLoaded', () => {
    const themeElement = document.getElementById('theme-element');

    // Soporta múltiples botones de tema (autenticado y no autenticado)
    const themeToggles = document.querySelectorAll('[id^="themeToggle"]');
    const themeIcons  = document.querySelectorAll('[id^="themeIcon"]');

    // 1. CARGAR PREFERENCIA GUARDADA
    const savedTheme = localStorage.getItem('theme') || 'light';
    applyTheme(savedTheme);

    // 2. ESCUCHAR EL CLIC EN CUALQUIER BOTÓN DE TEMA
    themeToggles.forEach(btn => {
        btn.addEventListener('click', () => {
            const currentTheme = themeElement.getAttribute('data-bs-theme');
            const newTheme = currentTheme === 'light' ? 'dark' : 'light';
            applyTheme(newTheme);
            localStorage.setItem('theme', newTheme);
        });
    });

    // 3. FUNCIÓN PARA APLICAR EL TEMA
    function applyTheme(theme) {
        themeElement.setAttribute('data-bs-theme', theme);

        themeIcons.forEach(icon => {
            if (theme === 'dark') {
                icon.classList.replace('fa-moon', 'fa-sun');
                icon.style.color = '#facc15';
            } else {
                icon.classList.replace('fa-sun', 'fa-moon');
                icon.style.color = '';
            }
        });
    }
});



// Lógica para cerrar alertas automáticamente después de 5 segundos
window.setTimeout(function() {
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        const bsAlert = new bootstrap.Alert(alert);
        bsAlert.close();
    });
}, 5000);
