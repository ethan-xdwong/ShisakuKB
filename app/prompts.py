"""组装给本地小模型的问答提示。"""

from __future__ import annotations

SYSTEM_PROMPT = (
    "你是衡石 ERP 手册助手。"
    "只根据用户给出的资料回答，不要使用资料以外的信息。"
    "使用简体中文。"
    "资料不够时回答：资料不足，无法回答。"
    "引用资料时只使用方括号编号，例如 [1]。不要编造链接。"
)
DEFAULT_CONTEXT_CHARS = 3000


def context_budget(num_ctx: int) -> int:
    """按模型上下文估算可放入资料的字数，上限 3000 字。"""
    estimated = max(800, int(num_ctx * 0.7))
    return min(DEFAULT_CONTEXT_CHARS, estimated)


def build_messages(
    question: str,
    chunks: list[dict[str, object]],
    budget: int,
) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    """按字数预算截取段落，编号与返回的段落顺序一致。"""
    blocks: list[str] = []
    used: list[dict[str, object]] = []
    size = 0
    for chunk in chunks:
        block = f"[{len(used) + 1}] {chunk['title']}\n{chunk['breadcrumb']}\n{chunk['text']}"
        if used and size + len(block) > budget:
            break
        if not used and len(block) > budget:
            block = block[:budget]
        blocks.append(block)
        size += len(block)
        used.append(chunk)
    user = "资料：\n" + "\n\n".join(blocks) + "\n\n问题：" + question.strip()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
    return messages, used
