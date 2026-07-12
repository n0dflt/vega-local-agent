import unittest
from unittest.mock import patch
from review.code_reviewer import OllamaReviewProvider,ReviewProviderError
from review.models import ReviewRequest

class CodeReviewerTests(unittest.TestCase):
    def request(self): return ReviewRequest("workflow-"+"a"*32,"bugfix","fix",[],1,"patch-1",[],["a.py"],[{"ok":True}],{},[])
    @patch("review.code_reviewer.call_ollama_chat",return_value=(True,"not json"))
    def test_free_text_is_not_success(self,_call):
        with self.assertRaises(ReviewProviderError): OllamaReviewProvider("model").review(self.request())
    @patch("review.code_reviewer.call_ollama_chat",return_value=(False,"offline"))
    def test_provider_error_is_distinct(self,_call):
        with self.assertRaises(ReviewProviderError): OllamaReviewProvider("model").review(self.request())
    @patch("review.code_reviewer.call_ollama_chat",side_effect=TimeoutError("timeout"))
    def test_timeout_is_provider_error(self,_call):
        with self.assertRaises(ReviewProviderError): OllamaReviewProvider("model").review(self.request())
    @patch("review.code_reviewer.call_ollama_chat",side_effect=ConnectionRefusedError("refused"))
    def test_connection_refused_is_provider_error(self,_call):
        with self.assertRaises(ReviewProviderError): OllamaReviewProvider("model").review(self.request())
    @patch("review.code_reviewer.call_ollama_chat",return_value=(True,""))
    def test_empty_response_is_rejected(self,_call):
        with self.assertRaises(ReviewProviderError): OllamaReviewProvider("model").review(self.request())
    @patch("review.code_reviewer.call_ollama_chat",return_value=(True,"```json\n{}\n```"))
    def test_markdown_wrapped_json_is_rejected(self,_call):
        with self.assertRaises(ReviewProviderError): OllamaReviewProvider("model").review(self.request())
    @patch("review.code_reviewer.call_ollama_chat",return_value=(True,"[]"))
    def test_json_wrong_type_is_rejected(self,_call):
        with self.assertRaises(ReviewProviderError): OllamaReviewProvider("model").review(self.request())
    @patch("review.code_reviewer.call_ollama_chat",return_value=(True,"{}"))
    def test_missing_required_fields_are_rejected(self,_call):
        with self.assertRaises(ReviewProviderError): OllamaReviewProvider("model").review(self.request())

if __name__=="__main__": unittest.main()
