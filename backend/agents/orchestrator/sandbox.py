"""
Deep Query — Document sandbox runner (DOCUMENT_GENERATION_SANDBOX_GUIDE §3.2)

One executor function: take a self-contained, model-written Python script and run it
inside a locked-down throwaway container, returning whatever files it wrote. The
security contract (proven empirically in backend/sandbox/README.md) is non-negotiable:
no network, read-only FS except /workspace/output, unprivileged user, dropped caps,
hard memory/cpu/pid/time limits. The script is treated as potentially hostile
(model-generated from corpus content) — the box, not trust, is what keeps it safe.

Simplified contract (project decision, see memory produce-sandbox-design): the script is
self-contained — the model embeds the data it computed. No input staging, no summary.json.
The sandbox answers exactly one question: "did this code run and produce a valid file?"
Number-correctness lives upstream (the LLM + the workflow verify step), not here.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.config import settings

logger = logging.getLogger(__name__)

_CAP_BYTES = 64 * 1024  # cap captured stdout/stderr so a chatty script can't flood state

# One global gate so concurrent `produce` steps don't oversubscribe the host. Created
# lazily inside the running loop (mirrors event_bus's client/lock pattern).
_semaphore: Optional[asyncio.Semaphore] = None
_sem_lock: Optional[asyncio.Lock] = None


async def _acquire_slot() -> asyncio.Semaphore:
    global _semaphore, _sem_lock
    if _semaphore is None:
        if _sem_lock is None:
            _sem_lock = asyncio.Lock()
        async with _sem_lock:
            if _semaphore is None:
                _semaphore = asyncio.Semaphore(max(1, settings.agent_sandbox_max_concurrent))
    return _semaphore


@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    output_files: list[Path] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """A run is OK only if it exited cleanly AND produced at least one file (an exit-0
        run that wrote nothing is a failure for our purposes — the contract is a document)."""
        return self.exit_code == 0 and not self.timed_out and bool(self.output_files)

    def classify(self) -> str:
        """Map the outcome to a clean error class for the repair loop + telemetry (§10)."""
        if self.timed_out:
            return "timeout"
        if self.exit_code in (137, 139):  # SIGKILL / SIGSEGV — usually the memory cap
            return "oom"
        if self.exit_code != 0:
            return "error"
        if not self.output_files:
            return "empty_output"
        return "ok"

    def error_digest(self) -> str:
        """A compact, model-feedable description of what went wrong (never shown raw to
        the user — the node narrates naturally)."""
        cls = self.classify()
        if cls == "timeout":
            return f"The script timed out (exceeded {settings.agent_sandbox_timeout_s}s)."
        if cls == "oom":
            return f"The script was killed (likely exceeded the {settings.agent_sandbox_memory} memory limit)."
        if cls == "empty_output":
            return ("The script exited 0 but wrote no file to /workspace/output/. Make sure it "
                    "saves the document to an absolute path under /workspace/output/.")
        tail = (self.stderr or self.stdout or "").strip()
        return tail[-4000:] if tail else f"The script exited with code {self.exit_code}."


def _mount(p: Path) -> str:
    """Host path for a -v bind mount. Docker (incl. Desktop on Windows) accepts a native
    absolute path; we pass argv directly via create_subprocess_exec (no shell), so MSYS
    path mangling never applies and the C:\\ drive colon is handled by the runtime."""
    return str(p.resolve())


def _build_cmd(job_dir: Path, image: str) -> list[str]:
    """The exact, proven flag set from backend/sandbox/README.md. Input is NOT mounted —
    the script is self-contained (project decision); only the writable output dir and the
    read-only script are bound."""
    runtime = (settings.agent_sandbox_runtime or "docker").strip()
    return [
        runtime, "run", "--rm",
        "--network=none",
        "--read-only", "--tmpfs", "/tmp",
        "-v", f"{_mount(job_dir / 'output')}:/workspace/output:rw",
        "-v", f"{_mount(job_dir / 'script.py')}:/workspace/script.py:ro",
        "--user", "1000:1000",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--memory", str(settings.agent_sandbox_memory),
        "--cpus", str(settings.agent_sandbox_cpus),
        "--pids-limit", str(settings.agent_sandbox_pids_limit),
        image,
        "python", "/workspace/script.py",
    ]


async def run_sandbox(
    script: str,
    job_dir: Path,
    *,
    image: Optional[str] = None,
    timeout: Optional[int] = None,
) -> SandboxResult:
    """Run a self-contained script in the sandbox and return the outcome + any files it
    wrote to /workspace/output/. Writes ``script.py`` into ``job_dir`` and binds
    ``job_dir/output`` as the only writable mount. Never raises for a script failure —
    that's a SandboxResult with a nonzero exit (the repair loop's job); only genuinely
    exceptional host conditions propagate."""
    image = image or settings.agent_sandbox_image
    timeout = timeout or settings.agent_sandbox_timeout_s
    job_dir = Path(job_dir)
    out_dir = job_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "script.py").write_text(script, encoding="utf-8")

    cmd = _build_cmd(job_dir, image)
    sem = await _acquire_slot()
    async with sem:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        except FileNotFoundError as exc:
            # Runtime binary missing — a clean, classifiable failure, not an opaque crash.
            logger.error("sandbox runtime '%s' not found: %s", cmd[0], exc)
            return SandboxResult(127, "", f"sandbox runtime '{cmd[0]}' not found", False)

        timed_out = False
        stdout_b = stderr_b = b""
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()

    stdout = stdout_b.decode("utf-8", "replace")[:_CAP_BYTES] if stdout_b else ""
    stderr = stderr_b.decode("utf-8", "replace")[:_CAP_BYTES] if stderr_b else ""
    exit_code = proc.returncode if proc.returncode is not None else -1
    files = (
        sorted(p for p in out_dir.iterdir() if p.is_file() and p.name != ".gitkeep")
        if out_dir.is_dir() else []
    )
    logger.info("sandbox run exit=%s timed_out=%s files=%s", exit_code, timed_out,
                [p.name for p in files])
    return SandboxResult(exit_code, stdout, stderr, timed_out, files)
