#!/usr/bin/env python3
"""Relink the existing Android SwiftShader overlay with the Bionic ABI shims.

The Vulkan object overrides in workspace/tmp are the retained Gemini build
artifacts. This script never changes the original overlay binary.
"""

import argparse
import pathlib
import shlex
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    build = workspace / "sources/swiftshader/build"
    tmp = workspace / "tmp"
    root = pathlib.Path(__file__).resolve().parents[1]
    subprocess.run(["ninja", "-C", str(build), "ReactorSubzero"], check=True)
    shim = tmp / "m1b72_bionic_stubs.o"
    subprocess.run(
        ["g++", "-fPIC", "-O2", "-c", str(root / "experiments/m1b/swiftshader/bionic_stubs.cpp"), "-o", str(shim)],
        check=True,
    )
    command = subprocess.check_output(
        ["ninja", "-C", str(build), "-t", "commands", "vk_swiftshader"], text=True
    ).splitlines()[-1].split(" && cd ")[0]
    parts = shlex.split(command)
    patched = {path.name: path for path in tmp.glob("*.cpp.o")}
    objects = [str(patched.get(pathlib.Path(item).name, build / item)) for item in parts if item.endswith(".o")]
    archives = [str(build / item) for item in parts if item.endswith(".a")]
    link = [
        "g++", "-shared", "-fPIC", "-O2", "-static-libstdc++", "-static-libgcc",
        "-Wl,-Bsymbolic", "-Wl,--version-script=" + str(tmp / "vulkan_hal.lds"),
        "-o", str(args.output), *objects,
        str(tmp / "VkDeviceMemoryExternalAndroid.cpp.o"), str(shim), *archives,
        "-ldl", "-lpthread", "-lrt", "-L" + str(workspace / "rootfs_m1b1/system/lib64"),
        "-lnativewindow", "-lsync",
    ]
    subprocess.run(link, check=True)


if __name__ == "__main__":
    main()
