from collections.abc import Iterable, Sequence
from datetime import datetime

import pandas as pd
from sqlalchemy import delete, distinct, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.database.base import utcnow
from app.database.models import CANDLE_DATA_COLUMNS, Candle

UPSERT_CHUNK_SIZE = 500
UPDATABLE_COLUMNS = tuple(c for c in CANDLE_DATA_COLUMNS if c != "time") + ("complete", "source")


class CandleRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_candles(self, instrument: str, granularity: str, candles: Iterable[dict], *, source: str) -> int:
        """Insert candles, updating any row with the same (instrument, granularity, time).

        Idempotent: re-downloading an overlapping range never creates duplicates.
        """
        rows = [
            {**{k: c[k] for k in CANDLE_DATA_COLUMNS}, "complete": c.get("complete", True),
             "instrument": instrument, "granularity": granularity, "source": source}
            for c in candles
        ]
        if not rows:
            return 0

        dialect = self.session.get_bind().dialect.name
        insert_fn = {"postgresql": pg_insert, "sqlite": sqlite_insert}.get(dialect)
        if insert_fn is None:
            raise NotImplementedError(f"Upsert not implemented for dialect {dialect!r}")

        now = utcnow()
        for start in range(0, len(rows), UPSERT_CHUNK_SIZE):
            chunk = [{**r, "created_at": now, "updated_at": now} for r in rows[start:start + UPSERT_CHUNK_SIZE]]
            stmt = insert_fn(Candle).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["instrument", "granularity", "time"],
                set_={**{c: stmt.excluded[c] for c in UPDATABLE_COLUMNS}, "updated_at": now},
            )
            self.session.execute(stmt)
        self.session.commit()
        return len(rows)

    def _base(self, instrument: str, granularity: str):
        return select(Candle).where(Candle.instrument == instrument, Candle.granularity == granularity)

    def count(self, instrument: str, granularity: str) -> int:
        stmt = select(func.count()).select_from(Candle).where(
            Candle.instrument == instrument, Candle.granularity == granularity
        )
        return int(self.session.execute(stmt).scalar_one())

    def sources(self, instrument: str, granularity: str) -> set[str]:
        stmt = select(distinct(Candle.source)).where(
            Candle.instrument == instrument, Candle.granularity == granularity
        )
        return set(self.session.execute(stmt).scalars().all())

    def delete_all(self, instrument: str, granularity: str) -> int:
        result = self.session.execute(
            delete(Candle).where(Candle.instrument == instrument, Candle.granularity == granularity)
        )
        self.session.commit()
        return result.rowcount or 0

    def time_range(self, instrument: str, granularity: str) -> tuple[datetime | None, datetime | None]:
        stmt = select(func.min(Candle.time), func.max(Candle.time)).where(
            Candle.instrument == instrument, Candle.granularity == granularity
        )
        first, last = self.session.execute(stmt).one()
        # Aggregates bypass the column TypeDecorator on some dialects; normalise.
        return _as_utc(first), _as_utc(last)

    def latest_time(self, instrument: str, granularity: str) -> datetime | None:
        return self.time_range(instrument, granularity)[1]

    def recent(self, instrument: str, granularity: str, limit: int) -> Sequence[Candle]:
        stmt = self._base(instrument, granularity).order_by(Candle.time.desc()).limit(limit)
        return list(reversed(self.session.execute(stmt).scalars().all()))

    def load_recent_dataframe(self, instrument: str, granularity: str, limit: int) -> pd.DataFrame:
        """The most recent `limit` candles, oldest first, same columns as load_dataframe."""
        cols = [getattr(Candle, c) for c in CANDLE_DATA_COLUMNS]
        stmt = (select(*cols).where(Candle.instrument == instrument, Candle.granularity == granularity)
                .order_by(Candle.time.desc()).limit(limit))
        rows = self.session.execute(stmt).all()[::-1]
        return self._frame(rows)

    def _frame(self, rows) -> pd.DataFrame:
        df = pd.DataFrame(rows, columns=list(CANDLE_DATA_COLUMNS))
        df["time"] = pd.to_datetime(df["time"], utc=True)
        numeric = [c for c in CANDLE_DATA_COLUMNS if c != "time"]
        df[numeric] = df[numeric].apply(pd.to_numeric).astype(float)  # NULL -> NaN, even for all-NULL columns
        return df

    def load_dataframe(
        self,
        instrument: str,
        granularity: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """Load candles in chronological order with a UTC ``time`` column."""
        cols = [getattr(Candle, c) for c in CANDLE_DATA_COLUMNS]
        stmt = select(*cols).where(Candle.instrument == instrument, Candle.granularity == granularity)
        if start is not None:
            stmt = stmt.where(Candle.time >= start)
        if end is not None:
            stmt = stmt.where(Candle.time <= end)
        stmt = stmt.order_by(Candle.time)
        return self._frame(self.session.execute(stmt).all())


def _as_utc(value):
    if value is None:
        return None
    ts = pd.Timestamp(value)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return ts.to_pydatetime()
