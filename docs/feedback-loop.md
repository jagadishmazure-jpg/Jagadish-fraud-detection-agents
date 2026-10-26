# Human-feedback loop

## The problem

Thresholds set by hand go stale: fraud adapts, and a detector that was
right last quarter over- or under-fires this quarter. The naive fix —
let the system retune itself from its own verdicts — removes the human
from exactly the decision that needs one. A silent threshold change is
an unaudited change to what counts as fraud.

## The loop

`fraud/feedback.py` implements four steps, each with a named owner:

1. **Verdicts.** An analyst resolves a case in the review queue as
   `confirmed_fraud` or `false_positive`. `FeedbackLoop.record_verdict`
   tallies verdicts per pattern.
2. **Proposal.** With at least 5 verdicts on a pattern and precision
   below 0.5, the loop proposes ONE tightening step for that pattern's
   parameter (card-testing count, cash-out ratio, ring score, or flag
   threshold). Fewer than 5 verdicts means no proposal: small samples
   do not move thresholds. A proposal that would leave its parameter's
   bounds is dropped, never clamped silently.
3. **Approval.** The proposal becomes a pending token in
   `ApprovalGate`: named-person approver, single-use, scoped to
   exactly one parameter change, expiring after one hour by default.
   The approver must answer exactly `yes` or `no`. Low-confidence
   answers (`maybe`, `yes?`) and self-contradicting answers (`yes,
   wait, no`) are refused and leave the token pending, so a clear
   decision can still be made. Bypass (no token), absent, rejected,
   reused, and expired tokens all raise; there is no other apply path.
4. **Audit and measurement.** `apply_approved` writes a
   `threshold_change` event (parameter, old value, new value, scope,
   approver) to the hash-chained ledger, then returns new parameters;
   the old parameters are never mutated. `measure_effect` re-runs the
   eval harness under both parameter sets on the held-out half of the
   labelled set and reports the macro-F1 delta — including when the
   change hurts or does nothing. A zero or negative delta is a result,
   not a failure to report.

## What this deliberately does not do

- No automatic application: a proposal without an approval is inert.
- No bulk retuning: one parameter per approval, so each change is
  attributable to one person and one reason.
- No training on verdicts: verdicts move thresholds by fixed steps,
  they do not fit a model. That keeps the effect measurable and
  reversible — the previous parameters are always recoverable from
  the ledger event.
- No generalisation claim: the measured effect is on the synthetic
  held-out half only. Real drift still needs real labelled history.
