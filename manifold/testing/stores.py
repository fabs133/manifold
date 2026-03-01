"""
manifold.testing.stores
~~~~~~~~~~~~~~~~~~~~~~~
Storage protocols and a reference SQLite implementation.

All stores are defined as Protocols first. This means:
- The EventConsumer depends only on the protocol, not the implementation
- Tests use in-memory implementations (also defined here)
- Production uses SQLite (defined here)
- Future implementations (Postgres, etc.) just implement the protocol

Protocol summary
----------------
BaselineStore   — append-only store for ConvergenceRecords
                  also holds DriftSignals (they arrive before records
                  and the EventConsumer needs to retrieve them by ID)
SnapshotStore   — versioned store for BaselineSnapshots
ProposalStore   — store for SpecProposals with status transitions
SpecRegistry    — manages spec versions and applies approved proposals
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from manifold.testing.models import (
    BaselineSnapshot,
    ConvergenceRecord,
    DriftSignal,
    ReviewStatus,
    SpecProposal,
)

# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class BaselineStore(Protocol):
    """
    Append-only store for ConvergenceRecords and DriftSignals.

    Records are never modified after writing. They can be marked stale
    (a flag, not deletion) when the spec they were collected under changes.
    """

    async def append(self, record: ConvergenceRecord) -> None:
        """Append a new convergence record."""
        ...

    async def append_signal(self, signal: DriftSignal) -> None:
        """Store a drift signal (for later retrieval by event consumer)."""
        ...

    async def get_signal(self, signal_id: str) -> DriftSignal | None:
        """Retrieve a stored drift signal by ID."""
        ...

    async def total_records(self) -> int:
        """Total number of records (including stale)."""
        ...

    async def records_for_class(
        self,
        input_class: str,
        exclude_stale: bool = True,
        limit: int | None = None,
    ) -> list[ConvergenceRecord]:
        """Fetch records for a specific input class."""
        ...

    async def expected_mad_for_class(self, input_class: str) -> float | None:
        """
        Historical mean MAD for this input class.
        Returns None if fewer than 10 valid records exist.
        """
        ...

    async def sample_fingerprints_for_class(
        self,
        input_class: str,
        n: int,
    ) -> list[str]:
        """Sample n input fingerprints from convergent records for this class."""
        ...

    async def mark_stale_for_spec_version(
        self,
        spec_id: str,
        spec_version: str,
    ) -> int:
        """
        Mark records collected under spec_id@spec_version as stale.
        Returns count of records marked.
        """
        ...

    async def take_snapshot(
        self,
        spec_registry: Any,
        notes: str = "",
    ) -> BaselineSnapshot:
        """Compute and return a snapshot from current records."""
        ...


@runtime_checkable
class SnapshotStore(Protocol):
    """Versioned store for BaselineSnapshots."""

    async def write(self, snapshot: BaselineSnapshot) -> None:
        """Persist a snapshot."""
        ...

    async def latest(self) -> BaselineSnapshot | None:
        """Return the most recent valid snapshot."""
        ...

    async def all(self) -> list[BaselineSnapshot]:
        """Return all snapshots, newest first."""
        ...


@runtime_checkable
class ProposalStore(Protocol):
    """Store for SpecProposals with status transitions."""

    async def write(self, proposal: SpecProposal) -> None:
        """Write a new proposal."""
        ...

    async def get(self, proposal_id: str) -> SpecProposal | None:
        """Retrieve by ID."""
        ...

    async def pending_proposals(self) -> list[SpecProposal]:
        """All proposals awaiting human review."""
        ...

    async def mark_rejected(
        self,
        proposal_id: str,
        reviewer_notes: str,
    ) -> None:
        """Mark a proposal as rejected by reviewer."""
        ...

    async def mark_approved(
        self,
        proposal_id: str,
        reviewer_notes: str,
        applied_at: datetime,
    ) -> None:
        """Mark a proposal as approved and applied."""
        ...


@runtime_checkable
class SpecRegistry(Protocol):
    """Manages spec versions and applies approved proposals."""

    async def current_versions(self) -> dict[str, str]:
        """Return {spec_id: version} for all registered specs."""
        ...

    async def apply_proposal(self, proposal: SpecProposal) -> str:
        """
        Apply an approved proposal to the registry.
        Returns the new spec version string.
        """
        ...


# ---------------------------------------------------------------------------
# In-memory implementations (for tests and development)
# ---------------------------------------------------------------------------


class InMemoryBaselineStore:
    """
    In-memory BaselineStore for tests.

    Thread-safety: not guaranteed. Use for single-threaded tests only.
    """

    def __init__(self) -> None:
        self._records: list[ConvergenceRecord] = []
        self._signals: dict[str, DriftSignal] = {}
        self._stale: set[str] = set()  # run_ids

    async def append(self, record: ConvergenceRecord) -> None:
        self._records.append(record)

    async def append_signal(self, signal: DriftSignal) -> None:
        self._signals[signal.signal_id] = signal

    async def get_signal(self, signal_id: str) -> DriftSignal | None:
        return self._signals.get(signal_id)

    async def total_records(self) -> int:
        return len(self._records)

    async def records_for_class(
        self,
        input_class: str,
        exclude_stale: bool = True,
        limit: int | None = None,
    ) -> list[ConvergenceRecord]:
        result = [
            r
            for r in self._records
            if r.input_class == input_class and (not exclude_stale or r.run_id not in self._stale)
        ]
        if limit:
            result = result[-limit:]
        return result

    async def expected_mad_for_class(self, input_class: str) -> float | None:
        records = await self.records_for_class(input_class)
        if len(records) < 10:
            return None
        return statistics.mean(r.inter_model_mad for r in records)

    async def sample_fingerprints_for_class(
        self,
        input_class: str,
        n: int,
    ) -> list[str]:
        records = await self.records_for_class(input_class, limit=n * 2)
        return [r.input_fingerprint for r in records[:n]]

    async def mark_stale_for_spec_version(
        self,
        spec_id: str,
        spec_version: str,
    ) -> int:
        count = 0
        for r in self._records:
            if r.spec_versions.get(spec_id) == spec_version:
                self._stale.add(r.run_id)
                count += 1
        return count

    async def take_snapshot(
        self,
        spec_registry: Any,
        notes: str = "",
    ) -> BaselineSnapshot:
        valid_records = [r for r in self._records if r.run_id not in self._stale]

        # Compute per-class stats
        classes: dict[str, list[ConvergenceRecord]] = {}
        for r in valid_records:
            classes.setdefault(r.input_class, []).append(r)

        records_by_class = {c: len(rs) for c, rs in classes.items()}
        mad_by_class = {
            c: statistics.mean(r.inter_model_mad for r in rs) for c, rs in classes.items()
        }
        mad_stddev_by_class = {
            c: (statistics.stdev(r.inter_model_mad for r in rs) if len(rs) > 1 else 0.0)
            for c, rs in classes.items()
        }
        confidence_by_class = {
            c: statistics.mean(r.confidence for r in rs) for c, rs in classes.items()
        }

        spec_versions = await spec_registry.current_versions()

        return BaselineSnapshot(
            snapshot_id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc),
            total_records=len(valid_records),
            records_by_class=records_by_class,
            mad_by_class=mad_by_class,
            mad_stddev_by_class=mad_stddev_by_class,
            confidence_by_class=confidence_by_class,
            spec_versions=spec_versions,
            proposals_since_last=[],  # consumer fills this in
            cluster_version=None,
            notes=notes,
        )


class InMemorySnapshotStore:
    def __init__(self) -> None:
        self._snapshots: list[BaselineSnapshot] = []

    async def write(self, snapshot: BaselineSnapshot) -> None:
        self._snapshots.append(snapshot)

    async def latest(self) -> BaselineSnapshot | None:
        valid = [s for s in self._snapshots if s.is_valid]
        return valid[-1] if valid else None

    async def all(self) -> list[BaselineSnapshot]:
        return list(reversed(self._snapshots))


class InMemoryProposalStore:
    def __init__(self) -> None:
        self._proposals: dict[str, SpecProposal] = {}

    async def write(self, proposal: SpecProposal) -> None:
        self._proposals[proposal.proposal_id] = proposal

    async def get(self, proposal_id: str) -> SpecProposal | None:
        return self._proposals.get(proposal_id)

    async def pending_proposals(self) -> list[SpecProposal]:
        return [p for p in self._proposals.values() if p.review_status == ReviewStatus.PENDING]

    async def mark_rejected(self, proposal_id: str, reviewer_notes: str) -> None:
        p = self._proposals.get(proposal_id)
        if p:
            # frozen dataclass → replace
            from dataclasses import replace

            self._proposals[proposal_id] = replace(
                p,
                review_status=ReviewStatus.REJECTED,
                reviewer_notes=reviewer_notes,
            )

    async def mark_approved(
        self,
        proposal_id: str,
        reviewer_notes: str,
        applied_at: datetime,
    ) -> None:
        p = self._proposals.get(proposal_id)
        if p:
            from dataclasses import replace

            self._proposals[proposal_id] = replace(
                p,
                review_status=ReviewStatus.APPROVED,
                reviewer_notes=reviewer_notes,
                applied_at=applied_at,
            )


class InMemorySpecRegistry:
    def __init__(self, initial_versions: dict[str, str] | None = None) -> None:
        self._versions: dict[str, str] = initial_versions or {}
        self._history: list[dict] = []

    async def current_versions(self) -> dict[str, str]:
        return dict(self._versions)

    async def apply_proposal(self, proposal: SpecProposal) -> str:
        old = self._versions.get(proposal.target_spec_id, "0.0.0")
        # Bump patch version
        parts = old.split(".")
        new = f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}" if len(parts) == 3 else "0.0.1"
        self._versions[proposal.target_spec_id] = new
        self._history.append(
            {
                "spec_id": proposal.target_spec_id,
                "old_version": old,
                "new_version": new,
                "proposal_id": proposal.proposal_id,
                "applied_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return new


# ---------------------------------------------------------------------------
# SQLite implementation (production)
# ---------------------------------------------------------------------------


class SQLiteBaselineStore:
    """
    Production BaselineStore backed by SQLite.

    Single file, no external dependencies, suitable for development and
    single-node production. Replace with Postgres-backed implementation
    for multi-node setups.

    Usage
    -----
        store = SQLiteBaselineStore("baseline.db")
        await store.initialise()
    """

    SCHEMA = """
        CREATE TABLE IF NOT EXISTS convergence_records (
            run_id            TEXT PRIMARY KEY,
            timestamp         TEXT NOT NULL,
            input_fingerprint TEXT NOT NULL,
            input_class       TEXT NOT NULL,
            cluster_version   TEXT,
            model_scores      TEXT NOT NULL,  -- JSON
            consensus_score   REAL NOT NULL,
            inter_model_mad   REAL NOT NULL,
            confidence        REAL NOT NULL,
            spec_versions     TEXT NOT NULL,  -- JSON
            raw_outputs       TEXT NOT NULL,  -- JSON
            is_stale          INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_input_class
            ON convergence_records(input_class, is_stale);

        CREATE TABLE IF NOT EXISTS drift_signals (
            signal_id         TEXT PRIMARY KEY,
            data              TEXT NOT NULL  -- full JSON
        );
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None

    async def initialise(self) -> None:
        """Create tables if they don't exist."""
        self._conn = sqlite3.connect(self._db_path)
        self._conn.executescript(self.SCHEMA)
        self._conn.commit()

    def _cx(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Call initialise() before using the store")
        return self._conn

    async def append(self, record: ConvergenceRecord) -> None:
        cx = self._cx()
        cx.execute(
            """INSERT OR IGNORE INTO convergence_records
               (run_id, timestamp, input_fingerprint, input_class,
                cluster_version, model_scores, consensus_score,
                inter_model_mad, confidence, spec_versions, raw_outputs)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                record.run_id,
                record.timestamp.isoformat(),
                record.input_fingerprint,
                record.input_class,
                record.cluster_version,
                json.dumps(record.model_scores),
                record.consensus_score,
                record.inter_model_mad,
                record.confidence,
                json.dumps(record.spec_versions),
                json.dumps(record.raw_outputs),
            ),
        )
        cx.commit()

    async def append_signal(self, signal: DriftSignal) -> None:
        cx = self._cx()
        cx.execute(
            "INSERT OR IGNORE INTO drift_signals (signal_id, data) VALUES (?,?)",
            (signal.signal_id, json.dumps(signal.to_dict())),
        )
        cx.commit()

    async def get_signal(self, signal_id: str) -> DriftSignal | None:
        row = (
            self._cx()
            .execute("SELECT data FROM drift_signals WHERE signal_id=?", (signal_id,))
            .fetchone()
        )
        return DriftSignal.from_dict(json.loads(row[0])) if row else None

    async def total_records(self) -> int:
        row = self._cx().execute("SELECT COUNT(*) FROM convergence_records").fetchone()
        return int(row[0])

    async def records_for_class(
        self,
        input_class: str,
        exclude_stale: bool = True,
        limit: int | None = None,
    ) -> list[ConvergenceRecord]:
        q = "SELECT * FROM convergence_records WHERE input_class=?"
        params: list[Any] = [input_class]
        if exclude_stale:
            q += " AND is_stale=0"
        q += " ORDER BY timestamp DESC"
        if limit:
            q += f" LIMIT {limit}"
        rows = self._cx().execute(q, params).fetchall()
        return [self._row_to_record(r) for r in rows]

    async def expected_mad_for_class(self, input_class: str) -> float | None:
        records = await self.records_for_class(input_class)
        if len(records) < 10:
            return None
        return statistics.mean(r.inter_model_mad for r in records)

    async def sample_fingerprints_for_class(
        self,
        input_class: str,
        n: int,
    ) -> list[str]:
        records = await self.records_for_class(input_class, limit=n * 2)
        return [r.input_fingerprint for r in records[:n]]

    async def mark_stale_for_spec_version(
        self,
        spec_id: str,
        spec_version: str,
    ) -> int:
        # Fetch all non-stale records and filter in Python for compatibility
        rows = self._cx().execute("SELECT * FROM convergence_records WHERE is_stale=0").fetchall()
        records = [self._row_to_record(r) for r in rows]
        stale_ids = [r.run_id for r in records if r.spec_versions.get(spec_id) == spec_version]
        if stale_ids:
            placeholders = ",".join("?" * len(stale_ids))
            self._cx().execute(
                f"UPDATE convergence_records SET is_stale=1 WHERE run_id IN ({placeholders})",
                stale_ids,
            )
            self._cx().commit()
        return len(stale_ids)

    async def take_snapshot(
        self,
        spec_registry: Any,
        notes: str = "",
    ) -> BaselineSnapshot:
        """Delegate to in-memory logic after loading valid records."""
        mem = InMemoryBaselineStore()
        valid_records = (
            self._cx().execute("SELECT * FROM convergence_records WHERE is_stale=0").fetchall()
        )
        for row in valid_records:
            mem._records.append(self._row_to_record(row))
        return await mem.take_snapshot(spec_registry, notes)

    def _row_to_record(self, row: tuple) -> ConvergenceRecord:
        # Column order matches INSERT
        run_id, timestamp, fp, ic, cv, ms, cs, mad, conf, sv, ro, _stale = row
        return ConvergenceRecord(
            run_id=run_id,
            timestamp=datetime.fromisoformat(timestamp),
            input_fingerprint=fp,
            input_class=ic,
            cluster_version=cv,
            model_scores=json.loads(ms),
            consensus_score=cs,
            inter_model_mad=mad,
            confidence=conf,
            spec_versions=json.loads(sv),
            raw_outputs=json.loads(ro),
        )
