from datetime import date, time

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from liveops.db import Base
from liveops.models import ShiftSchedule, StoredSetting
from liveops.settings import SettingsStore, roster_people


def test_unconfigured_roster_suggests_existing_shifts_without_writing_settings(monkeypatch):
    import liveops.app as app_module

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    store = SettingsStore(None)  # No secrets are read from this isolated database.
    try:
        with Session(engine) as db:
            db.add_all([
                ShiftSchedule(work_date=date(2026, 9, 1), start_time=time(6), end_time=time(10),
                              host_name="主播甲", promoter="投手甲", ops="", live_room_id=""),
                ShiftSchedule(work_date=date(2026, 10, 1), start_time=time(6), end_time=time(10),
                              host_name="主播乙", promoter="", ops="旧投手乙", live_room_id=""),
                ShiftSchedule(work_date=date(2026, 10, 2), start_time=time(6), end_time=time(10),
                              host_name="主播甲", promoter="投手甲", ops="", live_room_id=""),
            ])
            db.commit()

        monkeypatch.setattr(app_module, "_db", lambda: Session(engine))
        monkeypatch.setattr(app_module, "_store", lambda _request: store)
        response = TestClient(app_module.app).get("/api/settings")
        assert response.status_code == 200
        people = response.json()["roster_people"]
        assert people == {"anchor": ["主播甲", "主播乙"], "ops": ["投手甲", "旧投手乙"],
                          "configured": {"anchor": False, "ops": False}}
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(StoredSetting)) == 0

            # A saved empty pool is intentional; a configured other pool may be nonempty.
            store.set(db, "roster_anchor_pool", "[]")
            store.set(db, "roster_promoter_pool", '["保留投手"]')
            db.commit()
            assert roster_people(db, store) == {
                "anchor": [], "ops": ["保留投手"],
                "configured": {"anchor": True, "ops": True},
            }

            # Each role is independently configured: an unconfigured role may still
            # suggest existing shifts without restoring removed names in the other.
            db.delete(db.get(StoredSetting, "roster_promoter_pool"))
            db.commit()
            assert roster_people(db, store) == {
                "anchor": [], "ops": ["投手甲", "旧投手乙"],
                "configured": {"anchor": True, "ops": False},
            }
    finally:
        engine.dispose()
