"use strict";

// ---- rendering: WebGL2, an orthographic camera, shading that matches the rasteriser -------
// Smooth shading: the light is worked out at the vertex from its own normal and is stretched
// along the triangle together with the colour - exactly the vcols × lit the rasteriser puts
// together. Same formula: ambient + diffuse·max(n·L, 0) + fill·max(-n·L, 0).
const VERTEX_SHADER = "#version 300 es\n" +
  "precision highp float;\n" +
  "in vec3 aPos;\n" +
  "in vec3 aNrm;\n" +
  "in vec3 aCol;\n" +
  "uniform vec3 uRight, uUp, uForward, uCentre;\n" +
  "uniform float uScale, uZc, uZr;\n" +
  "uniform vec2 uHalf;\n" +
  "uniform vec3 uLight;\n" +
  "uniform float uAmbient, uDiffuse, uFill;\n" +
  "out vec3 vWorld;\n" +
  "out vec3 vCol;\n" +
  "out vec3 vLit;\n" +
  "void main() {\n" +
  "  vec3 d = aPos - uCentre;\n" +                         // (v - centre) @ basis.T, as in the rasteriser
  "  float x = dot(d, uRight) * uScale;\n" +
  "  float y = dot(d, uUp) * uScale;\n" +
  "  float z = dot(d, uForward);\n" +                       // depth: the smaller, the nearer the viewer
  "  gl_Position = vec4(x / uHalf.x, y / uHalf.y, (z - uZc) / uZr, 1.0);\n" +
  "  vWorld = aPos;\n" +
  "  vCol = aCol;\n" +
  "  float lam = dot(normalize(aNrm), uLight);\n" +
  "  vLit = aCol * (uAmbient + uDiffuse * clamp(lam, 0.0, 1.0) + uFill * clamp(-lam, 0.0, 1.0));\n" +
  "}\n";

// Flat shading (shading = flat in the settings): the triangle normal comes from the screen
// derivatives of the world position - the normal of the plane, turned towards the viewer, which
// for front faces is the geometric normal of the rasteriser. The light is in world coordinates,
// and so is the normal.
const FRAGMENT_SHADER = "#version 300 es\n" +
  "precision highp float;\n" +
  "in vec3 vWorld;\n" +
  "in vec3 vCol;\n" +
  "in vec3 vLit;\n" +
  "uniform vec3 uLight;\n" +
  "uniform float uAmbient, uDiffuse, uFill;\n" +
  "uniform int uFlat;\n" +
  "uniform float uAlpha;\n" +                                    // 1.0 on the body; on capsules - colliderOpacity
  "out vec4 outColour;\n" +
  "void main() {\n" +
  "  vec3 lit = vLit;\n" +
  "  if (uFlat == 1) {\n" +
  "    vec3 n = normalize(cross(dFdx(vWorld), dFdy(vWorld)));\n" +
  "    if (!gl_FrontFacing) n = -n;\n" +                       // normal by the winding, as in the rasteriser
  "    float lam = dot(n, uLight);\n" +
  "    lit = vCol * (uAmbient + uDiffuse * clamp(lam, 0.0, 1.0) + uFill * clamp(-lam, 0.0, 1.0));\n" +
  "  }\n" +
  "  outColour = vec4(clamp(lit, 0.0, 1.0), uAlpha);\n" +
  "}\n";

