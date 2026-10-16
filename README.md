# Fraud detection agents

End-to-end financial fraud detection on synthetic transaction data:
seeded transaction streams → transparent anomaly scoring → signature
pattern detectors → investigator case assembly → prioritized analyst
review queue → hash-chained audit ledger.

> **Synthetic data only.** Every account, transaction, and fraud pattern
> is generated deterministically in-process. This is an independent
> portfolio project demonstrating fraud-detection engineering patterns;
> it is not affiliated with any financial institution, and nothing here
> is production fraud tooling.

## The problem

Rule engines drown analysts in false positives: thousands of alerts,
no prioritization, no assembled evidence. The expensive part of fraud
operations is not detection — it is the investigator hours spent turning
a raw alert into a decision. This project attacks that cost directly:
every flag carries its reasons, flags roll up into evidence-cited cases,
and cases land in a priority-ordered queue with SLA tracking.

## Architecture

```
transactions.py ──▶ detect.py ──▶ cases.py ──▶ queue.py
 (seeded streams,   (per-txn scoring   (case assembly:   (prioritized
  4 fraud            + pattern          timeline,          worklist,
  injectors)          detectors)        exposure,          verdicts,
                                       related            SLA)
                                       accounts)
        │                                        │
        └──────────▶ audit.py ◀──────────────────┘
                     (hash-chained ledger:
                      detection → case → assign → verdict)
```

**Detection philosophy:** baselines are built from *clean* history and
fraud is scored against them — never the reverse. Every score cites its
numbers (velocity multiples, z-scores, novel geos/devices), and every
pattern detector encodes one documented signature (see
[docs/fraud-patterns.md](docs/fraud-patterns.md)).

## Example: card testing to verdict

```
1. gen_transactions(seed=42) → 12 accounts, 30 days of organic spend
2. build_baselines(clean)    → per-account mean/std, known geos/devices
3. inject_card_testing(acct-001, n=18)
     → 18 sub-$5 ecom authorizations in 25 minutes, one new device
4. score_transaction()       → velocity 173x normal, micro-auth risk
5. detect_card_testing()     → "18 sub-$5 authorizations within 30 minutes"
6. assemble_case()           → CASE-0001, priority high, timeline + exposure
7. queue.add → assign("analyst-7") → resolve("confirmed_fraud", notes=...)
8. FraudLedger               → detection → case_opened → assigned → verdict,
                              hash-chained and verifiable
```

## The four fraud patterns

| Pattern | Signature | Severity |
|---|---|---|
| Card testing | ≥10 sub-$5 ecom auths in 30 min | high |
| Account takeover | ≤$2 probe from new device+geo, then ≥4 high-value purchases in 6h | critical |
| Money mule | Credits from 3+ counterparties, then ≥70% withdrawn via ATM in 24h | critical |
| Merchant collusion | ≥6 identical round-dollar charges at one merchant in 7 days | medium |

Details: [docs/fraud-patterns.md](docs/fraud-patterns.md).

## Production path

- Replace the seeded generators with real transaction feeds (Kafka,
  Kinesis); the scoring/detector/case/queue contracts are stream-shaped
  already.
- Per-transaction scoring is stateless and horizontally scalable;
  pattern detectors are per-account windows — shard by account.
- The review queue needs a real case-management UI; verdicts here are
  the API that UI would call.
- Add model-based scorers behind the same `score_transaction` interface;
  keep the reason-citing contract — investigators will not act on a
  number they cannot explain.

## Tests

```bash
pytest -q   # 35 tests, deterministic, no network
```

## Layout

```
fraud/
  transactions.py   seeded streams + 4 fraud injectors
  detect.py         baselines, per-txn scoring, pattern detectors
  cases.py          investigator case assembly
  queue.py          analyst review queue (verdicts, SLA)
  audit.py          hash-chained FraudLedger
docs/
  fraud-patterns.md pattern signatures and detector mapping
```
