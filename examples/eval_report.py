"""Measured eval report on the labelled synthetic set (offline).

Prints per-pattern precision / recall / F1 with Wilson intervals and
the macro F1. The set is synthetic and self-injected: this is a
correctness check on the detectors, NOT a real-world detection rate.
Output is re-checked in CI via scripts/render_docs.py --check.
"""
from fraud import build_labeled_set, evaluate

txns, expected, baselines = build_labeled_set()
result = evaluate(txns, expected, baselines)

print(f"labelled accounts: {result['n_accounts']} "
      f"(8 with an injected pattern, 4 benign fan-in)")
print(f"{'pattern':20} {'tp':>3} {'fp':>3} {'fn':>3} "
      f"{'prec':>6} {'recall':>6} {'f1':>6}  precision CI / recall CI")
for pattern in sorted(result["per_pattern"]):
    m = result["per_pattern"][pattern]
    print(f"{pattern:20} {m['tp']:>3} {m['fp']:>3} {m['fn']:>3} "
          f"{m['precision']:>6.2f} {m['recall']:>6.2f} {m['f1']:>6.2f}  "
          f"{m['precision_ci']} / {m['recall_ci']}")
print(f"macro F1: {result['macro_f1']:.2f}")
print("Note: small self-injected set; intervals show the uncertainty.")
