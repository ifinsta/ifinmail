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
    });
})();
