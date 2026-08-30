import asyncio
from decimal import Decimal

import pytest

from app.agent.graph import AgentRunner
from app.agent.nodes import map_live_columns
from app.intelligence import pipeline_by_sector, won_deals_without_work_orders
from app.monday.client import GraphQLMondayClient
from app.monday.schemas import BoardItemsResult, BoardSchema, ColumnSchema, MondayItem
from tests.test_monday_client import FakeHTTPClient, FakeResponse
from tests.test_agent_graph import dependencies, sid


def test_live_dropdown_sector_flows_from_transport_to_sector_analysis() -> None:
    """A one-label monday Dropdown must remain a usable scalar business sector."""
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
                                    {"id": "sector", "title": "Sector", "type": "dropdown", "settings": {}},
                                    {"id": "amount", "title": "Amount", "type": "numbers", "settings": {}},
                                ],
                            }
                        ]
                    }
                }
            ),
            FakeResponse(
                {
                    "data": {
                        "boards": [
                            {
                                "id": "42",
                                "name": "Deals",
                                "items_page": {
                                    "cursor": None,
                                    "items": [
                                        {
                                            "id": "d-1",
                                            "name": "Acme",
                                            "column_values": [
                                                {"id": "sector", "type": "dropdown", "text": "Energy", "value": '{"ids":[1]}'},
                                                {"id": "amount", "type": "numbers", "text": "100", "value": "100"},
                                            ],
                                        }
                                    ],
                                },
                            }
                        ]
                    }
                }
            ),
        ]
    )
    client = GraphQLMondayClient(token="test-token", http_client=fake)
    schema = asyncio.run(client.get_board_schema("42"))
    items = asyncio.run(client.get_board_items("42"))

    records = map_live_columns(schema, items, board_kind="deals")
    analysis = pipeline_by_sector(records)

    assert records[0]["sector"] == "Energy"
    assert analysis.metrics["sectors"] == {
        "Energy": {"deal_count": 1, "total_value_inr": Decimal("100")}
    }


def test_multi_select_sector_remains_unclassified_with_explicit_quality_reason() -> None:
    """Selecting the first of multiple sectors would invent an arbitrary classification."""
    analysis = pipeline_by_sector([{"id": "d-1", "sector": ["Energy", "Retail"], "amount": "100"}])

    assert analysis.metrics["sectors"] == {
        "Unclassified": {"deal_count": 1, "total_value_inr": Decimal("100")}
    }
    assert analysis.quality.exclusions == {"sector:ambiguous_multi_select_sector": 1}


def test_item_name_client_fallback_requires_explicit_mapping_configuration() -> None:
    """A deal-name item must never become a client unless the board explicitly says so."""
    schema = BoardSchema(
        board_id="101",
        name="Deals",
        columns=(ColumnSchema(id="client", title="Client", type="text"),),
    )
    result = BoardItemsResult(
        board_id="101",
        items=(
            MondayItem(id="d-1", name="Fallback Co", values={"client": ""}),
            MondayItem(id="d-2", name="Item Name", values={"client": "Explicit Co"}),
        ),
    )

    default_mapped = map_live_columns(schema, result, board_kind="deals")
    client_mapped = map_live_columns(
        schema, result, board_kind="deals", item_name_semantic="client"
    )

    assert default_mapped[0]["deal_name"] == "Fallback Co"
    assert default_mapped[0]["client"] == ""
    assert client_mapped[0]["client"] == "Fallback Co"
    assert client_mapped[0]["_client_source"] == "item_name_fallback"
    assert client_mapped[1]["client"] == "Explicit Co"


