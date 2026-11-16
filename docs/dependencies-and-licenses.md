# Licensing and external runtime inputs

AaaS is an experimental Android application runtime for Linux. This repository
does not currently include a project-wide license. Public visibility of the
source is not permission to use, modify, or redistribute it. The project owner
must choose and authorize a license after confirming ownership of the original
contributions. Apache-2.0 is the current recommendation for owner-controlled
AaaS code because it includes an express patent grant and is familiar in the
Android/Linux ecosystem. MIT and GPL-3.0-or-later remain alternatives with
different patent and copyleft tradeoffs. No license has been applied.

## Third-party source

Some files retain independent upstream notices and must not be relicensed by a
future project-wide license. In particular, the tree includes AOSP-attributed
Binder/JNI and graphics interfaces, MIT-noticed audio files, upstream Wayland
protocol descriptions, generated AIDL material, and SwiftShader-related
patches. Preserve their file-level notices. Exact origin, revision, modification
history, and notice obligations are not established for every imported or
generated file; those items require review before a source release.

## Android image and binary distribution

The accepted developer preview was assembled from the Android SDK package
`system-images;android-36;default;x86_64` (revision `r02`, build
`BE2A.250530.026.D1`) and contains locally modified runtime components. A fresh
source checkout does not contain the Android image and is not independently
runnable without the required external inputs and assembly steps. Those image
terms, modifications, bundled third-party binaries, and associated notice or
source obligations have not been cleared for redistribution. Do not redistribute
the accepted bundle or SDK image. A supported user-side acquisition and
assembly workflow has not yet been established.

Detailed candidate-specific binary inventories and one-time publication
review records are retained locally by the maintainer; they are not part of the
source repository. This summary is not legal advice or a redistribution
approval.

## Decisions required before public source release

1. The owner selects a project license and confirms authority over covered
   contributions, including any employer or contributor rights.
2. The maintainer resolves the origin and notices for imported/generated source
   files while preserving independent upstream terms.
3. The owner reviews whether existing Git author identities and historical
   machine-specific paths are suitable for public exposure. History has not
   been rewritten.
4. The Android image acquisition, transformation, and binary redistribution
   questions remain separate from source publication and require rights review.

Until those decisions are complete, the repository is not an authorized
open-source release and the developer-preview binaries are not cleared for
public distribution.
