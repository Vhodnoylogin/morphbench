# Browser add-ons

Russian: [addons.ru.md](addons.ru.md).

This document describes API **v1** on the development branch `feature/addons`. It is not a
feature of the existing 0.8.0 release archive. An add-on is a local HTML/JavaScript/CSS package
that adds an inspector tab to the server-backed viewer. The central model view stays visible.
Self-contained HTML exported by `mb.py web` does not activate add-ons.

V1 supports browser add-ons only. It has no Python imports, native plug-ins, backend hooks,
installer scripts, vertex editing API or game integration. A separate mod can maintain its own
add-on against the public interface without adding that mod's formats or calculations to Morphbench.

## Install, enable and disable

Use the viewer's add-on manager to upload a ZIP, inspect its metadata, and explicitly enable it.
Installation always leaves the package **disabled**. Enabled compatible packages have their own
inspector tabs. Selecting an add-on tab loads its entry page; disabling the active package in
that viewer unloads the frame and removes its tab. Closing an add-on tab's inspector does not
undo changes that it already made to the preview.

Package files and enabled state are per-machine data in the configured `addonDirectory`.
They are never bundled or versioned; the default source-checkout folder is Git-ignored.
An empty setting uses `addons` beside the active configuration file. An already installed ID
cannot be replaced in v1; a second installation with that ID returns `alreadyInstalled`.
Incompatible or damaged packages cannot be enabled.

The same operations are available without opening a mesh:

```text
python mb.py addons --json
python mb.py addons --install <package-folder>/scene-inspector.zip --json
python mb.py addons --enable scene-inspector --json
python mb.py addons --disable scene-inspector --json
```

For an existing local server:

| Request | Body | Result |
|---|---|---|
| `GET /api/addons` | — | `{apiVersion:1, addons:[...]}` |
| `POST /api/addons/install` | Raw ZIP bytes, `Content-Type: application/zip` | Installed package entry, initially disabled |
| `POST /api/addons/enabled` | JSON `{id:"scene-inspector", enabled:true}` | `{apiVersion:1, addons:[...]}` after the change |
| `GET /addons/<id>/<relative-file>` | — | A validated enabled package asset |
| `GET /web/addon-sdk.js` | — | The host's v1 browser SDK |

Enable/disable requests require `Content-Type: application/json`. Browser administration
requests must come from the host page; cross-origin requests are rejected. Local automation
clients can omit `Origin`, as with the [HTTP API](http.md). HTTP errors use a failure status
and `{error:"message"}`; package errors also carry `code:"machineCode"`. Do not interpret a failed request as an empty list.

An ordinary package entry contains its manifest fields plus `enabled` (boolean), `compatible`
(boolean), and `status` (`enabled` or `disabled`). Incompatible installed packages have
`status:"incompatible"`; invalid ones have `status:"invalid"`. Both carry an
`error:{code,message}` diagnostic. Treat `enabled` and `compatible` as separate conditions.

## Package format and limits

The ZIP must contain `addon.json` at its root, with the entry HTML and all other assets under
that same root. Do not ZIP the containing folder. The example manifest is:

```json
{
  "id": "scene-inspector",
  "name": "Scene inspector",
  "version": "1.0.0",
  "apiVersion": 1,
  "entry": "index.html",
  "description": "Neutral example of the Morphbench browser add-on API."
}
```

`id`, `name`, `version`, `apiVersion` and `entry` are required; `description` is optional.
Unknown manifest fields are rejected. IDs match `[a-z][a-z0-9-]{0,63}`. `name` and `version`
are nonempty strings; `apiVersion` is the integer `1`. The entry must name an included `.html`
file. Paths are relative, case-consistent, forward-slash paths. Absolute paths, `..`, backslashes,
links, encrypted ZIP members, duplicate/case-colliding paths and Windows-reserved names are rejected.
Allowed file extensions are `.html`, `.css`, `.js`, `.json`, `.svg`, `.png`, `.jpg` and `.jpeg`.

The `addonLimits` configuration object controls the following defaults:

| Key | Default | Meaning |
|---|---:|---|
| `maxArchiveBytes` | 16 MiB | Uploaded/compressed archive bytes |
| `maxFiles` | 256 | ZIP paths, including explicit and implicit directories |
| `maxFileBytes` | 4 MiB | Uncompressed bytes per file |
| `maxTotalBytes` | 16 MiB | Total uncompressed bytes |
| `maxCompressionRatio` | 200 | Maximum ratio per ZIP member |
| `maxManifestBytes` | 64 KiB | Manifest bytes |

The complete archive is validated before publication. Mutations take a nonblocking OS writer
lock; another CLI/server process gets `busy` instead of losing an enabled-state update. Package files and enabled state remain
separate from the mesh and skeleton inputs. Installation does not execute package code.

