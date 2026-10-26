# Measured evaluation

The original demo reported "4 of 4 injected patterns detected, 0 false
positives on 8 clean accounts." That is a true statement about one
seeded run, but it is an anecdote, not a measurement: it has no
denominator discipline, no per-pattern breakdown, and no uncertainty.
This harness (`fraud/eval.py`) replaces the anecdote with arithmetic
while staying honest about what the numbers are.

## The labelled set

`build_labeled_set()` builds a fixed 12-account synthetic stream:

| Accounts | Expected label |
|---|---|
| acct-001 | card_testing |
| acct-004 | account_takeover |
| acct-007 | money_mule |
| acct-010 | merchant_collusion |
| acct-002, acct-003, acct-005, acct-006 | mule_ring |
| acct-008, acct-009, acct-011, acct-012 | clean (benign payroll fan-in) |

Baselines come from the clean stream only, exactly as in production
use. The ring detector runs once over the whole stream and maps back
to its member accounts; the four per-account detectors run per account.

## Metrics

Per pattern: true positives, false positives, false negatives,
precision, recall, F1, and Wilson 95% confidence intervals for
precision and recall. Macro F1 is the plain mean of the five per-pattern
F1 scores. Precision or recall with a zero denominator is reported as
0.0, never hidden.

The intervals are the point of the exercise. Four of the five patterns
have a single positive account each, so a perfect 1.00 precision still
carries a Wilson interval of roughly (0.21, 1.00): the harness refuses
to let a small set look like strong evidence. The mule-ring pattern,
with four positive accounts, narrows to roughly (0.51, 1.00).

## Latest run

Output of `python examples/eval_report.py` (real run, re-checked in CI):

<!-- run: python examples/eval_report.py -->
```text
labelled accounts: 12 (8 with an injected pattern, 4 benign fan-in)
pattern               tp  fp  fn   prec recall     f1  precision CI / recall CI
account_takeover       1   0   0   1.00   1.00   1.00  (0.2065, 1.0) / (0.2065, 1.0)
card_testing           1   0   0   1.00   1.00   1.00  (0.2065, 1.0) / (0.2065, 1.0)
merchant_collusion     1   0   0   1.00   1.00   1.00  (0.2065, 1.0) / (0.2065, 1.0)
money_mule             1   0   0   1.00   1.00   1.00  (0.2065, 1.0) / (0.2065, 1.0)
mule_ring              4   0   0   1.00   1.00   1.00  (0.5101, 1.0) / (0.5101, 1.0)
macro F1: 1.00
Note: small self-injected set; intervals show the uncertainty.
```
<!-- /run -->

## How to read this

- This is a correctness check on detectors the repo injects itself. It
  is NOT a real-world detection rate, and it must never be quoted as
  one. Real fraud adapts; this set does not.
- A regression that breaks any detector shows up here as a missed
  pattern or a false positive before it reaches the demo narrative.
- Threshold changes from the feedback loop are measured with
  `measure_effect` on the held-out half of this set (see
  [feedback-loop.md](feedback-loop.md)), never on the accounts the
  change was tuned against.

## What would make this stronger

A larger labelled set (hundreds of accounts per pattern), a held-out
generation seed distinct from the tuning seed, and eventually labelled
history in the shape of real operations data. All three are planned;
none is claimed here.
