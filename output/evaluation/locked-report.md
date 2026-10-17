# AssureDesk evaluation

Batch: `locked-frozen-v2`; 90 recorded variant runs over 30 questions.

Status: scored. source-grounded review; no independent human validation claimed

Semantic release gate: **not passed** (complete-supported threshold 90%; independent validation required).

| Variant | Supported complete | Selective precision | Missing / unscored | Known cost + uncertain reservation |
|---|---|---|---|---|
| dense | 0/7 | 0/0 | 0/0 | $0.154829 |
| hybrid | 1/7 | 1/1 | 0/0 | $0.153996 |
| corrective | 0/7 | 0/0 | 0/0 | $0.210378 |

Full retrieval, routing, citation, uncertainty, and cost counts: `report.json`.
Reference ANSWERABLE cases; failed retrievals remain zero-scored.
Unscored semantic outcomes are unresolved, never inferred from the model's own support check.

## Cases requiring review

- privileged-1 / dense: conflict; not complete and supported
- privileged-1 / hybrid: provider_failed; not complete and supported
- privileged-1 / corrective: provider_failed; not complete and supported
- privileged-2 / dense: provider_failed; not complete and supported
- privileged-2 / hybrid: provider_failed; not complete and supported
- privileged-2 / corrective: provider_failed; not complete and supported
- privileged-3 / dense: provider_failed; not complete and supported
- privileged-3 / hybrid: provider_failed; not complete and supported
- privileged-3 / corrective: provider_failed; not complete and supported
- privileged-4 / dense: provider_failed; not complete and supported
- privileged-4 / hybrid: provider_failed; not complete and supported
- privileged-4 / corrective: provider_failed; not complete and supported
- privileged-5 / dense: provider_failed; not complete and supported
- privileged-5 / hybrid: conflict; not complete and supported
- privileged-5 / corrective: provider_failed; not complete and supported
- ai-1 / dense: provider_failed; not complete and supported
- ai-1 / hybrid: provider_failed; not complete and supported
- ai-1 / corrective: provider_failed; not complete and supported
- ai-2 / dense: provider_failed; not complete and supported
- ai-2 / hybrid: provider_failed; not complete and supported
- ai-2 / corrective: provider_failed; not complete and supported
- ai-3 / dense: provider_failed; not complete and supported
- ai-3 / hybrid: awaiting_review; not complete and supported
- ai-3 / corrective: provider_failed; not complete and supported
- ai-4 / dense: provider_failed; not complete and supported
- ai-4 / hybrid: provider_failed; not complete and supported
- ai-4 / corrective: provider_failed; not complete and supported
- ai-5 / dense: provider_failed; not complete and supported
- ai-5 / hybrid: provider_failed; not complete and supported
- ai-5 / corrective: provider_failed; not complete and supported
- network-1 / dense: conflict; not complete and supported
- network-1 / hybrid: provider_failed; not complete and supported
- network-1 / corrective: provider_failed; not complete and supported
- network-2 / dense: provider_failed; not complete and supported
- network-2 / hybrid: provider_failed; not complete and supported
- network-2 / corrective: provider_failed; not complete and supported
- network-3 / dense: provider_failed; not complete and supported
- network-3 / hybrid: provider_failed; not complete and supported
- network-3 / corrective: provider_failed; not complete and supported
- network-4 / dense: awaiting_review; not complete and supported
- network-4 / hybrid: provider_failed; not complete and supported
- network-4 / corrective: provider_failed; not complete and supported
- network-5 / dense: provider_failed; not complete and supported
- network-5 / hybrid: provider_failed; not complete and supported
- network-5 / corrective: provider_failed; not complete and supported
- support-1 / dense: provider_failed; not complete and supported
- support-1 / hybrid: conflict; not complete and supported
- support-1 / corrective: conflict; not complete and supported
- support-2 / dense: conflict; not complete and supported
- support-2 / hybrid: conflict; not complete and supported
- support-2 / corrective: unsupported; not complete and supported
- support-3 / dense: conflict; not complete and supported
- support-3 / hybrid: conflict; not complete and supported
- support-3 / corrective: conflict; not complete and supported
- support-4 / dense: unsupported; not complete and supported
- support-4 / hybrid: needs_clarification; not complete and supported
- support-4 / corrective: needs_clarification; not complete and supported
- support-5 / dense: conflict; not complete and supported
- support-5 / hybrid: conflict; not complete and supported
- support-5 / corrective: conflict; not complete and supported
- keys-1 / dense: awaiting_review; not complete and supported
- keys-1 / hybrid: awaiting_review; not complete and supported
- keys-1 / corrective: awaiting_review; not complete and supported
- keys-2 / dense: unsupported; not complete and supported
- keys-2 / corrective: unsupported; not complete and supported
- keys-3 / dense: awaiting_review; not complete and supported
- keys-3 / hybrid: awaiting_review; not complete and supported
- keys-3 / corrective: awaiting_review; not complete and supported
- keys-4 / dense: awaiting_review; not complete and supported
- keys-4 / hybrid: awaiting_review; not complete and supported
- keys-4 / corrective: needs_clarification; not complete and supported
- keys-5 / dense: awaiting_review; not complete and supported
- keys-5 / hybrid: awaiting_review; not complete and supported
- keys-5 / corrective: awaiting_review; not complete and supported
- availability-1 / dense: unsupported; not complete and supported
- availability-1 / hybrid: unsupported; not complete and supported
- availability-1 / corrective: unsupported; not complete and supported
- availability-2 / dense: unsupported; not complete and supported
- availability-2 / hybrid: unsupported; not complete and supported
- availability-2 / corrective: unsupported; not complete and supported
- availability-3 / dense: awaiting_review; not complete and supported
- availability-3 / hybrid: awaiting_review; not complete and supported
- availability-3 / corrective: provider_failed; not complete and supported
- availability-4 / dense: needs_clarification; not complete and supported
- availability-4 / hybrid: needs_clarification; not complete and supported
- availability-4 / corrective: needs_clarification; not complete and supported
- availability-5 / dense: unknown_evidence; not complete and supported
- availability-5 / hybrid: unsupported; not complete and supported
- availability-5 / corrective: unsupported; not complete and supported
