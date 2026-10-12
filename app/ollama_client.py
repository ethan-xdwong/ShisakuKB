"""调用本机 Ollama 的对话接口。"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator

import httpx

logger = logging.getLogger(__name__)

DEFAULT_NUM_CTX = 4096
_CONTEXT_KEY = re.compile(r"context_length$")
_NUM_CTX = re.compile(r"num_ctx\s+(\d+)")


class OllamaError(Exception):
    """本地模型不可用或返回错误。"""


class OllamaClient:
    """保持 OpenAI 式 messages，实际请求 Ollama /api/chat。"""

    def __init__(self, host: str, model: str) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.num_ctx = DEFAULT_NUM_CTX

    async def resolve_num_ctx(self) -> None:
        """读取模型上下文长度；失败时保持 4096。"""
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.post(
                    f"{self.host}/api/show",
                    json={"name": self.model},
                )
                response.raise_for_status()
                found = _find_context_length(response.json())
        except httpx.HTTPError as exc:
            logger.warning("未能读取 Ollama 上下文长度，按 4096 处理：%s", exc)
            self.num_ctx = DEFAULT_NUM_CTX
            return
        if found is None:
            self.num_ctx = DEFAULT_NUM_CTX
            return
        self.num_ctx = min(max(found, 512), DEFAULT_NUM_CTX)

    async def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": 0.2, "num_ctx": self.num_ctx},
        }
        timeout = httpx.Timeout(10, read=180)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", f"{self.host}/api/chat", json=payload) as response:
                    if response.status_code == 404:
                        raise OllamaError(
                            f"模型 {self.model} 未就绪。请确认本机已拉取该模型。"
                        )
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode("utf-8", errors="replace")[:300]
                        raise OllamaError(f"Ollama 返回 {response.status_code}：{detail}")
                    async for line in response.aiter_lines():
                        piece = _read_stream_line(line)
                        if piece:
                            yield piece
        except OllamaError:
            raise
        except httpx.HTTPError as exc:
            raise OllamaError(f"无法连接 Ollama（{self.host}）。请确认本地服务已启动。") from exc


def _find_context_length(payload: object) -> int | None:
    if not isinstance(payload, dict):
        return None
    model_info = payload.get("model_info")
    if isinstance(model_info, dict):
        for key, value in model_info.items():
            if _CONTEXT_KEY.search(str(key)) and isinstance(value, (int, float)):
                return int(value)
    parameters = payload.get("parameters")
    if isinstance(parameters, str):
        matched = _NUM_CTX.search(parameters)
        if matched:
            return int(matched.group(1))
    return None


def _read_stream_line(line: str) -> str:
    text = line.strip()
    if not text:
        return ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OllamaError("Ollama 返回了无法解析的内容。") from exc
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if error:
        raise OllamaError(f"Ollama 错误：{error}")
    message = payload.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if not isinstance(content, str):
        return ""
    return content
