# E1: nested Lipstick simplecompositor

First build the pinned sources in the isolated image:

```sh
git clone https://github.com/sailfishos/lipstick.git sources/lipstick-m01
git -C sources/lipstick-m01 checkout --detach b220a976699b30d69e00b5a6480ade809fca55ae
git clone https://github.com/sailfishos/qtwayland.git sources/sailfish-qtwayland
git -C sources/sailfish-qtwayland checkout --detach f377218d71c1c2de7b0cf71f0acd551309d8e86b
experiments/lipstick/build-isolated.sh
```

The script records its image ID, complete build logs and per-probe exit codes under `results/m01/lipstick/`. The Docker image is isolated from host package installation. `Dockerfile` pins the base image and Debian package snapshot; compare `image-packages-and-notices.json` after rebuilding. Current probes fail before a compositor executable is available.

When a real `simplecompositor` build is available, build the independent event client:

```sh
mkdir -p results/m01/lipstick/test-client-build
cd results/m01/lipstick/test-client-build
qmake ../../../../experiments/lipstick/test-client/client.pro
make -j2
```

Then run `nested_test.py` with a compositor launch command and the exact socket path it creates. Example shape, **not a verified Lipstick invocation**:

```sh
python3 experiments/lipstick/nested_test.py \
  --compositor /absolute/path/to/simplecompositor \
  --socket "$XDG_RUNTIME_DIR/aaas-lipstick-test" \
  --client "$PWD/results/m01/lipstick/test-client-build/aas-wayland-test-client" \
  --output "$PWD/results/m1/lipstick-nested"
```

The operator focuses both clients, resizes both, closes A, and leaves B open. The harness verifies event records, kills the compositor, checks B disconnects, and removes a stale test socket. A passing event test still needs an explicit review that no Sailfish phone daemon was required. No M1 runtime pass is recorded yet.
