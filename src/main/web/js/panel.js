"use strict";

// Workspace navigation only reflects facade state. Mode and tab changes use the same
// App.invoke entry point as mesh controls; no hidden UI-only session is maintained here.
class WorkspaceUI {
  constructor(app) {
    this.app = app;
    this.bench = app.bench;
    this.modeNav = document.getElementById("mode-nav");
    this.tabNav = document.getElementById("mode-tabs");
    this.modes = [
      { id: "morphs", label: T.wsMorphs, note: T.wsMorphsNote, tabs: ["sliders", "display"],
        icon: ["M3 4h10M3 8h10M3 12h10", "M6 2v4M10 6v4M5 10v4"] },
      { id: "colliders", label: T.wsColliders, note: T.wsCollidersNote, tabs: ["edit", "display"],
        icon: ["M5 3a3 3 0 0 1 5 0l3 6a3 3 0 0 1-5 3L3 6a3 3 0 0 1 2-3Z", "M4 5l7 6"] },
      { id: "physics", label: T.wsPhysics, note: T.wsPhysicsNote, tabs: ["configuration", "ranges"],
        icon: ["M8 1v3M8 12v3M1 8h3M12 8h3", "M11.5 4.5a5 5 0 1 1-7 7M5 6l3 2 3-5"] },
      { id: "slots", label: T.wsSlots, note: T.wsSlotsNote, tabs: ["author", "display"],
        icon: ["M2 2h5v5H2zM9 2h5v5H9zM2 9h5v5H2zM9 9h5v5H9z"] },
    ];
    this.tabLabels = { sliders: T.wsSliders, display: T.wsDisplay, edit: T.wsEdit,
      configuration: T.wsConfiguration, ranges: T.wsRanges, author: T.wsAuthor };
    this.modeButtons = new Map();
    this.tabButtons = new Map();
    if (!this.modeNav || !this.tabNav) return;
    this.modeNav.setAttribute("aria-label", T.wsModes);
    this.tabNav.setAttribute("aria-label", T.wsTabs);
    this.tabNav.setAttribute("role", "tablist");
    document.getElementById("model-panel").setAttribute("aria-label", T.wsModels);
    document.getElementById("panel").setAttribute("role", "tabpanel");
    document.getElementById("workspace-context").textContent = T.wsModels;
    document.getElementById("viewport-title").textContent = T.wsViewport;
    for (const mode of this.modes) {
      const enabled = this.bench.workspace_modes().includes(mode.id);
      const icon = el("span", { class: "mode-icon", "aria-hidden": "true" });
      // A fixed SVG template lets the HTML parser select its namespace without an URL in
      // the offline page. Path data below is static markup, never model or user content.
      const template = document.createElement("template");
      template.innerHTML = '<svg viewBox="0 0 16 16"></svg>';
      const svg = template.content.firstChild;
      for (const path of mode.icon) {
        const shape = document.createElementNS(svg.namespaceURI, "path");
        shape.setAttribute("d", path); svg.appendChild(shape);
      }
      icon.appendChild(svg);
      const button = el("button", { class: "mode-button", type: "button", title: enabled ? mode.note : T.wsUnavailable,
        ...(!enabled ? { disabled: "disabled" } : {}), "aria-disabled": String(!enabled),
        "data-workspace-mode": mode.id, on: { click: () => app.invoke("workspace_mode", mode.id) } },
      [icon, el("span", { text: mode.label }),
        !enabled ? el("span", { class: "mode-badge", text: T.wsWithheld }) : null]);
      this.modeButtons.set(mode.id, button);
      this.modeNav.appendChild(button);
    }
    this.modeNav.addEventListener("keydown", (event) => this.onNavigate(event, this.modeButtons, "workspace_mode"));
    this.tabNav.addEventListener("keydown", (event) => this.onNavigate(event, this.tabButtons, "workspace_tab"));
    this.refresh();
  }
  onNavigate(event, buttons, method) {
    const entries = Array.from(buttons).filter(([, button]) => !button.disabled);
    const keys = entries.map(([key]) => key), nodes = entries.map(([, button]) => button);
    const index = nodes.indexOf(document.activeElement);
    if (index < 0 || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? 0 : event.key === "End" ? keys.length - 1
      : (index + (event.key === "ArrowRight" ? 1 : -1) + keys.length) % keys.length;
    this.app.invoke(method, keys[next]);
    buttons.get(keys[next]).focus();
  }
  refresh() {
    if (!this.modeNav || !this.tabNav) return;
    const state = typeof this.bench.workspace_state === "function" ? this.bench.workspace_state()
      : { mode: this.bench.placements && this.bench.placements.mode === "slots" ? "slots" : "morphs" };
    const mode = this.modes.find((item) => item.id === state.mode) || this.modes[0];
    const tab = mode.tabs.includes(state.tab) ? state.tab : mode.tabs[0];
    if (this.activeMode !== mode.id) {
      this.tabNav.textContent = "";
      this.tabButtons.clear();
      for (const name of mode.tabs) {
        const button = el("button", { class: "context-tab", type: "button", role: "tab",
          id: "workspace-tab-" + name, "aria-controls": "panel", text: this.tabLabels[name],
          on: { click: () => this.app.invoke("workspace_tab", name) } });
        this.tabButtons.set(name, button); this.tabNav.appendChild(button);
      }
      this.activeMode = mode.id;
    }
    for (const [id, button] of this.modeButtons) {
      const selected = id === mode.id;
      button.classList.toggle("on", selected);
      button.setAttribute("aria-pressed", String(selected));
      button.tabIndex = selected ? 0 : -1;
    }
    for (const [id, button] of this.tabButtons) {
      const selected = id === tab;
      button.classList.toggle("on", selected);
      button.setAttribute("aria-selected", String(selected));
      button.tabIndex = selected ? 0 : -1;
    }
    document.getElementById("panel").setAttribute("aria-labelledby", "workspace-tab-" + tab);
    const matches = (value, selected) => !value || value.split(/\s+/).includes(selected) || value === "common";
    for (const section of document.querySelectorAll("[data-mode], [data-tab]")) {
      section.hidden = !matches(section.getAttribute("data-mode"), mode.id) || !matches(section.getAttribute("data-tab"), tab);
    }
    document.body.setAttribute("data-workspace-mode", mode.id);
    document.getElementById("workspace-description").textContent = mode.note;
    document.getElementById("workspace-status").textContent = this.bench.is_open() ? T.wsReady : T.wsNoMesh;
    document.getElementById("viewport-mode").textContent = mode.label;
    document.getElementById("inspector-title").textContent = mode.label;
    document.getElementById("inspector-description").textContent = this.tabLabels[tab];
  }
}

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
    const modelRoot = document.getElementById("model-panel") || root;
    const viewRoot = document.getElementById("view-tools") || root;
    root.appendChild(el("div", { class: "inspector-heading" }, [
      el("h2", { id: "inspector-title" }), el("p", { id: "inspector-description" })]));

