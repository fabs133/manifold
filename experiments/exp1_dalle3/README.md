# Experiment 1: DALL-E 3 Sprite Generation

**Goal:** Prove that Manifold orchestration improves reliability and cost-efficiency for sprite generation compared to baseline manual retries.

## Hypothesis

Manifold should provide:
- **Higher success rate** (10-20% improvement)
- **Fewer duplicate retries** (0% vs 28% in control)
- **Better cost efficiency** (fewer wasted API calls)
- **Complete traceability** (audit trail of all decisions)

## Experimental Design

### Control Group (Baseline)
- Manual retry loop (up to 3 attempts)
- Simple prompt without grid constraints
- Basic validation (just checks image exists)
- No loop detection
- No progress tracking

**Files:**
- `control/baseline.py` - Control experiment runner

### Treatment Group (Manifold)
- Spec-driven orchestration
- ImageDimensionsSpec validates output
- Budget enforcement (max 3 attempts, $0.50 limit)
- Semantic loop detection
- Complete trace logging

**Files:**
- `manifold/workflow.yaml` - Declarative workflow
- `manifold/experiment.py` - Treatment experiment runner

## Running the Experiments

### Prerequisites

```bash
# Set OpenAI API key
export OPENAI_API_KEY="sk-..."

# Install manifold (if not already)
cd /c/Users/fbrmp/Projekte/manifold
pip install -e .
```

### Run Control (Baseline)

```bash
cd /c/Users/fbrmp/Projekte/manifold/experiments/exp1_dalle3
python control/baseline.py --trials 50
```

### Run Treatment (Manifold)

```bash
cd /c/Users/fbrmp/Projekte/manifold/experiments/exp1_dalle3
python manifold/experiment.py --trials 50
```

### Run Both (Comparison)

```bash
# Quick test (5 trials each)
python control/baseline.py --trials 5
python manifold/experiment.py --trials 5

# Full experiment (50 trials each)
python control/baseline.py --trials 50
python manifold/experiment.py --trials 50
```

## Results

Results are saved to `results/` directory:
- `baseline_YYYYMMDD_HHMMSS.json` - Control results
- `manifold_YYYYMMDD_HHMMSS.json` - Treatment results

### Metrics Collected

For each trial:
- `success`: Whether generation met requirements
- `attempts_needed`: Number of API calls made
- `total_cost`: Total API cost in USD
- `time_seconds`: Wall-clock time
- `loop_detected`: Whether semantic loop occurred
- `duplicate_failures`: Number of identical retry failures

### Expected Results

**Control (Baseline):**
- Success rate: 40-50%
- Avg attempts: 2.5-2.8
- Loop incidents: 5-10%
- Duplicate retries: 20-30%

**Treatment (Manifold):**
- Success rate: 55-65%
- Avg attempts: 2.2-2.5
- Loop incidents: 0%
- Duplicate retries: 0%

**Improvement:**
- +10-20% success rate
- -10% fewer attempts
- -100% loop prevention
- -100% duplicate retry elimination

## Cost Estimate

- **Control**: 50 trials × 2.6 avg attempts × $0.04 = ~$5.20
- **Treatment**: 50 trials × 2.3 avg attempts × $0.04 = ~$4.60
- **Total**: ~$10

Savings per trial: $0.012 (11.5% cost reduction)

## Analysis

After running experiments, use `analysis.py` to compare results:

```bash
python ../analysis.py \
  --control results/baseline_*.json \
  --treatment results/manifold_*.json \
  --output comparison_exp1.json
```

This generates:
- Statistical significance tests
- Improvement percentages
- Cost/benefit analysis
- Visualizations
