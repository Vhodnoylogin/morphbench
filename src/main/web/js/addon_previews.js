"use strict";

// Drawing helpers shared by the main workspace and independent preview surfaces.
// Geometry, camera and colouring keys still come through the facade; these helpers
// only transfer its answers to a renderer or translate canvas input coordinates.
const ViewportDrawing = {
  refreshPositions(bench, renderer) {
    for (const name of bench.shape_names()) {
      const shape = bench.shape(name);
      bench.vertex_normals(name);
      renderer.setPositions(shape);
      renderer.setNormals(shape);
    }
  },
  refreshColours(bench, renderer) {
    for (const name of bench.shape_names()) {
      const shape = bench.shape(name);
      if (!shape.triCount) continue;
      const key = bench.vertex_colour_key(name);
      let colours;
      if (key === null) {
        colours = new Float32Array(shape.count * 3).fill(Palette.SHADE);
      } else if (bench.view.colouring === "bone") {
        const palette = Palette.bones(shape.boneNames.length), last = Math.max(shape.boneNames.length - 1, 0);
        colours = new Float32Array(shape.count * 3);
        for (let i = 0; i < shape.count; i++) {
          const bone = key[i];
          if (bone < 0) {
            colours[i * 3] = Palette.NO_BONE[0];
            colours[i * 3 + 1] = Palette.NO_BONE[1];
            colours[i * 3 + 2] = Palette.NO_BONE[2];
          } else {
            const index = clamp(bone, 0, last) * 3;
            colours[i * 3] = palette[index];
            colours[i * 3 + 1] = palette[index + 1];
            colours[i * 3 + 2] = palette[index + 2];
          }
        }
      } else {
        colours = Palette.heat(key);
      }
      renderer.setColours(shape, colours);
    }
  },
  cursorFraction(canvas, event) {
    const rect = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    const px = (event.clientX - rect.left) * dpr, py = (event.clientY - rect.top) * dpr;
    const width = canvas.width, height = canvas.height, half = Math.min(width, height) * 0.5;
    return [(px - width * 0.5) / half, (height * 0.5 - py) / half];
  }
};

