"""Optional P1-17 smoke test against the approved internal Ollama service."""
import os
import unittest

from integrations.ollama import OllamaClient


@unittest.skipUnless(
    os.environ.get("P117_TEST_OLLAMA_URL"),
    "set P117_TEST_OLLAMA_URL to the approved internal Ollama endpoint",
)
class LiveOllamaRagAdapterTests(unittest.TestCase):
    def test_embedding_dimensions_and_grounded_draft_contract(self):
        client = OllamaClient(
            os.environ["P117_TEST_OLLAMA_URL"],
            embedding_model=os.environ.get("EMBEDDING_MODEL", "bge-m3"),
            draft_model=os.environ.get("RAG_DRAFT_MODEL", "qwen3:14b"),
            timeout_s=300,
        )
        try:
            embeddings = client.embed(["NationLabs approved redundant firewall design"])
            self.assertEqual(len(embeddings), 1)
            self.assertEqual(len(embeddings[0]), 1024)
            generated = client.generate_grounded(
                question="Draft one sentence describing the approved design and cite it.",
                knowledge_context=[
                    {
                        "label": "K1",
                        "content": "The approved design uses a redundant firewall pair.",
                        "provenance": {
                            "approval_status": "APPROVED",
                            "source_uri": "controlled://p117/live-smoke",
                        },
                    }
                ],
                commercial_facts={
                    "authority": "ACCEPTED_VALIDATED_QUOTE",
                    "currency": "AED",
                    "total": "29925.00",
                },
            )
        finally:
            client.close()
        self.assertTrue(generated["draft"])
        self.assertEqual(generated["model"], "qwen3:14b")
        self.assertEqual(generated["citations_used"], ["K1"])


if __name__ == "__main__":
    unittest.main()
