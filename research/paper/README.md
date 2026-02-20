# Research Paper

**Manifold: Eliminating False Positives in Multi-Agent LLM Systems Through Specification-Driven Orchestration**

Fabio-Eric Rempel, Independent Researcher

## Status

The paper is currently in preparation. LaTeX source and compiled PDF will be added to this directory once finalized.

## Reproducing the Results

The experimental data and scripts are located in the [`experiments/`](../../experiments/) directory:

| Experiment | Directory | Description |
|------------|-----------|-------------|
| EXP1 | [`experiments/exp1_dalle3/`](../../experiments/exp1_dalle3/) | Adversarial image generation (DALL-E 3) |
| EXP2 | [`experiments/exp2_gpt_image/`](../../experiments/exp2_gpt_image/) | Adversarial image generation (GPT Image) |
| EXP3 | [`experiments/exp3_extraction/`](../../experiments/exp3_extraction/) | Structured data extraction |
| EXP4 | [`experiments/exp4_content/`](../../experiments/exp4_content/) | Multi-step content synthesis |

### Data Pipeline

- **Raw results:** Each experiment directory contains `results/` with per-approach JSONL files
- **Consolidated data:** [`experiments/data/consolidated/`](../../experiments/data/consolidated/) — normalized trial data across all experiments
- **Revalidated data:** [`experiments/data/revalidated/`](../../experiments/data/revalidated/) — universal validation applied post-hoc
- **Analysis script:** [`experiments/scripts/analyze.py`](../../experiments/scripts/analyze.py) — generates comparison tables and statistics
- **Consolidation:** [`experiments/scripts/consolidate.py`](../../experiments/scripts/consolidate.py) — normalizes raw results into comparable format
- **Universal validation:** [`experiments/scripts/universal_validator.py`](../../experiments/scripts/universal_validator.py) — applies uniform validation criteria across all approaches

### Key Results

- **EXP3 Structured Extraction:** Manifold 94% true success vs. naive 34% (p < 0.001, Cohen's h = 1.40)
- **False positive rate:** Manifold 0% vs. naive 66%
- **Field-level accuracy:** Manifold 99.1%
- **Cost efficiency:** Manifold achieves higher quality without the 1.5-3.5x cost inflation of smart retry approaches

## Citation

See [`CITATION.cff`](../../CITATION.cff) in the repository root, or use the "Cite this repository" button on GitHub.