    // the model: what is open and, when a server is behind the page, what to choose from
    modelRoot.appendChild(this.buildModel());
    this.slotsPanel = new SlotsPanel(app, root);
    // The shared workspace chooser replaces the older mesh/Slots selector. The underlying
    // control remains owned by SlotsPanel, while all of its authoring fields are preserved.
    this.slotsPanel.mode.parentElement.hidden = true;
    this.slotsPanel.section.setAttribute("data-mode", "slots");
    this.slotsPanel.section.setAttribute("data-tab", "author");

    // view presets
    this.presetButtons = new Map();
    const presetRow = el("div", { class: "row" });
    for (const name of view.preset_names()) {
      const labels={back:T.edBack,below:T.edBelow,front:T.edFront,quarter:T.edQuarter,side:T.edSide,top:T.edTop};
      const b = el("button", { text: labels[name]||name, on: { click: () => app.invoke("preset", name) } });
      this.presetButtons.set(name, b);
      presetRow.appendChild(b);
    }
    viewRoot.appendChild(el("section", null, [el("h2", { text: T.secView }), presetRow,
      el("div", { class: "row", style: "margin-top:6px" }, [
        el("button", { text: T.btnZoom11, on: { click: () => { app.invoke("zoom", 1.0); } } }),
        el("button", { text: T.btnResetPan, on: { click: () => app.invoke("pan", 0, 0) } }),
      ])]));

    // aim
    const targets = bench.focus_targets();
    this.focusSelect = el("select", { "aria-label": T.secFocus, on: { change: () => this.onFocus() } });
    this.focusSelect.appendChild(el("option", { value: "", text: T.optWholeModel }));
    const groups = [["shapes", T.grpShapes, "shape"], ["bones", T.grpBones, "bone"], ["morphs", T.grpMorphs, "morph"]];
    for (const [key, title, kind] of groups) {
      if (!targets[key].length) continue;
      const g = el("optgroup", { label: title });
      for (const t of targets[key]) g.appendChild(el("option", { value: kind + ":" + t.name, text: t.name }));
      this.focusSelect.appendChild(g);
    }
    this.focusInfo = el("div", { class: "muted" });
    root.appendChild(el("section", { "data-tab": "display" }, [el("h2", { text: T.secFocus }), this.focusSelect, this.focusInfo]));

