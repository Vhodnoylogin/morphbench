"use strict";
// Numeric owner for normalized source spans; raw provider formats are parsed by the server.
// Static configured geometry only. Keep the generic math in sync with PhysicsWorkspace.
class PhysicsWorkspaceMirror {
  constructor(document=null,texts={},limits={}) {
    this._document=null;this._edits=Object.create(null);this._source=[];this._texts=texts;
    this._maxChars=limits.max_chars===undefined?2000000:limits.max_chars;this._maxFields=limits.max_fields===undefined?20000:limits.max_fields;
    if(!Number.isInteger(this._maxChars)||!Number.isInteger(this._maxFields)||this._maxChars<=0||this._maxFields<=0)this._fail("physicsw.size");
    if(document!==null)this.replace(document);
  }
  _clone(value) {return JSON.parse(JSON.stringify(value));}
  _message(key,values={}) {
    return String(this._texts[key]||key).replace(/%\((\w+)\)[sdfg]/g,(match,name)=>Object.prototype.hasOwnProperty.call(values,name)?String(values[name]):match);
  }
  _fail(key,values={}) {throw new Error(this._message(key,values));}
  _finite(value) {
    if(typeof value!=="number"||!Number.isFinite(value))this._fail("physicsw.finite");
    return value;
  }
  replace(document) {
    const plain=(value)=>value===null||typeof value==="string"||typeof value==="boolean"||
      (typeof value==="number"&&Number.isFinite(value))||(Array.isArray(value)&&value.every(plain))||
      (value&&Object.getPrototypeOf(value)===Object.prototype&&Object.values(value).every(plain));
    if(!document||!plain(document)||typeof document.text!=="string"||!["fsmp","cbpc"].includes(document.kind)||
      !Array.isArray(document.fields)||!["records","groups","warnings"].every((key)=>document[key]===undefined||Array.isArray(document[key])))this._fail("physicsw.document");
    const candidate=this._clone(document),source=Array.from(candidate.text),ids=new Set(),spans=[];
    if(source.length>this._maxChars||candidate.fields.length>this._maxFields)this._fail("physicsw.size");
    for(const field of candidate.fields) {
      if(!field||typeof field!=="object"||typeof field.id!=="string"||!field.id||ids.has(field.id)||
        !Number.isInteger(field.start)||!Number.isInteger(field.end)||field.start<0||field.start>=field.end||field.end>source.length||
        !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(source.slice(field.start,field.end).join("")))this._fail("physicsw.document");
      this._finite(field.value);
      if(field.value!==Number(source.slice(field.start,field.end).join("")))this._fail("physicsw.document");
      ids.add(field.id);spans.push([field.start,field.end]);
    }
    spans.sort((a,b)=>a[0]-b[0]);
    if(spans.some((span,index)=>index>0&&spans[index-1][1]>span[0]))this._fail("physicsw.document");
    const groupIds=new Set(),recordIds=new Set();
    for(const group of candidate.groups||[]) {
      if(!group||typeof group!=="object"||typeof group.id!=="string"||groupIds.has(group.id))this._fail("physicsw.document");
      groupIds.add(group.id);
    }
    for(const record of candidate.records||[]) {
      if(!record||typeof record!=="object"||!["raw","limits"].includes(record.type)||typeof record.id!=="string"||recordIds.has(record.id))this._fail("physicsw.document");
      recordIds.add(record.id);
      if(record.type==="limits"&&(typeof record.range_supported!=="boolean"||typeof record.frame_supported!=="boolean"||
        !record.frame||Array.isArray(record.frame)||typeof record.frame!=="object"||
        ["linear","angular"].some((key)=>!record[key]||Array.isArray(record[key])||typeof record[key]!=="object")))this._fail("physicsw.document");
    }
    if((candidate.warnings||[]).some((row)=>!row||Array.isArray(row)||typeof row!=="object"))this._fail("physicsw.document");
    candidate.groups=candidate.groups||[];candidate.records=candidate.records||[];candidate.warnings=candidate.warnings||[];
    this._document=candidate;this._source=source;this._edits=Object.create(null);return this.state();
  }
  set(fieldId,value) {
    this._finite(value);
    if(!this._document)this._fail("physicsw.empty");
    const field=this._document.fields.find((row)=>row.id===fieldId);
    if(!field)this._fail("physicsw.field",{field:fieldId});
    if(field.editable===false)this._fail("physicsw.readonly",{field:fieldId});
    if(value===field.value)delete this._edits[fieldId];else this._edits[fieldId]=value;
    return this.state();
  }
  state() {
    if(!this._document)return {kind:null,text:"",fields:[],groups:[],records:[],warnings:[],dirty:false,document:null,edits:{}};
    const result=this._clone(this._document);
    for(const field of result.fields) {
      field.changed=Object.prototype.hasOwnProperty.call(this._edits,field.id);
      if(field.changed)field.value=this._edits[field.id];
    }
    result.dirty=Object.keys(this._edits).length>0;result.document=this._clone(this._document);result.edits={...this._edits};return result;
  }
  export_text() {
    if(!this._document)this._fail("physicsw.empty");
    const edits=this._document.fields.filter((field)=>Object.prototype.hasOwnProperty.call(this._edits,field.id)).sort((a,b)=>b.start-a.start);
    let source=this._source.slice();
    for(const field of edits) {
      const value=this._edits[field.id],replacement=Object.is(value,-0)?"-0":String(value);
      source=source.slice(0,field.start).concat(Array.from(replacement),source.slice(field.end));
    }
    return source.join("");
  }
  _matrix(frame) {
    if(frame&&!Array.isArray(frame))frame=frame.matrix;
    if(!Array.isArray(frame)||frame.length!==4||frame.some((row)=>!Array.isArray(row)||row.length!==4||row.some((value)=>typeof value!=="number"||!Number.isFinite(value))))return null;
    if(frame[3].some((value,index)=>value!==[0,0,0,1][index]))return null;
    const columns=[0,1,2].map((col)=>[0,1,2].map((row)=>frame[row][col]));
    const lengths=columns.map((col)=>Math.sqrt(col.reduce((total,value)=>total+value*value,0))),epsilon=1e-6;
    if(lengths.some((size)=>!Number.isFinite(size)||size<=0)||Math.max(...lengths)-Math.min(...lengths)>epsilon*Math.max(...lengths))return null;
    for(let a=0;a<3;a++)for(let b=a+1;b<3;b++)if(Math.abs(columns[a].reduce((total,value,index)=>total+value*columns[b][index],0))>epsilon*lengths[a]*lengths[b])return null;
    const m=frame,det=m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])-m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])+m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]);
    return det>0?frame:null;
  }
  _rotate(quaternion) {
    const size=Math.sqrt(quaternion.reduce((total,value)=>total+value*value,0));
    if(!Number.isFinite(size)||size===0)return null;
    const [x,y,z,w]=quaternion.map((value)=>value/size);
    return [[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
      [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
      [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]];
  }
  envelopes(frames={},options={}) {
    const radius=this._finite(options.angular_radius===undefined?1:options.angular_radius),segments=options.angular_segments===undefined?24:options.angular_segments;
    if(radius<=0||!Number.isInteger(segments)||segments<1||segments>256)this._fail("physicsw.geometry");
    const state=this.state(),values=Object.fromEntries(state.fields.map((field)=>[field.id,field.value]));
    const result={mode:"configured_limits",records:[],lines:[],warnings:this._clone(state.warnings)};
    const vector=(items,size)=>{
      if(!Array.isArray(items)||items.length!==size)return null;
      const out=[];
      for(const item of items) {
        if(typeof item==="string"&&Object.prototype.hasOwnProperty.call(values,item))out.push(values[item]);
        else if(typeof item==="number"&&Number.isFinite(item))out.push(item);else return null;
      }
      return out;
    };
    const warning=(code,key,record,args={})=>result.warnings.push({code,message:this._message(key,args),record:record.id});
    for(const record of state.records) {
      const row=this._clone(record);row.linear=null;row.angular=null;result.records.push(row);
      if(record.type!=="limits"||!record.range_supported)continue;
      for(const kind of ["linear","angular"]) {
        const bounds=record[kind]||{},lower=vector(bounds.lower,3),upper=vector(bounds.upper,3);
        if(!lower||!upper){warning("missing_limits","physicsw.missingLimits",record,{kind});continue;}
        row[kind]=["x","y","z"].map((axis,index)=>({axis,lower:lower[index],upper:upper[index],status:lower[index]>upper[index]?"unconstrained":lower[index]===upper[index]?"locked":"limited"}));
      }
      const frame=record.frame||{},node=this._matrix(frames&&frames[frame.body]),origin=vector(frame.origin,3),basis=vector(frame.basis,4),rotation=basis?this._rotate(basis):null;
      if(!record.frame_supported||!node||!origin||!rotation){warning("missing_frame","physicsw.missingFrame",record,{name:frame.body||""});continue;}
      const axes=[0,1,2].map((rowno)=>[0,1,2].map((col)=>[0,1,2].reduce((total,k)=>total+node[rowno][k]*rotation[k][col],0)));
      const centre=[0,1,2].map((rowno)=>node[rowno][3]+[0,1,2].reduce((total,k)=>total+node[rowno][k]*origin[k],0));
      if(axes.flat().concat(centre).some((value)=>!Number.isFinite(value))){warning("missing_frame","physicsw.missingFrame",record,{name:frame.body||""});continue;}
      const world=(point)=>[0,1,2].map((rowno)=>centre[rowno]+[0,1,2].reduce((total,k)=>total+axes[rowno][k]*point[k],0));
      row.world_origin=centre;row.world_axes=[0,1,2].map((col)=>[0,1,2].map((rowno)=>axes[rowno][col]));
      const line=(kind,axis,a,b)=>{const points=[world(a),world(b)];if(points.flat().every(Number.isFinite))result.lines.push({kind,record:record.id,axis,a:points[0],b:points[1]});};
      if(row.linear) {
        row.linear.forEach((limit,index)=>{if(limit.status==="unconstrained")return;const a=[0,0,0],b=[0,0,0];a[index]=limit.lower;b[index]=limit.upper;line("linear_axis",["x","y","z"][index],a,b);});
        if(row.linear.every((limit)=>limit.status!=="unconstrained")) {
          const corners=[];for(const x of [row.linear[0].lower,row.linear[0].upper])for(const y of [row.linear[1].lower,row.linear[1].upper])for(const z of [row.linear[2].lower,row.linear[2].upper])corners.push([x,y,z]);
          corners.forEach((a,index)=>{for(let axis=0;axis<3;axis++){const other=index^(1<<(2-axis));if(index<other)line("linear_box",["x","y","z"][axis],a,corners[other]);}});
        }
      }
      if(row.angular) {
        row.angular_glyph_radius=radius;
        row.angular.forEach((limit,index)=>{
          if(limit.status==="unconstrained")return;
          if(limit.upper-limit.lower>2*Math.PI){warning("angular_revolution","physicsw.angularRevolution",record);return;}
          const points=[];
          for(let step=0;step<=segments;step++){const angle=limit.lower+(limit.upper-limit.lower)*step/segments,point=[0,0,0];point[(index+1)%3]=radius*Math.cos(angle);point[(index+2)%3]=radius*Math.sin(angle);points.push(point);}
          for(let step=0;step<segments;step++)line("angular_glyph",["x","y","z"][index],points[step],points[step+1]);
        });
      }
    }
    return result;
  }
}
