# HTTP automation

Russian: [http.ru.md](http.ru.md).

The running Morphbench server supports local HTTP requests. The same server is used by
the launcher and the browser viewer. Prefer these requests for repeated server operations;
use the UI to inspect the picture or for an operation not exposed by the API.

## Launch and environment

From the repository root:

```text
python mb.py serve --no-browser --root <mesh-folder>
```

To read a MO2 profile's merged Data, start the launcher or Python through MO2. A server
started outside MO2 cannot acquire that virtual view from an HTTP client. Before opening
meshes, check `insideMo2` and `dataRoot` in `/api/environment`. The launcher can be started
using the local MO2 bridge's documented `/run` operation with its registered executable name.
The bridge belongs to a separate project and has its own authentication and busy guard.

`serve` can attach to an existing server. Close an older instance before launching a new
version; the client must not assume the process on the same port comes from the new bundle.

## Supported routes

The following table uses GET. The default address is `http://127.0.0.1:8767`; the host and port
come from the settings. Source and protocol details are in `presenters/serve.py`.

| Route | Result |
|---|---|
| `/api/environment` | Environment and current root; `insideMo2` reports the server's virtual view |
| `/api/catalog?all=0&rescan=0` | Mesh entries with morphs; `all=1` includes entries without TRI, `rescan=1` refreshes the listing |
| `/api/payload?index=0` | Open the numbered catalogue entry and return its viewer payload |
| `/api/payload?name=<relative-path>` | Open an entry by catalogue name; URL-encode the path |
| `/api/payload` | Return the currently open mesh's payload |
| `/api/root` | Current root and mesh count |
| `/api/root?root=<folder>` | Set the browse root; under MO2 it must remain within the game's Data |
| `/api/workspace` | Current mode, capsule editor, physics document, nominal limits and exported configuration text |
| `/api/shutdown` | Stop the server after returning the response |

Catalogue and payload requests can also supply `root=<folder>`. To open a mesh without TRI,
pass `all=1` to both the catalogue and the payload request, for example
`/api/payload?name=femalebody_1.nif&all=1`.
A payload request without
an open mesh returns an error. Opening a payload changes the server's selected mesh;
setting a root and shutting down are actions even though their routes use GET.

## Workspace requests

These POST routes require UTF-8 JSON and `Content-Type: application/json`. Cross-origin
browser requests are rejected; local scripts can omit `Origin`. Input size, numeric-field
count and replay action count are bounded by the workspace settings.

| Route | JSON body | Result |
|---|---|---|
| `/api/physics/import` | `{"kind":"fsmp","text":"<system/>"}`; use `cbpc` for TXT | `{"document":...}`; parse only, without changing server state |
| `/api/workspace` | `{"actions":[{"method":"workspace_mode","args":["physics"]}]}` | Apply the bounded action batch and return workspace state |
| `/api/workspace/skeleton` | A `morphbench-workspace` version-1 recipe, including its `source` and `actions` | New skeleton NIF bytes as `application/octet-stream` |

Workspace state contains `workspace`, `colliders`, `physics`, `envelopes` and `text`.
It also includes `fileVisibility`: static native file evidence plus separate viewer/policy
inclusion. `respect_file_visibility(on,show_hidden=false)` is an allowlisted workspace action.
Unknown ancestry is never promoted to a confirmed file state; see [visibility](visibility.md).
`text` is the current source-preserving configuration export, or `null` before import.
Parsing does not install the document: replay `physics_replace` with the returned document,
then `physics_set` with an imported field ID and a finite number. Saved physics state retains
the original normalized `document` and an `edits` map for replay.

Allowed action methods are `workspace_mode`, `workspace_tab`, `physics_replace`, `physics_set`,
`collider_select`, `collider_set`, `collider_translate`, `collider_add`, `collider_remove` and
`collider_reset`. Every action has exactly `method` and an `args` array. A rejected batch leaves
the previous editable state intact. Mode names are `morphs`, `colliders`, `physics` and `slots`;
the [workspace guide](workspace.md) describes tabs, coordinate spaces and recipe examples.

Skeleton download verifies the original skeleton path/hash and its current bytes, then replays
the recipe on a copy. The endpoint returns bytes; it accepts no arbitrary output filesystem
path. Save the result to a new file. Unsupported shapes remain read-only.

For PPB, the same parser route accepts `{"kind":"ppb","text":"..."}`. Apply its normalized
document with `ppb_replace`; edit existing fields with `ppb_set(fieldId,value)`. Choose both
records explicitly for `ppb_to_collider(capsuleId,bone,index)` or
`ppb_from_collider(capsuleId,bone,index)`. These methods are also allowlisted batch actions.
`ppb_link(capsuleId,bone,index)` starts explicit bidirectional source editing; `ppb_unlink()`
ends it while retaining edits. The separate PPB state's `binding` is null or
`{capsule,bone,index}`. While linked, `ppb_set`, `collider_set` and `collider_translate` update
the linked geometry and source spans atomically. Linking copies source geometry into the
working capsule; it does not infer a runtime PPB match. Invalid edits preserve both owners.
`GET /api/workspace` includes separate `ppb` state and `ppbText` (null before import).
Importing PPB does not change the skeleton or the independent FSMP/CBPC document. Source-only
editing can run without a mesh. Capsule transfers require a loaded target rig; recipes bind
its path/hash. See [PPB scope](ppb.md); runtime overrides are not resolved.

