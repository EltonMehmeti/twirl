from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from tests.factories import make_item, make_shop, make_style
from twirl import clock
from twirl.booking.errors import NoAvailability
from twirl.booking.requests import RentalRequest, create_request
from twirl.models import Booking


@pytest.mark.parametrize("dresses", [1, 2])
def test_fifty_parallel_requests_never_double_book(committed, dresses):
    make_session = sessionmaker(committed, expire_on_commit=False)
    with make_session() as s:
        style = make_style(s, make_shop(s))
        for _ in range(dresses):
            make_item(s, style, size="38")
        s.commit()
        style_id = style.id
    event = clock.today() + timedelta(days=30)

    def attempt(i: int) -> str:
        with make_session() as s:
            try:
                create_request(
                    s,
                    RentalRequest(
                        style_id=style_id,
                        size="38",
                        event_date=event,
                        name=f"R{i}",
                        phone=f"+3834912{i:04d}",
                    ),
                    today=clock.today(),
                )
                s.commit()
                return "ok"
            except NoAvailability:
                s.rollback()
                return "none"

    with ThreadPoolExecutor(max_workers=50) as pool:
        results = list(pool.map(attempt, range(50)))

    assert results.count("ok") == dresses
    assert results.count("none") == 50 - dresses
    with make_session() as s:
        assert s.scalar(select(func.count()).select_from(Booking)) == dresses
