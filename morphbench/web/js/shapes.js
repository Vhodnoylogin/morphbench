"use strict";

// ---- the core's data, in the shape it was embedded into the page --------------------------
class Shape {
  constructor(raw) {
    this.name = raw.name;
    this.base = Codec.f32(raw.vertices);          // the vertices as they came, never touched
    this.pos = new Float32Array(this.base);        // the vertices with the sliders applied
    this.nrm = new Float32Array(this.base.length); // vertex normals over the deformed positions
    this.count = raw.vertexCount;
    this.tris = Codec.index(raw.triangles, raw.indexType);
    this.triCount = this.tris.length / 3;
    this.boneKey = Codec.i16(raw.boneKey);
    this.boneNames = raw.boneNames;
    this.heldBones = raw.heldBones;      // bones that hold vertices: they decide which capsules show
  }
}

class Deltas {
  // The offsets of one morph on one shape: vertex numbers and int16 vectors with one shared
  // multiplier.
  constructor(raw) {
    this.indices = Codec.index(raw.indices, raw.indexType);
    this.q = Codec.i16(raw.offsets);
    this.scale = raw.scale;
    this.count = raw.count;
  }
  applyTo(pos, amount) {
    const k = amount * this.scale, idx = this.indices, q = this.q;
    for (let i = 0, n = idx.length; i < n; i++) {
      const v = idx[i] * 3, j = i * 3;
      pos[v] += k * q[j]; pos[v + 1] += k * q[j + 1]; pos[v + 2] += k * q[j + 2];
    }
  }
  lengthsInto(out) {
    const idx = this.indices, q = this.q, k = this.scale;
    for (let i = 0, n = idx.length; i < n; i++) {
      const j = i * 3;
      out[idx[i]] = k * Math.sqrt(q[j] * q[j] + q[j + 1] * q[j + 1] + q[j + 2] * q[j + 2]);
    }
  }
}

class Strain {
  constructor(raw) {
    this.indices = Codec.index(raw.indices, raw.indexType);
    this.values = Codec.u8(raw.values);
    this.max = raw.max;
  }
  valuesInto(out) {
    const idx = this.indices, v = this.values, k = this.max / 255.0;
    for (let i = 0, n = idx.length; i < n; i++) out[idx[i]] = v[i] * k;
  }
}

// A chunk of collider geometry - the capsules of one bone, or the bumper - exactly as the
// facade's collider_meshes() and bumper_mesh() hand it over: already in world coordinates and
// without morphs, so the sliders never move it and its normals are computed once. The fields
// are the same as Shape's - the renderer does not care which of the two it got; `bone` is the
// bone the chunk hangs on (null for the bumper).
class ColliderMesh {
  constructor(name, raw, bone) {
    this.name = name;
    this.bone = bone === undefined ? null : bone;
    this.pos = Codec.f32(raw.vertices);
    this.count = raw.vertexCount;
    this.tris = Codec.index(raw.triangles, raw.indexType);
    this.triCount = this.tris.length / 3;
    this.nrm = vertexNormals(this.pos, this.tris, new Float32Array(this.pos.length));
  }
}
