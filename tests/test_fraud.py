"""Tests for the fraud detection pipeline. All deterministic (seeded),
no network, no API keys."""

import pytest

from fraud import (
    FraudCase,
    FraudLedger,
    PatternDetector,
    ReviewQueue,
    assemble_case,
    build_baselines,
    gen_transactions,
    inject_account_takeover,
    inject_card_testing,
    inject_merchant_collusion,
    inject_money_mule,
    score_transaction,
)
from fraud.detect import AccountBaseline


@pytest.fixture()
def clean():
    FraudCase._seq = 0
    return gen_transactions(n_accounts=12, days=30, seed=42)


@pytest.fixture()
def attacked(clean):
    txns = inject_card_testing(clean, "acct-001", n=18, seed=7)
    txns = inject_account_takeover(txns, "acct-004", seed=11)
    txns = inject_money_mule(txns, "acct-007", seed=13)
    txns = inject_merchant_collusion(txns, "acct-010", seed=17)
    return txns


@pytest.fixture()
def baselines(clean):
    # Baselines are built from CLEAN history, never the attacked stream.
    return build_baselines(clean)


def _score_all(txns, baselines):
    scored = {}
    for t in txns:
        b = baselines[t["account_id"]]
        recent = [x for x in txns if x["account_id"] == t["account_id"]]
        scored[t["txn_id"]] = score_transaction(t, b, recent)
    return scored


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

def test_gen_deterministic():
    a = gen_transactions(n_accounts=6, days=10, seed=1)
    b = gen_transactions(n_accounts=6, days=10, seed=1)
    assert a == b


def test_gen_different_seeds_differ():
    a = gen_transactions(n_accounts=6, days=10, seed=1)
    b = gen_transactions(n_accounts=6, days=10, seed=2)
    assert a != b


def test_personas_present(clean):
    # 12 accounts cycle steady/traveler/business
    assert len({t["account_id"] for t in clean}) == 12
    assert len(clean) > 200


def test_injectors_do_not_mutate(clean):
    before = len(clean)
    inject_card_testing(clean, "acct-001")
    inject_account_takeover(clean, "acct-004")
    inject_money_mule(clean, "acct-007")
    inject_merchant_collusion(clean, "acct-010")
    assert len(clean) == before


def test_inject_card_testing_adds_n(clean):
    out = inject_card_testing(clean, "acct-001", n=18)
    assert len(out) == len(clean) + 18
    added = [t for t in out if t["txn_id"].startswith("acct-001-f")]
    assert len(added) == 18
    assert all(t["amount"] < 5 for t in added)


def test_inject_account_takeover_structure(clean):
    out = inject_account_takeover(clean, "acct-004")
    added = [t for t in out if t["txn_id"].startswith("acct-004-f")]
    assert len(added) == 9  # 1 probe + 8 burst
    assert added[0]["amount"] == 1.00
    assert all(t["amount"] >= 400 for t in added[1:])


# ---------------------------------------------------------------------------
# Per-transaction scoring
# ---------------------------------------------------------------------------

def test_clean_accounts_score_low(clean, baselines):
    scored = _score_all(clean, baselines)
    worst = max(scored.values(), key=lambda s: s["score"])
    assert worst["score"] < 55.0, f"clean txn scored {worst['score']}: {worst}"


def test_takeover_burst_scores_high(attacked, baselines):
    scored = _score_all(attacked, baselines)
    burst = [s for tid, s in scored.items()
             if tid.startswith("acct-004-f") and tid != "acct-004-f00000"]
    assert burst, "expected burst transactions"
    assert all(s["score"] >= 55.0 for s in burst)
    assert all(s["flagged"] for s in burst)


def test_score_reasons_cite_numbers(attacked, baselines):
    scored = _score_all(attacked, baselines)
    burst = [s for tid, s in scored.items() if tid.startswith("acct-004-f")][1]
    text = " ".join(burst["reasons"])
    assert "$" in text  # amounts cited
    assert any(k in text for k in ("new device", "new geo", "std above"))


def test_micro_auth_gets_merchant_risk_reason(attacked, baselines):
    scored = _score_all(attacked, baselines)
    probes = [s for tid, s in scored.items()
              if tid.startswith("acct-001-f")]
    assert probes
    assert any("micro authorization" in " ".join(s["reasons"]) for s in probes)


def test_velocity_reason_on_burst(attacked, baselines):
    scored = _score_all(attacked, baselines)
    burst = [s for tid, s in scored.items()
             if tid.startswith("acct-004-f")][-1]
    assert any("velocity" in r for r in burst["reasons"])


# ---------------------------------------------------------------------------
# Pattern detectors
# ---------------------------------------------------------------------------

