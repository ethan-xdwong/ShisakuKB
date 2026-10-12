"""从 HTML 手册抽取小节，并做结构检查。"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from bs4.element import Tag

ROOT = Path(__file__).resolve().parents[1]
KB_DIR = ROOT / "kb"
INDEX_PATH = ROOT / "data" / "index.json"
GLOSSARY_DOC_ID = "glossary"
MANUAL_NAME = "衡石手册"
ANCHOR_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WHITESPACE_PATTERN = re.compile(r"\s+")

logger = logging.getLogger(__name__)


class IndexBuildError(Exception):
    """手册结构不符合检索约定。"""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


def build_index() -> int:
    """读取 kb 下的 HTML，检查结构并写出 data/index.json。"""
    files = sorted(path for path in KB_DIR.rglob("*.html") if path.is_file())
    if not files:
        raise IndexBuildError(["kb 目录下没有 HTML 页面"])

    errors: list[str] = []
    chunks: list[dict[str, str]] = []
    seen_doc_ids: dict[str, str] = {}
    seen_section_ids: dict[str, str] = {}
    seen_titles: dict[str, str] = {}
    glossary_terms: list[tuple[str, str]] = []
    body_parts: list[str] = []

    for path in files:
        page_chunks, page_terms, page_body = _parse_page(
            path,
            errors,
            seen_doc_ids,
            seen_section_ids,
            seen_titles,
        )
        chunks.extend(page_chunks)
        glossary_terms.extend(page_terms)
        if page_body:
            body_parts.append(page_body)

    body_text = "\n".join(body_parts)
    if not glossary_terms:
        errors.append("术语表缺少 data-term 规范词")
    seen_terms: set[str] = set()
    for term, location in glossary_terms:
        if term in seen_terms:
            errors.append(f"{location}: 规范词重复：{term}")
            continue
        seen_terms.add(term)
        if term not in body_text:
            errors.append(f"{location}: 规范词未在正文出现：{term}")

    if errors:
        raise IndexBuildError(errors)

    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "chunks": chunks,
    }
    INDEX_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("已写入 %s，共 %s 个段落", INDEX_PATH, len(chunks))
    return len(chunks)


def _parse_page(
    path: Path,
    errors: list[str],
    seen_doc_ids: dict[str, str],
    seen_section_ids: dict[str, str],
    seen_titles: dict[str, str],
) -> tuple[list[dict[str, str]], list[tuple[str, str]], str]:
    rel = path.relative_to(KB_DIR).as_posix()
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    article = _require_article(soup, rel, errors)
    if article is None:
        return [], [], ""

    doc_id = _clean(article.get("data-doc-id", ""))
    doc_title = _clean(article.get("data-doc-title", ""))
    h1 = article.find("h1")
    h1_text = _clean(h1.get_text(" ", strip=True) if isinstance(h1, Tag) else "")
    header = article.find("header", recursive=False)
    breadcrumb = header.find(class_="breadcrumb") if isinstance(header, Tag) else None
    breadcrumb_text = _clean(breadcrumb.get_text(" ", strip=True) if isinstance(breadcrumb, Tag) else "")
    _check_page_identity(
        soup,
        rel,
        errors,
        doc_id,
        doc_title,
        h1_text,
        breadcrumb_text,
        seen_doc_ids,
    )

    sections = article.find_all("section", recursive=False)
    if not sections:
        errors.append(f"{rel}: 文章中没有小节")
    _check_json_ld(soup, rel, errors, doc_title, sections)

    chunks: list[dict[str, str]] = []
    terms: list[tuple[str, str]] = []
    body_parts: list[str] = []
    for section in sections:
        if not isinstance(section, Tag):
            continue
        chunk, term = _parse_section(
            section,
            rel,
            errors,
            doc_id,
            doc_title,
            breadcrumb_text,
            seen_section_ids,
            seen_titles,
        )
        if chunk is None:
            continue
        chunks.append(chunk)
        if doc_id == GLOSSARY_DOC_ID:
            if term is None:
                errors.append(f"{rel}: 术语小节缺少规范词：{chunk['section_id']}")
            else:
                terms.append((term, f"{rel}#{chunk['section_id']}"))
        else:
            body_parts.append(chunk["text"])
            if term is not None:
                errors.append(f"{rel}: 规范词只能写在术语表：{term}")

    return chunks, terms, "\n".join(body_parts)


def _require_article(soup: BeautifulSoup, rel: str, errors: list[str]) -> Tag | None:
    articles = soup.find_all("article")
    if len(articles) != 1:
        errors.append(f"{rel}: 需要且仅需要一篇 article，当前 {len(articles)} 篇")
        return None
    article = articles[0]
    if not isinstance(article, Tag):
        errors.append(f"{rel}: article 结构无效")
        return None
    return article


def _check_page_identity(
    soup: BeautifulSoup,
    rel: str,
    errors: list[str],
    doc_id: str,
    doc_title: str,
    h1_text: str,
    breadcrumb_text: str,
    seen_doc_ids: dict[str, str],
) -> None:
    if ANCHOR_PATTERN.fullmatch(doc_id) is None:
        errors.append(f"{rel}: data-doc-id 无效：{doc_id}")
    elif doc_id in seen_doc_ids:
        errors.append(f"{rel}: 文档 id 与 {seen_doc_ids[doc_id]} 重复：{doc_id}")
    else:
        seen_doc_ids[doc_id] = rel

    if not doc_title:
        errors.append(f"{rel}: 缺少 data-doc-title")
    if not h1_text:
        errors.append(f"{rel}: 缺少 h1")
    elif doc_title and doc_title != h1_text:
        errors.append(f"{rel}: 标题与 h1 不一致：{doc_title} / {h1_text}")
    if h1_text and breadcrumb_text != f"{MANUAL_NAME} / {h1_text}":
        errors.append(f"{rel}: 面包屑应为「{MANUAL_NAME} / {h1_text}」")

    title_tag = soup.find("title")
    title_text = _clean(title_tag.get_text(" ", strip=True) if isinstance(title_tag, Tag) else "")
    if h1_text and title_text != f"{h1_text} — {MANUAL_NAME}":
        errors.append(f"{rel}: title 与 h1 不一致")

    descriptions = soup.select("meta[name='description']")
    if len(descriptions) != 1:
        errors.append(f"{rel}: 需要一条 description")


def _check_json_ld(
    soup: BeautifulSoup,
    rel: str,
    errors: list[str],
    doc_title: str,
    sections: list[Tag],
) -> None:
    scripts = soup.select("script[type='application/ld+json']")
    if len(scripts) != 1:
        errors.append(f"{rel}: 需要一条 TechArticle JSON-LD")
        return
    description = ""
    meta = soup.select_one("meta[name='description']")
    if isinstance(meta, Tag):
        description = _clean(str(meta.get("content", "")))
    try:
        payload = json.loads(scripts[0].get_text())
    except json.JSONDecodeError:
        errors.append(f"{rel}: JSON-LD 无法解析")
        return
    if payload.get("@type") != "TechArticle":
        errors.append(f"{rel}: JSON-LD 类型不是 TechArticle")
    if payload.get("headline") != doc_title:
        errors.append(f"{rel}: JSON-LD headline 与页面标题不一致")
    if description and payload.get("description") != description:
        errors.append(f"{rel}: JSON-LD description 与 meta description 不一致")
    parts = payload.get("hasPart")
    if not isinstance(parts, list) or len(parts) != len(sections):
        errors.append(f"{rel}: JSON-LD hasPart 数量与小节不一致")
        return
    for part, section in zip(parts, sections):
        section_id = _clean(str(section.get("id", "")))
        h2 = section.find("h2", recursive=False)
        h2_text = _clean(h2.get_text(" ", strip=True) if isinstance(h2, Tag) else "")
        if not isinstance(part, dict):
            errors.append(f"{rel}: JSON-LD hasPart 项无效")
            continue
        if part.get("name") != h2_text or part.get("cssSelector") != f"#{section_id}":
            errors.append(f"{rel}: JSON-LD 与小节不一致：{h2_text}")


def _parse_section(
    section: Tag,
    rel: str,
    errors: list[str],
    doc_id: str,
    doc_title: str,
    breadcrumb_text: str,
    seen_section_ids: dict[str, str],
    seen_titles: dict[str, str],
) -> tuple[dict[str, str] | None, str | None]:
    if section.find("section") is not None:
        errors.append(f"{rel}: 小节不能嵌套")
        return None, None

    section_id = _clean(str(section.get("id", "")))
    data_id = _clean(str(section.get("data-section-id", "")))
    location = f"{rel}#{section_id or '未命名'}"
    if ANCHOR_PATTERN.fullmatch(section_id) is None:
        errors.append(f"{location}: 缺少有效 id")
        return None, None
    if data_id != section_id:
        errors.append(f"{location}: data-section-id 与 id 不一致")
    if section_id in seen_section_ids:
        errors.append(f"{location}: 锚点与 {seen_section_ids[section_id]} 重复")
    else:
        seen_section_ids[section_id] = location

    headings = section.find_all("h2", recursive=False)
    if len(headings) != 1:
        errors.append(f"{location}: 小节需要且仅需要一个 h2")
        return None, None
    title = _clean(headings[0].get_text(" ", strip=True))
    if not title:
        errors.append(f"{location}: 小节标题为空")
        return None, None
    if title in seen_titles:
        errors.append(f"{location}: 标题与 {seen_titles[title]} 重复：{title}")
    else:
        seen_titles[title] = location

    first_p = _first_paragraph(headings[0])
    first_text = _clean(first_p.get_text(" ", strip=True) if isinstance(first_p, Tag) else "")
    if len(first_text) < 12:
        errors.append(f"{location}: 缺少首段")
    _check_diagram(section, location, errors)

    text = _section_text(section)
    if not text:
        errors.append(f"{location}: 小节正文为空")
        return None, None

    term = _read_term(section, location, errors)
    crumb = f"{breadcrumb_text} / {title}" if breadcrumb_text else title
    url = f"/kb/{rel}#{section_id}"
    chunk = {
        "doc_id": doc_id,
        "doc_title": doc_title,
        "section_id": section_id,
        "title": title,
        "breadcrumb": crumb,
        "text": text,
        "index_text": f"{crumb}\n{text}",
        "url": url,
    }
    return chunk, term


def _read_term(section: Tag, location: str, errors: list[str]) -> str | None:
    terms = section.find_all("dfn")
    if not terms:
        return None
    if len(terms) != 1:
        errors.append(f"{location}: 一节只能定义一个规范词")
        return None
    data_term = _clean(str(terms[0].get("data-term", "")))
    visible = _clean(terms[0].get_text(" ", strip=True))
    if not data_term or data_term != visible:
        errors.append(f"{location}: data-term 必须与可见词一致")
        return None
    return data_term


def _first_paragraph(heading: Tag) -> Tag | None:
    for node in heading.next_siblings:
        if isinstance(node, Tag):
            if node.name == "p":
                return node
            return None
        if str(node).strip():
            return None
    return None


def _check_diagram(section: Tag, location: str, errors: list[str]) -> None:
    if not section.select("pre.mermaid"):
        return
    step_count = 0
    for ordered in section.find_all("ol"):
        step_count += len(ordered.find_all("li", recursive=False))
    if step_count < 2:
        errors.append(f"{location}: 含流程图的小节至少要有两个步骤")


def _section_text(section: Tag) -> str:
    clone = BeautifulSoup(str(section), "html.parser")
    root = clone.find("section") or clone
    for node in root.select("pre.mermaid"):
        node.decompose()
    lines: list[str] = []
    for line in root.get_text("\n", strip=True).splitlines():
        cleaned = _clean(line)
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


def _clean(text: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", text).strip()


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        count = build_index()
    except IndexBuildError as exc:
        for item in exc.errors:
            print(item, file=sys.stderr)
        sys.exit(1)
    print(f"已写入 {INDEX_PATH}，共 {count} 个段落")


if __name__ == "__main__":
    main()
