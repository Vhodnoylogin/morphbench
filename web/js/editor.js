"use strict";
// Numerical browser facade for mode and body-local capsule edits. Text formats
// are recognized by the server adapter; this owner keeps normalized documents.
const WORKSPACE_TABS = {morphs:["sliders","display"],colliders:["edit","ppb","display"],physics:["configuration","ranges"],slots:["author","display"]};
const editorClone = (value) => JSON.parse(JSON.stringify(value));
const editorError = (field) => { throw new Error(say(T["edInvalid"] || T.slotsInvalid,{field})); };
const editorVector = (value) => {
  if(!Array.isArray(value)||value.length!==3||value.some((x)=>typeof x!=="number"||!Number.isFinite(x)||!Number.isFinite(Math.fround(x)))) editorError("vector");
  return value.map(Math.fround);
};
const editorPoint = (matrix,point) => matrix.slice(0,3).map((row)=>row[0]*point[0]+row[1]*point[1]+row[2]*point[2]+row[3]);
const editorPPBCopy = (owner) => {
  const state=owner.ppb.state(),copy=new PhysicsWorkspaceMirror(null,DATA.physicsTexts||{},{max_chars:owner.bench.settings.physicsMaxChars,max_fields:owner.bench.settings.physicsMaxFields});
  if(state.document){copy.replace(state.document);for(const [id,value] of Object.entries(state.edits||{}))copy.set(id,value);}
  return copy;
};
function editorLocalDelta(matrix,world) {
  const a=matrix.slice(0,3).map((row)=>row.slice(0,3)),det=dot(a[0],cross(a[1],a[2]));
  if(!Number.isFinite(det)||Math.abs(det)<1e-10) editorError("frame");
  const cols=[cross(a[1],a[2]),cross(a[2],a[0]),cross(a[0],a[1])];
  return [0,1,2].map((axis)=>(cols[0][axis]*world[0]+cols[1][axis]*world[1]+cols[2][axis]*world[2])/det);
}
function editorCapsuleMesh(cap,matrix,segments) {
  const seg=Math.max(4,segments|0),rings=Math.max(2,Math.floor(seg/3));
  const axis=cap.p2.map((x,i)=>x-cap.p1[i]),length=norm(axis),w=length>1e-6?axis.map((x)=>x/length):[0,0,1];
  const tmp=[0,0,0];tmp[w.map(Math.abs).indexOf(Math.min(...w.map(Math.abs)))]=1;
  let u=cross(w,tmp);const ul=norm(u);u=u.map((x)=>x/ul);const v=cross(w,u);
  const levels=[];
  for(let i=0;i<=rings;i++) {const angle=-Math.PI/2+i*Math.PI/(2*rings);levels.push([cap.p1.map((x,j)=>x+w[j]*Math.sin(angle)*cap.radius),Math.cos(angle)]);}
  for(let i=rings;i>=0;i--) {const angle=-Math.PI/2+i*Math.PI/(2*rings);levels.push([cap.p2.map((x,j)=>x-w[j]*Math.sin(angle)*cap.radius),Math.cos(angle)]);}
  const points=[],indices=[];
  for(const [base,radius] of levels) for(let i=0;i<seg;i++) {
    const angle=2*Math.PI*i/seg;
    points.push(...editorPoint(matrix,base.map((x,j)=>x+cap.radius*radius*(Math.cos(angle)*u[j]+Math.sin(angle)*v[j]))));
  }
  for(let row=0;row<levels.length-1;row++) for(let i=0;i<seg;i++) {
    const j=(i+1)%seg,a=row*seg,b=(row+1)*seg;indices.push(a+i,b+i,b+j,a+i,b+j,a+j);
  }
  const pos=new Float32Array(points),tris=new Uint32Array(indices);
  return {name:"editable:"+cap.bone+":"+cap.index,bone:cap.bone,index:cap.index,pos,tris,count:pos.length/3,triCount:tris.length/3,nrm:vertexNormals(pos,tris,new Float32Array(pos.length))};
}
class EditorState {
  constructor(bench) {
    this.bench=bench;
    this.mode=(DATA.workspace||{}).mode||(bench.placements.mode==="slots"?"slots":"morphs");
    this.tabs={};this.tabs[this.mode]=(DATA.workspace||{}).tab||WORKSPACE_TABS[this.mode][0];
    this.original=editorClone(DATA.colliderEditor||{capsules:[],bodies:[],selected:null,bodyMatrices:{},nodeMatrices:{}});
    this.state=editorClone(this.original);this.actions=editorClone(this.original.editActions||[]);
    if(this.original.originalCapsules)this.original.capsules=editorClone(this.original.originalCapsules);
    this.original.selected=null;this.original.changed=[];
    for(const body of this.original.bodies){body.changed=false;body.count=this.original.capsules.filter((cap)=>cap.bone===body.bone).length;}
    this.physics=new PhysicsWorkspaceMirror(null,DATA.physicsTexts||{},{max_chars:this.bench.settings.physicsMaxChars,max_fields:this.bench.settings.physicsMaxFields});
    if(DATA.physics&&DATA.physics.document) {
      this.physics.replace(DATA.physics.document);
      for(const [id,value] of Object.entries(DATA.physics.edits||{})) this.physics.set(id,value);
    }
    this.ppb=new PhysicsWorkspaceMirror(null,DATA.physicsTexts||{},{max_chars:this.bench.settings.physicsMaxChars,max_fields:this.bench.settings.physicsMaxFields});
    if(DATA.ppb&&DATA.ppb.document) {
      this.ppb.replace(DATA.ppb.document);
      for(const [id,value] of Object.entries(DATA.ppb.edits||{}))this.ppb.set(id,value);
    }
    this.binding=editorClone((DATA.ppb||{}).binding||null);
  }
  record(method,args) {
    const last=this.actions[this.actions.length-1];
    if(method==="collider_set"&&last&&last.method===method&&last.args[0]===args[0]&&last.args[1]===args[1]) {
      Object.assign(last.args[2],editorClone(args[2]));return;
    }
    if(this.actions.length>=this.bench.settings.workspaceActionLimit) editorError("actions");
    this.actions.push({method,args:editorClone(args)});
  }
  capsule(bone,index,editable=true) {
    const cap=this.state.capsules.find((c)=>c.bone===bone&&c.index===index);
    if(!Number.isInteger(index)||!cap||(editable&&!cap.editable)) editorError("capsule");return cap;
  }
  rebuild() {
    if(this.bench._colliderMeshes===null)return;
    for(const body of this.state.bodies) {
      const current=this.state.capsules.filter((cap)=>cap.bone===body.bone),original=this.original.capsules.filter((cap)=>cap.bone===body.bone);
      const geometry=(caps)=>caps.map((cap)=>[cap.p1,cap.p2,cap.radius]);
      body.changed=JSON.stringify(geometry(current))!==JSON.stringify(geometry(original));body.count=current.length;
      for(const cap of current) {cap.changed=body.changed;cap.length=rnd(norm(cap.p2.map((x,i)=>x-cap.p1[i])),3);cap.total=rnd(norm(cap.p2.map((x,i)=>x-cap.p1[i]))+2*cap.radius,3);}
    }
    this.state.changed=this.state.bodies.filter((body)=>body.changed).map((body)=>body.bone).sort();
    const bodies=new Set(this.state.bodies.filter((b)=>b.editable).map((b)=>b.bone));
    const untouched=this.bench._colliderMeshes.filter((mesh)=>!bodies.has(mesh.bone));
    this.bench._colliderMeshes=untouched.concat(this.state.capsules.filter((cap)=>cap.editable).map((cap)=>editorCapsuleMesh(cap,this.state.bodyMatrices[cap.bone],this.bench.settings.colliderSegments)));
  }
  recipe() {
    const physics=this.physics.state(),actions=[];
    if(this.state.available) {
      actions.push({method:"collider_reset",args:[]});
      actions.push(...editorClone(this.actions));
    }
    if(physics.document) {
      actions.push({method:"physics_replace",args:[physics.document]});
      for(const [id,value] of Object.entries(physics.edits||{})) actions.push({method:"physics_set",args:[id,value]});
    }
    const ppb=this.ppb.state();
    if(ppb.document) {
      actions.push({method:"ppb_replace",args:[ppb.document]});
      for(const [id,value] of Object.entries(ppb.edits||{}))actions.push({method:"ppb_set",args:[id,value]});
    }
    if(this.binding)actions.push({method:"ppb_link",args:[this.binding.capsule,this.binding.bone,this.binding.index]});
    if(this.state.available){const selected=this.state.selected;actions.push({method:"collider_select",args:selected?[selected.bone,selected.index]:[null]});}
    actions.push({method:"workspace_mode",args:[this.mode]},{method:"workspace_tab",args:[this.tabs[this.mode]||WORKSPACE_TABS[this.mode][0]]});
    return {format:"morphbench-workspace",version:1,source:DATA.source||null,actions};
  }
}
const editorOwner = (bench) => bench._editor||(bench._editor=new EditorState(bench));
Object.assign(BenchMirror.prototype,{
  workspace_state() {const owner=editorOwner(this);return {mode:owner.mode,tab:owner.tabs[owner.mode]||WORKSPACE_TABS[owner.mode][0],tabs:WORKSPACE_TABS[owner.mode].slice()};},
  workspace_mode(mode="morphs") {
    mode=mode==="mesh"?"morphs":mode;if(!Object.hasOwn(WORKSPACE_TABS,mode)) editorError("mode");
    editorOwner(this).mode=mode;this.slots_mode(mode==="slots"?"slots":"mesh");
    this.show_colliders(mode==="colliders",false);return this.workspace_state();
  },
  workspace_tab(tab) {const owner=editorOwner(this);if(!WORKSPACE_TABS[owner.mode].includes(tab)) editorError("tab");owner.tabs[owner.mode]=tab;return this.workspace_state();},
  collider_edit_state() {return editorClone(editorOwner(this).state);},
  collider_select(bone,index=0) {const owner=editorOwner(this);if(bone===null)owner.state.selected=null;else{owner.capsule(bone,index,false);owner.state.selected={bone,index};}return this.collider_edit_state();},
  collider_set(bone,index,changes) {
    const owner=editorOwner(this),cap=owner.capsule(bone,index);
    if(!changes||typeof changes!=="object"||Object.keys(changes).some((key)=>!["p1","p2","radius"].includes(key))) editorError("changes");
    const next=editorClone(cap);
    for(const key of ["p1","p2"]) if(Object.hasOwn(changes,key)) next[key]=editorVector(changes[key]);
    if(Object.hasOwn(changes,"radius")) {if(typeof changes.radius!=="number"||!Number.isFinite(changes.radius)||!Number.isFinite(Math.fround(changes.radius))||changes.radius<0) editorError("radius");next.radius=changes.radius;}
    const ppb=this._ppb_collider_source(bone,index,next,changes);
    owner.record("collider_set",[bone,index,changes]);Object.assign(cap,next);if(ppb)owner.ppb=ppb;owner.state.selected={bone,index};owner.rebuild();return editorClone(cap);
  },
  collider_translate(bone,index,delta) {
    const owner=editorOwner(this),cap=owner.capsule(bone,index),vec=editorVector(delta);
    const p1=cap.p1.map((x,i)=>x+vec[i]),p2=cap.p2.map((x,i)=>x+vec[i]);
    if(this._ppb_target(bone,index)){delta.forEach((value)=>this._ppb_value(value));p1.concat(p2).forEach((value)=>this._ppb_value(value));}
    return this.collider_set(bone,index,{p1,p2});
  },
  collider_add(bone,p1,p2,radius) {
    const owner=editorOwner(this),body=owner.state.bodies.find((b)=>b.bone===bone&&b.editable);
    if(!body) editorError("bone");p1=editorVector(p1);p2=editorVector(p2);
    if(typeof radius!=="number"||!Number.isFinite(radius)||!Number.isFinite(Math.fround(radius))||radius<0) editorError("radius");
    const index=Math.max(-1,...owner.state.capsules.filter((c)=>c.bone===bone).map((c)=>c.index))+1;
    owner.record("collider_add",[bone,p1,p2,radius]);
    const cap={bone,index,p1,p2,radius,kind:body.kind,shapeKind:body.shapeKind,editable:true,changed:true};owner.state.capsules.push(cap);owner.state.selected={bone,index};owner.binding=null;owner.rebuild();return editorClone(cap);
  },
  collider_remove(bone,index=0) {
    const owner=editorOwner(this);owner.capsule(bone,index);
    const caps=owner.state.capsules.filter((c)=>c.bone===bone);if(caps.length<=1) editorError("last capsule");
    owner.record("collider_remove",[bone,index]);owner.state.capsules=owner.state.capsules.filter((c)=>!(c.bone===bone&&c.index===index));
    owner.state.capsules.filter((c)=>c.bone===bone).forEach((c,i)=>c.index=i);owner.state.selected={bone,index:0};owner.binding=null;owner.rebuild();return this.collider_edit_state();
  },
  collider_reset() {const owner=editorOwner(this);if(!owner.state.available)editorError("skeleton");owner.state=editorClone(owner.original);owner.actions=[];owner.binding=null;owner.rebuild();return this.collider_edit_state();},
  physics_replace(document) {if(!document||!["fsmp","cbpc"].includes(document.kind))editorError("document");return editorOwner(this).physics.replace(document);},
  physics_set(id,value) {return editorOwner(this).physics.set(id,value);},
  physics_state() {return editorOwner(this).physics.state();},
  physics_export() {return editorOwner(this).physics.export_text();},
  physics_envelopes() {return editorOwner(this).physics.envelopes(this.slots_anchors());},
  ppb_replace(document) {
    if(!document||document.kind!=="ppb")editorError("document");
    const candidate=new PhysicsWorkspaceMirror(null,DATA.physicsTexts||{},{max_chars:this.settings.physicsMaxChars,max_fields:this.settings.physicsMaxFields});
    candidate.replace(document);
    const normalized=candidate.state(),fields=new Map(normalized.fields.map((field)=>[field.id,field])),groups=new Set(normalized.groups.map((group)=>group.id)),seen=new Set();
    for(const field of normalized.fields)this._ppb_value(field.value);
    if(!Array.isArray(normalized.capsules))editorError("PPB capsules");
    for(const cap of normalized.capsules) {
      if(!cap||typeof cap!=="object"||typeof cap.id!=="string"||seen.has(cap.id)||!groups.has(cap.id)||typeof cap.geometry_supported!=="boolean"||!cap.fields||Array.isArray(cap.fields)||typeof cap.fields!=="object"||!cap.geometry||Array.isArray(cap.geometry)||typeof cap.geometry!=="object")editorError("PPB capsule");
      seen.add(cap.id);
      const bindings=Object.values(cap.fields),geometry=cap.geometry;
      if(bindings.some((id)=>typeof id!=="string"||!fields.has(id)||fields.get(id).group!==cap.id||fields.get(id).active!==true))editorError("PPB binding");
      if(["p1","p2"].some((key)=>!Array.isArray(geometry[key])||geometry[key].length!==3))editorError("PPB geometry");
      if(cap.geometry_supported) {
        const ids=geometry.p1.concat(geometry.p2,[geometry.radius,geometry.enabled]);
        if(new Set(ids.filter((id)=>typeof id==="string")).size!==8||ids.some((id)=>typeof id!=="string"||!bindings.includes(id)))editorError("PPB binding");
      }
    }
    const owner=editorOwner(this);owner.ppb=candidate;owner.binding=null;return this.ppb_state();
  },
  _ppb_value(value) {if(typeof value!=="number"||!Number.isFinite(value)||Math.abs(value)>3.4028234663852886e38||(value!==0&&Math.fround(value)===0))editorOwner(this).ppb._fail("ppbw.float");return value;},
  ppb_set(id,value) {
    const owner=editorOwner(this),candidate=editorPPBCopy(owner);candidate.set(id,this._ppb_value(value));
    this._ppb_commit_source(candidate,[id]);return this.ppb_state();
  },
  _ppb_commit_source(candidate,changedIds) {
    const owner=editorOwner(this);
    if(owner.binding){
      const {ids}=this._ppb_geometry(owner.binding.capsule);
      if(changedIds.some((id)=>ids.includes(id))){
        const {values}=this._ppb_geometry(owner.binding.capsule,candidate.state()),{bone,index}=owner.binding,cap=owner.capsule(bone,index);
        const changes={p1:editorVector(values.slice(0,3)),p2:editorVector(values.slice(3,6)),radius:values[6]};
        owner.record("collider_set",[bone,index,changes]);Object.assign(cap,changes);owner.state.selected={bone,index};owner.rebuild();
      }
    }
    owner.ppb=candidate;
  },
  ppb_state() {
    const owner=editorOwner(this),state=owner.ppb.state(),fields=new Map(state.fields.map((field)=>[field.id,field.value]));
    state.binding=editorClone(owner.binding);
    for(const cap of state.capsules||[]) {
      if(!cap||typeof cap!=="object")continue;
      const geometry=cap.geometry,ids=geometry&&Array.isArray(geometry.p1)&&Array.isArray(geometry.p2)?geometry.p1.concat(geometry.p2,[geometry.radius]):[];
      cap.transfer_supported=cap.geometry_supported===true&&ids.length===7&&ids.every((id)=>typeof id==="string"&&fields.has(id))&&fields.get(ids[6])>0;
    }
    return state;
  },
  ppb_export() {return editorOwner(this).ppb.export_text();},
  _ppb_geometry(capsuleId,state=this.ppb_state()) {
    const matches=(Array.isArray(state.capsules)?state.capsules:[]).filter((item)=>item&&item.id===capsuleId);
    if(matches.length!==1)editorOwner(this).ppb._fail("ppbw.transfer");
    const capsule=matches[0],geometry=capsule.geometry;
    if(capsule.geometry_supported!==true||capsule.frame!=="body-local"||!geometry||!Array.isArray(geometry.p1)||geometry.p1.length!==3||!Array.isArray(geometry.p2)||geometry.p2.length!==3)editorOwner(this).ppb._fail("ppbw.transfer");
    const ids=geometry.p1.concat(geometry.p2,[geometry.radius]),fields=new Map(state.fields.map((field)=>[field.id,field]));
    if(new Set(ids).size!==7||ids.some((id)=>typeof id!=="string"||!fields.has(id)||fields.get(id).editable===false||fields.get(id).active!==true))editorOwner(this).ppb._fail("ppbw.transfer");
    const values=ids.map((id)=>this._ppb_value(fields.get(id).value));if(values[6]<=0)editorOwner(this).ppb._fail("ppbw.transfer");
    return {ids,values};
  },
  ppb_link(capsuleId,bone,index) {
    const {values}=this._ppb_geometry(capsuleId),owner=editorOwner(this),cap=owner.capsule(bone,index),changes={p1:editorVector(values.slice(0,3)),p2:editorVector(values.slice(3,6)),radius:values[6]};
    owner.record("collider_set",[bone,index,changes]);Object.assign(cap,changes);owner.state.selected={bone,index};owner.binding={capsule:capsuleId,bone,index};owner.rebuild();return this.ppb_state();
  },
  ppb_unlink() {editorOwner(this).binding=null;return this.ppb_state();},
  _ppb_target(bone,index) {const binding=editorOwner(this).binding;return !!binding&&binding.bone===bone&&binding.index===index;},
  _ppb_collider_source(bone,index,next,changes) {
    if(!this._ppb_target(bone,index))return null;
    const owner=editorOwner(this),{ids}=this._ppb_geometry(owner.binding.capsule),candidate=editorPPBCopy(owner),values=next.p1.concat(next.p2,[next.radius]).map((value)=>this._ppb_value(value));
    if(values[6]<=0)owner.ppb._fail("ppbw.transfer");
    for(const [key,indices] of [["p1",[0,1,2]],["p2",[3,4,5]],["radius",[6]]])if(Object.hasOwn(changes,key)){
      (key==="radius"?[changes[key]]:changes[key]).forEach((value)=>this._ppb_value(value));
      indices.forEach((i)=>candidate.set(ids[i],values[i]));
    }
    return candidate;
  },
  ppb_to_collider(capsuleId,bone,index) {const {values}=this._ppb_geometry(capsuleId);return this.collider_set(bone,index,{p1:values.slice(0,3),p2:values.slice(3,6),radius:values[6]});},
  ppb_from_collider(capsuleId,bone,index) {
    const {ids}=this._ppb_geometry(capsuleId),owner=editorOwner(this),cap=owner.capsule(bone,index,false),values=cap.p1.concat(cap.p2,[cap.radius]).map((value)=>this._ppb_value(value));
    if(cap.radius<=0)editorError("PPB radius");
    const candidate=editorPPBCopy(owner);ids.forEach((id,i)=>candidate.set(id,values[i]));
    this._ppb_commit_source(candidate,ids);
    return this.ppb_state();
  },
  workspace_recipe() {return editorOwner(this).recipe();},
  workspace_replay(actions) {
    const allowed={workspace_mode:[1,1],workspace_tab:[1,1],physics_replace:[1,1],physics_set:[2,2],ppb_replace:[1,1],ppb_set:[2,2],ppb_link:[3,3],ppb_unlink:[0,0],ppb_to_collider:[3,3],ppb_from_collider:[3,3],collider_select:[1,2],collider_set:[3,3],collider_translate:[3,3],collider_add:[4,4],collider_remove:[1,2],collider_reset:[0,0]};
    if(!Array.isArray(actions)||actions.length>this.settings.workspaceActionLimit) editorError("actions");
    for(const action of actions) {
      if(!action||Object.keys(action).sort().join()!=="args,method"||!Object.hasOwn(allowed,action.method)||!Array.isArray(action.args)) editorError("action");
      const range=allowed[action.method];if(action.args.length<range[0]||action.args.length>range[1]) editorError("arguments");
    }
    const owner=editorOwner(this),before={state:editorClone(owner.state),actions:editorClone(owner.actions),mode:owner.mode,tabs:editorClone(owner.tabs),physics:owner.physics.state(),ppb:owner.ppb.state(),binding:editorClone(owner.binding),placementMode:this.placements.mode,colliders:this.view.colliders,bumper:this.view.bumper};
    try {for(const action of actions) this[action.method](...action.args);}
    catch(error) {
      Object.assign(owner,{state:before.state,actions:before.actions,mode:before.mode,tabs:before.tabs,binding:before.binding});
      const limits={max_chars:this.settings.physicsMaxChars,max_fields:this.settings.physicsMaxFields};
      owner.physics=new PhysicsWorkspaceMirror(null,DATA.physicsTexts||{},limits);if(before.physics.document) {owner.physics.replace(before.physics.document);for(const [id,value] of Object.entries(before.physics.edits||{})) owner.physics.set(id,value);}
      owner.ppb=new PhysicsWorkspaceMirror(null,DATA.physicsTexts||{},limits);if(before.ppb.document){owner.ppb.replace(before.ppb.document);for(const [id,value] of Object.entries(before.ppb.edits||{}))owner.ppb.set(id,value);}
      this.slots_mode(before.placementMode);this.view.colliders=before.colliders;this.view.bumper=before.bumper;owner.rebuild();throw error;
    }
    return this.workspace_state();
  }
});
