// Runs before first paint so a saved theme doesn't flash the wrong colors.
(function () {
    'use strict';
    try {
        const saved = localStorage.getItem('theme');
        if (saved === 'dark' || saved === 'light') {
            document.documentElement.dataset.theme = saved;
        }
    } catch (error) {
        // Storage can be blocked. The system preference still applies.
    }
})();
