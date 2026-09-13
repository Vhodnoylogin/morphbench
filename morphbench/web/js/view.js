"use strict";

// ---- mirror of morphbench/view.py: ViewState ----------------------------------------------
// The method names are the core's own, underscores and all. They look wrong for JavaScript on
// purpose: a button on the page runs the same call a person would type on the command line,
// and renaming one here would quietly break that promise.
class ViewMirror {
  constructor(settings, presets, init) {
    this.settings = settings;
    this.presets = presets;
    this.yaw = init.yaw; this.pitch = init.pitch; this.zoom = init.zoom;
    this.pan = init.pan ? init.pan.slice() : [0, 0];
    this.visible = init.visible === null ? null : new Set(init.visible);
    this.colouring = init.colouring;
    // The capsule layer over the body and the bumper are two separate flags, as in the core;
    // a saved state from before these keys existed means "off".
    this.colliders = !!init.colliders;
    this.bumper = !!init.bumper;
    this.highlightMorph = init.highlightMorph;
    this.width = init.width; this.height = init.height;
    this.focus = init.focus ? { name: init.focus.name, centre: init.focus.centre.slice(),
                                radius: init.focus.radius } : null;
    // Light: either behind the camera (a direction in camera axes - right, up, towards the
    // viewer) or on its own (a world direction). The core hands over both directions; the
    // settings are only a fallback for an old state that carries neither.
    const light = init.light;
    this.lightFollow = !!light.follow;
    this.lightCameraDir = (light.cameraDirection
      || (light.follow ? light.direction : settings.lightCameraDirection)).slice();
    this.lightWorldDir = (light.worldDirection
      || (light.follow ? settings.lightDirection : light.direction)).slice();
    this.ambient = light.ambient; this.diffuse = light.diffuse; this.fill = light.fill;
    // Half-span of the last frame: zooming to a point uses it to turn fractions of the frame
    // into model units.
    this.frameHalf = null;
  }
  // camera
  orbit(dYaw, dPitch) { this.yaw = mod360(this.yaw + dYaw); this.pitch = clamp(this.pitch + dPitch, -89, 89); return this; }
  look(yaw, pitch) { this.yaw = mod360(yaw); this.pitch = clamp(pitch, -89, 89); return this; }
  preset(name) {
    if (!(name in this.presets)) throw new Error(say(T.errNoPreset, { name }));
    return this.look(this.presets[name][0], this.presets[name][1]);
  }
  preset_names() { return Object.keys(this.presets).sort(); }
  preset_name() {
    const y = rnd(this.yaw, 1), p = rnd(this.pitch, 1);
    for (const name in this.presets) {
      const v = this.presets[name];
      if (rnd(mod360(v[0]), 1) === y && rnd(v[1], 1) === p) return name;
    }
    return null;
  }
  set_zoom(factor) { this.zoom = Math.max(0.05, Number(factor)); return this; }
  // Zoom to a point: the point of the scene under the cursor stays where it is. fx, fy are the
  // cursor's offset from the centre of the frame, in fractions of half the shorter side of the
  // canvas, right and up. Without the half-span of the last frame that point is unknown, and
  // the zoom runs from the centre instead - as it does in the core.
  zoom_at(factor, fx, fy) {
    const old = this.zoom, next = Math.max(0.05, Number(factor));
    if (this.frameHalf !== null && old > 0.0 && next !== old) {
      const fill = this.settings.frameFill;
      const u = Number(fx) * this.frameHalf / (fill * old);
      const v = Number(fy) * this.frameHalf / (fill * old);
      const k = 1.0 - old / next;
      this.pan = [this.pan[0] - u * k, this.pan[1] - v * k];
    }
    this.zoom = next;
    return this;
  }
  resize(width, height) { this.width = Math.trunc(width); this.height = Math.trunc(height); return this; }
  // pan: the frame slides along the screen axes - right and up - in model units
  set_pan(dx, dy) { this.pan = [Number(dx), Number(dy)]; return this; }
  pan_by(dx, dy) { return this.set_pan(this.pan[0] + dx, this.pan[1] + dy); }
  // aim
  focus_on(centre, radius, name) { this.focus = { name: name, centre: centre.slice(), radius: Math.max(radius, 1e-3) }; return this; }
  focus_all() { this.focus = null; return this; }
  // The frame: the aim sphere with its padding, or else the extent passed in; the pan shifts
  // the centre - the same rule ViewState.framing() follows in the core. The half-span is kept
  // for zoom_at.
  framing(centre, halfSpan) {
    let c = centre, half = halfSpan;
    if (this.focus !== null) { c = this.focus.centre; half = this.focus.radius * this.settings.focusPadding; }
    if (this.pan[0] !== 0 || this.pan[1] !== 0) {
      const b = this.basis();
      c = [0, 1, 2].map((i) => c[i] - b.right[i] * this.pan[0] - b.up[i] * this.pan[1]);
    }
    this.frameHalf = half;
    return [c, half];
  }
  // light
  light_follow_camera(on) { this.lightFollow = !!on; return this; }
  light_direction(x, y, z) {
    const v = [Number(x), Number(y), Number(z)];
    if (norm(v) < 1e-6) throw new Error(T.errZeroLight);
    if (this.lightFollow) this.lightCameraDir = v; else this.lightWorldDir = v;
    return this;
  }
  light_power(ambient, diffuse, fill) {
    if (ambient !== undefined && ambient !== null) this.ambient = Math.max(0.0, Number(ambient));
    if (diffuse !== undefined && diffuse !== null) this.diffuse = Math.max(0.0, Number(diffuse));
    if (fill !== undefined && fill !== null) this.fill = Math.max(0.0, Number(fill));
    return this;
  }
  // Light back to what the settings say: the mode, both directions and the powers - a mirror
  // of ViewState.light_reset.
  light_reset() {
    const st = this.settings;
    this.lightFollow = !!st.lightFollowCamera;
    this.lightCameraDir = st.lightCameraDirection.slice();
    this.lightWorldDir = st.lightDirection.slice();
    this.ambient = Number(st.ambient); this.diffuse = Number(st.diffuse); this.fill = Number(st.fill);
    return this;
  }
  // A unit vector towards the source in world coordinates - what the renderer needs. Behind
  // the camera it is built from the camera axes: right·x + up·y - forward·z, so it travels
  // with the view.
  light_vector() {
    let v;
    if (this.lightFollow) {
      const b = this.basis(), d = this.lightCameraDir;
      v = [0, 1, 2].map((i) => b.right[i] * d[0] + b.up[i] * d[1] - b.forward[i] * d[2]);
    } else {
      v = this.lightWorldDir.slice();
    }
    const n = norm(v);
    return n > 1e-6 ? v.map((x) => x / n) : [0, 0, 1];
  }
  light_state() {
    const d = this.lightFollow ? this.lightCameraDir : this.lightWorldDir;
    return { follow: this.lightFollow, direction: d.map((x) => rnd(x, 3)),
             cameraDirection: this.lightCameraDir.map((x) => rnd(x, 3)),
             worldDirection: this.lightWorldDir.map((x) => rnd(x, 3)),
             ambient: rnd(this.ambient, 3), diffuse: rnd(this.diffuse, 3), fill: rnd(this.fill, 3) };
  }
  // capsule layer: the bumper is separate and off by default; null or undefined means leave it
  // as it is, the same as None does in ViewState.show_colliders
  show_colliders(on, bumper) {
    this.colliders = on === undefined ? true : !!on;
    if (bumper !== undefined && bumper !== null) this.bumper = !!bumper;
    return { colliders: this.colliders, bumper: this.bumper };
  }
  // layers
  show_all() { this.visible = null; return this; }
  only(names) { this.visible = new Set(names); return this; }
  show(name) { if (this.visible !== null) this.visible.add(name); return this; }
  hide(name) { if (this.visible === null) this.visible = new Set(); this.visible.delete(name); return this; }
  is_visible(name) { return this.visible === null || this.visible.has(name); }
  // colouring
  colour_by(mode, morph) {
    if (!["shade", "bone", "morph", "strain"].includes(mode)) throw new Error(T.errColourMode);
    this.colouring = mode; this.highlightMorph = morph === undefined ? null : morph; return this;
  }
  // the three camera axes: right, up, and from the viewer towards the model. The character
  // faces along +Y, so a yaw of zero puts the camera in front of them, looking towards -Y.
  basis() {
    const ry = this.yaw * Math.PI / 180, rp = this.pitch * Math.PI / 180;
    const forward = [-Math.sin(ry) * Math.cos(rp), -Math.cos(ry) * Math.cos(rp), -Math.sin(rp)];
    let right = cross(forward, [0, 0, 1]);
    const n = norm(right);
    right = n < 1e-5 ? [1, 0, 0] : right.map((x) => x / n);
    return { right: right, up: cross(right, forward), forward: forward };
  }
  as_dict() {
    return {
      yaw: rnd(this.yaw, 1), pitch: rnd(this.pitch, 1), preset: this.preset_name(),
      zoom: rnd(this.zoom, 3),
      pan: [rnd(this.pan[0], 2), rnd(this.pan[1], 2)],
      colouring: this.colouring, highlightMorph: this.highlightMorph,
      visible: this.visible === null ? null : Array.from(this.visible).sort(),
      colliders: this.colliders, bumper: this.bumper,
      width: this.width, height: this.height,
      light: this.light_state(),
      focus: this.focus === null ? null : { name: this.focus.name,
        centre: this.focus.centre.map((x) => rnd(x, 2)), radius: rnd(this.focus.radius, 2) },
    };
  }
}
