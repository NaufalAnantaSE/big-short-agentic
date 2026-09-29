"""Account migration tests use only an isolated temporary database."""
import pytest
import uuid
import db

@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / f'test_{uuid.uuid4().hex}.db')
    monkeypatch.setattr(db, 'DB_PATH', test_db)
    db.init_db()
    return db

def test_moves_private_data_atomically_and_does_not_resume_trading(isolated_db):
    from separate_accounts import separate_admin_account
    trader_user = f'trader_{uuid.uuid4().hex[:8]}'
    admin = db.get_user_by_username('admin')
    assert admin is not None
    db.update_user_credentials(admin['id'], 'demo-key', 'demo-secret')
    db.save_session('old-session', admin['id'], 'ACTIVE_SEARCHING', 5, 20, 10, 0, 'PUMP_GAINERS', False, 123)
    db.record_order(admin['id'], 'old-session', 'TEST-USDT', 1, 1, 1, 1, 'test-id', 'order-test', 'TEST')
    
    result = separate_admin_account('admin', trader_user, 'unique-password-test')
    trader = db.get_user_by_username(trader_user)
    assert trader is not None
    assert trader['role'] == 'user'
    assert result['user_id'] == trader['id']
    
    admin_after = db.get_user_by_username('admin')
    assert not admin_after['encrypted_api_key']
    assert not admin_after['encrypted_secret_key']
    
    trader_creds = db.get_decrypted_user_credentials(trader['id'])
    assert trader_creds['api_key'] == 'demo-key'
    assert db.get_latest_user_session(trader['id'])['status'] == 'TERMINATED'
    assert db.get_user_orders(admin['id']) == []
    assert len(db.get_user_orders(trader['id'])) == 1
    
    with pytest.raises(ValueError):
        separate_admin_account('admin', trader_user, 'another-password')
    assert db.get_decrypted_user_credentials(trader['id'])['api_key'] == 'demo-key'
