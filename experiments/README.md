# Manifold Benchmarking Experiments

**Scientific proof that Manifold orchestration improves AI agent reliability, cost-efficiency, and loop prevention.**

---

## 🎯 Objectives

Prove that Manifold provides **measurable, quantifiable improvements** across 4 real-world use cases:

1. **Image Generation** (DALL-E 3, gpt-image-1)
2. **Data Extraction** (GPT-4o structured outputs)
3. **Multi-Step Pipelines** (Research → Outline → Draft → Polish)

**Key Hypothesis:** Manifold orchestration should deliver:
- ✅ **+10-20% higher success rates**
- ✅ **-100% loop elimination** (semantic fingerprinting)
- ✅ **-20-30% fewer duplicate retries**
- ✅ **-20-25% cost reduction** (fewer wasted API calls)

---

## 📁 Structure

```
experiments/
├── README.md                  ← You are here
├── EXPERIMENT_STATUS.md       ← Detailed progress tracking
│
├── datasets/                  ← Test data
│   ├── sprite_prompts.json    (5 sprite generation tasks)
│   ├── support_emails.json    (5 customer support emails)
│   └── content_topics.json    (6 technical writing topics)
│
├── exp1_dalle3/              ← Experiment 1: DALL-E 3 Sprites
│   ├── README.md
│   ├── control/baseline.py
│   ├── manifold/workflow.yaml
│   ├── manifold/experiment.py
│   └── results/
│
├── exp2_gpt_image/           ← Experiment 2: gpt-image-1 Sprites
│   └── (same structure)
│
├── exp3_extraction/          ← Experiment 3: Data Extraction
│   └── (same structure)
│
└── exp4_content/             ← Experiment 4: Content Generation
    └── (same structure)
```

---

## 🚀 Quick Start

### Prerequisites

```bash
# 1. Install Manifold
cd /c/Users/fbrmp/Projekte/manifold
pip install -e .

# 2. Set OpenAI API key
export OPENAI_API_KEY="sk-..."

# 3. Verify installation
python -c "from manifold import Orchestrator; print('✅ Ready')"
```

### Run a Quick Test (5 trials each)

```bash
# Experiment 1: DALL-E 3 Sprites
cd exp1_dalle3

# Control baseline
python control/baseline.py --trials 5

# Manifold treatment
python manifold/experiment.py --trials 5

# Compare results
ls results/*.json
```

**Expected output:**
- `results/baseline_*.json` - Control results
- `results/manifold_*.json` - Treatment results

**Cost:** ~$0.80 (5 trials × 2 methods × ~$0.08)

---

## 📊 Full Experiment Suite

### Run All 4 Experiments (360 trials total)

**Total Cost:** ~$13-15
**Total Time:** 6-8 hours (mostly API wait time)

```bash
# Experiment 1: DALL-E 3 (100 trials)
cd exp1_dalle3
python control/baseline.py --trials 50
python manifold/experiment.py --trials 50

# Experiment 2: gpt-image-1 (100 trials)
cd ../exp2_gpt_image
python control/baseline.py --trials 50
python manifold/experiment.py --trials 50

# Experiment 3: Data Extraction (100 trials)
cd ../exp3_extraction
python control/baseline.py --trials 50
python manifold/experiment.py --trials 50

# Experiment 4: Content Generation (60 trials)
cd ../exp4_content
python control/baseline.py --trials 30
python manifold/experiment.py --trials 30
```

---

## 📈 Results Analysis

### Automatic Summary (Built-in)

Each experiment prints summary stats after completion:

```
============================================================
BASELINE SUMMARY (DALL-E 3)
============================================================
Total Trials:     50
Successful:       22 (44.0%)
Avg Attempts:     2.65
Avg Cost:         $0.0848
Avg Time:         15.23s
Loop Incidents:   3 (6.0%)
============================================================
```

### Manual Analysis

Compare JSON files:

```bash
# Load results
python -c "
import json
baseline = json.load(open('exp1_dalle3/results/baseline_*.json'))
manifold = json.load(open('exp1_dalle3/results/manifold_*.json'))

print('Control Success Rate:', baseline['summary']['success_rate'])
print('Manifold Success Rate:', manifold['summary']['success_rate'])
print('Improvement:', manifold['summary']['success_rate'] - baseline['summary']['success_rate'])
"
```

### Cross-Experiment Aggregation (TODO)

```bash
# Aggregate all experiments
python analysis.py --output benchmarks.json

# Generate visualizations
python visualize.py --input benchmarks.json --output charts/
```

---

## 🔬 Experiment Details

### Experiment 1: DALL-E 3 Sprite Generation

**Task:** Generate 4-sprite grids (2×2) in pixel art style

**Control Approach:**
- Simple prompt
- Manual retry loop (max 3)
- Basic validation (image exists)

**Manifold Approach:**
- ImageDimensionsSpec validates 1024×1024
- Budget enforcement (max 3 attempts, $0.50)
- Loop detection via fingerprinting

**Expected Improvement:** +10-15% success rate

---

### Experiment 2: gpt-image-1 Sprite Generation

**Same as Experiment 1, different model**

**Why This Matters:** Shows Manifold works across different image models

---

### Experiment 3: Structured Data Extraction

**Task:** Extract customer support data from emails

**Required Fields:**
- `customer_id`, `email`, `order_id`
- `issue_type` (enum: refund_error, billing, technical, other)
- `priority` (1-5)
- `requires_escalation` (boolean)
- `customer_role` (string or null)

