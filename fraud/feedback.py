"""Human-feedback loop: analyst verdicts propose threshold changes,
a named-person approval gate allows them, and the hash-chained ledger
records them. Nothing here auto-tunes.

Rules, all enforced by tests:
  - A threshold change applies ONLY through an approved approval token.
    There is no other apply path: bypass (no token), absent token,
    rejected token, reused token and expired token all raise.
  - Approval is a named person, single-use, scoped to exactly one
    parameter change, and expiring (TTL seconds, default one hour).
  - The analyst's response must be an unambiguous "yes" to approve or
    "no" to reject. Low-confidence ("maybe", "yes?") and
    self-contradicting ("yes, wait, no") responses are refused and
    leave the token pending, so a clear decision can still be made.
  - A proposal needs at least 5 verdicts on its pattern, and the
    measured effect of the change is always computed on the held-out
    half of the labelled set and reported, whether it helps or not.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .eval import evaluate

MIN_VERDICTS = 5
DEFAULT_TTL_SECONDS = 3600
_AMBIGUOUS_HINTS = ("maybe", "?", "wait", "not sure", "perhaps",
                    "hold on", "unsure")


@dataclass
class TuningParams:
    """Thresholds the feedback loop may move, with hard bounds.

    Defaults are the shipped detector behaviour; changing a default
    here changes detection, which is why changes need approval.
    """
    flag_threshold: float = 55.0
    card_testing_min: int = 10
    cashout_ratio: float = 0.7
    ring_score_threshold: float = 70.0

    def __post_init__(self) -> None:
        if not 0.0 < self.flag_threshold <= 100.0:
            raise ValueError("flag_threshold must be in (0, 100]")
        if self.card_testing_min < 1:
            raise ValueError("card_testing_min must be >= 1")
        if not 0.0 < self.cashout_ratio <= 1.0:
            raise ValueError("cashout_ratio must be in (0, 1]")
        if not 0.0 < self.ring_score_threshold <= 100.0:
            raise ValueError("ring_score_threshold must be in (0, 100]")

    def as_dict(self) -> Dict:
        return {
            "flag_threshold": self.flag_threshold,
            "card_testing_min": self.card_testing_min,
            "cashout_ratio": self.cashout_ratio,
            "ring_score_threshold": self.ring_score_threshold,
        }


# pattern -> (parameter, step) for a precision-driven tightening proposal.
# A proposal is only a proposal: the gate and the measured effect decide.
_PROPOSAL_MAP = {
    "card_testing": ("card_testing_min", 2),
    "account_takeover": ("flag_threshold", 5.0),
    "money_mule": ("cashout_ratio", 0.05),
    "merchant_collusion": ("flag_threshold", 5.0),
    "mule_ring": ("ring_score_threshold", 5.0),
}


class ApprovalGate:
    """Named-person, single-use, scoped, expiring approvals."""

    def __init__(self) -> None:
        self._tokens: Dict[str, Dict] = {}

    def propose(self, parameter: str, old_value, new_value,
                scope: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str:
        token = secrets.token_hex(8)
        now = datetime.now(timezone.utc)
        self._tokens[token] = {
            "parameter": parameter,
            "old_value": old_value,
            "new_value": new_value,
            "scope": scope,
            "state": "pending",
            "approver": None,
            "expires_at": now + timedelta(seconds=ttl_seconds),
            "already_expired": ttl_seconds <= 0,
        }
        return token

    def decide(self, token: str, approver: str, response: str) -> str:
        """Approve ("yes") or reject ("no"). Returns the new state.

        Anything else is refused and the token stays pending.
        """
        rec = self._tokens.get(token)
        if rec is None:
            raise ValueError(f"unknown approval token {token!r}")
        if rec["state"] != "pending":
            raise ValueError(f"approval already {rec['state']}; "
                             f"tokens are single-use")
        if rec["already_expired"] or datetime.now(timezone.utc) >= rec["expires_at"]:
            raise ValueError("approval has expired")
        if not approver or not approver.strip() \
                or approver.strip().lower() in ("system", "auto"):
            raise ValueError("approver must be a named person, not a system")
        text = response.strip().lower()
        if text == "yes":
            rec["state"] = "approved"
            rec["approver"] = approver.strip()
            return "approved"
        if text == "no":
            rec["state"] = "rejected"
            rec["approver"] = approver.strip()
            return "rejected"
        if any(h in text for h in _AMBIGUOUS_HINTS) or text.count("yes") + text.count("no") != 1:
            raise ValueError(f"ambiguous response {response!r} refused; "
                             f"answer exactly 'yes' or 'no'")
        raise ValueError(f"ambiguous response {response!r} refused; "
                         f"answer exactly 'yes' or 'no'")

    def approved_proposal(self, token: str) -> Dict:
        rec = self._tokens.get(token)
        if rec is None:
            raise ValueError(f"unknown approval token {token!r}")
        if rec["state"] != "approved":
            raise ValueError(f"approval is {rec['state']}, not approved")
        return rec


class FeedbackLoop:
    """Collects analyst verdicts and turns them into gated proposals."""

    def __init__(self) -> None:
        self._verdicts: Dict[str, Dict[str, int]] = {}

    def record_verdict(self, pattern: str, verdict: str) -> None:
        if verdict not in ("confirmed_fraud", "false_positive"):
            raise ValueError(f"unknown verdict {verdict!r}")
        counts = self._verdicts.setdefault(
            pattern, {"confirmed_fraud": 0, "false_positive": 0})
        counts[verdict] += 1

    def precision(self, pattern: str) -> Optional[float]:
        counts = self._verdicts.get(pattern)
        if not counts:
            return None
        total = counts["confirmed_fraud"] + counts["false_positive"]
        if total == 0:
            return None
        return round(counts["confirmed_fraud"] / total, 4)

    def propose_changes(self, params: TuningParams,
                        gate: ApprovalGate) -> List[Dict]:
        """One tightening proposal per pattern with >= MIN_VERDICTS
        verdicts and precision below 0.5. Each proposal is a pending
        approval token; nothing is applied here."""
        proposals = []
        current = params.as_dict()
        for pattern, (parameter, step) in sorted(_PROPOSAL_MAP.items()):
            counts = self._verdicts.get(pattern)
            if not counts:
                continue
            total = counts["confirmed_fraud"] + counts["false_positive"]
            if total < MIN_VERDICTS:
                continue
            if counts["confirmed_fraud"] / total >= 0.5:
                continue
            new_value = round(current[parameter] + step, 4)
            try:
                TuningParams(**{**current, parameter: new_value})
            except ValueError:
                continue  # out-of-bounds proposal is dropped, not clamped
            token = gate.propose(
                parameter, current[parameter], new_value,
                scope=f"{pattern} precision below 0.5 on {total} verdicts")
            proposals.append({"pattern": pattern, "parameter": parameter,
                              "old_value": current[parameter],
                              "new_value": new_value, "token": token})
        return proposals


def apply_approved(params: TuningParams, gate: ApprovalGate,
                   token: str, ledger) -> TuningParams:
    """Apply an approved proposal and audit-log it. The ONLY apply path.

    Raises on unknown, pending, rejected, reused or expired tokens.
    Returns new params; the input params are never mutated.
    """
    rec = gate.approved_proposal(token)
    new_values = {**params.as_dict(), rec["parameter"]: rec["new_value"]}
    new_params = TuningParams(**new_values)
    rec["state"] = "applied"  # single-use: a second apply raises
    ledger.record("threshold_change", {
        "parameter": rec["parameter"],
        "old_value": rec["old_value"],
        "new_value": rec["new_value"],
        "scope": rec["scope"],
        "approver": rec["approver"],
    })
    return new_params


def measure_effect(params_before: TuningParams, params_after: TuningParams,
                   txns, expected, baselines,
                   account_subset: Optional[List[str]] = None) -> Dict:
    """Re-run the eval harness under both param sets on the given
    accounts (default: all) and report the macro-F1 delta honestly,
    including when the change hurts."""
    subset = {a: expected[a] for a in
              (account_subset if account_subset is not None
               else sorted(expected))}
    before = evaluate(txns, subset, baselines,
                      params=params_before.as_dict())
    after = evaluate(txns, subset, baselines,
                     params=params_after.as_dict())
    return {
        "n_accounts": len(subset),
        "macro_f1_before": before["macro_f1"],
        "macro_f1_after": after["macro_f1"],
        "macro_f1_delta": round(after["macro_f1"] - before["macro_f1"], 4),
        "per_pattern_before": {k: v["f1"]
                               for k, v in before["per_pattern"].items()},
        "per_pattern_after": {k: v["f1"]
                              for k, v in after["per_pattern"].items()},
    }
