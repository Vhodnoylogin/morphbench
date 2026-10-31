"use strict";
// Public Body Slots schema-v1 format adapter. No runtime or inventory operations.
const BodySlotsFormat = {
  rig: "skyrimvr-humanoid-v1", units: "skyrim-engine-unit", axes: "right-handed-z-up",
  hands: {left:1,right:2}, contents: {weapon:1,shield:2,torch:4,potion:8,food:16,tool:32,other:64},
  limits: {count:256,coordinate:1000000,rotationTolerance:0.0001},
  value(object,key,fallback) { return Object.prototype.hasOwnProperty.call(object,key)?object[key]:fallback; },
  fail(field) { throw new Error(say(T.slotsInvalid,{field:field})); },
  exact(value, keys, field) {
    if (!value || Array.isArray(value) || typeof value!=="object" || Object.keys(value).sort().join()!==keys.slice().sort().join()) this.fail(field);
  },
  text(value,size,field,identity) {
    if(typeof value!=="string"||!value.length||value.length>=size||/[^\x20-\x7e]/.test(value)||(identity&&!/^[A-Za-z0-9_./-]+$/.test(value))) this.fail(field);
    return value;
  },
  mask(values,choices,field) {
    if(!Array.isArray(values)||!values.length||new Set(values).size!==values.length||values.some((name)=>!Object.prototype.hasOwnProperty.call(choices,name))) this.fail(field);
    return values.reduce((total,name)=>total+choices[name],0);
  },
  number(value,field) {
    if(typeof value!=="number"||!Number.isFinite(value)||Math.abs(value)>1000000) this.fail(field);
    return Math.fround(value);
  },
  vector(value,size,field) {
    if(!Array.isArray(value)||value.length!==size) this.fail(field);
    return value.map((x)=>this.number(x,field));
  },
  normalize(project) {
    this.exact(project,["schemaVersion","provider","referenceRig","units","axes","slots"],"project");
    if(project.schemaVersion!==1||project.referenceRig!==this.rig||project.units!==this.units||project.axes!==this.axes) this.fail("schemaVersion/referenceRig/units/axes");
    this.text(project.provider,64,"provider",true);
    if(!Array.isArray(project.slots)||project.slots.length>256) this.fail("slots");
    const rows=project.slots.map((value)=>{
      this.exact(value,["key","anchor","kind","enabled","position","rotation","accessRegion","hands","contents","scaleMode"],"slot");
      this.text(value.key,64,"key",true); this.text(value.anchor,96,"anchor",false); this.text(value.kind,32,"kind",true);
      if(typeof value.enabled!=="boolean"||value.scaleMode!=="anchor") this.fail("enabled/scaleMode");
      this.mask(value.hands,this.hands,"hands"); this.mask(value.contents,this.contents,"contents");
      this.exact(value.accessRegion,["shape","center","radius"],"accessRegion");
      if(value.accessRegion.shape!=="sphere"||!Array.isArray(value.rotation)||value.rotation.length!==3) this.fail("sphere/rotation");
      return {name:value.key,anchor:value.anchor,enabled:value.enabled,position:this.vector(value.position,3,"position"),
        rotation:value.rotation.map((row)=>this.vector(row,3,"rotation")),center:this.vector(value.accessRegion.center,3,"center"),
        radius:this.number(value.accessRegion.radius,"radius"),attributes:{kind:value.kind,hands:value.hands,contents:value.contents}};
    });
    return [{namespace:project.provider,reference:{rig:this.rig,units:this.units,axes:this.axes}},rows];
  },
  schema(project) {
    const metadata=project.metadata,reference=this.value(metadata,"reference",{});
    if(!reference||typeof reference!=="object"||Array.isArray(reference)) this.fail("reference");
    return {schemaVersion:1,provider:this.value(metadata,"namespace",""),referenceRig:this.value(reference,"rig",this.rig),units:this.value(reference,"units",this.units),axes:this.value(reference,"axes",this.axes),
      slots:project.placements.map((row)=>({key:row.name,anchor:row.anchor,kind:this.value(row.attributes,"kind","holster"),enabled:row.enabled,
        position:row.position,rotation:row.rotation,accessRegion:{shape:"sphere",center:row.center,radius:row.radius},
        hands:this.value(row.attributes,"hands",Object.keys(this.hands)),contents:this.value(row.attributes,"contents",Object.keys(this.contents)),scaleMode:"anchor"}))};
  },
  preset(snapshot) {
    let template=null;
    try {
      this.text(snapshot.metadata.namespace,64,"provider",true);this.text(snapshot.placement,64,"key",true);
      template={provider:snapshot.metadata.namespace,key:snapshot.placement};
    } catch(error) { /* Unfinished/generic author identities need no runtime binding. */ }
    return {format:"morphbench-placement-preset",version:1,binding:"unbound",template:template,changes:placementClone(snapshot.changes)};
  },
  encode(project,bench) {
    const schema=this.schema(project),[metadata,rows]=this.normalize(schema);
    const normalized=bench.slots_validate(metadata,rows,this.limits),ordered=normalized.placements;
    const bytes=new Uint8Array(112+408*ordered.length),view=new DataView(bytes.buffer);
    const text=(offset,value,size)=>{this.text(value,size,"text",false);for(let i=0;i<value.length;i++) bytes[offset+i]=value.charCodeAt(i);};
    [66,83,76,79,84,83,13,10].forEach((x,i)=>bytes[i]=x);
    [1,112,408,ordered.length,408*ordered.length,0].forEach((x,i)=>view.setUint32(8+i*4,x,true));
    text(32,schema.provider,64);
    ordered.forEach((row,index)=>{
      const offset=112+index*408,attributes=row.attributes;
      view.setUint32(offset,408,true);view.setUint32(offset+4,row.enabled?1:0,true);
      text(offset+8,schema.provider,64);text(offset+72,row.name,64);text(offset+136,row.anchor,96);text(offset+232,this.rig,64);text(offset+296,attributes.kind,32);
      const values=row.position.concat(row.rotation.flat(),[row.radius],row.center);
      values.forEach((x,i)=>view.setFloat32(offset+328+i*4,x,true));
      view.setUint32(offset+392,this.mask(attributes.hands,this.hands,"hands"),true);
      view.setUint32(offset+396,this.mask(attributes.contents,this.contents,"contents"),true);
    });
    return bytes;
  }
};
