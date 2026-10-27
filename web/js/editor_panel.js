"use strict";
// Controls only: all edits enter App.invoke and the numeric facade.
class EditorPanel {
  constructor(app,root) {
    this.app=app;this.bench=app.bench;this.root=root;this.fieldSignature="";
    this.makeColliders();this.makePhysics();
    const svgTemplate=document.createElement("template");svgTemplate.innerHTML="<svg></svg>";
    this.overlay=svgTemplate.content.firstElementChild;
    this.svgNamespace=this.overlay.namespaceURI;
    this.overlay.id="editor-overlay";this.overlay.setAttribute("aria-hidden","true");
    Object.assign(this.overlay.style,{position:"absolute",inset:"0",width:"100%",height:"100%",pointerEvents:"none",overflow:"hidden"});
    app.canvas.parentElement.appendChild(this.overlay);
  }
  section(mode,tab,title) {
    const section=el("section",{"data-mode":mode,"data-tab":tab,class:"editor-section"},[el("h2",{text:title})]);
    this.root.insertBefore(section,this.root.querySelector(".session-section"));return section;
  }
  button(text,callback) {return el("button",{type:"button",text,on:{click:callback}});}
  fail(error) {this.app.panel.error.textContent=String(error.message||error);}
  download(name,text,type="application/json") {
    const url=URL.createObjectURL(new Blob([text],{type})),link=el("a",{href:url,download:name});
    document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  selected() {const state=this.bench.collider_edit_state(),sel=state.selected;return sel?state.capsules.find((c)=>c.bone===sel.bone&&c.index===sel.index):null;}
  makeColliders() {
    const section=this.section("colliders","edit",T.edCollider);
    this.capsuleSelect=el("select",{"aria-label":T.edChoose,on:{change:()=>{
      const cap=this.bench.collider_edit_state().capsules[Number(this.capsuleSelect.value)];if(cap)this.app.invoke("collider_select",cap.bone,cap.index);
    }}});section.appendChild(this.capsuleSelect);
    section.appendChild(el("p",{class:"muted",text:T.edFrame}));
    this.capsuleFields={};
    for(const [key,label] of [["p1",T.edP1],["p2",T.edP2],["radius",T.edRadius]]) {
      const count=key==="radius"?1:3,fields=[];
      const row=el("div",{class:"row"},[el("span",{text:label,class:"editor-field-label"})]);
      for(let i=0;i<count;i++) {const input=el("input",{type:"number",step:String(this.bench.settings.editorStep),class:"short","aria-label":label+(count>1?" XYZ"[i+1]:"")});if(key==="radius") input.min="0";fields.push(input);row.appendChild(input);}
      this.capsuleFields[key]=fields;section.appendChild(row);
    }
    this.apply=this.button(T.edApply,()=>{
      const cap=this.selected();if(!cap)return;
      const changes={};for(const key of ["p1","p2","radius"]) {const values=this.capsuleFields[key].map((field)=>field.value.trim()===""?NaN:Number(field.value));changes[key]=key==="radius"?values[0]:values;}
      this.app.invoke("collider_set",cap.bone,cap.index,changes);
    });
    this.duplicate=this.button(T.edAdd,()=>{const cap=this.selected();if(cap)this.app.invoke("collider_add",cap.bone,cap.p1,cap.p2,cap.radius);});
    this.remove=this.button(T.edRemove,()=>{const cap=this.selected();if(cap)this.app.invoke("collider_remove",cap.bone,cap.index);});
    section.appendChild(el("div",{class:"row editor-actions"},[this.apply,this.duplicate,this.remove]));
    section.appendChild(this.button(T.edReset,()=>this.app.invoke("collider_reset")));
    section.appendChild(el("p",{class:"muted",text:T.edDrag}));
    this.colliderNote=el("p",{class:"muted"});section.appendChild(this.colliderNote);
    section.appendChild(el("div",{class:"row editor-actions"},[
      this.button(T.edRecipe,()=>this.download("morphbench-edits.json",JSON.stringify(this.bench.workspace_recipe(),null,2))),
      this.button(T.edSkeleton,()=>this.exportSkeleton())]));
    this.recipeUpload=el("input",{type:"file",accept:".json","aria-label":T.edImportRecipe,on:{change:()=>this.importRecipe()}});
    section.appendChild(el("label",{class:"slot-field"},[T.edImportRecipe,this.recipeUpload]));
  }
  async importRecipe() {
    try {
      const file=this.recipeUpload.files[0];if(!file)return;
      if(file.size>this.bench.settings.workspaceRequestLimit) throw Error(T.edInvalid);
      const recipe=placementParseJSON(await file.text());
      if(recipe.format!=="morphbench-workspace"||recipe.version!==1) throw Error(T.edInvalid);
      if(!Array.isArray(recipe.actions))throw Error(T.edInvalid);
      if(recipe.actions.some((action)=>String(action.method).startsWith("collider_"))&&JSON.stringify(recipe.source)!==JSON.stringify(DATA.source)) throw Error(T.edStale);
      this.app.invoke("workspace_replay",recipe.actions);
    }catch(error){this.fail(error);}
  }
  async exportSkeleton() {
    try {
      if(!this.bench.server)throw Error(T.edNoServerExport);
      const response=await fetch("/api/workspace/skeleton",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(this.bench.workspace_recipe())});
      if(!response.ok){const problem=await response.json();throw Error(problem.error);}
      this.download("morphbench-skeleton.nif",await response.arrayBuffer(),"application/octet-stream");
    }catch(error){this.fail(error);}
  }
  makePhysics() {
    const section=this.section("physics","configuration",T.edPhysics);
    this.kind=el("select",{"aria-label":T.edImport},[el("option",{value:"fsmp",text:"FSMP · XML"}),el("option",{value:"cbpc",text:"CBPC · TXT"})]);
    this.configUpload=el("input",{type:"file",accept:".xml,.txt,.json","aria-label":T.edLoad,on:{change:()=>this.importPhysics()}});
    section.appendChild(el("div",{class:"row"},[this.kind,this.configUpload]));
    this.physicsNote=el("p",{class:"muted",text:T.edNoConfig});section.appendChild(this.physicsNote);
    this.groups=el("select",{"aria-label":T.edGroup,on:{change:()=>{this.fieldSignature="";this.refreshPhysics();}}});
    this.filter=el("input",{type:"text",placeholder:T.edFilter,on:{input:()=>{this.fieldSignature="";this.refreshPhysics();}}});
    section.appendChild(el("div",{class:"row editor-actions"},[this.groups,this.filter]));
    this.fields=el("div",{class:"physics-fields"});section.appendChild(this.fields);
    this.rawDirty=false;
    this.source=el("textarea",{rows:"8","aria-label":T.edSource,spellcheck:"false",style:"width:100%",on:{input:()=>{this.rawDirty=true;}}});
    section.appendChild(el("details",null,[el("summary",{text:T.edSource}),this.source,this.button(T.edApplySource,()=>this.applySource())]));
    section.appendChild(el("div",{class:"row editor-actions"},[
      this.button(T.edExport,()=>{const state=this.bench.physics_state();if(state.document)this.download("morphbench-physics."+(state.document.kind==="fsmp"?"xml":"txt"),this.bench.physics_export(),"text/plain;charset=utf-8");}),
      this.button(T.edSession,()=>this.download("morphbench-workspace.json",JSON.stringify(this.bench.workspace_recipe(),null,2)))]));
    const ranges=this.section("physics","ranges",T.edRanges);
    ranges.appendChild(el("p",{class:"warn",text:T.edNominal}));
    this.rangeNotes=el("div",{class:"muted"});ranges.appendChild(this.rangeNotes);
    this.rangeValues=el("pre");ranges.appendChild(this.rangeValues);
  }
  async importPhysics() {
    try {
      const file=this.configUpload.files[0];if(!file)return;
      if(file.size>this.bench.settings.physicsMaxChars*4)throw Error(T.edInvalid);
      let text;
      if(file.arrayBuffer)text=new TextDecoder("utf-8",{fatal:true,ignoreBOM:true}).decode(await file.arrayBuffer());else text=await file.text();
      if(file.name.toLowerCase().endsWith(".json")) {
        const recipe=placementParseJSON(text);
        if(recipe.format!=="morphbench-workspace"||recipe.version!==1)throw Error(T.edInvalid);
        // A configuration workspace can travel without a mesh; capsule recipes still bind their original source.
        const capsuleActions=recipe.actions.some((action)=>String(action.method).startsWith("collider_"));
        if(capsuleActions&&JSON.stringify(recipe.source)!==JSON.stringify(DATA.source))throw Error(T.edStale);
        this.app.invoke("workspace_replay",recipe.actions);return;
      }
      if(!this.bench.server)throw Error(T.edServer);
      const kind=file.name.toLowerCase().endsWith(".xml")?"fsmp":this.kind.value;
      const response=await fetch("/api/physics/import",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({kind,text})});
      const parsed=await response.json();if(!response.ok)throw Error(parsed.error);
      this.app.invoke("physics_replace",parsed.document);this.app.invoke("workspace_mode","physics");
      this.rawDirty=false;this.fieldSignature="";this.refresh();
    }catch(error){this.fail(error);}
  }
  async applySource() {
    try {
      if(!this.bench.server)throw Error(T.edServer);
      const response=await fetch("/api/physics/import",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({kind:this.kind.value,text:this.source.value})});
      const parsed=await response.json();if(!response.ok)throw Error(parsed.error);
      this.rawDirty=false;this.app.invoke("physics_replace",parsed.document);
    }catch(error){this.fail(error);}
  }
  refreshPhysics() {
    const state=this.bench.physics_state(),document=state.document,fields=state.fields||[];
    if(!document) {this.physicsNote.textContent=T.edNoConfig;this.fields.textContent="";return;}
    this.kind.value=document.kind;
    this.physicsNote.textContent=say(T.edChanged,{count:fields.filter((field)=>field.changed).length});
    const groups=state.groups||document.groups||[],signature=JSON.stringify(groups.map((group)=>[group.id,group.label]));
    if(this.groups.dataset.signature!==signature) {
      this.groups.textContent="";this.groups.appendChild(el("option",{value:"",text:T.edFields}));
      for(const group of groups)this.groups.appendChild(el("option",{value:group.id,text:group.label}));
      this.groups.dataset.signature=signature;
    }
    const filter=this.filter.value.toLowerCase(),wanted=fields.filter((field)=>(!this.groups.value||field.group===this.groups.value)&&(!filter||((field.label||"")+" "+(field.group||"")).toLowerCase().includes(filter)));
    const fieldSignature=JSON.stringify(wanted.map((field)=>[field.id,field.value,field.changed]));
    if(fieldSignature!==this.fieldSignature) {
      this.fieldSignature=fieldSignature;this.fields.textContent="";
      for(const field of wanted) {
        const input=el("input",{type:"number",step:"any",value:String(field.value),"aria-label":field.label+" · "+field.id,on:{change:()=>this.app.invoke("physics_set",field.id,input.value.trim()===""?NaN:Number(input.value))}});
        this.fields.appendChild(el("label",{class:"physics-field"},[el("span",{text:field.label,title:field.id}),input]));
      }
    }
    if(!this.rawDirty)this.source.value=this.bench.physics_export();
    const result=this.bench.physics_envelopes();
    const warnings=[...(state.warnings||[]),...(result.warnings||[])];
    this.rangeNotes.textContent=warnings.map((warning)=>warning.message||warning.code||String(warning)).filter((value,index,array)=>array.indexOf(value)===index).join("\n");
    this.rangeValues.textContent=JSON.stringify(result.records||[],null,2);
  }
  refresh() {
    const state=this.bench.collider_edit_state(),selected=state.selected;
    const signature=state.capsules.map((cap)=>cap.bone+":"+cap.index+":"+cap.editable).join("|");
    if(this.capsuleSelect.dataset.signature!==signature) {
      this.capsuleSelect.textContent="";this.capsuleSelect.appendChild(el("option",{value:"",text:T.edChoose}));
      state.capsules.forEach((cap,index)=>this.capsuleSelect.appendChild(el("option",{value:String(index),text:cap.bone+" · "+cap.index+(cap.editable?"":" · "+T.edReadonly)})));
      this.capsuleSelect.dataset.signature=signature;
    }
    const index=selected?state.capsules.findIndex((cap)=>cap.bone===selected.bone&&cap.index===selected.index):-1;
    this.capsuleSelect.value=index<0?"":String(index);
    const cap=index>=0?state.capsules[index]:null;
    for(const [key,fields] of Object.entries(this.capsuleFields))fields.forEach((field,i)=>{field.disabled=!cap||!cap.editable;if(field!==document.activeElement)field.value=cap?String(key==="radius"?cap.radius:cap[key][i]):"";});
    this.apply.disabled=this.duplicate.disabled=this.remove.disabled=!cap||!cap.editable;
    this.colliderNote.textContent=state.capsules.length?"":T.edNoCapsules;
    this.refreshPhysics();
  }
  project(point) {
    const framed=this.bench.framing(),basis=this.bench.view.basis(),scale=this.app.scale/(window.devicePixelRatio||1),rect=this.app.canvas.getBoundingClientRect();
    const delta=point.map((x,i)=>x-framed[0][i]);return [rect.width/2+dot(delta,basis.right)*scale,rect.height/2-dot(delta,basis.up)*scale];
  }
  pick(event) {
    const rect=this.app.canvas.getBoundingClientRect(),at=[event.clientX-rect.left,event.clientY-rect.top],state=this.bench.collider_edit_state();let best=null,distance=this.bench.settings.editorPickPixels;
    for(const cap of state.capsules.filter((item)=>item.editable)) {
      const matrix=state.bodyMatrices[cap.bone],point=this.project(editorPoint(matrix,cap.p1.map((x,i)=>(x+cap.p2[i])/2))),dist=Math.hypot(point[0]-at[0],point[1]-at[1]);
      if(dist<distance){best=cap;distance=dist;}
    }
    if(best)this.app.invoke("collider_select",best.bone,best.index);
  }
  drawOverlay() {
    this.overlay.textContent="";
    const mode=this.bench.workspace_state().mode;if(!["colliders","physics"].includes(mode))return;
    const add=(tag,attrs)=>{const element=document.createElementNS(this.svgNamespace,tag);for(const [key,value] of Object.entries(attrs))element.setAttribute(key,String(value));this.overlay.appendChild(element);};
    try {
      if(mode==="colliders") {
        const state=this.bench.collider_edit_state(),cap=this.selected();if(!cap)return;
        const matrix=state.bodyMatrices[cap.bone];
        for(const point of [cap.p1,cap.p2]){const screen=this.project(editorPoint(matrix,point));add("circle",{cx:screen[0],cy:screen[1],r:5,fill:"#5ce1ce",stroke:"#122725","stroke-width":2});}
      }else {
        const result=this.bench.physics_envelopes();
        for(const line of result.lines||[]) {
          const a=this.project(line.a),b=this.project(line.b);
          add("line",{x1:a[0],y1:a[1],x2:b[0],y2:b[1],stroke:line.kind==="angular_glyph"?"#d6b47b":"#5ce1ce","stroke-width":1.5,opacity:0.85});
        }
      }
    }catch(_){/* no model/frame: numeric inspection remains available */}
  }
}