## Example

```python
import json
from urllib.parse import urlencode
from urllib.request import ProxyHandler, build_opener

base = "http://127.0.0.1:8767"
client = build_opener(ProxyHandler({}))

def get(route):
    with client.open(base + route, timeout=60) as response:
        return json.load(response)

environment = get("/api/environment")
entries = get("/api/catalog")
payload = get("/api/payload?" + urlencode({"name": entries[0]["name"]}))
print(environment["insideMo2"], payload["summary"])
```

To import a configuration and install it into server state, using the same `client` and `base`:

```python
from pathlib import Path
from urllib.request import Request

def post(route, body):
    request = Request(base + route, method="POST",
                      data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json"})
    with client.open(request, timeout=60) as response:
        return json.load(response)

parsed = post("/api/physics/import", {
    "kind": "fsmp", "text": Path("physics.xml").read_bytes().decode("utf-8")})
state = post("/api/workspace", {"actions": [
    {"method": "physics_replace", "args": [parsed["document"]]},
    {"method": "workspace_mode", "args": ["physics"]}]})
print(state["physics"]["fields"], state["text"])
```

No browser is needed for these calls. JSON errors contain an `error` field and use HTTP
error status codes. A failed request must not be interpreted as an empty successful result.

## Scope

The API supplies catalogue, environment, viewer payload and bounded workspace operations;
it does not expose arbitrary `MorphBench` methods. Workspace browser edits stay local until
their recipe is submitted; GET does not collect unsent browser edits. Morph sliders changed
in the browser are not automatically a server-side batch recipe. Use `mb.py workspace` for
file-based replay and new-path exports.

FSMP overlays are nominal rest-frame limits, not motion simulation. Unresolved defaults,
inheritance and unsupported semantics withhold previews. CBPC returns raw parameters only;
its clamps are not final displacement or direct angular limits. See [workspace.md](workspace.md).

See [cli.md](cli.md) for computations, [building.md](building.md) for packaging and
[repository development guidance](https://github.com/Vhodnoylogin/morphbench/blob/main/CLAUDE.md)
for implementation contracts; these instructions are not bundled with the release.

## Local add-on packages (development)

API v1 on `feature/addons` includes these additive development routes:

| Request | Body | Result |
|---|---|---|
| `GET /api/addons` | — | `{apiVersion:1, addons:[...]}`; entries include opaque `generation` |
| `POST /api/addons/install` | Raw ZIP, `Content-Type: application/zip` | Installed entry, disabled; existing ID returns `alreadyInstalled` |
| `POST /api/addons/update` | Raw ZIP, `Content-Type: application/zip` | Replacement entry, disabled; manifest `id` selects an existing disabled target |
| `POST /api/addons/enabled` | JSON `{id,enabled}`, `Content-Type: application/json` | The updated list envelope |
| `GET /addon-assets/<id>/<generation>/<relative-file>` | — | Asset of the current enabled generation; old identity returns `staleGeneration` |
| `GET /addons/<id>/<relative-file>` | — | Legacy route to the current enabled package |

Update returns `notFound` for a missing manifest ID and `updateRequiresDisabled` for an
enabled target. Version labels are opaque and not ordered. Install/update use the configured
ZIP limits, validate before publication, and return package errors as `{error,code}` with a
failure HTTP status. A successful update creates a new generation but requires explicit
re-enabling. Registry v2 uses immutable generations and one atomic state pointer; previous
bytes remain without automated garbage collection. New binaries read legacy v1 registries;
older binaries reject v2. See [the registry and lifecycle contract](addons.md) for crash limits.

The root viewer binds frames and every SDK request to a generation. Re-enabling a replacement
does not authorize an old frame: it receives `staleGeneration` and closes on its next request.
Reload viewers retained across an update. The sandbox uses the [public browser SDK](addons.md)
for preview operations and `state.get`/`state.set`/`state.reset`; these state methods are SDK
messages, not HTTP routes. Their host-owned `sessionStorage` value is scoped to add-on ID and
browser tab/origin and survives model navigation/reload. It is separate from scene state,
performs no automatic replay and is not durable project storage.

Foreign-origin and iframe requests to the root page and server APIs are rejected, including
GET actions. Local CLI clients can omit `Origin`. Package CSP `connect-src 'none'` blocks all
fetch/XHR, including packaged JSON: use local classic JS data, HTML-embedded JSON or user-picked
files through File API. XML package assets are not allowed. The existing 0.8.0 archive does not
contain this add-on infrastructure.
