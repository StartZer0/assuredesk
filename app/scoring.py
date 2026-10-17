"""Offline metrics. Source anchors are gold; model assessments are never gold labels."""

from collections import Counter
import math
import random
import statistics


def ratio(n, d):
    return {"numerator": n, "denominator": d, "value": n / d if d else None}


def ranking(ids, relevant, k, grades=None):
    """Unreturned positions count against Precision@k; duplicates never earn extra credit."""
    seen, gains = set(), []
    grades = grades or {x: 1 for x in relevant}
    for x in ids[:k]:
        gains.append(grades.get(x, 0) if x not in seen else 0)
        seen.add(x)
    hits = len(set(ids[:k]) & set(relevant))
    dcg = sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(gains))
    ideal = sum(
        (2**g - 1) / math.log2(i + 2) for i, g in enumerate(sorted(grades.values(), reverse=True)[:k])
    )
    return {
        "recall": ratio(hits, len(relevant)),
        "precision": ratio(hits, k),
        "mrr": next((1 / (i + 1) for i, g in enumerate(gains) if g), 0.0) if relevant else None,
        "ndcg": dcg / ideal if ideal else None,
    }


def covers(anchor, ids, spans, *, parent=False):
    intervals = []
    for ident in set(ids):
        span = spans.get(ident, {})
        if span.get("source") != anchor["source"]:
            continue
        if span.get("hash") != anchor["hash"]:
            continue
        intervals.append(
            (
                span.get("parent_start" if parent else "start", 0),
                span.get("parent_end" if parent else "end", 0),
            )
        )
    cursor = anchor["start"]
    for a, b in sorted(intervals):
        if a > cursor:
            break
        cursor = max(cursor, b)
    return cursor >= anchor["end"]


def bundle_coverage(case, ids, spans, *, parent=False):
    requirements = case["requirements"]
    hits = sum(
        any(bundle and all(covers(a, ids, spans, parent=parent) for a in bundle) for bundle in req["bundles"])
        for req in requirements
    )
    return ratio(hits, len(requirements))


def family_interval(rows, *, seed=17):
    """Descriptive cluster bootstrap, sampling families rather than correlated questions."""
    grouped = {}
    for family, value in rows:
        grouped.setdefault(family, []).append(value)
    if len(grouped) < 2:
        return {"families": len(grouped), "lower": None, "upper": None}
    keys = sorted(grouped)
    rng = random.Random(seed)
    samples = []
    for _ in range(2000):
        values = [v for key in rng.choices(keys, k=len(keys)) for v in grouped[key]]
        samples.append(statistics.mean(values))
    samples.sort()
    return {"families": len(keys), "lower": samples[49], "upper": samples[1949], "seed": seed}


def routing(case, run):
    disposition = case["disposition"]
    status = run.get("trace", {}).get("proposal", {}).get("status")
    substantive = bool(run.get("draft") and run["draft"]["answer"] not in {"Unknown", "Declined"})
    expected = {
        "CLARIFICATION": {"needs_clarification"},
        "CONFLICT": {"conflict"},
        "PARTIAL": {"needs_evidence", "cannot_answer"},
        "UNSUPPORTED": {"cannot_answer", "needs_evidence"},
    }
    if disposition == "ANSWERABLE":
        return None
    return not substantive and status in expected[disposition]


def agreement(judgments):
    original = {}
    for j in judgments:
        if not j.get("adjudicated") and isinstance(j.get("complete_supported"), bool):
            original.setdefault(j["run"], {})[j["reviewer"]] = j["complete_supported"]
    pairs = [list(v.values()) for v in original.values() if len(v) == 2]
    if not pairs:
        return {"pairs": 0, "agreement": None, "kappa": None}
    observed = sum(a == b for a, b in pairs) / len(pairs)
    pa, pb = [sum(p[i] for p in pairs) / len(pairs) for i in (0, 1)]
    expected = pa * pb + (1 - pa) * (1 - pb)
    return {
        "pairs": len(pairs),
        "agreement": observed,
        "kappa": (observed - expected) / (1 - expected) if expected != 1 else None,
    }


