"""Live integration tests against BingX VST (Virtual Swap Trading) Demo environment."""

import pytest
from config import load_config
from client import BingXClient

@pytest.fixture(scope="module")
def vst_client():
    config = load_config()
    assert config.api_key and config.secret_key, "API credentials required for VST tests."
    return BingXClient(config)

def test_vst_connectivity_and_balance(vst_client):
    bal_data = vst_client.get_balance()
    assert isinstance(bal_data, (list, dict))
    if isinstance(bal_data, list):
        assert len(bal_data) > 0
        vst_asset = next((x for x in bal_data if x.get("asset") == "VST"), None)
        assert vst_asset is not None
        assert float(vst_asset.get("balance", 0)) > 0
        assert float(vst_asset.get("equity", 0)) > 0
    else:
        assert bal_data.get("asset") == "VST"
        assert float(bal_data.get("balance", 0)) > 0
        assert float(bal_data.get("equity", 0)) > 0

def test_vst_hedge_mode(vst_client):
    mode = vst_client.get_position_mode()
    assert isinstance(mode, dict)
    # BingX Hedge mode requires dualSidePosition: "true"
    assert str(mode.get("dualSidePosition", "")).lower() == "true"

def test_vst_positions_query(vst_client):
    positions = vst_client.get_positions()
    assert isinstance(positions, list)

def test_vst_contracts_and_leverage(vst_client):
    contracts = vst_client.get_contracts()
    assert len(contracts) > 100
    
    # Query leverage for a known pair
    lev = vst_client.get_leverage("DOGE-USDT")
    assert isinstance(lev, dict)
    assert "maxShortLeverage" in lev
    assert int(lev.get("maxShortLeverage", 0)) >= 20
