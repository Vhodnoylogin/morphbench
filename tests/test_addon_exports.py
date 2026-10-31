"""Actual export-host/RPC JavaScript with browser and download resource doubles.

These tests exercise user-action gating, snapshots, authorization races and URL
cleanup. DOMParser is a double here; actual XML/browser download qualification is
separate and is not inferred from these synthetic checks.
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
from presenters.web import WebPage
from test_workspace_integration import run_browser

ROOT = Path(__file__).resolve().parent.parent

PLATFORM = r"""
class Element {
 constructor(tag){this.tag=tag;this.children=[];this.parentNode=null;this.hidden=false;}
 setAttribute(name,value){this[name]=value;}
 addEventListener(name,handler){(this.listeners??={})[name]=handler;}
 appendChild(node){node.parentNode=this;this.children.push(node);return node;}
 insertBefore(node,before){node.parentNode=this;this.children.splice(this.children.indexOf(before),0,node);return node;}
 remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(node=>node!==this);this.parentNode=null;}
 click(){if(this.tag==='a')downloads.push({filename:this.download,blob:urls.get(this.href)});}
}
const downloads=[],urls=new Map(),revoked=[];let urlSerial=0,xmlParserHook=null;
// Product TTLs are long-lived browser timers; they must not keep a Node fixture alive.
const nativeSetTimeout=global.setTimeout;
global.setTimeout=(fn,ms,...args)=>{const timer=nativeSetTimeout(fn,ms,...args);if(ms>=1000)timer.unref();return timer;};
const mainPanel=new Element('aside');
document.createElement=tag=>new Element(tag);
document.getElementById=id=>mainPanel;
document.documentElement={lang:'en'};
global.window={location:{href:'http://localhost/?addon=example'},history:{replaceState(){}}};
URL.createObjectURL=blob=>{const url='blob:example/'+(++urlSerial);urls.set(url,blob);return url;};
URL.revokeObjectURL=url=>{revoked.push(url);urls.delete(url);};
global.DOMParser=class {parseFromString(text,type){
 if(type!=='application/xml')throw Error('wrong parse type');
 if(xmlParserHook)return xmlParserHook(text);
 return {documentElement:{},getElementsByTagNameNS:(namespace,name)=>{
  if(name!=='parsererror')throw Error('wrong parse-error query');
  return [];
 }};
}};
const clone=value=>JSON.parse(JSON.stringify(value));
const deferred=()=>{let resolve;const promise=new Promise(yes=>{resolve=yes;});return {promise,resolve};};
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function setup(){
 const replies=[],events=[],context={generation:'g1',enabled:true,requests:0,hook:null};
 const source={postMessage:message=>{if(message.type==='morphbench-addon:event')events.push(clone(message));else replies.push(clone(message));}};
 const host=Object.create(AddonHost.prototype);host.active='example';host.generation='g1';host.opened=true;
 host.frame=new Element('iframe');host.frame.contentWindow=source;
 host.panel=new Element('aside');host.panel.appendChild(host.frame);host.paintNav=()=>{};
 const bench=new BenchMirror(DATA);
 bench.settings.addonExportMaxBytes=1048576;bench.settings.addonExportAuthorizeTimeoutMs=100;
 host.app={bench};host.json=async()=>{context.requests++;if(context.hook)await context.hook();
  return {addons:[{id:'example',name:'Example',version:'dev',generation:context.generation,enabled:context.enabled,compatible:true}]};};
 let serial=0;
 const request=async(method,params={},sender=source,extra={})=>{
  const id=String(++serial);await host.receive({source:sender,data:{type:'morphbench-addon:request',apiVersion:1,id,method,params,...extra}});
  return replies.find(reply=>reply.id===id);
 };
 const prepare=(text='{"value":1}',filename='preset.v1.json',format='json')=>request('exports.prepare',{filename,format,text});
 const manager=host.exportManager();
 return Object.assign(context,{host,manager,bench,request,prepare,source,replies,events});
}
"""


class TestAddonExports(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        bench = common.bench(self.tmp.name, common.sample_model(), common.sample_morphs())
        self.payload = WebPage(bench).payload()

    def run_js(self, code):
        source = "\n".join((ROOT / "web/js" / name).read_text(encoding="utf-8")
                           for name in ("addon_session.js", "addons.js"))
        return run_browser(self, self.tmp.name, self.payload, source + PLATFORM
                           + "\n(async()=>{\n" + code
                           + "\n})().catch(error=>{console.error(error);process.exitCode=1;});")

    def test_prepare_is_inert_and_download_uses_the_exact_utf8_snapshot(self):
        result = self.run_js(r"""
