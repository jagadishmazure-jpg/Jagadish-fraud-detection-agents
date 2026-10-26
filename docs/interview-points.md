# Interview points

Short, honest talking points for Jagadish-fraud-detection-agents. Every number quoted is from the
real run shown in the README.

- The cost in fraud operations is investigator time, so I designed for explainable cases, not just scores.
- Two layers on purpose: in the seeded demo the per-transaction score tops out at 50.5 for card-testing probes (threshold 55), and the window-based detector catches the pattern.
- Baselines from clean history only, to avoid poisoning 'normal' with the attack.
- 4 of 4 injected patterns detected with 0 false positives on 8 clean accounts. I describe that as a correctness check, not a detection rate.
- The betterment adds measurement instead of anecdote: a 12-account labelled set with per-pattern precision/recall/F1 and Wilson intervals (macro F1 1.00, but the intervals stay wide because four patterns have one positive account each — the harness refuses to let a small set look like strong evidence).
- A mule ring is a graph problem, not a bigger mule: shared counterparties plus a shared device plus coordinated pass-through across 3+ accounts. Ring accounts pass ~60% onward, below the single-mule 70% line, so the two detectors stay distinct — and payroll-style fan-in scores ~13 and never flags.
- Threshold tuning is human-gated, not automatic: verdicts propose, a named-person single-use approval applies, the change is hash-chained, and its effect is measured on a held-out half. A zero or negative delta is reported, not hidden.
- Triage narratives are templates, not model output: every amount, timestamp, and account id is re-checked against the case record, so the paragraph cannot invent a fact.

## Likely follow-up questions

- How would you lower false positives at scale? (Calibrate weights on labelled history, add per-segment baselines.)
- Where would ML fit? (Behind the same scorer interface, still returning reasons, with model-risk sign-off.)
- How do you handle concept drift? (Monitor flag rates and verdict mix per week; rebuild baselines.)
