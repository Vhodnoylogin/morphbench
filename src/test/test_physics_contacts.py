"""CBPC contacts retain source and use explicit actor weights and rest node frames offline."""
import copy
import json
import math
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

from morphbench.physics_workspace import PhysicsWorkspace  # noqa: E402
from presenters.physics_document import parse_document  # noqa: E402


IDENTITY = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
FRAME = [[0, -2, 0, 10], [2, 0, 0, 20], [0, 0, 2, 30], [0, 0, 0, 1]]
NODE = "NPC L Hand [LHnd]"
SOURCE = ("\ufeff# 😀 collision document\r\n[AffectedNodes]\r\n" + NODE + "\r\n"
          "[Options]\r\nClaw.linearX 0.5 0.7 # raw parameter\r\n"
          "[" + NODE + "] # nested node tag\r\n"
          " 1.00,2,3,1 | 5,6,7,3 # weighted sphere\r\n"
          " 0,0,0,2 & 10,0,0,1 | 0,0,0,4 & 20,0,0,2 # unequal radii\r\n"
          "opaque vendor data 123\r\n[" + NODE + "]\r\n0,0,0,0\r\n")


def contacts(document):
    return [row for row in document["records"] if row["type"] == "contact"]


def radius_binding_cases():
    """Externally supplied normalized documents may lack optional adapter metadata."""
    document = parse_document("cbpc", "[A]\n0,0,0,-1 & 5,0,0,2 | 0,0,0,3 & 10,0,0,4\n")
    for field in document["fields"]:
        field.pop("minimum", None)
    radii = [end[3] for side in ("low", "high") for end in contacts(document)[0]["geometry"][side]]
    malformed = []
    for minimum in (-10, 1):
        candidate = copy.deepcopy(document)
        next(field for field in candidate["fields"] if field["id"] == radii[0])["minimum"] = minimum
        malformed.append(candidate)
    for change in (lambda row: row.update(shape=[]),
                   lambda row: row.update(shape="__proto__"),
                   lambda row: row.update(weighted=False),
                   lambda row: row["geometry"]["low"][0].__setitem__(3, row["geometry"]["low"][0][0]),
                   lambda row: row["geometry"]["high"][0].__setitem__(0, row["geometry"]["low"][0][3])):
        candidate = copy.deepcopy(document)
        change(contacts(candidate)[0])
        malformed.append(candidate)
    return document, radii, malformed


