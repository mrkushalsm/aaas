# AaaS research foundation (M0)

Independent Android compatibility runtime research for x86_64 Linux. This checkout contains evidence and experiment scaffolding, not an operational Android runtime. The source report is `docs/research-report.pdf` (SHA-256 pinned in `manifests/sources.json`).

## Reproduce M0

```sh
scripts/capture_host.sh
python3 scripts/verify_sources.py
scripts/probe_builds.sh
python3 benchmarks/baseline.py
python3 benchmarks/validate.py results/m0/baselines.jsonl
python3 -m unittest discover -s tests -v
```

Source clones are ignored under `sources/`. Raw logs stay in `results/m0/`. Build probes may fail on missing Sailfish development packages; failure is evidence, not a green build. No host package installation, security-control changes, or Android image modification is performed.

## Layout

- `docs/`: report, architecture, audit, and milestone gates
- `manifests/`: source and revision inventory
- `scripts/`: host capture, remote source checks, build probes
- `experiments/`: experiment definitions
- `benchmarks/`: machine-readable observation contract and baseline availability harness
- `tests/`: foundation checks
- `results/m0/`: captured host, source, build, and baseline evidence
