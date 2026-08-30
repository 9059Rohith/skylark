import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from app.monday.client import GraphQLMondayClient, MondayAPIError
from app.monday.schemas import ColumnSchema, SearchFilters
from app.monday.tools import normalize_column_value


class FakeResponse:
    def __init__(
        self,
        payload: Mapping[str, Any],
        *,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = dict(headers or {})

    def json(self) -> Mapping[str, Any]:
        return self._payload


class FakeHTTPClient:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    async def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append({"url": url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def column(column_id: str, title: str, column_type: str, settings: dict[str, Any] | None = None) -> ColumnSchema:
    return ColumnSchema(id=column_id, title=title, type=column_type, settings=settings or {})


@pytest.mark.parametrize(
    ("raw", "schema", "expected"),
    [
        ({"id": "stage", "type": "status", "text": "Won", "value": '{"index": 1}'}, column("stage", "Stage", "status", {"labels": {"1": "Won"}}), "Won"),
        ({"id": "date", "type": "date", "text": "", "value": '{"date": "2026-08-30", "time": "09:15:00"}'}, column("date", "Close Date", "date"), "2026-08-30"),
        ({"id": "amount", "type": "numbers", "text": "1,250", "value": "1250"}, column("amount", "Amount", "numbers"), "1,250"),
        ({"id": "notes", "type": "text", "text": "  signed  ", "value": '"signed"'}, column("notes", "Notes", "text"), "signed"),
        ({"id": "tags", "type": "dropdown", "text": "Energy, Priority", "value": '{"ids": [2, 7]}'}, column("tags", "Tags", "dropdown"), ["Energy", "Priority"]),
        ({"id": "mirror", "type": "mirror", "text": "WO-4, WO-9", "value": '{"display_value": "WO-4, WO-9"}'}, column("mirror", "Work Orders", "mirror"), ["WO-4", "WO-9"]),
    ],
)
def test_normalize_column_value_unboxes_monday_types_before_cleaning(
    raw: dict[str, Any], schema: ColumnSchema, expected: object
) -> None:
    """Returning monday's JSON envelopes would leak transport complexity into metrics."""
    assert normalize_column_value(raw, schema) == expected


def test_board_schema_uses_stable_version_settings_field_and_concurrent_ttl_cache() -> None:
    """Deprecated schema fields or duplicate concurrent reads make discovery brittle."""
    fake = FakeHTTPClient(
        [
            FakeResponse(
                {
                    "data": {
                        "boards": [
                            {
                                "id": "42",
                                "name": "Deals",
                                "columns": [
                                    {
                                        "id": "stage",
                                        "title": "Stage",
                                        "type": "status",
                                        "settings": '{"labels":{"1":"Won"}}',
                                    }
                                ],
                            }
                        ]
                    }
                }
            )
        ]
    )
    client = GraphQLMondayClient(token="secret", http_client=fake)

    async def read_concurrently() -> tuple[object, object]:
        return await asyncio.gather(
            client.get_board_schema("42"), client.get_board_schema("42")
        )

    first, second = asyncio.run(read_concurrently())

    assert first == second
    assert first.columns[0].settings == {"labels": {"1": "Won"}}
    assert len(fake.requests) == 1
    request = fake.requests[0]
    assert request["url"] == "https://api.monday.com/v2"
    assert request["headers"]["API-Version"] == "2026-07"
    assert "columns { id title type settings }" in request["json"]["query"]
    assert "settings_str" not in request["json"]["query"]


def test_board_schema_cache_expires_after_fifteen_minutes() -> None:
    """Serving schemas forever would hide board changes from later analysis."""
    now = [100.0]
    payload = {
        "data": {
            "boards": [
                {"id": "42", "name": "Deals", "columns": []}
            ]
        }
    }
    fake = FakeHTTPClient([FakeResponse(payload), FakeResponse(payload)])
    client = GraphQLMondayClient(
        token="secret", http_client=fake, monotonic=lambda: now[0]
    )

    async def read_around_expiry() -> None:
        await client.get_board_schema("42")
        now[0] = 999.0
        await client.get_board_schema("42")
        now[0] = 1000.0
        await client.get_board_schema("42")

    asyncio.run(read_around_expiry())

    assert len(fake.requests) == 2


def test_get_board_items_follows_next_page_cursor_and_preserves_partial_errors() -> None:
    """Stopping at page one or discarding partial data silently undercounts boards."""
    fake = FakeHTTPClient(
        [
            FakeResponse(
                {
                    "data": {
                        "boards": [
                            {
                                "id": "42",
                                "name": "Deals",
                                "items_page": {
                                    "cursor": "next-1",
                                    "items": [
                                        {"id": "d-1", "name": "Acme", "column_values": []}
                                    ],
                                },
                            }
                        ]
                    },
                    "errors": [{"message": "one column was unavailable", "path": ["boards", 0]}],
                }
            ),
            FakeResponse(
                {
                    "data": {
                        "next_items_page": {
                            "cursor": None,
                            "items": [
                                {"id": "d-2", "name": "Beta", "column_values": []}
                            ],
                        }
                    }
                }
            ),
        ]
    )
    client = GraphQLMondayClient(token="secret", http_client=fake)

    result = asyncio.run(client.get_board_items("42"))

    assert [item.id for item in result.items] == ["d-1", "d-2"]
    assert result.partial is True
    assert result.caveats == ("one column was unavailable",)
    assert "items_page(limit: 500)" in fake.requests[0]["json"]["query"]
    assert fake.requests[0]["json"]["variables"] == {"boardIds": ["42"]}
    assert fake.requests[1]["json"]["variables"] == {"cursor": "next-1"}
    assert "limit: 500" in fake.requests[1]["json"]["query"]
    assert "next_items_page" in fake.requests[1]["json"]["query"]


def test_search_items_filters_normalized_values_across_all_pages() -> None:
    """Filtering only raw envelopes or page one misses legitimate matches."""
    pages = [
        FakeResponse(
            {
                "data": {
                    "boards": [
                        {
                            "id": "42",
                            "name": "Deals",
                            "items_page": {
                                "cursor": "next",
                                "items": [
                                    {
                                        "id": "d-1",
                                        "name": "Acme upgrade",
                                        "column_values": [
                                            {"id": "stage", "type": "status", "text": "Lost", "value": '{"index": 3}'}
                                        ],
                                    }
                                ],
                            },
                        }
                    ]
                }
            }
        ),
        FakeResponse(
            {
                "data": {
                    "next_items_page": {
                        "cursor": None,
                        "items": [
                            {
                                "id": "d-2",
                                "name": "Beta upgrade",
                                "column_values": [
                                    {"id": "stage", "type": "status", "text": "Won", "value": '{"index": 1}'}
                                ],
                            }
                        ],
                    }
                }
            }
        ),
    ]
    client = GraphQLMondayClient(token="secret", http_client=FakeHTTPClient(pages))

    result = asyncio.run(
        client.search_items(
            "42", SearchFilters(name_contains="upgrade", column_values={"stage": "won"})
        )
    )

    assert [item.id for item in result.items] == ["d-2"]


def test_rate_limit_retry_honors_retry_after_and_stays_bounded() -> None:
    """Ignoring server retry guidance can amplify throttling or retry forever."""
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    fake = FakeHTTPClient(
        [
            FakeResponse({}, status_code=429, headers={"Retry-After": "2"}),
            FakeResponse({}, status_code=429, headers={"Retry-After": "3"}),
            FakeResponse({}, status_code=429, headers={"Retry-After": "30"}),
        ]
    )
    client = GraphQLMondayClient(
        token="secret", http_client=fake, max_attempts=3, max_retry_delay=5, sleep=record_sleep
    )

    with pytest.raises(MondayAPIError) as error:
        asyncio.run(client.get_board_items("42"))

    assert error.value.classification == "rate_limit"
    assert len(fake.requests) == 3
    assert sleeps == [2.0, 3.0]


def test_graphql_retry_in_seconds_is_honored_before_success() -> None:
    """Ignoring GraphQL retry metadata needlessly fails recoverable reads."""
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    fake = FakeHTTPClient(
        [
            FakeResponse(
                {
                    "errors": [
                        {
                            "message": "Complexity budget exhausted",
                            "extensions": {"retry_in_seconds": 1.5},
                        }
                    ]
                }
            ),
            FakeResponse(
                {
                    "data": {
                        "boards": [
                            {"id": "42", "name": "Deals", "items_page": {"cursor": None, "items": []}}
                        ]
                    }
                }
            ),
        ]
    )
    client = GraphQLMondayClient(token="secret", http_client=fake, sleep=record_sleep)

    result = asyncio.run(client.get_board_items("42"))

    assert result.items == ()
    assert sleeps == [1.5]


def test_non_retryable_graphql_failure_is_classified() -> None:
    """Collapsing permission failures into generic transport errors prevents safe handling."""
    fake = FakeHTTPClient(
        [
            FakeResponse(
                {
                    "errors": [
                        {"message": "User unauthorized", "extensions": {"code": "UserUnauthorizedException"}}
                    ]
                }
            )
        ]
    )
    client = GraphQLMondayClient(token="secret", http_client=fake)

    with pytest.raises(MondayAPIError) as error:
        asyncio.run(client.get_board_items("42"))

    assert error.value.classification == "authentication"
    assert error.value.retryable is False


def test_invalid_board_id_is_rejected_before_transport() -> None:
    """Allowing arbitrary board identifiers weakens the typed GraphQL boundary."""
    fake = FakeHTTPClient([])
    client = GraphQLMondayClient(token="secret", http_client=fake)

    with pytest.raises(ValueError, match="board_id"):
        asyncio.run(client.get_board_items("42) { delete_something"))

    assert fake.requests == []