class TestContactParsing(unittest.TestCase):
    def test_nested_node_tags_duplicate_sections_and_original_spans(self):
        document = parse_document("cbpc", SOURCE)
        rows = contacts(document)
        self.assertEqual([row["node"] for row in rows], [NODE] * 3)
        self.assertEqual([row["shape"] for row in rows], ["sphere", "capsule", "sphere"])
        self.assertEqual([row["weighted"] for row in rows], [True, True, False])
        self.assertNotEqual(rows[0]["group"], rows[2]["group"])
        self.assertTrue(any(row["type"] == "raw" for row in document["records"]))
        owner = PhysicsWorkspace(document)
        self.assertEqual(owner.export_text(), SOURCE)
        before = copy.deepcopy(document)
        field_id = rows[0]["geometry"]["low"][0][0]
        field = next(item for item in document["fields"] if item["id"] == field_id)
        owner.set(field_id, 2.5)
        self.assertEqual(owner.export_text(), SOURCE[:field["start"]] + "2.5" + SOURCE[field["end"]:])
        owner.envelopes({NODE: FRAME}, weight=37.5)
        self.assertEqual(document, before)
        self.assertEqual(owner.state()["document"], before)
        owner.set(field_id, 1)
        self.assertEqual(owner.export_text(), SOURCE)

    def test_only_exact_sphere_or_matching_capsule_grammar_becomes_geometry(self):
        malformed = ("1,2,3", "1,2,3,4,5", "1,2,3,4:", "1,2,3,4 & 5,6,7,8 & 9,0,1,2",
                     "1,2,3,4 | 1,2,3,4 & 5,6,7,8", "1,2,3,4 || 1,2,3,4", "1,2,3,4 extra")
        for line in malformed:
            with self.subTest(line=line):
                source = "[" + NODE + "]\n" + line + " # retain\n"
                document = parse_document("cbpc", source)
                self.assertFalse(contacts(document))
                owner = PhysicsWorkspace(document)
                self.assertFalse(owner.envelopes({NODE: IDENTITY})["lines"])
                self.assertEqual(owner.export_text(), source)
        for section in ("Options", "ExtraOptions", "AffectedNodes", "ColliderNodes", "PlayerNodes", "ConfigMap"):
            self.assertFalse(contacts(parse_document("cbpc", "[" + section + "]\n1,2,3,4\n")))
        self.assertEqual(contacts(parse_document("cbpc", "\ufeff[" + NODE + "]\r\n1,2,3,4\r\n"))[0]["node"], NODE)
        for header in ("[B [Tag]", "[B] extra", "[B][C]"):
            self.assertFalse(contacts(parse_document("cbpc", "[A]\n" + header + "\n1,2,3,4\n")))

    def test_nonfinite_and_negative_source_radii_are_preserved_and_withheld(self):
        for radius in ("-1", "1e999"):
            source = "[" + NODE + "]\n0,0,0," + radius + "\n"
            owner = PhysicsWorkspace(parse_document("cbpc", source))
            result = owner.envelopes({NODE: IDENTITY})
            self.assertEqual(result["records"][0]["status"], "invalid_geometry")
            self.assertFalse(result["lines"])
            self.assertEqual(owner.export_text(), source)
            json.dumps(result, allow_nan=False)

    def test_contact_schema_validation_is_atomic(self):
        owner = PhysicsWorkspace(parse_document("cbpc", SOURCE))
        before = owner.state()
        for change in (lambda row: row.update(shape="box"),
                       lambda row: row["geometry"]["low"][0].append("f0"),
                       lambda row: row["geometry"]["high"][0].__setitem__(0, "absent")):
            candidate = copy.deepcopy(before["document"])
            change(contacts(candidate)[0])
            with self.assertRaises(ValueError):
                owner.replace(candidate)
            self.assertEqual(owner.state(), before)

    def test_radius_semantics_do_not_depend_on_optional_minimum_metadata(self):
        document, radii, malformed = radius_binding_cases()
        owner = PhysicsWorkspace(document)
        original = owner.state()
        self.assertEqual(owner.export_text(), document["text"])
        for radius_id in radii:
            with self.assertRaises(ValueError):
                owner.set(radius_id, -2)
            self.assertEqual(owner.state(), original)
        owner.set(radii[0], 2)
        coordinate_id = contacts(document)[0]["geometry"]["low"][0][0]
        owner.set(coordinate_id, -5)
        before = owner.state()
        self.assertEqual(owner.export_text(), "[A]\n-5,0,0,2 & 5,0,0,2 | 0,0,0,3 & 10,0,0,4\n")
        for candidate in malformed:
            with self.assertRaises(ValueError):
                owner.replace(candidate)
            self.assertEqual(owner.state(), before)
            with self.assertRaises(ValueError):
                owner.set(radii[0], -7)
            self.assertEqual(owner.state(), before)


