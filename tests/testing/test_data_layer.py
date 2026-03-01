"""
Tests for manifold.testing data layer.

Coverage:
- models: construction, derived fields, serialisation round-trip
- stores: in-memory happy path + edge cases
- events: EventBus dispatch, EventConsumer routing
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from manifold.testing.models import (
    BaselineSnapshot,
    ConvergenceRecord,
    DriftSignal,
    DriftType,
    ProposalStatus,
    ReviewStatus,
    SpecProposal,
    _compute_mad,
    _fingerprint,
)
from manifold.testing.stores import (
    InMemoryBaselineStore,
    InMemoryProposalStore,
    InMemorySnapshotStore,
    InMemorySpecRegistry,
    SQLiteBaselineStore,
)
from manifold.testing.events import (
    Event,
    EventBus,
    EventConsumer,
    EventType,
    payload_drift_detected,
    payload_run_completed,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_record(
    input_class: str = "ngo_religious",
    scores: dict | None = None,
    run_id: str | None = None,
    spec_versions: dict | None = None,
) -> ConvergenceRecord:
    return ConvergenceRecord.create(
        run_id=run_id or str(uuid.uuid4()),
        input_data={"name": "Caritas Berlin", "type": "welfare"},
        input_class=input_class,
        cluster_version="v1",
        model_scores=scores or {"gpt4o": 0.8, "gemini": 0.75, "llama": 0.82, "mistral": 0.79},
        spec_versions=spec_versions or {"classify_spec": "1.0.0"},
    )


def make_signal(drift_type: DriftType = DriftType.CRITERIA_GAP) -> DriftSignal:
    return DriftSignal(
        signal_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc),
        drift_type=drift_type,
        input_fingerprint="abc123",
        input_class="ngo_religious",
        model_scores={"gpt4o": 0.8, "gemini": -0.3, "llama": 0.1, "mistral": 0.6},
        observed_mad=0.42,
        expected_mad=0.04,
        baseline_records=150,
        outlier_model=None,
        implicated_specs=["classify_spec"],
        representative_fps=["fp1", "fp2"],
    )


def make_proposal(signal: DriftSignal | None = None) -> SpecProposal:
    s = signal or make_signal()
    return SpecProposal(
        proposal_id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc),
        triggered_by_signal_id=s.signal_id,
        target_spec_id="classify_spec",
        current_spec_version="1.0.0",
        proposed_change="Add 'ambiguous_religious' sub-class to criteria",
        proposed_spec_code="class ClassifySpec(Spec): ...",
        hypothesis="Models diverge because criteria don't cover welfare orgs with religious affiliation",
        drift_examples=["abc123"],
        convergence_examples=["fp1", "fp2"],
        proposal_status=ProposalStatus.VALIDATED,
        validation_mad_before=0.42,
        validation_mad_after=0.06,
        models_converged_after=4,
    )


# ---------------------------------------------------------------------------
# models.py
# ---------------------------------------------------------------------------


class TestComputeMAD:
    def test_identical_values_gives_zero(self):
        assert _compute_mad([0.5, 0.5, 0.5]) == 0.0

    def test_known_values(self):
        # values [0, 1]: mean=0.5, deviations=[0.5, 0.5], MAD=0.5
        assert _compute_mad([0.0, 1.0]) == pytest.approx(0.5)

    def test_empty_gives_zero(self):
        assert _compute_mad([]) == 0.0

    def test_single_value_gives_zero(self):
        assert _compute_mad([0.7]) == 0.0


class TestFingerprint:
    def test_deterministic(self):
        data = {"name": "Caritas", "type": "welfare"}
        assert _fingerprint(data) == _fingerprint(data)

    def test_different_data_different_fingerprint(self):
        assert _fingerprint({"a": 1}) != _fingerprint({"a": 2})

    def test_key_order_irrelevant(self):
        assert _fingerprint({"a": 1, "b": 2}) == _fingerprint({"b": 2, "a": 1})

    def test_returns_16_chars(self):
        assert len(_fingerprint({"x": "y"})) == 16


class TestConvergenceRecordCreate:
    def test_derives_mad_correctly(self):
        record = make_record(scores={"a": 0.0, "b": 1.0})
        assert record.inter_model_mad == pytest.approx(0.5)

    def test_confidence_is_one_minus_mad(self):
        record = make_record(scores={"a": 0.8, "b": 0.8, "c": 0.8})
        assert record.confidence == pytest.approx(1.0)

    def test_confidence_clamps_at_zero(self):
        # MAD > 1.0 should not give negative confidence
        record = make_record(scores={"a": -1.0, "b": 1.0})
        assert record.confidence >= 0.0

    def test_raises_on_empty_scores(self):
        with pytest.raises(ValueError, match="model_scores must not be empty"):
            ConvergenceRecord.create(
                run_id="x",
                input_data={},
                input_class="test",
                cluster_version=None,
                model_scores={},
                spec_versions={},
            )

    def test_serialisation_round_trip(self):
        r = make_record()
        assert ConvergenceRecord.from_dict(r.to_dict()).run_id == r.run_id
        assert ConvergenceRecord.from_dict(r.to_dict()).inter_model_mad == pytest.approx(
            r.inter_model_mad
        )

    def test_timestamp_is_utc_datetime(self):
        r = make_record()
        assert isinstance(r.timestamp, datetime)


class TestDriftSignal:
    def test_serialisation_round_trip(self):
        s = make_signal()
        s2 = DriftSignal.from_dict(s.to_dict())
        assert s2.signal_id == s.signal_id
        assert s2.drift_type == DriftType.CRITERIA_GAP
        assert s2.expected_mad == pytest.approx(0.04)

    def test_null_expected_mad_survives_round_trip(self):
        s = make_signal()
        d = s.to_dict()
        d["expected_mad"] = None
        s2 = DriftSignal.from_dict(d)
        assert s2.expected_mad is None


class TestSpecProposal:
    def test_mad_improvement_computed(self):
        p = make_proposal()
        assert p.mad_improvement == pytest.approx(0.42 - 0.06)

    def test_mad_improvement_none_when_not_validated(self):
        p = SpecProposal(
            proposal_id="x",
            created_at=datetime.now(timezone.utc),
            triggered_by_signal_id="s",
            target_spec_id="classify_spec",
            current_spec_version="1.0.0",
            proposed_change="test",
            proposed_spec_code="...",
            hypothesis="test",
            drift_examples=[],
            convergence_examples=[],
        )
        assert p.mad_improvement is None

    def test_serialisation_round_trip(self):
        p = make_proposal()
        p2 = SpecProposal.from_dict(p.to_dict())
        assert p2.proposal_id == p.proposal_id
        assert p2.proposal_status == ProposalStatus.VALIDATED
        assert p2.review_status == ReviewStatus.PENDING


# ---------------------------------------------------------------------------
# stores.py — InMemory
# ---------------------------------------------------------------------------


class TestInMemoryBaselineStore:
    @pytest.mark.asyncio
    async def test_append_and_count(self):
        store = InMemoryBaselineStore()
        await store.append(make_record())
        await store.append(make_record())
        assert await store.total_records() == 2

    @pytest.mark.asyncio
    async def test_records_for_class_filters(self):
        store = InMemoryBaselineStore()
        await store.append(make_record(input_class="class_a"))
        await store.append(make_record(input_class="class_b"))
        results = await store.records_for_class("class_a")
        assert len(results) == 1
        assert results[0].input_class == "class_a"

    @pytest.mark.asyncio
    async def test_expected_mad_none_below_threshold(self):
        store = InMemoryBaselineStore()
        for _ in range(9):
            await store.append(make_record())
        assert await store.expected_mad_for_class("ngo_religious") is None

    @pytest.mark.asyncio
    async def test_expected_mad_computed_above_threshold(self):
        store = InMemoryBaselineStore()
        for _ in range(10):
            await store.append(make_record())
        mad = await store.expected_mad_for_class("ngo_religious")
        assert mad is not None
        assert 0.0 <= mad <= 1.0

    @pytest.mark.asyncio
    async def test_mark_stale_excludes_from_query(self):
        store = InMemoryBaselineStore()
        r = make_record(spec_versions={"classify_spec": "1.0.0"})
        await store.append(r)
        count = await store.mark_stale_for_spec_version("classify_spec", "1.0.0")
        assert count == 1
        results = await store.records_for_class("ngo_religious", exclude_stale=True)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_stale_records_visible_when_not_excluded(self):
        store = InMemoryBaselineStore()
        r = make_record(spec_versions={"classify_spec": "1.0.0"})
        await store.append(r)
        await store.mark_stale_for_spec_version("classify_spec", "1.0.0")
        results = await store.records_for_class("ngo_religious", exclude_stale=False)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_signal_store_and_retrieve(self):
        store = InMemoryBaselineStore()
        signal = make_signal()
        await store.append_signal(signal)
        retrieved = await store.get_signal(signal.signal_id)
        assert retrieved is not None
        assert retrieved.signal_id == signal.signal_id

    @pytest.mark.asyncio
    async def test_get_signal_returns_none_for_unknown(self):
        store = InMemoryBaselineStore()
        assert await store.get_signal("does-not-exist") is None

    @pytest.mark.asyncio
    async def test_snapshot_stats_correct(self):
        store = InMemoryBaselineStore()
        registry = InMemorySpecRegistry({"classify_spec": "1.0.0"})
        for _ in range(5):
            await store.append(make_record(input_class="class_a"))
        for _ in range(3):
            await store.append(make_record(input_class="class_b"))

        snap = await store.take_snapshot(registry)
        assert snap.total_records == 8
        assert snap.records_by_class["class_a"] == 5
        assert snap.records_by_class["class_b"] == 3
        assert "class_a" in snap.mad_by_class


class TestInMemoryProposalStore:
    @pytest.mark.asyncio
    async def test_write_and_retrieve(self):
        store = InMemoryProposalStore()
        p = make_proposal()
        await store.write(p)
        retrieved = await store.get(p.proposal_id)
        assert retrieved is not None
        assert retrieved.proposal_id == p.proposal_id

    @pytest.mark.asyncio
    async def test_pending_proposals(self):
        store = InMemoryProposalStore()
        await store.write(make_proposal())
        await store.write(make_proposal())
        pending = await store.pending_proposals()
        assert len(pending) == 2

    @pytest.mark.asyncio
    async def test_mark_rejected(self):
        store = InMemoryProposalStore()
        p = make_proposal()
        await store.write(p)
        await store.mark_rejected(p.proposal_id, "criteria are fine")
        updated = await store.get(p.proposal_id)
        assert updated.review_status == ReviewStatus.REJECTED
        assert updated.reviewer_notes == "criteria are fine"

    @pytest.mark.asyncio
    async def test_approved_leaves_pending_list(self):
        store = InMemoryProposalStore()
        p = make_proposal()
        await store.write(p)
        await store.mark_approved(p.proposal_id, "looks good", datetime.now(timezone.utc))
        assert len(await store.pending_proposals()) == 0


class TestInMemorySpecRegistry:
    @pytest.mark.asyncio
    async def test_apply_proposal_bumps_patch_version(self):
        registry = InMemorySpecRegistry({"classify_spec": "1.0.0"})
        p = make_proposal()
        new_version = await registry.apply_proposal(p)
        assert new_version == "1.0.1"

    @pytest.mark.asyncio
    async def test_current_versions(self):
        registry = InMemorySpecRegistry({"a": "1.0.0", "b": "2.1.3"})
        versions = await registry.current_versions()
        assert versions["a"] == "1.0.0"
        assert versions["b"] == "2.1.3"


# ---------------------------------------------------------------------------
# stores.py — SQLite
# ---------------------------------------------------------------------------


class TestSQLiteBaselineStore:
    @pytest.mark.asyncio
    async def test_append_and_retrieve(self, tmp_path):
        store = SQLiteBaselineStore(tmp_path / "test.db")
        await store.initialise()
        r = make_record()
        await store.append(r)
        results = await store.records_for_class("ngo_religious")
        assert len(results) == 1
        assert results[0].run_id == r.run_id

    @pytest.mark.asyncio
    async def test_total_records(self, tmp_path):
        store = SQLiteBaselineStore(tmp_path / "test.db")
        await store.initialise()
        await store.append(make_record())
        await store.append(make_record())
        assert await store.total_records() == 2

    @pytest.mark.asyncio
    async def test_idempotent_append(self, tmp_path):
        """INSERT OR IGNORE — same run_id twice does not duplicate."""
        store = SQLiteBaselineStore(tmp_path / "test.db")
        await store.initialise()
        r = make_record()
        await store.append(r)
        await store.append(r)
        assert await store.total_records() == 1

    @pytest.mark.asyncio
    async def test_signal_round_trip(self, tmp_path):
        store = SQLiteBaselineStore(tmp_path / "test.db")
        await store.initialise()
        s = make_signal()
        await store.append_signal(s)
        s2 = await store.get_signal(s.signal_id)
        assert s2 is not None
        assert s2.drift_type == DriftType.CRITERIA_GAP

    @pytest.mark.asyncio
    async def test_mark_stale(self, tmp_path):
        store = SQLiteBaselineStore(tmp_path / "test.db")
        await store.initialise()
        await store.append(make_record(spec_versions={"classify_spec": "1.0.0"}))
        count = await store.mark_stale_for_spec_version("classify_spec", "1.0.0")
        assert count == 1
        assert len(await store.records_for_class("ngo_religious")) == 0


# ---------------------------------------------------------------------------
# events.py
# ---------------------------------------------------------------------------


class TestEventBus:
    @pytest.mark.asyncio
    async def test_handler_called_on_emit(self):
        bus = EventBus()
        received = []

        async def handler(event: Event):
            received.append(event)

        bus.subscribe(EventType.DRIFT_DETECTED, handler)
        event = Event.create(EventType.DRIFT_DETECTED, "test", {})
        await bus.emit(event)

        assert len(received) == 1
        assert received[0].event_id == event.event_id

    @pytest.mark.asyncio
    async def test_multiple_handlers_all_called(self):
        bus = EventBus()
        calls = []
        bus.subscribe(EventType.DRIFT_DETECTED, AsyncMock(side_effect=lambda e: calls.append("h1")))
        bus.subscribe(EventType.DRIFT_DETECTED, AsyncMock(side_effect=lambda e: calls.append("h2")))

        await bus.emit(Event.create(EventType.DRIFT_DETECTED, "test", {}))
        assert set(calls) == {"h1", "h2"}

    @pytest.mark.asyncio
    async def test_failing_handler_does_not_stop_others(self):
        bus = EventBus()
        calls = []

        async def bad_handler(event):
            raise RuntimeError("oops")

        async def good_handler(event):
            calls.append("ok")

        bus.subscribe(EventType.DRIFT_DETECTED, bad_handler)
        bus.subscribe(EventType.DRIFT_DETECTED, good_handler)

        await bus.emit(Event.create(EventType.DRIFT_DETECTED, "test", {}))
        assert calls == ["ok"]

    @pytest.mark.asyncio
    async def test_no_handlers_does_not_raise(self):
        bus = EventBus()
        await bus.emit(Event.create(EventType.SPEC_UPDATED, "test", {}))

    @pytest.mark.asyncio
    async def test_subscribe_many(self):
        bus = EventBus()
        calls = []
        bus.subscribe_many(
            {
                EventType.DRIFT_DETECTED: AsyncMock(side_effect=lambda e: calls.append("drift")),
                EventType.SPEC_UPDATED: AsyncMock(side_effect=lambda e: calls.append("spec")),
            }
        )
        await bus.emit(Event.create(EventType.DRIFT_DETECTED, "x", {}))
        await bus.emit(Event.create(EventType.SPEC_UPDATED, "x", {}))
        assert "drift" in calls
        assert "spec" in calls


class TestEventConsumer:
    def _make_consumer(self):
        baseline = InMemoryBaselineStore()
        snapshots = InMemorySnapshotStore()
        proposals = InMemoryProposalStore()
        registry = InMemorySpecRegistry({"classify_spec": "1.0.0"})
        correction_runner = AsyncMock()
        bus = EventBus()
        consumer = EventConsumer(
            baseline_store=baseline,
            snapshot_store=snapshots,
            proposal_store=proposals,
            spec_registry=registry,
            correction_runner=correction_runner,
            bus=bus,
            snapshot_interval=5,
        )
        return consumer, baseline, snapshots, proposals, registry, correction_runner, bus

    @pytest.mark.asyncio
    async def test_converged_run_updates_baseline(self):
        consumer, baseline, *_ = self._make_consumer()
        record = make_record()

        event = Event.create(
            EventType.RUN_COMPLETED,
            source="test",
            payload=payload_run_completed(
                run_id=record.run_id,
                success=True,
                had_drift=False,
                drift_signal_id=None,
                convergence_record=record,
            ),
        )
        await consumer._on_run_completed(event)
        assert await baseline.total_records() == 1

    @pytest.mark.asyncio
    async def test_drifted_run_emits_drift_detected(self):
        consumer, baseline, _, _, _, _, bus = self._make_consumer()
        signal = make_signal()
        await baseline.append_signal(signal)

        received_events = []

        async def _capture(e: Event) -> None:
            received_events.append(e)

        bus.subscribe(EventType.DRIFT_DETECTED, _capture)

        event = Event.create(
            EventType.RUN_COMPLETED,
            source="test",
            payload=payload_run_completed(
                run_id="run-1",
                success=True,
                had_drift=True,
                drift_signal_id=signal.signal_id,
                convergence_record=None,
            ),
        )
        await consumer._on_run_completed(event)
        await asyncio.sleep(0)
        assert len(received_events) == 1

    @pytest.mark.asyncio
    async def test_snapshot_taken_at_interval(self):
        consumer, baseline, snapshots, _, registry, _, _ = self._make_consumer()

        for _ in range(4):
            await baseline.append(make_record())

        event = Event.create(
            EventType.RUN_COMPLETED,
            source="test",
            payload=payload_run_completed(
                run_id=str(uuid.uuid4()),
                success=True,
                had_drift=False,
                drift_signal_id=None,
                convergence_record=make_record(),
            ),
        )
        await consumer._on_run_completed(event)

        snap = await snapshots.latest()
        assert snap is not None

    @pytest.mark.asyncio
    async def test_proposal_approved_updates_spec_registry(self):
        consumer, _, _, proposals, registry, _, bus = self._make_consumer()
        p = make_proposal()
        await proposals.write(p)

        event = Event.create(
            EventType.PROPOSAL_APPROVED,
            source="test",
            payload={"proposal_id": p.proposal_id, "reviewer_notes": "looks good"},
        )
        await consumer._on_proposal_approved(event)

        versions = await registry.current_versions()
        assert versions["classify_spec"] == "1.0.1"

    @pytest.mark.asyncio
    async def test_spec_updated_marks_baseline_stale(self):
        consumer, baseline, _, _, _, _, _ = self._make_consumer()
        await baseline.append(make_record(spec_versions={"classify_spec": "1.0.0"}))

        event = Event.create(
            EventType.SPEC_UPDATED,
            source="test",
            payload={
                "spec_id": "classify_spec",
                "old_version": "1.0.0",
                "new_version": "1.0.1",
                "proposal_id": "p1",
            },
        )
        await consumer._on_spec_updated(event)

        records = await baseline.records_for_class("ngo_religious", exclude_stale=True)
        assert len(records) == 0