const c=setup(),text='{"name":"Русский 😀","value":1}\r\n';
const response=await c.prepare(text,'Настройки.v2.json'),before={downloads:downloads.length,urls:urls.size};
const record=c.manager.record;await c.manager.download(record,{isTrusted:false});
const synthetic=downloads.length;await c.manager.download(record,{isTrusted:true});
console.log(JSON.stringify({response,before,synthetic,downloads:await Promise.all(downloads.map(async item=>({filename:item.filename,text:await item.blob.text(),type:item.blob.type}))),events:c.events,pending:c.manager.record,retainedURLs:urls.size}));
""")
        text = '{"name":"Русский 😀","value":1}\r\n'
        self.assertEqual(result["response"]["result"], {
            "prepared": True, "filename": "Настройки.v2.json", "format": "json",
            "bytes": len(text.encode("utf-8"))})
        self.assertEqual(result["before"], {"downloads": 0, "urls": 0})
        self.assertEqual(result["synthetic"], 0)
        self.assertEqual(result["downloads"], [{"filename": "Настройки.v2.json", "text": text,
                                              "type": "text/plain;charset=utf-8"}])
        self.assertEqual(result["events"][0]["event"], "exports.requested")
        self.assertIsNone(result["pending"])
        self.assertEqual(result["retainedURLs"], 1)

    def test_rejected_names_formats_unicode_and_json_preserve_previous_snapshot(self):
        result = self.run_js(r"""
const c=setup();await c.prepare();const original=c.manager.record,rejected=[];
for(const filename of ['../p.json','C:\\p.json','folder/p.json','p.exe','p.json.html','.p.json','a..b.json','CON.json','COM¹.json','LPT9.v2.json','a .json','x\u202Ey.json','x\n.json','x'.repeat(256)+'.json']){
 const result=await c.prepare('{}',filename);rejected.push(result.error?.code);if(c.manager.record!==original)throw Error('lost previous file');
}
for(const params of [{filename:'p.json',format:'html',text:'{}'},{filename:'p.xml',format:'json',text:'{}'},{filename:'p.json',format:'json',text:'{bad}'},{filename:'p.json',format:'json',text:'"\ud800"'},{filename:'p\ud800.json',format:'json',text:'{}'},{filename:'p.json',format:'json',text:'{}',path:'/tmp'}]){
 const result=await c.request('exports.prepare',params);rejected.push(result.error?.code);if(c.manager.record!==original)throw Error('lost previous file');
}
console.log(JSON.stringify({rejected,downloads:downloads.length,controls:c.host.panel.children.filter(node=>node.tag==='section').length}));
""")
        self.assertEqual(result["rejected"], ["invalidParams"] * 20)
        self.assertEqual(result["downloads"], 0)
        self.assertEqual(result["controls"], 1)

    def test_byte_bound_counts_unicode_and_invalid_settings_fail_explicitly(self):
        result = self.run_js(r"""
const c=setup();c.bench.settings.addonExportMaxBytes=6;
const exact=await c.prepare('"😀"'),tooLarge=await c.prepare('"😀x"');
const invalid=[];for(const limit of [0,-1,1.5,Infinity,'100']){c.bench.settings.addonExportMaxBytes=limit;invalid.push((await c.prepare()).error?.code);}
c.bench.settings.addonExportMaxBytes=100;c.bench.settings.addonExportAuthorizeTimeoutMs=10000;
invalid.push((await c.prepare()).error?.code);
console.log(JSON.stringify({exact,tooLarge,invalid,pending:c.manager.record.text}));
""")
        self.assertEqual(result["exact"]["result"]["bytes"], 6)
        self.assertEqual(result["tooLarge"]["error"]["code"], "limitExceeded")
        self.assertEqual(result["invalid"], ["invalidExportConfig"] * 6)
        self.assertEqual(result["pending"], '"😀"')

    def test_xml_is_parsed_inertly_and_declarations_stylesheets_errors_reject(self):
        result = self.run_js(r"""