class Renderer {
  constructor(canvas, settings) {
    this.canvas = canvas;
    this.settings = settings;
    const gl = canvas.getContext("webgl2", { antialias: true, preserveDrawingBuffer: true });
    if (!gl) throw new Error(T.errNoWebGL);
    this.gl = gl;
    this.program = this._program(VERTEX_SHADER, FRAGMENT_SHADER);
    this.attr = { pos: gl.getAttribLocation(this.program, "aPos"), nrm: gl.getAttribLocation(this.program, "aNrm"),
                  col: gl.getAttribLocation(this.program, "aCol") };
    this.uni = {};
    for (const name of ["uRight", "uUp", "uForward", "uCentre", "uScale", "uZc", "uZr", "uHalf",
                        "uLight", "uAmbient", "uDiffuse", "uFill", "uFlat", "uAlpha"])
      this.uni[name] = gl.getUniformLocation(this.program, name);
    this.meshes = new Map();
    this.bg = settings.background.map((x) => x / 255.0);
    this.flat = settings.shading === "flat";
    // The capsule layer: colour and opacity from the same settings keys the rasteriser reads.
    this.colliderTint = settings.colliderColour.map((x) => x / 255.0);
    this.colliderAlpha = settings.colliderOpacity;
  }
  _shader(type, src) {
    const gl = this.gl, sh = gl.createShader(type);
    gl.shaderSource(sh, src); gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error(say(T.errShader, { log: gl.getShaderInfoLog(sh) }));
    return sh;
  }
  _program(vs, fs) {
    const gl = this.gl, p = gl.createProgram();
    gl.attachShader(p, this._shader(gl.VERTEX_SHADER, vs));
    gl.attachShader(p, this._shader(gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(say(T.errProgram, { log: gl.getProgramInfoLog(p) }));
    return p;
  }
  _attribute(buffer, data, location, usage) {
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, data, usage);
    gl.enableVertexAttribArray(location);
    gl.vertexAttribPointer(location, 3, gl.FLOAT, false, 0, 0);
  }
  // buffers of one shape: positions, normals and colours change, the triangles do not
  upload(shape) {
    const gl = this.gl;
    if (!shape.triCount) return;
    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    const pos = gl.createBuffer(), nrm = gl.createBuffer(), col = gl.createBuffer();
    this._attribute(pos, shape.pos, this.attr.pos, gl.DYNAMIC_DRAW);
    this._attribute(nrm, shape.nrm, this.attr.nrm, gl.DYNAMIC_DRAW);
    this._attribute(col, shape.count * 12, this.attr.col, gl.DYNAMIC_DRAW);
    const idx = gl.createBuffer();
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, idx);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, shape.tris, gl.STATIC_DRAW);
    gl.bindVertexArray(null);
    this.meshes.set(shape.name, { vao, pos, nrm, col, count: shape.tris.length,
      type: shape.tris instanceof Uint32Array ? gl.UNSIGNED_INT : gl.UNSIGNED_SHORT });
  }
  _refill(buffer, data) {
    if (!buffer) return;
    this.gl.bindBuffer(this.gl.ARRAY_BUFFER, buffer);
    this.gl.bufferSubData(this.gl.ARRAY_BUFFER, 0, data);
  }
  setPositions(shape) { const m = this.meshes.get(shape.name); if (m) this._refill(m.pos, shape.pos); }
  setNormals(shape) { const m = this.meshes.get(shape.name); if (m) this._refill(m.nrm, shape.nrm); }
  setColours(shape, colours) { const m = this.meshes.get(shape.name); if (m) this._refill(m.col, colours); }
  // A chunk of capsules gets the same buffers as a shape of the mesh, but a single colour for
  // every vertex: the shader lays the shading on it from the normal itself, by the same formula
  // it uses on skin.
  uploadColliders(chunk) {
    if (!chunk || !chunk.triCount) return;
    this.upload(chunk);
    const t = this.colliderTint, colours = new Float32Array(chunk.count * 3);
    for (let i = 0; i < chunk.count; i++) { colours[i * 3] = t[0]; colours[i * 3 + 1] = t[1]; colours[i * 3 + 2] = t[2]; }
    this.setColours(chunk, colours);
  }
  // The capsule chunks that have to be drawn right now: the capsules of the visible bones when
  // the layer is on, and the bumper on top of that by its own flag. No skeleton, or the layer
  // switched off - nothing.
  _colliderChunks(bench) {
    const view = bench.view, out = [];
    if (!view.colliders || !bench.has_skeleton()) return out;
    for (const chunk of bench.collider_mesh().concat([view.bumper ? bench.bumper_mesh() : null]))
      if (chunk && chunk.triCount && this.meshes.has(chunk.name)) out.push(chunk);
    return out;
  }
  resize() {
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(1, Math.round(this.canvas.clientWidth * dpr));
    const h = Math.max(1, Math.round(this.canvas.clientHeight * dpr));
    if (this.canvas.width !== w || this.canvas.height !== h) { this.canvas.width = w; this.canvas.height = h; }
  }
  // The depth range is the visible vertices projected onto the view axis, so that the buffer cuts
  // nothing off. Capsules enter it when they are on, and only the visible ones (the very chunks
  // that get drawn): the bumper is four times the body and would otherwise be clipped.
  _depthRange(bench, centre, forward) {
    let zmin = Infinity, zmax = -Infinity;
    const clouds = bench.visible_shapes().map((n) => bench.shape(n)).filter((s) => s.triCount > 0)
      .concat(this._colliderChunks(bench));
    for (const s of clouds) {
      const p = s.pos;
      for (let i = 0, n = p.length; i < n; i += 3) {
        const z = (p[i] - centre[0]) * forward[0] + (p[i + 1] - centre[1]) * forward[1] + (p[i + 2] - centre[2]) * forward[2];
        if (z < zmin) zmin = z; if (z > zmax) zmax = z;
      }
    }
    return [zmin, zmax];
  }
  draw(bench) {
    const gl = this.gl, view = bench.view;
    this.resize();
    const w = this.canvas.width, h = this.canvas.height;
    gl.viewport(0, 0, w, h);
    gl.clearColor(this.bg[0], this.bg[1], this.bg[2], 1.0);
    gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LESS); gl.disable(gl.CULL_FACE);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    // The whole model, the aim sphere or a panorama - the mirror of the core decides what is
    // framed; nothing to show means an empty canvas, just as the rasteriser has nothing to draw.
    let framed;
    try { framed = bench.framing(); } catch (_) { return null; }
    const c = framed[0], half = framed[1];
    const basis = view.basis();
    const span = half * 2.0;
    const scale = (Math.min(w, h) * this.settings.frameFill) / Math.max(span, 1e-3) * view.zoom;
    const [zmin, zmax] = this._depthRange(bench, c, basis.forward);
    gl.useProgram(this.program);
    gl.uniform3fv(this.uni.uRight, basis.right);
    gl.uniform3fv(this.uni.uUp, basis.up);
    gl.uniform3fv(this.uni.uForward, basis.forward);
    gl.uniform3fv(this.uni.uCentre, c);
    gl.uniform1f(this.uni.uScale, scale);
    gl.uniform1f(this.uni.uZc, 0.5 * (zmin + zmax));
    gl.uniform1f(this.uni.uZr, Math.max(0.5 * (zmax - zmin), 1e-3) * 1.01);
    gl.uniform2f(this.uni.uHalf, w * 0.5, h * 0.5);
    // The light comes from the view state on every frame: when it follows the camera it travels
    // with the angle.
    gl.uniform3fv(this.uni.uLight, bench.light_vector());
    gl.uniform1f(this.uni.uAmbient, view.ambient);
    gl.uniform1f(this.uni.uDiffuse, view.diffuse);
    gl.uniform1f(this.uni.uFill, view.fill);
    gl.uniform1i(this.uni.uFlat, this.flat ? 1 : 0);
    gl.uniform1f(this.uni.uAlpha, 1.0);
    for (const name of bench.visible_shapes()) {
      const m = this.meshes.get(name);
      if (!m) continue;
      gl.bindVertexArray(m.vao);
      gl.drawElements(gl.TRIANGLES, m.count, m.type, 0);
    }
    this._overlayColliders(bench);
    gl.bindVertexArray(null);
    return { scale: scale };
  }
  // Capsules over the body - translucent, with a depth of their own: the mirror of the
  // rasteriser's _overlay_colliders. The point is that both shells are visible at once: inside
  // the body a capsule shows through the skin, outside it lies on the background. That is why
  // the body's depth does not cut the capsules - the depth buffer is cleared once for the whole
  // layer before it, and the capsules sort only against each other (the near wall hides the far
  // one and the neighbouring capsule, not the body). The chunks go by bone, but their buffer is
  // shared: one buffer per bone and the capsules would cut each other by drawing order instead
  // of by depth. The body is drawn by this point, and nobody needs its depth any more. The
  // vertex colour is one per chunk, the light is the same formula of the same shader, the
  // opacity is uAlpha.
  _overlayColliders(bench) {
    const chunks = this._colliderChunks(bench);
    if (!chunks.length) return;
    const gl = this.gl;
    gl.enable(gl.BLEND);
    // The canvas alpha stays at one: otherwise the page would show through the capsules.
    gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ZERO, gl.ONE);
    gl.uniform1f(this.uni.uAlpha, this.colliderAlpha);
    gl.clear(gl.DEPTH_BUFFER_BIT);
    for (const chunk of chunks) {
      const m = this.meshes.get(chunk.name);
      gl.bindVertexArray(m.vao);
      gl.drawElements(gl.TRIANGLES, m.count, m.type, 0);
    }
    gl.uniform1f(this.uni.uAlpha, 1.0);
    gl.disable(gl.BLEND);
  }
}
