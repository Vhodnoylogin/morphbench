"use strict";

// Packages live in opaque-origin frames. Only this explicit, versioned message door
// can touch the current preview; installing a package does not execute it.
class AddonHost {
  constructor(app) {
    this.app=app;this.active=null;this.generation=null;this.frame=null;this.entries=[];this.opened=false;
    this.panel=el("aside",{id:"addon-panel",class:"inspector",hidden:"hidden"});
    document.querySelector(".workspace").appendChild(this.panel);
    this.nav=el("nav",{id:"addon-nav","aria-label":T.addonTitle});
    document.getElementById("mode-nav").after(this.nav);
    this.manager=el("button",{type:"button",text:T.addonTitle,on:{click:()=>this.select(null)}});
    this.nav.appendChild(this.manager);
    if(!app.bench.server){this.manager.disabled=true;this.manager.title=T.addonServer;return;}
    this.listener=(event)=>this.receive(event);
    window.addEventListener("message",this.listener);
    this.refresh().then(()=>{
      const wanted=new URL(window.location.href).searchParams.get("addon");
      if(wanted&&this.entries.some((row)=>row.id===wanted&&row.enabled&&row.compatible))this.select(wanted);
    }).catch((error)=>{this.manager.title=String(error.message||error);});
  }
  previewManager() {
    if(!this.previewHost)this.previewHost=new AddonPreviewHost(this);
    return this.previewHost;
  }
  notify(event,data) {
    if(this.frame)this.frame.contentWindow.postMessage({type:"morphbench-addon:event",apiVersion:1,event,data},"*");
  }
  async json(path, options={}) {
    const response=await fetch(path,options),data=await response.json();
    if(!response.ok)throw Object.assign(Error(data.error||T.addonFailure),{code:data.code||"operationFailed"});
    return data;
  }
  async refresh() {
    const data=await this.json("/api/addons");this.entries=data.addons;
    for(const node of Array.from(this.nav.children))if(node!==this.manager)node.remove();
    for(const row of this.entries.filter((entry)=>entry.enabled&&entry.compatible)){
      this.nav.appendChild(el("button",{type:"button",text:row.name,"data-addon":row.id,
        on:{click:()=>this.select(row.id)}}));
    }
    if(this.active&&!this.entries.some((entry)=>entry.id===this.active&&entry.enabled&&entry.compatible&&entry.generation===this.generation))this.close();
    this.paintNav();
    if(this.opened&&!this.active)this.showManager();
  }
  paintNav() {
    this.manager.classList.toggle("on",this.opened&&!this.active);
    this.manager.setAttribute("aria-pressed",String(this.opened&&!this.active));
    for(const node of this.nav.querySelectorAll("[data-addon]")){
      const selected=this.opened&&node.getAttribute("data-addon")===this.active;
      node.classList.toggle("on",selected);node.setAttribute("aria-pressed",String(selected));
    }
  }
  select(identifier) {
    const entry=identifier&&this.entries.find((row)=>row.id===identifier&&row.enabled&&row.compatible);
    if(identifier&&!entry)return;
    this.destroyFrame();this.opened=true;this.active=identifier;this.generation=entry?entry.generation:null;
    document.getElementById("panel").hidden=true;this.panel.hidden=false;this.panel.textContent="";
    this.panel.appendChild(el("h2",{text:entry?entry.name:T.addonTitle}));
    this.panel.appendChild(el("button",{type:"button",text:T.addonReturn,on:{click:()=>this.close()}}));
    if(entry){
      this.frame=el("iframe",{class:"addon-frame",title:entry.name,sandbox:"allow-scripts",
        referrerpolicy:"no-referrer",src:"/addon-assets/"+encodeURIComponent(entry.id)+"/"+encodeURIComponent(entry.generation)+"/"+entry.entry.split("/").map(encodeURIComponent).join("/")});
      this.panel.appendChild(this.frame);
    }else this.showManager();
    const url=new URL(window.location.href);
    if(identifier)url.searchParams.set("addon",identifier);else url.searchParams.delete("addon");
    window.history.replaceState(null,"",url);this.paintNav();
  }
  destroyFrame() {if(this.previewHost)this.previewHost.reset();if(this.frame)this.frame.remove();this.frame=null;}
  close() {
    this.destroyFrame();this.active=null;this.generation=null;this.opened=false;this.panel.hidden=true;
    document.getElementById("panel").hidden=false;
    const url=new URL(window.location.href);url.searchParams.delete("addon");window.history.replaceState(null,"",url);
    this.paintNav();
  }
  showManager() {
    let content=this.panel.querySelector(".addon-manager");
    if(content)content.remove();content=el("div",{class:"addon-manager"});this.panel.appendChild(content);
    content.appendChild(el("p",{text:T.addonInstallNote}));
    const error=el("p",{class:"error",role:"status"});content.appendChild(error);
    const upload=el("input",{type:"file",accept:".zip,application/zip","aria-label":T.addonInstall});
    upload.addEventListener("change",async()=>{
      if(!upload.files.length)return;upload.disabled=true;
      try{await this.json("/api/addons/install",{method:"POST",headers:{"Content-Type":"application/zip"},body:upload.files[0]});await this.refresh();}
      catch(exc){error.textContent=String(exc.message||exc);upload.disabled=false;upload.value="";}
    });content.appendChild(upload);
    content.appendChild(el("p",{text:T.addonUpdateNote}));
    const update=el("input",{type:"file",accept:".zip,application/zip","aria-label":T.addonUpdate});
    update.addEventListener("change",async()=>{
      if(!update.files.length)return;update.disabled=true;
      try{await this.json("/api/addons/update",{method:"POST",headers:{"Content-Type":"application/zip"},body:update.files[0]});await this.refresh();}
      catch(exc){error.textContent=String(exc.message||exc);update.disabled=false;update.value="";}
    });content.appendChild(update);
    if(!this.entries.length)content.appendChild(el("p",{text:T.addonEmpty}));
    for(const row of this.entries){
      const toggle=el("input",{type:"checkbox","aria-label":row.name||row.id});toggle.checked=row.enabled;
      toggle.disabled=!row.compatible;
      toggle.addEventListener("change",async()=>{
        toggle.disabled=true;
        try{await this.json("/api/addons/enabled",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:row.id,enabled:toggle.checked})});await this.refresh();}
        catch(exc){error.textContent=String(exc.message||exc);toggle.checked=row.enabled;toggle.disabled=!row.compatible;}
      });
      content.appendChild(el("section",null,[el("label",null,[toggle," "+(row.name||row.id)+" "+(row.version||"")]),
        el("p",{class:"muted",text:row.description||""}),row.error?el("p",{class:"error",text:row.error.message}):null]));
    }
  }
  changed(method) {
    if(this.opened&&["workspace_mode","workspace_tab"].includes(method)){this.close();return;}
    if(!this.frame||method==="resize")return;
    this.notify("scene.changed",{method});
  }
  failure(code,message=T.addonParams) {return Object.assign(Error(message),{code});}
  params(value,keys,required=[]) {
    if(!value||typeof value!=="object"||Array.isArray(value)||Object.keys(value).some((key)=>!keys.includes(key))
      ||required.some((key)=>!Object.hasOwn(value,key)))throw this.failure("invalidParams");
  }
  async models() {
    const root=this.app.bench.server.root;
    const entries=root?await this.json("/api/catalog?"+new URLSearchParams({root,all:"1"})):[];
    return {root,entries};
  }
  sessionState(method,identifier,params) {
    // The host owns the namespace. The opaque frame never receives a storage handle
    // and cannot name another add-on. sessionStorage survives same-tab navigation.
    const bench=this.app.bench,key="morphbench:addon-state:v1:"+identifier;
    this.params(params,method==="state.set"?["value"]:[],method==="state.set"?["value"]:[]);
    try{
      const storage=window.sessionStorage;
      if(method==="state.reset"){storage.removeItem(key);return {value:null};}
      if(method==="state.set"){
        const raw=JSON.stringify(bench.addon_validate_state(params.value)),value=bench.addon_decode_state(raw);
        storage.setItem(key,raw);return {value};
      }
      const raw=storage.getItem(key);
      if(raw===null)return {value:null};
      return {value:bench.addon_decode_state(raw)};
    }catch(error){
      if(error.code&&typeof error.code==="string")throw error;
      throw this.failure("stateUnavailable",T.addonFailure);
    }
  }
  async receive(event) {
    const source=this.frame&&this.frame.contentWindow,request=event.data;
    if(!source||event.source!==source||!request||request.type!=="morphbench-addon:request")return;
    if(typeof request.id!=="string"||request.id.length>128)return;
    const reply={type:"morphbench-addon:response",apiVersion:1,id:request.id};
    const receivedAt=Date.now();let after,closeAfterReply=false;
    try{
      if(request.apiVersion!==1)throw this.failure("incompatibleApi",T.addonApi);
      const installed=await this.json("/api/addons");
      const entry=installed.addons.find((row)=>row.id===this.active&&row.enabled&&row.compatible);
      if(this.frame?.contentWindow!==source)return;
      if(!entry){source.postMessage({...reply,error:{code:"disabled",message:T.addonDisabled}},"*");this.close();return;}
      if(entry.generation!==this.generation){source.postMessage({...reply,error:{code:"staleGeneration",message:T.addonDisabled}},"*");this.close();return;}
      const params=request.params,bench=this.app.bench;
      const invoke=(method,...args)=>{
        const result=this.app.invoke(method,...args);
        if(result===undefined)throw this.failure("invalidParams",this.app.panel.error.textContent||T.addonFailure);
        return result;
      };
      switch(request.method){
        case "host.info":
          this.params(params,[]);
          reply.result={apiVersion:1,addon:{id:entry.id,name:entry.name,version:entry.version},language:document.documentElement.lang,
            capabilities:["host.info","models.list","models.open","morphs.get","morphs.set","morphs.reset","scene.get","scene.geometry","view.get","view.set","state.get","state.set","state.reset",...ADDON_PREVIEW_METHODS],previewLimits:this.previewManager().limits(),scope:"browser-session",
            stateScope:"tab-session",stateLimits:bench.addon_state_limits()};break;
        case "state.get":case "state.set":case "state.reset":
          reply.result=this.sessionState(request.method,entry.id,params);break;
        case "models.list":this.params(params,[]);reply.result=await this.models();break;
        case "models.open":{
          this.params(params,["name"],["name"]);
          if(typeof params.name!=="string"||!(await this.models()).entries.some((row)=>row.name===params.name))throw this.failure("invalidParams");
          reply.result={navigating:true};after=()=>this.app.panel.go({name:params.name,root:bench.server.root,addon:entry.id,all:"1"});break;
        }
        case "morphs.get":this.params(params,[]);reply.result=bench.addon_morphs();break;
        case "morphs.set":
          this.params(params,["values"],["values"]);
          if(!bench.is_open())throw this.failure("noMesh",T.addonNoMesh);
          if(!params.values||typeof params.values!=="object"||Array.isArray(params.values)||Object.entries(params.values).some(
            ([name,value])=>!bench.morphs().includes(name)||typeof value!=="number"||!Number.isFinite(value)))throw this.failure("invalidParams");
          reply.result=invoke("addon_set_morphs",params.values);break;
        case "morphs.reset":this.params(params,[]);reply.result=invoke("addon_reset_morphs");break;
        case "scene.get":this.params(params,[]);reply.result=bench.addon_scene();break;
        case "scene.geometry":
          this.params(params,["shape"],["shape"]);
          if(!bench.is_open())throw this.failure("noMesh",T.addonNoMesh);
          if(typeof params.shape!=="string"||!bench.shape_names().includes(params.shape))throw this.failure("unknownShape",T.addonParams);
          reply.result=bench.addon_geometry(params.shape);break;
        case "view.get":this.params(params,[]);reply.result=bench.addon_view();break;
        case "view.set":
          this.params(params,["preset","yaw","pitch","zoom","pan","visibleShapes"]);
          // Validate and change atomically in the facade, not in this transport.
          reply.result=invoke("addon_set_view",params);break;
        default:
          if(!ADDON_PREVIEW_METHODS.includes(request.method))throw this.failure("unknownMethod",T.addonMethod);
          reply.result=await this.previewManager().request(request.method,params,
            {frame:this.frame,source,identifier:this.active,generation:this.generation},receivedAt);
          break;
      }
    }catch(error){reply.error={code:error.code||"operationFailed",message:String(error.message||error)};
      closeAfterReply=["disabled","staleGeneration"].includes(error.code);
    }
    if(this.frame?.contentWindow!==source)return;
    source.postMessage(reply,"*");
    if(closeAfterReply){this.close();return;}
    if(after){
      const identifier=this.active,generation=this.generation;
      setTimeout(async()=>{
        if(this.frame?.contentWindow!==source||this.active!==identifier||this.generation!==generation)return;
        try{
          const current=await this.json("/api/addons");
          if(this.frame?.contentWindow===source&&this.active===identifier
            &&this.generation===generation&&current.addons.some((row)=>row.id===identifier&&row.enabled&&row.compatible&&row.generation===generation))after();
        }catch(error){/* A stale or disabled frame never initiates navigation. */}
      },0);
    }
  }
}
