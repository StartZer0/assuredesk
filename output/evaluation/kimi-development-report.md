# AssureDesk evaluation

Batch: `kimi-development-v1`; 15 recorded variant runs over 5 questions.

Status: scored. source-grounded review; no independent human validation claimed

Semantic release gate: **not passed** (complete-supported threshold 90%; independent validation required).
Frozen locked factual target met: False. Independent validation available: False.

| Variant | Supported complete | Selective precision | Missing / unscored | Known cost + uncertain reservation |
|---|---|---|---|---|
| dense | 3/3 | 3/3 | 0/0 | $0.011111 |
| hybrid | 3/3 | 3/3 | 0/0 | $0.011533 |
| corrective | 3/3 | 3/3 | 0/0 | $0.014913 |

Full retrieval, routing, citation, uncertainty, and cost counts: `report.json`.
Reference ANSWERABLE cases; failed retrievals remain zero-scored.
Unscored semantic outcomes are unresolved, never inferred from the model's own support check.

## Cases requiring review

- personal-tokens-3 / dense: awaiting_review; not complete and supported
- personal-tokens-3 / hybrid: awaiting_review; not complete and supported
- personal-tokens-3 / corrective: awaiting_review; not complete and supported
- personal-tokens-4 / dense: awaiting_review; not complete and supported
- personal-tokens-4 / hybrid: needs_clarification; not complete and supported
- personal-tokens-4 / corrective: needs_clarification; not complete and supported
