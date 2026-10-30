"use strict";

// Versioned add-on operations mirror AddonSessionMixin, through the same facade as
// ordinary controls. No package receives the facade object or live typed arrays.
Object.assign(BenchMirror.prototype, {
  addon_state_limits() {
    const limits={maxBytes:this.settings.addonStateMaxBytes,maxDepth:this.settings.addonStateMaxDepth};
    if(Object.values(limits).some((value)=>!Number.isSafeInteger(value)||value<=0))
      throw Object.assign(Error(T.addonParams),{code:"invalidLimits"});
    return limits;
  },
  addon_validate_state(value) {
    const limits=this.addon_state_limits(),ancestors=new Set();
    const fail=(code="invalidState")=>{throw Object.assign(Error(T.addonParams),{code});};
    const text=(value)=>{
      // Reject unpaired UTF-16 surrogates rather than silently replacing user data.
      for(let i=0;i<value.length;i++){
        const c=value.charCodeAt(i);
        if(c>=0xd800&&c<=0xdbff){const next=value.charCodeAt(++i);if(!(next>=0xdc00&&next<=0xdfff))fail();}
        else if(c>=0xdc00&&c<=0xdfff)fail();
      }
    };
    const check=(item,depth)=>{
      if(depth>limits.maxDepth)fail("limitExceeded");
      if(item===null||typeof item==="boolean")return;
      if(typeof item==="string"){text(item);return;}
      if(typeof item==="number"&&Number.isFinite(item))return;
      if(typeof item!=="object"||ancestors.has(item)||(!Array.isArray(item)&&Object.getPrototypeOf(item)!==Object.prototype&&Object.getPrototypeOf(item)!==null))fail();
      ancestors.add(item);
      try{
        if(Array.isArray(item)){
          for(let i=0;i<item.length;i++){if(!Object.hasOwn(item,i))fail();check(item[i],depth+1);}
        }else for(const [key,child] of Object.entries(item)){text(key);check(child,depth+1);}
      }finally{ancestors.delete(item);}
    };
    check(value,0);
    return JSON.parse(JSON.stringify(value));
  },
  addon_decode_state(data) {
    if(typeof data!=="string")throw Object.assign(Error(T.addonParams),{code:"invalidState"});
    if(new TextEncoder().encode(data).length>this.addon_state_limits().maxBytes)
      throw Object.assign(Error(T.addonParams),{code:"limitExceeded"});
    let value;
    try{value=JSON.parse(data);}catch(error){throw Object.assign(Error(T.addonParams),{code:"invalidState"});}
    return this.addon_validate_state(value);
  },
  addon_scene() {
    const visible = new Set(this.visible_shapes());
    return JSON.parse(JSON.stringify({open:this.is_open(), names:this.names, summary:this.summary,
      shapes:this.shape_names().map((name)=>({name,vertices:this.shape(name).count,
        triangles:this.shape(name).triCount,visible:visible.has(name)})),
      workspace:this.workspace_state(),colliders:this.collider_edit_state(),fileVisibility:this.file_visibility()}));
  },
  addon_geometry(name) {
    if(!this.is_open()) throw Object.assign(Error(T.addonNoMesh),{code:"noMesh"});
    const shape=this.shape(name);
    return {name,space:"model",vertices:Array.from(this.deformed(name)),baseVertices:Array.from(shape.base),
      triangles:Array.from(shape.tris),boneNames:shape.boneNames.slice()};
  },
  addon_morphs() { return {names:this.morphs(),values:this.sliders()}; },
  addon_set_morphs(values) {
    if(!this.is_open())throw Object.assign(Error(T.addonNoMesh),{code:"noMesh"});
    if(!values||typeof values!=="object"||Array.isArray(values)||Object.entries(values).some(
      ([name,value])=>!this.morphs().includes(name)||typeof value!=="number"||!Number.isFinite(value)))throw Object.assign(Error(T.addonParams),{code:"invalidParams"});
    const previous=this.sliders();
    try {
      this.set_sliders(values);
      if(this.shape_names().some((name)=>Array.from(this.deformed(name)).some((value)=>!Number.isFinite(value))))throw Object.assign(Error(T.addonParams),{code:"invalidParams"});
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
        (name)=>typeof name!=="string"||!this.shape_names().includes(name)))))throw Object.assign(Error(T.addonParams),{code:"invalidParams"});
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
