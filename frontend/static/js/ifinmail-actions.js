/**
 * ifinmail Declarative Actions
 * Replaces inline onclick handlers (CSP-safe). Usage: data-action="reload" | "history-back"; data-confirm on a submit button asks first.
 */
(function () {
    'use strict';

    var handlers = {
        'reload': function () { window.location.reload(); },
        'history-back': function () { window.history.back(); }
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
            handler();
        }
    });
})();
