/**
 * ifinmail Declarative Actions
 * Replaces inline onclick handlers (CSP-safe). Usage: data-action="reload" | "history-back"; data-confirm on a submit button asks first.
 */
(function () {
    'use strict';

    var handlers = {
        'reload': function () { window.location.reload(); },
        'history-back': function () { window.history.back(); },
        'copy-field': function (el) {
            var src = el && document.getElementById(el.getAttribute('data-copy-from'));
            if (!src) return;
            var text = (src.textContent || '').trim();
            var done = function (ok) {
                var orig = el.getAttribute('data-label-copy') || 'Copy';
                el.textContent = ok ? (el.getAttribute('data-label-done') || 'Copied') : 'Failed';
                window.setTimeout(function () { el.textContent = orig; }, 1500);
            };
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(false); });
                return;
            }
            var ta = document.createElement('textarea');
            ta.value = text;
            ta.setAttribute('readonly', '');
            document.body.appendChild(ta);
            ta.select();
            var ok = false;
            try { ok = document.execCommand('copy'); } catch (err) { ok = false; }
            document.body.removeChild(ta);
            done(ok);
        }
    };

    // Destructive form buttons: <button type="submit" data-confirm="Are you sure?">
    document.addEventListener('submit', function (event) {
        var trigger = event.submitter;
        var message = trigger && trigger.getAttribute('data-confirm');
        if (message && !window.confirm(message)) {
            event.preventDefault();
        }
    });

    document.addEventListener('click', function (event) {
        var el = event.target.closest('[data-action]');
        if (!el) return;
        var handler = handlers[el.getAttribute('data-action')];
        if (handler) {
            event.preventDefault();
            handler(el);
        }
    });
})();
