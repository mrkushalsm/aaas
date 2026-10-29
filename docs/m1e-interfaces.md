# M1E proposed interfaces and identity model

Status: **design contract; not implemented**

## Identity mapping

These identifiers have different owners and must remain separate:

| Identifier | Owner | Scope / lifetime |
|---|---|---|
| AaaS session ID | host launcher | random, private to one runtime session |
| AaaS host-window ID | host session manager | stable within the session; one `xdg_toplevel` |
| Android display ID | Android DisplayManager | runtime-assigned; may be reused after display removal, so pair with generation |
| Android task ID | ActivityTaskManager | Android task lifecycle; not the same as an Activity or display ID |
| Activity token/component | ActivityTaskManager/PackageManager | one Activity instance or component identity |
| buffer ID + generation | Composer transport | one buffer ownership epoch |
| Wayland configure generation | host presenter | one toplevel geometry epoch |
| input focus generation | host presenter/input adapter | invalidates stale events after focus or window lifecycle changes |

The intended relationship is `host_window_id -> (android_display_id,
display_generation) -> task_id`, with Activity records remaining Android-owned.
The relationship is not assumed one-to-one: an Android task may host several
Activities. Independent task/window mappings require live ActivityTaskManager
and WindowManager verification.

## Host-to-Android launch/control channel

The launcher now accepts a validated `--app <package>` request and asks the
Android PackageManager shell resolver for a `MAIN`/`LAUNCHER` component. This
is still a single-window diagnostic path, not the future multi-window broker.
The broker interface should accept only structured fields:

- session token;
- request sequence and operation (`CREATE_APP_WINDOW`, `CLOSE_APP_WINDOW`,
  `SET_WINDOW_SIZE`, `FOCUS_WINDOW`, `BACK`, `QUERY_STATE`);
- package name or explicit component (never a shell command string);
- requested content width, height, and density bounds;
- host-window ID and expected display generation for operations after create.

The broker resolves the package's launcher Activity through PackageManager,
checks user-unlocked and launchability, and asks the supported Android task and
display services to launch. It reports a typed result containing task ID,
display ID, display generation, resolved component, current lifecycle state,
and a bounded error code. It does not expose general Binder transactions or
arbitrary command execution to the host.

## Frame transport

Existing wire protocol v2 is a single output stream. Its message has generation
and buffer identity but no host-window or Android-display target. Preserve v2
semantics. M1E must either:

1. Negotiate a new frame protocol version with an explicit stream/window ID and
   display generation, or
2. Keep one authenticated `SOCK_SEQPACKET` stream per host window, with a
   session-level manager associating socket path and window ID.

Both options must preserve FD transfer, acquire fences, delayed release fences,
buffer ID uniqueness per stream, stale-generation rejection, bounded buffers,
and teardown acknowledgements. A display ID must never be reused as a host
window ID implicitly.

## Input routing

Pointer v1 and keyboard v2 currently target Android display 0. Keep those
messages intact. New multi-window routing must explicitly bind the authenticated
session, host-window ID, Android display ID, display generation, focus
generation, and monotonic input sequence. Focus enter/leave must release held
buttons and keys before changing target. A destroyed display invalidates every
queued event for its generation. No global host input capture is introduced.

## Resize and lifecycle

Wayland configure sizes are surface logical pixels. Android display dimensions
are content pixels and depend on scale/density policy. A resize transaction
must report the chosen content dimensions and density; successful Android
configuration update is acknowledged before pointer coordinates use the new
generation. Merely scaling the old image is not accepted as Android resize.

Minimize/unmap should pause or rate-limit output while Android lifecycle remains
correct. Host close should finish the exposed task or close the session only
when it is the last app window; that policy is pending the M1E.1 prototype.
