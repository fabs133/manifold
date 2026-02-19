"""Tests that all public API exports are importable and correctly exposed."""


class TestPublicAPI:
    def test_version(self):
        from manifold import __version__

        assert __version__ == "0.1.0"

    def test_context_exports(self):
        from manifold import (
            Context,
            ContextUpdater,
            create_context,
        )

        assert Context is not None
        assert ContextUpdater is not None
        assert create_context is not None

    def test_spec_exports(self):
        from manifold import (
            Spec,
            SpecResult,
        )

        assert Spec is not None
        assert SpecResult is not None

    def test_manifest_exports(self):
        from manifold import (
            ManifestLoader,
            Step,
        )

        assert ManifestLoader is not None
        assert Step is not None

    def test_router_exports(self):
        from manifold import (
            COMPLETE,
            FAIL,
        )

        assert COMPLETE is not None
        assert FAIL is not None

    def test_loop_detection_exports(self):
        from manifold import LoopDetector, AttemptFingerprint

        assert LoopDetector is not None
        assert AttemptFingerprint is not None

    def test_orchestrator_exports(self):
        from manifold import (
            OrchestratorBuilder,
        )

        assert OrchestratorBuilder is not None

    def test_agent_exports(self):
        from manifold import Agent, AgentOutput

        assert Agent is not None
        assert AgentOutput is not None


class TestAllExportsCount:
    def test_all_has_expected_count(self):
        import manifold

        # 34 public exports + __version__
        assert len(manifold.__all__) >= 34
