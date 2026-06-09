"""Per-connector circuit breaker + health (guide §5, §12).

A hostile or broken connector must not hang queries. Each connector's failures
are tracked; after a threshold of consecutive failures the circuit **opens** and
calls **fast-fail** for a cooldown window instead of waiting on a dead connector.
This isolates a failing connector into a clear, user-legible error.

State is in-process (a module-level singleton). Note: with multiple API workers
each holds its own breaker — acceptable for Phase 4; a shared (Redis) breaker is a
later refinement.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """The circuit is open; the call was fast-failed without reaching the connector."""


@dataclass
class _State:
    consecutive_failures: int = 0
    state: str = CLOSED
    opened_monotonic: float = 0.0
    last_success_at: float = 0.0
    last_failure_at: float = 0.0
    last_error: str = ""


class CircuitBreaker:
    def __init__(self, *, failure_threshold: int = 3, cooldown_s: float = 30.0) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        self._states: dict[str, _State] = {}
        self._lock = threading.Lock()

    def _state(self, name: str) -> _State:
        with self._lock:
            return self._states.setdefault(name, _State())

    def check(self, name: str) -> None:
        """Raise CircuitOpenError if the connector's circuit is open and still
        cooling down. After cooldown, allow a single trial (half-open)."""
        st = self._state(name)
        with self._lock:
            if st.state == OPEN:
                if time.monotonic() - st.opened_monotonic >= self.cooldown_s:
                    st.state = HALF_OPEN  # let one call through to test recovery
                else:
                    raise CircuitOpenError(name)

    def record_success(self, name: str) -> None:
        st = self._state(name)
        with self._lock:
            st.consecutive_failures = 0
            st.state = CLOSED
            st.last_success_at = time.time()

    def record_failure(self, name: str, error: str = "") -> None:
        st = self._state(name)
        with self._lock:
            st.consecutive_failures += 1
            st.last_failure_at = time.time()
            st.last_error = error[:300]
            if st.consecutive_failures >= self.failure_threshold:
                st.state = OPEN
                st.opened_monotonic = time.monotonic()

    def health(self, name: str) -> dict[str, Any]:
        st = self._state(name)
        return {
            "connector": name,
            "state": st.state,
            "consecutive_failures": st.consecutive_failures,
            "last_success_at": st.last_success_at or None,
            "last_failure_at": st.last_failure_at or None,
            "last_error": st.last_error or None,
        }


circuit_breaker = CircuitBreaker()
