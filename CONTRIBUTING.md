# Contributing to Manifold

Thank you for your interest in contributing to Manifold! This guide will help you get started.

## Getting Started

### Prerequisites

- Python 3.10 or higher
- Git

### Development Setup

```bash
# Clone the repository
git clone https://github.com/fabs133/manifold.git
cd manifold

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows

# Install in development mode with dev dependencies
pip install -e ".[dev]"
```

### Verify Setup

```bash
# Run tests
pytest

# Check formatting
black --check manifold/
ruff check manifold/

# Type checking
mypy manifold/
```

## Development Workflow

### 1. Create a Branch

```bash
git checkout -b feature/your-feature-name
```

### 2. Make Changes

- Write code following the style guidelines below
- Add or update tests as needed
- Update documentation if behavior changes

### 3. Run Checks

All of these must pass before submitting a PR:

```bash
# Format code
black manifold/ tests/

# Lint
ruff check manifold/ tests/

# Type check
mypy manifold/

# Run tests
pytest
```

### 4. Submit a Pull Request

- Push your branch and open a PR against `master`
- Describe what your change does and why
- Reference any related issues

## Code Style

### Formatting

We use **Black** for code formatting with a line length of 100:

```bash
black manifold/ tests/
```

### Linting

We use **Ruff** for linting:

```bash
ruff check manifold/ tests/
```

### Type Hints

All public APIs should have type hints. We use **mypy** for type checking:

```bash
mypy manifold/
```

### Conventions

- Use descriptive variable and function names
- Write docstrings for all public classes and methods
- Keep functions focused and small
- Prefer composition over inheritance

## Project Structure

```
manifold/
├── manifold/           # Core library
│   ├── __init__.py     # Public API (34 exports)
│   └── core/           # Orchestration engine
│       ├── agent.py        # Agent base class
│       ├── context.py      # Immutable context
│       ├── loop_detector.py # Fingerprint-based loop prevention
│       ├── manifest.py     # YAML/JSON manifest loader
│       ├── orchestrator.py # Main execution engine
│       ├── router.py       # Edge-based routing
│       └── spec.py         # Specification contracts
├── tests/              # Test suite
├── docs/               # Documentation
├── examples/           # Usage examples
└── experiments/        # Research experiments
```

## What to Contribute

### Bug Reports

If you find a bug, please open an issue with:
- A clear description of the problem
- Steps to reproduce it
- Expected vs actual behavior
- Python version and OS

### Feature Requests

We welcome suggestions! Open an issue describing:
- The problem you're trying to solve
- Your proposed solution
- Any alternatives you considered

### Code Contributions

Good first contributions:
- Writing additional specs (see `docs/WRITING_SPECS.md`)
- Adding examples for new domains
- Improving documentation
- Writing tests for edge cases

### Integration Requests

Want Manifold to work with a specific tool or framework? Open an issue with the `integration` label describing:
- The tool/framework you want integrated
- Your use case
- Any technical details or constraints

## Writing Specs

Specs are the core abstraction in Manifold. See `docs/WRITING_SPECS.md` for a comprehensive guide on authoring specifications.

Key principles:
- Specs must be **pure** (no side effects, no IO)
- Specs must be **deterministic** (same input = same result)
- Use `suggested_fix` in `SpecResult.fail()` to enable self-correction

## Running Experiments

The `experiments/` directory contains the research experiments from the Manifold paper. See `experiments/README.md` for reproduction instructions.

**Note:** Running experiments requires an OpenAI API key and will incur API costs.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

## Questions?

Open an issue with the `question` label and we'll be happy to help.
