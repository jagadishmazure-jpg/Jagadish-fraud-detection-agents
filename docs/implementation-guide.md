# Implementation guide: from offline build to Azure

> Status: **planned**. Nothing here has been deployed. The offline build in this
> repository is what exists today; this guide is how it would be taken to a
> real Azure environment.

## Azure service mapping

| Offline component | Azure service (planned) | Notes |
|---|---|---|
| Seeded transaction stream | Azure Event Hubs (Kafka API) | Partition by account ID |
| `score_transaction` | Azure Container Apps consumer, or Fabric Real-Time Intelligence | Stateless, scales out |
| Baselines | Azure Cache for Redis or Cosmos DB, rebuilt nightly from clean history |  |
| Model-based scorer (planned) | Azure Machine Learning managed online endpoint | Same reason-citing contract |
| Cases and queue | Azure SQL Database + an internal case UI | Analyst sign-in through Entra ID |
| `FraudLedger` | Azure Storage with immutable (WORM) blob policy | Tamper evidence at rest |

## Steps

1. Publish transactions to Event Hubs and run the scorer as a Container Apps consumer with a managed identity.
2. Persist baselines and rebuild them from cleared (non-fraud) history on a schedule.
3. Run pattern detectors over per-account windows; shard by account.
4. Write cases to Azure SQL, expose the queue to analysts, and keep verdicts as the only path to account action.
5. Append ledger entries to immutable blob storage and verify the chain daily.
6. Before any ML scorer goes live, register it in the model-risk inventory with a validation report.

## Guardrails to keep when going live

- Every flag and pattern carries human-readable evidence; nothing is a bare number.
- The system never blocks or closes an account: it opens cases, and an analyst records the verdict.
- Baselines come from clean history only, so attacked data cannot shift what normal looks like.
- Every detection, case, assignment and verdict is written to a hash-chained ledger that can be verified.
- Synthetic accounts and merchants only; no real card or customer data.

## What to measure before calling it production-ready

- Precision and recall per pattern on a labelled set, and false positives per 1,000 accounts.
- Analyst minutes per case and SLA breach rate.
- End-to-end latency from transaction to case.
