/**
 * Spam Filtering page: the slider shows the four scores of the level it is on, before it is
 * saved. The forms work without this script (the level is also shown as a number).
 */
(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {
        var slider = document.getElementById('sensitivity-slider');
        var data = document.getElementById('spam-levels');
        if (!slider || !data) return;
        var levels;
        try {
            levels = JSON.parse(data.textContent);
        } catch (e) {
            return;
        }
        var label = document.getElementById('sensitivity-label');
        slider.addEventListener('input', function () {
            var scores = levels[slider.value];
            if (!scores) return;
            if (label) label.textContent = slider.value;
            Object.keys(scores).forEach(function (name) {
                var cell = document.querySelector('[data-score="' + name + '"]');
                if (cell) cell.textContent = scores[name];
            });
        });
    });
})();
