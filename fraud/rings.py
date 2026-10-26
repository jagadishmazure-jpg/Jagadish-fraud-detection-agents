"""Mule RING detection: a graph layer over accounts, counterparties and devices.

This is deliberately distinct from the single-mule detector in detect.py.
A single mule is one account with fan-in credits and a rapid cash-out.
A ring is a SET of accounts that move money together: shared inbound
counterparties, shared devices, and coordinated pass-through (credits in,
money out fast) across the set. One account, however mule-like, is never
a ring; a payroll or marketplace payout fan-in, however large, is never
a ring either, because the money is not passed through onward.

Graph model (all fields already exist on the transaction dicts):
  - credit edge: counterparty (the merchant on a credit) -> account
  - device edge: account <-> device_id (shared devices link accounts)
  - cash-out edge: account -> ATM debits after its last credit

Ring score (0-100) for a connected component of accounts:
  - shared counterparties: 40 points, scaled by min(shared, 3) / 3
  - shared devices: 30 points when >= 2 accounts share a device
  - pass-through: 30 points scaled by the fraction of accounts whose
    ATM outflow within 48h of their last credit is >= 50% of inflow
A component flags when it has >= 3 accounts and scores >= threshold.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

RING_MIN_ACCOUNTS = 3
RING_SCORE_THRESHOLD = 70.0
PASS_THROUGH_RATIO = 0.5
PASS_THROUGH_WINDOW_HOURS = 48


def _ts(txn: Dict) -> datetime:
    return datetime.fromisoformat(txn["timestamp"])


def _account_stats(txns: List[Dict]) -> Dict[str, Dict]:
    """Per-account fan-in, device and pass-through facts."""
    by_acct: Dict[str, List[Dict]] = defaultdict(list)
    for t in txns:
        by_acct[t["account_id"]].append(t)
    stats: Dict[str, Dict] = {}
    for acct, rows in by_acct.items():
        credits = [t for t in rows if t["direction"] == "credit"]
        counterparties = {t["merchant"] for t in credits}
        inflow = round(sum(t["amount"] for t in credits), 2)
        devices = {t["device_id"] for t in rows}
        outflow = 0.0
        if credits:
            last_credit = max(_ts(t) for t in credits)
            cashout = [t for t in rows
                       if t["channel"] == "atm" and t["direction"] == "debit"
                       and last_credit < _ts(t) <= last_credit + timedelta(
                           hours=PASS_THROUGH_WINDOW_HOURS)]
            outflow = round(sum(t["amount"] for t in cashout), 2)
        stats[acct] = {
            "counterparties": counterparties,
            "inflow": inflow,
            "devices": devices,
            "outflow": outflow,
            "pass_through": (outflow / inflow) if inflow > 0 else 0.0,
            "txn_ids": [t["txn_id"] for t in rows],
        }
    return stats


def _components(stats: Dict[str, Dict]) -> List[Set[str]]:
    """Connected components of accounts linked by a shared counterparty
    or a shared device. Singletons are returned too (callers filter)."""
    counterparty_to_accts: Dict[str, Set[str]] = defaultdict(set)
    device_to_accts: Dict[str, Set[str]] = defaultdict(set)
    for acct, st in stats.items():
        for cp in st["counterparties"]:
            counterparty_to_accts[cp].add(acct)
        for dv in st["devices"]:
            device_to_accts[dv].add(acct)
    neighbours: Dict[str, Set[str]] = defaultdict(set)
    for groups in (counterparty_to_accts, device_to_accts):
        for accts in groups.values():
            for a in accts:
                neighbours[a] |= (accts - {a})
    seen: Set[str] = set()
    comps: List[Set[str]] = []
    for acct in sorted(stats):
        if acct in seen:
            continue
        stack = [acct]
        comp: Set[str] = set()
        while stack:
            cur = stack.pop()
            if cur in comp:
                continue
            comp.add(cur)
            seen.add(cur)
            stack.extend(sorted(neighbours[cur] - comp))
        comps.append(comp)
    return comps


class RingDetector:
    """Detects coordinated mule rings across the whole stream."""

    def __init__(self, txns: List[Dict],
                 min_accounts: int = RING_MIN_ACCOUNTS,
                 score_threshold: float = RING_SCORE_THRESHOLD) -> None:
        self.txns = sorted(txns, key=lambda t: t["timestamp"])
        self.min_accounts = min_accounts
        self.score_threshold = score_threshold

    def _score_component(self, comp: Set[str],
                         stats: Dict[str, Dict]) -> Dict:
        shared_cps = set()
        for acct in comp:
            for cp in stats[acct]["counterparties"]:
                holders = [a for a in comp
                           if cp in stats[a]["counterparties"]]
                if len(holders) >= 2:
                    shared_cps.add(cp)
        device_holders: Dict[str, List[str]] = defaultdict(list)
        for acct in comp:
            for dv in stats[acct]["devices"]:
                device_holders[dv].append(acct)
        shared_devices = {dv: sorted(a) for dv, a in device_holders.items()
                          if len(a) >= 2}
        passing = [a for a in comp
                   if stats[a]["pass_through"] >= PASS_THROUGH_RATIO]
        score = round(
            40.0 * min(len(shared_cps), 3) / 3.0
            + (30.0 if shared_devices else 0.0)
            + 30.0 * (len(passing) / len(comp) if comp else 0.0), 1)
        return {
            "score": score,
            "shared_counterparties": sorted(shared_cps),
            "shared_devices": shared_devices,
            "passing_accounts": sorted(passing),
        }

    def detect_rings(self) -> List[Dict]:
        stats = _account_stats(self.txns)
        rings = []
        for comp in _components(stats):
            if len(comp) < self.min_accounts:
                continue
            scored = self._score_component(comp, stats)
            if scored["score"] < self.score_threshold:
                continue
            inflow = round(sum(stats[a]["inflow"] for a in comp), 2)
            outflow = round(sum(stats[a]["outflow"] for a in comp), 2)
            txn_ids = sorted(tid for a in comp for tid in stats[a]["txn_ids"]
                             if any(t["txn_id"] == tid
                                    and (t["direction"] == "credit"
                                         or t["channel"] == "atm")
                                    for t in self.txns))
            rings.append({
                "pattern": "mule_ring",
                "accounts": sorted(comp),
                "severity": "critical",
                "score": scored["score"],
                "evidence": (
                    f"{len(comp)} accounts share "
                    f"{len(scored['shared_counterparties'])} inbound "
                    f"counterparties "
                    f"({', '.join(scored['shared_counterparties']) or 'none'}); "
                    f"{len(scored['shared_devices'])} shared devices; "
                    f"{len(scored['passing_accounts'])} of {len(comp)} accounts "
                    f"passed >= 50% of inflow onward within 48h "
                    f"(${inflow:,.2f} in, ${outflow:,.2f} out)"),
                "txn_ids": txn_ids,
                "shared_counterparties": scored["shared_counterparties"],
                "shared_devices": scored["shared_devices"],
            })
        return rings

    def detect_for_account(self, account_id: str) -> Optional[Dict]:
        for ring in self.detect_rings():
            if account_id in ring["accounts"]:
                return ring
        return None
