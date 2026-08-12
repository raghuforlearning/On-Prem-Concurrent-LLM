"""P1-17 queued, grounded draft processor.

The processor deliberately keeps retrieved language and deterministic quote
facts as separate inputs all the way to the local model adapter.
"""
from typing import Any


class RagDraftProcessor:
    def __init__(self, repository: Any, gateway: Any, *, top_k: int = 5):
        self.repository = repository
        self.gateway = gateway
        self.top_k = top_k

    def process(self, job: dict[str, Any]) -> dict[str, Any]:
        try:
            commercial_facts = self.repository.accepted_commercial_facts(
                job["accepted_quote_id"]
            )
            embeddings = self.gateway.embed([job["query"]])
            retrieval = self.repository.search(
                query=job["query"],
                query_vector=embeddings[0],
                purpose="CUSTOMER_DRAFT",
                actor=job["actor"],
                actor_role=job["actor_role"],
                opp_id=job["opp_id"],
                customer_scope=job.get("customer_scope"),
                top_k=self.top_k,
            )
            if not retrieval.citations:
                raise ValueError("no approved knowledge matched the draft request")

            knowledge_context = [
                {
                    "label": citation.label,
                    "content": citation.content,
                    "provenance": citation.as_dict(include_content=False),
                }
                for citation in retrieval.citations
            ]
            generated = self.gateway.generate_grounded(
                question=job["query"],
                knowledge_context=knowledge_context,
                commercial_facts=commercial_facts,
            )
            return self.repository.complete_draft(
                job=job,
                retrieval=retrieval,
                commercial_facts=commercial_facts,
                draft_text=generated["draft"],
                citations_used=generated["citations_used"],
                model=generated["model"],
            )
        except Exception as exc:
            self.repository.fail_draft(
                job["job_id"],
                error_message=str(exc),
                actor="rag-worker",
                opp_id=job["opp_id"],
            )
            raise
