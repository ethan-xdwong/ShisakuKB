"""中文分词与 BM25 检索。"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import jieba
from rank_bm25 import BM25Okapi

from app.indexer import INDEX_PATH

logger = logging.getLogger(__name__)

USERDICT = Path(__file__).resolve().parent / "userdict.txt"
STOPWORDS = frozenset(
    {
        "的",
        "了",
        "吗",
        "呢",
        "吧",
        "啊",
        "呀",
        "哇",
        "着",
        "过",
        "与",
        "和",
        "或",
        "及",
        "以及",
        "在",
        "是",
        "为",
        "以",
        "把",
        "被",
        "对",
        "从",
        "到",
        "等",
        "这",
        "那",
        "就",
        "也",
        "还",
        "很",
        "更",
        "最",
        "一个",
        "一种",
    }
)
PUNCT_PATTERN = re.compile(r"^[\W_]+$", re.UNICODE)
SPACE_PATTERN = re.compile(r"\s+")
BM25_K1 = 1.5
BM25_B = 0.75
EXCERPT_LIMIT = 140

_ready = False


def tokenize(text: str) -> list[str]:
    """按手册用户词典切分问句或段落。"""
    _ensure_tokenizer()
    tokens: list[str] = []
    for word in jieba.lcut(text):
        token = word.strip()
        if not token or token in STOPWORDS or PUNCT_PATTERN.fullmatch(token):
            continue
        tokens.append(token)
    return tokens


class BM25Store:
    """已建索引的段落检索。"""

    def __init__(self, chunks: list[dict[str, str]]) -> None:
        self.chunks = chunks
        corpus = [tokenize(chunk["index_text"]) for chunk in chunks]
        empty = [chunk["section_id"] for chunk, tokens in zip(chunks, corpus) if not tokens]
        if empty:
            raise ValueError("以下段落无法分词：" + "、".join(empty))
        self._bm25 = BM25Okapi(corpus, k1=BM25_K1, b=BM25_B)

    @classmethod
    def load(cls, path: Path = INDEX_PATH) -> "BM25Store":
        payload = json.loads(path.read_text(encoding="utf-8"))
        chunks = payload.get("chunks")
        if not isinstance(chunks, list) or not chunks:
            raise ValueError(f"索引为空：{path}")
        return cls(chunks)

    def search(self, query: str, top_k: int) -> list[dict[str, object]]:
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda item: float(item[1]), reverse=True)
        hits: list[dict[str, object]] = []
        for index, score in ranked:
            value = float(score)
            if value <= 0:
                continue
            if len(hits) >= top_k:
                break
            chunk = self.chunks[index]
            hits.append(
                {
                    "doc_id": chunk["doc_id"],
                    "doc_title": chunk["doc_title"],
                    "section_id": chunk["section_id"],
                    "title": chunk["title"],
                    "breadcrumb": chunk["breadcrumb"],
                    "text": chunk["text"],
                    "url": chunk["url"],
                    "excerpt": _excerpt(chunk["text"]),
                    "score": round(value, 4),
                }
            )
        return hits


def _excerpt(text: str) -> str:
    flat = SPACE_PATTERN.sub(" ", text).strip()
    if len(flat) <= EXCERPT_LIMIT:
        return flat
    return flat[:EXCERPT_LIMIT] + "…"


def _ensure_tokenizer() -> None:
    global _ready
    if _ready:
        return
    jieba.setLogLevel(logging.ERROR)
    jieba.load_userdict(str(USERDICT))
    _ready = True
