"""Single-process P1-17 worker for queued local-AI drafting jobs."""
import os
import time

from integrations.ollama import OllamaClient
from knowledge import KnowledgeRepository
from rag_drafting import RagDraftProcessor


def build_processor() -> RagDraftProcessor:
    dsn = os.environ["PG_DSN"]
    repository = KnowledgeRepository(dsn)
    repository.init_schema()
    gateway = OllamaClient(
        os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434"),
        embedding_model=os.environ.get("EMBEDDING_MODEL", "bge-m3"),
        draft_model=os.environ.get("RAG_DRAFT_MODEL", "qwen3:14b"),
        timeout_s=float(os.environ.get("RAG_OLLAMA_TIMEOUT_S", "300")),
    )
    return RagDraftProcessor(repository, gateway)


def run_forever() -> None:
    processor = build_processor()
    poll_seconds = float(os.environ.get("RAG_WORKER_POLL_S", "2"))
    if poll_seconds <= 0:
        raise ValueError("RAG_WORKER_POLL_S must be positive")
    try:
        while True:
            job = processor.repository.claim_next_draft_job()
            if job is None:
                time.sleep(poll_seconds)
                continue
            try:
                processor.process(job)
            except Exception:
                # The processor has persisted FAILED_REVIEW. Continue so one
                # bad document/model response cannot stop the local queue.
                continue
    finally:
        processor.gateway.close()


if __name__ == "__main__":
    run_forever()
