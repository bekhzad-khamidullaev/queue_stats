from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import urlencode

from django.http import HttpRequest


def to_int(value: Any, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def api_pagination_params(payload: Dict[str, Any], default_page_size: int = 100, max_page_size: int = 1000) -> tuple[int, int, int]:
    page = to_int(payload.get("page"), default=1, minimum=1)
    page_size = to_int(payload.get("page_size"), default=default_page_size, minimum=1, maximum=max_page_size)
    offset = (page - 1) * page_size
    return page, page_size, offset


def api_pagination_meta(total: int, page: int, page_size: int) -> Dict[str, int | bool]:
    total_pages = max(1, (total + page_size - 1) // page_size) if page_size else 1
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
    }


def ui_paginated_rows(request: HttpRequest, rows: List[Dict[str, Any]], default_page_size: int = 100, max_page_size: int = 500) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    page = to_int(request.GET.get("page"), default=1, minimum=1)
    page_size = to_int(request.GET.get("page_size"), default=default_page_size, minimum=1, maximum=max_page_size)

    total = len(rows)
    total_pages = max(1, (total + page_size - 1) // page_size) if page_size else 1
    if page > total_pages:
        page = total_pages
    offset = (page - 1) * page_size
    page_rows = rows[offset:offset + page_size]

    start_index = offset + 1 if total else 0
    end_index = min(offset + page_size, total)
    query_pairs = [(key, value) for key, value in request.GET.lists() if key != "page"]
    base_qs = urlencode(query_pairs, doseq=True)

    def _link(target_page: int) -> str:
        if base_qs:
            return f"?{base_qs}&page={target_page}"
        return f"?page={target_page}"

    return page_rows, {
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "start_index": start_index,
        "end_index": end_index,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "prev_page_url": _link(page - 1) if page > 1 else "",
        "next_page_url": _link(page + 1) if page < total_pages else "",
    }


def ui_pagination_params(request: HttpRequest, default_page_size: int = 100, max_page_size: int = 500) -> tuple[int, int]:
    page = to_int(request.GET.get("page"), default=1, minimum=1)
    # Get page_size from GET or cookie, fallback to default
    page_size_str = request.GET.get("page_size") or request.COOKIES.get("filters_page_size", str(default_page_size))
    page_size = to_int(page_size_str, default=default_page_size, minimum=1, maximum=max_page_size)
    return page, page_size


def ui_pagination_meta(request: HttpRequest, page: int, page_size: int, total: int) -> Dict[str, Any]:
    total_pages = max(1, (total + page_size - 1) // page_size) if page_size else 1
    if page > total_pages:
        page = total_pages
    offset = (page - 1) * page_size
    start_index = offset + 1 if total else 0
    end_index = min(offset + page_size, total)
    query_pairs = [(key, value) for key, value in request.GET.lists() if key != "page"]
    base_qs = urlencode(query_pairs, doseq=True)

    def _link(target_page: int) -> str:
        if base_qs:
            return f"?{base_qs}&page={target_page}"
        return f"?page={target_page}"

    return {
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "start_index": start_index,
        "end_index": end_index,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "prev_page_url": _link(page - 1) if page > 1 else "",
        "next_page_url": _link(page + 1) if page < total_pages else "",
    }
