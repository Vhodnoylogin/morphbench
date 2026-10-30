"use strict";

// Versioned add-on operations mirror AddonSessionMixin, through the same facade as
// ordinary controls. No package receives the facade object or live typed arrays.
Object.assign(BenchMirror.prototype, {
  addon_scene() {
    const visible = new Set(this.visible_shapes());
    return JSON.parse(JSON.stringify({open:this.is_open(), names:this.names, summary:this.summary,
      shapes:this.shape_names().map((name)=>({name,vertices:this.shape(name).count,
        triangles:this.shape(name).triCount,visible:visible.has(name)})),
      workspace:this.workspace_state(),colliders:this.collider_edit_state(),fileVisibility:this.file_visibility()}));
  },
  addon_geometry(name) {
    if(!this.is_open()) throw Error(T.addonNoMesh);
    const shape=this.shape(name);
    return {name,space:"model",vertices:Array.from(this.deformed(name)),baseVertices:Array.from(shape.base),
      triangles:Array.from(shape.tris),boneNames:shape.boneNames.slice()};
  },
  addon_morphs() { return {names:this.morphs(),values:this.sliders()}; },
  addon_set_morphs(values) {
    if(!this.is_open())throw Error(T.addonNoMesh);
    if(!values||typeof values!=="object"||Array.isArray(values)||Object.entries(values).some(
      ([name,value])=>!this.morphs().includes(name)||typeof value!=="number"||!Number.isFinite(value)))throw Error(T.addonParams);
    const previous=this.sliders();
    try {
      this.set_sliders(values);
      if(this.shape_names().some((name)=>Array.from(this.deformed(name)).some((value)=>!Number.isFinite(value))))throw Error(T.addonParams);
    } catch(error) {this._sliders=new Map(Object.entries(previous));throw error;}
    return this.addon_morphs();
  },
  addon_reset_morphs() {this.reset_sliders();return this.addon_morphs();},
  addon_view() {return JSON.parse(JSON.stringify({state:this.view_state(true),presets:this.presets()}));},
  addon_set_view(changes) {
    const numeric=(value)=>typeof value==="number"&&Number.isFinite(value);
    if(!changes||typeof changes!=="object"||Array.isArray(changes)
      ||Object.keys(changes).some((key)=>!["preset","yaw","pitch","zoom","pan","visibleShapes"].includes(key))
      ||["yaw","pitch","zoom"].some((key)=>key in changes&&!numeric(changes[key]))
      ||("zoom" in changes&&changes.zoom<=0)
      ||("preset" in changes&&(typeof changes.preset!=="string"||!Object.hasOwn(this.presets(),changes.preset)))
      ||("pan" in changes&&(!Array.isArray(changes.pan)||changes.pan.length!==2
        ||!changes.pan.every((value)=>numeric(value)&&Number.isFinite(Math.fround(value)))))
      ||("visibleShapes" in changes&&(!Array.isArray(changes.visibleShapes)||changes.visibleShapes.some(
        (name)=>typeof name!=="string"||!this.shape_names().includes(name)))))throw Error(T.addonParams);
    const previous=this.view;
    this.view=new ViewMirror(this.settings,this.presets(),this.view_state(true));
    try {
      if("preset" in changes)this.preset(changes.preset);
      if("yaw" in changes||"pitch" in changes)this.look(changes.yaw??this.view.yaw,changes.pitch??this.view.pitch);
      if("zoom" in changes)this.zoom(changes.zoom);
      if("pan" in changes)this.pan(...changes.pan.map(Math.fround));
      if("visibleShapes" in changes)this.only(changes.visibleShapes);
      return this.addon_view();
    }catch(error){this.view=previous;throw error;}
  }
});
