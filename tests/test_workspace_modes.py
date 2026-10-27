"""Workspace modes own their overlays; switching never leaks capsule visibility."""
import tempfile
import unittest
import common


class TestWorkspaceModes(unittest.TestCase):
    def test_switching_modes_separates_capsule_and_slots_layers(self):
        with tempfile.TemporaryDirectory() as temporary:
            bench = common.MorphBench(common.config(temporary))
            for mode in ("colliders", "morphs", "colliders", "physics", "colliders", "slots", "morphs"):
                state = bench.workspace_mode(mode)
                self.assertEqual(state["mode"], mode)
                self.assertEqual(bench.view.colliders, mode == "colliders")
                self.assertFalse(bench.view.bumper)
                self.assertEqual(bench._placements.mode, "slots" if mode == "slots" else "mesh")


if __name__ == "__main__":
    common.main()
