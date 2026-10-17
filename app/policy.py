"""Shared authorization boundary, never inferred from prompts."""

from datetime import date
from sqlalchemy import select
from .db import Chunk, Meta, Source


class Rejected(Exception):
    def __init__(self, code, status=422):
        self.code, self.status = code, status
        super().__init__(code)


def require(condition, code="not_found", status=404):
    if not condition:
        raise Rejected(code, status)


def content_user(user, account):
    return bool(
        user and user.active and account in user.accounts and set(user.roles) & {"sales", "security_reviewer"}
    )


def access(user, workbook):
    require(content_user(user, workbook.account) and workbook.product == "atlas")


def security(user, workbook=None):
    require(user and user.active and "security_reviewer" in user.roles)
    if workbook:
        access(user, workbook)


def curate_source(user, account, disclosure, audience):
    security(user)
    require(account == "*" or account in user.accounts)
    if account == "*":
        required_accounts = set(audience) if disclosure == "customer_approved" else {"acme", "nova"}
        require(required_accounts <= set(user.accounts))


def admin(user):
    require(user and user.active and "administrator" in user.roles)


def readable(user, source, account):
    return (
        content_user(user, account)
        and source.product == "atlas"
        and source.account in ("*", account)
        and bool(set(user.roles) & set(source.roles))
    )


def eligible(user, source, workbook, *, disclose=True):
    current = date.today().isoformat()
    valid = (
        source.active
        and not source.superseded
        and source.valid_from <= workbook.as_of <= source.valid_until
        and current <= source.valid_until
    )
    return (
        valid
        and readable(user, source, workbook.account)
        and (
            not disclose
            or (
                source.authority != "historical_response"
                and (
                    source.disclosure == "public"
                    or (source.disclosure == "customer_approved" and workbook.account in source.audience)
                )
            )
        )
    )


def epoch(session, lock=False):
    stmt = select(Meta).where(Meta.id == 1)
    return session.scalar(stmt.with_for_update() if lock else stmt)


def evidence(session, user, workbook, ids, *, disclose=True):
    result = []
    for ident in dict.fromkeys(ids):
        chunk = session.get(Chunk, ident)
        require(chunk is not None)
        source = session.get(Source, chunk.source_id)
        require(eligible(user, source, workbook, disclose=disclose))
        result.append((chunk, source))
    return result


def draft_access(session, user, workbook, draft):
    access(user, workbook)
    for ident in draft.evidence:
        chunk = session.get(Chunk, ident)
        require(chunk is not None and readable(user, session.get(Source, chunk.source_id), workbook.account))
