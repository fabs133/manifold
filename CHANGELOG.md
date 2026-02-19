# Changelog

All notable changes to Manifold will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Restructured repository for publication readiness
- Moved experiment-specific agents and specs to `experiments/lib/`
- Moved sprite harness to `examples/sprite_generation/harness/` (reference implementation)
- Cleaned core `manifold/` package to contain only the orchestration engine
- Added `CONTRIBUTING.md` with development workflow and code style guidelines
- Added minimal test suite for core components

### Fixed
- LICENSE author name corrected
- `.gitignore` updated to exclude secrets and intermediate experiment data

## [0.1.0] - 2026-02-15

### Added
- **Core Orchestration Engine**
  - `Orchestrator` with builder pattern (`OrchestratorBuilder`)
  - `run_workflow()` convenience function for simple execution
  - `WorkflowResult` and `StepExecutionResult` data classes

- **Specification System**
  - `Spec` base class with `evaluate()` contract
  - `SpecResult` with ok/fail/unknown outcomes and `suggested_fix`
  - `SpecEngine` for batch evaluation of pre/post/invariant specs
  - 5 built-in specs: `HasDataField`, `HasArtifact`, `BudgetNotExceeded`, `CandidateNotNone`, `CandidateHasAttribute`

- **Manifest System**
  - `ManifestLoader` supporting YAML and JSON formats
  - `Manifest`, `Step`, `Edge`, `RetryPolicy`, `GlobalConfig` data classes
  - Declarative workflow definitions with validation

- **Router**
  - `Router` with conditional edge evaluation
  - `ConditionEvaluator` supporting: `post_ok`, `failed()`, `has()`, `attempts()`
  - `RetryRouter` for retry-specific routing logic
  - `COMPLETE` and `FAIL` sentinel destinations

- **Loop Detection**
  - `LoopDetector` with semantic fingerprinting (SHA-256)
  - `AttemptFingerprint` capturing step_id, inputs, tools, failed_rules
  - Prevents identical retry cycles automatically

- **Context System**
  - Immutable `Context` with trace, artifacts, and budgets
  - `ContextUpdater` for safe state transitions
  - `create_context()` factory function
  - `Artifact`, `TraceEntry`, `ToolCall`, `SpecResultRef`, `Budgets` data classes

- **Agent System**
  - `Agent` base class with async execution
  - `AgentOutput` with data, artifacts, and tool calls
  - `AgentRegistry` for agent lookup by name
  - `AgentAdapter` for wrapping existing functions as agents

- **Documentation**
  - `README.md` with quick start and feature overview
  - `docs/CONCEPTS.md` - Architecture and design principles
  - `docs/MANIFEST_SCHEMA.md` - Complete manifest reference
  - `docs/WRITING_SPECS.md` - Spec authoring guide

- **Examples**
  - `examples/simple_example/` - Complete working workflow
  - `examples/sprite_generation/` - Domain-specific example with manifest

[Unreleased]: https://github.com/fabs133/manifold/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/fabs133/manifold/releases/tag/v0.1.0
