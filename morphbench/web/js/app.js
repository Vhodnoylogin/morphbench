"use strict";

// ---- the page as a whole ---------------------------------------------------------------------
const POSITION_METHODS = new Set(["set_slider", "set_sliders", "reset_sliders"]);
const COLOUR_METHODS = new Set(["colour_by"]);

class App {
  constructor(data) {
    this.data = data;
    this.bench = new BenchMirror(data);
    this.lastCall = "";
    this.scale = 1.0;
    this.canvas = document.getElementById("canvas");
    this.renderer = new Renderer(this.canvas, data.settings);
    for (const name of this.bench.shape_names()) this.renderer.upload(this.bench.shape(name));
    // Capsules go into the buffers once, every chunk of every bone: the sliders do not move
    // them and they all share one colour, while which of them to draw is decided by
    // collider_mesh() on every frame.
    for (const chunk of this.bench.collider_meshes()) this.renderer.uploadColliders(chunk);
    this.renderer.uploadColliders(this.bench.bumper_mesh());
    this.refreshPositions();
    this.refreshColours();
    this.panel = new Panel(this, document.getElementById("panel"));
    this.bindMouse();
    new ResizeObserver(() => this.draw()).observe(this.canvas.parentElement);
    this.panel.refresh();
    this.draw();
  }
  // The one door to every action: the name of a facade method and its arguments.
  invoke(method, ...args) {
    this.panel.error.textContent = "";
    try {
      this.bench[method](...args);
    } catch (e) {
      this.panel.error.textContent = String(e.message || e);
      return;
    }
    this.lastCall = "bench." + method + "(" + args.map((a) => JSON.stringify(a)).join(", ") + ")";
    if (POSITION_METHODS.has(method)) this.refreshPositions();
    if (COLOUR_METHODS.has(method)) this.refreshColours();
    this.panel.refresh();
    this.draw();
  }
  // Positions with the sliders applied, and the normals that follow from them, into the
  // buffers; the normals are recomputed after every slider move, because the shading is
  // taken off the deformed body.
  refreshPositions() {
    for (const name of this.bench.shape_names()) {
      const s = this.bench.shape(name);
      this.bench.vertex_normals(name);         // deformed() inside: positions and normals at once
      this.renderer.setPositions(s);
      this.renderer.setNormals(s);
    }
  }
  // The value comes from the facade, the colour is made here - by the same rule the rasteriser uses.
  refreshColours() {
    for (const name of this.bench.shape_names()) {
      const s = this.bench.shape(name);
      if (!s.triCount) continue;
      const key = this.bench.vertex_colour_key(name);
      let colours;
      if (key === null) {
        colours = new Float32Array(s.count * 3).fill(Palette.SHADE);
      } else if (this.bench.view.colouring === "bone") {
        const palette = Palette.bones(s.boneNames.length), last = Math.max(s.boneNames.length - 1, 0);
        colours = new Float32Array(s.count * 3);
        for (let i = 0; i < s.count; i++) {
          const k = key[i];
          if (k < 0) { colours[i * 3] = Palette.NO_BONE[0]; colours[i * 3 + 1] = Palette.NO_BONE[1]; colours[i * 3 + 2] = Palette.NO_BONE[2]; }
          else { const j = clamp(k, 0, last) * 3; colours[i * 3] = palette[j]; colours[i * 3 + 1] = palette[j + 1]; colours[i * 3 + 2] = palette[j + 2]; }
        }
      } else {
        colours = Palette.heat(key);
      }
      this.renderer.setColours(s, colours);
    }
  }
  // The canvas size is part of the view state as well: it reaches the core through the same
  // resize that --size goes through.
  draw() {
    this.renderer.resize();
    const w = this.canvas.width, h = this.canvas.height, view = this.bench.view;
    if (w !== view.width || h !== view.height) { this.invoke("resize", w, h); return; }
    const r = this.renderer.draw(this.bench);
    if (r) this.scale = r.scale;
  }
  // The cursor point in fractions of half the shorter side of the canvas, measured from the
  // centre, right and up - out of canvas pixels, allowing for the screen density and for
  // where the canvas sits on the page.
  cursorFraction(e) {
    const c = this.canvas, rect = c.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    const px = (e.clientX - rect.left) * dpr, py = (e.clientY - rect.top) * dpr;
    const w = c.width, h = c.height, m = Math.min(w, h) * 0.5;
    return [(px - w * 0.5) / m, (h * 0.5 - py) / m];
  }
  bindMouse() {
    const c = this.canvas;
    let drag = null;
    c.addEventListener("contextmenu", (e) => e.preventDefault());
    c.addEventListener("pointerdown", (e) => {
      drag = { button: e.button, x: e.clientX, y: e.clientY };
      try { c.setPointerCapture(e.pointerId); } catch (_) { /* a pointer without capture is no great loss */ }
    });
    c.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      drag.x = e.clientX; drag.y = e.clientY;
      if (drag.button === 0) {
        const k = this.bench.settings.orbitSensitivity;
        this.invoke("orbit", rnd(dx * k, 2), rnd(dy * k, 2));
      } else if (drag.button === 2) {
        // Screen pixels into model units through the frame scale - and into the core by the
        // same method the command line calls.
        const dpr = window.devicePixelRatio || 1;
        this.invoke("pan_by", rnd(dx * dpr / this.scale, 3), rnd(-dy * dpr / this.scale, 3));
      }
    });
    const stop = (e) => { drag = null; try { c.releasePointerCapture(e.pointerId); } catch (_) {} };
    c.addEventListener("pointerup", stop);
    c.addEventListener("pointercancel", stop);
    // The wheel zooms towards the point under the cursor: the facade's zoom_at with the new
    // zoom and the fractions of the frame.
    c.addEventListener("wheel", (e) => {
      e.preventDefault();
      const f = this.cursorFraction(e);
      const z = rnd(this.bench.view.zoom * Math.exp(-e.deltaY * this.bench.settings.wheelZoomRate), 3);
      this.invoke("zoom_at", z, rnd(f[0], 3), rnd(f[1], 3));
    }, { passive: false });
    c.addEventListener("dblclick", () => { this.invoke("pan", 0, 0); this.invoke("zoom", 1.0); });
  }
}
