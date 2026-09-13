"use strict";

// ---- side panel ----------------------------------------------------------------------------
class Panel {
  constructor(app, root) {
    this.app = app;
    this.bench = app.bench;
    this.root = root;
    this.build();
  }
  build() {
    const bench = this.bench, app = this.app, view = bench.view, st = bench.settings;
    const root = this.root;

    // the model: what is open and, when a server is behind the page, what to choose from
    root.appendChild(this.buildModel());

    // view presets
    this.presetButtons = new Map();
    const presetRow = el("div", { class: "row" });
    for (const name of view.preset_names()) {
      const b = el("button", { text: name, on: { click: () => app.invoke("preset", name) } });
      this.presetButtons.set(name, b);
      presetRow.appendChild(b);
    }
    root.appendChild(el("section", null, [el("h2", { text: T.secView }), presetRow,
      el("div", { class: "row", style: "margin-top:6px" }, [
        el("button", { text: T.btnZoom11, on: { click: () => { app.invoke("zoom", 1.0); } } }),
        el("button", { text: T.btnResetPan, on: { click: () => app.invoke("pan", 0, 0) } }),
      ])]));

    // aim
    const targets = bench.focus_targets();
    this.focusSelect = el("select", { on: { change: () => this.onFocus() } });
    this.focusSelect.appendChild(el("option", { value: "", text: T.optWholeModel }));
    const groups = [["shapes", T.grpShapes, "shape"], ["bones", T.grpBones, "bone"], ["morphs", T.grpMorphs, "morph"]];
    for (const [key, title, kind] of groups) {
      if (!targets[key].length) continue;
      const g = el("optgroup", { label: title });
      for (const t of targets[key]) g.appendChild(el("option", { value: kind + ":" + t.name, text: t.name }));
      this.focusSelect.appendChild(g);
    }
    this.focusInfo = el("div", { class: "muted" });
    root.appendChild(el("section", null, [el("h2", { text: T.secFocus }), this.focusSelect, this.focusInfo]));

    // mesh shapes
    this.partBoxes = new Map();
    const parts = el("div", { class: "parts" });
    for (const name of bench.shape_names()) {
      const box = el("input", { type: "checkbox", on: { change: () => this.onPart(name, box.checked) } });
      this.partBoxes.set(name, box);
      const s = bench.shape(name);
      parts.appendChild(el("div", { class: "part" }, [
        el("label", null, [box, el("span", { text: name }), el("span", { class: "muted", text: s.count + T.lblVerts })]),
        el("span", { class: "only", text: T.btnOnly, on: { click: () => app.invoke("only", [name]) } })]));
    }
    root.appendChild(el("section", null, [el("h2", { text: T.secShapes }),
      bench.shape_names().length ? parts : el("div", { class: "muted", text: T.noMesh }),
      el("div", { class: "row", style: "margin-top:6px" }, [
        el("button", { text: T.btnShowAll, on: { click: () => app.invoke("show_all") } })])]));

    // Collision capsules - the section is here only when a skeleton is open: without one the
    // core has no such layer either. Both checkboxes go through the single facade method
    // show_colliders(on, bumper): the capsule box leaves the bumper alone (null), and the
    // bumper box leaves the layer as it is.
    this.colliderBox = null; this.bumperBox = null;
    if (bench.has_skeleton()) {
      this.colliderBox = el("input", { type: "checkbox",
        on: { change: () => app.invoke("show_colliders", this.colliderBox.checked, null) } });
      this.bumperBox = el("input", { type: "checkbox",
        on: { change: () => app.invoke("show_colliders", bench.view.colliders, this.bumperBox.checked) } });
      if (!bench.bumper_mesh()) { this.bumperBox.disabled = true; this.bumperBox.title = T.noBumper; }
      root.appendChild(el("section", null, [el("h2", { text: T.secCapsules }),
        el("div", { class: "current" }, [el("span", { text: bench.names.skeleton }),
          el("span", { class: "muted", text: T.summaryCapsules + bench.summary.colliders })]),
        el("div", { class: "row", style: "margin-top:6px" }, [
          el("label", null, [this.colliderBox, T.lblCapsules]),
          el("label", null, [this.bumperBox, T.lblBumper])]),
        el("div", { class: "muted", text: T.capsulesNote })]));
    }

    // colouring
    this.colourRadios = new Map();
    const modes = [["shade", T.modeShade], ["bone", T.modeBone], ["morph", T.modeMorph], ["strain", T.modeStrain]];
    const modeRow = el("div", { class: "row" });
    for (const [mode, title] of modes) {
      const r = el("input", { type: "radio", name: "colouring", value: mode, on: { change: () => this.onColour() } });
      this.colourRadios.set(mode, r);
      modeRow.appendChild(el("label", null, [r, " " + title]));
    }
    this.morphSelect = el("select", { on: { change: () => this.onColour() } });
    this.morphSelect.appendChild(el("option", { value: "", text: T.optNoMorph }));
    for (const m of bench.morphs()) this.morphSelect.appendChild(el("option", { value: m, text: m }));
    root.appendChild(el("section", null, [el("h2", { text: T.secColour }), modeRow,
      el("div", { class: "row", style: "margin-top:6px" }, [el("span", { class: "muted", text: T.colourMorphNote })]),
      this.morphSelect]));

    // light: bound to the camera or to the world, the direction towards the source, three powers
    this.lightFollowBox = el("input", { type: "checkbox",
      on: { change: () => app.invoke("light_follow_camera", this.lightFollowBox.checked) } });
    this.lightDirLabel = el("span", { class: "muted" });
    this.lightDirInputs = [0, 1, 2].map(() => el("input", { type: "number", step: "any", class: "short",
      on: { change: () => this.onLightDir() } }));
    this.lightPowerInputs = {};
    const powerRow = el("div", { class: "row" });
    for (const [key, title] of [["ambient", T.lightAmbient], ["diffuse", T.lightDiffuse], ["fill", T.lightFill]]) {
      const inp = el("input", { type: "number", step: "any", min: "0", class: "short", on: { change: () => this.onLightPower() } });
      this.lightPowerInputs[key] = inp;
      powerRow.appendChild(el("label", null, [title + " ", inp]));
    }
    root.appendChild(el("section", null, [el("h2", { text: T.secLight }),
      el("div", { class: "row" }, [el("label", null, [this.lightFollowBox, T.lblBehindCamera])]),
      el("div", { class: "row", style: "margin-top:6px" }, [this.lightDirLabel].concat(this.lightDirInputs)),
      el("div", { class: "muted", style: "margin-top:6px", text: T.lightPowers }), powerRow,
      el("div", { class: "row", style: "margin-top:6px" }, [
        el("button", { text: T.btnLightDefaults, on: { click: () => this.resetLight() } }),
        el("span", { class: "muted", text: T.shadingIs + st.shading })])]));

    // sliders
    this.sliderRows = new Map();
    const range = st.sliderRange, step = String(st.sliderStep);
    const sliders = el("div");
    for (const name of bench.morphs()) {
      const rng = el("input", { type: "range", min: range[0], max: range[1], step: step });
      const num = el("input", { type: "number", step: step });
      rng.addEventListener("input", () => { num.value = rng.value; app.invoke("set_slider", name, Number(rng.value)); });
      num.addEventListener("change", () => { app.invoke("set_slider", name, Number(num.value) || 0); });
      const row = el("div", { class: "slider" }, [el("span", { class: "name", text: name, title: name }), rng, num]);
      this.sliderRows.set(name, { row, rng, num });
      sliders.appendChild(row);
    }
    root.appendChild(el("section", null, [el("h2", { text: T.secSliders }),
      bench.morphs().length ? sliders : el("div", { class: "muted", text: bench.is_open() ? T.noMorphFile : T.noMesh }),
      el("div", { class: "row", style: "margin-top:6px" }, [
        el("button", { text: T.btnResetSliders, on: { click: () => app.invoke("reset_sliders") } }),
        el("span", { class: "muted", text: T.sliderRange + range[0] + " … " + range[1] + T.fromSettings })])]));

    // bone legend
    this.legendSelect = el("select", { on: { change: () => this.refreshLegend() } });
    for (const name of bench.shape_names()) this.legendSelect.appendChild(el("option", { value: name, text: name }));
    if (bench.shapes.has(st.baseShape)) this.legendSelect.value = st.baseShape;
    this.legend = el("div", { class: "legend" });
    this.legendSection = el("section", null, [el("h2", { text: T.secLegend }), this.legendSelect, this.legend]);
    root.appendChild(this.legendSection);

    // state
    this.lastCall = el("pre", { text: "" });
    this.state = el("pre");
    this.command = el("pre");
    this.note = el("div", { class: "muted" });
    this.error = el("div", { class: "err" });
    root.appendChild(el("section", null, [el("h2", { text: T.secState }),
      el("div", { class: "muted", text: T.lastCall }), this.lastCall,
      el("div", { class: "muted", text: T.stateLine }), this.state,
      el("div", { class: "muted", text: T.sameFrame }), this.command, this.note, this.error]));
  }

