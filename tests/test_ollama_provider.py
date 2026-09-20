import json
import unittest

from src.analysis.ollama_provider import OllamaNewsAnalysisProvider
from src.models import PendingArticle


class OllamaProviderTests(unittest.TestCase):
    def test_uses_local_structured_output_without_streaming(self):
        requests = []

        def transport(payload):
            requests.append(payload)
            return {
                "message": {
                    "content": json.dumps(
                        {
                            "stock_symbol": "2330",
                            "company_name": "台積電",
                            "ai_summary": "營收展望上調。",
                            "sentiment": "positive",
                            "sentiment_score": 0.7,
                            "importance_score": 4,
                            "topic": "guidance",
                        }
                    )
                }
            }

        provider = OllamaNewsAnalysisProvider(model="test-local", transport=transport)
        result = provider.analyze(
            PendingArticle(
                1,
                "2026-08-23T07:00:00Z",
                "2330",
                None,
                "台積電上調展望",
                "公司上調營收展望。",
                "Publisher",
            )
        )
        self.assertEqual(result.company_name, "台積電")
        self.assertEqual(requests[0]["model"], "test-local")
        self.assertFalse(requests[0]["stream"])
        self.assertEqual(requests[0]["options"]["temperature"], 0)
        self.assertEqual(requests[0]["format"]["type"], "object")


if __name__ == "__main__":
    unittest.main()
