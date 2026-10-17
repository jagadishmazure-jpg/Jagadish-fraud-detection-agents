"""Inject four fraud patterns into a synthetic stream, then detect, score, case and queue them (offline)."""
from fraud import (
    FraudCase,
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

FraudCase._seq = 0
clean = gen_transactions(n_accounts=12, days=30, seed=42)
injected = {"acct-001": "card_testing", "acct-004": "account_takeover",
            "acct-007": "money_mule", "acct-010": "merchant_collusion"}
txns = inject_card_testing(clean, "acct-001", n=18, seed=7)
txns = inject_account_takeover(txns, "acct-004", seed=11)
txns = inject_money_mule(txns, "acct-007", seed=13)
txns = inject_merchant_collusion(txns, "acct-010", seed=17)
baselines = build_baselines(clean)          # baselines come from clean history only

by_acct = {}
for t in txns:
    by_acct.setdefault(t["account_id"], []).append(t)
scored = {t["txn_id"]: score_transaction(t, baselines[t["account_id"]], by_acct[t["account_id"]]) for t in txns}
detector = PatternDetector(txns, scored)
queue = ReviewQueue()

print(f"{len(txns)} transactions, {len(by_acct)} accounts, {len(injected)} accounts with an injected pattern\n")
tp = fp = fn = 0
for acct in sorted(by_acct):
    patterns = detector.detect_all(acct, baselines[acct])
    names = [p["pattern"] for p in patterns]
    expected = injected.get(acct)
    tp += expected in names
    fn += expected is not None and expected not in names
    fp += len([n for n in names if n != expected])
    case = assemble_case(acct, patterns, [scored[t["txn_id"]] for t in by_acct[acct]], by_acct[acct], txns)
    if case:
        queue.add(case)
    flagged = sum(scored[t["txn_id"]]["flagged"] for t in by_acct[acct])
    print(f"{acct}  injected={expected or '-':18} detected={','.join(names) or '-':18} flagged_txns={flagged}")

print(f"\nPattern detection: {tp} true positives, {fp} false positives, {fn} missed")
print("\nAnalyst worklist (critical first):")
for row in queue.worklist():
    print(f"  {row['case_id']}  {row['account_id']}  {row['priority']:8}  exposure=${row['exposure']:,.2f}")
