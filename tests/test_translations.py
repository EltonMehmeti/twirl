from pathlib import Path

from babel.messages.extract import extract_from_dir
from babel.messages.pofile import read_po

ROOT = Path(__file__).resolve().parents[1]
PO_FILE = ROOT / "src/twirl/locale/sq/LC_MESSAGES/messages.po"
METHOD_MAP = [("**.py", "python"), ("**/templates/**.html", "jinja2")]
OPTIONS = {"**/templates/**.html": {"extensions": "jinja2.ext.i18n"}}


def _catalog():
    with PO_FILE.open("rb") as handle:
        return read_po(handle)


def test_every_albanian_string_is_translated():
    catalog = _catalog()
    missing = [m.id for m in catalog if m.id and not m.string]
    fuzzy = [m.id for m in catalog if m.id and m.fuzzy]
    assert not missing, missing
    assert not fuzzy, fuzzy


def test_catalog_contains_every_source_string():
    catalog = _catalog()
    source = {
        message
        for _, _, message, _, _ in extract_from_dir(
            str(ROOT / "src/twirl"), METHOD_MAP, OPTIONS, keywords={"_": None, "N_": None}
        )
        if isinstance(message, str)
    }
    missing = sorted(source - {m.id for m in catalog if m.id})
    assert not missing, missing
