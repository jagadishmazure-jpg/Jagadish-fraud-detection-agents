"""Synthetic transaction streams with deterministic, seeded personas and
injectable fraud patterns.

A transaction is a plain dict:
    txn_id, account_id, timestamp (ISO-8601), amount, merchant,
    merchant_category, geo (city code), device_id, channel (card_present /
    ecom / atm), direction (debit / credit)

Injectors return NEW lists (never mutate their input) so clean baselines
can be built from the pristine stream and fraud scored against them.
"""

from __future__ import annotations

import copy
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

PERSONAS = ("steady", "traveler", "business")

_MERCHANTS = [
    ("FreshMart", "grocery"), ("FuelStop", "fuel"), ("ShopNow", "retail"),
    ("BeanHouse", "dining"), ("SkyWays", "travel"), ("RideNow", "transport"),
    ("CarePharm", "pharmacy"), ("BuildBarn", "home"), ("StreamBox", "subscription"),
    ("BurritoBar", "dining"), ("MegaMart", "retail"), ("PetroPlus", "fuel"),
]

_GEOS = ["ATL", "NYC", "CHI", "DAL", "SFO", "MIA", "SEA", "DEN"]


def _persona_txns(rng: random.Random, account_id: str, persona: str,
                  start: datetime, days: int) -> List[Dict]:
    txns: List[Dict] = []
    seq = 0
    for day in range(days):
        base = start + timedelta(days=day)
        if persona == "steady":
            n = rng.randint(1, 4)
            home_geo = _GEOS[0]
            device = f"dev-{account_id}-home"
        elif persona == "traveler":
            n = rng.randint(2, 6)
            home_geo = rng.choice(_GEOS)
            device = f"dev-{account_id}-mobile"
        else:  # business
            n = rng.randint(4, 10)
            home_geo = _GEOS[1]
            device = f"dev-{account_id}-corp"
        for _ in range(n):
            hour = rng.randint(6, 22)
            minute = rng.randint(0, 59)
            merchant, category = rng.choice(_MERCHANTS)
            if persona == "business":
                amount = round(rng.uniform(20, 800), 2)
            elif persona == "traveler":
                amount = round(rng.uniform(10, 450), 2)
            else:
                amount = round(rng.uniform(5, 180), 2)
            seq += 1
            txns.append({
                "txn_id": f"{account_id}-t{seq:05d}",
                "account_id": account_id,
                "timestamp": (base + timedelta(hours=hour, minutes=minute)).isoformat(),
                "amount": amount,
                "merchant": merchant,
                "merchant_category": category,
                "geo": home_geo if rng.random() > 0.08 else rng.choice(_GEOS),
                "device_id": device,
                "channel": "card_present" if rng.random() > 0.35 else "ecom",
                "direction": "debit",
            })
    return txns


def gen_transactions(n_accounts: int = 12, days: int = 30,
                     seed: int = 42,
                     start: Optional[datetime] = None) -> List[Dict]:
    """Generate a deterministic multi-account transaction stream."""
    rng = random.Random(seed)
    start = start or datetime(2026, 9, 1, 0, 0, 0)
    txns: List[Dict] = []
    for i in range(n_accounts):
        account_id = f"acct-{i + 1:03d}"
        persona = PERSONAS[i % len(PERSONAS)]
        txns.extend(_persona_txns(rng, account_id, persona, start, days))
    txns.sort(key=lambda t: t["timestamp"])
    return txns


def _fraud_txn(rng: random.Random, account_id: str, seq: int, ts: datetime,
               amount: float, merchant: str, geo: str, device: str,
               channel: str = "ecom", category: str = "fraud_probe") -> Dict:
    return {
        "txn_id": f"{account_id}-f{seq:05d}",
        "account_id": account_id,
        "timestamp": ts.isoformat(),
        "amount": round(amount, 2),
        "merchant": merchant,
        "merchant_category": category,
        "geo": geo,
        "device_id": device,
        "channel": channel,
        "direction": "debit",
    }