    // mesh shapes
    this.fileRespectBox=el("input",{type:"checkbox",on:{change:()=>app.invoke("respect_file_visibility",this.fileRespectBox.checked,bench.view.showFileHidden)}});
    this.fileHiddenBox=el("input",{type:"checkbox",on:{change:()=>app.invoke("respect_file_visibility",bench.view.respectFileVisibility,this.fileHiddenBox.checked)}});
    this.fileVisibilitySummary=el("p",{class:"muted"});
    modelRoot.appendChild(el("section",null,[
      el("label",{class:"row"},[this.fileRespectBox,T.visibilityRespect]),
      el("label",{class:"row"},[this.fileHiddenBox,T.visibilityShowHidden]),
      this.fileVisibilitySummary,
      el("details",null,[el("summary",{text:T.visibilityHelp}),el("p",{class:"muted",text:T.visibilityScope})])
    ]));
    this.partBoxes = new Map();
    const parts = el("div", { class: "parts" });
    const fileStates=new Map(bench.file_visibility().shapes.map((row)=>[row.name,row]));
    for (const name of bench.shape_names()) {
      const box = el("input", { type: "checkbox", on: { change: () => this.onPart(name, box.checked) } });
      this.partBoxes.set(name, box);
      const s = bench.shape(name);
      const metadata=fileStates.get(name),stateText=!metadata||metadata.state==="unknown"?T.visibilityUnknown:
        metadata.localHidden?T.visibilityLocalHidden:metadata.inheritedHidden?T.visibilityInheritedHidden:T.visibilityVisible;
      parts.appendChild(el("div", { class: "part" }, [
        el("label", null, [box, el("span",{class:"part-name"},[el("span",{text:name}),el("small",{class:"file-state",text:stateText})]), el("span", { class: "muted", text: s.count + T.lblVerts })]),
        el("button", { class: "only", text: T.btnOnly, on: { click: () => app.invoke("only", [name]) } })]));
    }
    modelRoot.appendChild(el("section", null, [el("h2", { text: T.secShapes }),
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
      // Where the bodies stand: on the ragdoll of skeleton.hkx, or on their nodes - said
      // outright, because a picture drawn on the nodes looks just as sure of itself.
      const rag = bench.summary.ragdoll || { state: "absent", file: null, unmatched: [] };
      const ragText = rag.state === "read"
        ? say(T.ragdollRead, { file: bench.names.ragdoll }) +
          (rag.unmatched.length ? say(T.ragdollUnmatched, { bones: rag.unmatched.join(", ") }) : "")
        : rag.state === "unreadable" ? say(T.ragdollUnreadable, { reason: rag.reason })
        : rag.file ? say(T.ragdollAbsent, { file: bench.names.ragdoll }) : "";
      const ragClass = rag.state === "read" && !rag.unmatched.length ? "muted" : "warn";
      root.appendChild(el("section", { "data-mode": "colliders", "data-tab": "display" }, [el("h2", { text: T.secCapsules }),
        el("div", { class: "current" }, [el("span", { text: bench.names.skeleton }),
          el("span", { class: "muted", text: T.summaryCapsules + bench.summary.colliders })]),
        el("div", { class: ragClass, text: ragText }),
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
    root.appendChild(el("section", { "data-tab": "display" }, [el("h2", { text: T.secColour }), modeRow,
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
    root.appendChild(el("section", { "data-tab": "display" }, [el("h2", { text: T.secLight }),
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
      const rng = el("input", { type: "range", min: range[0], max: range[1], step: step, "aria-label": name });
      const num = el("input", { type: "number", step: step, "aria-label": name });
      rng.addEventListener("input", () => { num.value = rng.value; app.invoke("set_slider", name, Number(rng.value)); });
      num.addEventListener("change", () => { app.invoke("set_slider", name, Number(num.value) || 0); });
      const row = el("div", { class: "slider" }, [el("span", { class: "name", text: name, title: name }), rng, num]);
      this.sliderRows.set(name, { row, rng, num });
      sliders.appendChild(row);
    }
    root.appendChild(el("section", { "data-mode": "morphs", "data-tab": "sliders" }, [el("h2", { text: T.secSliders }),
      bench.morphs().length ? sliders : el("div", { class: "muted", text: bench.is_open() ? T.noMorphFile : T.noMesh }),
      el("div", { class: "row", style: "margin-top:6px" }, [
        el("button", { text: T.btnResetSliders, on: { click: () => app.invoke("reset_sliders") } }),
        el("span", { class: "muted", text: T.sliderRange + range[0] + " … " + range[1] + T.fromSettings })])]));

    // bone legend
    this.legendSelect = el("select", { on: { change: () => this.refreshLegend() } });
    for (const name of bench.shape_names()) this.legendSelect.appendChild(el("option", { value: name, text: name }));
    if (bench.shapes.has(st.baseShape)) this.legendSelect.value = st.baseShape;
    this.legend = el("div", { class: "legend" });
    this.legendSection = el("section", { "data-tab": "display" }, [el("h2", { text: T.secLegend }), this.legendSelect, this.legend]);
    root.appendChild(this.legendSection);

    // state
    this.lastCall = el("pre", { text: "" });
    this.state = el("pre");
    this.command = el("pre");
    this.note = el("div", { class: "muted" });
    this.error = el("div", { class: "err" });
    root.appendChild(el("section", { class: "session-section" }, [el("details", null, [el("summary", { text: T.secState }),
      el("div", { class: "muted", text: T.lastCall }), this.lastCall,
      el("div", { class: "muted", text: T.stateLine }), this.state,
      el("div", { class: "muted", text: T.sameFrame }), this.command]), this.note, this.error]));
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
    this.modelSelect = el("select", { class: "mesh-browser", size: "8", "aria-label": T.chooseMesh,
      on: { change: () => this.onModel() } });
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
    this.rootInput = el("input", { type: "text", class: "wide", value: srv.root || "", title: T.browseFolder,
      "aria-label": T.browseFolder });
    this.allBox = el("input", { type: "checkbox", on: { change: () => this.go({ root: this.rootInput.value }) } });
    this.allBox.checked = !srv.withMorphs;
    this.skeletonInput=el("input",{type:"text",class:"wide",value:bench.summary&&bench.summary.skeleton||"","aria-label":T.edSkeletonPath});
    return el("section", null, [el("h2", { text: T.secModel }), current, this.modelSelect,
      el("div", { class: "row", style: "margin-top:6px" }, [this.rootInput,
        el("button", { text: T.btnBrowse, on: { click: () => this.go({ root: this.rootInput.value }) } })]),
      el("div", { class: "row" }, [el("label", null, [this.allBox, T.lblWithoutMorphs])]),
      el("details",null,[el("summary",{text:T.edSkeletonPath}),el("div",{class:"row"},[this.skeletonInput,
        el("button",{text:T.edLoad,on:{click:()=>this.go({root:srv.root,skeleton:this.skeletonInput.value})}})])]),
      envLine, el("div", { class: "err", text: srv.error || "" })]);
  }
  // Going to the same server with another body or another root: the page holds one body, so
  // changing the model is a reload with a different query, not a second set of geometry.
  go(params) {
    const workspace = this.bench.workspace_state();
    params.mode = workspace.mode;
    params.tab = workspace.tab;
    if(this.app.addons&&this.app.addons.active&&params.addon===undefined)params.addon=this.app.addons.active;
    if(params.skeleton===undefined&&this.bench.summary&&this.bench.summary.skeleton)params.skeleton=this.bench.summary.skeleton;
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
    this.slotsPanel.refresh();
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
    this.fileRespectBox.checked=view.respectFileVisibility;
    this.fileHiddenBox.checked=view.showFileHidden;this.fileHiddenBox.disabled=!view.respectFileVisibility;
    const fileState=bench.file_visibility();
    this.fileVisibilitySummary.textContent=say(T.visibilitySummary,{visible:fileState.counts.visible,hidden:fileState.counts.hidden,
      unknown:fileState.counts.unknown,included:fileState.counts.inspectionVisible});

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
    if(state.respectFileVisibility)parts.push("--respect-file-visibility");
    if(state.respectFileVisibility&&state.showFileHidden)parts.push("--show-file-hidden");
    if (Math.abs(state.zoom - 1.0) > 1e-9) parts.push("--zoom", fmt(state.zoom));
    if (state.pan[0] !== 0 || state.pan[1] !== 0) parts.push("--pan=" + state.pan[0] + "," + state.pan[1]);
    if (state.width !== st.imageWidth || state.height !== st.imageHeight)
      parts.push("--size", state.width + "x" + state.height);
    if (state.focus) {
      const i = state.focus.name.indexOf(":");
      parts.push("--focus-" + state.focus.name.slice(0, i), q(state.focus.name.slice(i + 1)));
    }
    // The capsule layer: the skeleton is named outright, even though render would have found it
    // beside the mesh on its own - and so is the ragdoll the bodies stand on, wherever it came from.
    if (state.colliders && bench.summary.skeleton) {
      parts.push("--skeleton", q(bench.summary.skeleton));
      const rag = bench.summary.ragdoll;
      if (rag && rag.state === "read") parts.push("--hkx", q(rag.file));
      parts.push("--colliders");
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
