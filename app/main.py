"""提供手册站点、BM25 检索和流式问答。"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.bm25_store import BM25Store
from app.indexer import INDEX_PATH, ROOT, IndexBuildError, build_index
from app.ollama_client import OllamaClient, OllamaError
from app.prompts import build_messages, context_budget

logger = logging.getLogger(__name__)
STATIC_DIR = ROOT / "app" / "static"
KB_DIR = ROOT / "kb"


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=4, ge=1, le=8)


class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=4, ge=1, le=8)
    retrieve_only: bool = False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        count = build_index()
    except IndexBuildError as exc:
        for item in exc.errors:
            logger.error(item)
        raise
    if not INDEX_PATH.is_file():
        raise FileNotFoundError(INDEX_PATH)
    app.state.store = BM25Store.load(INDEX_PATH)
    client = OllamaClient(
        os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
        os.environ.get("OLLAMA_MODEL", "openbmb/MiniCPM5-2B"),
    )
    await client.resolve_num_ctx()
    app.state.ollama = client
    logger.info("索引 %s 段，模型 %s，num_ctx %s", count, client.model, client.num_ctx)
    yield


app = FastAPI(title="衡石手册问答", lifespan=lifespan)


@app.post("/api/search")
def search(body: SearchRequest, request: Request) -> dict[str, list[dict[str, object]]]:
    query = _clean_query(body.query)
    hits = request.app.state.store.search(query, body.top_k)
    return {"results": [_public_source(hit) for hit in hits]}


@app.post("/api/ask")
async def ask(body: AskRequest, request: Request) -> StreamingResponse:
    query = _clean_query(body.query)
    store: BM25Store = request.app.state.store
    ollama: OllamaClient = request.app.state.ollama

    async def generate() -> AsyncIterator[str]:
        try:
            hits = store.search(query, body.top_k)
            if not hits:
                yield _sse("sources", {"sources": []})
                yield _sse("delta", {"text": "资料中没有相关内容。"})
                yield _sse("done", {})
                return
            _messages, used = build_messages(query, hits, context_budget(ollama.num_ctx))
            yield _sse("sources", {"sources": [_public_source(hit) for hit in used]})
            if body.retrieve_only:
                yield _sse("done", {})
                return
            try:
                async for piece in ollama.stream_chat(_messages):
                    yield _sse("delta", {"text": piece})
            except OllamaError as exc:
                logger.warning("调用 Ollama 失败：%s", exc)
                yield _sse("error", {"message": str(exc)})
            yield _sse("done", {})
        except Exception:
            logger.exception("问答失败")
            yield _sse("error", {"message": "问答服务内部错误。"})
            yield _sse("done", {})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/")
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/kb", StaticFiles(directory=KB_DIR, html=True), name="kb")


def _clean_query(query: str) -> str:
    text = query.strip()
    if not text:
        raise HTTPException(status_code=400, detail="问题不能为空")
    return text


def _public_source(hit: dict[str, object]) -> dict[str, object]:
    return {
        "doc_id": hit["doc_id"],
        "doc_title": hit["doc_title"],
        "section_id": hit["section_id"],
        "title": hit["title"],
        "breadcrumb": hit["breadcrumb"],
        "url": hit["url"],
        "excerpt": hit["excerpt"],
        "score": hit["score"],
    }


def _sse(event: str, payload: dict[str, object]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n"
