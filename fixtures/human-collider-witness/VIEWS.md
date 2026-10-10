# Open the witnesses in Morphbench

Owner-facing instructions: [VIEWS.ru.md](VIEWS.ru.md).

Both installed human witnesses use `meshes/test_morphbench_human/body/femalebody_1.nif`
at weight100. NPC base000806 uses the private control/skeleton_female.nif and
matching HKX; base000807 uses marker/skeleton_female.nif and matching HKX.
The neutral body has no TRI and the default morph-only catalog hides it. Selecting
the shared body alone also cannot choose these separately stored private skeletons.

Run `view.py --mod <installed-fixture-mod> --bench <Morphbench-folder>
--out <new-external-viewer-folder>` with the bundled Morphbench Python or an
equivalent environment. It verifies all7 installed fixture files against the
artifact manifest, then invokes standard Morphbench CLI web/colliders operations
with explicit body, skeleton and HKX inputs. It never fits, edits or transforms
the fixture and contains no separate geometry/parser implementation.

Open generated index.html for labelled control/marker comparison, or each
interactive control.html/marker.html separately. These are the stock Morphbench
viewer with capsules already enabled. Rotate, select front/side/back, focus on
bones and toggle layers as usual. Files remain usable after the main server is
closed; they snapshot selected installed inputs rather than claiming a MO2 VFS.
viewer-manifest.json pins inputs and generated pages; colliders.json retains
numerical results. Output belongs outside Git; recipe/docs stay in this test-only
fixture and are excluded from releases.

Compare the same in-game witnesses with trd at comparable front/side angles:
left thigh is on the viewer's right in a front view. Check anatomical attachment,
orientation and enlarged left envelope against the corresponding page. Record
animated-pose differences separately. An in-game image plus reported interaction
alone does not establish this comparison, exact dimensions or solver acceptance.
Old immutable orders and their pinned documents are unchanged.
