"""Regression coverage for desktop SQLite writers sharing one database file."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func

from memoryhub.core.forget.rules import ForgetRuleService
from memoryhub.storage.database import Database
from memoryhub.storage.models import PreferenceRow


def test_multiple_database_instances_and_direct_writer_are_serialized(tmp_path):
    db_path = tmp_path / "shared.db"
    first = Database(str(db_path))
    second = Database(str(db_path.resolve()))
    first.init_schema()
    second.init_schema()
    rules = ForgetRuleService(db_path)

    def write_batch(worker: int) -> None:
        database = first if worker % 2 == 0 else second
        for item in range(15):
            with database.session() as session:
                session.add(
                    PreferenceRow(
                        memory_id=f"pref_{worker}_{item}",
                        user_id="concurrency-user",
                        preference_type="format_preference",
                        content=f"worker {worker} item {item}",
                    )
                )
            if item % 5 == 0:
                created = rules.create(
                    user_id=f"user-{worker}",
                    topic=f"topic-{item}",
                    keywords=[f"keyword-{worker}-{item}"],
                )
                assert rules.delete(f"user-{worker}", created["rule_id"])

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(write_batch, range(8)))

        with first.session() as session:
            count = session.query(func.count(PreferenceRow.memory_id)).scalar()
        assert count == 120
    finally:
        rules.close()
        first.close()
        second.close()