const c=setup(),xml='<?xml version="1.0"?><preset><value>2</value></preset>';
const good=await c.prepare(xml,'preset.xml','xml'),original=c.manager.record,rejected=[];
for(const text of ['<!DOCTYPE preset SYSTEM "http://remote/"><preset/>','<!ENTITY x "y"><preset/>','<?xml-stylesheet href="http://remote/"?><preset/>'])rejected.push((await c.prepare(text,'p.xml','xml')).error?.code);
for(const errorNamespace of ['http://www.mozilla.org/newlayout/xml/parsererror.xml','http://www.w3.org/1999/xhtml']) {
 xmlParserHook=()=>({documentElement:{},getElementsByTagNameNS:(namespace,name)=>
   name==='parsererror'&&(namespace==='*'||namespace===errorNamespace)?[{}]:[]});
 rejected.push((await c.prepare('<broken>','p.xml','xml')).error?.code);
}
xmlParserHook=()=>({documentElement:null,getElementsByTagNameNS:()=>[]});
rejected.push((await c.prepare('','p.xml','xml')).error?.code);
console.log(JSON.stringify({good,rejected,retained:c.manager.record===original,downloads:downloads.length}));
""")
        self.assertTrue(result["good"]["result"]["prepared"])
        self.assertEqual(result["rejected"], ["invalidParams"] * 6)
        self.assertTrue(result["retained"])
        self.assertEqual(result["downloads"], 0)

    def test_download_rechecks_disabled_and_replaced_generation(self):
        result = self.run_js(r"""
const output=[];for(const changed of ['disabled','generation']){
 const c=setup();await c.prepare();const record=c.manager.record;
 if(changed==='disabled')c.enabled=false;else c.generation='g2';
 await c.manager.download(record,{isTrusted:true});output.push({closed:c.host.frame===null,pending:c.manager.record,urls:urls.size});
}
console.log(JSON.stringify({output,downloads:downloads.length}));
""")
        self.assertEqual(result["downloads"], 0)
        self.assertTrue(all(row["closed"] and row["pending"] is None and not row["urls"]
                            for row in result["output"]))

    def test_pending_authorization_cannot_download_a_replaced_snapshot(self):
        result = self.run_js(r"""
const c=setup();await c.prepare('{"old":1}');const old=c.manager.record,gate=deferred();c.hook=()=>gate.promise;
const download=c.manager.download(old,{isTrusted:true});await delay(0);c.hook=null;
await c.prepare('{"new":2}','new.json');gate.resolve();await download;
await c.manager.download(old,{isTrusted:true});
console.log(JSON.stringify({downloads:downloads.length,pending:c.manager.record.text,busy:c.manager.record.busy,urls:urls.size}));
""")
        self.assertEqual(result, {"downloads": 0, "pending": '{"new":2}', "busy": False, "urls": 0})

    def test_cancel_and_frame_close_abort_inflight_work_and_revoke_urls(self):
        result = self.run_js(r"""
const c=setup();await c.prepare();await c.manager.download(c.manager.record,{isTrusted:true});
await c.prepare('{"next":2}');const record=c.manager.record,gate=deferred();c.hook=()=>gate.promise;
const download=c.manager.download(record,{isTrusted:true});await delay(0);
c.hook=null;const cancelled=await c.request('exports.cancel');gate.resolve();await download;
const empty=await c.request('exports.cancel');c.host.destroyFrame();
console.log(JSON.stringify({cancelled,empty,downloads:downloads.length,urls:urls.size,revoked:revoked.length,frame:c.host.frame}));
""")
        self.assertEqual(result["cancelled"]["result"], {"cancelled": True})
        self.assertEqual(result["empty"]["result"], {"cancelled": False})
        self.assertEqual(result["downloads"], 1)
        self.assertEqual(result["urls"], 0)
        self.assertEqual(result["revoked"], 1)
        self.assertIsNone(result["frame"])

    def test_timeout_suppresses_late_authorization_and_allows_explicit_retry(self):
        result = self.run_js(r"""