def test_detect_card_testing(attacked, baselines):
    scored = _score_all(attacked, baselines)
    det = PatternDetector(attacked, scored)
    hit = det.detect_card_testing("acct-001")
    assert hit is not None
    assert hit["pattern"] == "card_testing"
    assert hit["severity"] == "high"
    assert len(hit["txn_ids"]) >= 10
    assert "30 minutes" in hit["evidence"]


def test_detect_account_takeover(attacked, baselines):
    scored = _score_all(attacked, baselines)
    det = PatternDetector(attacked, scored)
    hit = det.detect_account_takeover("acct-004", baselines["acct-004"])
    assert hit is not None
    assert hit["pattern"] == "account_takeover"
    assert hit["severity"] == "critical"
    assert "probe" in hit["evidence"]


def test_detect_money_mule(attacked, baselines):
    scored = _score_all(attacked, baselines)
    det = PatternDetector(attacked, scored)
    hit = det.detect_money_mule("acct-007")
    assert hit is not None
    assert hit["pattern"] == "money_mule"
    assert hit["severity"] == "critical"
    assert "counterparties" in hit["evidence"]


def test_detect_merchant_collusion(attacked, baselines):
    scored = _score_all(attacked, baselines)
    det = PatternDetector(attacked, scored)
    hit = det.detect_merchant_collusion("acct-010")
    assert hit is not None
    assert hit["pattern"] == "merchant_collusion"
    assert hit["severity"] == "medium"
    assert len(hit["txn_ids"]) == 8


def test_no_patterns_on_clean_account(clean, baselines):
    scored = _score_all(clean, baselines)
    det = PatternDetector(clean, scored)
    assert det.detect_all("acct-002", baselines["acct-002"]) == []


def test_detect_all_returns_all_hits(attacked, baselines):
    scored = _score_all(attacked, baselines)
    det = PatternDetector(attacked, scored)
    hits = det.detect_all("acct-001", baselines["acct-001"])
    assert [h["pattern"] for h in hits] == ["card_testing"]


# ---------------------------------------------------------------------------
# Case assembly
# ---------------------------------------------------------------------------

def _case_for(attacked, baselines, account_id):
    scored = _score_all(attacked, baselines)
    det = PatternDetector(attacked, scored)
    patterns = det.detect_all(account_id, baselines[account_id])
    return assemble_case(account_id, patterns,
                         list(scored.values()), attacked, attacked)


def test_case_exposure_totals(attacked, baselines):
    case = _case_for(attacked, baselines, "acct-010")
    expected = round(sum(t["amount"] for t in case.txns
                         if t["direction"] == "debit"), 2)
    assert case.total_exposure == expected
    assert case.total_exposure == 8 * 250.00


def test_case_timeline_ordered(attacked, baselines):
    case = _case_for(attacked, baselines, "acct-004")
    stamps = [t["timestamp"] for t in case.timeline]
    assert stamps == sorted(stamps)


def test_case_priority_critical_for_takeover(attacked, baselines):
    case = _case_for(attacked, baselines, "acct-004")
    assert case.priority == "critical"
    assert "account_takeover" in case.summary()["patterns"]


def test_case_priority_high_for_card_testing(attacked, baselines):
    case = _case_for(attacked, baselines, "acct-001")
    assert case.priority == "high"


def test_case_related_accounts_via_shared_device(attacked, baselines):
    # A second account touching the fraud device gets linked.
    extra = {
        "txn_id": "acct-005-x1", "account_id": "acct-005",
        "timestamp": "2026-09-20T03:00:00", "amount": 42.00,
        "merchant": "FuelStop", "merchant_category": "fuel", "geo": "ATL",
        "device_id": "dev-acct-001-unknown-1", "channel": "ecom",
        "direction": "debit",
    }
    txns = attacked + [extra]
    case = _case_for(txns, baselines, "acct-001")
    assert "acct-005" in case.related_accounts


def test_assemble_none_when_clean(clean, baselines):
    scored = _score_all(clean, baselines)
    det = PatternDetector(clean, scored)
    patterns = det.detect_all("acct-002", baselines["acct-002"])
    assert assemble_case("acct-002", patterns, list(scored.values()),
                         clean, clean) is None


def test_case_summary_shape(attacked, baselines):
    case = _case_for(attacked, baselines, "acct-007")
    s = case.summary()
    assert s["case_id"].startswith("CASE-")
    assert s["total_exposure"] > 0
    assert s["top_signals"]
    assert isinstance(s["related_accounts"], list)


# ---------------------------------------------------------------------------
# Review queue
# ---------------------------------------------------------------------------

def test_worklist_prioritizes_critical(attacked, baselines):
    q = ReviewQueue()
    q.add(_case_for(attacked, baselines, "acct-001"))   # high
    q.add(_case_for(attacked, baselines, "acct-004"))   # critical
    q.add(_case_for(attacked, baselines, "acct-010"))   # high
    wl = q.worklist()
    assert [w["priority"] for w in wl] == ["critical", "high", "high"]
    assert wl[0]["account_id"] == "acct-004"


