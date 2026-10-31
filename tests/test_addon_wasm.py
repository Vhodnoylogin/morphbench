"""Embedded WebAssembly policy without widening add-on network or native access.

Synthetic local packages exercise the actual asset routes and generation checks. Node,
when available, executes the documented embedded-bytes pattern; browser CSP enforcement
and a consumer's compiled kernel need separate actual-browser qualification.
"""
import base64
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
from morphbench.addons import AddonError
from morphbench.journal import Journal
from presenters.serve import WebServer


# A complete WASM module exporting i32 add(i32, i32). This is a test fixture, not
# a workbench/domain formula or a second implementation of any consumer kernel.
ADD_MODULE = bytes.fromhex(
    "0061736d01000000 01070160027f7f017f 03020100 "
    "070701036164640000 0a09010700200020016a0b")
ENCODED = base64.b64encode(ADD_MODULE).decode("ascii")
SCRIPT = """'use strict';
async function loadKernel() {
  if (typeof WebAssembly !== 'object' || typeof WebAssembly.instantiate !== 'function') {
    throw new Error('WebAssembly unavailable');
  }
  const bytes = Uint8Array.from(atob('%s'), character => character.charCodeAt(0));
  const {instance} = await WebAssembly.instantiate(bytes, {});
  return instance.exports;
}
""" % ENCODED


def package(version="1", extra=None):
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("addon.json", json.dumps({
            "id": "wasm-probe", "name": "Embedded module probe", "version": version,
            "apiVersion": 1, "entry": "index.html"}))
        archive.writestr("index.html", '<!doctype html><script src="kernel.js"></script>')
        archive.writestr("kernel.js", SCRIPT)
        if extra:
            archive.writestr(*extra)
    return target.getvalue()


class TestAddonWasm(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bench = common.bench(self.tmp.name, common.sample_model(), common.sample_morphs())
        self.server = WebServer(self.bench, port=0, journal=Journal()).start()
        self.addCleanup(self.server.stop)
        self.client = build_opener(ProxyHandler({}))

    def get(self, path):
        try:
            response = self.client.open(Request(self.server.url.rstrip("/") + path), timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def install(self):
        row = self.bench.addon_install_bytes(package())
        self.bench.addon_enable(row["id"], True)
        return row

    def test_html_and_script_get_narrow_wasm_policy_on_both_asset_routes(self):
        row = self.install()
        for prefix in ("/addons/wasm-probe/", "/addon-assets/wasm-probe/" + row["generation"] + "/"):
            for filename in ("index.html", "kernel.js"):
                with self.subTest(prefix=prefix, filename=filename):
                    status, headers, body = self.get(prefix + filename)
                    self.assertEqual(status, 200, body)
                    policy = headers["Content-Security-Policy"]
                    script = next(value for value in policy.split(";")
                                  if value.strip().startswith("script-src "))
                    self.assertIn("'wasm-unsafe-eval'", script.split())
                    self.assertNotIn("'unsafe-eval'", script.split())
                    for restriction in ("default-src 'none'", "connect-src 'none'",
                                        "form-action 'none'", "base-uri 'none'",
                                        "frame-src 'none'", "object-src 'none'",
                                        "sandbox allow-scripts"):
                        self.assertIn(restriction, policy)
                    for permission in ("allow-same-origin", "allow-downloads", "allow-popups"):
                        self.assertNotIn(permission, policy)
                    self.assertIn(prefix, script)

    def test_enabled_generation_remains_required_for_embedded_module_bytes(self):
        row = self.install()
        path = "/addon-assets/wasm-probe/" + row["generation"] + "/kernel.js"
        self.assertEqual(self.get(path)[0], 200)
        self.bench.addon_enable("wasm-probe", False)
        self.assertNotEqual(self.get(path)[0], 200)
        replacement = self.bench.addon_update_bytes(package("2"))
        self.bench.addon_enable("wasm-probe", True)
        self.assertNotEqual(row["generation"], replacement["generation"])
        self.assertNotEqual(self.get(path)[0], 200)
        current = "/addon-assets/wasm-probe/" + replacement["generation"] + "/kernel.js"
        self.assertEqual(self.get(current)[0], 200)

    def test_raw_wasm_is_not_a_new_unbounded_asset_or_network_permission(self):
        with self.assertRaises(AddonError) as caught:
            self.bench.addon_install_bytes(package(extra=("kernel.wasm", ADD_MODULE)))
        self.assertEqual(caught.exception.code, "unsupportedFile")
        self.assertEqual(self.bench.addons()["addons"], [])

    def test_actual_webassembly_instantiates_embedded_bytes_without_imports_or_fetch(self):
        executable = shutil.which("node")
        if not executable:
            self.skipTest("Node not found for actual WebAssembly execution")
        script = Path(self.tmp.name) / "wasm-test.js"
        script.write_text(SCRIPT + """
(async()=>{
 const kernel = await loadKernel();
 let invalidModule = false;
 try {await WebAssembly.instantiate(Uint8Array.from([0,1,2]), {});}
 catch(error) {invalidModule = error instanceof WebAssembly.CompileError;}
 const module = await WebAssembly.compile(Uint8Array.from(atob('%s'), c=>c.charCodeAt(0)));
 console.log(JSON.stringify({sum:kernel.add(7,35),signed:kernel.add(-7,2),
   imports:WebAssembly.Module.imports(module), invalidModule}));
})().catch(error=>{console.error(error);process.exitCode=1;});
""" % ENCODED, encoding="utf-8")
        result = subprocess.run([executable, str(script)], capture_output=True, text=True,
                                timeout=10, check=True)
        self.assertEqual(json.loads(result.stdout), {
            "sum": 42, "signed": -5, "imports": [], "invalidModule": True})


if __name__ == "__main__":
    common.main()
