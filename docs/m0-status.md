# M0 status: fail / incomplete

Observed on EndeavourOS, kernel 7.2.9, KDE Wayland, Intel i5-12450H. Raw host evidence is under `results/m0/host/`; absence of a capability in logs is not proof of kernel impossibility.

Pinned report commits for Droidloom, Waydroid, Lipstick, Qt HWC, Digitalis, Teto and the cited drm_hwcomposer tree returned HTTP 200 from their commit-object endpoints. Waydroid HAL `lineage-20` resolves but is mutable. The remaining named sources lack immutable report revisions. Remote object existence does not verify buildability or full dependency closure.

Build attempts: Lipstick at `b220a97` configured at top level then failed on Qt compositor/compositor-private/Sensors modules. Qt HWC at `31f4f65` failed on `android-headers` after hwcomposer2 detection returned no. See full `results/m0/build-probes/*.log`. Neither executable ran. No packages were installed.

Waydroid and Droidloom executable availability was checked; neither was installed. `results/m0/baselines.jsonl` records unavailable, not measured. The benchmark schema and harness run, but no launch/frame data exist.

M0 is incomplete because the AOSP/Android image and several source revisions are not frozen, full transitive license/build closure is missing, standalone runtime probes did not run, and no baseline runtime benchmarks were possible. All architecture statements in `interfaces.md` are hypotheses. Proceed only through M1 gates; never infer runtime correctness from successful compilation.
