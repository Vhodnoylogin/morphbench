"""Lossless configuration edits and truthful nominal geometry on synthetic documents only."""
import copy
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

from morphbench.physics_workspace import PhysicsWorkspace  # noqa: E402
from presenters.physics_document import parse_document  # noqa: E402


XML = '''\ufeff<?xml version="1.0" encoding="UTF-8"?>\r
<system>\r
  <!-- custom 😀 комментарий: 999, <!DOCTYPE is only text -->\r
  <bone name="Anchor"><mass>0</mass></bone>\r
  <bone name="Tip"><mass>  1.250e+0  </mass><opaque value='4.5'>retain me</opaque></bone>\r
  <generic-constraint bodyA="Tip" bodyB="Anchor">\r
    <frameInB><origin x="1" y="2" z="3"/><basis x="0" y="0" z="0" w="2"/></frameInB>\r
    <linearLowerLimit x="-1" y="0" z="1"/>\r
    <linearUpperLimit x="2" y="0" z="-1"/>\r
    <angularLowerLimit x="0" y="0" z="-0.5"/>\r
    <angularUpperLimit x="0" y="0" z="0.5"/>\r
    <unknown flag="yes"><literal>unparsed &amp; safe</literal></unknown>\r
  </generic-constraint>\r
</system>\r
'''
CBPC = '''# 😀 custom file, 999 is a comment\r
[ConfigMap]\r
NPC Ear1=ClawEar=IsRace(123)\r
[Options]\r
TuningMode = 0 # keep\r
ClawEar.Xmaxoffset 0.35 0.50 # weight endpoints\r
ClawEar.Xminoffset -0.35 -0.50\r
ClawEar.linearX 1.0\r
unknown text remains verbatim\r
[NPC Ear1]\r
1,2,3,0.5 & 4,5,6,0.5 | 7,8,9,0.7 & 1,2,3,0.7 # shape\r
[NPC Ear1]\r
0,0,0,1\r
'''
FRAME = [[0, -2, 0, 10], [2, 0, 0, 20], [0, 0, 2, 30], [0, 0, 0, 1]]


def find(document, label):
    return next(field for field in document["fields"] if field["label"] == label)


