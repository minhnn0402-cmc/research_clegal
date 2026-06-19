import unittest
from unittest.mock import patch, MagicMock

from src.domain.llms.relation_fallback import LangExtractRelationFallback


class _DummyAnnotatedDocument:
    extractions = []


class TestLangExtractCmcProvider(unittest.TestCase):
    
    @patch("src.domain.llms.relation_fallback.LangExtractRelationFallback._get_from_cache", return_value=None)
    @patch("src.domain.llms.relation_fallback.LangExtractRelationFallback._load_langextract_examples", return_value=[MagicMock()])
    def test_forces_openai_provider_when_base_url_set(self, _mock_examples, _mock_cache) -> None:

        with patch("langextract.extract", return_value=_DummyAnnotatedDocument()) as mock_extract:
            fallback = LangExtractRelationFallback(
                model_id="cmc-legal",
                base_url="http://cmc-host:8106/v1",
                api_key="fake-key",
            )
            # Invoke extraction
            content = "Bãi bỏ điểm đ khoản 2 Điều 5 Luật Đất đai."
            fallback.extract_relation_targets(content)
            
            # Ensure langextract.extract was called with the forced OpenAI config
            self.assertTrue(mock_extract.called, "langextract.extract was not called (possibly due to cache hit)")
            
            _args, kwargs = mock_extract.call_args
            self.assertEqual(kwargs["text_or_documents"], content)
            self.assertIn("config", kwargs)
            config = kwargs["config"]
            
            self.assertEqual(getattr(config, "provider", None), "openai")
            self.assertEqual(getattr(config, "model_id", None), "cmc-legal")
            self.assertEqual(config.provider_kwargs.get("base_url"), "http://cmc-host:8106/v1")
            self.assertEqual(config.provider_kwargs.get("api_key"), "fake-key")


if __name__ == "__main__":
    unittest.main()
