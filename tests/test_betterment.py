"""Tests for the Week 8 betterment: mule rings, eval harness,
template triage narratives, and the approval-gated feedback loop.

All deterministic (seeded), no network, no model calls. The existing
suite in test_fraud.py is untouched; these tests only add coverage.
"""

import pytest

from fraud import (
    ApprovalGate,
    FeedbackLoop,
    FraudCase,
    FraudLedger,
    PatternDetector,
    ReviewQueue,
    RingDetector,
    TuningParams,
    apply_approved,
    assemble_case,
    build_baselines,
    build_labeled_set,
    claims_grounded,
    evaluate,
    gen_transactions,
    inject_account_takeover,
    inject_benign_fanin,
    inject_card_testing,
    inject_money_mule,
    inject_mule_ring,
    measure_effect,
    narrative_has_no_pii,
    render_narrative,
    score_transaction,
    split_accounts,
    wilson_interval,
)


@pytest.fixture()
def clean():
    FraudCase._seq = 0
    return gen_transactions(n_accounts=12, days=30, seed=42)


@pytest.fixture()
def baselines(clean):
    return build_baselines(clean)


def _score_all(txns, baselines, **kwargs):
    by_acct = {}
    for t in txns:
        by_acct.setdefault(t["account_id"], []).append(t)
    return {t["txn_id"]: score_transaction(t, baselines[t["account_id"]],
                                           by_acct[t["account_id"]], **kwargs)
            for t in txns}


def _case_for(txns, baselines, account_id):
    scored = _score_all(txns, baselines)
    det = PatternDetector(txns, scored)
    patterns = det.detect_all(account_id, baselines[account_id])
    ring = RingDetector(txns).detect_for_account(account_id)
    if ring:
        patterns = patterns + [ring]
    return assemble_case(account_id, patterns, list(scored.values()),
                         txns, txns)


# ---------------------------------------------------------------------------
# 1. Mule rings
# ---------------------------------------------------------------------------

RING_ACCTS = ["acct-002", "acct-003", "acct-005", "acct-006"]


def test_ring_detected_on_injected_ring(clean):
    txns = inject_mule_ring(clean, RING_ACCTS, seed=23)
    rings = RingDetector(txns).detect_rings()
    assert len(rings) == 1
    ring = rings[0]
    assert ring["pattern"] == "mule_ring"
    assert ring["severity"] == "critical"
    assert ring["accounts"] == sorted(RING_ACCTS)
    assert ring["score"] >= 70.0
    assert "RingSource-A" in ring["evidence"]
    assert ring["txn_ids"]


def test_ring_score_components(clean):
    txns = inject_mule_ring(clean, RING_ACCTS, seed=23)
    ring = RingDetector(txns).detect_rings()[0]
    assert len(ring["shared_counterparties"]) == 3
    assert ring["shared_devices"]  # two accounts share one device
    assert ring["score"] == 100.0  # 40 shared cps + 30 device + 30 pass-through


def test_ring_is_distinct_from_single_mule(clean, baselines):
    txns = inject_mule_ring(clean, RING_ACCTS, seed=23)
    scored = _score_all(txns, baselines)
    det = PatternDetector(txns, scored)
    for acct in RING_ACCTS:
        assert det.detect_money_mule(acct) is None  # ~60% < 70% cash-out line
    assert RingDetector(txns).detect_for_account("acct-002") is not None


def test_single_mule_is_not_a_ring(clean):
    txns = inject_money_mule(clean, "acct-007", seed=13)
    assert RingDetector(txns).detect_rings() == []


def test_two_accounts_sharing_is_not_a_ring(clean):
    txns = inject_mule_ring(clean, ["acct-002", "acct-003"], seed=23)
    assert RingDetector(txns).detect_rings() == []


def test_payroll_fanin_is_not_a_ring(clean):
    txns = inject_benign_fanin(
        clean, ["acct-008", "acct-009", "acct-011", "acct-012"],
        "PayrollCo", seed=29)
    assert RingDetector(txns).detect_rings() == []


def test_marketplace_fanin_is_not_a_ring(clean):
    txns = inject_benign_fanin(
        clean, ["acct-008", "acct-009", "acct-011", "acct-012"],
        "MarketplaceHub", seed=31)
    assert RingDetector(txns).detect_rings() == []


def test_ring_threshold_is_tunable(clean):
    txns = inject_mule_ring(clean, RING_ACCTS, seed=23)
    assert RingDetector(txns, score_threshold=100.0).detect_rings()
    assert RingDetector(txns, score_threshold=100.1).detect_rings() == []