class TestContactGeometry(unittest.TestCase):
    def test_weight_interpolation_rotated_scaled_node_frame_and_numeric_record(self):
        owner = PhysicsWorkspace(parse_document("cbpc", SOURCE))
        result = owner.envelopes({NODE: FRAME}, weight=25, contact_segments=8)
        row = result["records"][1]
        self.assertEqual(row["type"], "contact")
        self.assertEqual(row["status"], "resolved")
        self.assertEqual(row["local_endpoints"], [[2, 3, 4, 1.5]])
        self.assertEqual(row["world_endpoints"], [[4, 24, 38, 3]])
        self.assertEqual(row["weight"], 25)
        self.assertEqual(result["weight"], 25)
        self.assertTrue(any(line["kind"] == "contact_sphere" for line in result["lines"]))
        self.assertEqual(contacts(owner.envelopes({NODE: IDENTITY}))[0]["local_endpoints"], [[1, 2, 3, 1]])
        self.assertEqual(contacts(owner.envelopes({NODE: IDENTITY}, weight=100))[0]["local_endpoints"], [[5, 6, 7, 3]])
        json.dumps(result, allow_nan=False)

    def test_unequal_capsule_uses_tangent_cone_and_retains_both_radii(self):
        source = "[A]\n0,0,0,2 & 10,0,0,1\n"
        owner = PhysicsWorkspace(parse_document("cbpc", source))
        result = owner.envelopes({"A": IDENTITY}, contact_segments=4)
        self.assertEqual(result["records"][0]["world_endpoints"], [[0, 0, 0, 2], [10, 0, 0, 1]])
        # First two four-edge rings lie at their common tangent, x=r*(rA-rB)/d.
        a, b = result["lines"][0]["a"], result["lines"][4]["a"]
        self.assertAlmostEqual(a[0], 0.2)
        self.assertAlmostEqual(b[0], 10.1)
        self.assertAlmostEqual(sum(value * value for value in a), 4)
        self.assertAlmostEqual(sum((value - centre) ** 2 for value, centre in zip(b, [10, 0, 0])), 1)
        self.assertAlmostEqual(math.hypot(a[1], a[2]), 2 * math.sqrt(0.99))
        self.assertAlmostEqual(math.hypot(b[1], b[2]), math.sqrt(0.99))
        self.assertEqual(owner.export_text(), source)

    def test_contained_and_coincident_capsule_endpoints_use_containing_sphere(self):
        for endpoints in ("0,0,0,3 & 1,0,0,1", "0,0,0,3 & 0,0,0,1", "0,0,0,0 & 0,0,0,0"):
            with self.subTest(endpoints=endpoints):
                result = PhysicsWorkspace(parse_document("cbpc", "[A]\n" + endpoints)).envelopes({"A": IDENTITY}, contact_segments=4)
                self.assertEqual(result["records"][0]["status"], "resolved")
                self.assertEqual(len(result["lines"]), 12)
                radius = result["records"][0]["local_endpoints"][0][3]
                for line in result["lines"]:
                    self.assertAlmostEqual(sum(value * value for value in line["a"]), radius * radius)

    def test_missing_node_and_unsupported_frame_are_distinct_and_never_origin_fallback(self):
        owner = PhysicsWorkspace(parse_document("cbpc", "[A]\n1,2,3,4\n"))
        for frames, expected in (({}, "unresolved_node"),
                                 ({"A": {"matrix": IDENTITY, "source": "ragdoll"}}, "unsupported_frame"),
                                 ({"A": [[1, 1, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]}, "unsupported_frame")):
            result = owner.envelopes(frames)
            self.assertEqual(result["records"][0]["status"], expected)
            self.assertEqual(result["records"][0]["local_endpoints"], [[1, 2, 3, 4]])
            self.assertIsNone(result["records"][0]["world_endpoints"])
            self.assertFalse(result["lines"])

    def test_radius_edits_reject_negative_values_atomically_but_repair_invalid_source(self):
        owner = PhysicsWorkspace(parse_document("cbpc", "[A]\n0,0,0,-1\n"))
        radius_id = contacts(owner.state())[0]["geometry"]["low"][0][3]
        before = owner.state()
        with self.assertRaises(ValueError):
            owner.set(radius_id, -2)
        self.assertEqual(owner.state(), before)
        owner.set(radius_id, 2)
        self.assertEqual(owner.envelopes({"A": IDENTITY})["records"][0]["world_endpoints"], [[0, 0, 0, 2]])
        self.assertEqual(owner.export_text(), "[A]\n0,0,0,2\n")

    def test_invalid_weights_and_tessellation_do_not_mutate_owner(self):
        owner = PhysicsWorkspace(parse_document("cbpc", SOURCE))
        before = owner.state()
        for weight in (-1, 101, True, "50", None, float("nan"), float("inf")):
            with self.subTest(weight=weight), self.assertRaises(ValueError):
                owner.envelopes({NODE: FRAME}, weight=weight)
            self.assertEqual(owner.state(), before)
        for segments in (0, 2, 257, 4.5, True):
            with self.assertRaises(ValueError):
                owner.envelopes(contact_segments=segments)
        self.assertEqual(owner.state(), before)


class TestContactBrowserParity(unittest.TestCase):
    def test_radius_bindings_enforce_edits_and_reject_malformed_documents_atomically(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is unavailable for browser parity")
        document, radii, malformed = radius_binding_cases()
        texts = json.loads((common.ROOT / "locale/en/physics_workspace.json").read_text(encoding="utf-8"))
        script_path = common.ROOT / "web/js/physics_workspace.js"
        code = "\nconst data=JSON.parse(require('fs').readFileSync(0,'utf8')),owner=new PhysicsWorkspaceMirror(data.document,data.texts);" \
               "const reject=(action)=>{const before=JSON.stringify(owner.state());let failed=false;try{action();}catch(error){failed=true;}if(!failed||JSON.stringify(owner.state())!==before)throw new Error('atomic rejection');};" \
               "if(owner.export_text()!==data.document.text)throw new Error('source');" \
               "for(const id of data.radii)reject(()=>owner.set(id,-2));" \
               "owner.set(data.radii[0],2);owner.set(data.document.records[0].geometry.low[0][0],-5);" \
               "for(const document of data.malformed){reject(()=>owner.replace(document));reject(()=>owner.set(data.radii[0],-7));}" \
               "process.stdout.write(JSON.stringify({state:owner.state(),text:owner.export_text()}));"
        loader = "eval(require('fs').readFileSync(process.argv[1],'utf8')+'\\n'+process.argv[2]);"
        completed = subprocess.run([node, "-e", loader, str(script_path), code],
                                   input=json.dumps({"document": document, "radii": radii, "malformed": malformed, "texts": texts}),
                                   text=True, encoding="utf-8", capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        owner = PhysicsWorkspace(document)
        owner.set(radii[0], 2)
        owner.set(contacts(document)[0]["geometry"]["low"][0][0], -5)
        self.assertEqual(json.loads(completed.stdout), {"state": owner.state(), "text": owner.export_text()})

    def test_numeric_contacts_geometry_source_and_invalid_edits_match_python(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is unavailable for browser parity")
        texts = json.loads((common.ROOT / "locale/en/physics_workspace.json").read_text(encoding="utf-8"))
        cases = []
        expected = []
        for source, frames, weight in ((SOURCE, {NODE: FRAME}, 37.5), (SOURCE, {}, 100),
                                       ("[A]\n0,0,0,-1\n", {"A": IDENTITY}, 0),
                                       ("[A]\n0,0,0,3 & 1,0,0,1\n", {"A": IDENTITY}, 50),
                                       ("[A]\n0,0,0,1\n", {"A": {"source": "ragdoll", "matrix": IDENTITY}}, 0)):
            document = parse_document("cbpc", source)
            owner = PhysicsWorkspace(document)
            radius_id = contacts(document)[0]["geometry"]["low"][0][3]
            before = owner.state()
            with self.assertRaises(ValueError):
                owner.set(radius_id, -7)
            self.assertEqual(owner.state(), before)
            cases.append({"document": document, "frames": frames, "weight": weight, "radius": radius_id})
            expected.append({"state": owner.state(), "text": owner.export_text(),
                             "envelopes": owner.envelopes(frames, weight=weight, contact_segments=8)})
        script_path = common.ROOT / "web/js/physics_workspace.js"
        code = "\nconst data=JSON.parse(require('fs').readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(data.cases.map(item=>{" \
               "const owner=new PhysicsWorkspaceMirror(item.document,data.texts),before=JSON.stringify(owner.state());let rejected=false;" \
               "try{owner.set(item.radius,-7);}catch(error){rejected=true;}if(!rejected||JSON.stringify(owner.state())!==before)throw new Error('atomicity');" \
               "for(const weight of [-1,101,NaN,true,null]){let failed=false;try{owner.envelopes(item.frames,{weight});}catch(error){failed=true;}if(!failed)throw new Error('weight');}" \
               "return {state:owner.state(),text:owner.export_text(),envelopes:owner.envelopes(item.frames,{weight:item.weight,contact_segments:8})};})));"
        loader = "eval(require('fs').readFileSync(process.argv[1],'utf8')+'\\n'+process.argv[2]);"
        completed = subprocess.run([node, "-e", loader, str(script_path), code],
                                   input=json.dumps({"texts": texts, "cases": cases}),
                                   text=True, encoding="utf-8", capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        actual = json.loads(completed.stdout)

        def compare(a, b):
            if type(a) in (int, float) and type(b) in (int, float):
                self.assertAlmostEqual(a, b, places=10)
            elif isinstance(a, dict):
                self.assertEqual(set(a), set(b))
                for key in a:
                    compare(a[key], b[key])
            elif isinstance(a, list):
                self.assertEqual(len(a), len(b))
                for left, right in zip(a, b):
                    compare(left, right)
            else:
                self.assertEqual(a, b)

        compare(actual, expected)


if __name__ == "__main__":
    common.main()
