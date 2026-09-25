import pytest

from twirl.phones import InvalidPhone, normalize_phone


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("044 123 456", "+38344123456"),
        ("+383 49 123 456", "+38349123456"),
        ("00383 45 123 456", "+38345123456"),
        ("+49 151 23456789", "+4915123456789"),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "123", "044 12"])
def test_normalize_phone_rejects_garbage(raw):
    with pytest.raises(InvalidPhone):
        normalize_phone(raw)
