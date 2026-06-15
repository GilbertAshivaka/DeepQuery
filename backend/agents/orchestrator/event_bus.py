"""
Deep Query — Agent run event bus (RESUMABLE_AGENT_SPEC_V2 §2.5/§2.6/§2.12, phase R2)

Every event a run emits is appended to a per-run **Redis Stream**
(``agent:run:{thread_id}:events``, monotonic stream IDs) and folded into a compact
**snapshot** (``agent:run:{thread_id}:snapshot``). This decouples *producing* events
(the orchestrator, driven in-request today; an executor in R3) from *consuming* them
(SSE subscribers): a client paints the UI with one GET on the snapshot, then tails
``/events`` from a ``Last-Event-ID``, getting replay-then-live for free — so reconnects,
multi-tab, and returning to an awaiting-approval run all work without re-running anything.

The bus is **best-effort for producers**: if Redis is unreachable, ``publish``/``init_run``
log and no-op so the in-request SSE stream (which still flows directly to the client)
never breaks. Consumers (``/events``/``/state``) require the bus and surface a clean error
when it's unavailable. Keys live on db 0 (shared with the checkpointer; AOF on) and carry
a TTL so abandoned runs expire (full sweeper is a later phase).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Callable, Optional

import redis.asyncio as aioredis

from core.config import settings

logger = logging.getLogger(__name__)

_EVENTS_KEY = "agent:run:{tid}:events"
_SNAPSHOT_KEY = "agent:run:{tid}:snapshot"
_MAILBOX_KEY = "agent:run:{tid}:mailbox"
# Hard cap on retained events per run (answer_token segments make streams long); the
# snapshot carries the painted state, so trimming old raw events is safe.
_STREAM_MAXLEN = 10000
# Subscriber block window; on timeout we surface a heartbeat so the SSE layer can ping
# and notice client disconnects.
_BLOCK_MS = 15000
# Statuses that mean the run is FINISHED — a subscriber always stops.
_DONE_STATUSES = {"done", "error", "interrupted"}
# Statuses that mean the run is PAUSED for human input. A subscriber stops on these ONLY
# when nothing is actively resuming the run; during a /resume the executor task is live and
# the snapshot momentarily still shows the pause, so the subscriber must tail THROUGH it.
_PAUSED_STATUSES = {"awaiting_approval", "awaiting_input"}
# Event types that end a live tail (a completed run, a failure, or a pause for input).
_TERMINAL_EVENTS = {"done", "error", "approval_required", "batch_approval_required", "question"}


def _subscriber_should_stop(status: Optional[str], is_live: Optional[Callable[[], bool]]) -> bool:
    """Decide whether a subscriber should stop after replay / on an idle heartbeat."""
    if status in _DONE_STATUSES:
        return True
    if status in _PAUSED_STATUSES:
        # Paused — stop only if no resume is driving the run forward right now.
        return not (is_live is not None and is_live())
    if status == "running":
        return is_live is not None and not is_live()  # producer died in a restart
    return False

_client: Optional[aioredis.Redis] = None
_client_lock: Optional[asyncio.Lock] = None


def _ttl_seconds() -> int:
    return max(1, settings.agent_run_ttl_hours) * 3600


async def _get_client() -> aioredis.Redis:
    """Lazily create the async Redis client inside the running loop."""
    global _client, _client_lock
    if _client is not None:
        return _client
    if _client_lock is None:
        _client_lock = asyncio.Lock()
    async with _client_lock:
        if _client is None:
            _client = aioredis.from_url(settings.agent_redis_url, decode_responses=True)
    return _client


# ── Snapshot fold ────────────────────────────────────────────

def _new_snapshot(thread_id: str, user_id: str = "") -> dict[str, Any]:
    return {
        "thread_id": thread_id,
        "user_id": user_id,
        "run_status": "running",        # running | awaiting_approval | done | error
        "plan": [],                      # [{id,label,status}]
        "trace": [],                     # reasoning/thinking/tool timeline (mirrors DB cot)
        "answer": "",                    # accumulated answer text
        "citations": [],
        "verification": {},
        "pending_approval": None,        # the approval_required / batch payload while paused
        "pending_question": None,        # the question payload while awaiting an answer (R7)
        "action_result": None,
        "intent": None,
        "grounded": True,
        "error": None,
        "last_event_id": None,           # stream ID of the most recent event (resume point)
    }


def _fold(snap: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Apply one event to the snapshot (the single source of truth for UI paint,
    mirroring how /run persists the DB trace and the frontend store assembles live)."""
    t = event.get("type")
    if t == "run_started":
        snap["run_status"] = "running"
    elif t == "plan":
        snap["plan"] = event.get("steps") or []
    elif t == "step_status":
        for s in snap["plan"]:
            if s.get("id") == event.get("id"):
                s["status"] = event.get("status")
        if event.get("status") == "awaiting-approval":
            snap["run_status"] = "awaiting_approval"
    elif t == "reasoning":
        snap["trace"].append({"kind": "reasoning", "text": event.get("text")})
    elif t == "thinking":
        if snap["trace"] and snap["trace"][-1].get("kind") == "thinking":
            snap["trace"][-1]["content"] = snap["trace"][-1].get("content", "") + event.get("content", "")
        else:
            snap["trace"].append({"kind": "thinking", "content": event.get("content", "")})
    elif t == "tool_activity":
        snap["trace"].append({"kind": "tool", "tool": event.get("tool"),
                              "detail": event.get("detail"), "status": event.get("status")})
    elif t == "skill_loaded":
        snap["trace"].append({"kind": "skill", "name": event.get("name"),
                              "version": event.get("version")})
    elif t == "citations":
        snap["citations"] = event.get("citations") or event.get("content") or []
    elif t == "answer_token":
        snap["answer"] = snap.get("answer", "") + event.get("content", "")
    elif t in ("approval_required", "batch_approval_required"):
        snap["pending_approval"] = {k: v for k, v in event.items() if k != "type"}
        snap["run_status"] = "awaiting_approval"
    elif t == "question":
        snap["pending_question"] = {k: v for k, v in event.items() if k != "type"}
        snap["run_status"] = "awaiting_input"
    elif t == "verification_result":
        snap["verification"] = {"outcome": event.get("outcome"),
                                "corrected_answer": event.get("corrected_answer", ""),
                                "explanation": event.get("explanation", "")}
    elif t == "action_result":
        snap["action_result"] = {k: v for k, v in event.items() if k != "type"}
    elif t == "done":
        if event.get("paused"):
            # A paused `done` follows an approval_required/question that already set the
            # precise status — don't clobber `awaiting_input` with `awaiting_approval`.
            if snap.get("run_status") not in _PAUSED_STATUSES:
                snap["run_status"] = "awaiting_approval"
        else:
            snap["run_status"] = "done"
        if event.get("answer"):
            snap["answer"] = event.get("answer")
        if event.get("citations"):
            snap["citations"] = event.get("citations")
        if event.get("intent"):
            snap["intent"] = event.get("intent")
        if event.get("grounded") is not None:
            snap["grounded"] = event.get("grounded")
    elif t == "error":
        snap["run_status"] = "error"
        snap["error"] = event.get("message")
    return snap


