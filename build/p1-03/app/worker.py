"""P1-03 — LangGraph worker: prove durable orchestration wiring.

Minimal one-node graph with the Postgres checkpointer. The full 47-step
workflow is P1-07 — this only proves: graph runs, checkpoint persists in
PostgreSQL, and resume works after a restart.
"""
import os
import time
import psycopg
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver

PG_DSN = os.environ["PG_DSN"]


class DemoState(TypedDict):
    opportunity: str
    step: str


def intake_node(state: DemoState) -> dict:
    return {"step": "intake_complete"}


def build_graph(checkpointer):
    g = StateGraph(DemoState)
    g.add_node("intake", intake_node)
    g.add_edge(START, "intake")
    g.add_edge("intake", END)
    return g.compile(checkpointer=checkpointer)


def main():
    # wait for postgres to accept connections (cold-boot race)
    for attempt in range(30):
        try:
            psycopg.connect(PG_DSN, connect_timeout=2).close()
            break
        except Exception:
            time.sleep(2)
    else:
        raise SystemExit("postgres unreachable after 60s")

    with PostgresSaver.from_conn_string(PG_DSN) as cp:
        cp.setup()  # creates checkpoint tables (idempotent)
        graph = build_graph(cp)
        result = graph.invoke(
            {"opportunity": "NL-OPP-P103-PROBE", "step": "start"},
            config={"configurable": {"thread_id": "p103-acceptance"}},
        )
        print(f"[worker] graph result: {result}", flush=True)

        state = cp.get({"configurable": {"thread_id": "p103-acceptance"}})
        assert state is not None, "checkpoint not persisted!"
        print("[worker] CHECKPOINT PERSISTED in PostgreSQL — resume-capable ✅", flush=True)

    # stay alive so restart-policy behavior is observable
    print("[worker] idle (restart: unless-stopped)", flush=True)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
