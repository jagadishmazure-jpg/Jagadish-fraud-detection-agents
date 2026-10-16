"""fraud: end-to-end financial fraud detection on synthetic transaction data.

Pipeline: seeded transaction streams -> per-transaction anomaly scoring ->
pattern detectors -> investigator case assembly -> analyst review queue ->
hash-chained audit ledger. Deterministic, stdlib-only, no network.
"""

from .audit import FraudLedger
from .cases import FraudCase, assemble_case
from .detect import AccountBaseline, PatternDetector, build_baselines, score_transaction
from .queue import ReviewQueue
from .transactions import (
    gen_transactions,
    inject_account_takeover,
    inject_card_testing,
    inject_merchant_collusion,
    inject_money_mule,
)

__all__ = [
    "gen_transactions",
    "inject_card_testing",
    "inject_account_takeover",
    "inject_money_mule",
    "inject_merchant_collusion",
    "score_transaction",
    "AccountBaseline",
    "build_baselines",
    "PatternDetector",
    "assemble_case",
    "FraudCase",
    "ReviewQueue",
    "FraudLedger",
]
