/* Assistant chat: asking and answers update the page in place, copy buttons, a composer that grows.
 *
 * Everything works without this script (forms post and the page reloads). With it, a question
 * appears at once, progress and the answer replace the conversation without a reload, and the
 * thread stays scrolled to the newest message.
 */
(function () {
    'use strict';

    var SELECTOR = '.ifinmail-assistant';
    var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var pollTimer = 0;
    var busy = false;

    function root() { return document.querySelector(SELECTOR); }

    /* ── Clipboard ───────────────────────────────────────────────────────────────────────── */
    function legacyCopy(text) {
        return new Promise(function (resolve, reject) {
            var area = document.createElement('textarea');
            area.value = text;
            area.setAttribute('readonly', '');
            area.className = 'ifinmail-assistant-offscreen';
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

    function attachCopy(button, getText, label, done) {
        button.addEventListener('click', function () {
            copyText(getText()).then(function () {
                var target = button.querySelector('span') || button;
                var previous = target.textContent;
                target.textContent = done;
                window.setTimeout(function () { target.textContent = previous || label; }, 1500);
            }).catch(function () { /* nothing to copy with here: the text stays selectable */ });
        });
    }

    /* ── Scrolling ───────────────────────────────────────────────────────────────────────── */
    function scroller() { return document.querySelector('[data-assistant-scroll]'); }

    function toBottom(smooth) {
        var box = scroller();
        if (!box) { return; }
        box.scrollTo({ top: box.scrollHeight, behavior: smooth && !reduceMotion ? 'smooth' : 'auto' });
    }

    function nearBottom() {
        var box = scroller();
        return !box || box.scrollHeight - box.scrollTop - box.clientHeight < 160;
    }

    /* ── Swapping the conversation in place ──────────────────────────────────────────────── */
    function swapIn(html) {
        var doc = new DOMParser().parseFromString(html, 'text/html');
        var next = doc.querySelector(SELECTOR);
        var current = root();
        if (!next || !current) { return false; }
        var follow = nearBottom();
        var typed = current.querySelector('[data-assistant-composer] textarea');
        var kept = typed && !typed.disabled ? typed.value : '';
        var hadFocus = typed && document.activeElement === typed;
        var railOpen = current.classList.contains('is-rail-open');
        current.replaceWith(document.importNode(next, true));
        if (doc.title) { document.title = doc.title; }
        busy = false;
        init();
        var area = document.querySelector('[data-assistant-composer] textarea');
        if (area && kept && !area.value) { area.value = kept; grow(area); }
        if (area && hadFocus) { area.focus({ preventScroll: true }); }
        if (railOpen && root()) { root().classList.add('is-rail-open'); }
        toBottom(follow);
        return true;
    }

    function reloadFromServer() {
        return fetch(window.location.href, { credentials: 'same-origin', headers: { 'Accept': 'text/html' } })
            .then(function (response) { return response.ok ? response.text() : null; })
            .then(function (html) { return html ? swapIn(html) : false; });
    }

    /* While a question runs, ask the small status endpoint and swap when something changed. */
    function startPolling() {
        window.clearTimeout(pollTimer);
        var working = document.querySelector('[data-assistant-poll]');
        if (!working) { return; }
        var url = working.getAttribute('data-assistant-poll');
        var known = working.getAttribute('data-messages');
        var tries = 0;
        var poll = function () {
            tries += 1;
            fetch(url, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
                .then(function (response) { return response.ok ? response.json() : null; })
                .then(function (data) {
                    if (data && (data.status !== 'running' || String(data.messages) !== known)) {
                        return reloadFromServer();
                    }
                    if (tries < 400) { pollTimer = window.setTimeout(poll, tries < 20 ? 1500 : 4000); }
                    return null;
                })
                .catch(function () { if (tries < 400) { pollTimer = window.setTimeout(poll, 4000); } });
        };
        pollTimer = window.setTimeout(poll, 1200);
    }

    /* ── Sending ─────────────────────────────────────────────────────────────────────────── */
    function escapeText(text) {
        var node = document.createElement('div');
        node.textContent = text;
        return node.innerHTML;
    }

    /* Show the question and a working line immediately, before the server has answered. */
    function showPending(text) {
        var chat = document.querySelector('.ifinmail-assistant-chat');
        var column = document.querySelector('.ifinmail-assistant-column');
        if (!chat || !column) { return; }
        var start = column.querySelector('.ifinmail-assistant-start');
        if (start) { start.remove(); }
        var suggestions = document.querySelector('.ifinmail-assistant-suggestions');
        if (suggestions) { suggestions.remove(); }
        chat.classList.remove('ifinmail-assistant-chat--empty');
        var thread = column.querySelector('.ifinmail-assistant-thread');
        if (!thread) {
            thread = document.createElement('div');
            thread.className = 'ifinmail-assistant-thread';
            thread.setAttribute('role', 'log');
            column.appendChild(thread);
        }
        var turn = document.createElement('article');
        turn.className = 'ifinmail-assistant-turn';
        turn.innerHTML = '<div class="ifinmail-assistant-user"><p>' + escapeText(text) + '</p></div>' +
            '<div class="ifinmail-assistant-working" role="status"><span class="ifinmail-assistant-dots" aria-hidden="true">' +
            '<i></i><i></i><i></i></span></div>';
        thread.appendChild(turn);
        toBottom(true);
    }

    function lockComposer(locked) {
        var composer = document.querySelector('[data-assistant-composer]');
        if (!composer) { return; }
        var send = composer.querySelector('.ifinmail-assistant-send');
        if (send) { send.disabled = locked; }
    }

    function submitAsk(form) {
        if (busy) { return; }
        var field = form.querySelector('[name="question"]');
        var text = field ? field.value.trim() : '';
        if (!text) { return; }
        busy = true;
        var data = new FormData(form);  // read the question before the box is cleared
        lockComposer(true);
        showPending(text);
        var composerArea = document.querySelector('[data-assistant-composer] textarea');
        if (composerArea) { composerArea.value = ''; grow(composerArea); }
        fetch(form.action, { method: 'POST', body: data, credentials: 'same-origin', headers: { 'Accept': 'text/html' } })
            .then(function (response) {
                if (!response.ok) { throw new Error('status ' + response.status); }
                var url = response.url;
                return response.text().then(function (html) {
                    if (!swapIn(html)) { window.location.assign(url); return; }
                    if (url && url !== window.location.href) { window.history.pushState({}, '', url); }
                });
            })
            .catch(function () {
                // The request may not have reached the server: fall back to a normal post.
                busy = false;
                HTMLFormElement.prototype.submit.call(form);
            });
    }

    /* ── Composer ────────────────────────────────────────────────────────────────────────── */
    function grow(area) {
        area.style.height = 'auto';
        area.style.height = Math.min(area.scrollHeight, 220) + 'px';
        var hint = document.querySelector('[data-assistant-count]');
        if (hint) {
            var left = (parseInt(area.getAttribute('maxlength'), 10) || 2000) - area.value.length;
            if (left < 300) { hint.textContent = String(left); }
            else { hint.textContent = hint.getAttribute('data-default') || hint.textContent; }
        }
    }

    /* ── Wiring (runs again after every swap) ────────────────────────────────────────────── */
    function init() {
        var host = root();
        if (!host) { return; }
        var labelCopy = host.getAttribute('data-label-copy') || 'Copy';
        var labelCopied = host.getAttribute('data-label-copied') || 'Copied';

        host.querySelectorAll('[data-assistant-copy]').forEach(function (button) {
            attachCopy(button, function () { return button.getAttribute('data-assistant-copy'); }, labelCopy, labelCopied);
        });
        host.querySelectorAll('.ifinmail-md-code').forEach(function (block) {
            if (block.querySelector('.ifinmail-md-copy')) { return; }
            var button = document.createElement('button');
            button.type = 'button';
            button.className = 'ifinmail-md-copy';
            button.textContent = labelCopy;
            block.appendChild(button);
            attachCopy(button, function () {
                var code = block.querySelector('code');
                return code ? code.textContent.replace(/\n$/, '') : '';
            }, labelCopy, labelCopied);
        });

        var hint = host.querySelector('[data-assistant-count]');
        if (hint) { hint.setAttribute('data-default', hint.textContent); }
        var composer = host.querySelector('[data-assistant-composer]');
        if (composer) {
            var area = composer.querySelector('textarea');
            area.addEventListener('input', function () { grow(area); });
            area.addEventListener('keydown', function (event) {
                if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
                    event.preventDefault();
                    if (area.value.trim() && !composer.querySelector('.ifinmail-assistant-send').disabled) {
                        composer.requestSubmit();
                    }
                }
            });
            grow(area);
            if (!document.querySelector('[data-assistant-poll]') && window.matchMedia('(min-width: 768px)').matches) {
                area.focus({ preventScroll: true });
                area.setSelectionRange(area.value.length, area.value.length);
            }
        }

        host.querySelectorAll('form[data-assistant-ask]').forEach(function (form) {
            form.addEventListener('submit', function (event) {
                if (!window.fetch || !window.FormData || !window.DOMParser) { return; }
                event.preventDefault();
                submitAsk(form);
            });
        });

        host.querySelectorAll('[data-assistant-confirm]').forEach(function (button) {
            button.addEventListener('click', function (event) {
                if (!window.confirm(button.getAttribute('data-assistant-confirm'))) { event.preventDefault(); }
            });
        });

        /* Conversation list: always beside the chat on wide screens, a drawer on narrow ones. */
        var toggle = host.querySelector('[data-assistant-rail-toggle]');
        if (toggle) {
            var setRail = function (open) {
                host.classList.toggle('is-rail-open', open);
                toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
            };
            toggle.addEventListener('click', function () { setRail(!host.classList.contains('is-rail-open')); });
            host.addEventListener('click', function (event) {
                if (event.target === host && host.classList.contains('is-rail-open')) { setRail(false); }
            });
            host.addEventListener('keydown', function (event) {
                if (event.key === 'Escape' && host.classList.contains('is-rail-open')) { setRail(false); toggle.focus(); }
            });
        }

        toBottom(false);
        startPolling();
    }

    window.addEventListener('popstate', function () { window.location.reload(); });
    init();
}());
