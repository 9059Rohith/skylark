from app.intelligence import cross_board, operations_metrics, pipeline_metrics
from app.monday import client, schemas, tools


def test_task_2_public_interfaces_exist() -> None:
    """A missing transport or intelligence entry point makes Task 2 unusable."""
    expected = (
        (client, "GraphQLMondayClient"),
        (client, "MondayAPIError"),
        (schemas, "ColumnSchema"),
        (schemas, "SearchFilters"),
        (tools, "normalize_column_value"),
        (pipeline_metrics, "pipeline_health"),
        (pipeline_metrics, "stage_conversion"),
        (pipeline_metrics, "pipeline_by_sector"),
        (pipeline_metrics, "missing_close_date_quality"),
        (operations_metrics, "average_work_order_completion_time"),
        (cross_board, "won_deals_without_work_orders"),
    )

    missing = [name for module, name in expected if not hasattr(module, name)]

    assert missing == []
