"use strict";
// Slots mode: widgets call the same named facade actions as mb.py slots recipes.
class SlotsPanel {
  constructor(app, root) {
    this.app=app;this.bench=app.bench;this.initial=placementClone(this.bench.slots_project());this.loadedToken="";
    this.mode=el("select",{on:{change:()=>app.invoke("slots_mode",this.mode.value)}});
    this.mode.appendChild(el("option",{value:"mesh",text:T.slotsMeshMode}));
    this.mode.appendChild(el("option",{value:"slots",text:T.slotsMode}));
    root.appendChild(el("section",null,[el("h2",{text:T.slotsWorkbench}),this.mode]));
    this.section=el("section",{class:"slots-editor"});root.appendChild(this.section);
    this.provider=el("input",{type:"text",class:"wide",on:{change:()=>{
      const metadata=this.bench.slots_project().metadata;metadata.namespace=this.provider.value;app.invoke("slots_metadata",metadata);
    }}});
    this.upload=el("input",{type:"file",accept:".json",on:{change:()=>this.load()}});
    this.list=el("select",{class:"wide",on:{change:()=>app.invoke("slots_select",this.list.value||null)}});
    this.newName=el("input",{type:"text",value:"slot1",class:"wide"});
    this.anchor=el("input",{type:"text",class:"wide",list:"slot-anchors"});
    const anchors=el("datalist",{id:"slot-anchors"});
    for(const name of Object.keys(this.bench.slots_anchors()).sort()) anchors.appendChild(el("option",{value:name}));
    this.target=el("select",{on:{change:()=>{this.loadedToken="";this.refresh();}}});
    this.target.appendChild(el("option",{value:"author",text:T.slotsAuthor}));
    this.target.appendChild(el("option",{value:"effective",text:T.slotsOverride}));
    this.fields={};
    const numeric=(key,count,title)=>{
      const inputs=[];for(let i=0;i<count;i++) inputs.push(el("input",{type:"number",step:this.bench.settings.placementStep,class:"slot-number"}));
      this.fields[key]=inputs;return el("label",{class:"slot-field"},[title,el("div",{class:"row"},inputs)]);
    };
    this.rotation=el("textarea",{rows:3,class:"wide",spellcheck:"false"});
    this.enabled=el("input",{type:"checkbox"});this.kind=el("input",{type:"text",class:"wide"});
    this.policy=el("div");this.handBoxes={};this.contentBoxes={};
    const checkList=(choices,texts,boxes)=>{
      const group=el("div",{class:"row"});for(const name of Object.keys(choices)) {
        const box=el("input",{type:"checkbox"});boxes[name]=box;group.appendChild(el("label",null,[box,texts[name]]));
      }return group;
    };
    this.policy.appendChild(el("label",{class:"slot-field"},[T.slotsKind,this.kind]));
    this.policy.appendChild(el("div",null,[T.slotsHands,checkList(BodySlotsFormat.hands,{left:T.slotsLeft,right:T.slotsRight},this.handBoxes)]));
    this.policy.appendChild(el("div",null,[T.slotsContents,checkList(BodySlotsFormat.contents,
      {weapon:T.slotsWeapon,shield:T.slotsShield,torch:T.slotsTorch,potion:T.slotsPotion,food:T.slotsFood,tool:T.slotsTool,other:T.slotsOther},this.contentBoxes)]));
    this.status=el("pre",{class:"slot-status"});
    this.apply=el("button",{text:T.slotsApply,on:{click:()=>this.edit()}});
    this.remove=el("button",{text:T.slotsRemove,on:{click:()=>app.invoke("slots_remove",this.list.value)}});
    this.clear=el("button",{text:T.slotsClear,on:{click:()=>app.invoke("slots_clear",this.list.value)}});
    this.section.appendChild(el("h2",{text:T.slotsMode}));
    this.section.appendChild(el("div",{class:"muted",text:T.slotsOffline}));
    this.section.appendChild(el("label",{class:"slot-field"},[T.slotsProvider,this.provider]));
    this.section.appendChild(el("div",{class:"row"},[this.upload,el("button",{text:T.slotsNew,on:{click:()=>this.newProject()}})]));
    this.section.appendChild(el("label",{class:"slot-field"},[T.slotsSelect,this.list]));
    this.section.appendChild(el("div",{class:"row"},[this.newName,el("button",{text:T.slotsAdd,on:{click:()=>this.add()}})]));
    this.section.appendChild(el("label",{class:"slot-field"},[T.slotsEditing,this.target]));
    this.section.appendChild(el("label",{class:"slot-field"},[T.slotsAnchor,this.anchor,anchors]));
    this.section.appendChild(numeric("position",3,T.slotsPosition));
    this.section.appendChild(el("label",{class:"slot-field"},[T.slotsRotation,this.rotation]));
    this.section.appendChild(numeric("center",3,T.slotsCenter));
    this.section.appendChild(numeric("radius",1,T.slotsRadius));
    this.section.appendChild(el("label",null,[this.enabled,T.slotsEnabled]));
    this.section.appendChild(this.policy);
    this.section.appendChild(el("div",{class:"row"},[this.apply,this.remove,this.clear]));
    this.section.appendChild(this.status);
    this.section.appendChild(el("div",{class:"muted",text:T.slotsMarkers}));
    this.section.appendChild(el("div",{class:"row"},[
      el("button",{text:T.slotsJSON,on:{click:()=>this.download("json")}}),
      el("button",{text:T.slotsPackage,on:{click:()=>this.download("package")}}),
      el("button",{text:T.slotsRecipe,on:{click:()=>this.download("recipe")}})]));
    this.section.appendChild(el("pre",{text:"python mb.py slots --project author.json --recipe session.json --out edited.json --package edited.bslots"}));
    this.section.appendChild(el("div",{class:"muted",text:T.slotsExports}));
  }
  newProject() {
    this.app.invoke("slots_replace",{namespace:this.provider.value||"morphbench",reference:{rig:BodySlotsFormat.rig,units:BodySlotsFormat.units,axes:BodySlotsFormat.axes}},[]);
  }
  add() {
    try {
      BodySlotsFormat.text(this.newName.value,64,"key",true);
      BodySlotsFormat.text(this.provider.value||"morphbench",64,"provider",true);
    if(!this.bench.slots_project().metadata.namespace) this.app.invoke("slots_metadata",{namespace:this.provider.value||"morphbench",reference:{rig:BodySlotsFormat.rig,units:BodySlotsFormat.units,axes:BodySlotsFormat.axes}});
    this.app.invoke("slots_add",this.newName.value,this.anchor.value||Object.keys(this.bench.slots_anchors()).sort()[0]||"NPC Pelvis [Pelv]",
      {kind:"holster",hands:Object.keys(BodySlotsFormat.hands),contents:Object.keys(BodySlotsFormat.contents)});
    } catch(error) {this.app.panel.error.textContent=String(error.message||error);}
  }
  edit() {
    try {
      const vector=(key)=>this.fields[key].map((input)=>input.value.trim()===""?NaN:Number(input.value));
      const changes={position:vector("position"),rotation:JSON.parse(this.rotation.value),center:vector("center"),radius:vector("radius")[0],enabled:this.enabled.checked};
      if(this.target.value==="author") {
        changes.anchor=this.anchor.value;
        changes.attributes={kind:this.kind.value,hands:Object.keys(this.handBoxes).filter((name)=>this.handBoxes[name].checked),
          contents:Object.keys(this.contentBoxes).filter((name)=>this.contentBoxes[name].checked)};
        const candidate=this.bench.slots_project();candidate.placements=candidate.placements.map((row)=>row.name===this.list.value?Object.assign({},row,changes):row);
        const [metadata,rows]=BodySlotsFormat.normalize(BodySlotsFormat.schema(candidate));
        if(!this.app.invoke("slots_validate",metadata,rows,BodySlotsFormat.limits)) return;
      }
      this.app.invoke(this.target.value==="author"?"slots_set":"slots_customize",this.list.value,changes);
    } catch(error) { this.app.panel.error.textContent=String(error.message||error); }
  }
  async load() {
    try {
      const file=this.upload.files[0];if(!file) return;
      if(file.size>1048576) BodySlotsFormat.fail("file size");
      const project=JSON.parse(await file.text()),[metadata,rows]=BodySlotsFormat.normalize(project);
      if(!this.app.invoke("slots_validate",metadata,rows,BodySlotsFormat.limits)) return;
      this.app.invoke("slots_replace",metadata,rows);
    } catch(error) { this.app.panel.error.textContent=String(error.message||error); }
    this.upload.value="";
  }
  download(kind) {
    try {
      const project=this.app.invoke("slots_project");if(!project) return;
      const schema=BodySlotsFormat.schema(project),[metadata,rows]=BodySlotsFormat.normalize(schema);
      if(!this.app.invoke("slots_validate",metadata,rows,BodySlotsFormat.limits)) return;
      let content=JSON.stringify(schema,null,2)+"\n",extension=".json",type="application/json";
      if(kind==="package") {content=BodySlotsFormat.encode(project,this.bench);extension=".bslots";type="application/octet-stream";}
      if(kind==="recipe") {content=JSON.stringify([{method:"slots_replace",args:[this.initial.metadata,this.initial.placements]}].concat(this.app.slotActions),null,2)+"\n";extension=".session.json";}
      const name=(schema.provider||"placements").replace(/[^A-Za-z0-9_.-]/g,"_");
      const url=URL.createObjectURL(new Blob([content],{type:type})),link=el("a",{href:url,download:name+extension});
      document.body.appendChild(link);link.click();link.remove();URL.revokeObjectURL(url);
    } catch(error) {this.app.panel.error.textContent=String(error.message||error);}
  }
  refresh() {
    const state=this.bench.slots_state();this.mode.value=state.mode;this.section.style.display=state.mode==="slots"?"":"none";
    if(document.activeElement!==this.provider) this.provider.value=state.project.metadata.namespace||"";
    this.list.textContent="";for(const row of state.project.placements) this.list.appendChild(el("option",{value:row.name,text:row.name}));
    this.list.value=state.selected||"";
    const authored=state.project.placements.find((row)=>row.name===state.selected),effective=state.effective.find((row)=>row.name===state.selected);
    const row=this.target.value==="author"?authored:effective;
    this.apply.disabled=this.remove.disabled=this.clear.disabled=!row;
    this.anchor.disabled=this.target.value!=="author";this.policy.style.display=this.target.value==="author"?"":"none";
    const token=JSON.stringify([row,this.target.value]);
    if(row&&token!==this.loadedToken) {
      this.anchor.value=row.anchor;this.rotation.value=JSON.stringify(row.rotation);this.enabled.checked=row.enabled;
      for(const key of ["position","center","radius"]) (key==="radius"?[row.radius]:row[key]).forEach((value,index)=>this.fields[key][index].value=value);
      this.kind.value=row.attributes.kind||"holster";
      for(const [key,box] of Object.entries(this.handBoxes)) box.checked=(row.attributes.hands||Object.keys(BodySlotsFormat.hands)).includes(key);
      for(const [key,box] of Object.entries(this.contentBoxes)) box.checked=(row.attributes.contents||Object.keys(BodySlotsFormat.contents)).includes(key);
    }
    this.loadedToken=token;
    const preview=state.preview.find((item)=>item.name===state.selected);
    this.status.textContent=!preview?T.slotsCreateHint:(!preview.available?T.slotsUnavailable:
      (preview.enabled?T.slotsAvailable:T.slotsDisabled)+"\n"+T.slotsWorldCenter+" "+preview.center.map((x)=>fmt(x)).join(", ")+"\n"+T.slotsWorldRadius+" "+fmt(preview.radius))+
      (preview?"\n"+(preview.customized?T.slotsCustomized:T.slotsDefault):"");
  }
}
