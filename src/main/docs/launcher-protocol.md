# Launcher and Application compatibility

Launcher v3 is a fixed Windows-to-Python handoff: one class and two
methods (entry point and Windows argument quoting). Application owns the window,
discovery, settings, translations, diagnostics and server lifetime. Released v1/v2
adapters remain supported; their native bytes are not changed.

## Minimal native host protocol 1 (Launcher v3)

Only `python/python.exe` and `mb.py`, relative to the EXE, are native anchors. The
host opens these files (MO2-safe), then starts without shell, console or redirected pipes:

```text
<launcher>/python/python.exe -I <launcher>/mb.py --launcher-host 1 --native-parent <PID> -- <original argv>
```

Every original argument, including empty values and future options, passes unchanged.
Caller cwd and environment reach the shim. C# interprets no App option or setting,
uses no PATH/registry discovery, reads no JSON and implements no HTTP client. It waits
for Python to preserve MO2 running-program accounting and returns the child's exit code.
Only failure before Python starts has a small native error dialog. The replaceable shim
and Application report later failures.

After discovering App using caller cwd/home hints, the shim restores the legacy launcher
working directory: relative plugin/library settings keep their meaning. App config stays
in App; `morphbench.launcher.json` and diagnostic output keep their launcher location.
Flat layouts, explicit App and game-root/VFS discovery remain Python policy.
`MORPHBENCH_PYTHON` no longer selects a native bootstrap interpreter; source development
stages the same fixed bundled interpreter layout.

`presenters.launcher` contains pure option/root/limit functions and `LauncherSession`,
which owns an optional in-process `WebServer` and reuses `ServerLink` for other servers.
Closing stops only its own server; explicit Stop can stop a separate server.
`presenters.launcher_window` owns Windows controls, one serialized worker, bounded logs
and the native-parent watch. Parent creation times reject recycled PIDs. There is no
native controller subprocess supervision, pipe reader or server PID shutdown policy.

A v3 Runtime declares `launcherHostProtocol: 1`; new Applications declare
`launcherHostProtocols: [1]`. The updater refuses an App lacking the requested adapter
before writing files. This capability is separate from native-library API/ABI and is not
an exact version/hash pin. **Install the new Application before replacing v1/v2 with v3.**
Application 0.8.7 introduces this adapter; Application 0.8.6 predates it. The new App
still supports the v1/v2 adapters, so Application can be upgraded before the native host.

Future UI, discovery, HTTP and lifecycle fixes update Application only. A correction to
the fixed Python ABI/dependencies, handoff or quoting can still require a new native
package; this boundary cannot guarantee that an EXE will never need replacement.

## Independent contracts

| Contract | Current value | Changes that require a new native package |
|---|---|---|
| Runtime/Application compatibility | API 1, `cp312-win_amd64` | native dependencies or interpreter actually change |
| Minimal native handoff | host protocol 1 | fixed interpreter/shim invocation actually needs to change |
| Native bootstrap and server adapter | protocol 1 | the frozen host cannot implement a required new native facility |
| Browser plugin API | API 1 | none by itself; Application owns it |

An Application schema-2 manifest declares `requiresRuntime` with `apiVersion` and
`pythonAbi`. A Runtime manifest advertises `applicationApi` and `pythonAbi` and has its
own hashed inventory. Matching API/ABI permits different Runtime versions and hashes;
every declared Runtime file is still verified, as is the exact selected interpreter.
The hash detects changed files; it is not an authenticity signature.

The sole pre-contract Runtime v1 is recognized by its recorded exact identity/hash.
Old Application schema-1 manifests keep their original exact-pin meaning. They are
never silently reinterpreted. Application 0.8.6 supports both v1 and v2; Application
0.8.5 must be updated before installing v2. The [installation guide](install-layout.md)
describes the one-time transition using the new updater.

## Released v2 bootstrap protocol 1

The entry filename `launcher/mb.py` and interpreter filename `launcher/python/python.exe`
are stable native anchors. Both packages include the same Application-owned entry shim;
Application wins their overlap. Native runs:

```text
python.exe mb.py --launcher-context --protocol 1
```

The shim uses only the standard library: it does not import Application, start a server,
write settings or verify all dependencies just to locate an installation. An explicit
absolute `MORPHBENCH_APP` wins, then sibling App, then exactly one complete game-root
installation. Missing, invalid and ambiguous candidates fail; paths stay lexical for MO2.

Success is exit code 0 and exactly one JSON object on stdout. Diagnostics use stderr.
Required fields are `protocolVersion: 1`, absolute `appHome`, `settingsHome` and
`localeHome` (the actual locale directory), `settings` (object), `serverApi` (relative
path prefix ending in `/`), `statusArgs` and `startArgs` (CLI argument strings).
Optional `environmentArgs` adapts diagnostics and defaults to `env --json`.
The native host ignores unknown fields. Known field meanings must remain stable.
`settings` may provide language and the positive bounded values
`launcherCliTimeoutMs`, `launcherHttpTimeoutMs`, `launcherStopWaitMs`,
`launcherLogMaxChars`; absent/invalid values use native bootstrap defaults
30000, 30000, 5000 ms and 200000 characters. Timeout covers process exit **and** pipe EOF.

Application may extend this response or provide another protocol adapter. It must
retain protocol 1 for shipped v2 hosts. Unsupported requested versions exit nonzero
without running App. Future layout, settings or server changes go into this shim/adapter,
not native discovery code. This is trusted local runtime code, not a signed update channel.

The provided CLI commands retain their flags: native appends properly quoted `--root`
and `--parent` where applicable. `serve --status --json` returns the existing state,
URL and environment dictionaries; normal `serve` is idempotent. No computation is
exclusive to the native window.

## Server adapter 1

The supplied prefix is `api/launcher/v1/`. GET suffixes are `environment`, `root`
(optional URL-encoded `root` query) and `shutdown`. Their JSON fields, status codes,
foreign-origin checks and `morphbench/` Server identity retain existing `/api/*`
semantics. Existing public routes remain available. Internal APIs may change while
these three adapters keep the native contract unchanged.

Automatic owner closure supplies `shutdown?pid=<spawned Python PID>`. The adapter must
return 409 without stopping if the PID is not its own; a request without `pid` keeps
manual Stop semantics. This prevents an idempotent/exited child from stopping a different
server that appeared on the same port. Preserve this guard as part of protocol 1.

Closing cancels native workers and suppresses callbacks to disposed windows. It stops
only a server owned by this window; an independently running server survives closure.
The Python parent watch also releases the port if its launcher died during startup.

## Release boundary

Keep a released Runtime inventory immutable. A native/interpreter/dependency correction
gets a new Runtime ID and separate qualification. Compatible Runtime releases do not
require rebuilding Application. Application updates contain no EXE/DLL/PYD files and
preserve user settings and plugins. This separation avoids reuploading unchanged native
files for each Application update; every new native upload may still require Nexus review.

Do not promise that v3 will never need replacement: a native defect, interpreter ABI
upgrade or new native facility can require it. Keep such changes out of routine App work.