// A host-owned canvas, never an add-on-owned iframe or another whole App. Each
// surface owns its facade, GPU context, input state and scheduled render work.
class AddonPreviewSurface {
  constructor(container, payload, options = {}) {
    this.disposed = false;
    this.renderer = null;
    this.observer = null;
    this.pendingDraw = null;
    this.listeners = [];
    this.drag = null;
    this.scale = 1;
    this.onCameraChange = options.onCameraChange || null;
    this.element = el("section", {class:"addon-preview-surface"});
    const caption = payload.names.nif || payload.names.skeleton || T.noMesh;
    this.element.appendChild(el("h3", {class:"addon-preview-caption", text:caption}));
    this.canvas = el("canvas", {class:"addon-preview-canvas", "aria-label":caption, role:"img", tabindex:"0"});
    this.element.appendChild(this.canvas);
    try {
      this.bench = new BenchMirror(payload);
      // This preview surface renders body geometry. Capsule/node-only NIFs need
      // the ordinary collider workspace rather than a successful blank canvas.
      if (!this.bench.shape_names().some((name) => {
        const shape = this.bench.shape(name);
        return shape.count > 0 && shape.triCount > 0;
      })) throw Object.assign(Error(T.addonPreviewMesh), {code:"noMesh"});
      this.bench.workspace_mode("morphs");
      this.renderer = new Renderer(this.canvas, this.bench.settings);
      for (const name of this.bench.shape_names()) this.renderer.upload(this.bench.shape(name));
      this.refreshPositions();
      this.refreshColours();
      this.bindPointer();
      container.appendChild(this.element);
      this.observer = new ResizeObserver(() => this.requestDraw());
      this.observer.observe(this.element);
      this.draw();
    } catch (error) {
      this.dispose();
      throw error;
    }
  }
  refreshPositions() { ViewportDrawing.refreshPositions(this.bench, this.renderer); }
  refreshColours() { ViewportDrawing.refreshColours(this.bench, this.renderer); }
  cursorFraction(event) { return ViewportDrawing.cursorFraction(this.canvas, event); }
  cameraKey(state) {
    // Viewport dimensions and derived lighting are not new camera gestures.
    return JSON.stringify([state.yaw, state.pitch, state.zoom, state.pan, state.preset, state.focus]);
  }
  invoke(method, ...args) { return this.perform(method, args, true); }
  invokeSilent(method, ...args) { return this.perform(method, args, false); }
  perform(method, args, notify) {
    if (this.disposed) throw Object.assign(Error(T.addonFailure), {code:"closedPreview"});
    const before = this.bench.addon_view().state;
    const result = this.bench[method](...args);
    if (["set_slider", "set_sliders", "reset_sliders", "addon_set_morphs", "addon_reset_morphs"].includes(method)) this.refreshPositions();
    if (method === "colour_by") this.refreshColours();
    this.requestDraw();
    const after = this.bench.addon_view().state;
    if (notify && this.onCameraChange && this.cameraKey(before) !== this.cameraKey(after)) this.onCameraChange(after, method);
    return result;
  }
  resize() {
    if (this.disposed) return;
    this.renderer.resize();
    const width = this.canvas.width, height = this.canvas.height;
    if (width !== this.bench.view.width || height !== this.bench.view.height) this.bench.resize(width, height);
  }
  draw() {
    if (this.disposed) return;
    this.resize();
    const result = this.renderer.draw(this.bench);
    if (result) this.scale = result.scale;
  }
  requestDraw() {
    if (this.disposed || this.pendingDraw !== null) return;
    this.pendingDraw = window.requestAnimationFrame(() => {
      this.pendingDraw = null;
      if (!this.disposed) this.draw();
    });
  }
  listen(target, name, callback, options) {
    target.addEventListener(name, callback, options);
    this.listeners.push({target, name, callback, options});
  }
  releasePointer() {
    const drag = this.drag;
    this.drag = null;
    if (drag) {
      try { this.canvas.releasePointerCapture(drag.pointerId); } catch (_) { /* capture may already be lost */ }
    }
  }
  bindPointer() {
    const canvas = this.canvas;
    this.listen(canvas, "contextmenu", (event) => event.preventDefault());
    this.listen(canvas, "pointerdown", (event) => {
      if (this.disposed || ![0, 2].includes(event.button) || (this.drag && this.drag.pointerId !== event.pointerId)) return;
      event.preventDefault();
      this.drag = {button:event.button, pointerId:event.pointerId, x:event.clientX, y:event.clientY};
      try { canvas.setPointerCapture(event.pointerId); } catch (_) { /* the window listeners retain an uncaptured gesture */ }
    });
    this.listen(window, "pointermove", (event) => {
      const drag = this.drag;
      if (this.disposed || !drag || drag.pointerId !== event.pointerId) return;
      const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
      drag.x = event.clientX; drag.y = event.clientY;
      if (drag.button === 0) {
        const sensitivity = this.bench.settings.orbitSensitivity;
        this.invoke("orbit", rnd(dx * sensitivity, 2), rnd(dy * sensitivity, 2));
      } else {
        const dpr = window.devicePixelRatio || 1;
        this.invoke("pan_by", rnd(dx * dpr / this.scale, 3), rnd(-dy * dpr / this.scale, 3));
      }
    });
    const stop = (event) => { if (this.drag && this.drag.pointerId === event.pointerId) this.releasePointer(); };
    this.listen(window, "pointerup", stop);
    this.listen(window, "pointercancel", stop);
    this.listen(canvas, "lostpointercapture", stop);
    this.listen(window, "blur", () => this.releasePointer());
    this.listen(canvas, "wheel", (event) => {
      if (this.disposed) return;
      event.preventDefault();
      const point = this.cursorFraction(event);
      const zoom = rnd(this.bench.view.zoom * Math.exp(-event.deltaY * this.bench.settings.wheelZoomRate), 3);
      this.invoke("zoom_at", zoom, rnd(point[0], 3), rnd(point[1], 3));
    }, {passive:false});
    this.listen(canvas, "dblclick", () => {
      if (!this.disposed) this.invoke("addon_set_view", {pan:[0, 0], zoom:1});
    });
  }
  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.releasePointer();
    if (this.pendingDraw !== null) window.cancelAnimationFrame(this.pendingDraw);
    this.pendingDraw = null;
    if (this.observer) this.observer.disconnect();
    this.observer = null;
    for (const {target, name, callback, options} of this.listeners) target.removeEventListener(name, callback, options);
    this.listeners = [];
    if (this.renderer) this.renderer.dispose();
    this.onCameraChange = null;
    this.element.remove();
  }
}
