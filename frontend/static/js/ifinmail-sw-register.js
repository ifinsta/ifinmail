/**
 * ifinmail Service Worker registration (CSP-safe: no inline script).
 * The worker URL, including its cache-busting version, is passed via data-sw-url.
 */
(function () {
    'use strict';

    var script = document.currentScript;
    var url = script && script.getAttribute('data-sw-url');
    if (url && 'serviceWorker' in navigator) {
        navigator.serviceWorker.register(url);
    }
})();
