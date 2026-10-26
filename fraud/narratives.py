"""Deterministic template triage narratives, grounded in case evidence.

These narratives are NOT model output. Every sentence is filled from
fields of the FraudCase itself (patterns, evidence strings, timeline,
exposure, related accounts), and the text says so on its first line.
`claims_grounded` re-checks a rendered narrative: every dollar amount,
timestamp, account id and case id in the text must already exist in the
case record. A narrative that invents a fact fails the check by design.

Case records contain no card numbers, email addresses or customer
names by construction (accounts are acct-### ids, merchants are
fictional names), and the renderer copies case fields only, so it
cannot introduce personal data. `narrative_has_no_pii` asserts that
no email-like or card-number-like string appears in the output.
"""

from __future__ import annotations

import re
from typing import List, Tuple

_MONEY = re.compile(r"\$[\d,]+\.\d{2}")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_ACCOUNT = re.compile(r"acct-\d{3}")
_CASE = re.compile(r"CASE-\d{4}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_CARD_RUN = re.compile(r"\d{13,19}")

HEADER = ("Template-generated triage note - no model output. "
          "Every figure below comes from the case record.")


def render_narrative(case) -> str:
    """Render a triage note for a FraudCase, using only its own fields."""
    lines = [HEADER,
             f"Case {case.case_id} for account {case.account_id} "
             f"is {case.priority} priority."]
    if case.patterns:
        lines.append("Detected patterns:")
        for p in case.patterns:
            lines.append(f"- {p['pattern']} ({p['severity']}): "
                         f"{p['evidence']}")
    else:
        lines.append("No pattern matched; the case rests on flagged "
                     "transactions alone.")
    lines.append(f"Total exposure: ${case.total_exposure:,.2f} across "
                 f"{len(case.txns)} transactions.")
    if case.timeline:
        lines.append(f"Timeline runs from {case.timeline[0]['timestamp']} "
                     f"to {case.timeline[-1]['timestamp']}.")
    if case.related_accounts:
        lines.append("Related accounts: "
                     + ", ".join(case.related_accounts) + ".")
    else:
        lines.append("Related accounts: none.")
    return "\n".join(lines)


def claims_grounded(narrative: str, case) -> Tuple[bool, List[str]]:
    """Check every checkable claim in the narrative against the case.

    Returns (grounded, violations). Amounts must appear in the case's
    evidence strings, timeline amounts, or total exposure; timestamps
    in the timeline; account ids as the case account or a related
    account; the case id must be this case's id.
    """
    violations: List[str] = []
    allowed_amounts = {f"${case.total_exposure:,.2f}"}
    for t in case.timeline:
        allowed_amounts.add(f"${t['amount']:,.2f}")
    for p in case.patterns:
        allowed_amounts |= set(_MONEY.findall(p["evidence"]))
    for amount in set(_MONEY.findall(narrative)):
        if amount not in allowed_amounts:
            violations.append(f"amount {amount} not in case evidence")
    allowed_ts = {t["timestamp"] for t in case.timeline}
    for ts in set(_TIMESTAMP.findall(narrative)):
        if ts not in allowed_ts:
            violations.append(f"timestamp {ts} not in case timeline")
    allowed_accts = {case.account_id} | set(case.related_accounts)
    for acct in set(_ACCOUNT.findall(narrative)):
        if acct not in allowed_accts:
            violations.append(f"account {acct} not in case record")
    for cid in set(_CASE.findall(narrative)):
        if cid != case.case_id:
            violations.append(f"case id {cid} is not this case")
    return (not violations, violations)


def narrative_has_no_pii(narrative: str) -> bool:
    """True when no email-like or card-number-like string is present."""
    if _EMAIL.search(narrative):
        return False
    for run in _CARD_RUN.findall(narrative.replace(",", "").replace(" ", "")):
        if len(run) >= 13:
            return False
    return True