To pack the neutral example, run this from `examples/scene-inspector`, with an output folder
outside the repository:

```text
python -m zipfile -c <output-folder>/scene-inspector.zip addon.json index.html main.js style.css
```

Install that ZIP and then enable `scene-inspector`. The example can refresh a scene snapshot,
open a catalogued model, set an existing morph, reset morphs and select a view preset. Its labels
follow the host language. It has no external dependencies or off-machine requests.

## SDK and message protocol

Load the host SDK as a classic script before your own script:

```html
<script src="/web/addon-sdk.js" defer></script>
<script src="main.js" defer></script>
```

Use local external JS and CSS files; the host restricts scripts and assets to local package/SDK
resources and blocks network connections. There is no module import from Morphbench's core.
The public global has three methods:

```javascript
const host = await MorphbenchAddon.connect(); // host.info result
const scene = await MorphbenchAddon.request("scene.get");
const unsubscribe = MorphbenchAddon.on("scene.changed", ({ method }) => {
  // Debounce a fresh read; do not write back in response to every notification.
});
unsubscribe();
```

`connect()` returns a promise for `host.info`, caching a successful connection for the frame's
lifetime. `request(method, params={})` returns a promise for the method's result.
`on(event, handler)` calls the handler with the event's `data` and returns an unsubscribe function.
Each request has its own **10-second timeout**. Completion, errors and timeouts remove the
pending request and its timer. Rejected `Error` objects have a machine-readable `.code`.
Opening the example directly, outside a Morphbench frame, fails with `notConnected`.

The transport is `window.parent.postMessage(message, "*")`. The wildcard is needed because
the sandbox frame has an opaque origin. The SDK accepts messages only from `window.parent`,
checks the API version and matches each response's unique string ID to a pending request.
The host independently verifies the sending frame and the enabled package.

```javascript
// Request
{ type: "morphbench-addon:request", apiVersion: 1, id: "unique-id",
  method: "scene.geometry", params: { shape: "Body" } }
// Successful response
{ type: "morphbench-addon:response", apiVersion: 1, id: "unique-id", result: {} }
// Failed response
{ type: "morphbench-addon:response", apiVersion: 1, id: "unique-id",
  error: { code: "unknownShape", message: "..." } }
// Notification
{ type: "morphbench-addon:event", apiVersion: 1,
  event: "scene.changed", data: { method: "..." } }
```

`scene.changed` announces a host preview operation. Its `method` string identifies the operation
for diagnostics; it is not a replay recipe. Notifications have no request ID. Reads do not mutate
the scene. Debounce reads and keep them separate from mutations to avoid feedback loops. A model
change replaces the page and frame, so reconnect and read state after loading.

## API v1

Only the parameters listed below are accepted. `params` must be an object, including for reads.
Unknown parameters, invalid numeric types, nonfinite numbers and invalid batches are rejected
before changing the preview. A zero morph value removes that name from the nonzero values map.

| Method | Parameters | Result |
|---|---|---|
| `host.info` | `{}` | `{apiVersion:1, addon:{id,name,version}, capabilities:[methodName,...], language:"en"\|"ru", scope:"browser-session"}` |
| `models.list` | `{}` | `{root:string\|null, entries:[catalogEntry,...]}`; includes models without TRI |
| `models.open` | `{name:catalogRelativeName}` | `{navigating:true}`, then the current viewer reloads |
| `morphs.get` | `{}` | `{names:[string,...], values:{name:nonzeroNumber,...}}` |
| `morphs.set` | `{values:{name:finiteNumber,...}}` | The same shape as `morphs.get` after merging the complete batch |
| `morphs.reset` | `{}` | The same shape as `morphs.get`, with `values:{}` |
| `scene.get` | `{}` | Scene snapshot described below |
| `scene.geometry` | `{shape:existingShapeName}` | Geometry snapshot described below |
| `view.get` | `{}` | `{state:viewState, presets:{presetName:[yaw,pitch],...}}` |
| `view.set` | Optional `{preset,yaw,pitch,zoom,pan,visibleShapes}` | The same shape as `view.get` after applying validated changes |

`capabilities` lists the methods supported by the connected host. Catalogue entries have
`name`, `nif`, `tri` (nullable), `kind` (nullable), `folder`, `file` and `index`. Pass the exact
`name` from `models.list` to `models.open`; arbitrary filesystem paths are not accepted.
The response is emitted before navigation. Model selection retains the active add-on and uses
the full catalogue (`all=1`). It resets unsaved morph, view and workspace preview changes exactly
like normal model selection. Save work through the host's usual controls before switching models.

Morph names must already exist in `names`; v1 does not author morphs. `morphs.set` merges rather
than replacing other slider values. If any name or value is invalid, none of that batch applies.
With no loaded morphs, `morphs.get` returns empty names and values.

