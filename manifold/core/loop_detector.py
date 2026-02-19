"""
LoopDetector - Prevents infinite retry loops.

The LoopDetector ensures that retries only happen when the
"situation has changed". This prevents:
- Identical retries that will fail the same way
- Infinite loops where agents repeat the same actions
- Wasted compute on doomed attempts

Key concept: Attempt Fingerprint
- Canonical representation of an attempt's inputs and failures
- If fingerprint repeats → loop detected → stop
"""

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING
import hashlib
import json

if TYPE_CHECKING:
    from manifold.core.context import Context, TraceEntry


@dataclass(frozen=True)
class AttemptFingerprint:
    """
    Canonical fingerprint for a step attempt.

    The fingerprint captures what makes an attempt unique:
    - step_id: Which step was attempted
    - input_hash: Hash of effective inputs
    - tool_calls_hash: Hash of tools used
    - failed_rule_ids: Which specs failed
    - missing_fields: What data was missing

    Two attempts with the same fingerprint are considered "identical"
    and indicate a loop (no progress being made).
    """

    step_id: str
    input_hash: str
    tool_calls_hash: str
    failed_rule_ids: tuple[str, ...]
    missing_fields: tuple[str, ...]
    invalid_fields: tuple[str, ...]

    def __hash__(self) -> int:
        return hash(
            (
                self.step_id,
                self.input_hash,
                self.tool_calls_hash,
                self.failed_rule_ids,
                self.missing_fields,
                self.invalid_fields,
            )
        )

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "input_hash": self.input_hash,
            "tool_calls_hash": self.tool_calls_hash,
            "failed_rule_ids": list(self.failed_rule_ids),
            "missing_fields": list(self.missing_fields),
            "invalid_fields": list(self.invalid_fields),
        }

    def diff(self, other: "AttemptFingerprint") -> dict[str, Any]:
        """
        Compare two fingerprints and return differences.

        Useful for explaining what changed between attempts.
        """
        diffs: dict[str, Any] = {}

        if self.step_id != other.step_id:
            diffs["step_id"] = {"from": self.step_id, "to": other.step_id}

        if self.input_hash != other.input_hash:
            diffs["input_hash"] = {"from": self.input_hash, "to": other.input_hash}

        if self.tool_calls_hash != other.tool_calls_hash:
            diffs["tool_calls_hash"] = {"from": self.tool_calls_hash, "to": other.tool_calls_hash}

        if set(self.failed_rule_ids) != set(other.failed_rule_ids):
            diffs["failed_rule_ids"] = {
                "removed": list(set(self.failed_rule_ids) - set(other.failed_rule_ids)),
                "added": list(set(other.failed_rule_ids) - set(self.failed_rule_ids)),
            }

        if set(self.missing_fields) != set(other.missing_fields):
            diffs["missing_fields"] = {
                "removed": list(set(self.missing_fields) - set(other.missing_fields)),
                "added": list(set(other.missing_fields) - set(self.missing_fields)),
            }

        if set(self.invalid_fields) != set(other.invalid_fields):
            diffs["invalid_fields"] = {
                "removed": list(set(self.invalid_fields) - set(other.invalid_fields)),
                "added": list(set(other.invalid_fields) - set(self.invalid_fields)),
            }

        return diffs

    def has_progress_from(self, previous: "AttemptFingerprint") -> bool:
        """
        Check if this fingerprint shows progress from a previous one.

        Progress means:
        - Fewer failing rules
        - Fewer missing fields
        - Different inputs (new data available)
        """
        # Input changed = new information available
        if self.input_hash != previous.input_hash:
            return True

        # Fewer failing rules = making progress
        if len(self.failed_rule_ids) < len(previous.failed_rule_ids):
            return True

        # Fewer missing fields = data was filled in
        if len(self.missing_fields) < len(previous.missing_fields):
            return True

        # Fewer invalid fields = data was corrected
        if len(self.invalid_fields) < len(previous.invalid_fields):
            return True

        # Different tools tried = different approach
        if self.tool_calls_hash != previous.tool_calls_hash:
            return True

        return False


