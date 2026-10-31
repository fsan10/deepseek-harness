from __future__ import annotations

import json
import urllib.error
import urllib.request


class ModelError(RuntimeError):
    pass


class DeepSeekClient:
    def __init__(self, cipher):
        self.cipher = cipher

    def _key(self, config: dict) -> str:
        if not config.get("api_key_ciphertext"):
            raise ModelError("模型配置尚未录入API Key")
        return self.cipher.decrypt(
            config["api_key_ciphertext"], config["api_key_nonce"],
            context=f"provider:{config['config_code']}",
        )

    def request_json(self, config: dict, path: str, payload: dict | None = None) -> dict:
        url = config["api_base_url"].rstrip("/") + path
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(url, data=body, method="POST" if body else "GET", headers={
            "Authorization": f"Bearer {self._key(config)}",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(request, timeout=int(config["request_timeout_seconds"])) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ModelError(f"DeepSeek请求失败（HTTP {exc.code}）") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ModelError("DeepSeek连接超时或不可用") from exc

    def test(self, config: dict) -> dict:
        payload = self.request_json(config, "/models")
        models = [item.get("id") for item in payload.get("data", []) if item.get("id")]
        return {"ok": config["model_name"] in models, "models": models}

    def completion(self, config: dict, messages: list[dict], tools: list[dict] | None = None) -> dict:
        payload = {
            "model": config["model_name"], "messages": messages,
            "temperature": float(config["temperature"]),
            "stream": False, "thinking": {"type": "enabled" if config["thinking_enabled"] else "disabled"},
        }
        if tools:
            payload["tools"] = tools
        return self.request_json(config, "/chat/completions", payload)
