import pytest
from orchestrator import SessionOrchestrator
from config import AppConfig
from scanner import MarketScanner, ExposureUnknownError
from client import BingXAPIError
from audit_logger import AuditLogger


def test_exposure_unknown_when_both_apis_timeout_blocks_new_entries(mocker):
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)

    # Both get_positions and get_open_orders time out
    mocker.patch.object(orch.client, "get_positions", side_effect=BingXAPIError(-1, "HTTP transport timeout"))
    mocker.patch.object(orch.client, "get_open_orders", side_effect=BingXAPIError(-1, "HTTP transport timeout"))

    mock_place_order = mocker.patch.object(orch.client, "place_order")
    mock_scan = mocker.patch.object(orch.scanner, "scan_universe")
    spy_audit = mocker.spy(AuditLogger, "log_event")

    res = orch.run_cycle(dry_run=False)

    # Must fail-closed: return EXPOSURE_UNKNOWN status, block scan and orders
    assert res["status"] == "EXPOSURE_UNKNOWN"
    mock_scan.assert_not_called()
    mock_place_order.assert_not_called()

    # Must log audit event
    assert any(call.args[0] == "EXPOSURE_UNKNOWN" for call in spy_audit.call_args_list)


def test_exposure_unknown_when_positions_fails_even_if_orders_succeeds(mocker):
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)

    mocker.patch.object(orch.client, "get_positions", side_effect=BingXAPIError(100410, "Rate limited"))
    mocker.patch.object(orch.client, "get_open_orders", return_value=[])

    mock_place_order = mocker.patch.object(orch.client, "place_order")

    res = orch.run_cycle(dry_run=False)

    assert res["status"] == "EXPOSURE_UNKNOWN"
    mock_place_order.assert_not_called()


def test_exposure_unknown_when_orders_fails_even_if_positions_succeeds(mocker):
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)

    mocker.patch.object(orch.client, "get_positions", return_value=[])
    mocker.patch.object(orch.client, "get_open_orders", side_effect=BingXAPIError(504, "Gateway Timeout"))

    mock_place_order = mocker.patch.object(orch.client, "place_order")

    res = orch.run_cycle(dry_run=False)

    assert res["status"] == "EXPOSURE_UNKNOWN"
    mock_place_order.assert_not_called()


def test_scanner_get_occupied_symbols_raises_exposure_unknown_error(mocker):
    config = AppConfig(api_key="mock", secret_key="mock")
    scanner = MarketScanner(client=mocker.MagicMock(), config=config)

    mocker.patch.object(scanner.client, "get_positions", side_effect=Exception("API failure"))
    mocker.patch.object(scanner.client, "get_open_orders", return_value=[])

    with pytest.raises(ExposureUnknownError):
        scanner.get_occupied_symbols()


def test_scanner_get_occupied_symbols_returns_empty_when_valid(mocker):
    config = AppConfig(api_key="mock", secret_key="mock")
    scanner = MarketScanner(client=mocker.MagicMock(), config=config)

    mocker.patch.object(scanner.client, "get_positions", return_value=[])
    mocker.patch.object(scanner.client, "get_open_orders", return_value=[])

    occupied = scanner.get_occupied_symbols()
    assert occupied == set()