  // The "Model" section. In a file on disk it is the name of the open mesh and nothing else:
  // there is nothing to choose from, and the page asks nobody. From a server it also carries
  // the meshes found under the browse root, the folder itself and the sweep that takes meshes
  // without morphs; picking one goes back to the same server with a different query.
  buildModel() {
    const bench = this.bench, names = bench.names, srv = bench.server;
    const current = el("div", { class: "current" }, [
      el("span", { text: names.nif || T.noMesh }),
      names.tri ? el("span", { class: "muted", text: T.morphsOf + names.tri + " (" + bench.summary.triKind + ")" }) : null]);
    if (!srv) {
      return el("section", null, [el("h2", { text: T.secModel }), current,
        el("div", { class: "muted", text: T.modelInServe })]);
    }
    const env = srv.environment || {};
    const envLine = el("div", { class: "muted", text:
      T.underMo2 + (env.insideMo2 ? T.yes : T.no) + T.rootIs + (srv.root || T.rootUnset) });
    // the mesh list: grouped by the folder below the root, each line is the file and the morph format
    this.modelSelect = el("select", { on: { change: () => this.onModel() } });
    this.modelSelect.appendChild(el("option", { value: "",
      text: srv.catalog.length ? T.pickMesh + srv.catalog.length + T.pickMeshEnd : T.noMeshesUnderRoot }));
    const groups = new Map();
    const same = (a, b) => !!a && !!b && a.replace(/\\/g, "/").toLowerCase() === b.replace(/\\/g, "/").toLowerCase();
    let currentName = "";
    for (const e of srv.catalog) {
      let g = groups.get(e.folder);
      if (!g) { g = el("optgroup", { label: e.folder || "." }); groups.set(e.folder, g); this.modelSelect.appendChild(g); }
      g.appendChild(el("option", { value: e.name, text: e.file + " · " + (e.kind || T.withoutMorphs) }));
      if (bench.summary && same(e.nif, bench.summary.nif)) currentName = e.name;
    }
    this.modelSelect.value = currentName;
    // the browse folder, and the sweep that takes meshes without morphs as well
    this.rootInput = el("input", { type: "text", class: "wide", value: srv.root || "", title: T.browseFolder });
    this.allBox = el("input", { type: "checkbox", on: { change: () => this.go({ root: this.rootInput.value }) } });
    this.allBox.checked = !srv.withMorphs;
    return el("section", null, [el("h2", { text: T.secModel }), current, this.modelSelect,
      el("div", { class: "row", style: "margin-top:6px" }, [this.rootInput,
        el("button", { text: T.btnBrowse, on: { click: () => this.go({ root: this.rootInput.value }) } })]),
      el("div", { class: "row" }, [el("label", null, [this.allBox, T.lblWithoutMorphs])]),
      envLine, el("div", { class: "err", text: srv.error || "" })]);
  }
  // Going to the same server with another body or another root: the page holds one body, so
  // changing the model is a reload with a different query, not a second set of geometry.
  go(params) {
    const q = [];
    for (const k in params) if (params[k] !== undefined && params[k] !== null && params[k] !== "") q.push(k + "=" + encodeURIComponent(params[k]));
    if (this.allBox && this.allBox.checked) q.push("all=1");
    window.location.href = "/?" + q.join("&");
  }
  onModel() {
    const name = this.modelSelect.value;
    if (name) this.go({ name: name, root: this.bench.server.root });
  }