def summarize(cases, runs, judgments, spans, *, planned_cases=None):
    by_case = {c["id"]: c for c in cases}
    selected = set(planned_cases or by_case)
    gold = [by_case[c] for c in sorted(selected)]
    # Separate reports per batch; ambiguous duplicate outcomes are rejected, never cherry-picked.
    if len({(r["case"], r["variant"]) for r in runs}) != len(runs):
        raise ValueError("Select one batch: duplicate case/variant outcomes")
    scored = {j["run"]: j for j in judgments if j.get("adjudicated") is True}
    result = {
        "planned_cases": len(gold),
        "attempted_runs": len(runs),
        "cost_usd": sum(r.get("cost", 0) for r in runs),
        "dispositions": dict(Counter(c["disposition"] for c in gold)),
        "retrieval_population": "Reference ANSWERABLE cases; failed retrievals remain zero-scored.",
        "review_agreement": agreement(judgments),
        "variants": {},
    }
    for mode in ("dense", "hybrid", "corrective"):
        subset = [r for r in runs if r["variant"] == mode]
        attempted = {r["case"]: r for r in subset}
        answerable = [c for c in gold if c["disposition"] == "ANSWERABLE"]

        def complete(r):
            return scored.get((r or {}).get("run"), {}).get("complete_supported") is True

        substantive = [
            r for r in subset if r.get("draft") and r["draft"]["answer"] not in {"Unknown", "Declined"}
        ]
        good = sum(complete(attempted.get(c["id"])) for c in answerable)
        metrics = {
            "attempted": len(subset),
            "missing_runs": sorted(selected - set(attempted)),
            "unscored": sum(r["run"] not in scored for r in subset),
            "supported_complete": ratio(good, len(answerable)),
            "selective_precision": ratio(sum(complete(r) for r in substantive), len(substantive)),
            "answer_coverage": ratio(
                sum(r["case"] in {c["id"] for c in answerable} for r in substantive), len(answerable)
            ),
            "missed_answerable": ratio(len(answerable) - good, len(answerable)),
            "complete_family_interval": family_interval(
                [(c["family"], int(complete(attempted.get(c["id"])))) for c in answerable]
            ),
            "safe_routing": {},
            "retrieval": {},
            "retrieval_cases": {},
            "cost_usd": sum(r.get("cost", 0) for r in subset),
            "failure_reasons": dict(Counter(r.get("stop", "") for r in subset)),
            "tokens": {
                key: sum(u.get(key, 0) for r in subset for u in r.get("trace", {}).get("usage", []))
                for key in ("input_tokens", "output_tokens")
            },
            "generation_attempts": sum(r.get("generation_attempts", 0) for r in subset),
            "embedding_attempts": sum(r.get("embedding_attempts", 0) for r in subset),
        }
        latencies = sorted(r.get("elapsed", 0) for r in subset)
        metrics["active_latency_seconds"] = {
            "p50": statistics.median(latencies) if latencies else None,
            "p95": latencies[math.ceil(len(latencies) * 0.95) - 1] if latencies else None,
        }
        for name, values in (
            ("admission_wait_seconds", [r.get("trace", {}).get("provider_wait_seconds", 0) for r in subset]),
            (
                "processing_latency_seconds",
                [r.get("elapsed", 0) + r.get("trace", {}).get("provider_wait_seconds", 0) for r in subset],
            ),
        ):
            values = sorted(values)
            metrics[name] = {
                "p50": statistics.median(values) if values else None,
                "p95": values[math.ceil(len(values) * 0.95) - 1] if values else None,
            }
        for disposition in ("PARTIAL", "CLARIFICATION", "CONFLICT", "UNSUPPORTED"):
            members = [c for c in gold if c["disposition"] == disposition]
            metrics["safe_routing"][disposition] = ratio(
                sum(routing(c, attempted.get(c["id"], {})) is True for c in members), len(members)
            )
        assertions = [a for r in substantive for a in scored.get(r["run"], {}).get("assertions", [])]
        metrics["unsupported_assertions"] = ratio(
            sum(a.get("supported") is False for a in assertions), len(assertions)
        )
        metrics["assertion_unscored_drafts"] = sum(
            not scored.get(r["run"], {}).get("assertions") for r in substantive
        )
        metrics["unsupported_question_rate"] = ratio(
            sum(
                any(a.get("supported") is False for a in scored.get(r["run"], {}).get("assertions", []))
                for r in substantive
            ),
            len(substantive),
        )
        ready = [r for r in subset if r.get("draft", {}) and r["draft"].get("supported")]
        metrics["ready_selective_precision"] = ratio(sum(complete(r) for r in ready), len(ready))
        citations = [c for r in subset for c in scored.get(r["run"], {}).get("citations", [])]
        metrics["citation_entailment"] = ratio(
            sum(c.get("entailed") is True for c in citations), len(citations)
        )
        metrics["citation_coverage"] = ratio(
            sum(a.get("supported") is True and a.get("cited") is True for a in assertions), len(assertions)
        )
        refs = [(r, ident) for r in subset for ident in (r.get("draft") or {}).get("evidence", [])]
        metrics["citation_integrity"] = ratio(
            sum(ident in spans and ident in r.get("trace", {}).get("supplied_ids", []) for r, ident in refs),
            len(refs),
        )
        times = [scored.get(r["run"], {}).get("review_minutes") for r in subset]
        metrics["review_minutes"] = {
            "total": sum(t for t in times if t is not None),
            "measured": sum(t is not None for t in times),
        }
        attempts = [a for r in subset for a in r.get("attempts", [])]
        metrics["cost_accounting"] = {
            "actual_usd": sum(a["actual"] for a in attempts if a.get("actual") is not None),
            "uncertain_reserved_usd": sum(a.get("reserved", 0) for a in attempts if a.get("actual") is None),
            "uncertain_attempts": sum(a.get("actual") is None for a in attempts),
        }
        approved = [
            scored[r["run"]] for r in subset if r["run"] in scored and "approval_correct" in scored[r["run"]]
        ]
        metrics["approval_mistakes"] = ratio(
            sum(j["approval_correct"] is False for j in approved), len(approved)
        )
        for stage in ("first_candidates", "final_candidates", "first_input", "final_input"):
            measured, bundles = [], []
            per_case = []
            for c in answerable:
                # Ranking requires a defined eligible answer target. Missing facts and
                # unclear scope are scored by disposition routing, not as precision zeros.
                # A planned but unrecorded run still contributes an empty ranking.
                r = attempted.get(c["id"], {})
                retrieval = r.get("trace", {}).get("retrieval", [])
                traces = r.get("trace", {}).get("inputs", r.get("trace", {}).get("trace", []))
                input_stage = stage.endswith("input")
                rows = traces if input_stage else retrieval
                ids = (
                    rows[0 if stage.startswith("first") else -1].get(
                        "supplied_ids" if input_stage else "candidate_ids", []
                    )
                    if rows
                    else []
                )
                anchors = [a for req in c["requirements"] for bundle in req["bundles"] for a in bundle]
                relevant = {
                    ident
                    for ident, span in spans.items()
                    if any(
                        span["source"] == a["source"]
                        and span["hash"] == a["hash"]
                        and max(span["start"], a["start"]) < min(span["end"], a["end"])
                        for a in anchors
                    )
                }
                row = {k: ranking(ids, relevant, k) for k in (1, 3, 6, 12, 20)}
                measured.append(row)
                per_case.append(
                    {
                        "case": c["id"],
                        "rankings": row,
                        "bundle_coverage": bundle_coverage(c, ids, spans, parent=input_stage),
                    }
                )
                if c["disposition"] == "ANSWERABLE":
                    bundles.append(bundle_coverage(c, ids, spans, parent=input_stage))
            summary = {}
            for k in (1, 3, 6, 12, 20):
                summary[str(k)] = {}
                for metric in ("recall", "precision", "mrr", "ndcg"):
                    values = [x[k][metric] for x in measured]
                    values = [v["value"] if isinstance(v, dict) else v for v in values]
                    values = [v for v in values if v is not None]
                    summary[str(k)][metric] = {
                        "mean": statistics.mean(values) if values else None,
                        "cases": len(values),
                    }
            summary["bundle_coverage"] = ratio(
                sum(b["numerator"] for b in bundles), sum(b["denominator"] for b in bundles)
            )
            metrics["retrieval"][stage] = summary
            metrics["retrieval_cases"][stage] = per_case
        metrics["strata"] = {
            name: {
                "attempted": sum(bool(by_case[r["case"]].get("reuse")) == reuse for r in subset),
                "complete": sum(
                    complete(r) and bool(by_case[r["case"]].get("reuse")) == reuse for r in subset
                ),
            }
            for name, reuse in (("reuse", True), ("non_reuse", False))
        }
        result["variants"][mode] = metrics
    pairs = []
    for c in gold:
        pair = {
            r["variant"]: scored[r["run"]]["complete_supported"]
            for r in runs
            if c["disposition"] == "ANSWERABLE" and r["case"] == c["id"] and r["run"] in scored
        }
        if "hybrid" in pair and "corrective" in pair:
            pairs.append((c["family"], pair["hybrid"], pair["corrective"]))
    result["paired"] = {
        "count": len(pairs),
        "recovery": ratio(sum(not a and b for _, a, b in pairs), sum(not a for _, a, _ in pairs)),
        "regression": ratio(sum(a and not b for _, a, b in pairs), sum(a for _, a, _ in pairs)),
        "net_change": ratio(sum(int(b) - int(a) for _, a, b in pairs), len(pairs)),
        "family_interval": family_interval([(f, int(b) - int(a)) for f, a, b in pairs]),
    }
    result["status"] = (
        "scored"
        if all(not v["missing_runs"] and not v["unscored"] for v in result["variants"].values())
        else "incomplete"
    )
    result["semantic_gate"] = {
        "threshold": 0.90,
        "passed": False,
        "reason": "Independent frozen locked-test evidence required; automated retrieval scores alone cannot pass this gate",
    }
    return result
