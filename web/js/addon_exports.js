"use strict";

// Opaque frames prepare inert UTF-8 snapshots, never links or filesystem paths.
// The parent owns the only Download control. A real click authorizes the current
// package again; async completion cannot act for a replaced frame or snapshot.
const ADDON_EXPORT_METHODS=Object.freeze(["exports.prepare","exports.cancel"]);

class AddonExportHost {
  constructor(host) {this.host=host;this.record=null;this.element=null;this.url=null;this.epoch=0;}
  limits() {
    const settings=this.host.app.bench.settings,maxBytes=settings.addonExportMaxBytes;
    const authorizeTimeoutMs=settings.addonExportAuthorizeTimeoutMs;
    if(!Number.isSafeInteger(maxBytes)||maxBytes<1||!Number.isSafeInteger(authorizeTimeoutMs)
      ||authorizeTimeoutMs<1||authorizeTimeoutMs>=10000)
      throw this.host.failure("invalidExportConfig",T.addonExportConfig);
    return {maxBytes,authorizeTimeoutMs,formats:["json","xml"],maxFilenameBytes:255,pendingFiles:1};
  }
  current(scope) {
    return scope.epoch===this.epoch&&this.host.frame===scope.frame
      &&this.host.frame?.contentWindow===scope.source&&this.host.active===scope.identifier
      &&this.host.generation===scope.generation;
  }
  requireCurrent(scope) {
    if(!this.current(scope))throw this.host.failure("staleGeneration",T.addonDisabled);
  }
  unicode(text) {
    for(let index=0;index<text.length;index++) {
      const code=text.charCodeAt(index);
      if(code>=0xD800&&code<=0xDBFF) {
        const next=text.charCodeAt(++index);
        if(!(next>=0xDC00&&next<=0xDFFF))return false;
      }else if(code>=0xDC00&&code<=0xDFFF)return false;
    }
    return true;
  }
  validate(params) {
    this.host.params(params,["filename","format","text"],["filename","format","text"]);
    const limits=this.limits(),{filename,format,text}=params;
    if(!limits.formats.includes(format)||typeof filename!=="string"||typeof text!=="string")
      throw this.host.failure("invalidParams");
    // Reject oversized code-unit strings before Unicode/encoding/parser work.
    if(text.length>limits.maxBytes)throw this.host.failure("limitExceeded",T.addonExportLimit);
    if(filename.length>limits.maxFilenameBytes||!this.unicode(filename)||!this.unicode(text))
      throw this.host.failure("invalidParams");
    const suffix="."+format;
    const base=filename.endsWith(suffix)?filename.slice(0,-suffix.length):"";
    // One portable leaf name: no paths, hidden names, controls,
    // bidi formatting, trailing spaces or Windows device names (including COM¹).
    if(!/^[\p{L}\p{M}\p{N}_-](?:[\p{L}\p{M}\p{N} ._-]*[\p{L}\p{M}\p{N}_-])?$/u.test(base)
      ||base.includes("..")||/^(?:con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])$/i.test(base.split(".")[0].trimEnd())
      ||new TextEncoder().encode(filename).length>limits.maxFilenameBytes)
      throw this.host.failure("invalidParams");
    const bytes=new TextEncoder().encode(text).length;
    if(bytes>limits.maxBytes)throw this.host.failure("limitExceeded",T.addonExportLimit);
    try {
      if(format==="json")JSON.parse(text);
      else {
        // No DTD/entity declarations or stylesheet processing, even in an inert
        // parser. The text is exported unchanged; it is never inserted as markup.
        if(/<!\s*(?:DOCTYPE|ENTITY)\b|<\?xml-stylesheet\b/i.test(text))throw Error();
        const parsed=new DOMParser().parseFromString(text,"application/xml");
        // Chromium and Firefox use different namespaces for parsererror nodes.
        if(!parsed.documentElement||parsed.getElementsByTagNameNS("*","parsererror").length)throw Error();
      }
    }catch(error){throw this.host.failure("invalidParams",T.addonExportFormat);}
    return {filename,format,text,bytes};
  }
  clearPending() {
    if(this.record?.cancel)this.record.cancel();
    this.record=null;
    if(this.element)this.element.remove();this.element=null;
  }
  releaseURL() {if(this.url){URL.revokeObjectURL(this.url);this.url=null;}}
  reset() {this.epoch++;this.clearPending();this.releaseURL();}
  request(method,params,scope,receivedAt=Date.now()) {
    const current={...scope,epoch:this.epoch};this.requireCurrent(current);
    if(method==="exports.cancel") {
      this.host.params(params,[]);const cancelled=Boolean(this.record);this.clearPending();return {cancelled};
    }
    if(method!=="exports.prepare")throw this.host.failure("unknownMethod",T.addonMethod);
    if(Date.now()-receivedAt>=this.limits().authorizeTimeoutMs)
      throw this.host.failure("exportTimeout",T.addonExportTimeout);
    const value=this.validate(params);this.requireCurrent(current);
    // Validation is complete before a previous, valid pending file is discarded.
    this.clearPending();const record={...value,scope:current,busy:false};this.record=record;
    const group=el("section",{class:"addon-export-controls","aria-label":T.addonExportTitle});
    const status=el("p",{role:"status",text:say(T.addonExportReady,{filename:record.filename,bytes:record.bytes})});
    const download=el("button",{type:"button",text:T.addonExportDownload,on:{click:event=>this.download(record,event)}});
    const cancel=el("button",{type:"button",text:T.addonExportCancel,on:{click:event=>{
      if(event.isTrusted&&this.record===record)this.clearPending();
    }}});
    record.status=status;record.download=download;
    group.appendChild(status);group.appendChild(download);group.appendChild(cancel);
    this.host.panel.insertBefore(group,this.host.frame);this.element=group;
    return {prepared:true,filename:record.filename,format:record.format,bytes:record.bytes};
  }
  async download(record,event) {
    if(!event?.isTrusted||this.record!==record||record.busy||!this.current(record.scope))return;
    record.busy=true;record.download.disabled=true;record.status.textContent=T.addonExportChecking;
    const controller=new AbortController();let timer,cancel;
    const interrupted=new Promise((resolve,reject)=>{cancel=reject;});
    record.cancel=()=>{cancel(this.host.failure("staleGeneration",T.addonDisabled));controller.abort();};
    try {
      const timeout=this.limits().authorizeTimeoutMs;
      timer=setTimeout(()=>{cancel(this.host.failure("exportTimeout",T.addonExportTimeout));controller.abort();},timeout);
      const installed=await Promise.race([this.host.json("/api/addons",{signal:controller.signal}),interrupted]);
      this.requireCurrent(record.scope);
      if(this.record!==record)return;
      const entry=installed.addons.find(row=>row.id===record.scope.identifier&&row.enabled&&row.compatible);
      if(!entry)throw this.host.failure("disabled",T.addonDisabled);
      if(entry.generation!==record.scope.generation)throw this.host.failure("staleGeneration",T.addonDisabled);
      if(typeof URL.createObjectURL!=="function"||typeof URL.revokeObjectURL!=="function"||typeof Blob!=="function")
        throw this.host.failure("exportUnavailable",T.addonExportUnavailable);
      this.releaseURL();
      this.url=URL.createObjectURL(new Blob([record.text],{type:"text/plain;charset=utf-8"}));
      const anchor=el("a",{href:this.url,download:record.filename,hidden:"hidden"});
      this.host.panel.appendChild(anchor);
      try{anchor.click();}finally{anchor.remove();}
      // Triggered is not saved: browser prompts/cancellation/disk writes are not
      // observable. Keep at most one URL until the next download or frame reset.
      this.host.notify("exports.requested",{filename:record.filename,format:record.format,bytes:record.bytes});
      record.cancel=null;this.clearPending();
    }catch(error) {
      if(this.record!==record||!this.current(record.scope))return;
      if(["disabled","staleGeneration"].includes(error.code)){this.host.close();return;}
      record.status.textContent=error.code?String(error.message):T.addonExportUnavailable;
      this.releaseURL();
    }finally {
      clearTimeout(timer);record.cancel=null;record.busy=false;record.download.disabled=false;
    }
  }
}
