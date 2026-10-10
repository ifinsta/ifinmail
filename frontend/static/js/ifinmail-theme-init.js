/**
 * ifinmail theme bootstrap. Loaded synchronously in <head> so the right theme
 * is on <html> before first paint (no flash).
 *
 * data-theme  = the person's choice: light | dark | auto | contrast
 * data-scheme = what is actually rendered: light | dark | contrast
 *
 * The choice lives in localStorage on this browser. Default is light, so
 * existing installs keep their current look until someone picks another theme.
 */
(function () {
    'use strict';

    var KEY = 'ifinmail-theme';
    var CHOICES = ['light', 'dark', 'auto', 'contrast'];
    var root = document.documentElement;
    var media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

    function read() {
        try {
            var value = window.localStorage.getItem(KEY);
            return CHOICES.indexOf(value) === -1 ? 'light' : value;
        } catch (e) {
            return 'light';
        }
    }

    function resolve(choice) {
        if (choice === 'auto') {
            return media && media.matches ? 'dark' : 'light';
        }
        return choice;
    }

    function apply(choice) {
        var scheme = resolve(choice);
        root.setAttribute('data-theme', choice);
        root.setAttribute('data-scheme', scheme);
        var meta = document.querySelector('meta[name="theme-color"]');
        if (meta) {
            if (!meta.hasAttribute('data-default')) {
                meta.setAttribute('data-default', meta.getAttribute('content') || '');
            }
            meta.setAttribute(
                'content',
                scheme === 'light' ? meta.getAttribute('data-default') : (scheme === 'dark' ? '#0B1220' : '#000000')
            );
        }
        try {
            document.dispatchEvent(new CustomEvent('ifinmail:theme', { detail: { choice: choice, scheme: scheme } }));
        } catch (e) { /* old browsers: nothing listens anyway */ }
    }

    function set(choice) {
        if (CHOICES.indexOf(choice) === -1) return;
        try { window.localStorage.setItem(KEY, choice); } catch (e) { /* private mode: apply for this page only */ }
        apply(choice);
    }

    window.IfinmailTheme = {
        get: read,
        set: set,
        scheme: function () { return root.getAttribute('data-scheme') || 'light'; },
        choices: CHOICES.slice()
    };

    apply(read());

    // Follow the operating system while the choice is "auto".
    if (media) {
        var onChange = function () { if (read() === 'auto') apply('auto'); };
        if (media.addEventListener) media.addEventListener('change', onChange);
        else if (media.addListener) media.addListener(onChange);
    }

    // Keep other open tabs in step.
    window.addEventListener('storage', function (e) {
        if (e.key === KEY) apply(read());
    });
})();
