from app.config import Settings


def test_monday_board_ids_use_required_deployment_environment_names(monkeypatch) -> None:
    """Deployment-provided board IDs must bind to the documented MONDAY_* names."""
    monkeypatch.setenv("MONDAY_DEALS_BOARD_ID", "101")
    monkeypatch.setenv("MONDAY_WORK_ORDERS_BOARD_ID", "202")

    settings = Settings(_env_file=None)

    assert settings.deals_board_id == "101"
    assert settings.work_orders_board_id == "202"


def test_legacy_unprefixed_board_id_environment_names_are_not_consumed(monkeypatch) -> None:
    """Keeping two env contracts makes misconfigured deployments look healthy."""
    monkeypatch.delenv("MONDAY_DEALS_BOARD_ID", raising=False)
    monkeypatch.delenv("MONDAY_WORK_ORDERS_BOARD_ID", raising=False)
    monkeypatch.setenv("DEALS_BOARD_ID", "wrong")
    monkeypatch.setenv("WORK_ORDERS_BOARD_ID", "wrong")

    settings = Settings(_env_file=None)

    assert settings.deals_board_id == ""
    assert settings.work_orders_board_id == ""


def test_openai_provider_environment_contract_is_bound(monkeypatch) -> None:
    """Production defaults and credentials must bind from the documented env names."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4-mini")

    settings = Settings(_env_file=None)

    assert settings.llm_provider == "openai"
    assert settings.openai_api_key == "test-openai-key"
    assert settings.openai_model == "gpt-5.4-mini"
