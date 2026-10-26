# Template triage narratives

## The problem

An analyst opening a case needs one paragraph that says what happened,
in what order, and how much is at stake — before they open the timeline.
A language model could write that paragraph, but it could also invent
a merchant, round an amount, or upgrade a severity. In a fraud record,
an invented fact is not a style issue; it is a false record.

## The approach

`fraud/narratives.py::render_narrative` builds the paragraph from a
template filled ONLY with fields of the `FraudCase` itself: case id,
account, priority, each pattern's name, severity and evidence string,
timeline timestamps, total exposure, and related accounts. No model is
called, anywhere, and the first line of every narrative says so:

> Template-generated triage note - no model output. Every figure below
> comes from the case record.

## The groundedness check

`claims_grounded(narrative, case)` re-checks the rendered text and
returns (grounded, violations):

- every dollar amount must appear in the case's evidence strings,
  timeline amounts, or total exposure;
- every timestamp must appear in the case timeline;
- every account id must be the case account or a related account;
- the case id must be this case's id.

A narrative with an invented amount, account, timestamp, or case id
fails the check. Tests cover each failure mode separately, so a future
template change that introduces a new claim type has to extend the
checker too, or the suite goes red.

## Personal data

Case records contain no card numbers, email addresses, or customer
names by construction: accounts are `acct-###` ids and merchants are
fictional names. The renderer copies case fields only, so it cannot
introduce personal data it was never given. `narrative_has_no_pii`
asserts that no email-like or card-number-like string appears in the
output, and tests pin it with both a planted email and a planted card
number.

## What this is not

This is not a model-generated summary, not a customer communication,
and not a verdict. The analyst still records the verdict in the review
queue; the narrative only shortens the time to that decision. If a
future version adds model-generated text, it must go through the same
groundedness checker, with failures routed to human review instead of
silently published.
