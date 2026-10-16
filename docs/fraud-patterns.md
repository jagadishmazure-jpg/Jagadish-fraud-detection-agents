# Fraud patterns

The four fraud signatures this project detects, what each one looks
like in transaction data, and which detector catches it. All patterns
are injected synthetically (see `fraud/transactions.py`); detectors
live in `fraud/detect.py`.

## 1. Card testing

**What it is:** criminals validate stolen card numbers with tiny
authorizations before the big purchase. The probes are cheap and
deniable; the damage comes later.

**Signature in the data:** a burst of sub-$5 e-commerce authorizations
— typically $1.00–$3.99 — at payment-gateway-style merchants, inside a
~30-minute window, from a single device the account has never used.

**Detector:** `detect_card_testing` — ≥10 sub-$5 ecom debits within any
rolling 30-minute window. Per-transaction scoring independently flags
the velocity (often 100x+ the account's normal rate) and the micro-auth
merchant risk.

**Investigator note:** the probe merchants and device are the pivot —
search them across accounts to find the rest of the compromised batch.

## 2. Account takeover

**What it is:** credential theft followed by a spending spree before
the victim notices. The tell is behavioral discontinuity: nothing about
the session resembles the account's history.

**Signature in the data:** a ≤$2 probe transaction from a new device in
a new geography, followed within hours by high-value e-commerce
purchases (≥$200) from the same device.

**Detector:** `detect_account_takeover` — probe from a device *and* geo
absent from the clean-history baseline, then ≥4 purchases ≥$200 from
that device within 6 hours. Severity: critical.

**Investigator note:** the probe-then-burst shape is what separates
takeover from a legitimate trip — travelers buy at normal cadence from
known devices.

## 3. Money mule

**What it is:** a recruited account receives illicit funds from several
sources, then cashes out fast. The account is the laundering hop.

**Signature in the data:** inbound credits from 3+ distinct
counterparties over a day or two, then rapid ATM withdrawals totaling
≥70% of the inflow within 24 hours of the last credit.

**Detector:** `detect_money_mule` — counterparty fan-in count plus the
inflow/outflow ratio inside the 24-hour window. Severity: critical.

**Investigator note:** counterparties are the network — each one is a
lead to another mule or the originating fraud.

## 4. Merchant collusion

**What it is:** a merchant (or a compromised terminal) runs repeated
charges against a card — skimming with the books balanced by
round-dollar amounts that look like legitimate purchases.

**Signature in the data:** ≥6 identical round-dollar charges at a single
merchant within 7 days. Organic spend has variance; collusion does not.

**Detector:** `detect_merchant_collusion` — groups by
(merchant, amount) over a 7-day span, ignoring probe-category
transactions so card-testing bursts cannot false-positive here.
Severity: medium.

**Investigator note:** low severity per case, high value in aggregate —
one colluding merchant touches many accounts.

## Detector layering

Per-transaction scoring (`score_transaction`: velocity 30 / amount 30 /
geo-device novelty 25 / merchant risk 15) catches *anomalous single
events*. Pattern detectors catch *shapes across events* — the mule's
individual credits and withdrawals each look ordinary; only the fan-in
then cash-out sequence is criminal. Both layers feed case assembly, so
an investigator sees the score, the pattern, and the evidence together.