def test_actual_workbook_titles_preserve_dates_and_match_by_deal_name_before_client() -> None:
    """Masked client-code differences must not defeat the shared deal-name match key."""
    deal_schema = BoardSchema(
        board_id="101",
        name="Deals",
        columns=(
            ColumnSchema(id="status", title="Deal Status", type="status"),
            ColumnSchema(id="stage", title="Deal Stage", type="status"),
            ColumnSchema(id="client", title="Client Code", type="text"),
            ColumnSchema(id="amount", title="Masked Deal value", type="numbers"),
            ColumnSchema(id="actual", title="Close Date (A)", type="date"),
            ColumnSchema(id="tentative", title="Tentative Close Date", type="date"),
            ColumnSchema(id="sector", title="Sector/service", type="dropdown"),
        ),
    )
    work_schema = BoardSchema(
        board_id="202",
        name="Work Orders",
        columns=(
            ColumnSchema(id="client", title="Customer Name Code", type="text"),
            ColumnSchema(id="serial", title="Serial #", type="text"),
            ColumnSchema(id="status", title="Execution Status", type="status"),
            ColumnSchema(id="start", title="Probable Start Date", type="date"),
            ColumnSchema(id="delivered", title="Data Delivery Date", type="date"),
            ColumnSchema(id="expected", title="Probable End Date", type="date"),
        ),
    )
    deals = map_live_columns(
        deal_schema,
        BoardItemsResult(
            board_id="101",
            items=(
                MondayItem(id="d-1", name="Solar Survey Alpha", values={"status": "Won", "stage": "H. Work Order Received", "client": "COMPANY001", "amount": "100", "actual": "2026-08-30", "tentative": "2026-09-30", "sector": "Renewables"}),
                MondayItem(id="d-2", name="Open Powerline Bid", values={"status": "Open", "stage": "E. Proposal/Commercials Sent", "client": "COMPANY002", "amount": "200", "actual": "", "tentative": "2026-10-15", "sector": "Powerline"}),
            ),
        ),
        board_kind="deals",
    )
    work_orders = map_live_columns(
        work_schema,
        BoardItemsResult(
            board_id="202",
            items=(MondayItem(id="wo-1", name="Solar Survey Alpha", values={"client": "WOCOMPANY999", "serial": "WO-7", "status": "Completed", "start": "2026-08-01", "delivered": "2026-08-20", "expected": "2026-08-25"}),),
        ),
        board_kind="work_orders",
    )

    gaps = won_deals_without_work_orders(deals, work_orders)

    assert deals[0]["close_date"] == "2026-08-30"
    assert deals[1]["close_date"] == "2026-10-15"
    assert deals[0]["close_date_actual"] == "2026-08-30"
    assert deals[0]["close_date_tentative"] == "2026-09-30"
    assert work_orders[0]["work_order_id"] == "WO-7"
    assert "deal_id" not in work_orders[0]
    assert gaps.metrics["won_deal_count"] == 1
    assert gaps.metrics["matched_work_order_count"] == 1


class ActualWorkbookSectorMonday:
    async def get_board_schema(self, board_id: str) -> BoardSchema:
        return BoardSchema(
            board_id=board_id,
            name="Deals",
            columns=(
                ColumnSchema(id="amount", title="Masked Deal value", type="numbers"),
                ColumnSchema(id="sector", title="Sector/service", type="dropdown"),
            ),
        )

    async def get_board_items(self, board_id: str) -> BoardItemsResult:
        return BoardItemsResult(
            board_id=board_id,
            items=(
                MondayItem(id="d-1", name="Renewable survey", values={"amount": "100", "sector": "Renewables"}),
                MondayItem(id="d-2", name="Powerline survey", values={"amount": "200", "sector": "Powerline"}),
                MondayItem(id="d-3", name="Mine survey", values={"amount": "300", "sector": "Mining"}),
            ),
        )

    async def search_items(self, board_id: str, filters: object) -> BoardItemsResult:
        return await self.get_board_items(board_id)


@pytest.mark.asyncio
async def test_energy_primary_archetype_expands_to_renewables_and_powerline() -> None:
    """The evaluator's Energy scope must include its workbook-specific sector members."""
    runner = AgentRunner(dependencies(ActualWorkbookSectorMonday()))

    result = await runner.run_agent("How healthy is pipeline for Energy?", sid(52))

    assert result["analysis"]["metrics"]["deal_count"] == 2
    assert result["analysis"]["metrics"]["total_pipeline_value_inr"] == "300"
