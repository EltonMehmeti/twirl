import pytest
from sqlalchemy.exc import IntegrityError

from tests.factories import make_item, make_shop, make_style
from twirl.catalog import add_items, create_style, normalize_size, size_sort_key
from twirl.codes import CODE_ALPHABET, random_code


def test_random_code_uses_unambiguous_alphabet():
    for _ in range(200):
        code = random_code(4)
        assert len(code) == 4
        assert set(code) <= set(CODE_ALPHABET)


def test_style_codes_are_sequential_per_shop(db):
    shop = make_shop(db)
    first = create_style(db, shop, name="Red gown", price_cents=4500)
    second = create_style(db, shop, name="Blue gown", price_cents=6000)
    other = create_style(db, make_shop(db), name="Other", price_cents=100)
    assert (first.code, second.code, other.code) == ("001", "002", "001")


def test_create_style_rejects_unknown_occasion(db):
    with pytest.raises(ValueError):
        create_style(db, make_shop(db), name="X", price_cents=100, occasion_tags=["party"])


def test_add_items_creates_one_item_per_physical_dress(db):
    style = create_style(db, make_shop(db), name="Gold", price_cents=7000)
    items = add_items(db, style, size=" m ", quantity=3)
    assert len(items) == 3
    assert {i.size for i in items} == {"M"}
    assert len({i.code for i in items}) == 3


@pytest.mark.parametrize("quantity", [0, 21])
def test_add_items_rejects_bad_quantity(db, quantity):
    style = create_style(db, make_shop(db), name="Gold", price_cents=7000)
    with pytest.raises(ValueError):
        add_items(db, style, size="38", quantity=quantity)


def test_item_code_unique_per_shop(db):
    style = make_style(db, make_shop(db))
    make_item(db, style, code="ACDE")
    with pytest.raises(IntegrityError), db.begin_nested():
        make_item(db, style, code="ACDE")


def test_normalize_size_rejects_blank():
    with pytest.raises(ValueError):
        normalize_size("   ")


def test_sizes_sort_numbers_then_letters():
    assert sorted(["M", "40", "XS", "38", "L"], key=size_sort_key) == ["38", "40", "XS", "M", "L"]