def test_assign_and_resolve(attacked, baselines):
    q = ReviewQueue()
    cid = q.add(_case_for(attacked, baselines, "acct-004"))
    q.assign(cid, "analyst-7")
    assert q.worklist()[0]["assignee"] == "analyst-7"
    q.resolve(cid, "confirmed_fraud", "analyst-7", notes="device takeover")
    assert q.worklist() == []
    stats = q.stats()
    assert stats == {"open": 0, "resolved": 1,
                     "confirmed_fraud": 1, "false_positive": 0}


def test_resolve_invalid_verdict_raises(attacked, baselines):
    q = ReviewQueue()
    cid = q.add(_case_for(attacked, baselines, "acct-001"))
    with pytest.raises(ValueError, match="unknown verdict"):
        q.resolve(cid, "maybe_fraud", "analyst-7")


def test_unknown_case_raises():
    q = ReviewQueue()
    with pytest.raises(ValueError, match="unknown case"):
        q.assign("CASE-9999", "analyst-7")


def test_cannot_resolve_twice(attacked, baselines):
    q = ReviewQueue()
    cid = q.add(_case_for(attacked, baselines, "acct-001"))
    q.resolve(cid, "false_positive", "analyst-7")
    with pytest.raises(ValueError, match="not open"):
        q.resolve(cid, "confirmed_fraud", "analyst-7")


def test_sla_hours_with_explicit_now(attacked, baselines):
    from datetime import datetime, timedelta
    q = ReviewQueue()
    case = _case_for(attacked, baselines, "acct-001")
    cid = q.add(case)
    opened = datetime.fromisoformat(case.opened_at.replace("Z", "+00:00"))
    assert q.sla_hours(cid, now=opened + timedelta(hours=5)) == 5.0


# ---------------------------------------------------------------------------
# Audit ledger
# ---------------------------------------------------------------------------

def test_ledger_chain_verifies():
    ledger = FraudLedger()
    ledger.record("detection", {"pattern": "card_testing"})
    ledger.record("case_opened", {"case_id": "CASE-0001"})
    ledger.record("verdict", {"case_id": "CASE-0001",
                              "verdict": "confirmed_fraud"})
    assert ledger.verify_chain()
    assert len(ledger.events_of("verdict")) == 1


def test_ledger_tamper_detected():
    ledger = FraudLedger()
    ledger.record("detection", {"pattern": "card_testing"})
    ledger.record("verdict", {"verdict": "confirmed_fraud"})
    ledger.entries[1]["payload"]["verdict"] = "false_positive"
    assert not ledger.verify_chain()


def test_ledger_linkage_break_detected():
    ledger = FraudLedger()
    ledger.record("a", {})
    ledger.record("b", {})
    ledger.entries[1]["prev_hash"] = "tampered"
    assert not ledger.verify_chain()


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------

def test_end_to_end_takeover_to_verdict(clean):
    FraudCase._seq = 0
    baselines = build_baselines(clean)          # clean history first
    txns = inject_account_takeover(clean, "acct-004", seed=11)
    scored = _score_all(txns, baselines)
    det = PatternDetector(txns, scored)
    patterns = det.detect_all("acct-004", baselines["acct-004"])
    assert any(p["pattern"] == "account_takeover" for p in patterns)

    case = assemble_case("acct-004", patterns, list(scored.values()),
                         txns, txns)
    assert case is not None and case.priority == "critical"

    ledger = FraudLedger()
    queue = ReviewQueue()
    for p in patterns:
        ledger.record("detection", {"pattern": p["pattern"],
                                    "account_id": "acct-004",
                                    "evidence": p["evidence"]})
    cid = queue.add(case)
    ledger.record("case_opened", case.summary())
    queue.assign(cid, "analyst-7")
    ledger.record("assigned", {"case_id": cid, "analyst": "analyst-7"})
    queue.resolve(cid, "confirmed_fraud", "analyst-7",
                  notes="new device + geo, probe then burst")
    ledger.record("verdict", {"case_id": cid,
                              "verdict": "confirmed_fraud"})

    assert ledger.verify_chain()
    assert [e["event_type"] for e in ledger.entries] == [
        "detection", "case_opened", "assigned", "verdict"]
    assert queue.stats()["confirmed_fraud"] == 1


def test_end_to_end_mule_case_exposure(clean):
    FraudCase._seq = 0
    baselines = build_baselines(clean)
    txns = inject_money_mule(clean, "acct-007", seed=13)
    scored = _score_all(txns, baselines)
    det = PatternDetector(txns, scored)
    patterns = det.detect_all("acct-007", baselines["acct-007"])
    assert any(p["pattern"] == "money_mule" for p in patterns)
    case = assemble_case("acct-007", patterns, list(scored.values()),
                         txns, txns)
    assert case.priority == "critical"
    assert case.total_exposure > 0
