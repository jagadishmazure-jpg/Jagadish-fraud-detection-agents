"""fraud: end-to-end financial fraud detection on synthetic transaction data.

Pipeline: seeded transaction streams -> per-transaction anomaly scoring ->
pattern detectors -> investigator case assembly -> analyst review queue ->
hash-chained audit ledger. Deterministic, stdlib-only, no network.
"""

from .audit import FraudLedger
from .cases import FraudCase, assemble_case
from .detect import AccountBaseline, PatternDetector, build_baselines, score_transaction
from .eval import build_labeled_set, evaluate, split_accounts, wilson_interval
from .feedback import (
    ApprovalGate,
    FeedbackLoop,
    TuningParams,
    apply_approved,
    measure_effect,
)
from .narratives import (
    claims_grounded,
    narrative_has_no_pii,
    render_narrative,
)
from .queue import ReviewQueue
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

__all__ = [
    "gen_transactions",
    "inject_card_testing",
    "inject_account_takeover",
    "inject_money_mule",
    "inject_merchant_collusion",
    "inject_mule_ring",
    "inject_benign_fanin",
    "score_transaction",
    "AccountBaseline",
    "build_baselines",
    "PatternDetector",
    "RingDetector",
    "assemble_case",
    "FraudCase",
    "ReviewQueue",
    "FraudLedger",
    "build_labeled_set",
    "evaluate",
    "split_accounts",
    "wilson_interval",
    "render_narrative",
    "claims_grounded",
    "narrative_has_no_pii",
    "TuningParams",
    "ApprovalGate",
    "FeedbackLoop",
    "apply_approved",
    "measure_effect",
]
