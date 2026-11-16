# Contributing to AaaS

AaaS is an experimental Android-on-Linux project. A source clone contains the
project code and tests, but not the Android SDK image or the accepted runtime;
cloning alone does not produce a bootable installation. See the [developer
runtime guide](docs/developer-runtime.md), [build-input guide](docs/m5-portable-development-release.md),
and [architecture guide](docs/architecture.md) before changing runtime code.

## Tests

The Python regression suite requires Python 3 and uses the standard library:

```sh
python3 -m unittest discover -s tests -q
```

Native components have focused Makefiles under `experiments/`. Their build
dependencies vary: targets may require `make`, a C/C++ compiler, `pkg-config`,
Wayland/DRM development packages, or Android NDK/Clang toolchains. Check the
selected component's Makefile and documentation for its exact prerequisites
and target; there is no single repository-wide native dependency set. The
repository does not provide a complete, reproducible Android image build. Do
not claim runtime acceptance from unit tests or source compilation alone.

## Changes and provenance

- Keep changes focused and include regression coverage for behavior changes.
- Record the upstream origin, version/revision, license, and modifications when
  adding imported or generated code. Preserve its copyright and license
  notices; do not apply the root Apache license to third-party code.
- Do not add Android system images, runtime bundles, userdata, VM disks,
  signing keys, logs, or generated build outputs. The checked-in
  `.gitignore` excludes common local artifacts, but review `git status` before
  committing.
- Do not include credentials or private user data in tests, logs, screenshots,
  or issue reports. Redact diagnostics before sharing them.

## Licensing contributions

Eligible original AaaS source code owned by the project owner is licensed under
Apache-2.0. By intentionally submitting a contribution for inclusion in that
covered source, you agree that the contribution is offered under Apache-2.0,
unless you clearly identify a different applicable license or the project
maintainers agree otherwise. Submit only work you have the right to contribute;
check employer or client obligations first. Existing third-party files and
notices keep their own terms. See [LICENSE](LICENSE) and
[third-party notices](THIRD_PARTY_NOTICES.md).
