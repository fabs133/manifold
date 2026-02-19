"""Tests for the LoopDetector — fingerprinting and loop prevention."""

from manifold.core.loop_detector import LoopDetector, AttemptFingerprint


class TestAttemptFingerprint:
    def test_identical_fingerprints_are_equal(self):
        fp1 = AttemptFingerprint(
            step_id="step1",
            input_hash="abc123",
            tool_calls_hash="def456",
            failed_rule_ids=("rule1",),
            missing_fields=("email",),
            invalid_fields=()
        )
        fp2 = AttemptFingerprint(
            step_id="step1",
            input_hash="abc123",
            tool_calls_hash="def456",
            failed_rule_ids=("rule1",),
            missing_fields=("email",),
            invalid_fields=()
        )
        assert hash(fp1) == hash(fp2)

    def test_different_fingerprints_differ(self):
        fp1 = AttemptFingerprint("step1", "abc", "def", ("r1",), (), ())
        fp2 = AttemptFingerprint("step1", "xyz", "def", ("r1",), (), ())
        assert hash(fp1) != hash(fp2)

    def test_to_dict(self):
        fp = AttemptFingerprint("step1", "abc", "def", ("r1", "r2"), ("email",), ())
        d = fp.to_dict()
        assert d["step_id"] == "step1"
        assert d["failed_rule_ids"] == ["r1", "r2"]
        assert d["missing_fields"] == ["email"]

    def test_diff_finds_changes(self):
        fp1 = AttemptFingerprint("step1", "abc", "def", ("r1", "r2"), ("email",), ())
        fp2 = AttemptFingerprint("step1", "abc", "def", ("r1",), (), ())
        diff = fp2.diff(fp1)
        assert "failed_rule_ids" in diff
        assert "missing_fields" in diff

    def test_diff_empty_when_identical(self):
        fp1 = AttemptFingerprint("step1", "abc", "def", ("r1",), (), ())
        fp2 = AttemptFingerprint("step1", "abc", "def", ("r1",), (), ())
        diff = fp1.diff(fp2)
        assert diff == {}

    def test_has_progress_with_fewer_failures(self):
        fp_before = AttemptFingerprint("step1", "abc", "def", ("r1", "r2"), (), ())
        fp_after = AttemptFingerprint("step1", "abc", "def", ("r1",), (), ())
        assert fp_after.has_progress_from(fp_before)

    def test_has_progress_with_different_input(self):
        fp_before = AttemptFingerprint("step1", "old_hash", "def", ("r1",), (), ())
        fp_after = AttemptFingerprint("step1", "new_hash", "def", ("r1",), (), ())
        assert fp_after.has_progress_from(fp_before)

    def test_no_progress_when_identical(self):
        fp_before = AttemptFingerprint("step1", "abc", "def", ("r1",), ("email",), ())
        fp_after = AttemptFingerprint("step1", "abc", "def", ("r1",), ("email",), ())
        assert not fp_after.has_progress_from(fp_before)


class TestLoopDetector:
    def test_first_attempt_not_loop(self):
        detector = LoopDetector()
        fp = AttemptFingerprint("step1", "abc", "def", (), (), ())
        assert not detector.is_loop(fp)

    def test_identical_retry_is_loop(self):
        detector = LoopDetector()
        fp = AttemptFingerprint("step1", "abc", "def", ("r1",), (), ())

        detector.record(fp)
        assert detector.is_loop(fp)

    def test_different_retry_not_loop(self):
        detector = LoopDetector()
        fp1 = AttemptFingerprint("step1", "abc", "def", ("r1",), (), ())
        fp2 = AttemptFingerprint("step1", "xyz", "def", ("r1",), (), ())

        detector.record(fp1)
        assert not detector.is_loop(fp2)

    def test_different_steps_independent(self):
        detector = LoopDetector()
        fp1 = AttemptFingerprint("step1", "abc", "def", (), (), ())
        fp2 = AttemptFingerprint("step2", "abc", "def", (), (), ())

        detector.record(fp1)
        assert not detector.is_loop(fp2)

    def test_has_progress_first_attempt(self):
        detector = LoopDetector()
        fp = AttemptFingerprint("step1", "abc", "def", (), (), ())
        assert detector.has_progress(fp)

    def test_has_progress_with_change(self):
        detector = LoopDetector()
        fp1 = AttemptFingerprint("step1", "abc", "def", ("r1", "r2"), (), ())
        fp2 = AttemptFingerprint("step1", "abc", "def", ("r1",), (), ())

        detector.record(fp1)
        assert detector.has_progress(fp2)

    def test_no_progress_identical(self):
        detector = LoopDetector()
        fp1 = AttemptFingerprint("step1", "abc", "def", ("r1",), (), ())
        fp2 = AttemptFingerprint("step1", "abc", "def", ("r1",), (), ())

        detector.record(fp1)
        assert not detector.has_progress(fp2)

    def test_reset_clears_state(self):
        detector = LoopDetector()
        fp = AttemptFingerprint("step1", "abc", "def", (), (), ())
        detector.record(fp)
        assert detector.is_loop(fp)

        detector.reset()
        assert not detector.is_loop(fp)

    def test_reset_single_step(self):
        detector = LoopDetector()
        fp1 = AttemptFingerprint("step1", "abc", "def", (), (), ())
        fp2 = AttemptFingerprint("step2", "abc", "def", (), (), ())

        detector.record(fp1)
        detector.record(fp2)

        detector.reset("step1")
        assert not detector.is_loop(fp1)
        assert detector.is_loop(fp2)

    def test_get_stats(self):
        detector = LoopDetector()
        fp1 = AttemptFingerprint("step1", "abc", "def", (), (), ())
        fp2 = AttemptFingerprint("step1", "xyz", "def", (), (), ())
        fp3 = AttemptFingerprint("step2", "abc", "def", (), (), ())

        detector.record(fp1)
        detector.record(fp2)
        detector.record(fp3)

        stats = detector.get_stats()
        assert "step1" in stats["steps_tracked"]
        assert "step2" in stats["steps_tracked"]
        assert stats["attempts_per_step"]["step1"] == 2
        assert stats["attempts_per_step"]["step2"] == 1
        assert stats["total_attempts"] == 3
