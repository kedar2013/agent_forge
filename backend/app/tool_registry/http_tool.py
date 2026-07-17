import os
import re
from typing import Any

import httpx

from app.tool_registry.base import ConfigDrivenTool

_PATH_PARAM_RE = re.compile(r"\{(\w+)\}")


class HttpTool(ConfigDrivenTool):
    """Declarative HTTP call tool.

    `config` shape:
        {
          "base_url": "https://api.example.com",
          "method": "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
          "path_template": "/weather/{city}",
          "auth": {"type": "none" | "api_key" | "bearer",
                    "header_name": "X-API-Key",   # api_key only
                    "secret_env": "WEATHER_API_KEY"},
          "timeout_seconds": 10
        }

    Secrets are never stored in `config` itself — only the name of an
    environment variable holding the secret (`secret_env`), so the JSONB
    row never contains a plaintext API key.
    """

    def __init__(
        self,
        *,
        name: str,
        description: str,
        input_schema: dict,
        config: dict,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(name=name, description=description, input_schema=input_schema)
        self._config = config
        self._transport = transport  # test seam; None means "real network"

    async def run_async(self, *, args: dict[str, Any], tool_context) -> Any:
        config = self._config
        path_template: str = config.get("path_template", "")
        path_params = set(_PATH_PARAM_RE.findall(path_template))

        path_values = {p: args[p] for p in path_params if p in args}
        path = path_template.format(**path_values)
        url = config["base_url"].rstrip("/") + path

        remaining = {k: v for k, v in args.items() if k not in path_params}
        method = config.get("method", "GET").upper()

        headers: dict[str, str] = {}
        auth = config.get("auth", {"type": "none"})
        if auth.get("type") == "api_key":
            secret = os.environ.get(auth.get("secret_env", ""), "")
            headers[auth.get("header_name", "X-API-Key")] = secret
        elif auth.get("type") == "bearer":
            secret = os.environ.get(auth.get("secret_env", ""), "")
            headers["Authorization"] = f"Bearer {secret}"

        timeout = config.get("timeout_seconds", 10)

        async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
            if method in ("GET", "DELETE"):
                response = await client.request(method, url, params=remaining, headers=headers)
            else:
                response = await client.request(method, url, json=remaining, headers=headers)

        try:
            body: Any = response.json()
        except ValueError:
            body = response.text

        return {"status_code": response.status_code, "body": body}
