"""Active-app PostgreSQL test bootstrap.

The suite always targets the explicit ``PG_DSN`` supplied by the caller.  CI
and local runs must point it at a disposable database; no fallback DSN exists.
"""
import os


def pytest_sessionstart(session):
    if not os.environ.get("PG_DSN"):
        return
    import psycopg

    from db import PG_DSN, init_schema
    import approvals
    import followup
    import quotes
    import quote_comparison
    import proposals
    import vendors

    init_schema()
    with psycopg.connect(PG_DSN) as conn:
        vendors.init_vendors(conn)
        followup.init_followups(conn)
        approvals.init_approvals(conn)
        quotes.init_quotes(conn)
    quote_comparison.init_quote_comparison(PG_DSN)
    proposals.init_proposals(PG_DSN)
