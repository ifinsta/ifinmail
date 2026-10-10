/**
 * ifinmail Settings hub: category search and the Appearance theme picker.
 * Requires ifinmail-theme-init.js (loaded in <head>) for the picker.
 */
(function () {
    'use strict';

    function initSearch() {
        var nav = document.querySelector('[data-settings-nav]');
        var input = nav && nav.querySelector('[data-settings-search]');
        if (!input) return;
        var items = nav.querySelectorAll('[data-settings-item]');
        var groups = nav.querySelectorAll('[data-settings-group]');
        var empty = nav.querySelector('[data-settings-empty]');

        function filter() {
            var query = input.value.trim().toLowerCase();
            var visible = 0;
            items.forEach(function (item) {
                var match = !query || (item.getAttribute('data-search') || '').indexOf(query) !== -1;
                item.hidden = !match;
                if (match) visible += 1;
            });
            groups.forEach(function (group) {
                group.hidden = !group.querySelector('[data-settings-item]:not([hidden])');
            });
            if (empty) empty.hidden = visible !== 0;
        }

        input.addEventListener('input', filter);
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && input.value) {
                input.value = '';
                filter();
            } else if (e.key === 'Enter') {
                var first = nav.querySelector('[data-settings-item]:not([hidden]) a');
                if (first) first.click();
            }
        });
    }

    function initThemePicker() {
        var picker = document.querySelector('[data-theme-picker]');
        var theme = window.IfinmailTheme;
        if (!picker || !theme) return;

        var badge = document.querySelector('[data-theme-active]');
        var help = document.querySelector('[data-theme-help]');
        var radios = picker.querySelectorAll('input[name="ifinmail-theme"]');

        function labelFor(value) {
            var radio = picker.querySelector('input[value="' + value + '"]');
            var label = radio && radio.closest('label');
            var text = label && label.querySelector('.ifinmail-theme-card__label');
            return text ? text.textContent.trim() : value;
        }

        function render() {
            var choice = theme.get();
            radios.forEach(function (radio) { radio.checked = radio.value === choice; });
            if (badge) badge.textContent = labelFor(theme.scheme());
            if (help) {
                help.textContent = choice === 'auto'
                    ? (picker.getAttribute('data-help-auto') || '')
                    : (picker.getAttribute('data-help-manual') || '');
            }
        }

        radios.forEach(function (radio) {
            radio.addEventListener('change', function () {
                if (radio.checked) theme.set(radio.value);
            });
        });
        document.addEventListener('ifinmail:theme', render);
        render();
    }

    initSearch();
    initThemePicker();
})();
