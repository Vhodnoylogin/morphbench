"use strict";

// Plugin packages live in opaque-origin frames. Discovery enables their tabs;
// only opening a tab mounts its frame and exposes this versioned message door.
function pluginTone(identifier) {
  const tones=["violet","amber","blue","rose","green","cyan"];
  let hash=0;
  for(const character of identifier)hash=(Math.imul(hash,31)+character.codePointAt(0))>>>0;
  return tones[hash%tones.length];
}

class AddonHost {
  constructor(app) {
    this.app=app;this.active=null;this.generation=null;this.frame=null;this.entries=[];this.opened=false;
    this.panel=el("aside",{id:"addon-panel",class:"inspector",role:"tabpanel",hidden:"hidden"});
    document.querySelector(".workspace").appendChild(this.panel);
    this.nav=document.getElementById("mode-nav");this.tabs=new Map();
    this.manager=el("button",{id:"plugin-menu-button",class:"plugin-menu-button",type:"button",
      "aria-haspopup":"dialog","aria-controls":"plugin-menu",text:T.addonTitle,on:{click:()=>this.openManager()}});
    document.getElementById("plugin-menu-slot").appendChild(this.manager);
    this.menu=el("dialog",{id:"plugin-menu",class:"plugin-menu","aria-labelledby":"plugin-menu-title"});
    this.menu.appendChild(el("div",{class:"plugin-menu-heading"},[
      el("h2",{id:"plugin-menu-title",text:T.addonTitle}),
      el("button",{type:"button",text:T.pluginClose,on:{click:()=>this.menu.close()}})]));
    this.managerPanel=el("div",{class:"plugin-menu-content"});this.menu.appendChild(this.managerPanel);
    document.body.appendChild(this.menu);
    if(app.workspace)app.workspace.setAddonTabs(this.tabs);
    if(!app.bench.server){this.manager.disabled=true;this.manager.title=T.addonServer;return;}
    this.listener=(event)=>this.receive(event);
    window.addEventListener("message",this.listener);
    this.ready=this.refresh().then(()=>{
      const wanted=new URL(window.location.href).searchParams.get("addon");
      if(wanted&&!this.opened){
        if(this.entries.some((row)=>row.id===wanted&&row.enabled&&row.compatible))this.select(wanted);
        else this.openManager(T.addonDisabled);
      }
    }).catch((error)=>{
      this.manager.title=String(error.message||error);this.openManager(this.manager.title);
    });
  }
  previewManager() {
    if(!this.previewHost)this.previewHost=new AddonPreviewHost(this);
    return this.previewHost;
  }
  exportManager() {
    if(!this.exportHost)this.exportHost=new AddonExportHost(this);
    return this.exportHost;
  }
  notify(event,data) {
    this.frame?.contentWindow?.postMessage({type:"morphbench-addon:event",apiVersion:1,event,data},"*");
  }
  async json(path, options={}) {
    const response=await fetch(path,options),data=await response.json();
    if(!response.ok)throw Object.assign(Error(data.error||T.addonFailure),{code:data.code||"operationFailed"});
    return data;
  }
  async refresh() {
    const data=await this.json("/api/addons?rescan=1");this.entries=data.addons;
    this.directory=data.directory||"";this.discoveryErrors=data.discoveryErrors||[];
    for(const node of this.tabs.values())node.remove();
    this.tabs=new Map();
    for(const row of this.entries.filter((entry)=>entry.enabled&&entry.compatible)){
      const button=el("button",{id:"addon-tab-"+row.id,class:"mode-button addon-workspace-tab",type:"button",
        "aria-controls":"addon-panel","data-addon":row.id,on:{click:()=>this.select(row.id)}},
        [el("span",{text:row.name}),el("span",{class:"mode-badge plugin-badge",text:T.wsPlugin})]);
      button.setAttribute("data-plugin-tone",pluginTone(row.id));
      this.nav.appendChild(button);this.tabs.set(row.id,button);
    }
    if(this.app.workspace)this.app.workspace.setAddonTabs(this.tabs);
    if(this.active&&!this.entries.some((entry)=>entry.id===this.active&&entry.enabled&&entry.compatible&&entry.generation===this.generation))this.close();
    this.paintNav();
    this.manager.textContent=T.addonTitle+" · "+this.entries.filter(row=>row.enabled&&row.compatible).length;
    if(this.menu.open)this.showManager();
  }
  paintNav() {
    if(this.app.workspace){this.app.workspace.refresh();return;}
    for(const node of this.nav.querySelectorAll("[data-addon]")){
      const selected=this.opened&&node.getAttribute("data-addon")===this.active;
      node.classList.toggle("on",selected);node.setAttribute("aria-pressed",String(selected));
    }
  }
  select(identifier,reload=false) {
    if(!identifier){this.openManager();return;}
    const entry=identifier&&this.entries.find((row)=>row.id===identifier&&row.enabled&&row.compatible);
    if(identifier&&!entry)return;
    if(this.menu.open)this.menu.close();
    // Selecting the current workspace is not a request to discard its iframe,
    // independent previews or unsaved controls. Reload is an explicit action.
    if(!reload&&this.opened&&this.active===identifier&&(!entry||this.frame&&this.generation===entry.generation)){
      this.paintNav();return;
    }
    this.destroyFrame();this.opened=true;this.active=identifier;this.generation=entry?entry.generation:null;
    document.getElementById("panel").hidden=true;this.panel.hidden=false;this.panel.textContent="";
    this.panel.setAttribute("aria-labelledby","addon-tab-"+identifier);
    this.panel.setAttribute("data-plugin-tone",pluginTone(identifier));
    this.panel.appendChild(el("div",{class:"plugin-workspace-heading"},[
      el("span",{class:"plugin-dot","aria-hidden":"true"}),el("h2",{text:entry.name}),
      el("span",{class:"mode-badge plugin-badge",text:T.wsPlugin})]));
    this.panel.appendChild(el("div",{class:"row plugin-workspace-actions"},[
      el("button",{type:"button",text:T.addonReturn,on:{click:()=>this.close()}}),
      el("button",{type:"button",text:T.addonFrameReload,on:{click:()=>this.select(identifier,true)}})]));
    if(entry){
      const status=el("p",{class:"muted",role:"status",text:T.addonFrameLoading});
      this.panel.appendChild(status);
      const frame=el("iframe",{class:"addon-frame",title:entry.name,sandbox:"allow-scripts",
        referrerpolicy:"no-referrer"});
      frame.addEventListener("load",()=>{if(this.frame===frame)status.hidden=true;});
      this.frame=frame;
      this.frameReady=this.loadFrame(frame,"/addon-assets/"+encodeURIComponent(entry.id)+"/"+encodeURIComponent(entry.generation)+"/"+entry.entry.split("/").map(encodeURIComponent).join("/"),status);
    }
    const url=new URL(window.location.href);
    if(identifier)url.searchParams.set("addon",identifier);else url.searchParams.delete("addon");
    window.history.replaceState(null,"",url);this.paintNav();
  }
  async loadFrame(frame,url,status) {
    // An iframe load event also fires for HTTP failures; its error event is
    // deliberately suppressed by browsers. Check the pinned asset as the parent
    // before mounting it, without parsing or executing its HTML outside the sandbox.
    const controller=new AbortController();this.frameLoad=controller;
    const timeout=this.app.bench.settings.addonFrameLoadTimeoutMs;
    let timer;
    try{
      if(!Number.isSafeInteger(timeout)||timeout<1)throw this.failure("invalidParams");
      timer=setTimeout(()=>controller.abort(),timeout);
      const response=await fetch(url,{signal:controller.signal,cache:"no-store"});
      if(!response.ok)throw this.failure("operationFailed");
      if(this.frame!==frame)return;
      if(controller.signal.aborted)throw this.failure("operationFailed");
      frame.setAttribute("src",url);this.panel.appendChild(frame);
    }catch(error){
      if(this.frame===frame){status.hidden=false;status.className="error";status.textContent=T.addonFrameError;this.frame=null;}
    }finally{
      clearTimeout(timer);if(this.frameLoad===controller)this.frameLoad=null;
    }
  }
  destroyFrame() {
    if(this.frameLoad)this.frameLoad.abort();this.frameLoad=null;
    if(this.previewHost)this.previewHost.reset();if(this.exportHost)this.exportHost.reset();if(this.frame)this.frame.remove();this.frame=null;
  }
  close() {
    this.destroyFrame();this.active=null;this.generation=null;this.opened=false;this.panel.hidden=true;
    document.getElementById("panel").hidden=false;
    const url=new URL(window.location.href);url.searchParams.delete("addon");window.history.replaceState(null,"",url);
    this.paintNav();
  }
  openManager(message="") {
    this.showManager();
    this.managerError.textContent=message;
    if(!this.menu.open)this.menu.showModal();
  }
  showManager() {
    this.managerPanel.textContent="";
    const content=el("div",{class:"addon-manager"});this.managerPanel.appendChild(content);
    content.appendChild(el("p",{text:T.addonInstallNote}));
    content.appendChild(el("p",{class:"plugin-directory",text:this.directory||T.pluginDefaultDirectory}));
    const error=el("p",{class:"error",role:"status"});content.appendChild(error);
    this.managerError=error;
    for(const failure of this.discoveryErrors||[])
      content.appendChild(el("p",{class:"error",text:(failure.path?failure.path+": ":"")+(failure.error?.message||failure.message||T.addonFailure)}));
    const pathInput=el("input",{type:"text",class:"wide","aria-label":T.pluginPath,placeholder:T.pluginPathHint,required:"required"});
    const load=el("button",{type:"submit",class:"primary",text:T.pluginLoad});
    const form=el("form",{class:"plugin-path-form"},[
      el("label",null,[T.pluginPath,pathInput]),el("div",{class:"row"},[load,
        el("button",{type:"button",text:T.pluginRescan,on:{click:async()=>{
          try{await this.refresh();}catch(exc){error.textContent=String(exc.message||exc);}
        }}})])]);
    form.addEventListener("submit",async(event)=>{
      event.preventDefault();if(!pathInput.value.trim())return;
      load.disabled=true;error.textContent="";
      try{await this.json("/api/addons/load",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({path:pathInput.value.trim()})});await this.refresh();}
      catch(exc){error.textContent=String(exc.message||exc);load.disabled=false;}
    });
    content.appendChild(form);
    const zipInput=(label,path)=>{
      const input=el("input",{type:"file",accept:".zip,application/zip","aria-label":label});
      input.addEventListener("change",async()=>{
        if(!input.files.length)return;input.disabled=true;
        try{
          const installed=await this.json(path,{method:"POST",headers:{"Content-Type":"application/zip"},body:input.files[0]});
          if(path==="/api/addons/install")await this.json("/api/addons/enabled",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:installed.id,enabled:true})});
          await this.refresh();
        }
        catch(exc){error.textContent=String(exc.message||exc);input.disabled=false;input.value="";}
      });return input;
    };
    content.appendChild(el("details",{class:"plugin-zip-controls"},[el("summary",{text:T.pluginZipOptions}),
      el("label",null,[T.addonInstall,zipInput(T.addonInstall,"/api/addons/install")]),
      el("p",{text:T.addonUpdateNote}),
      el("label",null,[T.addonUpdate,zipInput(T.addonUpdate,"/api/addons/update")])]));
    if(!this.entries.length)content.appendChild(el("p",{text:T.addonEmpty}));
    for(const row of this.entries){
      const toggle=el("input",{type:"checkbox","aria-label":row.name||row.id});toggle.checked=row.enabled;
      toggle.disabled=!row.compatible;
      toggle.addEventListener("change",async()=>{
        toggle.disabled=true;
        try{await this.json("/api/addons/enabled",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:row.id,enabled:toggle.checked})});await this.refresh();}
        catch(exc){error.textContent=String(exc.message||exc);toggle.checked=row.enabled;toggle.disabled=!row.compatible;}
      });
      content.appendChild(el("section",{class:"plugin-card","data-plugin-tone":pluginTone(row.id)},[
        el("div",{class:"plugin-card-heading"},[el("span",{class:"plugin-dot","aria-hidden":"true"}),
          el("strong",{text:row.name||row.id}),el("span",{class:"muted",text:row.version||""})]),
        el("label",{class:"plugin-toggle"},[toggle,row.enabled?T.addonEnabled:T.addonDisabledState]),
        el("button",{type:"button",text:T.addonOpen,...(!row.enabled||!row.compatible?{disabled:"disabled"}:{}),
          on:{click:()=>this.select(row.id)}}),
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
            capabilities:["host.info","models.list","models.open","morphs.get","morphs.set","morphs.reset","scene.get","scene.geometry","view.get","view.set","state.get","state.set","state.reset",...ADDON_PREVIEW_METHODS,...ADDON_EXPORT_METHODS],previewLimits:this.previewManager().limits(),exportLimits:this.exportManager().limits(),scope:"browser-session",
            stateScope:"tab-session",stateLimits:bench.addon_state_limits()};break;
        case "exports.prepare":case "exports.cancel":
          reply.result=this.exportManager().request(request.method,params,
            {frame:this.frame,source,identifier:this.active,generation:this.generation},receivedAt);break;
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
