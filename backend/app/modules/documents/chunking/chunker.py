"""Paragraph-boundary-aware chunking with configurable size and overlap.

A chunk never splits a paragraph unless the paragraph itself exceeds
chunk_size_tokens, in which case it is split at sentence boundaries; if even
a single sentence exceeds chunk_size_tokens (pathological OCR output with no
punctuation), it is hard-split at the token level as a last resort - so
chunking is guaranteed to terminate and never produces a chunk larger than
roughly chunk_size_tokens + chunk_overlap_tokens.

Overlap is carried at paragraph granularity: the trailing paragraphs of one
chunk (up to chunk_overlap_tokens worth) are repeated at the start of the
next chunk, so a semantic unit that would otherwise fall on a chunk boundary
stays available to whichever chunk a retriever picks.
"""

import re
from dataclasses import dataclass
from typing import Any

import tiktoken

from app.modules.documents.extraction.types import ExtractedPage

_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

_encoding = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_encoding.encode(text))


@dataclass(frozen=True)
class _Paragraph:
    page_number: int
    text: str
    token_count: int


@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    page_number: int  # the page this chunk starts on
    text: str
    token_count: int
    metadata: dict[str, Any]


class DocumentChunker:
    def __init__(self, *, chunk_size_tokens: int, chunk_overlap_tokens: int) -> None:
        if chunk_size_tokens <= 0:
            raise ValueError("chunk_size_tokens must be positive")
        if chunk_overlap_tokens < 0 or chunk_overlap_tokens >= chunk_size_tokens:
            raise ValueError(
                "chunk_overlap_tokens must be non-negative and smaller than chunk_size_tokens"
            )
        self._chunk_size_tokens = chunk_size_tokens
        self._chunk_overlap_tokens = chunk_overlap_tokens

    def chunk(self, pages: list[ExtractedPage]) -> list[Chunk]:
        paragraphs = self._split_into_paragraphs(pages)
        if not paragraphs:
            return []

        chunks: list[Chunk] = []
        current: list[_Paragraph] = []
        current_tokens = 0
        chunk_index = 0

        for paragraph in paragraphs:
            if current and current_tokens + paragraph.token_count > self._chunk_size_tokens:
                chunks.append(self._build_chunk(chunk_index, current))
                chunk_index += 1
                current, current_tokens = self._carry_overlap(current)
            current.append(paragraph)
            current_tokens += paragraph.token_count

        if current:
            chunks.append(self._build_chunk(chunk_index, current))

        return chunks

    def _build_chunk(self, chunk_index: int, paragraphs: list[_Paragraph]) -> Chunk:
        text = "\n\n".join(p.text for p in paragraphs)
        source_pages = sorted({p.page_number for p in paragraphs})
        metadata: dict[str, Any] = {"source_pages": source_pages} if len(source_pages) > 1 else {}
        return Chunk(
            chunk_index=chunk_index,
            page_number=paragraphs[0].page_number,
            text=text,
            token_count=count_tokens(text),
            metadata=metadata,
        )

    def _carry_overlap(self, previous: list[_Paragraph]) -> tuple[list[_Paragraph], int]:
        carried: list[_Paragraph] = []
        carried_tokens = 0
        for paragraph in reversed(previous):
            if carried_tokens + paragraph.token_count > self._chunk_overlap_tokens:
                break
            carried.insert(0, paragraph)
            carried_tokens += paragraph.token_count
        return carried, carried_tokens

    def _split_into_paragraphs(self, pages: list[ExtractedPage]) -> list[_Paragraph]:
        paragraphs: list[_Paragraph] = []
        for page in pages:
            if not page.text.strip():
                continue
            for raw in _PARAGRAPH_SPLIT_RE.split(page.text):
                collapsed = " ".join(raw.split())
                if collapsed:
                    paragraphs.extend(self._split_oversized(page.page_number, collapsed))
        return paragraphs

    def _split_oversized(self, page_number: int, text: str) -> list[_Paragraph]:
        token_count = count_tokens(text)
        if token_count <= self._chunk_size_tokens:
            return [_Paragraph(page_number=page_number, text=text, token_count=token_count)]

        sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
        if len(sentences) > 1:
            result: list[_Paragraph] = []
            for sentence in sentences:
                result.extend(self._split_oversized(page_number, sentence))
            return result

        # A single sentence still exceeds the chunk size (e.g. garbled OCR
        # with no punctuation) - hard-split at the token level so chunking
        # is guaranteed to terminate.
        tokens = _encoding.encode(text)
        return [
            _Paragraph(
                page_number=page_number,
                text=_encoding.decode(tokens[i : i + self._chunk_size_tokens]),
                token_count=len(tokens[i : i + self._chunk_size_tokens]),
            )
            for i in range(0, len(tokens), self._chunk_size_tokens)
        ]
