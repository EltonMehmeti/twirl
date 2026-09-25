from datetime import timedelta

from tests.factories import make_booking, make_item, make_shop, make_style
from twirl import clock
from twirl.booking.dates import derive_rental_dates
from twirl.booking.rules import rules_for_shop
from twirl.search import upcoming_saturdays

EVENT = clock.today() + timedelta(days=30)


def _gown(db, shop, name="Red silk gown", sizes=("38", "40"), **fields):
    style = make_style(db, shop, name=name, **fields)
    return style, [make_item(db, style, size=size) for size in sizes]


def test_home_shows_search_and_dresses_to_anonymous_visitors(client, db):
    shop = make_shop(db, name="Bella", slug="bella", city="Prishtinë")
    style, _ = _gown(db, shop)
    response = client.get("/")
    assert response.status_code == 200
    assert 'name="date"' in response.text and 'name="size"' in response.text
    assert "Red silk gown" in response.text
    assert f'href="/bella/{style.code}"' in response.text
    assert "<option selected>Prishtinë</option>" not in response.text
    assert ">Prishtinë</option>" in response.text
    assert 'href="/listo"' in response.text  # providers still find their way in


def test_date_search_hides_booked_dress_and_links_with_the_date(client, db):
    shop = make_shop(db, slug="bella")
    free, _ = _gown(db, shop, name="Free gown", sizes=("38",))
    taken, (item,) = _gown(db, shop, name="Taken gown", sizes=("38",))
    dates = derive_rental_dates(EVENT, rules_for_shop(shop))
    make_booking(db, item, pickup=dates.pickup, return_=dates.return_)

    response = client.get(f"/?date={EVENT.isoformat()}&size=38")

    assert "Free gown" in response.text
    assert "Taken gown" not in response.text
    assert f'href="/bella/{free.code}?event_date={EVENT.isoformat()}&amp;size=38"' in response.text


def test_bad_filters_are_ignored_not_errors(client, db):
    shop = make_shop(db)
    _gown(db, shop)
    response = client.get("/?date=nonsense&size=99&city=Atlantis&category=x&max=abc&sort=y&page=-1")
    assert response.status_code == 200
    assert "Red silk gown" in response.text


def test_past_date_explains_itself(client, db):
    _gown(db, make_shop(db))
    today = clock.today().isoformat()
    response = client.get(f"/?date={today}")
    assert 'id="date-error"' in response.text
    assert f'value="{today}"' in response.text  # kept in the field so it can be fixed


def test_no_results_offers_ways_out(client, db):
    _gown(db, make_shop(db), sizes=("38",))
    response = client.get("/?size=38&max=5")
    assert "Red silk gown" not in response.text
    assert 'href="/?size=38"' in response.text  # drop the price cap


def test_home_lists_shops(client, db):
    shop = make_shop(db, name="Sallon Ana", slug="sallon-ana")
    _gown(db, shop)
    make_shop(db, name="Empty shop")
    response = client.get("/")
    assert 'href="/sallon-ana"' in response.text
    assert "Empty shop" not in response.text


def test_dress_page_opens_with_search_date_and_free_size(client, db, shop):
    style, (item38, _) = _gown(db, shop)
    dates = derive_rental_dates(EVENT, rules_for_shop(shop))
    make_booking(db, item38, pickup=dates.pickup, return_=dates.return_)

    response = client.get(f"/bella/{style.code}?event_date={EVENT.isoformat()}&size=38")

    assert f'value="{EVENT.isoformat()}"' in response.text
    assert '<option value="38" disabled>' in response.text
    assert '<option value="40" selected>' in response.text


def test_availability_swaps_in_size_select_with_taken_sizes_disabled(client, db, shop):
    style, (item38, _) = _gown(db, shop)
    dates = derive_rental_dates(EVENT, rules_for_shop(shop))
    make_booking(db, item38, pickup=dates.pickup, return_=dates.return_)
    response = client.get(
        f"/bella/{style.code}/availability?event_date={EVENT.isoformat()}&size=38"
    )
    assert 'id="size-select" required hx-swap-oob="true"' in response.text
    assert '<option value="38" disabled>' in response.text
    assert '<option value="40" selected>' in response.text


def test_date_shortcuts_are_saturdays_a_shop_can_still_serve(db):
    make_shop(db)
    today = clock.today()
    days = upcoming_saturdays(db, None, today=today)
    assert 1 <= len(days) <= 3
    assert all(day.weekday() == 5 and day > today for day in days)
    assert days == sorted(days)


def test_no_shops_means_no_date_shortcuts(client, db):
    assert 'class="v-datepicks"' not in client.get("/").text


def test_language_switch_keeps_the_search(client, db):
    response = client.get("/?date=2030-06-01&size=38")
    assert "/lang/en?next=/%3Fdate%3D2030-06-01%26size%3D38" in response.text
    switched = client.get("/lang/en?next=/%3Fdate%3D2030-06-01%26size%3D38", follow_redirects=False)
    assert switched.headers["location"] == "/?date=2030-06-01&size=38"


def test_language_switch_refuses_other_sites(client):
    for target in ("//evil.example", "/\\evil.example", "https://evil.example"):
        response = client.get("/lang/en", params={"next": target}, follow_redirects=False)
        assert response.headers["location"] == "/"


def test_loosening_only_offers_filters_that_bring_dresses_back(client, db):
    _gown(db, make_shop(db, city="Ferizaj"), sizes=("38",))
    response = client.get("/?size=38&max=5&city=Ferizaj")
    assert 'href="/?size=38&amp;city=Ferizaj"' in response.text  # drop the price cap: 1 dress
    assert 'href="/?city=Ferizaj&amp;max=5"' not in response.text  # any size: still nothing


def test_too_soon_date_points_to_the_earliest_date_that_works(client, db):
    _gown(db, make_shop(db))
    tomorrow = clock.today() + timedelta(days=1)
    response = client.get(f"/?date={tomorrow.isoformat()}")
    notice = response.text.split('class="v-nores"')[1].split("</div>")[0]
    earliest = [
        day
        for day in (clock.today() + timedelta(days=n) for n in range(2, 31))
        if f"/?date={day.isoformat()}" in notice
    ]
    assert len(earliest) == 1 and earliest[0] > tomorrow
