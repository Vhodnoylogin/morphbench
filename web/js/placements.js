"use strict";
// Numeric mirror of morphbench/placements.py; format adapters live separately.
const placementFail = (field) => { throw new Error(say(T.slotsInvalid, {field:field})); };
const placementClone = (value) => JSON.parse(JSON.stringify(value, (key,item) => {
  if (item === undefined || typeof item === "function" || typeof item === "symbol" ||
      (typeof item === "number" && !Number.isFinite(item))) placementFail("JSON");
  return item;
}));
const composePlacement = (author,override) => placementClone(Object.assign({},author,override));
const placementMV = (matrix, vector) => matrix.map((row) => dot(row, vector));
const placementDet = (matrix) => dot(matrix[0], cross(matrix[1], matrix[2]));
const PLACEMENT_RECIPE_ARITY = {
  slots_replace:[2,2],slots_add:[2,3],slots_select:[1,1],slots_set:[2,2],slots_customize:[2,2],
  slots_clear:[1,1],slots_remove:[1,1],slots_metadata:[1,1],slots_mode:[0,1],
  slots_project:[0,0],slots_effective:[0,0],slots_preview:[0,0],slots_state:[0,0],slots_restore:[1,1]
};

// JSON.parse supplies syntax validation and string decoding. This small token walk
// rejects duplicate object members before they can silently replace earlier data.
function placementParseJSON(text) {
  const value=JSON.parse(text),tokens=text.match(/"(?:[^"\\]|\\.)*"|[{}\[\]:,]|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null/g)||[];
  let index=0;
  const visit=()=>{
    const token=tokens[index++];
    if(token==="{") {
      const keys=new Set();
      if(tokens[index]!=="}") do {
        const key=JSON.parse(tokens[index++]);if(keys.has(key)) placementFail("duplicate JSON field");keys.add(key);
        index++;visit();
      } while(tokens[index++]===",");
      else index++;
    } else if(token==="[") {
      if(tokens[index]!=="]") do {visit();} while(tokens[index++]===",");
      else index++;
    }
  };
  visit();return placementClone(value);
}

