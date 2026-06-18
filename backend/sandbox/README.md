# Document Sandbox — image + isolation proof

The locked-down container that runs model-generated `produce` scripts (xlsx/docx/…).
This directory is the **environment layer only**: one image + a by-hand proof that the
security contract holds. No application code depends on it yet — that wiring (the
`produce` controller action + `DocumentAgent` + `run_sandbox()`) lands in a later pass.

See `DOCUMENT_GENERATION_SANDBOX_GUIDE.md` (§3) for the design rationale.

## The security contract (load-bearing)

Every sandbox run is launched with these flags. They are the whole reason a
model-generated script — potentially prompt-injected via poisoned corpus content — is
safe to execute:

| Flag | Guarantee |
|---|---|
| `--network=none` | no exfiltration, no external calls |
| `--read-only` + `--tmpfs /tmp` | filesystem immutable except scratch + the job's `output/` |
| `--user 1000:1000` | runs as the unprivileged `runner`, never root |
| `--cap-drop ALL` | no Linux capabilities |
| `--security-opt no-new-privileges` | cannot escalate |
| `--memory 1g --cpus 1 --pids-limit 128` | bounded blast radius |
| `--rm` | container is discarded after the run |

Worst case collapses to "the script corrupts its own `output/`," which validation and
the user's eyes catch.

## Build

```bash
docker build -t deepquery-doctools:0.1 backend/sandbox
```

(Swap `docker`→`podman` on a rootless host — identical otherwise. Run from the repo root,
or adjust the build-context path.)

## Prove it works (happy path)

From `backend/sandbox/`:

```bash
podman run --rm \
  --network=none --read-only --tmpfs /tmp \
  -v "$PWD/testjob/input:/workspace/input:ro" \
  -v "$PWD/testjob/output:/workspace/output:rw" \
  -v "$PWD/testjob/script.py:/workspace/script.py:ro" \
  --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges \
  --memory 1g --cpus 1 --pids-limit 128 \
  deepquery-doctools:0.1 python /workspace/script.py
```

Expect: `wrote report.xlsx + summary.json; total = 4400.0`, and both files appear in
`testjob/output/`.

## Prove isolation holds (must-fail path)

Same flags, swap the mounted script for the network probe:

```bash
podman run --rm \
  --network=none --read-only --tmpfs /tmp \
  -v "$PWD/testjob/input:/workspace/input:ro" \
  -v "$PWD/testjob/output:/workspace/output:rw" \
  -v "$PWD/testjob/netprobe.py:/workspace/script.py:ro" \
  --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges \
  --memory 1g --cpus 1 --pids-limit 128 \
  deepquery-doctools:0.1 python /workspace/script.py
```

Expect: `OK: network blocked — URLError` (or similar). If you see `FAIL: network
reachable`, the runtime is ignoring `--network=none` — **do not ship** until fixed.

## Host notes

- **Linux (prod target):** the flags above behave exactly as documented. Rootless Podman
  is preferred — no daemon, no socket, the container runs as the backend's own user.
- **Windows Docker Desktop (local dev only):**
  - Git Bash mangles bind-mount paths. Prefix the command with `MSYS_NO_PATHCONV=1`.
  - The drive holding this repo must be added under Docker Desktop → Settings →
    Resources → File Sharing, or the bind mount silently yields an empty `input/`.
  - None of this exists on Linux — which is why the deploy target stays Linux.

## Versioning

The image tag (`deepquery-doctools:0.1`) is recorded in run telemetry next to
`skills@versions`. Rebuilds are deliberate (dependency-discipline). Bump the tag when
`requirements.txt` changes; pin the new tag in `settings.agent_sandbox_image`.