  // --- what the panel does: every action calls a method of the facade mirror ---
  onFocus() {
    const v = this.focusSelect.value;
    if (!v) return this.app.invoke("focus_all");
    const i = v.indexOf(":"), kind = v.slice(0, i), name = v.slice(i + 1);
    this.app.invoke("focus_" + kind, name);
  }
  // A shape checkbox is only() with the list of the visible shapes, or show_all() when they
  // are all visible: that keeps the state exactly what the core's view_state() would report.
  onPart(name, checked) {
    const view = this.bench.view, all = this.bench.shape_names();
    const names = all.filter((n) => n === name ? checked : view.is_visible(n));
    if (names.length === all.length) this.app.invoke("show_all");
    else this.app.invoke("only", names);
  }
  onColour() {
    let mode = "shade";
    for (const [m, r] of this.colourRadios) if (r.checked) mode = m;
    const morph = this.morphSelect.value || null;
    this.app.invoke("colour_by", mode, (mode === "morph" || mode === "strain") ? morph : null);
  }
  onLightDir() {
    const v = this.lightDirInputs.map((i) => Number(i.value) || 0);
    this.app.invoke("light_direction", v[0], v[1], v[2]);
    this.showLight(this.bench.view.as_dict().light, true);   // the fields show what the facade accepted
  }
  onLightPower() {
    const v = (key) => Number(this.lightPowerInputs[key].value) || 0;
    this.app.invoke("light_power", v("ambient"), v("diffuse"), v("fill"));
    this.showLight(this.bench.view.as_dict().light, true);
  }
  // Light as in the settings - one facade call, and the core has a method of the same name.
  resetLight() {
    this.app.invoke("light_reset");
  }

