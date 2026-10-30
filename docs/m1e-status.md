# M1E status

Status: **PARTIAL — two Android tasks and output streams live; independent window use remains unverified**
Date: 2026-10-30
Code baseline before this continuation: `635626f` (`feat(composer): isolate virtual display transports`)

## Multi-output prototype delivered

The opt-in command now accepts two installed packages:

```sh
python3 scripts/run_aaas.py --experimental-virtual-display \
  --app com.android.settings --app2 com.android.deskclock --startup-timeout 180
```

One shared Android runtime created two system-owned trusted, private,
own-content displays. Android assigned display IDs 2 and 3; ActivityTaskManager
placed Settings task 8 and DeskClock task 9 on those displays. Composer assigned
virtual display IDs 100 and 101 and used independent local transports at
`/dev/aaas/wayland-vdisplay.sock` and `...sock-2`. Each output had its own
presenter, input-adapter socket, per-display buffer slots, locks, and generation
state. Both outputs emitted frames concurrently during the same run.

KWin reported two native xdg toplevels with distinct title/app-ID pairs:

| Android app | Task / Android display / Composer display | Wayland identity |
|---|---|---|
| Settings | 8 / 2 / 100 | `AaaS: com.android.settings`, `org.aaas.com-android-settings` |
| DeskClock | 9 / 3 / 101 | `AaaS: com.android.deskclock`, `org.aaas.com-android-deskclock` |

Each real Android surface was captured separately from its active Wayland
window. The screenshots are [Settings](../results/m1e/live/two_app_settings_wayland.png)
and [DeskClock](../results/m1e/live/two_app_deskclock_wayland.png). Their hashes,
logs, task/display identities, frame counters, and test limitations are in
[`two_app_outputs.json`](../results/m1e/live/two_app_outputs.json).

## Graphics ownership and shutdown boundary

The cap-two Composer binary has build ID
`ce4508c7312f6b69f8a832bd136738e584273854` and SHA-256
`4e07db6faead3712512fa0a886e4faf914582164b5a9c15c50302bc2abcee8c0`.
It owns a separate `AaasTransport` instance per virtual output, with independent
slot namespaces and per-display generation state. In the final bounded live run, Composer
created IDs 100 and 101 and submitted 260 and 245 frames respectively. Both
presenters used explicit synchronization and had zero rejected frames.

The two live runs observed GPU-only output/client-target DMA-BUF aliasing. That
alias is expected on the GPU-only VirtualDisplaySurface path; the implementation
does not force distinct allocations or self-copy. The retained stride-aware,
DMA_BUF_IOCTL_SYNC copy helper remains a separate mixed/distinct-backing path;
its host component tests pass, but no real distinct DMA-BUF copy was observed.

At shutdown the broker released display 3 then display 2, Android logged both
display removals and task destruction, the broker acknowledged `released`, and
the runtime state and status sentinel both reached STOPPED. The Settings presenter reported 260 imports/submissions, 259 releases, and 260
presentations; DeskClock reported 245 imports/submissions, 244 releases, and 245
presentations. Each presenter therefore had one final imported frame without a
matching release at process exit. Full-session cleanup works, but complete
in-flight drain and independent single-output teardown are not established.

## Important acceptance limits

KWin placed both toplevels at the same geometry `(600,0,720,1280)`. Individual
active-window captures prove each app rendered; they do not prove that both
were simultaneously visible without overlap. The Wayland client correctly
leaves placement to KWin, but this experiment did not establish a usable
side-by-side or independently arranged desktop presentation.

Controlled `/dev/uinput` clicks changed both Android views: Settings Search
opened on display 2, and the DeskClock Alarm tab opened on display 3. The
display-2 adapter logged Binder pointer DOWN/UP. With Search focused, a synthetic
non-sensitive `hii` fixture traversed Wayland/XKB/keyboard-v2/Binder and appeared
visibly in the Android editor. KWin focus switching emitted display-2 focus
leave and display-3 focus enter; the key events were recorded only by display 2.
This is partial cross-window focus evidence: DeskClock text entry, per-output
scroll, and complete two-way keyboard isolation remain unverified.

There is no Wayland configure-to-Android VirtualDisplay resize path. The
launcher treats either app/task or presenter exit as session-level termination;
closing one output while preserving the other, task-specific minimize, and
independent teardown are not implemented. Normal mode also continues presenting
the primary diagnostic output. Source-LMKD/cgroup was not combined with this
two-app run, although the existing single-app enhanced smoke evidence remains.

## Verification

For the code and live run in this continuation:

- The two-display broker built from source and was loaded by Android init.
- Cap-two Composer reported two ready independent endpoints and rendered both
  outputs concurrently.
- The two app tasks reached RUNNING on separate Android display IDs.
- Separate Settings and DeskClock active-window captures show actual Android
  pixels; each view changed after an output-targeted pointer click. Settings
  Search visibly displayed the synthetic key fixture.
- Full-session shutdown removed both displays and reached STOPPED.
- 147 Python tests, M1A, forced presenter rebuild/tests, input-adapter, Composer
  component, broker build, and external workspace checks are recorded in
  `results/m1e/acceptance.json` and `results/m1e/build_receipts/multi_output.json`.

The enhanced two-app smoke also reached RUNNING then STOPPED with source-LMKD/cgroup enabled; its monitor reported 0 errors, degraded=false, and the delegated hierarchy was removed. No memory-pressure experiment was induced.

These are component and bounded live prototype results, not full M1E acceptance.

## Next verified work

1. Give KWin a usable independent placement path and capture both application
   windows visible at once.
2. Verify keyboard editing in a second app and per-output scroll/focus routing;
   Settings synthetic typing and pointer changes in both outputs are now live.
3. Apply Wayland configure dimensions to the Android virtual display and verify
   Android configuration, rendering, and input coordinate changes.
4. Add task-specific close/minimize and broker display lifetime controls so one
   app can close while the other remains alive.
5. Drain/reconcile in-flight buffers on output teardown; verify no cross-output
   buffer/fence reuse.
6. Verify primary diagnostic output suppression in app mode and repeat enhanced
   LMKD/cgroup with two apps.

Overall M1E remains **PARTIAL**. Two Android tasks, two trusted displays, two
Composer output streams, and two native toplevels are demonstrated, but the
required independent user-visible window behavior and per-window interaction
lifecycle have not yet passed.
