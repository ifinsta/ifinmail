/* Assistant page: while an answer is being prepared, poll its status and reload when it is done. */
(function () {
    'use strict';
    var node = document.querySelector('[data-assistant-poll]');
    if (!node) { return; }
    var url = node.getAttribute('data-assistant-poll');
    var tries = 0;
    function check() {
        tries += 1;
        fetch(url, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
            .then(function (response) { return response.ok ? response.json() : { status: 'running' }; })
            .then(function (data) {
                if (data.status !== 'running') { window.location.reload(); return; }
                if (tries < 400) { window.setTimeout(check, tries < 20 ? 1500 : 4000); }
            })
            .catch(function () { if (tries < 400) { window.setTimeout(check, 4000); } });
    }
    window.setTimeout(check, 1500);
}());