# ── Producer API (best-effort) ───────────────────────────────

async def init_run(thread_id: str, user_id: str) -> None:
    """Seed the snapshot with the run's owner before the first event (so /state and
    /events can authorize). Best-effort."""
    try:
        client = await _get_client()
        snap = _new_snapshot(thread_id, user_id)
        # A thread_id is per-run; start its stream fresh so a (defensive) key reuse can't
        # inherit a prior run's events.
        await client.delete(_EVENTS_KEY.format(tid=thread_id))
        await client.set(_SNAPSHOT_KEY.format(tid=thread_id), json.dumps(snap), ex=_ttl_seconds())
    except Exception as exc:
        logger.warning("event_bus.init_run failed for %s: %s", thread_id, exc)


async def publish(thread_id: str, event: dict[str, Any]) -> Optional[str]:
    """Append an event to the run's stream and fold it into the snapshot. Returns the
    stream sequence ID, or None if the bus is unavailable (producer continues regardless)."""
    try:
        client = await _get_client()
        ekey = _EVENTS_KEY.format(tid=thread_id)
        skey = _SNAPSHOT_KEY.format(tid=thread_id)
        seq = await client.xadd(ekey, {"d": json.dumps(event)},
                                maxlen=_STREAM_MAXLEN, approximate=True)
        raw = await client.get(skey)
        snap = json.loads(raw) if raw else _new_snapshot(thread_id)
        _fold(snap, event)
        snap["last_event_id"] = seq
        ttl = _ttl_seconds()
        await client.set(skey, json.dumps(snap), ex=ttl)
        await client.expire(ekey, ttl)
        return seq
    except Exception as exc:
        logger.warning("event_bus.publish failed for %s (%s): %s", thread_id, event.get("type"), exc)
        return None


# ── Consumer API ─────────────────────────────────────────────

async def get_snapshot(thread_id: str) -> Optional[dict[str, Any]]:
    client = await _get_client()
    raw = await client.get(_SNAPSHOT_KEY.format(tid=thread_id))
    return json.loads(raw) if raw else None


