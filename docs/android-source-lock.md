# Android source graph status (M0.1)

`manifests/sources.json` pins every listed standalone or reference repository to an observed Git commit. These are **individual snapshots**, not a compatible multi-repository Android build. The `selected_from` field preserves the moving ref used for each new pin. `results/m0/source-verification.json` records commit-object existence, not build compatibility.

The generated Composer AIDL headers are a separately checked subset of the
Android 16 QPR2 source candidate. Their 92 input definitions, 276 generated
header mappings, source hashes, and Apache-2.0 header evidence are in the
[Composer AIDL provenance manifest](../manifests/composer-aidl-provenance.json).
That mapping does not replace a full `repo manifest -r` lock or a historical
generation receipt.

Digitalis's `android16` manifest is pinned at `c04ff674ee0926fe79e690b20493c7b2f0e380b4`. Its `default.xml` uses AOSP's `android16-qpr2-release` branch and includes `digitalis.xml`, which removes the AOSP Goldfish and Berberis projects and replaces them with Digitalis GitHub projects. The pinned manifest contains **1,015** effective project paths. None of those branch-backed projects has been synced or converted to a revision lock. The observed AOSP platform manifest and superproject commits in `sources.json` are reference snapshots; they do not prove the Digitalis project graph corresponds to that superproject commit.

To materialize the Android graph on a sufficiently provisioned isolated build machine:

```sh
git clone https://gerrit.googlesource.com/git-repo git-repo-tool
git -C git-repo-tool checkout --detach f4ce9572d1f9e412a5685297d2806ce410e4d4a0
export PATH="$PWD/git-repo-tool:$PATH"
mkdir -p android16 && cd android16
repo init -u https://github.com/DigitalisX64/manifest.git -b android16 \
  --repo-url=https://gerrit.googlesource.com/git-repo \
  --repo-rev=f4ce9572d1f9e412a5685297d2806ce410e4d4a0
git -C .repo/manifests checkout --detach c04ff674ee0926fe79e690b20493c7b2f0e380b4
repo sync -c -j4
python3 /absolute/path/to/aaas/scripts/android_repo_lock.py generate --lock /absolute/path/to/aaas/manifests/android16-locked.xml
```

The pinned manifest's Digitalis remote uses SSH `git@github.com:DigitalisX64`; access to that remote must be configured or the manifest must be transparently mirrored in an **experiment-specific** overlay. The command above may fail on machines without SSH access. A resolved repo lock is accepted only when every project has a 40-hex revision and the four Digitalis override paths equal their separately recorded pins. If branch heads move between snapshot and sync, validation fails rather than silently accepting different source. `repo manifest -r` is run only after a successful sync. No `android16-locked.xml` is present yet; the full graph remains unmaterialized.

For local audit without Android checkout:

```sh
python3 scripts/android_repo_lock.py inspect
python3 -m unittest discover -s tests -v
```

The first command parses includes, removals and replacement paths from the pinned manifest checkout at `sources/digitalis-manifest`. Its output is retained at `results/m0/android-manifest-inspection.json`. The lock generator and validator are exercised on small XML fixtures; they have not been exercised against a synced AOSP tree.
