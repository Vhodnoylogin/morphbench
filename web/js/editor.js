"use strict";
// Numerical browser facade for mode and body-local capsule edits. Text formats
// are recognized by the server adapter; this owner keeps normalized documents.
const WORKSPACE_TABS = {morphs:["sliders","display"],colliders:["edit","display"],physics:["configuration","ranges"],slots:["author","display"]};
const editorClone = (value) => JSON.parse(JSON.stringify(value));
const editorError = (field) => { throw new Error(say(T["edInvalid"] || T.slotsInvalid,{field})); };
const editorVector = (value) => {
  if(!Array.isArray(value)||value.length!==3||value.some((x)=>typeof x!=="number"||!Number.isFinite(x)||!Number.isFinite(Math.fround(x)))) editorError("vector");
  return value.map(Math.fround);
};
const editorPoint = (matrix,point) => matrix.slice(0,3).map((row)=>row[0]*point[0]+row[1]*point[1]+row[2]*point[2]+row[3]);
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
      const selected=this.state.selected;actions.push({method:"collider_select",args:selected?[selected.bone,selected.index]:[null]});
    }
    if(physics.document) {
      actions.push({method:"physics_replace",args:[physics.document]});
      for(const [id,value] of Object.entries(physics.edits||{})) actions.push({method:"physics_set",args:[id,value]});
    }
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
    owner.record("collider_set",[bone,index,changes]);Object.assign(cap,next);owner.state.selected={bone,index};owner.rebuild();return editorClone(cap);
  },
  collider_translate(bone,index,delta) {
    const owner=editorOwner(this),cap=owner.capsule(bone,index),vec=editorVector(delta);
    const p1=editorVector(cap.p1.map((x,i)=>x+vec[i])),p2=editorVector(cap.p2.map((x,i)=>x+vec[i]));
    owner.record("collider_set",[bone,index,{p1,p2}]);
    cap.p1=p1;cap.p2=p2;owner.state.selected={bone,index};owner.rebuild();return editorClone(cap);
  },
  collider_add(bone,p1,p2,radius) {
    const owner=editorOwner(this),body=owner.state.bodies.find((b)=>b.bone===bone&&b.editable);
    if(!body) editorError("bone");p1=editorVector(p1);p2=editorVector(p2);
    if(typeof radius!=="number"||!Number.isFinite(radius)||!Number.isFinite(Math.fround(radius))||radius<0) editorError("radius");
    const index=Math.max(-1,...owner.state.capsules.filter((c)=>c.bone===bone).map((c)=>c.index))+1;
    owner.record("collider_add",[bone,p1,p2,radius]);
    const cap={bone,index,p1,p2,radius,kind:body.kind,shapeKind:body.shapeKind,editable:true,changed:true};owner.state.capsules.push(cap);owner.state.selected={bone,index};owner.rebuild();return editorClone(cap);
  },
  collider_remove(bone,index=0) {
    const owner=editorOwner(this);owner.capsule(bone,index);
    const caps=owner.state.capsules.filter((c)=>c.bone===bone);if(caps.length<=1) editorError("last capsule");
    owner.record("collider_remove",[bone,index]);owner.state.capsules=owner.state.capsules.filter((c)=>!(c.bone===bone&&c.index===index));
    owner.state.capsules.filter((c)=>c.bone===bone).forEach((c,i)=>c.index=i);owner.state.selected={bone,index:0};owner.rebuild();return this.collider_edit_state();
  },
  collider_reset() {const owner=editorOwner(this);if(!owner.state.available)editorError("skeleton");owner.state=editorClone(owner.original);owner.actions=[];owner.rebuild();return this.collider_edit_state();},
  physics_replace(document) {return editorOwner(this).physics.replace(document);},
  physics_set(id,value) {return editorOwner(this).physics.set(id,value);},
  physics_state() {return editorOwner(this).physics.state();},
  physics_export() {return editorOwner(this).physics.export_text();},
  physics_envelopes() {return editorOwner(this).physics.envelopes(this.slots_anchors());},
  workspace_recipe() {return editorOwner(this).recipe();},
  workspace_replay(actions) {
    const allowed={workspace_mode:[1,1],workspace_tab:[1,1],physics_replace:[1,1],physics_set:[2,2],collider_select:[1,2],collider_set:[3,3],collider_translate:[3,3],collider_add:[4,4],collider_remove:[1,2],collider_reset:[0,0]};
    if(!Array.isArray(actions)||actions.length>this.settings.workspaceActionLimit) editorError("actions");
    for(const action of actions) {
      if(!action||Object.keys(action).sort().join()!=="args,method"||!Object.hasOwn(allowed,action.method)||!Array.isArray(action.args)) editorError("action");
      const range=allowed[action.method];if(action.args.length<range[0]||action.args.length>range[1]) editorError("arguments");
    }
    const owner=editorOwner(this),before={state:editorClone(owner.state),actions:editorClone(owner.actions),mode:owner.mode,tabs:editorClone(owner.tabs),physics:owner.physics.state(),placementMode:this.placements.mode,colliders:this.view.colliders,bumper:this.view.bumper};
    try {for(const action of actions) this[action.method](...action.args);}
    catch(error) {
      Object.assign(owner,{state:before.state,actions:before.actions,mode:before.mode,tabs:before.tabs});
      owner.physics=new PhysicsWorkspaceMirror(null,DATA.physicsTexts||{});if(before.physics.document) {owner.physics.replace(before.physics.document);for(const [id,value] of Object.entries(before.physics.edits||{})) owner.physics.set(id,value);}
      this.slots_mode(before.placementMode);this.view.colliders=before.colliders;this.view.bumper=before.bumper;owner.rebuild();throw error;
    }
    return this.workspace_state();
  }
});
