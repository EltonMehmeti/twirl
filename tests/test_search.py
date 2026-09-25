from datetime import timedelta

from tests.factories import make_booking, make_item, make_shop, make_style
from twirl import clock
from twirl.booking.dates import derive_rental_dates
from twirl.booking.rules import rules_for_shop
from twirl.models import ShopClosure
from twirl.search import PAGE_SIZE, Filters, city_options, search, shop_cards, size_options

TODAY = clock.today()
EVENT = TODAY + timedelta(days=30)


def names(results):
    return [card.style.name for card in results.cards]


def dress(db, shop, name, *, sizes=("38",), price_cents=5000, category=None, published=True):
    style = make_style(db, shop, name=name, price_cents=price_cents, published=published)
    style.category = category
    items = [make_item(db, style, size=size) for size in sizes]
    return style, items


def test_lists_published_dresses_of_published_shops_only(db):
    live = make_shop(db, city="Prishtinë")
    hidden_shop = make_shop(db, status="draft")
    dress(db, live, "Live gown")
    dress(db, live, "Hidden gown", published=False)
    dress(db, hidden_shop, "Draft shop gown")
    style_without_items = make_style(db, live, name="No items")
    assert style_without_items

    results = search(db, Filters(), today=TODAY)

    assert names(results) == ["Live gown"]
    assert results.total == 1


def test_date_hides_dresses_booked_for_that_event(db):
    shop = make_shop(db)
    _, (taken,) = dress(db, shop, "Taken gown")
    dress(db, shop, "Free gown")
    dates = derive_rental_dates(EVENT, rules_for_shop(shop))
    make_booking(db, taken, pickup=dates.pickup, return_=dates.return_)

    assert names(search(db, Filters(event_date=EVENT), today=TODAY)) == ["Free gown"]
    assert sorted(names(search(db, Filters(), today=TODAY))) == ["Free gown", "Taken gown"]


def test_cleaning_buffer_counts_as_busy(db):
    shop = make_shop(db, cleaning_days=2)
    _, (item,) = dress(db, shop, "Gown")
    dates = derive_rental_dates(EVENT, rules_for_shop(shop))
    # returned the day before our pickup: still being cleaned
    make_booking(
        db,
        item,
        pickup=dates.pickup - timedelta(days=4),
        return_=dates.pickup - timedelta(days=1),
        cleaning_days=2,
    )
    assert names(search(db, Filters(event_date=EVENT), today=TODAY)) == []


def test_date_and_size_must_match_the_same_item(db):
    shop = make_shop(db)
    _, (item38, _) = dress(db, shop, "Gown", sizes=("38", "40"))
    dates = derive_rental_dates(EVENT, rules_for_shop(shop))
    make_booking(db, item38, pickup=dates.pickup, return_=dates.return_)

    assert names(search(db, Filters(event_date=EVENT, size="38"), today=TODAY)) == []
    results = search(db, Filters(event_date=EVENT, size="40"), today=TODAY)
    assert names(results) == ["Gown"]
    assert results.cards[0].sizes == ["40"]


def test_cards_list_free_sizes_in_order(db):
    shop = make_shop(db)
    dress(db, shop, "Gown", sizes=("M", "40", "36", "S"))
    (card,) = search(db, Filters(), today=TODAY).cards
    assert card.sizes == ["36", "40", "S", "M"]


def test_date_too_soon_for_every_shop_says_so(db):
    shop = make_shop(db, pickup_lead_days=2)
    dress(db, shop, "Gown")
    results = search(db, Filters(event_date=TODAY), today=TODAY)
    assert results.date_unreachable
    assert results.cards == []


def test_shop_closed_on_pickup_day_is_left_out(db):
    open_shop = make_shop(db)
    closed_shop = make_shop(db)
    dress(db, open_shop, "Open gown")
    dress(db, closed_shop, "Closed gown")
    db.add(
        ShopClosure(
            shop_id=closed_shop.id,
            starts_on=EVENT - timedelta(days=20),
            ends_on=EVENT + timedelta(days=20),
        )
    )
    db.flush()
    db.expire_all()
    assert names(search(db, Filters(event_date=EVENT), today=TODAY)) == ["Open gown"]


def test_city_category_and_price_filters_combine(db):
    pr = make_shop(db, city="Prishtinë")
    fe = make_shop(db, city="Ferizaj")
    dress(db, pr, "Cheap evening", price_cents=3000, category="evening")
    dress(db, pr, "Dear evening", price_cents=9000, category="evening")
    dress(db, pr, "Bridal", price_cents=3000, category="bridal")
    dress(db, fe, "Ferizaj evening", price_cents=3000, category="evening")

    results = search(
        db, Filters(city="Prishtinë", category="evening", max_price_cents=5000), today=TODAY
    )
    assert names(results) == ["Cheap evening"]


def test_sort_by_price(db):
    shop = make_shop(db)
    for name, price in [("Mid", 5000), ("Low", 2000), ("High", 9000)]:
        dress(db, shop, name, price_cents=price)
    assert names(search(db, Filters(sort="price_asc"), today=TODAY)) == ["Low", "Mid", "High"]
    assert names(search(db, Filters(sort="price_desc"), today=TODAY)) == ["High", "Mid", "Low"]


def test_paginates(db):
    shop = make_shop(db)
    for n in range(PAGE_SIZE + 3):
        dress(db, shop, f"Gown {n}")
    first = search(db, Filters(), today=TODAY)
    last = search(db, Filters(page=2), today=TODAY)
    assert (first.total, first.pages, len(first.cards)) == (PAGE_SIZE + 3, 2, PAGE_SIZE)
    assert len(last.cards) == 3
    assert search(db, Filters(page=99), today=TODAY).page == 2


def test_options_only_offer_what_exists(db):
    pr = make_shop(db, city="Prishtinë")
    make_shop(db, city="Pejë")  # no dresses
    dress(db, pr, "Gown", sizes=("40", "36"))
    dress(db, pr, "Hidden", sizes=("50",), published=False)
    assert size_options(db) == ["36", "40"]
    assert city_options(db) == ["Prishtinë"]


def test_shop_cards_count_published_dresses(db):
    big = make_shop(db, name="Big", city="Prizren")
    small = make_shop(db, name="Small", city="Prizren")
    make_shop(db, name="Empty")
    for n in range(3):
        dress(db, big, f"B{n}")
    dress(db, small, "S0")
    cards = shop_cards(db)
    assert [(c.shop.name, c.dresses) for c in cards] == [("Big", 3), ("Small", 1)]
    assert cards[0].cover.name == "B2"
