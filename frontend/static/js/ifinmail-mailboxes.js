/**
 * ifinmail Mailbox / Alias name fields
 * Keeps the "Name" input a bare local part: lowercase, no spaces, no @.
 * Pasting a full address keeps the part before @; anything else is left for
 * native pattern validation and the server-side form check.
 */
(function () {
    'use strict';

    var LOCAL_PART_RE = /^[a-z0-9](?:[a-z0-9._+-]{0,62}[a-z0-9])?$/;

    function cleanup(value) {
        var text = (value || '').trim().toLowerCase().replace(/\s+/g, '');
        var at = text.indexOf('@');
        if (at !== -1) {
            text = text.slice(0, at);
        }
        return text;
    }

    function attach(input) {
        if (!input) {
            return;
        }
        // Normalise when the field loses focus (runs before native validation
        // on submit), so a pasted "name@example.com" becomes "name".
        input.addEventListener('change', function () {
            var before = input.value;
            var after = cleanup(before);
            if (after !== before) {
                input.value = after;
            }
            input.setCustomValidity('');
        });
        input.addEventListener('input', function () {
            input.setCustomValidity('');
        });
    }

    function valid(input) {
        return LOCAL_PART_RE.test(input.value);
    }

    document.addEventListener('DOMContentLoaded', function () {
        initNameCleanup();
        initManageModal();
        initCopyButtons();
    });

    /* ── Name cleanup ──────────────────────────────────── */

    function initNameCleanup() {
        var ids = ['mb-local', 'al-local'];
        for (var i = 0; i < ids.length; i++) {
            attach(document.getElementById(ids[i]));
        }
        // Defensive: normalise once more right before submit in case the
        // change event did not fire (e.g. autofill without blur).
        var forms = document.querySelectorAll('form');
        for (var j = 0; j < forms.length; j++) {
            (function (form) {
                form.addEventListener('submit', function () {
                    var input = form.querySelector('#mb-local, #al-local');
                    if (input) {
                        input.value = cleanup(input.value);
                        if (input.value && !valid(input)) {
                            input.setCustomValidity(input.title || 'Invalid name.');
                        } else {
                            input.setCustomValidity('');
                        }
                    }
                });
            })(forms[j]);
        }
    }

    /* ── Manage mailbox modal ──────────────────────────── */

    function initManageModal() {
        var overlay = document.getElementById('mailbox-manage-modal');
        if (!overlay) {
            return;
        }
        // Keep the dialog at body level so no overflow container clips it.
        if (overlay.parentNode !== document.body) {
            document.body.appendChild(overlay);
        }

        var addressEl = document.getElementById('mailbox-manage-address');
        var pendingEl = document.getElementById('mailbox-manage-pending');
        var inviteAddress = document.getElementById('mailbox-manage-invite-address');
        var quotaAddress = document.getElementById('mailbox-manage-quota-address');
        var quotaInput = document.getElementById('mailbox-manage-quota');
        var statusAddress = document.getElementById('mailbox-manage-status-address');
        var enableBtn = document.getElementById('mailbox-manage-enable');
        var disableBtn = document.getElementById('mailbox-manage-disable');

        function open(trigger) {
            var address = trigger.getAttribute('data-address') || '';
            var quotaMb = trigger.getAttribute('data-quota-mb') || '0';
            var active = trigger.getAttribute('data-active') === '1';
            var pending = trigger.getAttribute('data-invite-pending') === '1';
            if (addressEl) {
                addressEl.textContent = address;
            }
            var profileLink = document.getElementById('mailbox-manage-profile');
            var mailboxId = trigger.getAttribute('data-id') || '';
            if (profileLink) {
                profileLink.href = mailboxId
                    ? '/accounts/settings/mailboxes/' + mailboxId + '/'
                    : '#';
            }
            if (pendingEl) {
                pendingEl.classList.toggle('ifinmail-hidden', !pending);
            }
            if (inviteAddress) {
                inviteAddress.value = address;
            }
            if (quotaAddress) {
                quotaAddress.value = address;
            }
            if (quotaInput) {
                quotaInput.value = quotaMb;
            }
            if (statusAddress) {
                statusAddress.value = address;
            }
            if (enableBtn) {
                enableBtn.classList.toggle('ifinmail-hidden', active);
            }
            if (disableBtn) {
                disableBtn.classList.toggle('ifinmail-hidden', !active);
            }
            overlay.classList.add('ifinmail-modal-overlay--active');
            document.body.classList.add('ifinmail-body--no-scroll');
        }

        function close() {
            overlay.classList.remove('ifinmail-modal-overlay--active');
            document.body.classList.remove('ifinmail-body--no-scroll');
        }

        document.addEventListener('click', function (event) {
            var trigger = event.target.closest('[data-action="open-manage-mailbox"]');
            if (trigger) {
                event.preventDefault();
                open(trigger);
                return;
            }
            var closer = event.target.closest('[data-action="close-manage-mailbox"]');
            if (closer) {
                event.preventDefault();
                close();
                return;
            }
            if (event.target === overlay) {
                close();
            }
        });

        var modalClose = document.getElementById('mailbox-manage-close');
        if (modalClose) {
            modalClose.addEventListener('click', close);
        }

        document.addEventListener('keydown', function (event) {
            if (
                event.key === 'Escape' &&
                overlay.classList.contains('ifinmail-modal-overlay--active')
            ) {
                close();
            }
        });
    }
    /* ── Copy buttons (setup links) ──────────────────── */

    function initCopyButtons() {
        document.addEventListener('click', function (event) {
            var btn = event.target.closest('[data-action="copy-invite"]');
            if (!btn) {
                return;
            }
            event.preventDefault();
            var text = btn.getAttribute('data-value') || '';
            if (!text) {
                return;
            }
            var done = function () {
                var original = btn.textContent;
                btn.textContent = 'Copied!';
                window.setTimeout(function () {
                    btn.textContent = original;
                }, 1500);
            };
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text).then(done, function () {
                    fallbackCopy(text);
                    done();
                });
            } else {
                fallbackCopy(text);
                done();
            }
        });
    }

    function fallbackCopy(text) {
        var area = document.createElement('textarea');
        area.value = text;
        area.setAttribute('readonly', '');
        area.style.position = 'fixed';
        area.style.opacity = '0';
        document.body.appendChild(area);
        area.select();
        try {
            document.execCommand('copy');
        } catch (err) {
            /* clipboard unavailable; the link stays visible to copy by hand */
        }
        document.body.removeChild(area);
    }
})();
