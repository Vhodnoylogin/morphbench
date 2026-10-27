"use strict";

// ---- start-up ---------------------------------------------------------------------------------
const summary = DATA.summary;
document.getElementById("title").textContent = "morphbench";
const subtitle = document.getElementById("subtitle");
subtitle.textContent = DATA.names.nif || (DATA.server ? T.chooseMesh : T.noMesh);
subtitle.title = summary
  ? T.summaryMorphs + (DATA.names.tri ? DATA.names.tri + " (" + summary.triKind + ")" : T.noTri) +
    T.summaryShapes + summary.shapes + T.summaryVerts + summary.vertices +
    T.summaryBones + summary.bones + T.summarySliders + summary.morphs +
    (DATA.names.skeleton ? T.summarySkeleton + DATA.names.skeleton + T.summaryCapsules + summary.colliders : "")
  : (DATA.server ? T.chooseMesh : T.noMesh);
try {
  window.mb = new App(DATA);
} catch (e) {
  const box = document.getElementById("nogl");
  box.style.display = "flex";
  box.textContent = T.cannotStart + (e.message || e);
  console.error(e);
}