const c=setup();c.bench.settings.addonExportAuthorizeTimeoutMs=5;await c.prepare();const record=c.manager.record;
const gate=deferred();c.hook=()=>gate.promise;await c.manager.download(record,{isTrusted:true});
const afterTimeout={downloads:downloads.length,busy:record.busy,enabled:!record.download.disabled,status:record.status.textContent};
gate.resolve();await delay(0);const afterLate=downloads.length;c.hook=null;
await c.manager.download(record,{isTrusted:true});
console.log(JSON.stringify({afterTimeout,afterLate,downloads:downloads.length}));
""")
        self.assertEqual(result["afterTimeout"]["downloads"], 0)
        self.assertFalse(result["afterTimeout"]["busy"])
        self.assertTrue(result["afterTimeout"]["enabled"])
        self.assertIn("timed out", result["afterTimeout"]["status"])
        self.assertEqual(result["afterLate"], 0)
        self.assertEqual(result["downloads"], 1)

    def test_double_click_is_single_download_and_at_most_one_url_is_retained(self):
        result = self.run_js(r"""
const c=setup();await c.prepare();const record=c.manager.record,gate=deferred();c.hook=()=>gate.promise;
const first=c.manager.download(record,{isTrusted:true}),second=c.manager.download(record,{isTrusted:true});gate.resolve();await Promise.all([first,second]);
c.hook=null;await c.prepare('{"next":2}','second.json');await c.manager.download(c.manager.record,{isTrusted:true});
const retained=urls.size;c.host.close();
console.log(JSON.stringify({downloads:downloads.map(item=>item.filename),retained,revoked:revoked.length,urls:urls.size}));
""")
        self.assertEqual(result["downloads"], ["preset.v1.json", "second.json"])
        self.assertEqual(result["retained"], 1)
        self.assertEqual(result["revoked"], 2)
        self.assertEqual(result["urls"], 0)

    def test_transport_sender_version_keys_and_capability_discovery_remain_explicit(self):
        result = self.run_js(r"""
const c=setup(),info=await c.request('host.info'),spoof=await c.request('exports.prepare',{},{});
const wrong=await c.request('exports.prepare',{},c.source,{apiVersion:2}),extra=await c.request('exports.cancel',{id:'other'});
console.log(JSON.stringify({info,spoof:spoof??null,wrong,extra,downloads:downloads.length}));
""")
        info = result["info"]["result"]
        self.assertTrue({"exports.prepare", "exports.cancel"}.issubset(info["capabilities"]))
        self.assertEqual(info["exportLimits"], {"maxBytes": 1048576, "authorizeTimeoutMs": 100,
                         "pendingTtlMs": 300000, "urlTtlMs": 60000, "maxSupportedBytes": 33554432,
                         "retainedUrls": 1,
                                                "formats": ["json", "xml"], "maxFilenameBytes": 255,
                                                "pendingFiles": 1})
        self.assertIsNone(result["spoof"])
        self.assertEqual(result["wrong"]["error"]["code"], "incompatibleApi")
        self.assertEqual(result["extra"]["error"]["code"], "invalidParams")
        self.assertEqual(result["downloads"], 0)

    def test_initial_authorization_budget_and_frame_changes_publish_no_late_export(self):
        result = self.run_js(r"""
const c=setup();c.bench.settings.addonExportAuthorizeTimeoutMs=5;
c.hook=()=>delay(15);const delayed=await c.prepare();
const empty=c.manager.record===null;c.hook=null;c.bench.settings.addonExportAuthorizeTimeoutMs=100;
await c.prepare();const record=c.manager.record,gate=deferred();c.hook=()=>gate.promise;
const download=c.manager.download(record,{isTrusted:true});await delay(0);
const replacement=new Element('iframe');replacement.contentWindow={postMessage(){}};c.host.frame=replacement;
gate.resolve();await download;
console.log(JSON.stringify({delayed,empty,downloads:downloads.length,newFrameRetained:c.host.frame===replacement,urls:urls.size}));
""")
        self.assertEqual(result["delayed"]["error"]["code"], "exportTimeout")
        self.assertTrue(result["empty"])
        self.assertEqual(result["downloads"], 0)
        self.assertTrue(result["newFrameRetained"])
        self.assertEqual(result["urls"], 0)


if __name__ == "__main__":
    common.main()
