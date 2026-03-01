"""
manifold.testing.events
~~~~~~~~~~~~~~~~~~~~~~~
Event schema and central EventConsumer.

Architecture
------------
The system is fully event-driven. Every significant state transition
emits an Event. The EventConsumer is the single entry point that
receives all events and decides what to do next.

This means:
- No direct coupling between components (baseline store, correction
  workflow, spec registry don't call each other)
- Full audit trail of every decision
- Easy to replay, test, and extend
- Natural backpressure: the consumer processes one event at a time
  per queue; concurrent runs emit events that queue cleanly

Event flow
----------
    Primary workflow completes
        → RUN_COMPLETED

    EventConsumer receives RUN_COMPLETED
        → reads artifacts from context
        → if DriftSignal found: emits DRIFT_DETECTED
        → if converged: emits BASELINE_UPDATED

    EventConsumer receives DRIFT_DETECTED
        → schedules correction workflow
        → emits CORRECTION_STARTED

    Correction workflow completes
        → CORRECTION_COMPLETED

    EventConsumer receives CORRECTION_COMPLETED
        → reads SpecProposal from result
        → writes to ProposalStore
        → emits PROPOSAL_READY

    Human approves proposal
        → PROPOSAL_APPROVED

    EventConsumer receives PROPOSAL_APPROVED
        → applies to SpecRegistry
        → emits SPEC_UPDATED

    EventConsumer receives SPEC_UPDATED
        → marks affected baseline records as stale (not deleted)
        → triggers snapshot if baseline is large enough
        → emits BASELINE_SNAPSHOT_TAKEN (if triggered)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable

from manifold.testing.models import (
    BaselineSnapshot,
    ConvergenceRecord,
    DriftSignal,
    SpecProposal,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------


class EventType(Enum):
    """
    All events in the system. Ordered by rough lifecycle position.

    PRIMARY WORKFLOW EVENTS
    -----------------------
    RUN_COMPLETED       — a primary workflow run finished (success or fail)
    BASELINE_UPDATED    — a convergent record was appended to the baseline
    DRIFT_DETECTED      — ConvergenceMonitor emitted a DriftSignal

    CORRECTION WORKFLOW EVENTS
    --------------------------
    CORRECTION_STARTED  — correction workflow was triggered for a signal
    CORRECTION_COMPLETED — correction workflow finished
    CORRECTION_FAILED   — correction workflow could not produce a proposal

    PROPOSAL EVENTS
    ---------------
    PROPOSAL_READY      — SpecProposal written, awaiting human review
    PROPOSAL_APPROVED   — human approved a proposal
    PROPOSAL_REJECTED   — human rejected a proposal

    SPEC REGISTRY EVENTS
    --------------------
    SPEC_UPDATED        — a spec was updated in the registry
    BASELINE_STALE      — some baseline records were marked stale after spec change

    SNAPSHOT EVENTS
    ---------------
    BASELINE_SNAPSHOT_TAKEN — a new snapshot was persisted
    """

    # Primary workflow
    RUN_COMPLETED = "run_completed"
    BASELINE_UPDATED = "baseline_updated"
    DRIFT_DETECTED = "drift_detected"

    # Correction workflow
    CORRECTION_STARTED = "correction_started"
    CORRECTION_COMPLETED = "correction_completed"
    CORRECTION_FAILED = "correction_failed"

    # Proposals
    PROPOSAL_READY = "proposal_ready"
    PROPOSAL_APPROVED = "proposal_approved"
    PROPOSAL_REJECTED = "proposal_rejected"

    # Spec registry
    SPEC_UPDATED = "spec_updated"
    BASELINE_STALE = "baseline_stale"

    # Snapshots
    BASELINE_SNAPSHOT_TAKEN = "baseline_snapshot_taken"


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Event:
    """
    A single event in the system.

    Every state transition emits an Event. Events are immutable
    once created. The payload contains the relevant data for handlers.

    Fields
    ------
    event_id    : globally unique identifier
    event_type  : what happened
    timestamp   : UTC
    source      : component that emitted the event (for logging/debugging)
    payload     : type-specific data (see payload shapes below)
    correlation_id : links events that belong to the same logical chain
                     (e.g. all events from one drift→correction→proposal cycle
                     share a correlation_id)
    """

    event_id: str
    event_type: EventType
    timestamp: datetime
    source: str
    payload: dict[str, Any]
    correlation_id: str | None = None

    @classmethod
    def create(
        cls,
        event_type: EventType,
        source: str,
        payload: dict[str, Any],
        correlation_id: str | None = None,
    ) -> "Event":
        return cls(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            source=source,
            payload=payload,
            correlation_id=correlation_id or str(uuid.uuid4()),
        )

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
        }


# ---------------------------------------------------------------------------
# Payload shapes (documentation + helpers)
# ---------------------------------------------------------------------------
#
# These are not enforced at runtime (dicts are flexible), but all handlers
# should follow these shapes. Each factory function is the canonical way
# to build a payload for a given event type.


def payload_run_completed(
    run_id: str,
    success: bool,
    had_drift: bool,
    drift_signal_id: str | None,
    convergence_record: ConvergenceRecord | None,
) -> dict:
    return {
        "run_id": run_id,
        "success": success,
        "had_drift": had_drift,
        "drift_signal_id": drift_signal_id,
        "convergence_record": convergence_record.to_dict() if convergence_record else None,
    }


def payload_drift_detected(signal: DriftSignal) -> dict:
    return {"drift_signal": signal.to_dict()}


def payload_baseline_updated(record: ConvergenceRecord) -> dict:
    return {"convergence_record": record.to_dict()}


def payload_correction_started(
    signal_id: str,
    workflow_run_id: str,
) -> dict:
    return {"signal_id": signal_id, "workflow_run_id": workflow_run_id}


def payload_correction_completed(
    signal_id: str,
    proposal: SpecProposal,
) -> dict:
    return {"signal_id": signal_id, "proposal": proposal.to_dict()}


def payload_correction_failed(
    signal_id: str,
    reason: str,
) -> dict:
    return {"signal_id": signal_id, "reason": reason}


def payload_proposal_ready(proposal: SpecProposal) -> dict:
    return {"proposal": proposal.to_dict()}


def payload_proposal_approved(
    proposal_id: str,
    reviewer_notes: str,
) -> dict:
    return {"proposal_id": proposal_id, "reviewer_notes": reviewer_notes}


def payload_proposal_rejected(
    proposal_id: str,
    reviewer_notes: str,
) -> dict:
    return {"proposal_id": proposal_id, "reviewer_notes": reviewer_notes}


def payload_spec_updated(
    spec_id: str,
    old_version: str,
    new_version: str,
    proposal_id: str,
) -> dict:
    return {
        "spec_id": spec_id,
        "old_version": old_version,
        "new_version": new_version,
        "proposal_id": proposal_id,
    }


def payload_baseline_stale(
    spec_id: str,
    stale_record_count: int,
) -> dict:
    return {"spec_id": spec_id, "stale_record_count": stale_record_count}


def payload_snapshot_taken(snapshot: BaselineSnapshot) -> dict:
    return {"snapshot": snapshot.to_dict()}


# ---------------------------------------------------------------------------
# EventBus — thin async pub/sub
# ---------------------------------------------------------------------------

Handler = Callable[[Event], Awaitable[None]]


class EventBus:
    """
    Minimal async pub/sub bus.

    Handlers are registered per EventType. When an event is emitted,
    all registered handlers for that type are called concurrently.

    This is intentionally thin — no persistence, no retry logic at this
    layer. The EventConsumer (below) is responsible for durability and
    error handling. The bus is just the wiring.

    Usage
    -----
        bus = EventBus()
        bus.subscribe(EventType.DRIFT_DETECTED, my_handler)
        await bus.emit(Event.create(EventType.DRIFT_DETECTED, ...))
    """

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[Handler]] = {}

    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        """Register a handler for an event type."""
        self._handlers.setdefault(event_type, []).append(handler)

    def subscribe_many(
        self,
        handlers: dict[EventType, Handler | list[Handler]],
    ) -> None:
        """Register multiple handlers at once."""
        for event_type, handler_or_list in handlers.items():
            if isinstance(handler_or_list, list):
                for h in handler_or_list:
                    self.subscribe(event_type, h)
            else:
                self.subscribe(event_type, handler_or_list)

    async def emit(self, event: Event) -> None:
        """
        Emit an event and await all handlers.

        Handlers run concurrently. If any handler raises, the exception
        is logged but does not prevent other handlers from running.
        The bus never raises.
        """
        handlers = self._handlers.get(event.event_type, [])
        if not handlers:
            logger.debug("No handlers for %s", event.event_type.value)
            return

        results = await asyncio.gather(
            *[h(event) for h in handlers],
            return_exceptions=True,
        )

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "Handler %d for %s raised: %s",
                    i,
                    event.event_type.value,
                    result,
                    exc_info=result,
                )


# ---------------------------------------------------------------------------
# EventConsumer — the nervous system
# ---------------------------------------------------------------------------


class EventConsumer:
    """
    Central coordinator. All routing logic lives here.

    The EventConsumer subscribes to the EventBus and decides what to do
    in response to each event. It does not contain business logic —
    it delegates to stores, the correction workflow runner, and the spec
    registry. Its job is coordination only.

    Dependencies (injected, all behind protocols defined in stores.py)
    ----------
    baseline_store      : reads/writes ConvergenceRecords
    snapshot_store      : reads/writes BaselineSnapshots
    proposal_store      : reads/writes SpecProposals
    spec_registry       : manages spec versions, applies proposals
    correction_runner   : runs the correction workflow
    bus                 : the EventBus to emit downstream events

    Configuration
    -------------
    snapshot_interval   : take a snapshot every N new convergence records
    """

    def __init__(
        self,
        baseline_store: Any,  # BaselineStore protocol (see stores.py)
        snapshot_store: Any,  # SnapshotStore protocol
        proposal_store: Any,  # ProposalStore protocol
        spec_registry: Any,  # SpecRegistry protocol
        correction_runner: Any,  # CorrectionRunner protocol
        bus: EventBus,
        snapshot_interval: int = 100,
    ) -> None:
        self._baseline_store = baseline_store
        self._snapshot_store = snapshot_store
        self._proposal_store = proposal_store
        self._spec_registry = spec_registry
        self._correction_runner = correction_runner
        self._bus = bus
        self._snapshot_interval = snapshot_interval

        # Wire up handlers
        bus.subscribe_many(
            {
                EventType.RUN_COMPLETED: self._on_run_completed,
                EventType.DRIFT_DETECTED: self._on_drift_detected,
                EventType.CORRECTION_COMPLETED: self._on_correction_completed,
                EventType.CORRECTION_FAILED: self._on_correction_failed,
                EventType.PROPOSAL_APPROVED: self._on_proposal_approved,
                EventType.PROPOSAL_REJECTED: self._on_proposal_rejected,
                EventType.SPEC_UPDATED: self._on_spec_updated,
            }
        )

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _on_run_completed(self, event: Event) -> None:
        """
        A primary workflow run finished.

        If it had drift: emit DRIFT_DETECTED.
        If it converged: append record to baseline, maybe take snapshot.
        """
        p = event.payload
        logger.info(
            "Run completed: run_id=%s success=%s drift=%s",
            p["run_id"],
            p["success"],
            p["had_drift"],
        )

        if p["had_drift"] and p.get("drift_signal_id"):
            # Retrieve the DriftSignal from the baseline store's signal log
            signal = await self._baseline_store.get_signal(p["drift_signal_id"])
            if signal:
                await self._bus.emit(
                    Event.create(
                        EventType.DRIFT_DETECTED,
                        source="event_consumer",
                        payload=payload_drift_detected(signal),
                        correlation_id=event.correlation_id,
                    )
                )
            return

        record_dict = p.get("convergence_record")
        if record_dict:
            record = ConvergenceRecord.from_dict(record_dict)
            await self._baseline_store.append(record)
            await self._bus.emit(
                Event.create(
                    EventType.BASELINE_UPDATED,
                    source="event_consumer",
                    payload=payload_baseline_updated(record),
                    correlation_id=event.correlation_id,
                )
            )

            # Take snapshot if interval hit
            count = await self._baseline_store.total_records()
            if count % self._snapshot_interval == 0:
                await self._maybe_take_snapshot(correlation_id=event.correlation_id)

    async def _on_drift_detected(self, event: Event) -> None:
        """
        Drift was detected. Start the correction workflow.
        """
        signal = DriftSignal.from_dict(event.payload["drift_signal"])
        logger.warning(
            "Drift detected: signal_id=%s type=%s class=%s mad=%.3f (expected=%.3f)",
            signal.signal_id,
            signal.drift_type.value,
            signal.input_class,
            signal.observed_mad,
            signal.expected_mad or 0.0,
        )

        workflow_run_id = str(uuid.uuid4())

        await self._bus.emit(
            Event.create(
                EventType.CORRECTION_STARTED,
                source="event_consumer",
                payload=payload_correction_started(signal.signal_id, workflow_run_id),
                correlation_id=event.correlation_id,
            )
        )

        # Run correction workflow (async, non-blocking for bus)
        asyncio.create_task(self._run_correction(signal, workflow_run_id, event.correlation_id))

    async def _run_correction(
        self,
        signal: DriftSignal,
        workflow_run_id: str,
        correlation_id: str | None,
    ) -> None:
        """Run the correction workflow and emit outcome event."""
        try:
            proposal = await self._correction_runner.run(signal)
            if proposal is not None:
                await self._bus.emit(
                    Event.create(
                        EventType.CORRECTION_COMPLETED,
                        source="event_consumer.correction_runner",
                        payload=payload_correction_completed(signal.signal_id, proposal),
                        correlation_id=correlation_id,
                    )
                )
            else:
                await self._bus.emit(
                    Event.create(
                        EventType.CORRECTION_FAILED,
                        source="event_consumer.correction_runner",
                        payload=payload_correction_failed(
                            signal.signal_id, "Correction workflow produced no proposal"
                        ),
                        correlation_id=correlation_id,
                    )
                )
        except Exception as e:
            logger.error("Correction workflow raised: %s", e, exc_info=True)
            await self._bus.emit(
                Event.create(
                    EventType.CORRECTION_FAILED,
                    source="event_consumer.correction_runner",
                    payload=payload_correction_failed(signal.signal_id, str(e)),
                    correlation_id=correlation_id,
                )
            )

    async def _on_correction_completed(self, event: Event) -> None:
        """Correction workflow produced a proposal. Write it and notify."""
        proposal = SpecProposal.from_dict(event.payload["proposal"])
        await self._proposal_store.write(proposal)
        logger.info(
            "Proposal ready: proposal_id=%s spec=%s mad_improvement=%.3f",
            proposal.proposal_id,
            proposal.target_spec_id,
            proposal.mad_improvement or 0.0,
        )
        await self._bus.emit(
            Event.create(
                EventType.PROPOSAL_READY,
                source="event_consumer",
                payload=payload_proposal_ready(proposal),
                correlation_id=event.correlation_id,
            )
        )

    async def _on_correction_failed(self, event: Event) -> None:
        """Correction workflow could not produce a proposal. Log and escalate."""
        logger.error(
            "Correction failed: signal_id=%s reason=%s",
            event.payload["signal_id"],
            event.payload["reason"],
        )
        # TODO: escalation hook (e.g. Slack notification, PagerDuty)

    async def _on_proposal_approved(self, event: Event) -> None:
        """Human approved a proposal. Apply it to the spec registry."""
        proposal_id = event.payload["proposal_id"]
        reviewer_notes = event.payload["reviewer_notes"]

        proposal = await self._proposal_store.get(proposal_id)
        if proposal is None:
            logger.error("Approved unknown proposal_id=%s", proposal_id)
            return

        old_version = proposal.current_spec_version
        new_version = await self._spec_registry.apply_proposal(proposal)

        await self._bus.emit(
            Event.create(
                EventType.SPEC_UPDATED,
                source="event_consumer",
                payload=payload_spec_updated(
                    spec_id=proposal.target_spec_id,
                    old_version=old_version,
                    new_version=new_version,
                    proposal_id=proposal_id,
                ),
                correlation_id=event.correlation_id,
            )
        )

    async def _on_proposal_rejected(self, event: Event) -> None:
        """Human rejected a proposal. Update status, no spec change."""
        proposal_id = event.payload["proposal_id"]
        logger.info("Proposal rejected: proposal_id=%s", proposal_id)
        await self._proposal_store.mark_rejected(
            proposal_id,
            event.payload.get("reviewer_notes", ""),
        )

    async def _on_spec_updated(self, event: Event) -> None:
        """
        A spec changed. Mark affected baseline records as stale.

        Records collected under the old spec version may no longer be
        comparable to new runs. We mark them stale (not delete — they
        are still evidence of what the old spec produced).
        """
        spec_id = event.payload["spec_id"]
        old_version = event.payload["old_version"]

        stale_count = await self._baseline_store.mark_stale_for_spec_version(spec_id, old_version)

        logger.info(
            "Marked %d baseline records stale after spec update: spec=%s v%s→v%s",
            stale_count,
            spec_id,
            old_version,
            event.payload["new_version"],
        )

        await self._bus.emit(
            Event.create(
                EventType.BASELINE_STALE,
                source="event_consumer",
                payload=payload_baseline_stale(spec_id, stale_count),
                correlation_id=event.correlation_id,
            )
        )

        # Take a snapshot to checkpoint the pre-change baseline
        await self._maybe_take_snapshot(
            notes=f"Triggered by spec update: {spec_id}",
            correlation_id=event.correlation_id,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _maybe_take_snapshot(
        self,
        notes: str = "",
        correlation_id: str | None = None,
    ) -> None:
        """Take a baseline snapshot and emit BASELINE_SNAPSHOT_TAKEN."""
        try:
            snapshot = await self._baseline_store.take_snapshot(
                spec_registry=self._spec_registry,
                notes=notes,
            )
            await self._snapshot_store.write(snapshot)
            await self._bus.emit(
                Event.create(
                    EventType.BASELINE_SNAPSHOT_TAKEN,
                    source="event_consumer",
                    payload=payload_snapshot_taken(snapshot),
                    correlation_id=correlation_id,
                )
            )
            logger.info(
                "Snapshot taken: snapshot_id=%s total_records=%d",
                snapshot.snapshot_id,
                snapshot.total_records,
            )
        except Exception as e:
            logger.error("Failed to take snapshot: %s", e, exc_info=True)
