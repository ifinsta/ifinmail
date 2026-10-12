/* Assistant page: live progress while an answer is prepared, copy buttons, a comfortable composer. */
(function () {
    'use strict';

    var root = document.querySelector('.ifinmail-assistant');
    var labelCopy = (root && root.getAttribute('data-label-copy')) || 'Copy';
    var labelCopied = (root && root.getAttribute('data-label-copied')) || 'Copied';
    var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    /* Conversation list: open beside the thread on wide screens, folded away on narrow ones. */
    var rail = document.querySelector('[data-assistant-rail]');
    if (rail && window.matchMedia) {
        var wide = window.matchMedia('(min-width: 1024px)');
        rail.open = wide.matches;
        if (wide.addEventListener) {
            wide.addEventListener('change', function (event) { rail.open = event.matches; });
        }
    }

    /* While a question runs: reload whenever a step arrives or the answer is done. */
    var working = document.querySelector('[data-assistant-poll]');
    if (working) {
        var url = working.getAttribute('data-assistant-poll');
        var known = working.getAttribute('data-messages');
        var tries = 0;
        var poll = function () {
            tries += 1;
            fetch(url, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
                .then(function (response) { return response.ok ? response.json() : null; })
                .then(function (data) {
                    if (data && (data.status !== 'running' || String(data.messages) !== known)) {
                        window.location.reload();
                        return;
                    }
                    if (tries < 400) { window.setTimeout(poll, tries < 20 ? 1500 : 4000); }
                })
                .catch(function () { if (tries < 400) { window.setTimeout(poll, 4000); } });
        };
        window.setTimeout(poll, 1500);
    }

    /* Copy to the clipboard, with a fallback for non-secure contexts. */
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

    function attachCopy(button, getText) {
        button.addEventListener('click', function () {
            copyText(getText()).then(function () {
                var previous = button.textContent;
                button.textContent = labelCopied;
                window.setTimeout(function () { button.textContent = previous; }, 1500);
            }).catch(function () { /* nothing to copy with here: leave the text selectable */ });
        });
    }

    document.querySelectorAll('[data-assistant-copy]').forEach(function (button) {
        attachCopy(button, function () { return button.getAttribute('data-assistant-copy'); });
    });
    document.querySelectorAll('.ifinmail-md-code').forEach(function (block) {
        var button = document.createElement('button');
        button.type = 'button';
        button.className = 'ifinmail-md-copy';
        button.textContent = labelCopy;
        block.appendChild(button);
        attachCopy(button, function () {
            var code = block.querySelector('code');
            return code ? code.textContent.replace(/\n$/, '') : '';
        });
    });

    /* Composer: grows with the text, Enter sends, Shift+Enter makes a new line. */
    var composer = document.querySelector('[data-assistant-composer]');
    if (composer) {
        var area = composer.querySelector('textarea');
        var counter = composer.querySelector('[data-assistant-count]');
        var grow = function () {
            area.style.height = 'auto';
            area.style.height = Math.min(area.scrollHeight + 2, 240) + 'px';
            if (counter) {
                var left = (parseInt(area.getAttribute('maxlength'), 10) || 2000) - area.value.length;
                counter.textContent = left < 300 ? String(left) : '';
            }
        };
        area.addEventListener('input', grow);
        area.addEventListener('keydown', function (event) {
            if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
                event.preventDefault();
                if (area.value.trim() && composer.reportValidity()) { composer.submit(); }
            }
        });
        grow();
        if (!area.disabled && !document.querySelector('[data-assistant-poll]')) {
            if (area.value) { area.focus({ preventScroll: true }); area.setSelectionRange(area.value.length, area.value.length); }
        }
    }

    /* Destructive actions ask first. */
    document.querySelectorAll('[data-assistant-confirm]').forEach(function (button) {
        button.addEventListener('click', function (event) {
            if (!window.confirm(button.getAttribute('data-assistant-confirm'))) { event.preventDefault(); }
        });
    });

    /* Land on the newest part of a long conversation. */
    var turns = document.querySelectorAll('.ifinmail-assistant-turn');
    if (turns.length) {
        var target = document.querySelector('.ifinmail-assistant-working') || turns[turns.length - 1];
        target.scrollIntoView({ block: 'end', behavior: reduceMotion ? 'auto' : 'smooth' });
    }
}());