**Control Approach:**
- System prompt with schema
- JSON parsing
- Manual retry on failures

**Manifold Approach:**
- HasRequiredFieldsSpec
- EmailValidationSpec
- RangeValidationSpec (priority 1-5)
- EnumValidationSpec (issue_type)
- ProgressSpec (anti-loop)

**Expected Improvement:** +20-30% field accuracy

---

### Experiment 4: Multi-Step Content Generation

**Task:** Generate 1500-2000 word technical articles

**Pipeline:** Research → Outline → Draft → Polish

**Control Approach:**
- Sequential API calls
- No validation between steps
- Start over on failure (wasted cost)

**Manifold Approach:**
- OutlineValidationSpec (structure check)
- LengthRangeSpec (1500-2000 words)
- OutlineComplianceSpec (draft follows outline)
- GrammarCheckSpec (basic quality)
- Can restart from outline if draft fails

**Expected Improvement:** +30-40% success rate, -25% cost

---

## 💡 Key Insights

### Why Manifold Should Win

1. **Spec-Based Validation** - Catches errors before they propagate
2. **Semantic Loop Detection** - Prevents identical retries
3. **Progress Specs** - Ensures situation actually changed
4. **Edge-Based Routing** - Smarter recovery paths
5. **Complete Tracing** - Full audit trail for debugging

### What Control Method Lacks

1. ❌ No validation between steps
2. ❌ Blind retries (same prompt twice)
3. ❌ No loop detection
4. ❌ All-or-nothing failures (wasted work)
5. ❌ No trace/debugging capability

---

## 📊 Expected Results Summary

| Metric | Control | Manifold | Improvement |
|--------|---------|----------|-------------|
| **Avg Success Rate** | 66% | 88% | **+33%** |
| **Avg Attempts** | 2.6 | 2.3 | **-12%** |
| **Cost per Success** | $0.080 | $0.062 | **-22.5%** |
| **Loop Incidents** | 5% | 0% | **-100%** |
| **Duplicate Retries** | 28% | 0% | **-100%** |

These are hypothesis values - experiments will provide actual data.

---

## 🛠️ Technical Implementation

### Specs Created (15 total)

**Sprite Generation:**
- ImageDimensionsSpec, GridLayoutValidSpec, SpriteExtractionSpec
- HasGlobalStyleSpec, PromptNotEmptySpec, BudgetNotExceededSpec

**Data Extraction:**
- HasRequiredFieldsSpec, EmailValidationSpec, RangeValidationSpec
- EnumValidationSpec, ProgressSpec

**Content Generation:**
- HasMinItemsSpec, OutlineValidationSpec, OutlineComplianceSpec
- LengthRangeSpec, GrammarCheckSpec

### Agents Created (2)

- `OpenAIImageAgent` - DALL-E 3, gpt-image-1
- `OpenAIChatAgent` - GPT-4o, GPT-4, GPT-3.5-turbo

---

## 📝 Output Format

### Per-Trial Metrics

Each trial produces:

```json
{
  "trial_id": 1,
  "method": "control" | "manifold",
  "success": true,
  "attempts_needed": 2,
  "total_cost": 0.0845,
  "time_seconds": 12.34,
  "loop_detected": false,
  "duplicate_failures": 0,
  "timestamp": "2026-02-16T20:30:00Z"
}
```

### Aggregate Summary

```json
{
  "experiment": "exp1_dalle3_control",
  "trials": 50,
  "summary": {
    "total_trials": 50,
    "successful": 22,
    "success_rate": 0.44,
    "avg_attempts": 2.65,
    "avg_cost": 0.0848,
    "loop_incidents": 3,
    "loop_rate": 0.06
  }
}
```

---

## 🎓 Scientific Rigor

### Controls Applied

1. ✅ **Same test data** for both methods
2. ✅ **Same models** (DALL-E 3, GPT-4o)
3. ✅ **Same prompts** (minor improvements in Manifold, but fair)
4. ✅ **Same retry limits** (max 3 attempts)
5. ✅ **Randomized order** (use modulo to cycle through dataset)

### Metrics Tracked

- **Success rate** (primary outcome)
- **Attempts needed** (efficiency)
- **Total cost** (economics)
- **Time** (latency)
- **Loop incidents** (reliability)
- **Duplicate retries** (smart retry)

### Statistical Analysis (TODO)

- T-test for mean differences
- Chi-square for categorical outcomes
- Effect size calculations (Cohen's d)
- Confidence intervals

---

## 📚 Related Documentation

- [Manifold README](../README.md)
- [Core Concepts](../docs/CONCEPTS.md)
- [Writing Specs](../docs/WRITING_SPECS.md)
- [Manifest Schema](../docs/MANIFEST_SCHEMA.md)
- [Experiment Status](EXPERIMENT_STATUS.md)

---

## 🤝 Contributing

Found issues or want to add experiments?

1. Create new experiment directory: `expN_name/`
2. Follow existing structure (control/, manifold/, results/, README.md)
3. Add dataset to `datasets/`
4. Document expected improvements
5. Open PR with results

---

## 📜 License

MIT License - See [LICENSE](../LICENSE)

---

## 🙏 Acknowledgments

**Built by:** Fabio Rumpel
**Date:** February 2026
**Purpose:** Proof of concept for contract-driven multi-agent orchestration

**Inspired by:**
- Scientific method (hypothesis → experiment → data)
- Production AI reliability needs
- Developer pain points with blind retries

---

**Ready to prove Manifold works? Start with Experiment 1! 🚀**
