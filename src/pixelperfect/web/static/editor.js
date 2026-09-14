/* Pixel-Perfect manual editor — dependency-free, no build step.
 *
 * Canonical state is an INDEXED document: a palette of RGBA colors plus an
 * Int16 grid of palette indices (-1 = transparent). The RGBA canvas is a
 * render cache. This makes both "palette mode" (recolor a swatch -> every
 * referencing cell updates) and "free color mode" (add a custom entry) compose
 * cleanly, and lets export reuse the server's render_indexed() path.
 */
(function () {
  "use strict";

  const TRANSPARENT = -1;
  let S = null;          // editor state
  let root = null;       // container element
  let els = {};          // cached DOM nodes
  let painting = false;
  let lastCell = null;
  let strokeSnapshot = null;

  // ---- helpers ---------------------------------------------------------------
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const hex2 = (n) => n.toString(16).padStart(2, "0");
  const rgbaHex = (c) => "#" + hex2(c.r) + hex2(c.g) + hex2(c.b) + hex2(c.a);
  const sameColor = (a, b) => a.r === b.r && a.g === b.g && a.b === b.b && a.a === b.a;

  function paletteKey(r, g, b) { return (r << 16) | (g << 8) | b; }

  // ---- public API ------------------------------------------------------------
  const PixelEditor = {
    mount(container) { root = container; build(); },
    open(result) {
      // Preserve in-editor edits when re-opening for the same restore result;
      // a new restore produces a new result object and re-initializes.
      if (S && S._result === result) { show(true); return; }
      initFromResult(result);
      show(true);
    },
    close() { show(false); },
    isDirty() { return S && S.dirty; },
  };
  window.PixelEditor = PixelEditor;

  // ---- DOM construction ------------------------------------------------------
  function build() {
    root.innerHTML = `
      <div class="ed-modal" role="dialog" aria-label="Pixel editor">
      <div class="ed-bar">
        <div class="ed-tools">
          <button data-tool="pencil" class="ed-tool active" title="Pencil (B)">✏️</button>
          <button data-tool="eraser" class="ed-tool" title="Eraser (E)">⌫</button>
          <button data-tool="bucket" class="ed-tool" title="Fill (G)">🪣</button>
          <button data-tool="eyedropper" class="ed-tool" title="Eyedropper (I)">💧</button>
        </div>
        <div class="ed-tools">
          <button id="ed-undo" class="ed-tool ed-wbtn" title="Undo (Ctrl+Z)">↶ Undo</button>
          <button id="ed-redo" class="ed-tool ed-wbtn" title="Redo (Ctrl+Shift+Z)">↷ Redo</button>
        </div>
        <div class="ed-tools">
          <button id="ed-zoom-out" class="ed-tool ed-zbtn" title="Zoom out (− or scroll)">🔍−</button>
          <span id="ed-zoom" class="ed-zoom">8×</span>
          <button id="ed-zoom-in" class="ed-tool ed-zbtn" title="Zoom in (+ or scroll)">🔍+</button>
        </div>
        <label class="ed-check" title="Toggle a cell grid overlay (shown at 4× zoom and above)"><input type="checkbox" id="ed-grid" title="Toggle a cell grid overlay (shown at 4× zoom and above)"> Grid</label>
        <label class="ed-check" title="Overlay the confidence heatmap: green = solid, red = ambiguous"><input type="checkbox" id="ed-heat" title="Overlay the confidence heatmap: green = solid, red = ambiguous"> Heatmap</label>
        <span id="ed-status" class="ed-status" title="Canvas size and the cell under the cursor"></span>
        <button id="ed-close" class="ed-tool" title="Close (Esc)">✕</button>
      </div>
      <div class="ed-main">
        <div class="ed-stage" id="ed-stage">
          <div class="ed-canvaswrap" id="ed-wrap">
            <canvas id="ed-canvas"></canvas>
            <canvas id="ed-overlay"></canvas>
          </div>
        </div>
        <div class="ed-side">
          <div class="ed-palette-head">Palette <span id="ed-cur" class="ed-cur" title="Click to copy hex"></span></div>
          <div id="ed-palette" class="ed-palette"></div>
          <div class="ed-addrow">
            <input type="color" id="ed-color" value="#000000" title="Pick any color to add to the palette">
            <button id="ed-add" class="ed-mini" title="Add the picked color to the palette and select it for painting">+ Add color</button>
          </div>
          <div class="ed-hint" title="Single-click selects a swatch for painting; double-click recolors it everywhere it is used.">Click a swatch to select · double-click to recolor it (updates all matching pixels).</div>
          <div class="ed-export">
            <button id="ed-dl-1x" class="ghost" title="Download the edited image at native 1× resolution (one image pixel per cell)">Download 1×</button>
            <button id="ed-dl-nx" class="ghost" title="Download the edited image upscaled (each cell enlarged), good for sharing previews">Download <span id="ed-nxlabel">8×</span></button>
          </div>
        </div>
      </div>
      </div>`;

    els = {
      canvas: root.querySelector("#ed-canvas"),
      overlay: root.querySelector("#ed-overlay"),
      wrap: root.querySelector("#ed-wrap"),
      stage: root.querySelector("#ed-stage"),
      palette: root.querySelector("#ed-palette"),
      cur: root.querySelector("#ed-cur"),
      status: root.querySelector("#ed-status"),
      zoom: root.querySelector("#ed-zoom"),
      grid: root.querySelector("#ed-grid"),
      heat: root.querySelector("#ed-heat"),
      color: root.querySelector("#ed-color"),
      nxlabel: root.querySelector("#ed-nxlabel"),
    };
    els.ctx = els.canvas.getContext("2d", { willReadFrequently: true });
    els.octx = els.overlay.getContext("2d");

    // tool buttons
    root.querySelectorAll("[data-tool]").forEach((b) =>
      b.addEventListener("click", () => setTool(b.dataset.tool)));
    root.querySelector("#ed-undo").onclick = undo;
    root.querySelector("#ed-redo").onclick = redo;
    root.querySelector("#ed-zoom-in").onclick = () => setZoom(S.zoom + 1);
    root.querySelector("#ed-zoom-out").onclick = () => setZoom(S.zoom - 1);
    els.grid.onchange = renderOverlay;
    els.heat.onchange = renderOverlay;
    root.querySelector("#ed-add").onclick = addCurrentColor;
    root.querySelector("#ed-dl-1x").onclick = () => download(1);
    root.querySelector("#ed-dl-nx").onclick = () => download(8);
    root.querySelector("#ed-close").onclick = () => show(false);
    els.cur.addEventListener("click", () => {
      const hex = els.cur.dataset.hex || "";
      if (!hex) return;
      if (navigator.clipboard) navigator.clipboard.writeText(hex);
      const prev = els.cur.textContent;
      els.cur.textContent = "copied ✓";
      setTimeout(() => { els.cur.textContent = prev; }, 800);
    });

    // pointer painting on the overlay (top layer)
    const ov = els.overlay;
    ov.addEventListener("pointerdown", onDown);
    ov.addEventListener("pointermove", onMove);
    ov.addEventListener("pointerup", onUp);
    ov.addEventListener("pointercancel", onUp);
    ov.style.touchAction = "none";

    // scroll / trackpad-pinch to zoom, centered on the cursor
    els.stage.addEventListener("wheel", onWheel, { passive: false });

    // click the dimmed backdrop (outside the modal) to close
    root.addEventListener("pointerdown", (e) => { if (e.target === root) show(false); });

    window.addEventListener("keydown", onKey);
  }

  function show(v) { root.style.display = v ? "flex" : "none"; }

  // ---- initialization from a /api/restore result -----------------------------
  function initFromResult(result) {
    const img = new Image();
    img.onload = () => {
      const w = img.naturalWidth, h = img.naturalHeight;
      const tmp = document.createElement("canvas");
      tmp.width = w; tmp.height = h;
      const tctx = tmp.getContext("2d", { willReadFrequently: true });
      tctx.imageSmoothingEnabled = false;
      tctx.drawImage(img, 0, 0);
      const data = tctx.getImageData(0, 0, w, h).data;

      // Seed the palette from the restore palette, then map every pixel to an
      // index (adding any stray color, and using -1 for transparent).
      const palette = (result.palette || []).map((hx) => {
        const h2 = hx.replace("#", "");
        return { r: parseInt(h2.slice(0, 2), 16), g: parseInt(h2.slice(2, 4), 16),
                 b: parseInt(h2.slice(4, 6), 16), a: 255, source: "extracted" };
      });
      const lookup = new Map();
      palette.forEach((c, i) => lookup.set(paletteKey(c.r, c.g, c.b), i));

      const indices = new Int16Array(w * h);
      for (let p = 0; p < w * h; p++) {
        const r = data[p * 4], g = data[p * 4 + 1], b = data[p * 4 + 2], a = data[p * 4 + 3];
        if (a < 128) { indices[p] = TRANSPARENT; continue; }
        const k = paletteKey(r, g, b);
        let idx = lookup.get(k);
        if (idx === undefined) {
          idx = palette.length;
          palette.push({ r, g, b, a: 255, source: "custom" });
          lookup.set(k, idx);
        }
        indices[p] = idx;
      }

      S = {
        _result: result,
        w, h, palette, indices,
        activeIndex: 0, tool: "pencil",
        zoom: fitZoom(w, h),
        history: [], future: [], dirty: false,
        heatImg: null,
      };
      if (result.confidence_map) {
        const hi = new Image();
        hi.onload = () => { S.heatImg = hi; renderOverlay(); };
        hi.src = result.confidence_map;
      }
      els.canvas.width = w; els.canvas.height = h;
      renderPalette(); setZoom(S.zoom); render(); setTool("pencil");
      setStatus(`${w}×${h}, ${palette.length} colors`);
    };
    img.src = result.native_png;
  }

  // ---- rendering -------------------------------------------------------------
  function colorAt(idx) {
    if (idx === TRANSPARENT) return [0, 0, 0, 0];
    const c = S.palette[idx];
    return [c.r, c.g, c.b, c.a];
  }

  function render() {
    const { w, h, indices } = S;
    const imgData = els.ctx.createImageData(w, h);
    const d = imgData.data;
    for (let p = 0; p < w * h; p++) {
      const [r, g, b, a] = colorAt(indices[p]);
      d[p * 4] = r; d[p * 4 + 1] = g; d[p * 4 + 2] = b; d[p * 4 + 3] = a;
    }
    els.ctx.putImageData(imgData, 0, 0);
    renderOverlay();
  }

  function renderOverlay() {
    if (!S) return;
    const { w, h, zoom } = S;
    const dw = w * zoom, dh = h * zoom;
    els.overlay.width = dw; els.overlay.height = dh;
    const o = els.octx;
    o.clearRect(0, 0, dw, dh);
    o.imageSmoothingEnabled = false;
    if (els.heat.checked && S.heatImg) {
      o.globalAlpha = 0.5;
      o.drawImage(S.heatImg, 0, 0, dw, dh);
      o.globalAlpha = 1;
    }
    if (els.grid.checked && zoom >= 4) {
      o.strokeStyle = "rgba(128,128,128,0.4)";
      o.lineWidth = 1;
      o.beginPath();
      for (let x = 0; x <= w; x++) { o.moveTo(x * zoom + 0.5, 0); o.lineTo(x * zoom + 0.5, dh); }
      for (let y = 0; y <= h; y++) { o.moveTo(0, y * zoom + 0.5); o.lineTo(dw, y * zoom + 0.5); }
      o.stroke();
    }
  }

  // Pick an initial zoom that fills most of the available editor stage,
  // estimated from the viewport (modal width minus the side panel + chrome).
  function fitZoom(w, h) {
    const availW = Math.min(1600, window.innerWidth * 0.98) - 320; // side panel + paddings
    const availH = window.innerHeight * 0.96 - 130; // toolbar + paddings
    const fit = Math.floor(Math.min(availW / w, availH / h));
    return clamp(fit, 1, 40);
  }

  function setZoom(z) {
    S.zoom = clamp(Math.round(z), 1, 40);
    const dw = S.w * S.zoom, dh = S.h * S.zoom;
    els.canvas.style.width = dw + "px"; els.canvas.style.height = dh + "px";
    els.canvas.style.imageRendering = "pixelated";
    els.overlay.style.width = dw + "px"; els.overlay.style.height = dh + "px";
    els.wrap.style.width = dw + "px"; els.wrap.style.height = dh + "px";
    els.zoom.textContent = S.zoom + "×";
    renderOverlay();
  }

  // Wheel/pinch zoom that keeps the cell under the cursor anchored.
  function onWheel(e) {
    if (!S) return;
    e.preventDefault();
    const before = S.zoom;
    const step = Math.abs(e.deltaY) > 30 ? 2 : 1;
    const next = clamp(before + (e.deltaY < 0 ? step : -step), 1, 32);
    if (next === before) return;
    // fractional position of the cursor within the canvas content (0..1)
    const rect = els.overlay.getBoundingClientRect();
    const fx = clamp((e.clientX - rect.left) / rect.width, 0, 1);
    const fy = clamp((e.clientY - rect.top) / rect.height, 0, 1);
    setZoom(next);
    // re-anchor: scroll so the same fractional point sits under the cursor
    const sRect = els.stage.getBoundingClientRect();
    els.stage.scrollLeft = fx * S.w * S.zoom - (e.clientX - sRect.left);
    els.stage.scrollTop = fy * S.h * S.zoom - (e.clientY - sRect.top);
  }

  // ---- palette UI ------------------------------------------------------------
  function renderPalette() {
    els.palette.innerHTML = "";
    S.palette.forEach((c, i) => {
      const sw = document.createElement("button");
      sw.className = "ed-sw" + (i === S.activeIndex ? " active" : "");
      sw.style.background = `rgba(${c.r},${c.g},${c.b},${c.a / 255})`;
      sw.title = rgbaHex(c) + (c.source === "custom" ? " (custom)" : "");
      sw.onclick = () => selectIndex(i);
      sw.ondblclick = () => recolorIndex(i);
      els.palette.appendChild(sw);
    });
    const c = S.palette[S.activeIndex];
    const hex = c ? rgbaHex(c) : "";
    els.cur.textContent = hex;
    els.cur.dataset.hex = hex;
  }

  function selectIndex(i) {
    S.activeIndex = i;
    if (S.tool === "eraser" || S.tool === "eyedropper") setTool("pencil");
    renderPalette();
  }

  function addCurrentColor() {
    const h = els.color.value.replace("#", "");
    const c = { r: parseInt(h.slice(0, 2), 16), g: parseInt(h.slice(2, 4), 16),
                b: parseInt(h.slice(4, 6), 16), a: 255, source: "custom" };
    // reuse an identical existing entry instead of duplicating
    let idx = S.palette.findIndex((p) => sameColor(p, c));
    if (idx === -1) { idx = S.palette.length; S.palette.push(c); }
    S.activeIndex = idx;
    renderPalette(); setTool("pencil");
  }

  function recolorIndex(i) {
    const cur = S.palette[i];
    els.color.value = rgbaHex(cur).slice(0, 7);
    els.color.click();
    const handler = () => {
      const h = els.color.value.replace("#", "");
      pushHistory();
      S.palette[i] = { r: parseInt(h.slice(0, 2), 16), g: parseInt(h.slice(2, 4), 16),
                       b: parseInt(h.slice(4, 6), 16), a: 255,
                       source: cur.source === "extracted" ? "extracted" : "custom" };
      S.dirty = true;
      renderPalette(); render();
      els.color.removeEventListener("change", handler);
    };
    els.color.addEventListener("change", handler);
  }

  // ---- tools -----------------------------------------------------------------
  function setTool(t) {
    S.tool = t;
    root.querySelectorAll("[data-tool]").forEach((b) =>
      b.classList.toggle("active", b.dataset.tool === t));
  }

  function cellFromEvent(e) {
    const rect = els.overlay.getBoundingClientRect();
    const sx = S.w / rect.width, sy = S.h / rect.height;
    const x = Math.floor((e.clientX - rect.left) * sx);
    const y = Math.floor((e.clientY - rect.top) * sy);
    if (x < 0 || y < 0 || x >= S.w || y >= S.h) return null;
    return { x, y };
  }

  function onDown(e) {
    const cell = cellFromEvent(e);
    if (!cell) return;
    els.overlay.setPointerCapture(e.pointerId);
    if (S.tool === "eyedropper") { eyedrop(cell); return; }
    if (S.tool === "bucket") { pushHistory(); bucketFill(cell); commit(); return; }
    strokeSnapshot = S.indices.slice();
    painting = true; lastCell = cell;
    applyAt(cell);
    render();
  }

  function onMove(e) {
    if (!S) return;
    const cell = cellFromEvent(e);
    if (cell) setStatus(`${S.w}×${S.h} · (${cell.x}, ${cell.y})`);
    if (!painting || !cell) return;
    if (lastCell) lineCells(lastCell, cell).forEach(applyAt);
    else applyAt(cell);
    lastCell = cell;
    render();
  }

  function onUp(e) {
    if (!painting) return;
    painting = false; lastCell = null;
    // commit the pre-stroke snapshot to history only if something changed
    if (strokeSnapshot && !arraysEqual(strokeSnapshot, S.indices)) {
      S.history.push(strokeSnapshot); S.future = []; S.dirty = true; trimHistory();
    }
    strokeSnapshot = null;
  }

  function applyAt({ x, y }) {
    const p = y * S.w + x;
    S.indices[p] = S.tool === "eraser" ? TRANSPARENT : S.activeIndex;
  }

  function eyedrop({ x, y }) {
    const idx = S.indices[y * S.w + x];
    if (idx === TRANSPARENT) { setTool("eraser"); return; }
    selectIndex(idx);
  }

  function bucketFill({ x, y }) {
    const target = S.indices[y * S.w + x];
    const repl = S.tool === "eraser" ? TRANSPARENT : S.activeIndex;
    if (target === repl) return;
    const { w, h, indices } = S;
    const stack = [[x, y]];
    while (stack.length) {
      const [cx, cy] = stack.pop();
      if (cx < 0 || cy < 0 || cx >= w || cy >= h) continue;
      const p = cy * w + cx;
      if (indices[p] !== target) continue;
      indices[p] = repl;
      stack.push([cx + 1, cy], [cx - 1, cy], [cx, cy + 1], [cx, cy - 1]);
    }
  }

  // Bresenham between two cells so fast drags don't leave gaps.
  function lineCells(a, b) {
    const cells = [];
    let x0 = a.x, y0 = a.y;
    const dx = Math.abs(b.x - x0), dy = Math.abs(b.y - y0);
    const sx = x0 < b.x ? 1 : -1, sy = y0 < b.y ? 1 : -1;
    let err = dx - dy;
    while (true) {
      cells.push({ x: x0, y: y0 });
      if (x0 === b.x && y0 === b.y) break;
      const e2 = 2 * err;
      if (e2 > -dy) { err -= dy; x0 += sx; }
      if (e2 < dx) { err += dx; y0 += sy; }
    }
    return cells;
  }

  function commit() { S.dirty = true; trimHistory(); render(); }

  // ---- history ---------------------------------------------------------------
  function pushHistory() { S.history.push(S.indices.slice()); S.future = []; trimHistory(); }
  function trimHistory() { if (S.history.length > 80) S.history.shift(); }

  function undo() {
    if (!S.history.length) return;
    S.future.push(S.indices.slice());
    S.indices = S.history.pop();
    render();
  }
  function redo() {
    if (!S.future.length) return;
    S.history.push(S.indices.slice());
    S.indices = S.future.pop();
    render();
  }

  function arraysEqual(a, b) {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
    return true;
  }

  // ---- export ----------------------------------------------------------------
  async function download(upscale) {
    const palette = S.palette.map(rgbaHex);
    const indices = Array.from(S.indices);
    setStatus("Exporting…");
    try {
      const r = await fetch("/api/export", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ width: S.w, height: S.h, palette, indices, upscale }),
      });
      if (!r.ok) { let m = `HTTP ${r.status}`; try { m = (await r.json()).error || m; } catch {} throw new Error(m); }
      const d = await r.json();
      const uri = upscale > 1 ? d.preview_png : d.native_png;
      const a = document.createElement("a");
      a.href = uri;
      a.download = `pixel-perfect_${S.w}x${S.h}${upscale > 1 ? "@" + upscale + "x" : ""}.png`;
      a.click();
      setStatus(`Exported ${d.width}×${d.height}${upscale > 1 ? " @" + upscale + "×" : ""}`);
    } catch (e) {
      setStatus("⚠ " + e.message);
    }
  }

  function setStatus(t) { els.status.textContent = t; }

  // ---- keyboard --------------------------------------------------------------
  function onKey(e) {
    if (!S || root.style.display === "none") return;
    if (e.target.tagName === "INPUT") return;
    if (e.key === "Escape") { show(false); return; }
    const k = e.key.toLowerCase();
    if ((e.ctrlKey || e.metaKey) && k === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
    if (k === "b") setTool("pencil");
    else if (k === "e") setTool("eraser");
    else if (k === "g") setTool("bucket");
    else if (k === "i") setTool("eyedropper");
    else if (e.key === "+" || e.key === "=") setZoom(S.zoom + 1);
    else if (e.key === "-") setZoom(S.zoom - 1);
  }
})();
