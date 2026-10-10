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

All routes below use GET. The default address is `http://127.0.0.1:8767`; the host and port
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
| `/api/shutdown` | Stop the server after returning the response |

Catalogue and payload requests can also supply `root=<folder>`. To open a mesh without TRI,
pass `all=1` to both the catalogue and the payload request, for example
`/api/payload?name=femalebody_1.nif&all=1`.
A payload request without
an open mesh returns an error. Opening a payload changes the server's selected mesh;
setting a root and shutting down are actions even though their routes use GET.

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

No browser is needed for these calls. JSON errors contain an `error` field and use HTTP
error status codes. A failed request must not be interpreted as an empty successful result.

## Scope

The current API supplies catalogue, environment and viewer payload operations. It does
not expose arbitrary `MorphBench` methods or NIF-writing commands. For numerical batch
analysis and new-file output, use the documented `mb.py` commands or the Python facade.
Sliders changed in the browser are not automatically a server-side batch recipe.

See [cli.md](cli.md) for computations, [building.md](building.md) for packaging and
[../CLAUDE.md](../CLAUDE.md) for implementation contracts.
