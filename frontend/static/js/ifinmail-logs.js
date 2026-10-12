/**
 * ifinmail Logs page
 * - Level and period filters apply as soon as they change (Apply stays for the keyboard-only).
 * - Live view: polls for events newer than the newest one shown and adds them at the top.
 */
(function () {
    'use strict';

    document.querySelectorAll('select[data-autosubmit]').forEach(function (select) {
        select.addEventListener('change', function () {
            if (select.form) { select.form.submit(); }
        });
    });

    var button = document.getElementById('live-toggle');
    var body = document.getElementById('logs-body');
    var status = document.getElementById('live-status');
    if (!button || !body) { return; }

    var timer = null;
    var after = button.getAttribute('data-after') || '';
    var pageSize = 25;
    var labels = {
        live: button.getAttribute('data-label-live') || 'Live view',
        pause: button.getAttribute('data-label-pause') || 'Pause live view'
    };
    var levelClass = { error: 'danger', warning: 'warning', info: 'info' };

    function cell(className, child) {
        var td = document.createElement('td');
        if (className) { td.className = className; }
        td.appendChild(child);
        return td;
    }

    function textNode(value) { return document.createTextNode(value == null ? '' : String(value)); }

    function buildRow(item) {
        var tr = document.createElement('tr');
        tr.setAttribute('data-log-id', item.id);
        tr.className = 'ifinmail-logs-new';

        var time = document.createElement('time');
        time.className = 'ifinmail-text--mono';
        time.setAttribute('datetime', item.time_iso);
        time.appendChild(textNode(item.time));
        tr.appendChild(cell('ifinmail-logs-time', time));

        var badge = document.createElement('span');
        badge.className = 'ifinmail-badge ifinmail-badge--' + (levelClass[item.level] || 'info');
        badge.appendChild(textNode(item.level_word));
        tr.appendChild(cell('', badge));

        var code = document.createElement('code');
        code.className = 'ifinmail-text--mono';
        code.appendChild(textNode(item.action || '—'));
        tr.appendChild(cell('ifinmail-logs-event', code));

        var by = cell('ifinmail-logs-by', textNode(item.user));
        by.title = item.user || '';
        tr.appendChild(by);
        tr.appendChild(cell('ifinmail-logs-detail', textNode(item.detail)));
        return tr;
    }

    function show(message) {
        if (!status) { return; }
        status.hidden = !message;
        status.textContent = message || '';
    }

    function poll() {
        var params = new URLSearchParams(button.getAttribute('data-query') || '');
        if (after) { params.set('after', after); }
        fetch(button.getAttribute('data-url') + '?' + params.toString(), {
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json' }
        })
            .then(function (response) { return response.ok ? response.json() : null; })
            .then(function (data) {
                if (!data || timer === null) { return; }
                var known = {};
                body.querySelectorAll('tr[data-log-id]').forEach(function (row) {
                    known[row.getAttribute('data-log-id')] = true;
                });
                var fresh = (data.rows || []).filter(function (item) { return !known[item.id]; });
                var empty = body.querySelector('.ifinmail-admin-table-empty');
                if (fresh.length && empty) { empty.closest('tr').remove(); }
                fresh.forEach(function (item) { body.insertBefore(buildRow(item), body.firstChild); });
                while (body.querySelectorAll('tr[data-log-id]').length > pageSize) {
                    body.querySelector('tr[data-log-id]:last-of-type').remove();
                }
                if (data.latest) { after = data.latest; }
                var now = new Date();
                show(labels.live + ' · ' + now.toLocaleTimeString() +
                    (fresh.length ? ' · +' + fresh.length : ''));
            })
            .catch(function () { show(labels.live + ' · …'); });
    }

    function start() {
        timer = window.setInterval(poll, 5000);
        button.setAttribute('aria-pressed', 'true');
        button.textContent = labels.pause;
        button.classList.add('ifinmail-btn--primary');
        poll();
    }

    function stop() {
        if (timer !== null) { window.clearInterval(timer); }
        timer = null;
        button.setAttribute('aria-pressed', 'false');
        button.textContent = labels.live;
        button.classList.remove('ifinmail-btn--primary');
        show('');
    }

    button.addEventListener('click', function () { if (timer === null) { start(); } else { stop(); } });
    document.addEventListener('visibilitychange', function () {
        if (document.hidden && timer !== null) { stop(); }  // never poll a hidden tab
    });
}());
