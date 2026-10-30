"use strict";

// Additive API v1: each handle owns one independent model, camera and canvas.
// Domain mapping belongs to the add-on. The existing single-view methods keep
// their original target and schemas.
const ADDON_PREVIEW_METHODS = Object.freeze([
  "previews.create", "previews.list", "previews.close", "previews.scene.get",
  "previews.geometry", "previews.morphs.get", "previews.morphs.set",
  "previews.morphs.reset", "previews.view.get", "previews.view.set",
  "previews.link", "previews.unlink"
]);

class AddonPreviewHost {
  constructor(host) {
    this.host=host;this.items=new Map();this.pending=new Map();this.serial=0;
    this.epoch=0;this.links=new Set();this.stage=null;this.hidden=[];
  }
  limits() {
    const settings=this.host.app.bench.settings;
    const maxPreviews=settings.addonMaxPreviews,loadTimeoutMs=settings.addonPreviewLoadTimeoutMs;
    // The SDK v1 request timeout is 10 seconds. The entire create operation,
    // including authorization, must have a shorter budget.
    if(!Number.isSafeInteger(maxPreviews)||maxPreviews<1
      ||!Number.isSafeInteger(loadTimeoutMs)||loadTimeoutMs<1||loadTimeoutMs>=10000)
      throw this.host.failure("invalidParams",T.addonPreviewConfig);
    return {maxPreviews,loadTimeoutMs};
  }
  current(scope) {
    return scope.epoch===this.epoch&&this.host.frame===scope.frame
      &&this.host.frame?.contentWindow===scope.source&&this.host.active===scope.identifier
      &&this.host.generation===scope.generation;
  }
  requireCurrent(scope) {
    if(!this.current(scope))throw this.host.failure("staleGeneration",T.addonDisabled);
  }
  async authorize(scope,signal) {
    this.requireCurrent(scope);
    const installed=await this.host.json("/api/addons",{signal});
    this.requireCurrent(scope);
    const entry=installed.addons.find(row=>row.id===scope.identifier&&row.enabled&&row.compatible);
    if(!entry)throw this.host.failure("disabled",T.addonDisabled);
    if(entry.generation!==scope.generation)throw this.host.failure("staleGeneration",T.addonDisabled);
  }
  target(preview) {
    const item=typeof preview==="string"&&this.items.get(preview);
    if(!item)throw this.host.failure("unknownPreview",T.addonUnknownPreview);
    this.requireCurrent(item.scope);return item;
  }
  descriptor(item) {return {preview:item.id,name:item.name};}
  notify(item,event,data) {
    if(this.current(item.scope))this.host.notify(event,data);
  }
  changed(item,method) {this.notify(item,"previews.changed",{preview:item.id,method});}
  cameraKey(state) {return JSON.stringify([state.yaw,state.pitch,state.zoom,state.pan,state.preset]);}
  cameraEvent(item,state,source,method) {
    item.revision++;
    this.notify(item,"previews.view.changed",{
      preview:item.id,state,revision:item.revision,source,method
    });
  }
  cameraChanged(item,state,method) {
    if(this.items.get(item.id)!==item||!this.current(item.scope))return;
    this.cameraEvent(item,state,item.id,method);
    if(this.links.has(item.id))this.synchronize(item,state,method);
  }
  synchronize(source,state,method) {
    for(const id of this.links) {
      if(id===source.id)continue;
      const target=this.target(id),before=target.surface.bench.addon_view().state;
      const after=target.surface.invokeSilent("addon_set_view",{yaw:state.yaw,pitch:state.pitch}).state;
      if(this.cameraKey(before)!==this.cameraKey(after))this.cameraEvent(target,after,source.id,method);
    }
  }
  ensureStage() {
    if(this.stage)return;
    const app=this.host.app,viewport=document.getElementById("viewport");
    // Pause the hidden main renderer before its canvas loses CSS dimensions;
    // otherwise ResizeObserver could change the main camera's viewport state.
    app.previewStageActive=true;
    this.hidden=Array.from(viewport.children).map(node=>({node,hidden:node.hidden}));
    for(const {node} of this.hidden)node.hidden=true;
    const modelPanel=document.getElementById("model-panel");
    if(modelPanel){this.hidden.push({node:modelPanel,hidden:modelPanel.hidden});modelPanel.hidden=true;}
    this.stage=el("div",{class:"addon-preview-grid"});
    viewport.classList.add("has-addon-previews");viewport.appendChild(this.stage);
  }
  restoreStage() {
    if(this.stage)this.stage.remove();this.stage=null;
    for(const {node,hidden} of this.hidden)node.hidden=hidden;
    this.hidden=[];
    const viewport=document.getElementById("viewport");
    if(viewport)viewport.classList.remove("has-addon-previews");
    this.host.app.previewStageActive=false;
    if(this.host.app.draw)this.host.app.draw();
  }
  async create(params,identity,receivedAt) {
    this.host.params(params,["name"],["name"]);
    if(typeof params.name!=="string"||!params.name)throw this.host.failure("invalidParams");
    const limits=this.limits(),deadline=receivedAt+limits.loadTimeoutMs;
    const remaining=deadline-Date.now();
    if(remaining<=0)throw this.host.failure("previewTimeout",T.addonPreviewTimeout);
    if(this.items.size+this.pending.size>=limits.maxPreviews)throw this.host.failure("previewLimit",T.addonPreviewLimit);
    const root=this.host.app.bench.server?.root;
    if(typeof root!=="string"||!root)throw this.host.failure("noMesh",T.addonNoMesh);
    const scope={...identity,epoch:this.epoch};this.requireCurrent(scope);
    const item={id:"preview-"+(++this.serial),name:params.name,scope,revision:0,surface:null};
    const controller=new AbortController();let timer,rejectCancellation;
    const cancellation=new Promise((resolve,reject)=>{rejectCancellation=reject;});
    const token={cancel:()=>{rejectCancellation(this.host.failure("staleGeneration",T.addonDisabled));controller.abort();}};
    this.pending.set(item.id,token);
    const timeout=new Promise((resolve,reject)=>{
      timer=setTimeout(()=>{reject(this.host.failure("previewTimeout",T.addonPreviewTimeout));controller.abort();},remaining);
    });
    try {
      const load=(async()=>{
        const payload=await this.host.json("/api/preview-payload?"+new URLSearchParams({root,name:params.name,all:"1"}),{signal:controller.signal});
        await this.authorize(scope,controller.signal);return payload;
      })();
      const payload=await Promise.race([load,timeout,cancellation]);
      this.requireCurrent(scope);
      if(this.pending.get(item.id)!==token||Date.now()>=deadline)
        throw this.host.failure("previewTimeout",T.addonPreviewTimeout);
      this.ensureStage();
      item.surface=new AddonPreviewSurface(this.stage,payload,{
        onCameraChange:(state,method)=>this.cameraChanged(item,state,method)
      });
      this.requireCurrent(scope);
      if(Date.now()>=deadline)throw this.host.failure("previewTimeout",T.addonPreviewTimeout);
      this.items.set(item.id,item);this.changed(item,"previews.create");
      return this.descriptor(item);
    } catch(error) {
      if(this.items.get(item.id)===item)this.items.delete(item.id);
      if(item.surface)item.surface.dispose();
      if(!this.items.size&&this.stage)this.restoreStage();
      throw error;
    } finally {
      clearTimeout(timer);if(this.pending.get(item.id)===token)this.pending.delete(item.id);
    }
  }
  close(preview) {
    const item=this.target(preview);this.items.delete(preview);this.links.delete(preview);
    if(this.links.size<2)this.links.clear();
    item.surface.dispose();if(!this.items.size)this.restoreStage();
    this.changed(item,"previews.close");return {closed:true};
  }
  reset() {
    this.epoch++;
    for(const token of this.pending.values())token.cancel();this.pending.clear();
    for(const item of this.items.values())item.surface.dispose();this.items.clear();this.links.clear();
    if(this.stage)this.restoreStage();
  }
  async request(method,params,identity,receivedAt) {
    const check=(keys,required=keys)=>this.host.params(params,keys,required);
    switch(method) {
      case "previews.create":return this.create(params,identity,receivedAt);
      case "previews.list":check([]);return {previews:Array.from(this.items.values(),item=>this.descriptor(item))};
      case "previews.close":check(["preview"]);return this.close(params.preview);
      case "previews.unlink":check([]);this.links.clear();return {previews:[],properties:[]};
      case "previews.link": {
        check(["previews","properties"]);
        if(!Array.isArray(params.previews)||params.previews.length<2
          ||new Set(params.previews).size!==params.previews.length
          ||!Array.isArray(params.properties)||params.properties.length!==1||params.properties[0]!=="orientation")
          throw this.host.failure("invalidParams");
        const items=params.previews.map(id=>this.target(id));
        this.links=new Set(items.map(item=>item.id));
        this.synchronize(items[0],items[0].surface.bench.addon_view().state,"previews.link");
        return {previews:Array.from(this.links),properties:["orientation"]};
      }
      case "previews.scene.get":check(["preview"]);return this.target(params.preview).surface.bench.addon_scene();
      case "previews.geometry": {
        check(["preview","shape"]);const bench=this.target(params.preview).surface.bench;
        if(typeof params.shape!=="string"||!bench.shape_names().includes(params.shape))throw this.host.failure("unknownShape");
        return bench.addon_geometry(params.shape);
      }
      case "previews.morphs.get":check(["preview"]);return this.target(params.preview).surface.bench.addon_morphs();
      case "previews.morphs.set":case "previews.morphs.reset": {
        check(method==="previews.morphs.set"?["preview","values"]:["preview"]);
        const item=this.target(params.preview),before=JSON.stringify(item.surface.bench.addon_morphs());
        const result=method==="previews.morphs.set"?item.surface.invoke("addon_set_morphs",params.values):item.surface.invoke("addon_reset_morphs");
        if(before!==JSON.stringify(result))this.changed(item,method);return result;
      }
      case "previews.view.get":check(["preview"]);return this.target(params.preview).surface.bench.addon_view();
      case "previews.view.set": {
        check(["preview","preset","yaw","pitch","zoom","pan","visibleShapes"],["preview"]);
        const item=this.target(params.preview),{preview,...changes}=params;
        return item.surface.invoke("addon_set_view",changes);
      }
      default:throw this.host.failure("unknownMethod",T.addonMethod);
    }
  }
}
