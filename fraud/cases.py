"""Investigator case assembly: group flagged transactions into a case with
timeline, exposure, signals, and related accounts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

_SEVERITY_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}


class FraudCase:
    _seq = 0

    def __init__(self, account_id: str, patterns: List[Dict],
                 flagged: List[Dict], txns: List[Dict],
                 all_txns: List[Dict]) -> None:
        FraudCase._seq += 1
        self.case_id = f"CASE-{FraudCase._seq:04d}"
        self.account_id = account_id
        self.patterns = patterns
        self.opened_at = datetime.now(timezone.utc).isoformat()

        by_id = {t["txn_id"]: t for t in txns}
        case_txn_ids = {tid for p in patterns for tid in p["txn_ids"]}
        case_txn_ids |= {f["txn_id"] for f in flagged
                         if f["account_id"] == account_id}
        self.txns = sorted(
            (by_id[i] for i in case_txn_ids if i in by_id),
            key=lambda t: t["timestamp"],
        )
        self.timeline = [
            {"timestamp": t["timestamp"], "txn_id": t["txn_id"],
             "amount": t["amount"], "merchant": t["merchant"],
             "channel": t["channel"], "direction": t["direction"]}
            for t in self.txns
        ]
        self.total_exposure = round(
            sum(t["amount"] for t in self.txns if t["direction"] == "debit"), 2)
        top_sev = max((p["severity"] for p in patterns),
                      key=lambda s: _SEVERITY_RANK.get(s, 0),
                      default="low")
        self.top_signals = [p["evidence"] for p in patterns]
        # related accounts: shared devices or merchants with case txns
        case_devices = {t["device_id"] for t in self.txns}
        case_merchants = {t["merchant"] for t in self.txns}
        related = set()
        for t in all_txns:
            if t["account_id"] == account_id:
                continue
            if (t["device_id"] in case_devices
                    or t["merchant"] in case_merchants):
                related.add(t["account_id"])
        self.related_accounts = sorted(related)
        # priority: critical pattern or exposure >= $5k -> critical, etc.
        if top_sev == "critical" or self.total_exposure >= 5000:
            self.priority = "critical"
        elif top_sev == "high" or self.total_exposure >= 1000:
            self.priority = "high"
        elif self.total_exposure >= 200:
            self.priority = "medium"
        else:
            self.priority = "low"

    def summary(self) -> Dict:
        return {
            "case_id": self.case_id,
            "account_id": self.account_id,
            "priority": self.priority,
            "patterns": [p["pattern"] for p in self.patterns],
            "n_transactions": len(self.txns),
            "total_exposure": self.total_exposure,
            "top_signals": self.top_signals,
            "related_accounts": self.related_accounts,
            "opened_at": self.opened_at,
        }


def assemble_case(account_id: str, patterns: List[Dict],
                  scored: List[Dict], txns: List[Dict],
                  all_txns: List[Dict]) -> Optional[FraudCase]:
    """Build an investigator case; None when nothing was flagged."""
    flagged = [s for s in scored if s["flagged"]
               and s["account_id"] == account_id]
    if not flagged and not patterns:
        return None
    return FraudCase(account_id, patterns, flagged, txns, all_txns)
