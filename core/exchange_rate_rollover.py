from __future__ import annotations

import datetime

import psycopg

from core.api.service import CoreService
from core.domain.exchange_rate import BASE_CURRENCY
from core.domain.result import Err


def roll_forward_missing_rates(connection: psycopg.Connection, *, as_of: datetime.date) -> int:
    """For every (tenant, currency) with prior rate history but nothing dated `as_of`,
    carries the latest known rate forward as an explicit row dated `as_of`.

    Only rolls currencies that already have at least one manually-recorded rate —
    it never invents a rate for a currency nobody has ever priced.
    """
    service = CoreService(connection)
    tracked = connection.execute(
        "SELECT DISTINCT tenant_id, currency_code FROM core.exchange_rates WHERE currency_code != %s",
        (BASE_CURRENCY,),
    ).fetchall()

    rolled = 0
    for tenant_id, currency_code in tracked:
        already_present = connection.execute(
            "SELECT 1 FROM core.exchange_rates WHERE tenant_id = %s AND currency_code = %s AND effective_date = %s",
            (tenant_id, currency_code, as_of),
        ).fetchone()
        if already_present:
            continue

        latest = service.get_exchange_rate(
            tenant_id=tenant_id, currency_code=currency_code, as_of_date=as_of - datetime.timedelta(days=1)
        )
        if latest is None:
            continue

        result = service.record_exchange_rate(
            tenant_id=tenant_id,
            currency_code=currency_code,
            rate_to_base=latest.rate_to_base,
            effective_date=as_of,
            source="carried_forward",
        )
        if isinstance(result, Err):
            connection.rollback()
            continue
        connection.commit()
        rolled += 1

    return rolled
