"""Large UTF-8 snapshots and finite export-resource ownership in actual host JavaScript.

Input strings are generated inside Node rather than embedded in source fixtures. Browser
Blob downloads and policy enforcement still require separate actual-browser qualification.
"""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import test_addon_exports as exports


CAPTURE_TIMERS = r"""
const timers=[];
global.setTimeout=(fn,ms)=>{const token={fn,ms,cleared:false};timers.push(token);return token;};
global.clearTimeout=token=>{if(token)token.cleared=true;};
"""


class TestAddonLargeExports(unittest.TestCase):
    setUp = exports.TestAddonExports.setUp
    run_js = exports.TestAddonExports.run_js

    def test_default_limit_rejects_twenty_mib_without_replacing_existing_snapshot(self):
        result = self.run_js(r"""
const c=setup();await c.prepare();const old=c.manager.record;
const text='"'+'x'.repeat(20*1024*1024-2)+'"';
const reply=await c.prepare(text,'geometry.json');
console.log(JSON.stringify({code:reply.error?.code,retained:c.manager.record===old,
  downloads:downloads.length,urls:urls.size}));c.host.destroyFrame();
""")
        self.assertEqual(result, {"code": "limitExceeded", "retained": True,
                                  "downloads": 0, "urls": 0})

    def test_explicit_large_limit_exact_utf8_boundaries_and_configuration_ceiling(self):
        result = self.run_js(r"""
const c=setup(),limit=32*1024*1024;c.bench.settings.addonExportMaxBytes=limit;
c.bench.settings.addonExportAuthorizeTimeoutMs=8000;
const twenty=await c.prepare('"'+'x'.repeat(20*1024*1024-2)+'"','geometry.json');
const exact=await c.prepare('"'+'x'.repeat(limit-2)+'"','exact.json'),old=c.manager.record;
const oversized=await c.prepare('"'+'x'.repeat(limit-1)+'"','oversized.json');
const retained=c.manager.record===old;
const unicode='"'+'😀'.repeat(Math.floor((limit-2)/4))+'x'.repeat((limit-2)%4)+'"';
const unicodeExact=await c.prepare(unicode,'unicode.json'),unicodeOld=c.manager.record;
const unicodeOver=await c.prepare(unicode.slice(0,-1)+'x"','unicode-over.json');
const unicodeRetained=c.manager.record===unicodeOld;
c.bench.settings.addonExportMaxBytes=limit+1;
const invalid=await c.prepare('{}');
c.bench.settings.addonExportMaxBytes=limit;
const invalidTtls=[];
for(const [key,value] of [['addonExportPendingTtlMs',0],['addonExportPendingTtlMs',3600001],
 ['addonExportUrlTtlMs',0],['addonExportUrlTtlMs',3600001],['addonExportPendingTtlMs',1.5],
 ['addonExportUrlTtlMs','1000']]) {
 const before=c.bench.settings[key];c.bench.settings[key]=value;
 invalidTtls.push((await c.prepare('{}')).error?.code);c.bench.settings[key]=before;
}
c.bench.settings.addonExportPendingTtlMs=3600000;c.bench.settings.addonExportUrlTtlMs=3600000;
const maximumTtls=(await c.request('host.info')).result?.exportLimits;
console.log(JSON.stringify({twenty:twenty.result?.bytes,exact:exact.result?.bytes,
 oversized:oversized.error?.code,retained,unicode:unicodeExact.result?.bytes,
 unicodeOver:unicodeOver.error?.code,unicodeRetained,invalid:invalid.error?.code,
 invalidTtls,maximumTtls:{pending:maximumTtls?.pendingTtlMs,url:maximumTtls?.urlTtlMs,
  supported:maximumTtls?.maxSupportedBytes,pendingFiles:maximumTtls?.pendingFiles,urls:maximumTtls?.retainedUrls},
 downloads:downloads.length}));c.host.destroyFrame();
""")
        self.assertEqual(result, {"twenty": 20 * 1024 * 1024, "exact": 32 * 1024 * 1024,
                                  "oversized": "limitExceeded", "retained": True,
                                  "unicode": 32 * 1024 * 1024, "unicodeOver": "limitExceeded",
                                  "unicodeRetained": True, "invalid": "invalidExportConfig",
                                  "invalidTtls": ["invalidExportConfig"] * 6,
                                  "maximumTtls": {"pending": 3600000, "url": 3600000,
                                                  "supported": 32 * 1024 * 1024,
                                                  "pendingFiles": 1, "urls": 1},
                                  "downloads": 0})

    def test_validation_crossing_request_deadline_preserves_previous_snapshot(self):
        result = self.run_js(r"""
const c=setup();await c.prepare();const old=c.manager.record;
let now=Date.now();Date.now=()=>now;
const validate=c.manager.validate.bind(c.manager);
c.manager.validate=params=>{const result=validate(params);now+=101;return result;};
const reply=await c.prepare('{"next":2}','next.json');
console.log(JSON.stringify({code:reply.error?.code,retained:c.manager.record===old,
 downloads:downloads.length,urls:urls.size}));c.host.destroyFrame();
""")
        self.assertEqual(result, {"code": "exportTimeout", "retained": True,
                                  "downloads": 0, "urls": 0})

    def test_wall_clock_expiry_and_late_authorization_do_not_depend_on_timer_dispatch(self):
        result = self.run_js(CAPTURE_TIMERS + r"""
let now=Date.now();Date.now=()=>now;
const pre=setup();pre.bench.settings.addonExportPendingTtlMs=10;
await pre.prepare();const preRecord=pre.manager.record,beforeRequests=pre.requests;now+=11;
await pre.manager.download(preRecord,{isTrusted:true});
const preResult={empty:pre.manager.record===null,requests:pre.requests-beforeRequests,
 expired:pre.events.some(item=>item.event==='exports.expired'&&item.data.reason==='pendingExpired')};
const during=setup();during.bench.settings.addonExportPendingTtlMs=10;
await during.prepare();const duringRecord=during.manager.record,gate=deferred();
during.hook=()=>gate.promise;const pending=during.manager.download(duringRecord,{isTrusted:true});
await Promise.resolve();now+=11;gate.resolve();await pending;
const duringResult={empty:during.manager.record===null,
 expired:during.events.some(item=>item.event==='exports.expired'&&item.data.reason==='pendingExpired')};
const late=setup();late.bench.settings.addonExportPendingTtlMs=300000;
await late.prepare();const lateRecord=late.manager.record,lateGate=deferred();
late.hook=()=>lateGate.promise;const lateWork=late.manager.download(lateRecord,{isTrusted:true});
await Promise.resolve();now+=101;lateGate.resolve();await lateWork;
const lateResult={retained:late.manager.record===lateRecord,busy:lateRecord.busy,
 timedOut:lateRecord.status.textContent.includes('timed out')};
console.log(JSON.stringify({pre:preResult,during:duringResult,late:lateResult,
 downloads:downloads.length,urls:urls.size}));
pre.host.destroyFrame();during.host.destroyFrame();late.host.destroyFrame();
""")
        self.assertEqual(result, {"pre": {"empty": True, "requests": 0, "expired": True},
                                  "during": {"empty": True, "expired": True},
                                  "late": {"retained": True, "busy": False, "timedOut": True},
                                  "downloads": 0, "urls": 0})

    def test_pending_timer_cleanup_and_queued_stale_callbacks_are_snapshot_scoped(self):
        result = self.run_js(CAPTURE_TIMERS + r"""
const c=setup(),ttl=c.manager.limits().pendingTtlMs;
await c.prepare();const first=timers.find(item=>item.ms===ttl);
await c.prepare('{"second":2}','second.json');const secondRecord=c.manager.record;
const second=timers.filter(item=>item.ms===ttl).at(-1);first.fn();
const staleRetained=c.manager.record===secondRecord;
await c.request('exports.cancel');second.fn();
await c.prepare('{"third":3}','third.json');const third=timers.filter(item=>item.ms===ttl).at(-1);
c.host.destroyFrame();third.fn();
const changed=setup();await changed.prepare();const changedTimer=timers.filter(item=>item.ms===ttl).at(-1);
changed.host.frame.remove();const replacement=new Element('iframe');replacement.contentWindow={postMessage(){}};
changed.host.panel.appendChild(replacement);changed.host.frame=replacement;changed.host.active='replacement';
changedTimer.fn();const changedResult={empty:changed.manager.record===null,
 replacementPreserved:changed.host.frame===replacement,children:changed.host.panel.children.length,
 events:changed.events.length};changed.host.destroyFrame();
console.log(JSON.stringify({staleRetained,cleared:[first.cleared,second.cleared,third.cleared],
 pending:c.manager.record,frame:c.host.frame,events:c.events.length,changed:changedResult,
 downloads:downloads.length}));
""")
        self.assertEqual(result, {"staleRetained": True, "cleared": [True, True, True],
                                  "pending": None, "frame": None, "events": 0,
                                  "changed": {"empty": True, "replacementPreserved": True,
                                              "children": 1, "events": 0}, "downloads": 0})

    def test_blob_allocation_crossing_expiry_or_authorization_deadline_leaves_no_download(self):
        result = self.run_js(CAPTURE_TIMERS + r"""
let now=Date.now();Date.now=()=>now;const NativeBlob=Blob,output=[];
for(const kind of ['pending','authorization']) {
 const c=setup();c.bench.settings.addonExportPendingTtlMs=kind==='pending'?10:300000;
 c.bench.settings.addonExportAuthorizeTimeoutMs=kind==='pending'?100:10;
 await c.prepare();const record=c.manager.record;
 global.Blob=class extends NativeBlob {constructor(parts,options){super(parts,options);now+=11;}};
 await c.manager.download(record,{isTrusted:true});global.Blob=NativeBlob;
 output.push({kind,empty:c.manager.record===null,retained:c.manager.record===record,
  expired:c.events.some(item=>item.event==='exports.expired'),
  timedOut:record.status.textContent.includes('timed out'),urls:urls.size,busy:record.busy,
  urlTimerCleared:timers.filter(item=>item.ms===c.manager.limits().urlTtlMs).at(-1)?.cleared});
 c.host.destroyFrame();
}
console.log(JSON.stringify({output,downloads:downloads.length}));
""")
        self.assertEqual(result, {
            "output": [
                {"kind": "pending", "empty": True, "retained": False, "expired": True,
                 "timedOut": False, "urls": 0, "busy": False, "urlTimerCleared": True},
                {"kind": "authorization", "empty": False, "retained": True, "expired": False,
                 "timedOut": True, "urls": 0, "busy": False, "urlTimerCleared": True}],
            "downloads": 0})

    def test_url_expiry_and_old_timer_cannot_revoke_a_new_download(self):
        result = self.run_js(CAPTURE_TIMERS + r"""
const c=setup(),ttl=c.manager.limits().urlTtlMs;
await c.prepare();await c.manager.download(c.manager.record,{isTrusted:true});
const first=timers.filter(item=>item.ms===ttl).at(-1),oldURL=c.manager.url;
await c.prepare('{"second":2}','second.json');await c.manager.download(c.manager.record,{isTrusted:true});
const second=timers.filter(item=>item.ms===ttl).at(-1),newURL=c.manager.url;first.fn();
const staleSafe=urls.has(newURL)&&!urls.has(oldURL);second.fn();
const expired=urls.size===0&&c.manager.url===null;
await c.prepare('{"third":3}','third.json');await c.manager.download(c.manager.record,{isTrusted:true});
const third=timers.filter(item=>item.ms===ttl).at(-1);c.host.destroyFrame();third.fn();
console.log(JSON.stringify({staleSafe,expired,firstCleared:first.cleared,
 thirdCleared:third.cleared,urls:urls.size,pending:c.manager.record,downloads:downloads.length}));
""")
        self.assertEqual(result, {"staleSafe": True, "expired": True, "firstCleared": True,
                                  "thirdCleared": True, "urls": 0, "pending": None, "downloads": 3})


if __name__ == "__main__":
    common.main()
