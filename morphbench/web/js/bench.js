"use strict";

// ---- mirror of morphbench/api.py: MorphBench -----------------------------------------------
// The method names are deliberately the facade's own, underscores and all: every button on the
// page calls a method from here, and that method answers one for one to a call of the core. The
// names are the API - making one of them look more like JavaScript would cut that tie.
class BenchMirror {
  constructor(data) {
    this.summary = data.summary;               // null - no mesh open (a page from the server)
    this.names = data.names;
    this.settings = data.settings;
    this.server = data.server || null;         // mesh list and environment - only when served
    this.shapes = new Map(data.shapes.map((raw) => [raw.name, new Shape(raw)]));
    this.morphList = data.morphs;
    this.deltas = {};
    for (const morph in data.deltas) {
      this.deltas[morph] = {};
      for (const shape in data.deltas[morph]) this.deltas[morph][shape] = new Deltas(data.deltas[morph][shape]);
    }
    this.strainData = {};
    for (const morph in data.strain) {
      this.strainData[morph] = {};
      for (const shape in data.strain[morph]) this.strainData[morph][shape] = new Strain(data.strain[morph][shape]);
    }
    this.targets = data.targets;
    // Capsules exist only when a skeleton is open: the bodies in pieces, one per bone, and the
    // bumper apart. They are unpacked and given their normals once - sliders never touch them.
    const raw = data.colliders || null;
    this._colliderMeshes = raw
      ? raw.bodies.map((b) => new ColliderMesh("colliders:" + b.bone, b, b.bone)) : null;
    this._bumperMesh = raw && raw.bumper ? new ColliderMesh("colliders:bumper", raw.bumper) : null;
    this.view = new ViewMirror(data.settings, data.presets, data.view);
    this._sliders = new Map(Object.entries(data.sliders));
  }

  is_open() { return this.summary !== null; }
  // skeleton and capsules: the core has already worked the geometry out, and it travels in the page
  has_skeleton() { return this._colliderMeshes !== null; }
  collider_bones() { return this.has_skeleton() ? this._colliderMeshes.map((m) => m.bone) : []; }
  // Bones with a body whose vertices sit in at least one visible shape - a mirror of the core's
  // visible_collider_bones(): hide the head and the head capsule is no longer wanted. A bone
  // "holds" a shape when it is the main bone of that shape's vertices (heldBones, counted by
  // the core); with collidersFollowParts off, every bone counts.
  visible_collider_bones() {
    const bones = this.collider_bones();
    if (!this.settings.collidersFollowParts) return bones;
    const held = new Set();
    for (const name of this.visible_shapes()) for (const b of this.shape(name).heldBones) held.add(b);
    return bones.filter((b) => held.has(b));
  }
  // every per-bone piece - they go into the buffers once
  collider_meshes() { return this.has_skeleton() ? this._colliderMeshes.slice() : []; }
  // the pieces of the visible bones only - a mirror of the core's collider_mesh(), which returns
  // them glued into one; here it stays a list, so no geometry is glued together every frame
  collider_mesh() {
    if (!this.has_skeleton()) return [];
    const keep = new Set(this.visible_collider_bones());
    return this._colliderMeshes.filter((m) => keep.has(m.bone));
  }
  bumper_mesh() { return this._bumperMesh; }
  show_colliders(on, bumper) { return this.view.show_colliders(on, bumper); }
  shape_names() { return Array.from(this.shapes.keys()).sort(); }
  shape(name) { const s = this.shapes.get(name); if (!s) throw new Error(say(T.errNoShape, { name })); return s; }
  morphs() { return this.morphList.slice(); }
  presets() { return this.view.presets; }
  visible_shapes() { return this.shape_names().filter((n) => this.view.is_visible(n)); }

  // sliders
  set_slider(name, value) {
    if (!this.morphList.includes(name)) throw new Error(say(T.errNoSlider, { name }));
    value = Number(value);
    if (value === 0.0) this._sliders.delete(name); else this._sliders.set(name, value);
    return this.sliders();
  }
  set_sliders(values) { for (const k in values) this.set_slider(k, values[k]); return this.sliders(); }
  sliders() { return Object.fromEntries(this._sliders); }
  reset_sliders() { this._sliders.clear(); return {}; }

