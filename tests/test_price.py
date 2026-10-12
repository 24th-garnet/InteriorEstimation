"""単価表の読み込みと検証。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from estimate import price
from estimate.price import PriceError

from .conftest import EXAMPLES

PRICES = EXAMPLES / "prices.csv"
TRADES = EXAMPLES / "trades.csv"

HEAD = "code,name,unit,division,section,material,loss,labor,trade,tax,source,as_of\n"


def write(tmp_path, body: str, head: str = HEAD,
          trades: str = "trade,name,daily\n内装工,内装仕上工,24000\n"):
    p, t = tmp_path / "p.csv", tmp_path / "t.csv"
    p.write_text(head + body, encoding="utf-8")
    t.write_text(trades, encoding="utf-8")
    return p, t


def test_見本が読める():
    book = price.load(PRICES, TRADES)
    assert len(book.items) >= 20
    assert len(book.trades) == 5
    # 生成物なので件数は固定しない。**全品目に出どころと適用日がある**ことを見る
    assert all(i.source and i.as_of for i in book.items.values())


def test_施工費は歩掛り_かける_労務単価():
    book = price.load(PRICES, TRADES)
    # 0.10 人工/㎡ × 24,000 円/人工 = 2,400 円/㎡
    assert book.labor_unit(book.items["WC-1000"]) == Decimal("2400.00")


def test_職種の無い品目は施工費_0():
    book = price.load(PRICES, TRADES)
    rug = next(i for i in book.items.values() if not i.trade)
    assert book.labor_unit(rug) == 0


def test_科目と中科目を持つ():
    book = price.load(PRICES, TRADES)
    assert (book.items["WC-1000"].division,
            book.items["WC-1000"].section) == ("内装工事", "壁・天井仕上")


def test_税区分の既定は課税(tmp_path):
    p, t = write(tmp_path, "A,あ,㎡,内装,仕上,100,0,0,,,,\n")
    assert price.load(p, t).items["A"].tax == price.TAXED


def test_知らない税区分は断る(tmp_path):
    p, t = write(tmp_path, "A,あ,㎡,内装,仕上,100,0,0,,軽減,,\n")
    with pytest.raises(PriceError, match="税区分"):
        price.load(p, t)


def test_出典と適用日を持つ():
    book = price.load(PRICES, TRADES)
    assert book.items["FL-2000"].source == "建設物価 2026-04"
    assert book.items["FL-2000"].as_of == date(2026, 4, 1)


def test_日付でない_as_of_は断る(tmp_path):
    p, t = write(tmp_path, "A,あ,㎡,内装,仕上,100,0,0,,課税,X,2026/04/01\n")
    with pytest.raises(PriceError, match="as_of"):
        price.load(p, t)


def test_出典の列は無くても読める(tmp_path):
    # 既にある表をそのまま読めないと、入れ替えが進まない
    head = "code,name,unit,division,section,material,loss,labor,trade\n"
    p, t = write(tmp_path, "A,あ,㎡,内装,仕上,100,0,0,\n", head=head)
    item = price.load(p, t).items["A"]
    assert item.source == "" and item.as_of is None and item.tax == price.TAXED


def test_知らない職種は断る(tmp_path):
    p, t = write(tmp_path, "A,あ,㎡,内装,仕上,100,0,0.1,左官,,,\n")
    with pytest.raises(PriceError, match="左官"):
        price.load(p, t)


def test_歩掛りがあるのに職種が空なら断る(tmp_path):
    # 黙って 0 円にすると施工費が静かに落ちる
    p, t = write(tmp_path, "A,あ,㎡,内装,仕上,100,0,0.1,,,,\n")
    with pytest.raises(PriceError, match="職種が空"):
        price.load(p, t)


def test_単位が空なら断る(tmp_path):
    p, t = write(tmp_path, "A,あ,,内装,仕上,100,0,0,,,,\n")
    with pytest.raises(PriceError, match="unit"):
        price.load(p, t)


def test_コードの重複は断る(tmp_path):
    p, t = write(tmp_path, "A,あ,㎡,内装,仕上,100,0,0,,,,\nA,い,㎡,内装,仕上,200,0,0,,,,\n")
    with pytest.raises(PriceError, match="重複"):
        price.load(p, t)


def test_不備は全部ためてから投げる(tmp_path):
    p, t = write(tmp_path, ",あ,㎡,内装,仕上,100,0,0,,,,\n"
                           "B,い,,内装,仕上,100,0,0,,,,\n"
                           "C,う,㎡,内装,仕上,-5,0,0,,,,\n")
    with pytest.raises(PriceError) as e:
        price.load(p, t)
    assert len(e.value.reasons) == 3


def test_列が足りなければ列の名前を出す(tmp_path):
    p, t = write(tmp_path, "A,あ,㎡\n", head="code,name,unit\n")
    with pytest.raises(PriceError, match="division"):
        price.load(p, t)
