# Interview points

Short, honest talking points for Jagadish-fraud-detection-agents. Every number quoted is from the
real run shown in the README.

- The cost in fraud operations is investigator time, so I designed for explainable cases, not just scores.
- Two layers on purpose: in the seeded demo the per-transaction score tops out at 50.5 for card-testing probes (threshold 55), and the window-based detector catches the pattern.
- Baselines from clean history only, to avoid poisoning 'normal' with the attack.
- 4 of 4 injected patterns detected with 0 false positives on 8 clean accounts. I describe that as a correctness check, not a detection rate.

## Likely follow-up questions

- How would you lower false positives at scale? (Calibrate weights on labelled history, add per-segment baselines.)
- Where would ML fit? (Behind the same scorer interface, still returning reasons, with model-risk sign-off.)
- How do you handle concept drift? (Monitor flag rates and verdict mix per week; rebuild baselines.)