  // geometry: base + the sum of amount × scale × int16 - the same sum Morph.apply does in the core
  deformed(name) {
    const s = this.shape(name);
    s.pos.set(s.base);
    for (const [morph, amount] of this._sliders) {
      const d = this.deltas[morph] && this.deltas[morph][name];
      if (d) d.applyTo(s.pos, amount);
    }
    return s.pos;
  }
  // vertex normals of a shape with the sliders applied - what smooth shading needs
  vertex_normals(name) {
    const s = this.shape(name);
    return vertexNormals(this.deformed(name), s.tris, s.nrm);
  }
  // Centre and half-span of the frame: the extent of the visible shapes with the sliders applied,
  // measured in camera axes, then the aim and the pan - a mirror of MorphBench.framing(). The
  // half-span stays in ViewMirror, so zooming to a point knows which frame was on the screen.
  framing() {
    const shapes = this.visible_shapes().map((n) => this.shape(n)).filter((s) => s.triCount > 0);
    if (!shapes.length) throw new Error(T.errAllHidden);
    const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
    for (const s of shapes) {
      const p = this.deformed(s.name);
      for (let i = 0, n = p.length; i < n; i += 3) {
        if (p[i] < lo[0]) lo[0] = p[i]; if (p[i] > hi[0]) hi[0] = p[i];
        if (p[i + 1] < lo[1]) lo[1] = p[i + 1]; if (p[i + 1] > hi[1]) hi[1] = p[i + 1];
        if (p[i + 2] < lo[2]) lo[2] = p[i + 2]; if (p[i + 2] > hi[2]) hi[2] = p[i + 2];
      }
    }
    const whole = [0.5 * (lo[0] + hi[0]), 0.5 * (lo[1] + hi[1]), 0.5 * (lo[2] + hi[2])];
    const b = this.view.basis(), r = b.right, u = b.up;
    let half = 0.0;
    for (const s of shapes) {
      const p = s.pos;
      for (let i = 0, n = p.length; i < n; i += 3) {
        const dx = p[i] - whole[0], dy = p[i + 1] - whole[1], dz = p[i + 2] - whole[2];
        const x = Math.abs(dx * r[0] + dy * r[1] + dz * r[2]);
        const y = Math.abs(dx * u[0] + dy * u[1] + dz * u[2]);
        if (x > half) half = x; if (y > half) half = y;
      }
    }
    return this.view.framing(whole, half);
  }

  // colouring keys: numbers, not colours
  bone_key(name) { return this.shape(name).boneKey; }
  morph_key(name, morph) {
    const s = this.shape(name), out = new Float32Array(s.count);
    const d = this.deltas[morph] && this.deltas[morph][name];
    if (d) d.lengthsInto(out);
    return out;
  }
  strain_key(name, morph) {
    const s = this.shape(name), out = new Float32Array(s.count);
    const st = this.strainData[morph] && this.strainData[morph][name];
    if (st) st.valuesInto(out);
    return out;
  }
  vertex_colour_key(name) {
    const mode = this.view.colouring;
    if (mode === "shade") return null;
    if (mode === "bone") return this.bone_key(name);
    if (!this.morphList.length || !this.view.highlightMorph) return new Float32Array(this.shape(name).count);
    if (mode === "morph") return this.morph_key(name, this.view.highlightMorph);
    return this.strain_key(name, this.view.highlightMorph);
  }

  // the state of the view
  orbit(dYaw, dPitch) { return this.view.orbit(dYaw, dPitch).as_dict(); }
  look(yaw, pitch) { return this.view.look(yaw, pitch).as_dict(); }
  preset(name) { return this.view.preset(name).as_dict(); }
  preset_name() { return this.view.preset_name(); }
  zoom(factor) { return this.view.set_zoom(factor).as_dict(); }
  resize(width, height) { return this.view.resize(width, height).as_dict(); }
  // Zoom to the point under the cursor: the frame is worked out again right here, so the point
  // is taken from the frame that is on the screen - the same order the facade keeps.
  zoom_at(factor, fx, fy) { this.framing(); return this.view.zoom_at(factor, fx, fy).as_dict(); }
  pan(dx, dy) { return this.view.set_pan(dx, dy).as_dict(); }
  pan_by(dx, dy) { return this.view.pan_by(dx, dy).as_dict(); }
  colour_by(mode, morph) { return this.view.colour_by(mode, morph).as_dict(); }
  only(names) { return this.view.only(names).as_dict(); }
  show_all() { return this.view.show_all().as_dict(); }
  // The core keeps "everything is visible" as null, and ViewState knows no shape names - so, as
  // in the facade, the list of visible shapes is spelled out here, and hide then takes away one
  // shape instead of all of them.
  hide(name) { if (this.view.visible === null) this.view.only(this.shape_names()); return this.view.hide(name).as_dict(); }
  show(name) { return this.view.show(name).as_dict(); }
  view_state() { return this.view.as_dict(); }

  // light: part of the state of the view as well
  light_follow_camera(on) { return this.view.light_follow_camera(on).as_dict(); }
  light_direction(x, y, z) { return this.view.light_direction(x, y, z).as_dict(); }
  light_power(ambient, diffuse, fill) { return this.view.light_power(ambient, diffuse, fill).as_dict(); }
  light_reset() { return this.view.light_reset().as_dict(); }
  light_vector() { return this.view.light_vector(); }

  // aim: the centres and radii are counted by the core already and sit in focus_targets
  _target(kind, name) {
    const hit = this.targets[kind].find((t) => t.name === name);
    if (!hit) throw new Error(say(T.errNoTarget, { kind, name }));
    return hit;
  }
  focus_bone(name) { const t = this._target("bones", name); return this.view.focus_on(t.centre, t.radius, "bone:" + name).as_dict(); }
  focus_morph(name) { const t = this._target("morphs", name); return this.view.focus_on(t.centre, t.radius, "morph:" + name).as_dict(); }
  focus_shape(name) { const t = this._target("shapes", name); return this.view.focus_on(t.centre, t.radius, "shape:" + name).as_dict(); }
  focus_all() { return this.view.focus_all().as_dict(); }
  focus_targets() { return this.targets; }
}