async def set_run_status(thread_id: str, status: str) -> None:
    """Patch a run's snapshot status (the restart supervisor uses this — spec §6)."""
    snap = await get_snapshot(thread_id)
    if snap is None:
        return
    snap["run_status"] = status
    client = await _get_client()
    await client.set(_SNAPSHOT_KEY.format(tid=thread_id), json.dumps(snap), ex=_ttl_seconds())


async def iter_run_threads() -> list[str]:
    """All run thread_ids that still have a (non-expired) snapshot. Used by the restart
    supervisor and the TTL sweeper."""
    client = await _get_client()
    prefix, suffix = "agent:run:", ":snapshot"
    out: list[str] = []
    async for key in client.scan_iter(match=f"{prefix}*{suffix}", count=200):
        if key.startswith(prefix) and key.endswith(suffix):
            out.append(key[len(prefix):-len(suffix)])
    return out


async def subscribe(
    thread_id: str,
    last_event_id: Optional[str] = None,
    is_live: Optional[Callable[[], bool]] = None,
) -> AsyncGenerator[tuple[Optional[str], Optional[dict[str, Any]]], None]:
    """Yield ``(seq_id, event)`` for a run: replay everything after ``last_event_id``,
    then — if the run is still live — tail new events until a terminal event. A
    ``(None, None)`` heartbeat is yielded on each idle block so the SSE layer can ping
    and detect disconnects.

    Replay never stops early on a terminal event (a fully-replayed stream may contain a
    pause followed by a resumed continuation); the decision to tail or stop is made from
    the snapshot's current status after replay. ``is_live`` (the executor's run-task
    check) guards the one case the snapshot can't: a run whose status is still ``running``
    but whose executor died in a process restart — we stop instead of tailing forever."""
    client = await _get_client()
    ekey = _EVENTS_KEY.format(tid=thread_id)

    # Replay phase: (last_id, +]  — exclusive start when a cursor is given, else all.
    start = f"({last_event_id}" if last_event_id else "-"
    last_seen = last_event_id or "0"
    entries = await client.xrange(ekey, min=start, max="+")
    for seq, fields in entries:
        last_seen = seq
        ev = _decode(fields)
        if ev is not None:
            yield seq, ev

    snap = await get_snapshot(thread_id)
    if _subscriber_should_stop((snap or {}).get("run_status"), is_live):
        return  # finished, or paused with nothing resuming it

    # Live tail until a terminal event (or the caller stops iterating / disconnects). A
    # /resume subscriber tails THROUGH the momentary paused status because is_live is True.
    while True:
        resp = await client.xread({ekey: last_seen}, block=_BLOCK_MS, count=200)
        if not resp:
            yield None, None  # heartbeat
            snap = await get_snapshot(thread_id)
            if _subscriber_should_stop((snap or {}).get("run_status"), is_live):
                return
            continue
        for _key, entries in resp:
            for seq, fields in entries:
                last_seen = seq
                ev = _decode(fields)
                if ev is None:
                    continue
                yield seq, ev
                if ev.get("type") in _TERMINAL_EVENTS:
                    return


def _decode(fields: dict[str, str]) -> Optional[dict[str, Any]]:
    try:
        return json.loads(fields["d"])
    except Exception:
        return None


# ── Interjection mailbox (spec §2.9) ─────────────────────────

async def interject(thread_id: str, message: str, mode: str = "augment") -> bool:
    """Append a mid-flight interjection to the run's mailbox (RPUSH). Drained by the
    controller at the top of its next loop iteration — never a concurrent write to the
    in-flight graph state. ``mode`` ∈ augment | cancel_step | cancel_run."""
    try:
        client = await _get_client()
        key = _MAILBOX_KEY.format(tid=thread_id)
        await client.rpush(key, json.dumps({"message": message, "mode": mode}))
        await client.expire(key, _ttl_seconds())
        return True
    except Exception as exc:
        logger.warning("event_bus.interject failed for %s: %s", thread_id, exc)
        return False


async def drain_mailbox(thread_id: str) -> list[dict[str, Any]]:
    """Pop all pending interjections for a run (each LPOP is atomic, so a concurrent
    interject is simply read on the next drain)."""
    out: list[dict[str, Any]] = []
    try:
        client = await _get_client()
        key = _MAILBOX_KEY.format(tid=thread_id)
        while True:
            item = await client.lpop(key)
            if item is None:
                break
            try:
                out.append(json.loads(item))
            except Exception:
                pass
    except Exception as exc:
        logger.warning("event_bus.drain_mailbox failed for %s: %s", thread_id, exc)
    return out