class LoopDetector:
    """
    Detects and prevents retry loops.

    The LoopDetector:
    1. Computes fingerprints for each attempt
    2. Tracks seen fingerprints per step
    3. Rejects identical retries
    4. Provides diff information for debugging

    Usage:
        detector = LoopDetector()

        for each attempt:
            fingerprint = detector.compute_fingerprint(entry, context)
            if detector.is_loop(fingerprint):
                # Stop! This is an identical retry
                break
            detector.record(fingerprint)
    """

    def __init__(self):
        # step_id -> set of fingerprint hashes
        self._seen: dict[str, set[int]] = {}
        # step_id -> last fingerprint (for diff)
        self._last: dict[str, AttemptFingerprint] = {}

    def compute_fingerprint(
        self, entry: "TraceEntry", context: "Context", input_data: dict[str, Any] | None = None
    ) -> AttemptFingerprint:
        """
        Compute canonical fingerprint for an attempt.

        Args:
            entry: The trace entry for this attempt
            context: Current workflow context
            input_data: Input data passed to the agent

        Returns:
            AttemptFingerprint
        """
        # Hash effective inputs
        input_hash = self._hash_inputs(entry.step_id, context, input_data)

        # Hash tool calls
        tool_calls_hash = self._hash_tool_calls(entry.tool_calls)

        # Extract failed rules
        failed_rules = tuple(sorted([sr.rule_id for sr in entry.spec_results if not sr.passed]))

        # Extract missing fields from spec results
        missing_fields = self._extract_missing_fields(entry.spec_results)

        # Extract invalid fields from spec results
        invalid_fields = self._extract_invalid_fields(entry.spec_results)

        return AttemptFingerprint(
            step_id=entry.step_id,
            input_hash=input_hash,
            tool_calls_hash=tool_calls_hash,
            failed_rule_ids=failed_rules,
            missing_fields=missing_fields,
            invalid_fields=invalid_fields,
        )

    def _hash_inputs(
        self, step_id: str, context: "Context", input_data: dict[str, Any] | None
    ) -> str:
        """Hash the effective inputs for a step."""
        # Include relevant context data
        # For build steps, include the list of generated files to track progress
        generated_files = context.data.get("generated_files", {})
        generated_file_list = sorted(generated_files.keys()) if generated_files else []

        canonical = {
            "step_id": step_id,
            "data_keys": sorted(context.data.keys()),
            "artifact_keys": sorted(context.artifacts.keys()),
            "input_data": input_data,
            "generated_files": generated_file_list,  # Track build progress
        }
        serialized = json.dumps(canonical, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()[:16]

    def _hash_tool_calls(self, tool_calls: tuple) -> str:
        """Hash the tool calls made during an attempt."""
        if not tool_calls:
            return "no_tools"

        canonical = sorted(
            [(tc.name, json.dumps(tc.args, sort_keys=True, default=str)) for tc in tool_calls]
        )
        serialized = json.dumps(canonical)
        return hashlib.sha256(serialized.encode()).hexdigest()[:16]

    def _extract_missing_fields(self, spec_results: tuple) -> tuple[str, ...]:
        """Extract missing field names from spec results."""
        missing = set()
        for sr in spec_results:
            if not sr.passed:
                data = sr.data
                if "missing_field" in data:
                    missing.add(data["missing_field"])
                if "missing_fields" in data:
                    missing.update(data["missing_fields"])
        return tuple(sorted(missing))

    def _extract_invalid_fields(self, spec_results: tuple) -> tuple[str, ...]:
        """Extract invalid field names from spec results."""
        invalid = set()
        for sr in spec_results:
            if not sr.passed:
                data = sr.data
                if "invalid_field" in data:
                    invalid.add(data["invalid_field"])
                if "invalid_fields" in data:
                    invalid.update(data["invalid_fields"])
        return tuple(sorted(invalid))

    def is_loop(self, fingerprint: AttemptFingerprint) -> bool:
        """
        Check if this fingerprint indicates a loop.

        Returns True if we've seen this exact fingerprint before.
        """
        step_id = fingerprint.step_id

        if step_id not in self._seen:
            return False

        return hash(fingerprint) in self._seen[step_id]

    def has_progress(self, fingerprint: AttemptFingerprint) -> bool:
        """
        Check if this fingerprint shows progress from the last attempt.

        Returns True if:
        - This is the first attempt for this step
        - The fingerprint differs from the last one in a meaningful way
        """
        step_id = fingerprint.step_id

        if step_id not in self._last:
            return True  # First attempt

        previous = self._last[step_id]
        return fingerprint.has_progress_from(previous)

    def record(self, fingerprint: AttemptFingerprint) -> None:
        """Record a fingerprint as seen."""
        step_id = fingerprint.step_id

        if step_id not in self._seen:
            self._seen[step_id] = set()

        self._seen[step_id].add(hash(fingerprint))
        self._last[step_id] = fingerprint

    def get_last(self, step_id: str) -> AttemptFingerprint | None:
        """Get the last fingerprint for a step."""
        return self._last.get(step_id)

    def get_diff(self, fingerprint: AttemptFingerprint) -> dict[str, Any] | None:
        """
        Get diff between this fingerprint and the last one for this step.

        Returns None if this is the first attempt.
        """
        previous = self.get_last(fingerprint.step_id)
        if previous is None:
            return None
        return fingerprint.diff(previous)

    def reset(self, step_id: str | None = None) -> None:
        """
        Reset loop detection state.

        Args:
            step_id: If provided, reset only that step. Otherwise reset all.
        """
        if step_id is None:
            self._seen.clear()
            self._last.clear()
        else:
            self._seen.pop(step_id, None)
            self._last.pop(step_id, None)

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about recorded attempts."""
        return {
            "steps_tracked": list(self._seen.keys()),
            "attempts_per_step": {k: len(v) for k, v in self._seen.items()},
            "total_attempts": sum(len(v) for v in self._seen.values()),
        }
