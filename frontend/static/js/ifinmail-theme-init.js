/**
 * ifinmail theme bootstrap. Loaded synchronously in <head> so the right theme
 * is on <html> before first paint (no flash).
 *
 * data-theme  = the person's choice: smooth | oceanic | light | dark | auto | contrast
 * data-scheme = what is actually rendered: smooth | oceanic | light | dark | contrast
 *
 * The choice lives in localStorage on this browser. Until someone chooses, the
 * server's default applies (data-default on this script's own tag, set under
 * Settings > Appearance); without one it is "smooth". Smooth is a light-only
 * look and never follows the operating system into a dark scheme; so is oceanic.
 */
(function () {
    'use strict';

    var KEY = 'ifinmail-theme';
    var CHOICES = ['smooth', 'oceanic', 'light', 'dark', 'auto', 'contrast'];
    var root = document.documentElement;
    var tag = document.currentScript;
    var configured = tag && tag.getAttribute('data-default');
    var DEFAULT = CHOICES.indexOf(configured) === -1 ? 'smooth' : configured;
    var media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

    function read() {
        try {
            var value = window.localStorage.getItem(KEY);
            return CHOICES.indexOf(value) === -1 ? DEFAULT : value;
        } catch (e) {
            return DEFAULT;
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
            /* Values mirror --ifinmail-color-surface-1 from the dark and contrast
               theme blocks (this runs before the stylesheets load). */
            meta.setAttribute(
                'content',
                (scheme === 'light' || scheme === 'smooth' || scheme === 'oceanic')
                    ? meta.getAttribute('data-default')
                    : (scheme === 'dark' ? '#0B1220' : '#000000')
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
        scheme: function () { return root.getAttribute('data-scheme') || DEFAULT; },
        fallback: DEFAULT,
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
