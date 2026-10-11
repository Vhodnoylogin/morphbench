"use strict";
// Numeric mirror of morphbench/placements.py; format adapters live separately.
const placementClone = (value) => JSON.parse(JSON.stringify(value));
const placementMV = (matrix, vector) => matrix.map((row) => dot(row, vector));
const placementDet = (matrix) => dot(matrix[0], cross(matrix[1], matrix[2]));

class PlacementMirror {
  constructor(settings, state, limits) {
    this.cfg = settings;
    this.limits = limits || {count:settings.placementLimit,coordinate:settings.placementCoordinateLimit,rotationTolerance:settings.placementRotationTolerance};
    if(Object.keys(this.limits).sort().join()!==["coordinate","count","rotationTolerance"].sort().join()||!Number.isInteger(this.limits.count)||this.limits.count<=0||["coordinate","rotationTolerance"].some((key)=>typeof this.limits[key]!=="number"||!Number.isFinite(this.limits[key])||this.limits[key]<=0)) this.fail("limits");
    this.metadata = {};
    this.authored = new Map();
    this.overrides = new Map();
    this.selected = null;
    this.mode = state ? state.mode : "mesh";
    this.anchors = state ? state.anchors : {};
    if (state) {
      this.replace(state.project.metadata, state.project.placements);
      for (const row of state.effective) {
        const author = this.authored.get(row.name), changes = {};
        for (const key of ["position", "rotation", "radius", "center", "enabled"])
          if (JSON.stringify(row[key]) !== JSON.stringify(author[key])) changes[key] = row[key];
        this.overrides.set(row.name, changes);
      }
      this.selected = state.selected;
    }
  }
  fail(field) { throw new Error(say(T.slotsInvalid, { field: field })); }
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
    this.metadata = placementClone(metadata); this.authored = candidate; this.overrides = new Map();
    this.selected = [...candidate.keys()].sort()[0] || null;
    return this.project();
  }
  project() { return placementClone({ metadata: this.metadata, placements: [...this.authored.keys()].sort().map((name) => this.authored.get(name)) }); }
  require(name) { if (!this.authored.has(name)) throw new Error(say(T.slotsMissing, { name: name })); return this.authored.get(name); }
  add(name, anchor, attributes) {
    if (this.authored.has(name) || this.authored.size >= this.limits.count) this.fail("name/count");
    const row = this.validate({name: name, anchor: anchor, position: [0,0,0], rotation: [[1,0,0],[0,1,0],[0,0,1]],
      radius: this.cfg.placementRadius, center: [0,0,0], enabled: true, attributes: attributes || {}});
    this.authored.set(name, row); this.selected = name; return placementClone(row);
  }
  set(name, changes, customize) {
    const author = this.require(name), allowed = customize ? ["position","rotation","radius","center","enabled"] : Object.keys(author).filter((key) => key !== "name");
    if (!changes || Array.isArray(changes) || typeof changes !== "object" || Object.keys(changes).some((key) => !allowed.includes(key))) this.fail("changes");
    const candidate = this.validate(Object.assign({}, author, customize ? this.overrides.get(name) : {}, changes));
    if (customize) {
      const override = {}; for (const key of allowed) if (JSON.stringify(candidate[key]) !== JSON.stringify(author[key])) override[key] = candidate[key];
      this.overrides.set(name, override);
    } else this.authored.set(name, candidate);
    return placementClone(candidate);
  }
  effective() { return [...this.authored.keys()].sort().map((name) => placementClone(Object.assign({}, this.authored.get(name), this.overrides.get(name)))); }
  preview() {
    return this.effective().map((row) => {
      const frame = this.anchors[row.anchor];
      const item = {name: row.name, anchor: row.anchor, enabled: row.enabled,
        customized: !!Object.keys(this.overrides.get(row.name) || {}).length, available: false};
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