class TestLosslessDocuments(unittest.TestCase):
    def test_unchanged_xml_and_cbpc_preserve_all_characters(self):
        for kind, text in (("fsmp", XML), ("cbpc", CBPC)):
            with self.subTest(kind=kind):
                owner = PhysicsWorkspace(parse_document(kind, text))
                self.assertEqual(owner.export_text().encode("utf-8"), text.encode("utf-8"))
                self.assertFalse(owner.state()["dirty"])
                json.dumps(owner.state(), allow_nan=False)

    def test_one_edit_replaces_only_the_numeric_span(self):
        document = parse_document("fsmp", XML)
        mass = next(field for field in document["fields"] if field["label"] == "mass" and field["value"] > 0)
        owner = PhysicsWorkspace(document)
        owner.set(mass["id"], 2.75)
        self.assertEqual(owner.export_text(), XML[:mass["start"]] + "2.75" + XML[mass["end"]:])
        self.assertEqual(owner.state()["document"], document)
        self.assertEqual(owner.state()["edits"], {mass["id"]: 2.75})
        owner.set(mass["id"], mass["value"])
        self.assertEqual(owner.export_text(), XML)
        self.assertFalse(owner.state()["dirty"])

    def test_multiple_different_length_edits_keep_original_positions(self):
        document = parse_document("fsmp", XML)
        owner = PhysicsWorkspace(document)
        selected = document["fields"][::4]
        expected = XML
        for field in selected:
            owner.set(field["id"], 100.25)
        for field in reversed(selected):
            expected = expected[:field["start"]] + "100.25" + expected[field["end"]:]
        self.assertEqual(owner.export_text(), expected)
        reparsed = parse_document("fsmp", owner.export_text())
        self.assertEqual(len(reparsed["fields"]), len(document["fields"]))

    def test_cbpc_conditions_names_comments_and_unknown_lines_survive(self):
        document = parse_document("cbpc", CBPC)
        owner = PhysicsWorkspace(document)
        self.assertFalse(any("123" == CBPC[field["start"]:field["end"]] for field in document["fields"]))
        clamp = find(document, "Xmaxoffset")
        owner.set(clamp["id"], 0.4)
        self.assertEqual(owner.export_text(), CBPC[:clamp["start"]] + "0.4" + CBPC[clamp["end"]:])
        envelope = owner.envelopes({"NPC Ear1": FRAME})
        self.assertFalse(envelope["lines"])
        self.assertTrue(all(row["type"] == "raw" for row in envelope["records"]))
        self.assertTrue(any(row["code"] == "cbpc_raw" for row in envelope["warnings"]))
        groups = [group["id"] for group in document["groups"] if group["label"] == "NPC Ear1"]
        self.assertEqual(len(groups), 2)
        self.assertNotEqual(groups[0], groups[1])

    def test_invalid_edits_are_atomic_and_reads_are_copies(self):
        owner = PhysicsWorkspace(parse_document("fsmp", XML))
        before = owner.state()
        for value in (float("nan"), float("inf"), -float("inf"), "2", True, None, 10 ** 500):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                owner.set("f0", value)
            self.assertEqual(owner.state(), before)
        with self.assertRaises(ValueError):
            owner.set("absent", 2)
        before["fields"][0]["value"] = 999
        self.assertNotEqual(before, owner.state())
        self.assertEqual(owner.export_text(), XML)

    def test_invalid_replace_is_atomic(self):
        owner = PhysicsWorkspace(parse_document("fsmp", XML))
        before = owner.state()
        for mutation in (lambda doc: doc["fields"].append(copy.deepcopy(doc["fields"][0])),
                         lambda doc: doc["fields"][0].update(start=-1),
                         lambda doc: doc["fields"][0].update(value=999),
                         lambda doc: doc["records"].append("invalid")):
            document = copy.deepcopy(before["document"])
            mutation(document)
            with self.assertRaises(ValueError):
                owner.replace(document)
            self.assertEqual(owner.state(), before)

    def test_malformed_xml_and_entity_declarations_are_rejected(self):
        for source in ("<system><bone></system>", "<!DOCTYPE x [<!ENTITY e '1'>]><x>&e;</x>",
                       "<!DOCTYPE x SYSTEM 'file:///C:/private.txt'><x/>"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                parse_document("xml", source)

    def test_numeric_entities_and_string_identifiers_are_never_rewritten(self):
        source = '<system><bone name="123"><mass>&#49;</mass><tag>1</tag></bone></system>'
        document = parse_document("fsmp", source)
        self.assertFalse(any(field["label"] in ("bone.name", "mass") for field in document["fields"]))
        tag = find(document, "tag")
        owner = PhysicsWorkspace(document)
        with self.assertRaises(ValueError):
            owner.set(tag["id"], 2)
        self.assertEqual(owner.export_text(), source)

    def test_resource_limits_are_explicit(self):
        with self.assertRaises(ValueError):
            parse_document("fsmp", XML, max_chars=len(XML) - 1)
        with self.assertRaises(ValueError):
            parse_document("fsmp", XML, max_fields=1)
        with self.assertRaises(ValueError):
            PhysicsWorkspace(parse_document("fsmp", XML), max_chars=100)

    def test_numeric_text_vectors_and_nonfinite_values(self):
        source = '<system><custom xyz="NaN">1, 2e-3, -4</custom><mass>Inf</mass></system>'
        document = parse_document("fsmp", source)
        self.assertEqual([field["value"] for field in document["fields"]], [1, 0.002, -4])
        self.assertEqual(len([row for row in document["warnings"] if row["code"] == "nonfinite"]), 2)
        self.assertEqual(PhysicsWorkspace(document).export_text(), source)


class TestConfiguredGeometry(unittest.TestCase):
    def test_frame_quaternion_uniform_scale_and_inverted_axis(self):
        owner = PhysicsWorkspace(parse_document("fsmp", XML))
        result = owner.envelopes({"Anchor": FRAME}, angular_segments=4)
        row = result["records"][0]
        self.assertEqual(row["world_origin"], [6, 22, 36])
        self.assertEqual([axis["status"] for axis in row["linear"]], ["limited", "locked", "unconstrained"])
        xline = next(line for line in result["lines"] if line["kind"] == "linear_axis" and line["axis"] == "x")
        self.assertEqual(xline["a"], [6, 20, 36])
        self.assertEqual(xline["b"], [6, 26, 36])
        self.assertFalse(any(line["kind"] == "linear_box" for line in result["lines"]))
        arcs = [line for line in result["lines"] if line["kind"] == "angular_glyph" and line["axis"] == "z"]
        self.assertEqual(len(arcs), 4)
        self.assertAlmostEqual(arcs[0]["a"][0], 6 + 2 * math.sin(0.5))
        self.assertAlmostEqual(arcs[0]["a"][1], 22 + 2 * math.cos(0.5))
        json.dumps(result, allow_nan=False)

    def test_edited_limits_drive_geometry_without_reparsing(self):
        document = parse_document("fsmp", XML)
        owner = PhysicsWorkspace(document)
        owner.set(find(document, "linearUpperLimit.x")["id"], 4)
        result = owner.envelopes({"Anchor": FRAME})
        xline = next(line for line in result["lines"] if line["kind"] == "linear_axis" and line["axis"] == "x")
        self.assertEqual(xline["b"], [6, 30, 36])

    def test_default_frame_and_missing_range_are_not_invented(self):
        source = '<system><generic-constraint bodyA="A" bodyB="B"><linearLowerLimit x="0" y="0" z="0"/></generic-constraint></system>'
        result = PhysicsWorkspace(parse_document("fsmp", source)).envelopes({"B": FRAME})
        self.assertFalse(result["lines"])
        self.assertEqual(result["records"][0]["world_origin"], [10, 20, 30])
        self.assertIsNone(result["records"][0]["linear"])
        self.assertTrue(any(item["code"] == "missing_limits" for item in result["warnings"]))

    def test_inheritance_and_unsupported_frame_semantics_withhold_geometry(self):
        sources = (XML.replace('<bone name="Anchor">', '<bone name="Anchor" extends="base">'),
                   XML.replace("frameInB", "frameInLerp"), XML.replace("<frameInB>", '<frameInB frameRef="A">'))
        for source in sources:
            with self.subTest(source=source[:50]):
                result = PhysicsWorkspace(parse_document("fsmp", source)).envelopes({"Anchor": FRAME})
                self.assertFalse(result["lines"])
                self.assertTrue(result["warnings"])

    def test_missing_sheared_reflected_and_nonfinite_frames_are_withheld(self):
        bad_frames = ({}, {"Anchor": [[1, 1, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]},
                      {"Anchor": [[-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]},
                      {"Anchor": [[float("nan"), 0, 0, 0]]})
        for frames in bad_frames:
            result = PhysicsWorkspace(parse_document("fsmp", XML)).envelopes(frames)
            self.assertFalse(result["lines"])
            self.assertTrue(any(item["code"] == "missing_frame" for item in result["warnings"]))

    def test_overflow_source_numbers_remain_opaque(self):
        source = XML.replace('linearUpperLimit x="2"', 'linearUpperLimit x="1e999"')
        document = parse_document("fsmp", source)
        self.assertTrue(any(item["code"] == "nonfinite" for item in document["warnings"]))
        owner = PhysicsWorkspace(document)
        self.assertEqual(owner.export_text(), source)
        self.assertIsNone(owner.envelopes({"Anchor": FRAME})["records"][0]["linear"])

    def test_unsupported_constraint_is_visible_and_preserved(self):
        source = '<system><cone-twist-constraint bodyA="A" bodyB="B"><limit x="1"/></cone-twist-constraint></system>'
        owner = PhysicsWorkspace(parse_document("fsmp", source))
        result = owner.envelopes({"B": FRAME})
        self.assertEqual(owner.export_text(), source)
        self.assertFalse(result["lines"])
        self.assertEqual(result["records"][0]["type"], "raw")
        self.assertEqual(result["warnings"][0]["code"], "unsupported_constraint")


class TestBrowserMirror(unittest.TestCase):
    def test_owner_export_and_geometry_match_python(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is unavailable for the optional browser parity check")
        root = Path(__file__).resolve().parent.parent
        script = (root / "web/js/physics_workspace.js").read_text(encoding="utf-8")
        texts = json.loads((root / "locale/en/physics_workspace.json").read_text(encoding="utf-8"))
        document = parse_document("fsmp", XML)
        owner = PhysicsWorkspace(document)
        edits = [(document["fields"][index]["id"], value) for index, value in enumerate((1e-7, 1e20, 1e-6, 1e21, -0.0))]
        for ident, value in edits:
            owner.set(ident, value)
        payload = json.dumps({"document": document, "edits": edits, "frames": {"Anchor": FRAME}, "texts": texts})
        code = script + "\nconst data=JSON.parse(process.argv[1]);const owner=new PhysicsWorkspaceMirror(data.document,data.texts);" \
               "for(const [id,value] of data.edits)owner.set(id,value);" \
               "const before=JSON.stringify(owner.state());let rejected=0;" \
               "for(const value of [NaN,Infinity,'2',true,null]){try{owner.set('f0',value);}catch(error){rejected++;}}" \
               "if(rejected!==5||JSON.stringify(owner.state())!==before)throw new Error('atomicity');" \
               "process.stdout.write(JSON.stringify({state:owner.state(),text:owner.export_text(),envelopes:owner.envelopes(data.frames,{angular_segments:4})}));"
        completed = subprocess.run([node, "-e", code, payload], text=True, encoding="utf-8", capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["state"], owner.state())
        self.assertEqual(result["text"], owner.export_text())
        expected = owner.envelopes({"Anchor": FRAME}, angular_segments=4)
        self.assertEqual(result["envelopes"]["records"], expected["records"])
        self.assertEqual(result["envelopes"]["warnings"], expected["warnings"])
        for browser, python in zip(result["envelopes"]["lines"], expected["lines"]):
            self.assertEqual(browser["kind"], python["kind"])
            for key in ("a", "b"):
                for a, b in zip(browser[key], python[key]):
                    self.assertAlmostEqual(a, b, places=10)
        self.assertEqual(len(result["envelopes"]["lines"]), len(expected["lines"]))


if __name__ == "__main__":
    common.main()
