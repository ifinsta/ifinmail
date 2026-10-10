/**
 * ifinmail Declarative Actions
 * Replaces inline onclick handlers (CSP-safe). Usage: data-action="reload" | "history-back".
 */
(function () {
    'use strict';

    var handlers = {
        'reload': function () { window.location.reload(); },
        'history-back': function () { window.history.back(); }
    };

    document.addEventListener('click', function (event) {
        var el = event.target.closest('[data-action]');
        if (!el) return;
        var handler = handlers[el.getAttribute('data-action')];
        if (handler) {
            event.preventDefault();
            handler();
        }
    });
})();
