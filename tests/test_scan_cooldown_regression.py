"""Regression tests for server-owned scan cooldown and the zero-second UI loop."""

import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import db

PROJECT = Path(__file__).resolve().parents[1]


def _insert_session(session_id: str, *, status="EXHAUSTED", auto_scan=1, last_scan_at=None, interval=60):
    db.save_session(
        session_id=session_id,
        user_id=1,
        status=status,
        margin=5.0,
        leverage=20,
        quota=10,
        filled_count=10,
        mode="PUMP_GAINERS",
        is_live=False,
        started_at=time.time(),
        auto_scan=bool(auto_scan),
        scan_interval=interval,
        last_scan_at=last_scan_at,
        latest_evaluations="[]",
    )


def test_claim_due_session_is_atomic_and_enforces_cooldown(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "cooldown.db"))
    db.init_db()
    session_id = "cooldown-session"
    _insert_session(session_id, last_scan_at=None, interval=60)

    now = time.time()
    assert db.claim_due_session(session_id, now=now) is True
    # A second scheduler tick at the same instant cannot claim the same scan.
    assert db.claim_due_session(session_id, now=now + 1) is False

    latest = db.get_latest_user_session(1)
    assert latest is not None
    assert latest["last_scan_at"] == now


def test_claim_due_session_allows_next_scan_only_after_interval(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "cooldown-interval.db"))
    db.init_db()
    session_id = "interval-session"
    first = 1_000.0
    _insert_session(session_id, last_scan_at=first, interval=60)

    assert db.claim_due_session(session_id, now=first + 59) is False
    assert db.claim_due_session(session_id, now=first + 60) is True


def test_concurrent_scheduler_ticks_only_claim_one_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "cooldown-concurrent.db"))
    db.init_db()
    session_id = "concurrent-session"
    _insert_session(session_id, last_scan_at=None, interval=60)
    now = time.time()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: db.claim_due_session(session_id, now=now), range(8)))

    assert sum(results) == 1


def test_countdown_zero_does_not_dispatch_refresh_loop():
    source = (PROJECT / "frontend/src/components/BotControlCard.vue").read_text()
    countdown_section = source[source.index("// Presentation-only countdown"):source.index("onUnmounted", source.index("// Presentation-only countdown"))]
    assert "emit('sync-requested')" not in countdown_section
    assert "Menunggu server" in source


def test_polling_is_not_fired_when_document_is_hidden():
    source = (PROJECT / "frontend/src/components/TraderDashboard.vue").read_text()
    assert "document.visibilityState !== 'visible'" in source
    assert "setInterval(pollSummary, 10000)" in source
