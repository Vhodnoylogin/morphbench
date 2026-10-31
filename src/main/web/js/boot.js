"use strict";

// ---- start-up ---------------------------------------------------------------------------------
if (DATA) {
  const summary = DATA.summary;
  document.getElementById("title").textContent = "morphbench";
  const subtitle = document.getElementById("subtitle");
  subtitle.textContent = DATA.names.nif || DATA.names.skeleton || (DATA.server ? T.chooseMesh : T.noMesh);
  subtitle.title = summary
    ? T.summaryMorphs + (DATA.names.tri ? DATA.names.tri + " (" + summary.triKind + ")" : T.noTri) +
      T.summaryShapes + summary.shapes + T.summaryVerts + summary.vertices +
      T.summaryBones + summary.bones + T.summarySliders + summary.morphs +
      (DATA.names.skeleton ? T.summarySkeleton + DATA.names.skeleton + T.summaryCapsules + summary.colliders : "")
    : (DATA.server ? T.chooseMesh : T.noMesh);
  try {
    window.mb = new App(DATA);
    if (summary && !DATA.shapes.some((shape) => shape.vertexCount && shape.triangles)
        && !(DATA.colliders && DATA.colliders.bodies.length)) {
      document.getElementById("hint").textContent = T.noRenderableGeometry;
    }
  } catch (e) {
    const box = document.getElementById("nogl");
    box.style.display = "flex";
    box.textContent = T.cannotStart + (e.message || e);
    console.error(e);
  }
}
