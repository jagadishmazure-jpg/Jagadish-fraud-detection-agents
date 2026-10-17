"""Per-transaction anomaly scoring plus signature-based pattern detectors.

Scoring is deliberately transparent: every scored transaction carries the
individual signal values and human-readable reasons, so an investigator
can see exactly why it was flagged. Baselines are built from CLEAN
history (never from the stream being scored).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------


class AccountBaseline:
    """Behavioral baseline for one account, built from clean history."""

    def __init__(self, account_id: str, txns: List[Dict]) -> None:
        self.account_id = account_id
        own = [t for t in txns if t["account_id"] == account_id
               and t["direction"] == "debit"]
        amounts = [t["amount"] for t in own]
        self.mean_amount = statistics.mean(amounts) if amounts else 50.0
        self.std_amount = statistics.pstdev(amounts) if len(amounts) > 1 else 25.0
        self.known_geos = {t["geo"] for t in own}
        self.known_devices = {t["device_id"] for t in own}
        self.known_merchants = {t["merchant"] for t in own}
        # transactions per hour, averaged over active days
        days = {(t["timestamp"][:10]) for t in own}
        self.txns_per_hour = (len(own) / max(len(days), 1)) / 24.0


def build_baselines(txns: List[Dict]) -> Dict[str, AccountBaseline]:
    accounts = {t["account_id"] for t in txns}
    return {a: AccountBaseline(a, txns) for a in accounts}


# ---------------------------------------------------------------------------
# Per-transaction scoring
# ---------------------------------------------------------------------------

def _zscore(value: float, mean: float, std: float) -> float:
    return (value - mean) / std if std > 0 else 0.0


def score_transaction(txn: Dict, baseline: AccountBaseline,
                      recent: Optional[List[Dict]] = None) -> Dict:
    """Score one transaction 0-100 against the account baseline.

    Signals (weights): velocity 30, amount 30, geo/device novelty 25,
    merchant risk 15. `recent` is the account's recent stream, used for
    the velocity signal (transactions in the trailing hour).
    """
    reasons: List[str] = []
    signals: Dict[str, float] = {}

    # --- velocity: txns in the trailing 60 minutes vs baseline rate
    ts = datetime.fromisoformat(txn["timestamp"])
    if recent:
        window = [t for t in recent
                  if t["account_id"] == txn["account_id"]
                  and datetime.fromisoformat(t["timestamp"]) <= ts
                  and datetime.fromisoformat(t["timestamp"]) > ts - timedelta(hours=1)]
        velocity_ratio = len(window) / max(baseline.txns_per_hour, 0.05)
    else:
        velocity_ratio = 1.0
    signals["velocity"] = min(velocity_ratio / 10.0, 1.0)
    if velocity_ratio >= 5:
        reasons.append(f"velocity {velocity_ratio:.1f}x normal rate "
                       f"({len(window) if recent else '?'} txns in trailing hour)")

    # --- amount z-score
    z = _zscore(txn["amount"], baseline.mean_amount, baseline.std_amount)
    signals["amount"] = min(max(z, 0.0) / 4.0, 1.0)
    if z >= 2.5:
        reasons.append(f"amount ${txn['amount']:.2f} is {z:.1f} std above "
                       f"account mean ${baseline.mean_amount:.2f}")

    # --- geo / device novelty
    novelty = 0.0
    if txn["geo"] not in baseline.known_geos:
        novelty += 0.6
        reasons.append(f"new geo {txn['geo']} (known: "
                       f"{len(baseline.known_geos)} locations)")
    if txn["device_id"] not in baseline.known_devices:
        novelty += 0.4
        reasons.append(f"new device {txn['device_id']}")
    signals["novelty"] = min(novelty, 1.0)

    # --- merchant risk: ecom micro-probes and ATM cash-outs are risky
    risk = 0.0
    if txn["channel"] == "atm" and txn["amount"] >= 1000:
        risk = 0.8
        reasons.append(f"large ATM withdrawal ${txn['amount']:.2f}")
    elif txn["channel"] == "ecom" and txn["amount"] < 5:
        risk = 0.7
        reasons.append(f"micro authorization ${txn['amount']:.2f} "
                       f"at {txn['merchant']}")
    signals["merchant_risk"] = risk

    score = round(100 * (0.30 * signals["velocity"]
                         + 0.30 * signals["amount"]
                         + 0.25 * signals["novelty"]
                         + 0.15 * signals["merchant_risk"]), 1)
    return {
        "txn_id": txn["txn_id"],
        "account_id": txn["account_id"],
        "score": score,
        "signals": {k: round(v, 3) for k, v in signals.items()},
        "reasons": reasons,
        "flagged": score >= 55.0,
    }


# ---------------------------------------------------------------------------
# Pattern detectors (signature logic over the scored stream)
# ---------------------------------------------------------------------------

class PatternDetector:
    """Detects the four injected fraud signatures across an account's stream."""

    def __init__(self, txns: List[Dict], scored: Dict[str, Dict]) -> None:
        self.txns = sorted(txns, key=lambda t: t["timestamp"])
        self.scored = scored  # txn_id -> score dict

    def _account_txns(self, account_id: str) -> List[Dict]:
        return [t for t in self.txns if t["account_id"] == account_id]

    def detect_card_testing(self, account_id: str) -> Optional[Dict]:
        """ >=10 sub-$5 ecom auths within any 30-minute window. """
        txns = [t for t in self._account_txns(account_id)
                if t["channel"] == "ecom" and t["amount"] < 5
                and t["direction"] == "debit"]
        for i, t in enumerate(txns):
            start = datetime.fromisoformat(t["timestamp"])
            window = [x for x in txns[i:]
                      if datetime.fromisoformat(x["timestamp"]) - start
                      <= timedelta(minutes=30)]
            if len(window) >= 10:
                return {
                    "pattern": "card_testing",
                    "account_id": account_id,
                    "severity": "high",
                    "evidence": (f"{len(window)} sub-$5 authorizations within "
                                 f"30 minutes starting {t['timestamp']}; "
                                 f"devices: {sorted({x['device_id'] for x in window})}"),
                    "txn_ids": [x["txn_id"] for x in window],
                }
        return None

    def detect_account_takeover(self, account_id: str,
                                baseline: AccountBaseline) -> Optional[Dict]:
        """Probe ($<=2) then high-value burst from a new device+geo."""
        txns = self._account_txns(account_id)
        for i, t in enumerate(txns):
            if not (t["amount"] <= 2.0 and t["channel"] == "ecom"):
                continue
            if (t["device_id"] in baseline.known_devices
                    or t["geo"] in baseline.known_geos):
                continue
            start = datetime.fromisoformat(t["timestamp"])
            burst = [x for x in txns[i + 1:]
                     if datetime.fromisoformat(x["timestamp"]) - start
                     <= timedelta(hours=6)
                     and x["device_id"] == t["device_id"]
                     and x["amount"] >= 200]
            if len(burst) >= 4:
                total = sum(x["amount"] for x in burst)
                return {
                    "pattern": "account_takeover",
                    "account_id": account_id,
                    "severity": "critical",
                    "evidence": (f"probe of ${t['amount']:.2f} from new device "
                                 f"{t['device_id']} in {t['geo']}, followed by "
                                 f"{len(burst)} high-value purchases totaling "
                                 f"${total:,.2f} within 6 hours"),
                    "txn_ids": [t["txn_id"]] + [x["txn_id"] for x in burst],
                }
        return None

    def detect_money_mule(self, account_id: str) -> Optional[Dict]:
        """Fan-in credits from 3+ counterparties, then rapid ATM cash-out."""
        txns = self._account_txns(account_id)
        credits = [t for t in txns if t["direction"] == "credit"]
        counterparties = {t["merchant"] for t in credits}
        if len(counterparties) < 3:
            return None
        last_credit = max(datetime.fromisoformat(t["timestamp"]) for t in credits)
        cashout = [t for t in txns
                   if t["channel"] == "atm" and t["direction"] == "debit"
                   and datetime.fromisoformat(t["timestamp"]) > last_credit
                   and datetime.fromisoformat(t["timestamp"]) - last_credit
                   <= timedelta(hours=24)]
        inflow = sum(t["amount"] for t in credits)
        outflow = sum(t["amount"] for t in cashout)
        if cashout and outflow >= 0.7 * inflow:
            return {
                "pattern": "money_mule",
                "account_id": account_id,
                "severity": "critical",
                "evidence": (f"{len(counterparties)} inbound counterparties "
                             f"(${inflow:,.2f} in), then ${outflow:,.2f} "
                             f"withdrawn via {len(cashout)} ATM transactions "
                             f"within 24h of last credit"),
                "txn_ids": ([t["txn_id"] for t in credits]
                            + [t["txn_id"] for t in cashout]),
            }
        return None

    def detect_merchant_collusion(self, account_id: str) -> Optional[Dict]:
        """ >=6 identical round-dollar charges at one merchant in 7 days. """
        txns = self._account_txns(account_id)
        groups: Dict[Tuple[str, float], List[Dict]] = defaultdict(list)
        for t in txns:
            if t["direction"] == "debit" and t["amount"] == round(t["amount"]) \
                    and t["merchant_category"] != "fraud_probe":
                groups[(t["merchant"], t["amount"])].append(t)
        for (merchant, amount), grp in groups.items():
            if len(grp) < 6:
                continue
            span = (datetime.fromisoformat(max(t["timestamp"] for t in grp))
                    - datetime.fromisoformat(min(t["timestamp"] for t in grp)))
            if span <= timedelta(days=7):
                return {
                    "pattern": "merchant_collusion",
                    "account_id": account_id,
                    "severity": "medium",
                    "evidence": (f"{len(grp)} identical ${amount:,.2f} charges "
                                 f"at {merchant} within {span.days + 1} days — "
                                 f"no organic spend variance"),
                    "txn_ids": [t["txn_id"] for t in grp],
                }
        return None

    def detect_all(self, account_id: str,
                   baseline: AccountBaseline) -> List[Dict]:
        out = []
        for fn in (self.detect_card_testing,
                   lambda a: self.detect_account_takeover(a, baseline),
                   self.detect_money_mule,
                   self.detect_merchant_collusion):
            hit = fn(account_id)
            if hit:
                out.append(hit)
        return out