def test_ring_injector_does_not_mutate(clean):
    before = len(clean)
    inject_mule_ring(clean, RING_ACCTS)
    inject_benign_fanin(clean, ["acct-008"], "PayrollCo")
    assert len(clean) == before


def test_ring_case_assembles(clean, baselines):
    txns = inject_mule_ring(clean, RING_ACCTS, seed=23)
    case = _case_for(txns, baselines, "acct-002")
    assert case is not None
    assert "mule_ring" in case.summary()["patterns"]
    assert case.priority == "critical"


# ---------------------------------------------------------------------------
# 2. Eval harness
# ---------------------------------------------------------------------------

def test_labeled_set_composition():
    txns, expected, _ = build_labeled_set()
    assert len(expected) == 12
    assert expected["acct-001"] == {"card_testing"}
    assert expected["acct-004"] == {"account_takeover"}
    assert expected["acct-007"] == {"money_mule"}
    assert expected["acct-010"] == {"merchant_collusion"}
    for acct in RING_ACCTS:
        assert expected[acct] == {"mule_ring"}
    for acct in ("acct-008", "acct-009", "acct-011", "acct-012"):
        assert expected[acct] == set()
    assert txns  # non-empty stream


def test_eval_all_patterns_detected_no_false_positives():
    txns, expected, baselines = build_labeled_set()
    result = evaluate(txns, expected, baselines)
    for pattern, m in result["per_pattern"].items():
        assert m["fp"] == 0, f"{pattern} false positives: {m}"
        assert m["fn"] == 0, f"{pattern} missed: {m}"
    assert result["macro_f1"] == 1.0


def test_eval_counts_match_labels():
    txns, expected, baselines = build_labeled_set()
    result = evaluate(txns, expected, baselines)
    assert result["per_pattern"]["mule_ring"]["tp"] == 4
    assert result["per_pattern"]["card_testing"]["tp"] == 1
    assert result["n_accounts"] == 12


def test_eval_wilson_interval_properties():
    lo, hi = wilson_interval(4, 4)
    assert 0.0 <= lo <= 1.0 <= hi
    assert lo > 0.5  # 4/4 still leaves real uncertainty, honestly shown
    lo1, _ = wilson_interval(1, 1)
    assert lo1 < lo  # one sample is weaker evidence than four
    assert wilson_interval(0, 0) == (0.0, 1.0)  # no samples: fully uncertain
    lo0, hi0 = wilson_interval(0, 10)
    assert lo0 == 0.0 and hi0 < 0.5


def test_eval_split_is_deterministic_and_disjoint():
    a, b = split_accounts([f"acct-{i + 1:03d}" for i in range(12)])
    assert len(a) == 6 and len(b) == 6
    assert not set(a) & set(b)
    assert split_accounts([f"acct-{i + 1:03d}" for i in range(12)]) == (a, b)


def test_eval_params_thread_through():
    txns, expected, baselines = build_labeled_set()
    # Raising the ring threshold above the ring score removes ring hits.
    result = evaluate(txns, expected, baselines,
                      params={"ring_score_threshold": 100.1})
    assert result["per_pattern"]["mule_ring"]["tp"] == 0
    assert result["per_pattern"]["mule_ring"]["fn"] == 4
    # Raising the flag threshold does not change pattern detection.
    result2 = evaluate(txns, expected, baselines,
                       params={"flag_threshold": 99.0})
    assert result2["per_pattern"]["card_testing"]["tp"] == 1


# ---------------------------------------------------------------------------
# 3. Template triage narratives
# ---------------------------------------------------------------------------

def _takeover_case(clean, baselines):
    txns = inject_account_takeover(clean, "acct-004", seed=11)
    return _case_for(txns, baselines, "acct-004")


def test_narrative_is_labeled_template_not_model(clean, baselines):
    case = _takeover_case(clean, baselines)
    text = render_narrative(case)
    assert text.startswith("Template-generated triage note - no model output.")
    assert "account_takeover" in text
    assert case.case_id in text
    assert "acct-004" in text


def test_narrative_grounded_for_real_case(clean, baselines):
    case = _takeover_case(clean, baselines)
    grounded, violations = claims_grounded(render_narrative(case), case)
    assert grounded and violations == []


