# M0 status: fail / incomplete

The first section records the original M0 snapshot. The M0.1 update below supersedes its mutable-ref inventory.

Observed on EndeavourOS, kernel 7.2.9, KDE Wayland, Intel i5-12450H. Raw host evidence is under `results/m0/host/`; absence of a capability in logs is not proof of kernel impossibility.

Pinned report commits for Droidloom, Waydroid, Lipstick, Qt HWC, Digitalis, Teto and the cited drm_hwcomposer tree returned HTTP 200 from their commit-object endpoints. Waydroid HAL `lineage-20` resolves but is mutable. The remaining named sources lack immutable report revisions. Remote object existence does not verify buildability or full dependency closure.

Build attempts: Lipstick at `b220a97` configured at top level then failed on Qt compositor/compositor-private/Sensors modules. Qt HWC at `31f4f65` failed on `android-headers` after hwcomposer2 detection returned no. See full `results/m0/build-probes/*.log`. Neither executable ran. No packages were installed.

Waydroid and Droidloom executable availability was checked; neither was installed. `results/m0/baselines.jsonl` records unavailable, not measured. The benchmark schema and harness run, but no launch/frame data exist.

M0 is incomplete because the AOSP/Android image and several source revisions are not frozen, full transitive license/build closure is missing, standalone runtime probes did not run, and no baseline runtime benchmarks were possible. All architecture statements in `interfaces.md` are hypotheses. Proceed only through M1 gates; never infer runtime correctness from successful compilation.

## M0.1 update

Individual Git repositories now have immutable observed snapshot IDs, including Waydroid HAL and the Digitalis manifest. This does not complete an Android build lock: the pinned Digitalis manifest still names 1,015 effective projects by moving branch. The post-sync lock generator and validator are in `scripts/android_repo_lock.py`; its small-fixture tests pass. See `android-source-lock.md`.

The isolated Lipstick build environment and direct dependency audit are documented in `lipstick-m01.md`. The host upstream probe was repeated. The image resolved Qt Sensors but lacks Sailfish packages; the legacy Sailfish QtCompositor fork did not compile against isolated Qt 5.15.8. `simplecompositor` did not build or run. Two-client nested runtime behavior remains untested. Droidloom and Waydroid baseline records remain unavailable. **M0 and M0.1 remain incomplete.**
