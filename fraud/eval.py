"""Measured evaluation on a labelled synthetic set.

The README's original claim ("4 of 4 injected patterns detected, 0 false
positives on 8 clean accounts") is a demo anecdote, not a measurement.
This harness replaces anecdote with arithmetic: a fixed labelled set of
accounts, each with an expected pattern set, scored per pattern with
precision / recall / F1 and Wilson confidence intervals, plus a macro
average. The set is synthetic and self-injected, so the numbers are a
correctness check on the detectors, NOT a real-world detection rate —
every report says so.

Labeled set composition (12 accounts, all from the seeded generator):
  - 1 card-testing, 1 account-takeover, 1 single money mule,
    1 merchant collusion, 4 mule-ring accounts, 4 benign fan-in
    accounts (payroll-style: one shared source, normal spending).
Detectors run per account; the ring detector runs once over the whole
stream and maps back to its member accounts.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Set, Tuple

from .detect import PatternDetector, build_baselines, score_transaction
from .rings import RingDetector
from .transactions import (
    gen_transactions,
    inject_account_takeover,
    inject_benign_fanin,
    inject_card_testing,
    inject_merchant_collusion,
    inject_money_mule,
    inject_mule_ring,
)

PATTERNS = ("card_testing", "account_takeover", "money_mule",
            "merchant_collusion", "mule_ring")

RING_ACCOUNTS = ("acct-002", "acct-003", "acct-005", "acct-006")
BENIGN_ACCOUNTS = ("acct-008", "acct-009", "acct-011", "acct-012")


def wilson_interval(successes: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score interval for a proportion. n == 0 means no samples:
    the interval spans everything, honestly."""
    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round(max(0.0, centre - half), 4),
            round(min(1.0, centre + half), 4))


def _f1(precision: float, recall: float) -> float:
    if precision + recall <= 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 4)


def build_labeled_set() -> Tuple[List[Dict], Dict[str, Set[str]], Dict]:
    """Return (txns, expected, baselines). `expected` maps account_id to
    its expected pattern set; clean accounts map to the empty set."""
    clean = gen_transactions(n_accounts=12, days=30, seed=42)
    txns = inject_card_testing(clean, "acct-001", n=18, seed=7)
    txns = inject_account_takeover(txns, "acct-004", seed=11)
    txns = inject_money_mule(txns, "acct-007", seed=13)
    txns = inject_merchant_collusion(txns, "acct-010", seed=17)
    txns = inject_mule_ring(txns, list(RING_ACCOUNTS), seed=23)
    txns = inject_benign_fanin(txns, list(BENIGN_ACCOUNTS),
                               "PayrollCo", seed=29)
    expected: Dict[str, Set[str]] = {f"acct-{i + 1:03d}": set()
                                     for i in range(12)}
    expected["acct-001"] = {"card_testing"}
    expected["acct-004"] = {"account_takeover"}
    expected["acct-007"] = {"money_mule"}
    expected["acct-010"] = {"merchant_collusion"}
    for acct in RING_ACCOUNTS:
        expected[acct] = {"mule_ring"}
    return txns, expected, build_baselines(clean)


def split_accounts(account_ids: List[str]) -> Tuple[List[str], List[str]]:
    """Deterministic alternating split: tuning half vs held-out half.
    Used so a threshold change proposed from one half is measured on
    accounts it was never tuned against."""
    ordered = sorted(account_ids)
    return ordered[0::2], ordered[1::2]


def evaluate(txns: List[Dict], expected: Dict[str, Set[str]],
             baselines: Dict, params: Optional[Dict] = None) -> Dict:
    """Run every detector over the labelled set and score per pattern.

    `params` optionally overrides thresholds (keys: flag_threshold,
    card_testing_min, cashout_ratio, ring_score_threshold); defaults
    preserve shipped behaviour.
    """
    p = params or {}
    by_acct: Dict[str, List[Dict]] = {}
    for t in txns:
        by_acct.setdefault(t["account_id"], []).append(t)
    scored = {t["txn_id"]: score_transaction(
        t, baselines[t["account_id"]], by_acct[t["account_id"]],
        flag_threshold=p.get("flag_threshold", 55.0))
        for t in txns}
    detector = PatternDetector(txns, scored)
    ring_hits = {a: True for ring in RingDetector(
        txns, score_threshold=p.get("ring_score_threshold", 70.0)
    ).detect_rings() for a in ring["accounts"]}
    detected: Dict[str, Set[str]] = {}
    for acct in sorted(expected):
        names = {h["pattern"] for h in detector.detect_all(
            acct, baselines[acct],
            params={"card_testing_min": p.get("card_testing_min", 10),
                    "cashout_ratio": p.get("cashout_ratio", 0.7)})}
        if ring_hits.get(acct):
            names.add("mule_ring")
        detected[acct] = names
    per_pattern: Dict[str, Dict] = {}
    for pattern in PATTERNS:
        tp = sum(1 for a in expected
                 if pattern in expected[a] and pattern in detected[a])
        fp = sum(1 for a in expected
                 if pattern not in expected[a] and pattern in detected[a])
        fn = sum(1 for a in expected
                 if pattern in expected[a] and pattern not in detected[a])
        precision = round(tp / (tp + fp), 4) if tp + fp > 0 else 0.0
        recall = round(tp / (tp + fn), 4) if tp + fn > 0 else 0.0
        per_pattern[pattern] = {
            "tp": tp, "fp": fp, "fn": fn,
            "precision": precision, "recall": recall,
            "f1": _f1(precision, recall),
            "precision_ci": wilson_interval(tp, tp + fp),
            "recall_ci": wilson_interval(tp, tp + fn),
        }
    macro_f1 = round(sum(m["f1"] for m in per_pattern.values())
                     / len(per_pattern), 4)
    return {
        "n_accounts": len(expected),
        "per_pattern": per_pattern,
        "macro_f1": macro_f1,
        "detected": {a: sorted(detected[a]) for a in sorted(detected)},
    }
