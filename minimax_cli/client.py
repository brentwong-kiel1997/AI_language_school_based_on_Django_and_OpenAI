import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
import httpx
from .config import Config

class MiniMaxError(Exception): pass
class AuthenticationError(MiniMaxError): pass
class APIError(MiniMaxError): pass
class NetworkError(MiniMaxError): pass
class ValidationError(MiniMaxError): pass
class QuotaExceededError(APIError): pass

@dataclass
class ChatResponse:
    text: str
    raw: Dict[str, Any]
    usage: Any = None
    model: Optional[str] = None
    choices: Any = None
    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)

class MiniMaxClient:
    def __init__(self, config=None, *, base_url=None, timeout=None, quota_endpoint=None, search_endpoint=None, transport=None):
        self.config = config or Config.load(); self.base_url = (base_url or self.config.base_url).rstrip("/")
        self.quota_endpoint = quota_endpoint or self.config.quota_endpoint
        self.search_endpoint = search_endpoint or self.config.search_endpoint
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout or self.config.timeout_seconds, transport=transport)
    def close(self): self._client.close()
    def __enter__(self): return self
    def __exit__(self, *_args): self.close()
    def _headers(self):
        if not self.config.api_key: raise AuthenticationError("MINIMAX_API_KEY is not configured")
        return {"Authorization": f"Bearer {self.config.api_key}", "Content-Type":"application/json"}
    def _request(self, method, path, **kwargs):
        try: response = self._client.request(method, path, headers=self._headers(), **kwargs)
        except httpx.HTTPError as exc: raise NetworkError(str(exc)) from exc
        if response.status_code in (401,403): raise AuthenticationError(response.text)
        if response.status_code == 429: raise QuotaExceededError(response.text)
        if response.status_code >= 400: raise APIError(response.text)
        return response
    @staticmethod
    def _response(payload, text=""):
        choices = payload.get("choices") or []
        if not text and choices:
            item=choices[0]; message=item.get("message", {}) or {}; text=message.get("content", item.get("text", "")) or ""
        return ChatResponse(text, payload, payload.get("usage"), payload.get("model"), choices)
    def text_chat(self, messages: List[Dict[str,str]], model=None, temperature=0, max_tokens=None, json_mode=False, stream=False, on_delta: Optional[Callable[[str],None]]=None):
        if not isinstance(messages,list) or not messages: raise ValidationError("messages must be non-empty list")
        outgoing=list(messages)
        if json_mode: outgoing.insert(0,{"role":"system","content":"Respond with valid JSON only. Do not include markdown fences."})
        body={"model":model or self.config.text_model,"messages":outgoing,"temperature":temperature,"stream":stream}
        body["max_tokens"] = self.config.max_tokens if max_tokens is None else max_tokens
        response=self._request("POST","/v1/text/chatcompletion_v2",json=body)
        if not stream:
            try: return self._response(response.json())
            except (ValueError,TypeError) as exc: raise APIError("Invalid JSON response") from exc
        text=""; events=[]
        for line in response.iter_lines():
            if isinstance(line,bytes): line=line.decode("utf-8","replace")
            if not line.startswith("data:"): continue
            value=line[5:].strip()
            if not value or value=="[DONE]": continue
            try: event=json.loads(value)
            except ValueError: continue
            events.append(event); choices=event.get("choices") or [{}]; delta=choices[0].get("delta",{}).get("content","") or event.get("delta","") or event.get("content","")
            if delta: text += delta; on_delta and on_delta(delta)
        return self._response(events[-1] if events else {}, text)
    def search_query(self, query, model=None):
        if not query: raise ValidationError("query must not be empty")
        body={"query":query}; model and body.update(model=model)
        try: result=self._request("POST",self.search_endpoint,json=body).json(); return result
        except ValueError as exc: raise APIError("Invalid JSON response") from exc
    def quota(self):
        try: return self._request("GET",self.quota_endpoint).json()
        except ValueError as exc: raise APIError("Invalid JSON response") from exc
