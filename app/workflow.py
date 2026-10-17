"""Bounded LangGraph execution. Checkpoints contain only run IDs and routing codes."""

import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from sqlalchemy import func, select

from . import policy, service
from .config import LIMITS
from .db import Approval, Attempt, Draft, Job, Run, User, Stage, db_time, digest
from .providers import input_bound, request_messages
from .retrieval import retrieve
from .schema import Proposal, Support


class State(TypedDict):
    run_id: str
    route: str
    step: int


class Engine:
    def __init__(self, db, generator, embeddings, *, job_guard=None):
        self.db, self.generator, self.embeddings = db, generator, embeddings
        self.job_guard = job_guard

    @staticmethod
    def stage_key(state, node):
        return f"{state['run_id']}:{state.get('step', 0)}:{node}"

    def finish(self, s, state, node, route):
        key = self.stage_key(state, node)
        stage = s.get(Stage, key)
        if stage is None:
            stage = Stage(key=key, run_id=state["run_id"], inputs={})
            s.add(stage)
        stage.output = {"route": route, "step": state.get("step", 0) + 1}
        return stage.output

    def context(self, s, run_id, *, lock=False, terminal=False):
        if lock:
            meta = policy.epoch(s, lock=True)
        else:
            meta = policy.epoch(s)
        run = s.get(Run, run_id)
        policy.require(run is not None)
        if self.job_guard:
            ident, owner, generation = self.job_guard
            job = s.get(Job, ident)
            policy.require(
                job
                and job.owner == owner
                and job.generation == generation
                and not job.cancel
                and job.status == "running"
                and job.lease > db_time(s),
                "lease_lost",
                409,
            )
        policy.require(run.status != "cancelled", "cancelled", 409)
        user = s.get(User, run.principal_id)
        q, book = service.question_context(s, user, run.question_id)
        policy.require(
            q.revision == run.revision and (run.policy, run.corpus) == (meta.policy, meta.corpus),
            "stale_run",
            409,
        )
        policy.require(not q.blocked, "review_required", 409)
        active = run.elapsed + (time.time() - run.active_started if run.active_started else 0)
        policy.require(terminal or active <= LIMITS["active_seconds"], "time_limit", 409)
        return run, user, q, book

    def reserve(self, run_id, kind, *, repair=False):
        with self.db.transaction() as s:
            run, user, q, book = self.context(s, run_id, lock=True)
            if kind == "embedding":
                policy.require(run.embedding_attempts < LIMITS["embedding_attempts"], "embedding_limit", 409)
                run.embedding_attempts += 1
                cost = 0.0  # Local CPU inference; runtime is still bounded and recorded.
            else:
                policy.require(run.generation_attempts < LIMITS["generation_attempts"], "attempt_limit", 409)
                if repair:
                    policy.require(not run.repair_used, "repair_limit", 409)
                    run.repair_used = True
                run.generation_attempts += 1
                cost = self.generator.reserve_cost()
            charge = func.coalesce(Attempt.actual, Attempt.reserved)
            limits = [
                (Attempt.run_id == run.id, LIMITS["run_usd"]),
                (Attempt.workbook_id == book.id, LIMITS["workbook_usd"]),
                (Attempt.created >= (int(time.time()) // 86400) * 86400, 5.0),
            ]
            for key, cap in [("evaluation_batch", 15.0), ("evaluation_campaign", 30.0)]:
                if run.record.get(key):
                    related = select(Run.id).where(Run.record[key].as_string() == run.record[key])
                    limits.append(
                        (
                            (Attempt.run_id.in_(related))
                            | (Attempt.details[key].as_string() == run.record[key]),
                            cap,
                        )
                    )
            for predicate, cap in limits:
                spent = s.scalar(select(func.coalesce(func.sum(charge), 0)).where(predicate))
                policy.require(spent + cost <= cap + 1e-9, "spend_limit", 409)
            settings = getattr(self.generator, "settings", None)
            details = {
                "model": self.embeddings.model_id
                if kind == "embedding"
                else getattr(settings, "model", "test"),
                "input_price": 0 if kind == "embedding" else getattr(settings, "input_price", 0),
                "output_price": 0 if kind == "embedding" else getattr(settings, "output_price", 0),
                "round": run.rounds,
                "repair": repair,
                "config": run.record.get("config"),
                "evaluation_batch": run.record.get("evaluation_batch"),
                "evaluation_campaign": run.record.get("evaluation_campaign"),
            }
            attempt = Attempt(run_id=run.id, workbook_id=book.id, kind=kind, reserved=cost, details=details)
            s.add(attempt)
            s.flush()
            return attempt.id

    def reconcile(self, attempt_id, actual):
        with self.db.transaction() as s:
            attempt = s.get(Attempt, attempt_id)
            if actual is not None:
                attempt.actual, attempt.status = max(0, actual), "complete"
            attempt.details = {
                **attempt.details,
                "finished": time.time(),
                **(getattr(self.generator, "last_usage", {}) if attempt.kind == "generation" else {}),
            }

    def call(self, run_id, kind, payload, schema, *, repair=False):
        policy.require(
            input_bound(request_messages(kind, payload, schema), schema) <= 6000, "context_limit", 422
        )
        if hasattr(self.generator, "admit"):
            with self.db.transaction() as s:
                self.context(s, run_id)
            start_wait = time.time()
            self.generator.admit()
            waited = time.time() - start_wait
            with self.db.transaction() as s:
                run, _, _, _ = self.context(s, run_id, terminal=True)
                if run.active_started:
                    run.active_started += waited
                run.record = {
                    **run.record,
                    "provider_wait_seconds": run.record.get("provider_wait_seconds", 0) + waited,
                }
        attempt = self.reserve(run_id, "generation", repair=repair)
        try:
            parsed, cost = self.generator.invoke(kind, payload, schema)
        except policy.Rejected:
            with self.db.transaction() as s:
                row = s.get(Attempt, attempt)
                row.details = {
                    **row.details,
                    **getattr(self.generator, "last_error", {}),
                    "finished": time.time(),
                }
            raise
        self.reconcile(attempt, cost)
        with self.db.transaction() as s:
            run, _, _, _ = self.context(s, run_id)
            usage = getattr(self.generator, "last_usage", {})
            record = dict(run.record)
            record["usage"] = record.get("usage", []) + [{"attempt": attempt, **usage}]
            run.record = record
        if parsed is None:
            if repair:
                raise policy.Rejected("invalid_model_output")
            correction = (
                "Return concise schema-valid JSON; use null for non-draft answers."
                if schema is Proposal
                else "Return concise JSON with supported, missing, next_queries."
            )
            return self.call(run_id, kind, {**payload, "format_retry": correction}, schema, repair=True)
        return parsed

    def search(self, state):
        ident = state["run_id"]
        with self.db.transaction() as s:
            run, user, q, book = self.context(s, ident, lock=True)
            prior = s.get(Stage, self.stage_key(state, "search"))
            if prior:
                queries = prior.inputs["queries"]
            else:
                limit = LIMITS["retrieval_rounds"] if run.mode == "corrective" else 1
                if run.rounds >= limit:
                    return self.finish(s, state, "search", "review")
                record = dict(run.record)
                queries = record.get("next_queries") or [q.text]
                queries = queries[:1] if run.rounds == 0 else queries[:2]
                seen_queries = record.get("queries", [])
                queries = [x for x in queries if x not in seen_queries]
                if not queries:
                    run.stop_reason = "no_progress"
                    return self.finish(s, state, "search", "review")
                run.rounds += 1
                record["queries"] = seen_queries + queries
                run.record = record
                s.add(
                    Stage(
                        key=self.stage_key(state, "search"),
                        run_id=ident,
                        inputs={
                            "queries": queries,
                            "input_digest": digest([queries, run.policy, run.corpus]),
                        },
                    )
                )
        vectors = []
        for query in queries:
            # One embedding attempt per query, no hidden retry or scope-changing arguments.
            attempt = self.reserve(ident, "embedding")
            vectors.append(self.embeddings.query(query))
            self.reconcile(attempt, 0)
        with self.db.transaction() as s:
            run, user, q, book = self.context(s, ident, lock=True)
            ids = retrieve(s, user, book, queries, vectors, run.mode, self.embeddings.model_id)
            record = dict(run.record)
            old = set(record.get("seen_evidence", []))
            anchors = list(
                dict.fromkeys(
                    x
                    for r in record.get("proposal", {}).get("requirements", [])
                    if r["coverage"] == "supported"
                    for x in r["evidence_ids"]
                )
            )[:3]
            # ponytail: retain three anchors within the six-excerpt context; expand only if measured cases need more.
            ids = list(dict.fromkeys([*anchors, *ids]))[:20]
            record["candidate_ids"] = ids
            record["retrieval"] = record.get("retrieval", []) + [
                {
                    "round": run.rounds,
                    "candidate_ids": ids,
                    "query_count": len(queries),
                    "queries": queries,
                    "new_ids": sorted(set(ids) - old),
                }
            ]
            record["seen_evidence"] = sorted(old | set(ids))
            run.record = record
            return self.finish(s, state, "search", "assess" if ids else "review")

    def payload(self, s, run, user, q, book, schema, kind):
        payload = {"question": q.text, "product": book.product, "as_of": book.as_of, "evidence": []}
        if run.rounds > 1:
            payload["missing_requirements"] = run.record.get("support", {}).get("missing", []) or [
                r["text"]
                for r in run.record.get("proposal", {}).get("requirements", [])
                if r["coverage"] == "missing"
            ]
        selected = []
        source_counts, spans = {}, []
        for chunk, src in policy.evidence(s, user, book, run.record.get("candidate_ids", [])):
            if len(selected) >= 6:
                break
            if source_counts.get(src.id, 0) >= 2:
                continue
            start, end = chunk.start, chunk.start + len(chunk.text)
            if any(
                sid == src.id and loc == chunk.locator and max(a, start) < min(b, end)
                for sid, loc, a, b in spans
            ):
                continue
            item = {
                "id": chunk.id,
                "title": src.title,
                "topic": src.family,
                "locator": chunk.locator,
                "valid_from": src.valid_from,
                "text": chunk.parent_text,
            }
            trial = {**payload, "evidence": payload["evidence"] + [item]}
            if input_bound(request_messages(kind, trial, schema), schema) > 5900:
                continue
            payload = trial
            selected.append(chunk.id)
            spans.append((src.id, chunk.locator, start, end))
            source_counts[src.id] = source_counts.get(src.id, 0) + 1
        return payload, selected

    def assess(self, state):
        ident = state["run_id"]
        with self.db.transaction() as s:
            run, user, q, book = self.context(s, ident)
            payload, selected = self.payload(s, run, user, q, book, Proposal, "assess")
            if not selected:
                return self.finish(s, state, "assess", "review")
            record = dict(run.record)
            record["inputs"] = record.get("inputs", []) + [{"round": run.rounds, "supplied_ids": selected}]
            run.record = record
        proposal = self.call(ident, "assess", payload, Proposal)
        refs = {x for r in proposal.requirements for x in r.evidence_ids}
        policy.require(refs <= set(selected), "unknown_evidence", 422)
        with self.db.transaction() as s:
            run, user, q, book = self.context(s, ident, lock=True)
            record = dict(run.record)
            old_supplied = set(record.get("supplied_ids", []))
            old_supported = set(record.get("supported_requirements", []))
            supported = {r.text for r in proposal.requirements if r.coverage == "supported"}
            progress = bool(set(selected) - old_supplied or supported - old_supported)
            record.update(
                proposal=proposal.model_dump(),
                supplied_ids=selected,
                next_queries=proposal.next_queries,
                supported_requirements=sorted(supported),
            )
            record["trace"] = record.get("trace", []) + [
                {
                    "round": run.rounds,
                    "status": proposal.status,
                    "evidence_count": len(selected),
                    "supplied_ids": selected,
                    "queries": record.get("retrieval", [{}])[-1].get("queries", []),
                    "new_ids": sorted(set(selected) - old_supplied),
                    "supported_requirements": sorted(supported),
                    "requirements": proposal.model_dump()["requirements"],
                    "progress": progress,
                }
            ]
            run.record = record
            if proposal.status == "draft_proposed":
                return self.finish(s, state, "assess", "check")
            if run.rounds > 1 and not progress:
                run.stop_reason = "no_progress"
            elif proposal.status == "needs_evidence" and proposal.next_queries:
                return self.finish(s, state, "assess", "search")
            else:
                run.stop_reason = proposal.status
            return self.finish(s, state, "assess", "review")

    def check(self, state):
        ident = state["run_id"]
        with self.db.transaction() as s:
            run, user, q, book = self.context(s, ident)
            proposal = Proposal.model_validate(run.record["proposal"])
            ids = list(dict.fromkeys(x for r in proposal.requirements for x in r.evidence_ids))
            supplied = list(dict.fromkeys([*ids, *run.record.get("supplied_ids", [])]))
            rows = policy.evidence(s, user, book, supplied)
            payload = {
                "question": q.text,
                "answer": proposal.answer,
                "recipient": book.account,
                "product": book.product,
                "requirements": proposal.model_dump()["requirements"],
                "explanation": proposal.explanation,
                "cited_ids": ids,
                "evidence": [
                    {"id": c.id, "title": src.title, "topic": src.family, "text": c.parent_text}
                    for c, src in rows
                ],
            }
            # Claimed evidence is mandatory; remove only extra context to meet the same bound.
            while input_bound(request_messages("check", payload, Support), Support) > 6000:
                extra = next(
                    (
                        i
                        for i in reversed(range(len(payload["evidence"])))
                        if payload["evidence"][i]["id"] not in ids
                    ),
                    None,
                )
                if extra is None:
                    break
                payload["evidence"].pop(extra)
        check = self.call(ident, "check", payload, Support)
        with self.db.transaction() as s:
            run, user, q, book = self.context(s, ident, lock=True)
            record = dict(run.record)
            record["support"] = check.model_dump()
            if check.supported and not check.missing:
                draft = service.new_draft(
                    s,
                    user,
                    q.id,
                    q.revision,
                    proposal.answer,
                    proposal.explanation,
                    ids,
                    supported=True,
                    claims=[{"text": r.text, "evidence_ids": r.evidence_ids} for r in proposal.requirements],
                )
                run.revision = q.revision
                record["draft_id"] = draft.id
                run.record = record
                return self.finish(s, state, "check", "review")
            record["next_queries"] = check.next_queries
            run.record = record
            run.stop_reason = "unsupported"
            return self.finish(s, state, "check", "search" if check.next_queries else "review")

    def review(self, state):
        ident = state["run_id"]
        with self.db.transaction() as s:
            run, user, q, book = self.context(s, ident, lock=True, terminal=True)
            record = dict(run.record)
            if not record.get("draft_id"):
                draft = service.new_draft(
                    s,
                    user,
                    q.id,
                    q.revision,
                    "Unknown",
                    "Further review is required; no complete supported answer was established.",
                    [],
                    supported=False,
                )
                run.revision = q.revision
                record["draft_id"] = draft.id
                run.record = record
            if run.active_started:
                run.elapsed += max(0, time.time() - run.active_started)
                run.active_started = None
            run.status = "awaiting_review"
            draft_id = record["draft_id"]
        interrupt({"run_id": ident, "draft_id": draft_id})
        with self.db.transaction() as s:
            run, user, q, book = self.context(s, ident, lock=True, terminal=True)
            draft = s.get(Draft, run.record["draft_id"])
            approval = s.scalar(select(Approval).where(Approval.draft_id == draft.id))
            policy.require(approval and approval.expires > time.time(), "approval_required", 409)
            policy.require(
                approval.fingerprint == service.fingerprint(s, user, q, book, draft), "stale_approval", 409
            )
            run.status = "succeeded"
        return {"route": "done"}

    def bounded(self, node):
        def invoke(state):
            try:
                with self.db.transaction() as s:
                    self.context(s, state["run_id"], terminal=True)
                    prior = s.get(Stage, self.stage_key(state, node.__name__))
                    if prior and prior.output is not None:
                        return prior.output
                return node(state)
            except policy.Rejected as exc:
                if exc.code not in {
                    "time_limit",
                    "attempt_limit",
                    "spend_limit",
                    "embedding_limit",
                    "repair_limit",
                    "context_limit",
                    "provider_failed",
                    "embedding_failed",
                    "invalid_model_output",
                    "unknown_evidence",
                    "embedding_input_limit",
                }:
                    raise
                with self.db.transaction() as s:
                    run, _, _, _ = self.context(s, state["run_id"], lock=True, terminal=True)
                    run.stop_reason = exc.code
                    return self.finish(s, state, node.__name__, "review")

        return invoke

    def graph(self, checkpointer):
        graph = StateGraph(State)
        graph.add_node("search", self.bounded(self.search))
        graph.add_node("assess", self.bounded(self.assess))
        graph.add_node("check", self.bounded(self.check))
        graph.add_node("review", self.review)
        graph.add_edge(START, "search")
        for name in ["search", "assess", "check"]:
            graph.add_conditional_edges(
                name, lambda state: state["route"], {x: x for x in ["search", "assess", "check", "review"]}
            )
        graph.add_edge("review", END)
        return graph.compile(checkpointer=checkpointer)
