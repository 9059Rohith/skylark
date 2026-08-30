"""Typed, resilient, read-only monday.com transport boundary."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from email.utils import parsedate_to_datetime
import json
import re
import time
from typing import Any, Protocol, runtime_checkable

import httpx

from app.monday.schemas import (
    BoardItemsResult,
    BoardSchema,
    ColumnSchema,
    MondayItem,
    SearchFilters,
)
from app.monday.tools import normalize_column_value


MONDAY_API_URL = "https://api.monday.com/v2"
MONDAY_API_VERSION = "2026-07"
ITEM_PAGE_LIMIT = 500
SCHEMA_TTL_SECONDS = 15 * 60
_BOARD_ID = re.compile(r"^[0-9]+$")

_SCHEMA_QUERY = """query BoardSchema($boardIds: [ID!]!) {
  boards(ids: $boardIds) {
    id
    name
    columns { id title type settings }
  }
}"""

_ITEM_FIELDS = """id
name
column_values { id type text value }"""

_FIRST_ITEMS_QUERY = f"""query BoardItems($boardIds: [ID!]!) {{
  boards(ids: $boardIds) {{
    id
    name
    items_page(limit: {ITEM_PAGE_LIMIT}) {{
      cursor
      items {{ {_ITEM_FIELDS} }}
    }}
  }}
}}"""

_NEXT_ITEMS_QUERY = f"""query NextBoardItems($cursor: String!) {{
  next_items_page(cursor: $cursor, limit: {ITEM_PAGE_LIMIT}) {{
    cursor
    items {{ {_ITEM_FIELDS} }}
  }}
}}"""


class MondayAPIError(RuntimeError):
    """A classified monday failure safe for routing and user-facing caveats."""

    def __init__(self, message: str, *, classification: str, retryable: bool) -> None:
        super().__init__(message)
        self.classification = classification
        self.retryable = retryable


@runtime_checkable
class MondayClient(Protocol):
    """Adapter shape supported by both official hosted MCP and GraphQL fallback."""

    async def get_board_schema(self, board_id: str) -> BoardSchema: ...

    async def get_board_items(self, board_id: str) -> BoardItemsResult: ...

    async def search_items(
        self, board_id: str, filters: SearchFilters | Mapping[str, Any]
    ) -> BoardItemsResult: ...


class _AsyncHTTPClient(Protocol):
    async def post(self, url: str, **kwargs: Any) -> Any: ...


class GraphQLMondayClient:
    """Production GraphQL fallback implementing the hosted-MCP-compatible boundary."""

    def __init__(
        self,
        token: str,
        *,
        http_client: _AsyncHTTPClient | None = None,
        max_attempts: int = 3,
        max_retry_delay: float = 30.0,
        schema_ttl: float = SCHEMA_TTL_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not token.strip():
            raise ValueError("token must not be empty")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._headers = {
            "Authorization": token,
            "Content-Type": "application/json",
            "API-Version": MONDAY_API_VERSION,
        }
        self._http = http_client or httpx.AsyncClient(timeout=httpx.Timeout(20.0))
        self._max_attempts = max_attempts
        self._max_retry_delay = max(0.0, max_retry_delay)
        self._schema_ttl = max(0.0, schema_ttl)
        self._sleep = sleep
        self._monotonic = monotonic
        self._schema_cache: dict[str, tuple[float, BoardSchema]] = {}
        self._schema_locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def _validate_board_id(board_id: str) -> str:
        normalized = str(board_id).strip()
        if not _BOARD_ID.fullmatch(normalized):
            raise ValueError("board_id must contain digits only")
        return normalized

    @staticmethod
    def _messages(payload: Mapping[str, Any]) -> tuple[str, ...]:
        errors = payload.get("errors")
        if not isinstance(errors, list):
            return ()
        return tuple(
            str(error.get("message", "Unknown monday GraphQL error"))
            for error in errors
            if isinstance(error, Mapping)
        )

    @staticmethod
    def _retry_seconds(payload: Mapping[str, Any]) -> float | None:
        errors = payload.get("errors")
        if not isinstance(errors, list):
            return None
        for error in errors:
            if not isinstance(error, Mapping):
                continue
            extensions = error.get("extensions")
            if isinstance(extensions, Mapping) and "retry_in_seconds" in extensions:
                try:
                    return max(0.0, float(extensions["retry_in_seconds"]))
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _classify_graphql(payload: Mapping[str, Any]) -> str:
        errors = payload.get("errors")
        combined = " ".join(GraphQLMondayClient._messages(payload)).casefold()
        codes = " "
        if isinstance(errors, list):
            codes = " ".join(
                str(error.get("extensions", {}).get("code", ""))
                for error in errors
                if isinstance(error, Mapping)
                and isinstance(error.get("extensions", {}), Mapping)
            ).casefold()
        if "unauthorized" in combined or "unauthorized" in codes or "authentication" in combined:
            return "authentication"
        if "permission" in combined or "forbidden" in combined:
            return "permission"
        if "not found" in combined:
            return "not_found"
        return "graphql"

    def _header_retry_seconds(self, value: object) -> float | None:
        if value is None:
            return None
        try:
            return max(0.0, float(str(value)))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(str(value)).timestamp()
                return max(0.0, retry_at - time.time())
            except (TypeError, ValueError, OverflowError):
                return None

    async def _execute(self, query: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
        last_error: MondayAPIError | None = None
        for attempt in range(self._max_attempts):
            try:
                response = await self._http.post(
                    MONDAY_API_URL,
                    headers=self._headers,
                    json={"query": query, "variables": dict(variables)},
                )
            except (httpx.TimeoutException, TimeoutError) as exc:
                last_error = MondayAPIError(str(exc), classification="timeout", retryable=True)
                retry_delay = min(2**attempt, self._max_retry_delay)
            except httpx.HTTPError as exc:
                last_error = MondayAPIError(str(exc), classification="transport", retryable=True)
                retry_delay = min(2**attempt, self._max_retry_delay)
            else:
                status = int(response.status_code)
                if status in {401, 403}:
                    classification = "authentication" if status == 401 else "permission"
                    raise MondayAPIError(
                        f"monday API returned HTTP {status}",
                        classification=classification,
                        retryable=False,
                    )
                if status == 429 or status >= 500:
                    classification = "rate_limit" if status == 429 else "server"
                    last_error = MondayAPIError(
                        f"monday API returned HTTP {status}",
                        classification=classification,
                        retryable=True,
                    )
                    header_delay = self._header_retry_seconds(response.headers.get("Retry-After"))
                    retry_delay = min(
                        header_delay if header_delay is not None else 2**attempt,
                        self._max_retry_delay,
                    )
                elif status < 200 or status >= 300:
                    raise MondayAPIError(
                        f"monday API returned HTTP {status}",
                        classification="http",
                        retryable=False,
                    )
                else:
                    try:
                        payload = response.json()
                    except (TypeError, ValueError, json.JSONDecodeError) as exc:
                        raise MondayAPIError(
                            "monday API returned malformed JSON",
                            classification="malformed_response",
                            retryable=False,
                        ) from exc
                    if not isinstance(payload, Mapping):
                        raise MondayAPIError(
                            "monday API returned a non-object response",
                            classification="malformed_response",
                            retryable=False,
                        )
                    if payload.get("data") is not None:
                        return payload
                    retry_hint = self._retry_seconds(payload)
                    if retry_hint is None:
                        raise MondayAPIError(
                            "; ".join(self._messages(payload)) or "monday GraphQL request failed",
                            classification=self._classify_graphql(payload),
                            retryable=False,
                        )
                    last_error = MondayAPIError(
                        "; ".join(self._messages(payload)),
                        classification="rate_limit",
                        retryable=True,
                    )
                    retry_delay = min(retry_hint, self._max_retry_delay)

            if attempt + 1 < self._max_attempts:
                await self._sleep(retry_delay)

        if last_error is not None:
            raise last_error
        raise MondayAPIError(
            "monday request failed", classification="transport", retryable=False
        )

    async def get_board_schema(self, board_id: str) -> BoardSchema:
        board_id = self._validate_board_id(board_id)
        cached = self._schema_cache.get(board_id)
        now = self._monotonic()
        if cached is not None and cached[0] > now:
            return cached[1]

        lock = self._schema_locks.setdefault(board_id, asyncio.Lock())
        async with lock:
            cached = self._schema_cache.get(board_id)
            now = self._monotonic()
            if cached is not None and cached[0] > now:
                return cached[1]
            payload = await self._execute(_SCHEMA_QUERY, {"boardIds": [board_id]})
            data = payload.get("data")
            boards = data.get("boards") if isinstance(data, Mapping) else None
            if not isinstance(boards, list) or not boards:
                raise MondayAPIError(
                    f"board {board_id} was not found",
                    classification="not_found",
                    retryable=False,
                )
            raw_board = boards[0]
            raw_columns = raw_board.get("columns", [])
            columns: list[ColumnSchema] = []
            for raw_column in raw_columns:
                raw_settings = raw_column.get("settings")
                if isinstance(raw_settings, str):
                    try:
                        settings = json.loads(raw_settings) if raw_settings else {}
                    except json.JSONDecodeError:
                        settings = {}
                elif isinstance(raw_settings, Mapping):
                    settings = dict(raw_settings)
                else:
                    settings = {}
                columns.append(
                    ColumnSchema(
                        id=str(raw_column.get("id", "")),
                        title=str(raw_column.get("title", "")),
                        type=str(raw_column.get("type", "")),
                        settings=settings,
                    )
                )
            schema = BoardSchema(
                board_id=str(raw_board.get("id", board_id)),
                name=str(raw_board.get("name", "")),
                columns=tuple(columns),
                caveats=self._messages(payload),
            )
            self._schema_cache[board_id] = (now + self._schema_ttl, schema)
            return schema

    @staticmethod
    def _item(raw_item: Mapping[str, Any]) -> MondayItem:
        values: dict[str, Any] = {}
        column_values = raw_item.get("column_values", [])
        if isinstance(column_values, list):
            for raw_value in column_values:
                if isinstance(raw_value, dict):
                    column_id = str(raw_value.get("id", ""))
                    if column_id:
                        values[column_id] = normalize_column_value(raw_value)
        return MondayItem(
            id=str(raw_item.get("id", "")),
            name=str(raw_item.get("name", "")),
            values=values,
        )

    async def get_board_items(self, board_id: str) -> BoardItemsResult:
        board_id = self._validate_board_id(board_id)
        payload = await self._execute(
            _FIRST_ITEMS_QUERY,
            {"boardIds": [board_id]},
        )
        data = payload.get("data")
        boards = data.get("boards") if isinstance(data, Mapping) else None
        if not isinstance(boards, list) or not boards:
            raise MondayAPIError(
                f"board {board_id} was not found",
                classification="not_found",
                retryable=False,
            )
        page = boards[0].get("items_page")
        if not isinstance(page, Mapping):
            raise MondayAPIError(
                "monday items page was malformed",
                classification="malformed_response",
                retryable=False,
            )

        caveats = list(self._messages(payload))
        raw_items = list(page.get("items") or [])
        cursor = page.get("cursor")
        while cursor:
            next_payload = await self._execute(
                _NEXT_ITEMS_QUERY,
                {"cursor": str(cursor)},
            )
            caveats.extend(self._messages(next_payload))
            next_data = next_payload.get("data")
            next_page = (
                next_data.get("next_items_page") if isinstance(next_data, Mapping) else None
            )
            if not isinstance(next_page, Mapping):
                raise MondayAPIError(
                    "monday next items page was malformed",
                    classification="malformed_response",
                    retryable=False,
                )
            raw_items.extend(next_page.get("items") or [])
            cursor = next_page.get("cursor")

        return BoardItemsResult(
            board_id=board_id,
            items=tuple(
                self._item(raw_item)
                for raw_item in raw_items
                if isinstance(raw_item, Mapping)
            ),
            caveats=tuple(caveats),
            partial=bool(caveats),
        )

    @staticmethod
    def _matches(actual: object, expected: object) -> bool:
        if isinstance(actual, list):
            return any(GraphQLMondayClient._matches(value, expected) for value in actual)
        if isinstance(actual, str) and isinstance(expected, str):
            return actual.strip().casefold() == expected.strip().casefold()
        return actual == expected

    async def search_items(
        self, board_id: str, filters: SearchFilters | Mapping[str, Any]
    ) -> BoardItemsResult:
        filters = filters if isinstance(filters, SearchFilters) else SearchFilters.model_validate(filters)
        result = await self.get_board_items(board_id)
        name_query = (filters.name_contains or "").strip().casefold()
        items = tuple(
            item
            for item in result.items
            if (not name_query or name_query in item.name.casefold())
            and all(
                self._matches(item.values.get(column_id), expected)
                for column_id, expected in filters.column_values.items()
            )
        )
        return result.model_copy(update={"items": items})