class PlacementMirror {
  constructor(settings, state, limits) {
    this.cfg = settings;
    this.limits = limits || {count:settings.placementLimit,coordinate:settings.placementCoordinateLimit,rotationTolerance:settings.placementRotationTolerance};
    if(Object.keys(this.limits).sort().join()!==["coordinate","count","rotationTolerance"].sort().join()||!Number.isInteger(this.limits.count)||this.limits.count<=0||["coordinate","rotationTolerance"].some((key)=>typeof this.limits[key]!=="number"||!Number.isFinite(this.limits[key])||this.limits[key]<=0)) this.fail("limits");
    this._metadata = {};
    this._authored = new Map();
    this._overrides = new Map();
    this._selected = null;
    this._mode = "mesh";
    this._anchors = state ? placementClone(state.anchors) : {};
    if (state) {
      if(state.session) this.restore(state.session);
      else {
        // Payloads generated before editable checkpoints carried effective rows only.
        this.replace(state.project.metadata, state.project.placements);
        for (const row of state.effective) {
          const author = this._authored.get(row.name), changes = {};
          for (const key of ["position", "rotation", "radius", "center", "enabled"])
            if (JSON.stringify(row[key]) !== JSON.stringify(author[key])) changes[key] = row[key];
          this._overrides.set(row.name, changes);
        }
        this.select(state.selected);this.setMode(state.mode);
      }
    }
  }
  get mode() { return this._mode; }
  get selected() { return this._selected; }
  anchors() { return placementClone(this._anchors); }
  fail(field) { placementFail(field); }
  validate(row) {
    const keys = ["name", "anchor", "position", "rotation", "radius", "center", "enabled", "attributes"];
    if (!row || Array.isArray(row) || Object.keys(row).sort().join() !== keys.sort().join()) this.fail("placement");
    const out = placementClone(row);
    for (const key of ["name", "anchor"]) if (typeof out[key] !== "string" || !out[key].trim()) this.fail(key);
    if (typeof out.enabled !== "boolean" || !out.attributes || Array.isArray(out.attributes) || typeof out.attributes !== "object") this.fail("enabled/attributes");
    const vector = (value, length, field) => {
      if (!Array.isArray(value) || value.length !== length || value.some((x) => typeof x !== "number" || !Number.isFinite(x) || Math.abs(x) > this.limits.coordinate)) this.fail(field);
    };
    vector(out.position, 3, "position"); vector(out.center, 3, "center");
    if (!Array.isArray(out.rotation) || out.rotation.length !== 3) this.fail("rotation");
    out.rotation.forEach((row) => vector(row, 3, "rotation"));
    const rotation = out.rotation, tolerance = this.limits.rotationTolerance;
    for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++)
      if (Math.abs(dot(rotation[i], rotation[j]) - (i === j ? 1 : 0)) > tolerance) this.fail("rotation");
    if (Math.abs(placementDet(rotation) - 1) > tolerance) this.fail("rotation");
    if (typeof out.radius !== "number" || !Number.isFinite(out.radius) || out.radius <= 0 || out.radius > this.limits.coordinate) this.fail("radius");
    return out;
  }
  replace(metadata, rows) {
    if (!metadata || Array.isArray(metadata) || typeof metadata !== "object" || !Array.isArray(rows) || rows.length > this.limits.count) this.fail("project");
    const candidate = new Map();
    for (const row of rows) { const value = this.validate(row); if (candidate.has(value.name)) this.fail("name"); candidate.set(value.name, value); }
    this._metadata = placementClone(metadata); this._authored = candidate; this._overrides = new Map();
    this._selected = [...candidate.keys()].sort()[0] || null;
    return this.project();
  }
  project() { return placementClone({ metadata: this._metadata, placements: [...this._authored.keys()].sort().map((name) => this._authored.get(name)) }); }
  _require(name) {
    if(typeof name!=="string") this.fail("name");
    if (!this._authored.has(name)) throw new Error(say(T.slotsMissing, { name: name }));
    return this._authored.get(name);
  }
  setMode(mode="slots") { if(!["mesh","slots"].includes(mode)) this.fail("mode");this._mode=mode;return mode; }
  select(name) { if(name!==null) this._require(name);this._selected=name;return name; }
  clear(name) { this._require(name);this._overrides.delete(name);return this.effective(); }
  remove(name) {
    this._require(name);this._authored.delete(name);this._overrides.delete(name);
    this._selected=[...this._authored.keys()].sort()[0]||null;return this.project();
  }
  setMetadata(metadata) {
    if(!metadata||typeof metadata!=="object"||Array.isArray(metadata)) this.fail("metadata");
    this._metadata=placementClone(metadata);return placementClone(this._metadata);
  }
  add(name, anchor, attributes) {
    if (typeof name!=="string" || this._authored.has(name) || this._authored.size >= this.limits.count) this.fail("name/count");
    const row = this.validate({name: name, anchor: anchor, position: [0,0,0], rotation: [[1,0,0],[0,1,0],[0,0,1]],
      radius: this.cfg.placementRadius, center: [0,0,0], enabled: true, attributes: attributes == null ? {} : attributes});
    this._authored.set(name, row); this._selected = name; return placementClone(row);
  }
  set(name, changes, customize) {
    const author = this._require(name), allowed = customize ? ["position","rotation","radius","center","enabled"] : Object.keys(author).filter((key) => key !== "name");
    if (!changes || Array.isArray(changes) || typeof changes !== "object" || Object.keys(changes).some((key) => !allowed.includes(key))) this.fail("changes");
    const candidate = this.validate(Object.assign({}, author, customize ? this._overrides.get(name) : {}, changes));
    if (customize) {
      const override = {},explicit = new Set(Object.keys(this._overrides.get(name)||{}).concat(Object.keys(changes)));
      for (const key of explicit) override[key] = candidate[key];
      this._overrides.set(name, override);
    } else this._authored.set(name, candidate);
    return placementClone(candidate);
  }
  effective() { return [...this._authored.keys()].sort().map((name) => composePlacement(this._authored.get(name), this._overrides.get(name))); }
  session() {
    return placementClone({version:1,project:this.project(),overrides:[...this._overrides.keys()].sort()
      .filter((name)=>Object.keys(this._overrides.get(name)).length).map((name)=>({name:name,changes:this._overrides.get(name)})),
      selected:this._selected,mode:this._mode});
  }
  restore(session) {
    if(!session||Array.isArray(session)||typeof session!=="object"||Object.keys(session).sort().join()!==["version","project","overrides","selected","mode"].sort().join()||session.version!==1) this.fail("session");
    const project=session.project;
    if(!project||Array.isArray(project)||typeof project!=="object"||Object.keys(project).sort().join()!==["metadata","placements"].sort().join()) this.fail("project");
    const candidate=new PlacementMirror(this.cfg,null,this.limits);
    candidate.replace(project.metadata,project.placements);
    if(!Array.isArray(session.overrides)||session.overrides.length>this.limits.count) this.fail("overrides");
    const allowed=["position","rotation","radius","center","enabled"];
    for(const item of session.overrides) {
      if(!item||Array.isArray(item)||typeof item!=="object"||Object.keys(item).sort().join()!==["name","changes"].sort().join()) this.fail("override");
      const name=item.name,changes=item.changes,author=candidate._require(name);
      if(candidate._overrides.has(name)||!changes||Array.isArray(changes)||typeof changes!=="object"||!Object.keys(changes).length||Object.keys(changes).some((key)=>!allowed.includes(key))) this.fail("override");
      const row=candidate.validate(Object.assign({},author,changes)),override={};
      for(const key of Object.keys(changes)) override[key]=row[key];
      candidate._overrides.set(name,override);
    }
    candidate.select(session.selected);candidate.setMode(session.mode);
    this._commit(candidate);return this.session();
  }
  _commit(candidate) {
    this._metadata=candidate._metadata;this._authored=candidate._authored;this._overrides=candidate._overrides;
    this._selected=candidate._selected;this._mode=candidate._mode;
  }
  recipe() { return [{method:"slots_restore",args:[this.session()]}]; }
  replay(actions) {
    if(!Array.isArray(actions)||actions.length>this.cfg.placementRecipeLimit) this.fail("recipe");
    actions=placementClone(actions);
    for(const action of actions) {
      if(!action||Array.isArray(action)||typeof action!=="object"||Object.keys(action).sort().join()!==["method","args"].sort().join()||typeof action.method!=="string"||!Object.prototype.hasOwnProperty.call(PLACEMENT_RECIPE_ARITY,action.method)||!Array.isArray(action.args)) this.fail("action");
      const [low,high]=PLACEMENT_RECIPE_ARITY[action.method];
      if(action.args.length<low||action.args.length>high) this.fail("action arguments");
    }
    const candidate=new PlacementMirror(this.cfg,null,this.limits);candidate.restore(this.session());
    const calls={slots_replace:(...args)=>candidate.replace(...args),slots_add:(...args)=>candidate.add(...args),
      slots_select:(...args)=>candidate.select(...args),slots_set:(name,changes)=>candidate.set(name,changes,false),
      slots_customize:(name,changes)=>candidate.set(name,changes,true),slots_clear:(...args)=>candidate.clear(...args),
      slots_remove:(...args)=>candidate.remove(...args),slots_metadata:(...args)=>candidate.setMetadata(...args),
      slots_mode:(...args)=>candidate.setMode(...args),slots_restore:(...args)=>candidate.restore(...args)};
    for(const action of actions) if(Object.prototype.hasOwnProperty.call(calls,action.method)) calls[action.method](...action.args);
    this._commit(candidate);return this.session();
  }
  preview() {
    return this.effective().map((row) => {
      const frame = this._anchors[row.anchor];
      const item = {name: row.name, anchor: row.anchor, enabled: row.enabled,
        customized: !!Object.keys(this._overrides.get(row.name) || {}).length, available: false};
      if (!frame || frame.length !== 4 || frame.some((line) => line.length !== 4 || line.some((x) => !Number.isFinite(x))) || frame[3].some((x,i)=>Math.abs(x-(i===3?1:0))>this.cfg.placementRotationTolerance)) return item;
      const basis = frame.slice(0,3).map((line) => line.slice(0,3)), scale = Math.cbrt(placementDet(basis));
      if (scale <= 0) return item;
      const rigid = basis.map((line) => line.map((x) => x / scale));
      for (let i=0;i<3;i++) for(let j=0;j<3;j++) if (Math.abs(dot(rigid[i],rigid[j])-(i===j?1:0)) > this.cfg.placementRotationTolerance) return item;
      const rotationCenter = placementMV(row.rotation,row.center), localCenter = row.position.map((x,i) => x+rotationCenter[i]);
      item.origin = placementMV(basis,row.position).map((x,i) => x+frame[i][3]);
      item.center = placementMV(basis,localCenter).map((x,i) => x+frame[i][3]);
      item.radius = row.radius*scale;
      item.axes = basis.map((line) => [0,1,2].map((index) => dot(line,row.rotation.map((r) => r[index]))));
      item.available = true; return item;
    });
  }
  meshes() {
    const segments = Math.max(4,Math.trunc(this.cfg.colliderSegments)), rings = Math.max(2,Math.trunc(segments/2)), unit=[], triangles=[];
    for(let ring=0;ring<=rings;ring++) for(let edge=0;edge<segments;edge++) {
      const latitude=Math.PI*ring/rings,longitude=2*Math.PI*edge/segments;
      unit.push([Math.sin(latitude)*Math.cos(longitude),Math.sin(latitude)*Math.sin(longitude),Math.cos(latitude)]);
    }
    for(let ring=0;ring<rings;ring++) for(let edge=0;edge<segments;edge++) {
      const a=ring*segments+edge,b=ring*segments+(edge+1)%segments;
      triangles.push([a,b,a+segments],[b,b+segments,a+segments]);
    }
    const out=[];
    for(const row of this.preview()) {
      if(!row.available||!row.enabled) continue;
      const scale=norm(row.axes.map((line)=>line[0])), marker=row.radius*this.cfg.placementMarkerFraction;
      const marks=[["region",row.center,row.radius],["origin",row.origin,marker]];
      ["x","y","z"].forEach((axis,index)=>marks.push([axis,row.origin.map((x,i)=>x+row.axes[i][index]/scale*row.radius),marker]));
      for(const [kind,center,radius] of marks) out.push({name:row.name+":"+kind,kind:kind,
        vertices:unit.map((point)=>point.map((x,i)=>x*radius+center[i])),triangles:triangles});
    }
    return out;
  }
}