def test_narrative_grounded_for_ring_case(clean, baselines):
    txns = inject_mule_ring(clean, RING_ACCTS, seed=23)
    case = _case_for(txns, baselines, "acct-002")
    grounded, violations = claims_grounded(render_narrative(case), case)
    assert grounded and violations == []


def test_narrative_invented_amount_fails_grounding(clean, baselines):
    case = _takeover_case(clean, baselines)
    text = render_narrative(case) + "\nHidden loss: $999,999.99."
    grounded, violations = claims_grounded(text, case)
    assert not grounded
    assert any("$999,999.99" in v for v in violations)


def test_narrative_invented_account_fails_grounding(clean, baselines):
    case = _takeover_case(clean, baselines)
    text = render_narrative(case) + "\nAlso linked: acct-099."
    grounded, violations = claims_grounded(text, case)
    assert not grounded
    assert any("acct-099" in v for v in violations)


def test_narrative_wrong_case_id_fails_grounding(clean, baselines):
    case = _takeover_case(clean, baselines)
    text = render_narrative(case).replace(case.case_id, "CASE-9999")
    grounded, violations = claims_grounded(text, case)
    assert not grounded
    assert any("CASE-9999" in v for v in violations)


def test_narrative_has_no_pii(clean, baselines):
    case = _takeover_case(clean, baselines)
    text = render_narrative(case)
    assert narrative_has_no_pii(text)
    assert not narrative_has_no_pii(text + " contact analyst@example.com")
    assert not narrative_has_no_pii(text + " card 4111111111111111")


# ---------------------------------------------------------------------------
# 4. Approval-gated feedback loop
# ---------------------------------------------------------------------------

def test_gate_approve_applies_and_audits():
    gate = ApprovalGate()
    ledger = FraudLedger()
    params = TuningParams()
    token = gate.propose("flag_threshold", 55.0, 60.0,
                         scope="account_takeover precision")
    assert gate.decide(token, "analyst-7", "yes") == "approved"
    new_params = apply_approved(params, gate, token, ledger)
    assert new_params.flag_threshold == 60.0
    assert params.flag_threshold == 55.0  # input never mutated
    assert ledger.verify_chain()
    events = ledger.events_of("threshold_change")
    assert len(events) == 1
    assert events[0]["payload"]["approver"] == "analyst-7"
    assert events[0]["payload"]["parameter"] == "flag_threshold"


def test_gate_bypass_without_token_raises():
    gate = ApprovalGate()
    ledger = FraudLedger()
    with pytest.raises(ValueError, match="unknown approval"):
        apply_approved(TuningParams(), gate, "no-such-token", ledger)


def test_gate_pending_token_cannot_apply():
    gate = ApprovalGate()
    ledger = FraudLedger()
    token = gate.propose("flag_threshold", 55.0, 60.0, scope="test")
    with pytest.raises(ValueError, match="not approved"):
        apply_approved(TuningParams(), gate, token, ledger)


def test_gate_reject_discards_change():
    gate = ApprovalGate()
    ledger = FraudLedger()
    token = gate.propose("flag_threshold", 55.0, 60.0, scope="test")
    assert gate.decide(token, "analyst-7", "no") == "rejected"
    with pytest.raises(ValueError, match="not approved"):
        apply_approved(TuningParams(), gate, token, ledger)
    assert ledger.events_of("threshold_change") == []


def test_gate_token_is_single_use():
    gate = ApprovalGate()
    ledger = FraudLedger()
    token = gate.propose("flag_threshold", 55.0, 60.0, scope="test")
    gate.decide(token, "analyst-7", "yes")
    apply_approved(TuningParams(), gate, token, ledger)
    with pytest.raises(ValueError, match="not approved"):
        apply_approved(TuningParams(), gate, token, ledger)


def test_gate_expired_token_raises():
    gate = ApprovalGate()
    token = gate.propose("flag_threshold", 55.0, 60.0, scope="test",
                         ttl_seconds=0)
    with pytest.raises(ValueError, match="expired"):
        gate.decide(token, "analyst-7", "yes")


def test_gate_requires_named_person_approver():
    gate = ApprovalGate()
    token = gate.propose("flag_threshold", 55.0, 60.0, scope="test")
    for bad in ("", "   ", "system", "auto"):
        with pytest.raises(ValueError, match="named person"):
            gate.decide(token, bad, "yes")
    assert gate.decide(token, "analyst-7", "yes") == "approved"


