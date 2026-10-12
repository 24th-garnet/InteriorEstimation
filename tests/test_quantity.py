"""数量リストの読み込み。"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from estimate import quantity
from estimate.quantity import QuantityError

from .conftest import EXAMPLES


def sheet(estimate=None, **kw) -> dict:
    d = {"scan_id": "s", "name": "n", "items": [{"code": "A", "qty": 1}]} | kw
    if estimate is not None:
        d["estimate"] = estimate
    return d


def test_見本が読める():
    s = quantity.load(EXAMPLES / "quantities.json")
    assert s.scan_id == "room-0a3f"
    assert len(s.lines) >= 20       # 生成物なので件数は固定しない


def test_小数が_float_を通らずに読める():
    s = quantity.load(EXAMPLES / "quantities.json")
    wc = next(l for l in s.lines if l.code == "WC-1000")
    assert wc.qty == Decimal("48.6")
    assert str(wc.qty) == "48.6"


def test_同じコードが_2_行あっても合算しない():
    # 「居間の壁」と「寝室の壁」は同じクロスでも別の行として見せたい
    s = quantity.parse(sheet(items=[{"code": "A", "qty": 10, "note": "居間"},
                                    {"code": "A", "qty": 6, "note": "寝室"}]))
    assert [l.note for l in s.lines] == ["居間", "寝室"]


def test_数量が_0_以下なら断る():
    with pytest.raises(QuantityError, match="0 以下"):
        quantity.parse(sheet(items=[{"code": "A", "qty": 0}]))


def test_不備は全部ためてから投げる():
    with pytest.raises(QuantityError) as e:
        quantity.parse(sheet(items=[{"qty": 1}, {"code": "B"}, {"code": "C", "qty": -1}]))
    assert len(e.value.reasons) == 3


def test_items_が空なら断る():
    with pytest.raises(QuantityError, match="空"):
        quantity.parse(sheet(items=[]))


# --- 値引き -------------------------------------------------------------

def disc(d):
    return quantity.parse(sheet(estimate={"number": "X", "issued": "2026-10-13",
                                          "discount": d})).discount


def test_値引きを額で読む():
    assert disc({"amount": 27205}).amount == Decimal("27205")


def test_値引きを端数調整で読む():
    d = disc({"name": "端数", "target": 1810000, "basis": "税込"})
    assert (d.name, d.target, d.basis) == ("端数", Decimal("1810000"), "税込")


def test_値引きの既定の基準は税込():
    assert disc({"target": 1810000}).basis == "税込"


def test_値引きは額と目標の両方を書けない():
    with pytest.raises(QuantityError, match="両方"):
        disc({"amount": 100, "target": 1810000})


def test_値引きに額も目標も無ければ断る():
    with pytest.raises(QuantityError, match="どちらかが要る"):
        disc({"name": "値引き"})


def test_値引きの額が_0_以下なら断る():
    with pytest.raises(QuantityError, match="0 より大きい"):
        disc({"amount": 0})


def test_知らない基準は断る():
    with pytest.raises(QuantityError, match="basis"):
        disc({"target": 1810000, "basis": "内税"})


def test_値引きが無くても読める():
    assert quantity.parse(sheet()).discount is None
