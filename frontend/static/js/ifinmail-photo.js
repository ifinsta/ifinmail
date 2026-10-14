/* Profile photo: choose a picture, drag and zoom a square, send the crop with the file.
   Without JavaScript the form still works: the server centres the square itself.
   The crop is sent as fractions of the picture, so the browser and the server agree whatever
   the picture's size or EXIF rotation. Images are read as data: URLs (blob: is not in the
   page's Content-Security-Policy). */
(function () {
    'use strict';
    var form = document.querySelector('[data-photo-form]');
    if (!form) { return; }
    var file = form.querySelector('[data-photo-file]');
    var canvas = form.querySelector('[data-photo-canvas]');
    var current = form.querySelector('[data-photo-current]');
    var zoomWrap = form.querySelector('[data-photo-zoom-wrap]');
    var zoom = form.querySelector('[data-photo-zoom]');
    var hint = form.querySelector('[data-photo-hint]');
    var save = form.querySelector('[data-photo-save]');
    var fx = form.querySelector('[data-photo-x]');
    var fy = form.querySelector('[data-photo-y]');
    var fs = form.querySelector('[data-photo-size]');
    if (!file || !canvas || !canvas.getContext) { return; }
    var ctx = canvas.getContext('2d');
    var MAX = 5 * 1024 * 1024;
    var img = null;
    var cx = 0.5;   // centre of the square, as a fraction of width and height
    var cy = 0.5;

    function sideFraction() { return 1 / (parseInt(zoom.value, 10) / 100); }

    function clamp() {
        var w = img.naturalWidth, h = img.naturalHeight, short = Math.min(w, h);
        var sw = (sideFraction() * short) / w, sh = (sideFraction() * short) / h;
        cx = Math.min(Math.max(cx, sw / 2), 1 - sw / 2);
        cy = Math.min(Math.max(cy, sh / 2), 1 - sh / 2);
        return { sw: sw, sh: sh };
    }

    function draw() {
        if (!img) { return; }
        var w = img.naturalWidth, h = img.naturalHeight, short = Math.min(w, h);
        clamp();
        var side = sideFraction() * short;
        var left = cx * w - side / 2, top = cy * h - side / 2;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, left, top, side, side, 0, 0, canvas.width, canvas.height);
        fx.value = (left / w).toFixed(4);
        fy.value = (top / h).toFixed(4);
        fs.value = sideFraction().toFixed(4);
    }

    function setHint(text, bad) {
        hint.textContent = text;
        hint.classList.toggle('ifinmail-photo__hint--error', !!bad);
    }

    file.addEventListener('change', function () {
        var f = file.files && file.files[0];
        img = null;
        save.disabled = true;
        if (!f) { return; }
        if (f.size > MAX) { setHint('That picture is larger than 5 MB.', true); return; }
        if (!/^image\/(jpeg|png|webp|gif)$/.test(f.type)) {
            setHint('Use a JPEG, PNG, WebP or GIF picture.', true);
            return;
        }
        var reader = new FileReader();
        reader.onload = function () {
            var probe = new Image();
            probe.onload = function () {
                if (Math.min(probe.naturalWidth, probe.naturalHeight) < 64) {
                    setHint('That picture is too small. Use one at least 64 pixels on each side.', true);
                    return;
                }
                img = probe;
                cx = 0.5; cy = 0.5; zoom.value = '100';
                canvas.hidden = false;
                zoomWrap.hidden = false;
                if (current) { current.hidden = true; }
                setHint('Drag the picture to position it, and use the slider to zoom.', false);
                save.disabled = false;
                draw();
            };
            probe.onerror = function () { setHint('That file is not a picture we can read.', true); };
            probe.src = reader.result;
        };
        reader.readAsDataURL(f);
    });

    zoom.addEventListener('input', draw);

    var drag = null;
    canvas.addEventListener('pointerdown', function (e) {
        if (!img) { return; }
        drag = { x: e.clientX, y: e.clientY, cx: cx, cy: cy };
        canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener('pointermove', function (e) {
        if (!drag || !img) { return; }
        var w = img.naturalWidth, h = img.naturalHeight, short = Math.min(w, h);
        var side = sideFraction() * short;
        var scale = side / canvas.clientWidth;      // source pixels per screen pixel
        cx = drag.cx - ((e.clientX - drag.x) * scale) / w;
        cy = drag.cy - ((e.clientY - drag.y) * scale) / h;
        draw();
    });
    function end() { drag = null; }
    canvas.addEventListener('pointerup', end);
    canvas.addEventListener('pointercancel', end);
    canvas.addEventListener('keydown', function (e) {
        if (!img) { return; }
        var step = 0.02, k = e.key;
        if (k === 'ArrowLeft') { cx -= step; } else if (k === 'ArrowRight') { cx += step; }
        else if (k === 'ArrowUp') { cy -= step; } else if (k === 'ArrowDown') { cy += step; }
        else { return; }
        e.preventDefault();
        draw();
    });
    canvas.tabIndex = 0;
})();
