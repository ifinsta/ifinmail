/* System health: copy buttons for values, and a busy state while the checks run. */
(function () {
    'use strict';

    function legacyCopy(text) {
        return new Promise(function (resolve, reject) {
            var area = document.createElement('textarea');
            area.value = text;
            area.setAttribute('readonly', '');
            area.style.position = 'fixed';
            area.style.opacity = '0';
            document.body.appendChild(area);
            area.select();
            try { document.execCommand('copy') ? resolve() : reject(new Error('copy refused')); }
            catch (error) { reject(error); }
            document.body.removeChild(area);
        });
    }

    /* Clipboard API first; when the browser refuses it, the older route; never an unhandled error. */
    function copyText(text) {
        if (navigator.clipboard && window.isSecureContext) {
            return navigator.clipboard.writeText(text).catch(function () { return legacyCopy(text); });
        }
        return legacyCopy(text);
    }

    document.querySelectorAll('[data-copy]').forEach(function (button) {
        button.addEventListener('click', function () {
            copyText(button.getAttribute('data-copy')).then(function () {
                var previous = button.textContent;
                button.textContent = button.getAttribute('data-copied') || 'Copied';
                window.setTimeout(function () { button.textContent = previous; }, 1500);
            }).catch(function () { /* the value stays selectable in its box */ });
        });
    });

    document.querySelectorAll('[data-health-recheck]').forEach(function (form) {
        form.addEventListener('submit', function () {
            var button = form.querySelector('button[type="submit"]');
            if (!button) { return; }
            button.textContent = button.getAttribute('data-label-busy') || button.textContent;
            // Disable after the submit has started, or the browser drops the request.
            window.setTimeout(function () { button.disabled = true; }, 0);
        });
    });
}());