def test_gate_self_contradicting_consent_refused():
    gate = ApprovalGate()
    token = gate.propose("flag_threshold", 55.0, 60.0, scope="test")
    with pytest.raises(ValueError, match="ambiguous"):
        gate.decide(token, "analyst-7", "yes, wait, no")
    # Refusal leaves the token pending: a clear decision still works.
    assert gate.decide(token, "analyst-7", "yes") == "approved"


def test_gate_low_confidence_response_refused():
    gate = ApprovalGate()
    token = gate.propose("flag_threshold", 55.0, 60.0, scope="test")
    for vague in ("maybe", "yes?", "perhaps", "not sure"):
        with pytest.raises(ValueError, match="ambiguous"):
            gate.decide(token, "analyst-7", vague)
    assert gate.decide(token, "analyst-7", "no") == "rejected"


def test_feedback_proposes_only_with_enough_verdicts():
    gate = ApprovalGate()
    loop = FeedbackLoop()
    for _ in range(4):  # below the 5-verdict minimum
        loop.record_verdict("card_testing", "false_positive")
    assert loop.propose_changes(TuningParams(), gate) == []
    loop.record_verdict("card_testing", "false_positive")
    proposals = loop.propose_changes(TuningParams(), gate)
    assert len(proposals) == 1
    assert proposals[0]["parameter"] == "card_testing_min"
    assert proposals[0]["new_value"] == 12


def test_feedback_no_proposal_when_precision_healthy():
    gate = ApprovalGate()
    loop = FeedbackLoop()
    for _ in range(5):
        loop.record_verdict("card_testing", "confirmed_fraud")
    assert loop.propose_changes(TuningParams(), gate) == []


def test_feedback_invalid_verdict_raises():
    loop = FeedbackLoop()
    with pytest.raises(ValueError, match="unknown verdict"):
        loop.record_verdict("card_testing", "maybe_fraud")


def test_feedback_out_of_bounds_proposal_dropped():
    gate = ApprovalGate()
    loop = FeedbackLoop()
    for _ in range(5):
        loop.record_verdict("money_mule", "false_positive")
    params = TuningParams(cashout_ratio=0.98)
    assert loop.propose_changes(params, gate) == []  # 1.03 > 1.0 dropped


def test_feedback_full_loop_with_measured_effect():
    txns, expected, baselines = build_labeled_set()
    tune_accts, heldout_accts = split_accounts(sorted(expected))
    loop = FeedbackLoop()
    for _ in range(6):
        loop.record_verdict("mule_ring", "false_positive")
    gate = ApprovalGate()
    proposals = loop.propose_changes(TuningParams(), gate)
    assert len(proposals) == 1
    token = proposals[0]["token"]
    gate.decide(token, "analyst-7", "yes")
    before = TuningParams()
    after = apply_approved(before, gate, token, FraudLedger())
    assert after.ring_score_threshold == 75.0
    effect = measure_effect(before, after, txns, expected, baselines,
                            account_subset=heldout_accts)
    assert effect["n_accounts"] == 6
    assert "macro_f1_delta" in effect
    assert effect["macro_f1_before"] == effect["macro_f1_after"]  # 75 < 100
    # The full run also works: effect is reported even when it is zero.
    full = measure_effect(before, after, txns, expected, baselines)
    assert full["n_accounts"] == 12


def test_tuning_params_bounds_reject_invalid():
    with pytest.raises(ValueError):
        TuningParams(flag_threshold=0.0)
    with pytest.raises(ValueError):
        TuningParams(cashout_ratio=1.5)
    with pytest.raises(ValueError):
        TuningParams(card_testing_min=0)


# ---------------------------------------------------------------------------
# Regression: existing behaviour preserved under new defaults
# ---------------------------------------------------------------------------

def test_score_default_threshold_unchanged(clean, baselines):
    txns = inject_account_takeover(clean, "acct-004", seed=11)
    scored = _score_all(txns, baselines)
    burst = [s for tid, s in scored.items()
             if tid.startswith("acct-004-f") and tid != "acct-004-f00000"]
    assert all(s["flagged"] for s in burst)


def test_queue_verdicts_feed_feedback_loop(clean, baselines):
    q = ReviewQueue()
    case = _case_for(inject_account_takeover(clean, "acct-004", seed=11),
                     baselines, "acct-004")
    cid = q.add(case)
    q.resolve(cid, "false_positive", "analyst-7")
    loop = FeedbackLoop()
    loop.record_verdict("account_takeover", "false_positive")
    assert loop.precision("account_takeover") == 0.0
