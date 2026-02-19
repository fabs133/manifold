# Research Paper

**Manifold: Eliminating False Positives in Multi-Agent LLM Systems Through Specification-Driven Orchestration**

Fabio-Eric Rempel, Independent Researcher

## Files

| File | Description |
|------|-------------|
| `manifold_paper.pdf` | Compiled paper (ready to read) |
| `main.tex` | LaTeX source |
| `neurips_2024.sty` | NeurIPS 2024 style file |
| `references.bib` | Bibliography |
| `figures/` | All figures referenced in the paper |

## Figures

| Figure | File | Description |
|--------|------|-------------|
| Figure 1 | `fig1_success_rates.png` | Success rates across approaches and experiments |
| Figure 2 | `fig2_cost_distributions.png` | Cost distributions per approach |
| Figure 3 | `fig3_exp3_quality.png` | EXP3 structured extraction quality analysis |
| Figure 4 | `fig4_exp4_quality.png` | EXP4 content synthesis quality analysis |
| Figure 5 | `fig5_cross_experiment.png` | Cross-experiment comparison |

## Reproducing the Results

The experimental data and scripts referenced in the paper are located in the [`experiments/`](../../experiments/) directory:

| Paper Section | Experiment | Directory | Description |
|--------------|------------|-----------|-------------|
| Section 4.1 | EXP1 | [`experiments/exp1_dalle3/`](../../experiments/exp1_dalle3/) | Adversarial image generation (DALL-E 3) |
| Section 4.1 | EXP2 | [`experiments/exp2_gpt_image/`](../../experiments/exp2_gpt_image/) | Adversarial image generation (GPT Image) |
| Section 4.2 | EXP3 | [`experiments/exp3_extraction/`](../../experiments/exp3_extraction/) | Structured data extraction |
| Section 4.3 | EXP4 | [`experiments/exp4_content/`](../../experiments/exp4_content/) | Multi-step content synthesis |

### Data Pipeline

The consolidated results and analysis scripts are in:

- **Raw results:** Each experiment directory contains `results/` with per-approach JSONL files
- **Consolidated data:** [`experiments/data/consolidated/`](../../experiments/data/consolidated/) — normalized trial data across all experiments
- **Revalidated data:** [`experiments/data/revalidated/`](../../experiments/data/revalidated/) — universal validation applied post-hoc
- **Analysis script:** [`experiments/scripts/analyze.py`](../../experiments/scripts/analyze.py) — generates the comparison tables and statistics from the paper
- **Consolidation:** [`experiments/scripts/consolidate.py`](../../experiments/scripts/consolidate.py) — normalizes raw results into comparable format
- **Universal validation:** [`experiments/scripts/universal_validator.py`](../../experiments/scripts/universal_validator.py) — applies uniform validation criteria across all approaches

### Key Results (from paper)

- **EXP3 Structured Extraction:** Manifold 94% true success vs. naive 34% (p < 0.001, Cohen's h = 1.40)
- **False positive rate:** Manifold 0% vs. naive 66%
- **Field-level accuracy:** Manifold 99.1%
- **Cost efficiency:** Manifold achieves higher quality without the 1.5-3.5x cost inflation of smart retry approaches

## Building the Paper

The paper is formatted for NeurIPS 2024. To compile locally:

```bash
cd research/paper
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```

Or upload the contents of this directory to [Overleaf](https://www.overleaf.com/).

## Citation

See [`CITATION.cff`](../../CITATION.cff) in the repository root, or use the "Cite this repository" button on GitHub.
