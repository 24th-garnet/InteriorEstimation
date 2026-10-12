"""見積書の頭書き。**明細を作ってから足せない**ものを確かめる。"""
from __future__ import annotations

from datetime import date

import pytest

from estimate import quantity
from estimate.quantity import QuantityError

from .conftest import EXAMPLES


def sheet(est=None, **kw) -> dict:
    d = {"scan_id": "s", "name": "n", "items": [{"code": "A", "qty": 1}]} | kw
    if est is not None:
        d["estimate"] = est
    return d


def head(est):
    return quantity.parse(sheet(est)).header


def test_見本に頭書きがある():
    h = quantity.load(EXAMPLES / "quantities.json").header
    assert h.number == "2026-1013-001"
    assert h.issued == date(2026, 10, 13)
    assert h.client == "見本 太郎"
    assert h.identified is True


def test_頭書きは省略できる():
    # 検算だけしたいときに見積番号を切りたくない
    h = quantity.parse(sheet()).header
    assert h.number == "" and h.identified is False


def test_valid_days_は発行日から日付にする():
    h = head({"number": "X", "issued": "2026-10-13", "valid_days": 14})
    assert h.valid_until == date(2026, 10, 27)


def test_valid_until_を直に書ける():
    h = head({"number": "X", "issued": "2026-10-13", "valid_until": "2026-11-30"})
    assert h.valid_until == date(2026, 11, 30)


def test_valid_until_と_valid_days_の両方は書けない():
    with pytest.raises(QuantityError, match="両方"):
        head({"number": "X", "issued": "2026-10-13",
              "valid_until": "2026-11-30", "valid_days": 14})


def test_番号と発行日は揃えて書く():
    # 片方だけでは後から見積りを特定できない
    with pytest.raises(QuantityError, match="揃えて"):
        head({"number": "X"})
    with pytest.raises(QuantityError, match="揃えて"):
        head({"issued": "2026-10-13"})


def test_有効期限が発行日より前なら断る():
    with pytest.raises(QuantityError, match="より前"):
        head({"number": "X", "issued": "2026-10-13", "valid_until": "2026-10-01"})


def test_日付の書き方が違えば断る():
    with pytest.raises(QuantityError, match="YYYY-MM-DD"):
        head({"number": "X", "issued": "2026/10/13"})


def test_版は_1_以上の整数():
    assert head({"number": "X", "issued": "2026-10-13", "revision": 3}).revision == 3
    with pytest.raises(QuantityError, match="1 以上"):
        head({"number": "X", "issued": "2026-10-13", "revision": 0})


def test_valid_days_は発行日が無いと置けない():
    with pytest.raises(QuantityError):
        head({"valid_days": 14})