`view.set` accepts an existing preset name; finite `yaw` and `pitch` in degrees; positive finite
`zoom`; `pan:[x,y]` containing two finite float32-representable numbers; and `visibleShapes:[name,...]` containing existing
shape names. `visibleShapes` replaces the viewer's selected shapes, and `[]` hides all of them.
Native file-visibility policy remains a separate state. A preset applies first, then supplied
angles override its angles; an omitted angle keeps the current/preset angle. Existing camera
normalization and limits apply, so read the returned state. The entire request is validated first.

`state` contains precise numeric camera values: `yaw`, `pitch`, `preset` (nullable), `zoom`,
`pan`, `colouring`, `highlightMorph`, `visible` (null means all selected),
`respectFileVisibility`, `showFileHidden`, `colliders`, `bumper`, `width`, `height`, `light`
and nullable `focus`. `light` contains `follow`, `direction`, `cameraDirection`, `worldDirection`,
`ambient`, `diffuse` and `fill`; a focus contains `name`, `centre` and `radius`. Numeric view data
is not rounded for display. V1 only allows the view setters listed above.

`scene.get` returns:

```javascript
{
  open: true,
  names: { nif: "body.nif", tri: "body.tri", skeleton: "skeleton.nif", ragdoll: null },
  summary: { /* normal Morphbench summary */ },
  shapes: [{ name: "Body", vertices: 100, triangles: 160, visible: true }],
  workspace: { mode: "morphs", tab: "sliders", tabs: [/* available tabs */] },
  colliders: { /* capsule editor snapshot */ },
  fileVisibility: { /* native evidence plus separate viewer/policy inclusion */ }
}
```

File names are nullable basenames; the summary can include source paths. `summary` contains
`nif`, `tri`, `triKind`, `shapes`, `vertices`, `bones`, `morphs`, `skeleton`, `colliders`, `ragdoll`
and `bounds:{min,max}`. It describes the opened sources, not a game observation. A shape's
`visible` reports inclusion under current viewer and native-file visibility policy. With no
mesh, `open:false`, `summary:null` and `shapes:[]` remain valid.

`workspace` describes the current mode/tab. `colliders` is the capsule editor payload, including
availability, body-local geometry, selected capsule, supported/editable flags, edits/original
capsules and distinct `bodyMatrices`/`nodeMatrices` when available. It is a read snapshot;
v1 has no capsule-writing method. See [workspace.md](workspace.md) for frame semantics and
[visibility.md](visibility.md) for the native evidence in `fileVisibility`. These snapshots
do not resolve game overrides or simulate physics.

`scene.geometry` returns:

```javascript
{
  name: "Body", space: "model",
  vertices: [/* x0,y0,z0,x1,y1,z1,... after current morphs */],
  baseVertices: [/* x0,y0,z0,... at rest */],
  triangles: [/* i0,i1,i2,... zero-based vertex indices */],
  boneNames: [/* bone names used by this shape */]
}
```

Arrays are detached copies. Changing them changes only the add-on's copy. Positions are in
model space, in game units; they do not include the view camera transform. Capsules have a
different, explicitly body-local frame; do not compare their endpoints directly with model-space
vertices. Use the appropriate snapshot matrices when converting frames. Geometry has the browser
payload's precision: its morph deltas are int16-quantized. It is not a promise of bit-for-bit
agreement with original floating-point source calculations or runtime skinning.

Host error codes include `invalidParams`, `unknownMethod`, `serverRequired`, `noMesh`,
`unknownShape` and `incompatibleApi`. Registry/disabled-package failures can supply additional
codes. SDK transport failures include `timeout`, `notConnected`, `disconnected` and
`invalidResponse`. Display error messages with `textContent`, not HTML interpolation.

## Isolation and lifecycle

The inspector runs in an iframe with `sandbox="allow-scripts"`, without `allow-same-origin`.
It cannot access the host's DOM or import its internal objects. The supported public interface
is the SDK and versioned protocol above; internal viewer classes, DOM structure and render
buffers are not an add-on API. No credentials, arbitrary filesystem access or server execution
are supplied through v1.

This is trust isolation, **not a malware sandbox**. An enabled package executes JavaScript and
can request the permitted preview mutations and read exposed source metadata/geometry. Install
packages whose source you trust. The CSP blocks external network access and iframe navigation
features are restricted, but no promise is made to contain browser vulnerabilities, resource
exhaustion or malicious computation.

Disable unloads the active frame in the viewer where the action occurs. Every later SDK request
is checked against the registry's current enabled/compatible state. Disabling does not rewind
completed edits or guarantee that JavaScript already running in another open viewer instantly
stops; close/reload those viewers to end their frames. Frame recreation resets the add-on's own
in-memory state. Browser preview changes do not automatically become server, disk or game state.
No result from an add-on establishes runtime contact, physics, culling or visual quality in Skyrim.
