"""Narrow, tool-free reviewer provider interfaces."""
from __future__ import annotations
import json
from typing import Protocol
from core.ollama_client import call_ollama_chat
from review.models import ReviewReport,ReviewRequest

class ReviewProviderError(RuntimeError): pass

class ReviewProvider(Protocol):
    def review(self,request:ReviewRequest)->ReviewReport: ...

class OllamaReviewProvider:
    def __init__(self,model:str): self.model=model
    def review(self,request):
        messages=[
            {"role":"system","content":"You are a read-only code reviewer. Return only one strict JSON ReviewReport object. Do not propose or apply patches."},
            {"role":"user","content":json.dumps(request.to_dict(),ensure_ascii=False)},
        ]
        try:
            ok,content=call_ollama_chat(self.model,messages)
        except (TimeoutError,ConnectionError,OSError) as exc:
            raise ReviewProviderError(f"Reviewer transport failed: {exc}") from exc
        if not ok: raise ReviewProviderError(content)
        if not isinstance(content,str) or not content.strip():
            raise ReviewProviderError("Reviewer returned an empty response.")
        try: data=json.loads(content)
        except json.JSONDecodeError as exc: raise ReviewProviderError("Reviewer returned invalid JSON.") from exc
        if not isinstance(data,dict): raise ReviewProviderError("Reviewer JSON must be an object.")
        try: return ReviewReport.from_dict(data)
        except (TypeError,ValueError) as exc: raise ReviewProviderError(f"Invalid ReviewReport: {exc}") from exc
