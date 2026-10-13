/* Passkeys: register one, sign in with one, or use one as the second step.
 *
 * The server hands out options with a one-time challenge and verifies what the browser returns;
 * this script only moves bytes between the server and navigator.credentials (WebAuthn sends
 * ArrayBuffers, the server speaks base64url). Everything works without it except passkeys.
 */
(function () {
    'use strict';

    function toBuffer(text) {
        var base64 = text.replace(/-/g, '+').replace(/_/g, '/');
        while (base64.length % 4) { base64 += '='; }
        var raw = window.atob(base64);
        var bytes = new Uint8Array(raw.length);
        for (var i = 0; i < raw.length; i += 1) { bytes[i] = raw.charCodeAt(i); }
        return bytes.buffer;
    }

    function toText(buffer) {
        var bytes = new Uint8Array(buffer);
        var raw = '';
        for (var i = 0; i < bytes.length; i += 1) { raw += String.fromCharCode(bytes[i]); }
        return window.btoa(raw).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    }

    function csrf() {
        var el = document.querySelector('[name=csrfmiddlewaretoken]');
        return el ? el.value : '';
    }

    function post(url, body, asJson) {
        var headers = { 'X-CSRFToken': csrf(), 'Accept': 'application/json' };
        if (asJson) { headers['Content-Type'] = 'application/json'; }
        return window.fetch(url, {
            method: 'POST', credentials: 'same-origin', headers: headers,
            body: asJson ? JSON.stringify(body) : body
        }).then(function (response) {
            return response.json().catch(function () { return { ok: false, error: 'Unexpected answer.' }; });
        });
    }

    function say(box, message, failed) {
        if (!box) { return; }
        box.textContent = message;
        box.hidden = !message;
        box.classList.toggle('ifinmail-passkey-status--error', !!failed);
    }

    function reason(error) {
        if (error && error.name === 'NotAllowedError') { return 'The request was cancelled or timed out.'; }
        if (error && error.name === 'InvalidStateError') { return 'This passkey is already registered.'; }
        return (error && error.message) || 'The passkey could not be used.';
    }

    function creationOptions(o) {
        o.challenge = toBuffer(o.challenge);
        o.user.id = toBuffer(o.user.id);
        (o.excludeCredentials || []).forEach(function (c) { c.id = toBuffer(c.id); });
        return o;
    }

    function requestOptions(o) {
        o.challenge = toBuffer(o.challenge);
        (o.allowCredentials || []).forEach(function (c) { c.id = toBuffer(c.id); });
        return o;
    }

    function assertionPayload(credential, next) {
        var r = credential.response;
        return {
            id: credential.id, rawId: toText(credential.rawId), type: credential.type, next: next || '',
            response: {
                clientDataJSON: toText(r.clientDataJSON), authenticatorData: toText(r.authenticatorData),
                signature: toText(r.signature), userHandle: r.userHandle ? toText(r.userHandle) : ''
            }
        };
    }

    /* Sign in (the login page and the second step share this). */
    function signIn(button) {
        var status = document.querySelector(button.getAttribute('data-status'));
        var next = button.getAttribute('data-next') || '';
        button.disabled = true;
        say(status, 'Waiting for your passkey…', false);
        post(button.getAttribute('data-options'), {}, true).then(function (answer) {
            if (!answer.ok) { throw new Error(answer.error); }
            return navigator.credentials.get({ publicKey: requestOptions(answer.options) });
        }).then(function (credential) {
            return post(button.getAttribute('data-verify'), assertionPayload(credential, next), true);
        }).then(function (answer) {
            if (!answer.ok) { throw new Error(answer.error); }
            window.location.assign(answer.next);
        }).catch(function (error) {
            say(status, reason(error), true);
            button.disabled = false;
        });
    }

    /* Register a new passkey from the passkeys page. */
    function register(form) {
        var status = document.querySelector(form.getAttribute('data-status'));
        var button = form.querySelector('button[type=submit]');
        button.disabled = true;
        say(status, 'Waiting for your device…', false);
        post(form.getAttribute('data-options'), new window.FormData(form), false).then(function (answer) {
            if (!answer.ok) { throw new Error(answer.error); }
            return navigator.credentials.create({ publicKey: creationOptions(answer.options) });
        }).then(function (credential) {
            var r = credential.response;
            return post(form.getAttribute('data-verify'), {
                id: credential.id, rawId: toText(credential.rawId), type: credential.type,
                response: {
                    clientDataJSON: toText(r.clientDataJSON), attestationObject: toText(r.attestationObject),
                    transports: r.getTransports ? r.getTransports() : []
                }
            }, true);
        }).then(function (answer) {
            if (!answer.ok) { throw new Error(answer.error); }
            window.location.reload();
        }).catch(function (error) {
            say(status, reason(error), true);
            button.disabled = false;
        });
    }

    function init() {
        var supported = !!(window.PublicKeyCredential && navigator.credentials && window.fetch);
        document.querySelectorAll('[data-passkey-signin]').forEach(function (button) {
            if (!supported) { button.hidden = true; return; }
            button.hidden = false;
            button.addEventListener('click', function () { signIn(button); });
        });
        document.querySelectorAll('form[data-passkey-register]').forEach(function (form) {
            if (!supported) {
                say(document.querySelector(form.getAttribute('data-status')),
                    'This browser does not support passkeys.', true);
                form.querySelector('button[type=submit]').disabled = true;
                return;
            }
            form.addEventListener('submit', function (event) { event.preventDefault(); register(form); });
        });
    }

    init();
}());
