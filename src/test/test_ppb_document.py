"""PPB source edits preserve opaque bytes and never infer provider runtime state."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

from morphbench.physics_workspace import PhysicsWorkspace  # noqa: E402
from presenters.ppb_document import parse_document, SLOT_CHILDREN, UPSTREAM_COMMIT  # noqa: E402


def block(slot="Fore", suffix="", *, radius="2.500", enable="1", newline="\r\n"):
    values = {"Enable": enable, "AX": "+1.25e+0", "AY": "-2.0", "AZ": "3",
              "BX": "4", "BY": "5", "BZ": ".625", "R": radius}
    return "".join("cap%s%s%s %s%s" % (slot, suffix, key, value, newline)
                   for key, value in values.items())


def first(document, parameter):
    return next(field for field in document["fields"] if field["parameter"] == parameter)


def codes(document):
    return {warning["code"] for warning in document["warnings"]}


class TestPPBSourceAdapter(unittest.TestCase):
    def test_unchanged_source_and_single_span_edit_preserve_exact_utf8(self):
        text = ("\ufeff# opaque 😀 comment 987\r\n; preserved; 42\r\n"
                "[not a PPB scope]\r\nunknown_name   20 and some text\r\n" + block() +
                "npcCap Example.esp:123 0 1 2 3 4 5 6 7\r\n")
        document = parse_document(text)
        owner = PhysicsWorkspace(document)
        self.assertEqual(owner.export_text().encode("utf-8"), text.encode("utf-8"))
        field = first(document, "AX")
        self.assertEqual(text[field["start"]:field["end"]], "+1.25e+0")
        owner.set(field["id"], -123.75)
        self.assertEqual(owner.export_text(), text[:field["start"]] + "-123.75" + text[field["end"]:])
        self.assertEqual(document["fields"][0]["line"], 5)
        json.dumps(owner.state(), allow_nan=False)

    def test_only_reviewed_capsule_keys_have_editable_numeric_spans(self):
        opaque = ("# capForeAX 123\n ; capForeAX 456\ncapMirrorL 1\ncapAutoFit 0\n"
                  "bodyScale 1.1\npivWristX 2\nnpcCap plugin:123 0 1 2 3 4 5 6 7\n"
                  "capTailAX 2\ncapHeadC0R 2\ncapHeadC01R 2\ncapHeadC35R 2\n"
                  "capheadAX 9\nCapHeadAX 9\ncapForeAX=3\n")
        document = parse_document(opaque)
        self.assertEqual(document["fields"], [])
        self.assertEqual(document["capsules"], [])
        self.assertEqual(set(document["controls"]), {"capMirrorL", "capAutoFit"})
        self.assertFalse(document["controls"]["capMirrorL"]["editable"])
        self.assertIn("ppb_unsupported_key", codes(document))
        self.assertIn("ppb_mirror", codes(document))
        self.assertIn("ppb_autofit", codes(document))

    def test_duplicates_across_headers_are_global_last_successful_assignment(self):
        text = block() + "[ignored heading]\ncapForeAX 9.25 # last assignment\ncapForeAX = 50\n"
        document = parse_document(text)
        cap = document["capsules"][0]
        active = cap["fields"]["AX"]
        earlier, later = [field for field in document["fields"] if field["parameter"] == "AX"]
        self.assertEqual(active, later["id"])
        self.assertEqual(later["value"], 9.25)
        self.assertFalse(earlier["active"])
        self.assertEqual(earlier["superseded_by"], later["id"])
        self.assertTrue(later["active"])
        self.assertEqual(cap["occurrences"]["AX"], [earlier["id"], later["id"]])
        self.assertIn("ppb_last_wins", codes(document))
        self.assertIn("ppb_malformed", codes(document))
        self.assertFalse(cap["transfer_supported"])

    def test_known_duplicates_retain_a_complete_manual_transfer(self):
        document = parse_document(block() + "capForeR 3\n")
        cap = document["capsules"][0]
        self.assertTrue(cap["transfer_supported"])
        self.assertEqual(cap["geometry"]["radius"], document["fields"][-1]["id"])

    def test_no_defaults_are_inferred_for_missing_fields_or_enable(self):
        document = parse_document("capForeAX 1\ncapForeR 2\n")
        cap = document["capsules"][0]
        self.assertEqual(cap["geometry"]["p1"], ["f0", None, None])
        self.assertIsNone(cap["geometry"]["enabled"])
        self.assertFalse(cap["complete"])
        self.assertFalse(cap["transfer_supported"])
        self.assertEqual(set(cap["missing"]), {"Enable", "AY", "AZ", "BX", "BY", "BZ"})
        self.assertIn("ppb_incomplete", codes(document))

    def test_geometry_metadata_uses_field_ids_and_body_local_game_units(self):
        document = parse_document(block("Thigh", "C2", enable="0"))
        cap = document["capsules"][0]
        self.assertEqual(cap["slot"], "Thigh")
        self.assertEqual(cap["index"], 2)
        self.assertEqual(cap["child_index"], 2)
        self.assertEqual(cap["frame"], "body-local")
        self.assertEqual(cap["units"], "game_units")
        self.assertEqual(cap["geometry"], {"p1": ["f1", "f2", "f3"], "p2": ["f4", "f5", "f6"],
                                           "radius": "f7", "enabled": "f0"})
        self.assertTrue(cap["transfer_supported"])
        self.assertFalse(cap["runtime_resolved"])
        self.assertFalse(document["runtime_resolved"])
        self.assertTrue(cap["mirror"]["paired"])
        self.assertEqual(cap["mirror"]["axis"], "x")
        self.assertEqual(document["provenance"]["commit"], UPSTREAM_COMMIT)

    def test_hand_list_offset_is_explicit_and_main_is_single_shape_only(self):
        document = parse_document(block("Hand") + block("Hand", "C1") + block("Hand", "C7"))
        main, first_child, last_child = document["capsules"]
        self.assertEqual(main["shape_scope"], "single")
        self.assertEqual(first_child["index"], 1)
        self.assertEqual(first_child["child_index"], 0)
        self.assertEqual(last_child["child_index"], 6)
        self.assertIn("ppb_hand_index", codes(document))

    def test_all_reviewed_slot_bounds_and_center_mirror_metadata(self):
        for slot, upper in SLOT_CHILDREN.items():
            with self.subTest(slot=slot):
                document = parse_document(block(slot, "C%d" % upper) + block(slot, "C%d" % (upper + 1)))
                self.assertEqual(len(document["capsules"]), 1)
                cap = document["capsules"][0]
                self.assertTrue(cap["transfer_supported"])
                self.assertEqual(cap["index"], upper)
                self.assertIn("ppb_unsupported_key", codes(document))
        self.assertFalse(parse_document(block("Head"))["capsules"][0]["mirror"]["paired"])

    def test_numeric_subset_preserves_trailing_comments_and_opaque_tail(self):
        text = "capForeAX 1.5#comment\ncapForeAY -2;comment\ncapForeAZ 3 opaque retained\n"
        document = parse_document(text)
        self.assertEqual([field["value"] for field in document["fields"]], [1.5, -2, 3])
        for field in document["fields"]:
            self.assertEqual(float(text[field["start"]:field["end"]]), field["value"])

    def test_nonfinite_overflow_partial_numbers_and_bad_exponents_stay_opaque(self):
        for value in ("nan", "Inf", "-infinity", "1e999", "3.5e38", "1e-100", "1foo", "1e", "1e+", "0x10"):
            with self.subTest(value=value):
                text = "capForeAX " + value + "\n"
                document = parse_document(text)
                self.assertEqual(document["fields"], [])
                self.assertFalse(document["capsules"][0]["transfer_supported"])
                self.assertIn("ppb_malformed", codes(document))
                self.assertEqual(document["text"], text)

    def test_nonpositive_radius_does_not_offer_geometry_transfer(self):
        for radius in ("0", "-1"):
            with self.subTest(radius=radius):
                document = parse_document(block(radius=radius))
                self.assertFalse(document["capsules"][0]["transfer_supported"])
                self.assertTrue(document["capsules"][0]["geometry_supported"])
                self.assertIn("ppb_nonpositive_radius", codes(document))
                self.assertEqual(len(document["fields"]), 8)

    def test_bom_is_preserved_but_first_command_is_not_marked_active(self):
        text = "\ufeff" + block()
        document = parse_document(text)
        self.assertEqual(len(document["fields"]), 7)
        self.assertIn("Enable", document["capsules"][0]["missing"])
        self.assertIn("ppb_bom", codes(document))
        self.assertEqual(PhysicsWorkspace(document).export_text(), text)

    def test_only_lf_delimits_commands_as_in_provider_getline(self):
        text = "unknown 1\vcapForeAX 55\u2028capForeAY 99\ncapForeAZ 3\r\n"
        document = parse_document(text)
        self.assertEqual([field["key"] for field in document["fields"]], ["capForeAZ"])
        self.assertEqual(document["fields"][0]["line"], 2)

    def test_resource_limits_reject_invalid_inputs_and_excess_fields(self):
        for text, kwargs in ((None, {}), ("x", {"max_chars": 0}), ("x", {"max_fields": True}),
                             ("xx", {"max_chars": 1}), (block(), {"max_fields": 7})):
            with self.subTest(text=text, kwargs=kwargs), self.assertRaises(ValueError):
                parse_document(text, **kwargs)

    def test_reparse_after_multiple_length_changes_updates_source_spans(self):
        text = block(newline="\n") + "# retain final comment without newline"
        document = parse_document(text)
        owner = PhysicsWorkspace(document)
        owner.set(first(document, "AX")["id"], 100.125)
        owner.set(first(document, "R")["id"], 7)
        exported = owner.export_text()
        reparsed = parse_document(exported)
        self.assertEqual(first(reparsed, "AX")["value"], 100.125)
        self.assertEqual(first(reparsed, "R")["value"], 7)
        self.assertTrue(exported.endswith("# retain final comment without newline"))
        self.assertEqual(PhysicsWorkspace(reparsed).export_text(), exported)


if __name__ == "__main__":
    unittest.main()
