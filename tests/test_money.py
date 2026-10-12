"""円の算術。**丸めの規約を直したら落ちる**ように書く。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from estimate.money import MoneyError, by_rate, dec, to_yen, total


def test_float_を文字列経由で畳む():
    # Decimal(48.6) は 48.6000000000000014... になる。これを通すと合計が濁る
    assert dec(48.6, field="qty") == Decimal("48.6")


def test_真偽値は数として受けない():
    # bool は int の子なので、素朴に書くと True が 1 として通ってしまう
    with pytest.raises(MoneyError):
        dec(True, field="qty")


def test_読めない値は欄の名前を添えて断る():
    with pytest.raises(MoneyError, match="material"):
        dec("いくらか", field="material")


def test_円未満は切り捨てる():
    assert to_yen(Decimal("22963.95")) == Decimal("22963")
    assert to_yen(Decimal("0.99")) == Decimal("0")


def test_合計は丸め直さない():
    # 行を丸めてから足す。足してから丸めると行の和と合計が食い違う
    rows = [to_yen(Decimal("10.6")), to_yen(Decimal("10.6")), to_yen(Decimal("10.6"))]
    assert total(rows) == Decimal("30")
    assert to_yen(Decimal("10.6") * 3) == Decimal("31")


def test_段の金額も円未満を切り捨てる():
    # 1,293,233 × 6.2% = 80,180.446
    assert by_rate(Decimal("1293233"), Decimal("0.062")) == Decimal("80180")


def test_段を丸めてから累計を作る():
    # 足してから丸めるのと値が違うことを固定する。累計は丸め済みの段の和
    base = Decimal("1293233")
    a = by_rate(base, Decimal("0.062"))
    b = by_rate(base + a, Decimal("0.095"))
    assert (a, b) == (Decimal("80180"), Decimal("130474"))
    assert base + a + b == Decimal("1503887")
