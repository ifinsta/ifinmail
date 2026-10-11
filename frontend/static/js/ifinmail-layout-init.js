/**
 * ifinmail layout state. Loaded synchronously in <head> so a minimized sidebar
 * is already minimized on first paint (no flash of the wide layout).
 *
 * html[data-sidebar="collapsed"]       the app sidebar is an icon rail
 * html[data-settings-rail="collapsed"] the settings category list is an icon rail
 *
 * The choice lives in localStorage on this browser. Default is expanded.
 * The phone drawer is separate (ifinmail-sidebar.js) and ignores these states.
 */
(function () {
    'use strict';

    var PANES = {
        sidebar: { key: 'ifinmail-sidebar', attr: 'data-sidebar' },
        settings: { key: 'ifinmail-settings-nav', attr: 'data-settings-rail' }
    };
    var root = document.documentElement;

    function read(name) {
        try {
            return window.localStorage.getItem(PANES[name].key) === 'collapsed' ? 'collapsed' : 'expanded';
        } catch (e) {
            return 'expanded';
        }
    }

    function sync(name) {
        var state = root.getAttribute(PANES[name].attr) === 'collapsed' ? 'collapsed' : 'expanded';
        var buttons = document.querySelectorAll('[data-collapse-toggle="' + name + '"]');
        for (var i = 0; i < buttons.length; i++) {
            var button = buttons[i];
            var label = button.getAttribute(state === 'collapsed' ? 'data-label-expand' : 'data-label-collapse');
            button.setAttribute('aria-expanded', state === 'collapsed' ? 'false' : 'true');
            if (label) {
                button.setAttribute('title', label);
                if (button.hasAttribute('aria-label') || !button.textContent.replace(/\s+/g, '')) {
                    button.setAttribute('aria-label', label);
                }
            }
        }
    }

    function apply(name, state) {
        if (state === 'collapsed') {
            root.setAttribute(PANES[name].attr, 'collapsed');
        } else {
            root.removeAttribute(PANES[name].attr);
        }
        sync(name);
    }

    function set(name, state) {
        if (!PANES[name]) return;
        try { window.localStorage.setItem(PANES[name].key, state === 'collapsed' ? 'collapsed' : 'expanded'); } catch (e) { /* private mode: this page only */ }
        apply(name, state);
    }

    function toggle(name) {
        if (!PANES[name]) return;
        set(name, root.getAttribute(PANES[name].attr) === 'collapsed' ? 'expanded' : 'collapsed');
    }

    window.IfinmailLayout = { get: read, set: set, toggle: toggle };

    for (var name in PANES) {
        if (read(name) === 'collapsed') root.setAttribute(PANES[name].attr, 'collapsed');
    }

    document.addEventListener('DOMContentLoaded', function () {
        for (var name in PANES) sync(name);

        document.addEventListener('click', function (e) {
            var button = e.target.closest ? e.target.closest('[data-collapse-toggle]') : null;
            if (button) toggle(button.getAttribute('data-collapse-toggle'));
        });

        // Alt+C minimizes / maximizes the app sidebar; ignored while typing.
        document.addEventListener('keydown', function (e) {
            if (!e.altKey || e.ctrlKey || e.metaKey || (e.key || '').toLowerCase() !== 'c') return;
            var t = e.target;
            if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
            e.preventDefault();
            toggle('sidebar');
        });
    });

    // Keep other open tabs in step.
    window.addEventListener('storage', function (e) {
        for (var name in PANES) {
            if (e.key === PANES[name].key) apply(name, read(name));
        }
    });
})();
