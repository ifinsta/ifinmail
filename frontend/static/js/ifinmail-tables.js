/**
 * Tables on a phone. A table with a header row is shown as a list of cards below tablet width
 * (see the Smooth theme's stylesheet): each cell is labelled with its column's heading, so the
 * person reads "Quota 1024 MB" instead of swiping sideways. Without this script, or for a table
 * with no header row, the table simply scrolls inside its card.
 */
(function () {
    'use strict';

    function labelOf(th) {
        if (!th) return '';
        var clone = th.cloneNode(true);
        var hidden = clone.querySelectorAll('.ifinmail-sr-only');
        for (var i = 0; i < hidden.length; i++) hidden[i].parentNode.removeChild(hidden[i]);
        return (clone.textContent || '').replace(/\s+/g, ' ').trim();
    }

    function stack(table) {
        var head = table.tHead && table.tHead.rows[0];
        if (!head || head.cells.length < 2) return;
        var labels = [];
        for (var i = 0; i < head.cells.length; i++) {
            var span = head.cells[i].colSpan || 1;
            for (var k = 0; k < span; k++) labels.push(labelOf(head.cells[i]));
        }
        var rows = table.tBodies;
        for (var b = 0; b < rows.length; b++) {
            for (var r = 0; r < rows[b].rows.length; r++) {
                var cells = rows[b].rows[r].cells;
                if (cells.length === 1 && (cells[0].colSpan || 1) > 1) continue; // empty state
                var col = 0;
                for (var c = 0; c < cells.length; c++) {
                    cells[c].setAttribute('data-label', labels[col] || '');
                    col += cells[c].colSpan || 1;
                }
            }
        }
        table.classList.add('is-stacked');
    }

    function run(root) {
        var tables = (root || document).querySelectorAll('.ifinmail-admin-table');
        for (var i = 0; i < tables.length; i++) stack(tables[i]);
    }

    document.addEventListener('DOMContentLoaded', function () {
        run(document);
        // Tables that scripts fill in later (live logs, search results).
        if (!window.MutationObserver) return;
        var timer = null;
        new MutationObserver(function () {
            window.clearTimeout(timer);
            timer = window.setTimeout(function () { run(document); }, 80);
        }).observe(document.body, { childList: true, subtree: true });
    });
})();