def inject_card_testing(txns: List[Dict], account_id: str,
                        n: int = 18, seed: int = 7) -> List[Dict]:
    """Many small authorization probes in a short window (card testing).

    Signature: >=10 sub-$5 authorizations within 30 minutes at ecom
    merchants, usually from a single new device.
    """
    rng = random.Random(seed)
    out = copy.deepcopy(txns)
    base = datetime(2026, 9, 20, 2, 0, 0)
    device = f"dev-{account_id}-unknown-1"
    for i in range(n):
        ts = base + timedelta(minutes=rng.randint(0, 25))
        out.append(_fraud_txn(rng, account_id, i, ts,
                              rng.choice([1.00, 1.99, 2.50, 3.99]),
                              rng.choice(["StripeTest", "PayGate", "QuickPay"]),
                              "NYC", device))
    out.sort(key=lambda t: t["timestamp"])
    return out


def inject_account_takeover(txns: List[Dict], account_id: str,
                            seed: int = 11) -> List[Dict]:
    """Spend spike from a new device in a new geo (account takeover).

    Signature: burst of high-value ecom purchases from a device and geo
    never seen on the account, shortly after a small probe transaction.
    """
    rng = random.Random(seed)
    out = copy.deepcopy(txns)
    base = datetime(2026, 9, 22, 14, 0, 0)
    device = f"dev-{account_id}-unknown-2"
    out.append(_fraud_txn(rng, account_id, 0, base, 1.00,
                          "ProbeStore", "LHR", device))
    for i in range(1, 9):
        ts = base + timedelta(minutes=20 + i * 12)
        out.append(_fraud_txn(rng, account_id, i, ts,
                              rng.uniform(400, 1500),
                              rng.choice(["GadgetHub", "TechStore", "JewelryCo"]),
                              "LHR", device))
    out.sort(key=lambda t: t["timestamp"])
    return out


def inject_money_mule(txns: List[Dict], account_id: str,
                      seed: int = 13) -> List[Dict]:
    """Fan-in of credits followed by rapid cash-out (money mule).

    Signature: several inbound credits from distinct counterparties,
    then near-total withdrawal via ATM within hours.
    """
    rng = random.Random(seed)
    out = copy.deepcopy(txns)
    base = datetime(2026, 9, 25, 9, 0, 0)
    device = f"dev-{account_id}-home"
    for i in range(5):
        out.append({
            "txn_id": f"{account_id}-m{i:05d}",
            "account_id": account_id,
            "timestamp": (base + timedelta(hours=i * 3)).isoformat(),
            "amount": round(rng.uniform(800, 2500), 2),
            "merchant": f"Counterparty-{i}",
            "merchant_category": "transfer_in",
            "geo": "ATL",
            "device_id": device,
            "channel": "ecom",
            "direction": "credit",
        })
    for i in range(3):
        out.append(_fraud_txn(rng, account_id, 100 + i,
                              base + timedelta(hours=16 + i),
                              rng.uniform(2000, 4000), "ATM-4471",
                              "ATL", device, channel="atm"))
    out.sort(key=lambda t: t["timestamp"])
    return out


def inject_merchant_collusion(txns: List[Dict], account_id: str,
                              seed: int = 17) -> List[Dict]:
    """Round-amount repeats at a single merchant (merchant collusion).

    Signature: >=6 identical round-dollar charges at one merchant within
    a week — inconsistent with organic spend variance.
    """
    rng = random.Random(seed)
    out = copy.deepcopy(txns)
    base = datetime(2026, 9, 18, 12, 0, 0)
    device = f"dev-{account_id}-home"
    for i in range(8):
        ts = base + timedelta(days=rng.randint(0, 6), hours=rng.randint(0, 8))
        out.append(_fraud_txn(rng, account_id, i, ts, 250.00,
                              "DiscountElectronics", "ATL", device,
                              channel="card_present",
                              category="electronics"))
    out.sort(key=lambda t: t["timestamp"])
    return out