  // --- reflecting the state ---
  showLight(light, force) {
    this.lightFollowBox.checked = light.follow;
    this.lightDirLabel.textContent = light.follow ? T.lightAxesCamera : T.lightAxesWorld;
    light.direction.forEach((v, i) => {
      const inp = this.lightDirInputs[i];
      if (force || document.activeElement !== inp) inp.value = v;
    });
    for (const key in this.lightPowerInputs) {
      const inp = this.lightPowerInputs[key];
      if (force || document.activeElement !== inp) inp.value = light[key];
    }
  }
  refresh() {
    const bench = this.bench, view = bench.view, state = view.as_dict();
    const preset = state.preset;
    for (const [name, b] of this.presetButtons) b.classList.toggle("on", name === preset);

    // aim
    const focusValue = state.focus ? state.focus.name : "";
    if (focusValue && !Array.from(this.focusSelect.options).some((o) => o.value === focusValue)) {
      // the target came from the command line as a substring - the core has already worked out the
      // sphere, so show it as it is
      this.focusSelect.appendChild(el("option", { value: focusValue, text: focusValue + T.focusFromCli }));
    }
    this.focusSelect.value = focusValue;
    this.focusInfo.textContent = state.focus
      ? T.focusCentre + state.focus.centre.join(" ") + T.focusRadius + state.focus.radius + T.focusPadding + bench.settings.focusPadding
      : T.frameCoversAll;

    // shapes
    for (const [name, box] of this.partBoxes) box.checked = view.is_visible(name);

    // capsules
    if (this.colliderBox) { this.colliderBox.checked = view.colliders; this.bumperBox.checked = view.bumper; }

    // colouring
    for (const [mode, r] of this.colourRadios) r.checked = (mode === view.colouring);
    this.morphSelect.value = view.highlightMorph || "";
    this.legendSection.style.display = view.colouring === "bone" && bench.shape_names().length ? "" : "none";
    if (view.colouring === "bone" && this.legendSelect.value && this.legendFor !== this.legendSelect.value) this.refreshLegend();

    // light
    this.showLight(state.light, false);

    // sliders
    const sliders = bench.sliders();
    for (const [name, r] of this.sliderRows) {
      const v = name in sliders ? sliders[name] : 0;
      if (document.activeElement !== r.rng) r.rng.value = v;
      if (document.activeElement !== r.num) r.num.value = fmt(v);
      r.row.classList.toggle("active", name in sliders);
    }

    // the state and the command
    this.lastCall.textContent = this.app.lastCall || "—";
    this.state.textContent = JSON.stringify({ view: state, sliders: sliders }, null, 2);
    this.command.textContent = this.buildCommand(preset);
    const notes = [];
    if (state.visible !== null && state.visible.length === 0) notes.push(T.allHidden);
    this.note.textContent = notes.join(" ");
  }
  refreshLegend() {
    const shape = this.bench.shape(this.legendSelect.value);
    const palette = Palette.bones(shape.boneNames.length);
    this.legendFor = shape.name;
    this.legend.textContent = "";
    shape.boneNames.forEach((name, i) => {
      const c = [palette[i * 3], palette[i * 3 + 1], palette[i * 3 + 2]].map((x) => Math.round(x * 255));
      this.legend.appendChild(el("div", { title: name }, [el("span", { class: "swatch", style: "background:rgb(" + c.join(",") + ")" }), name]));
    });
    const g = Palette.NO_BONE.map((x) => Math.round(x * 255));
    this.legend.appendChild(el("div", null, [el("span", { class: "swatch", style: "background:rgb(" + g.join(",") + ")" }), T.noBone]));
  }
  // The mb.py render command line, with the same options cmd_render takes: everything clicked
  // on the page can be repeated without a window. Pairs of numbers go through an equals sign so
  // that a leading minus is not taken for an option by the parser. Light gets into the command
  // only where it differs from the settings: given no light options, render lights the body
  // exactly as the settings say.
  buildCommand(preset) {
    const bench = this.bench, st = bench.settings, state = bench.view.as_dict(), sliders = bench.sliders();
    if (!bench.summary) return T.noFrameSource;
    const q = (s) => /[^\w.\-=:\\\/]/.test(s) ? '"' + s.replace(/"/g, '\\"') + '"' : s;
    // the output name is not a key: a file name is the same in every language, and this line
    // is pasted into a shell as it stands
    const parts = ["python", "mb.py", "render", q(bench.summary.nif), "--out", "frame.png"];
    if (bench.summary.tri) parts.push("--tri", q(bench.summary.tri));
    if (preset) parts.push("--view", preset); else parts.push("--look=" + state.yaw + "," + state.pitch);
    for (const name in sliders) parts.push("--slider", q(name + "=" + fmt(sliders[name])));
    if (state.colouring !== "shade") parts.push("--colour", state.colouring);
    if (state.highlightMorph) parts.push("--morph", q(state.highlightMorph));
    if (state.visible !== null) parts.push("--only", q(state.visible.join(",")));
    if (Math.abs(state.zoom - 1.0) > 1e-9) parts.push("--zoom", fmt(state.zoom));
    if (state.pan[0] !== 0 || state.pan[1] !== 0) parts.push("--pan=" + state.pan[0] + "," + state.pan[1]);
    if (state.width !== st.imageWidth || state.height !== st.imageHeight)
      parts.push("--size", state.width + "x" + state.height);
    if (state.focus) {
      const i = state.focus.name.indexOf(":");
      parts.push("--focus-" + state.focus.name.slice(0, i), q(state.focus.name.slice(i + 1)));
    }
    // The capsule layer: the skeleton is named outright, even though render would have found it
    // beside the mesh on its own.
    if (state.colliders && bench.summary.skeleton) {
      parts.push("--skeleton", q(bench.summary.skeleton), "--colliders");
      if (state.bumper) parts.push("--bumper");
    }
    const light = state.light;
    if (light.follow !== st.lightFollowCamera) parts.push("--light", light.follow ? "camera" : "world");
    const dirDefault = (light.follow ? st.lightCameraDirection : st.lightDirection).map((x) => rnd(x, 3));
    if (light.direction.some((x, i) => x !== dirDefault[i])) parts.push("--light-dir=" + light.direction.join(","));
    if (light.ambient !== rnd(st.ambient, 3) || light.diffuse !== rnd(st.diffuse, 3) || light.fill !== rnd(st.fill, 3))
      parts.push("--light-power=" + [light.ambient, light.diffuse, light.fill].join(","));
    return parts.join(" ");
  }
}
