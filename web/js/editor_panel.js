"use strict";
// Controls only: all edits enter App.invoke and the numeric facade.
class EditorPanel {
  constructor(app,root) {
    this.app=app;this.bench=app.bench;this.root=root;this.fieldSignature="";
    this.makeColliders();this.makePPB();this.makePhysics();
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
      if(recipe.actions.some((action)=>String(action.method).startsWith("collider_")||["ppb_to_collider","ppb_from_collider"].includes(action.method))&&JSON.stringify(recipe.source)!==JSON.stringify(DATA.source)) throw Error(T.edStale);
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
  makePPB() {
    const section=this.section("colliders","ppb",T.edPpb);
    section.appendChild(el("p",{class:"warn",text:T.edPpbScope}));
    this.ppbUpload=el("input",{type:"file",accept:".txt","aria-label":T.edPpbLoad,on:{change:()=>this.importPPB()}});
    section.appendChild(el("label",{class:"slot-field"},[T.edPpbLoad,this.ppbUpload]));
    this.ppbGroup=el("select",{"aria-label":T.edPpbGroup,on:{change:()=>this.refreshPPB()}});
    section.appendChild(el("label",{class:"slot-field"},[T.edPpbGroup,this.ppbGroup]));
    this.ppbTarget=el("select",{"aria-label":T.edPpbTarget,on:{change:()=>{
      const cap=this.bench.collider_edit_state().capsules[Number(this.ppbTarget.value)];
      if(this.ppbTarget.value!==""&&cap)this.app.invoke("collider_select",cap.bone,cap.index);
    }}});
    section.appendChild(el("label",{class:"slot-field"},[T.edPpbTarget,this.ppbTarget]));
    this.ppbFields=el("div",{class:"physics-fields"});section.appendChild(this.ppbFields);
    const transfer=(method)=>{const cap=this.selected();if(cap)this.app.invoke(method,this.ppbGroup.value,cap.bone,cap.index);};
    this.ppbTo=this.button(T.edPpbTo,()=>transfer("ppb_to_collider"));
    this.ppbFrom=this.button(T.edPpbFrom,()=>transfer("ppb_from_collider"));
    section.appendChild(el("div",{class:"row editor-actions"},[this.ppbTo,this.ppbFrom]));
    this.ppbNote=el("p",{class:"muted",style:"white-space:pre-line"});section.appendChild(this.ppbNote);
    this.ppbSource=el("textarea",{rows:"8","aria-label":T.edPpbSource,spellcheck:"false",style:"width:100%",on:{input:()=>{this.ppbRawDirty=true;}}});
    section.appendChild(el("details",null,[el("summary",{text:T.edPpbSource}),this.ppbSource,this.button(T.edApplySource,()=>this.parsePPB(this.ppbSource.value))]));
    section.appendChild(this.button(T.edPpbExport,()=>{if(this.bench.ppb_state().document)this.download("PPB_tuning.morphbench.txt",this.bench.ppb_export(),"text/plain;charset=utf-8");}));
  }
  async importPPB() {
    try {
      const file=this.ppbUpload.files[0];if(!file)return;
      if(file.size>this.bench.settings.physicsMaxChars*4)throw Error(T.edInvalid);
      const text=new TextDecoder("utf-8",{fatal:true,ignoreBOM:true}).decode(await file.arrayBuffer());
      await this.parsePPB(text);
    }catch(error){this.fail(error);}
  }
  async parsePPB(text) {
    try {
      if(!this.bench.server)throw Error(T.edServer);
      const response=await fetch("/api/physics/import",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({kind:"ppb",text})});
      const parsed=await response.json();if(!response.ok)throw Error(parsed.error);
      this.ppbRawDirty=false;this.ppbFieldSignature="";this.app.invoke("ppb_replace",parsed.document);
    }catch(error){this.fail(error);}
  }
  refreshPPB() {
    const state=this.bench.ppb_state(),capsules=state.capsules||[],signature=JSON.stringify(capsules.map((cap)=>[cap.id,cap.slot,cap.index]));
    if(this.ppbGroup.dataset.signature!==signature) {
      this.ppbGroup.textContent="";this.ppbGroup.appendChild(el("option",{value:"",text:T.edPpbGroup}));
      for(const cap of capsules)this.ppbGroup.appendChild(el("option",{value:cap.id,text:cap.slot+(cap.index?" · C"+cap.index:" · 0")}));
      this.ppbGroup.dataset.signature=signature;
    }
    const collider=this.bench.collider_edit_state(),targetSignature=JSON.stringify(collider.capsules.map((cap)=>[cap.bone,cap.index,cap.editable]));
    if(this.ppbTarget.dataset.signature!==targetSignature) {
      this.ppbTarget.textContent="";this.ppbTarget.appendChild(el("option",{value:"",text:T.edPpbTarget}));
      collider.capsules.forEach((cap,index)=>this.ppbTarget.appendChild(el("option",{value:String(index),text:cap.bone+" · "+cap.index})));
      this.ppbTarget.dataset.signature=targetSignature;
    }
    const selected=this.selected(),targetIndex=selected?collider.capsules.findIndex((cap)=>cap.bone===selected.bone&&cap.index===selected.index):-1;
    this.ppbTarget.value=targetIndex<0?"":String(targetIndex);
    const cap=capsules.find((item)=>item.id===this.ppbGroup.value),fields=(state.fields||[]).filter((field)=>cap&&field.group===cap.id),fieldSignature=JSON.stringify(fields.map((field)=>[field.id,field.label]));
    if(this.ppbFieldSignature!==fieldSignature) {
      this.ppbFieldSignature=fieldSignature;this.ppbFields.textContent="";this.ppbInputs=new Map();
      for(const field of fields) {
        const input=el("input",{type:"number",step:"any","aria-label":field.label+" · PPB · "+field.id,on:{change:()=>this.app.invoke("ppb_set",field.id,input.value.trim()===""?NaN:Number(input.value))}});
        input.disabled=field.editable===false;this.ppbInputs.set(field.id,input);
        this.ppbFields.appendChild(el("label",{class:"physics-field"},[el("span",{text:field.label,title:field.id}),input]));
      }
    }
    for(const field of fields){const input=this.ppbInputs.get(field.id);if(input!==document.activeElement)input.value=String(field.value);}
    this.ppbTo.disabled=!cap||!cap.transfer_supported||!selected||!selected.editable;
    this.ppbFrom.disabled=!cap||!cap.transfer_supported||!selected;
    this.ppbNote.textContent=state.document?Array.from(new Set((state.warnings||[]).filter((warning)=>!warning.group||(cap&&warning.group===cap.id)).map((warning)=>warning.message||warning.code))).join("\n"):T.edPpbEmpty;
    if(!this.ppbRawDirty)this.ppbSource.value=state.document?this.bench.ppb_export():"";
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
        const capsuleActions=recipe.actions.some((action)=>String(action.method).startsWith("collider_")||["ppb_to_collider","ppb_from_collider"].includes(action.method));
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
    const fieldSignature=JSON.stringify(wanted.map((field)=>[field.id,field.label]));
    if(fieldSignature!==this.fieldSignature) {
      this.fieldSignature=fieldSignature;this.fields.textContent="";this.physicsInputs=new Map();
      for(const field of wanted) {
        const input=el("input",{type:"number",step:"any",value:String(field.value),"aria-label":field.label+" · "+field.id,on:{change:()=>this.app.invoke("physics_set",field.id,input.value.trim()===""?NaN:Number(input.value))}});
        this.physicsInputs.set(field.id,input);
        this.fields.appendChild(el("label",{class:"physics-field"},[el("span",{text:field.label,title:field.id}),input]));
      }
    }
    for(const field of wanted) {const input=this.physicsInputs.get(field.id);if(input!==document.activeElement)input.value=String(field.value);}
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
    this.refreshPPB();
    this.refreshPhysics();
  }
  project(point) {
    const framed=this.bench.framing(),basis=this.bench.view.basis(),scale=this.app.scale/(window.devicePixelRatio||1),rect=this.app.canvas.getBoundingClientRect();
    const delta=point.map((x,i)=>x-framed[0][i]);return [rect.width/2+dot(delta,basis.right)*scale,rect.height/2-dot(delta,basis.up)*scale];
  }
  pick(event) {
    if(!this.bench.view.colliders)return null;
    const rect=this.app.canvas.getBoundingClientRect(),at=[event.clientX-rect.left,event.clientY-rect.top],state=this.bench.collider_edit_state();
    const basis=this.bench.view.basis(),scale=this.app.scale/(window.devicePixelRatio||1),tolerance=this.bench.settings.editorPickPixels;
    const visible=new Set(this.bench.collider_mesh().map((chunk)=>chunk.bone));let best=null,rank=null;
    for(const cap of state.capsules.filter((item)=>item.editable)) {
      if(!visible.has(cap.bone))continue;
      const matrix=state.bodyMatrices[cap.bone],a=editorPoint(matrix,cap.p1),b=editorPoint(matrix,cap.p2),pa=this.project(a),pb=this.project(b);
      const axis=pb.map((x,i)=>x-pa[i]),length=axis[0]*axis[0]+axis[1]*axis[1];
      const along=length?clamp(((at[0]-pa[0])*axis[0]+(at[1]-pa[1])*axis[1])/length,0,1):0;
      const distance=Math.hypot(at[0]-pa[0]-along*axis[0],at[1]-pa[1]-along*axis[1]);
      const bodyScale=Math.max(...[0,1,2].map((i)=>Math.hypot(matrix[0][i],matrix[1][i],matrix[2][i]))),radius=cap.radius*bodyScale*scale;
      const outside=Math.max(0,distance-radius);if(outside>tolerance)continue;
      // Projection picking covers the whole capsule. Where silhouettes overlap, prefer
      // the foreground body; an actual silhouette hit wins over the outside tolerance.
      const point=a.map((x,i)=>x+along*(b[i]-x));
      const depth=dot(point,basis.forward)-Math.sqrt(Math.max(0,radius*radius-distance*distance))/scale;
      const candidate=[outside>0?1:0,outside>0?outside:depth,depth];
      if(!rank||candidate[0]<rank[0]||(candidate[0]===rank[0]&&(candidate[1]<rank[1]||(candidate[1]===rank[1]&&candidate[2]<rank[2])))) {best=cap;rank=candidate;}
    }
    if(best)this.app.invoke("collider_select",best.bone,best.index);
    return best;
  }
  drawOverlay() {
    this.overlay.textContent="";
    const mode=this.bench.workspace_state().mode;if(!["colliders","physics"].includes(mode))return;
    const add=(tag,attrs)=>{const element=document.createElementNS(this.svgNamespace,tag);for(const [key,value] of Object.entries(attrs))element.setAttribute(key,String(value));this.overlay.appendChild(element);};
    try {
      if(mode==="colliders") {
        const state=this.bench.collider_edit_state(),cap=this.selected();
        if(!cap||!this.bench.view.colliders||!this.bench.collider_mesh().some((chunk)=>chunk.bone===cap.bone))return;
        const matrix=state.bodyMatrices[cap.bone];
        const endpoints=[cap.p1,cap.p2].map((point)=>this.project(editorPoint(matrix,point)));
        add("line",{x1:endpoints[0][0],y1:endpoints[0][1],x2:endpoints[1][0],y2:endpoints[1][1],stroke:"#5ce1ce","stroke-width":2});
        for(const screen of endpoints)add("circle",{cx:screen[0],cy:screen[1],r:5,fill:"#5ce1ce",stroke:"#122725","stroke-width":2});
        if(cap.editable&&this.bench.view.colliders) {
          const centre=endpoints[0].map((x,i)=>(x+endpoints[1][i])/2),handle=document.createElementNS(this.svgNamespace,"circle");
          for(const [key,value] of Object.entries({cx:centre[0],cy:centre[1],r:this.bench.settings.editorPickPixels/2,fill:"#122725",stroke:"#5ce1ce","stroke-width":2}))handle.setAttribute(key,String(value));
          Object.assign(handle.style,{pointerEvents:"all",cursor:"grab"});
          const title=document.createElementNS(this.svgNamespace,"title");title.textContent=T.edMove;handle.appendChild(title);
          handle.addEventListener("pointerdown",(event)=>this.app.startColliderDrag(event,cap));this.overlay.appendChild(handle);
          const arm=this.bench.settings.editorPickPixels/4;
          add("path",{d:`M ${centre[0]-arm} ${centre[1]} h ${2*arm} M ${centre[0]} ${centre[1]-arm} v ${2*arm}`,stroke:"#5ce1ce","stroke-width":1.5});
        }
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
