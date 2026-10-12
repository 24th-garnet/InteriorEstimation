"""数量 × 単価。**計算の規約を直したら落ちる**ように書く。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from estimate import breakdown, price, quantity

from .conftest import EXAMPLES

PRICES, TRADES = EXAMPLES / "prices.csv", EXAMPLES / "trades.csv"

#: 計算の規約を検算するための固定の表。**見本とは切り離す。**
#:
#: 「数字を直したら落ちる」ようにしたいのは**規約**であって、見本ではない。
#: 同じ表に乗せていると、見本を差し替えるたびに規約の検算が巻き添えで落ち、
#: 本当に規約が変わったのかが分からなくなる。
FIXED_PRICES = """\
code,name,unit,division,section,material,loss,labor,trade,tax
H1,撤去,㎡,内装工事,下地・撤去,0,0,0.04,内装工,課税
W1,壁紙,㎡,内装工事,壁・天井仕上,450,0.05,0.10,内装工,課税
W2,天井材,㎡,内装工事,壁・天井仕上,1200,0.05,0.12,内装工,課税
F1,床材,㎡,内装工事,床仕上,4200,0.05,0.25,大工,課税
F2,床シート,㎡,内装工事,床仕上,1800,0.08,0.15,内装工,課税
D1,ドア,箇所,建具工事,木製建具,42000,0,0.8,建具工,課税
L1,照明,台,電気設備工事,照明器具,4800,0,0.25,電工,課税
G1,家具,本,家具工事,置き家具,89000,0,0.5,家具工,課税
G2,敷物,枚,家具工事,置き家具,18000,0,0,,課税
I1,保険料,式,諸費用,保険,32000,0,0,,非課税
I2,立替金,式,諸費用,立替金,18000,0,0,,不課税
"""

FIXED_TRADES = """\
trade,name,daily
内装工,内装仕上工,24000
大工,大工,26000
建具工,建具工,25000
電工,電気工事士,27000
家具工,家具設置,20000
"""


@pytest.fixture(scope="module")
def fixed(tmp_path_factory):
    d = tmp_path_factory.mktemp("fixed")
    (d / "p.csv").write_text(FIXED_PRICES, encoding="utf-8")
    (d / "t.csv").write_text(FIXED_TRADES, encoding="utf-8")
    return price.load(d / "p.csv", d / "t.csv")


def book():
    """見本の表。**見本の回帰を見るテストだけが使う。**"""
    return price.load(PRICES, TRADES)


def est(items, bk=None):
    return breakdown.build(
        quantity.parse({"scan_id": "s", "name": "n", "items": items}),
        bk if bk is not None else book())


def only_row(items, bk=None) -> breakdown.Row:
    return est(items, bk).rows[0]


def test_ロスは材料にだけ掛かり_手間には掛からない(fixed):
    # 切り代で材料は余分に要るが、張る手間は増えない
    r = only_row([{"code": "W1", "qty": 100}], fixed)
    assert r.qty_with_loss == Decimal("105.00")      # 100 × 1.05
    assert r.material == Decimal("47250")            # 105 × 450
    assert r.days == Decimal("10.00")                # 100 × 0.10（ロスを掛けない）
    assert r.labor == Decimal("240000")              # 100 × 0.10 × 24,000


def test_人工は丸めない(fixed):
    # 0.25 人工を切り上げると、台数の多い照明で手間が倍になる
    r = only_row([{"code": "L1", "qty": 1}], fixed)
    assert r.days == Decimal("0.25")


def test_金額は円未満を切り捨てる(fixed):
    # 3.2 × 1.08 × 1800 = 6,220.8
    r = only_row([{"code": "F2", "qty": 3.2}], fixed)
    assert r.material == Decimal("6220")


def test_合計は行の和と一致する(fixed):
    e = est([{"code": "W1", "qty": 48.6}, {"code": "F1", "qty": 19.4},
             {"code": "D1", "qty": 2}], fixed)
    assert e.amount == sum((r.amount for r in e.rows), Decimal(0))
    assert e.amount == e.material + e.labor


def test_小計は段ごとに行の和と一致する(fixed):
    e = est([{"code": "W1", "qty": 48.6}, {"code": "F1", "qty": 19.4},
             {"code": "D1", "qty": 2}], fixed)
    for d in e.divisions:
        assert d.amount == sum((s.amount for s in d.sections), Decimal(0))
        for s in d.sections:
            assert s.amount == sum((r.amount for r in s.rows), Decimal(0))
    assert e.amount == sum((d.amount for d in e.divisions), Decimal(0))


def test_科目と中科目の_3_段で積む(fixed):
    e = est([{"code": "H1", "qty": 10}, {"code": "W1", "qty": 10},
             {"code": "F1", "qty": 10}], fixed)
    assert [d.name for d in e.divisions] == ["内装工事"]
    assert [s.name for s in e.divisions[0].sections] == \
        ["下地・撤去", "壁・天井仕上", "床仕上"]


def test_税区分ごとに小計が出る(fixed):
    e = est([{"code": "W1", "qty": 10}, {"code": "I1", "qty": 1},
             {"code": "I2", "qty": 1}], fixed)
    by = e.by_tax
    assert set(by) == {"課税", "非課税", "不課税"}
    assert by["非課税"] == Decimal("32000")
    assert by["不課税"] == Decimal("18000")
    assert sum(by.values()) == e.amount


def test_使われなかった税区分は出さない(fixed):
    assert set(est([{"code": "W1", "qty": 10}], fixed).by_tax) == {"課税"}


def test_出どころの無い行を数える(fixed):
    # 固定の表には source を書いていないので、全部が出どころ無しになる
    assert len(est([{"code": "W1", "qty": 10}], fixed).unsourced) == 1


def test_単価の無いコードは落とさずに残す(fixed):
    # 黙って落とすと合計だけが静かに小さくなる
    e = est([{"code": "W1", "qty": 10}, {"code": "謎-9999", "qty": 3, "note": "？"}], fixed)
    assert [u.code for u in e.unknown] == ["謎-9999"]
    assert e.unknown[0].qty == Decimal("3")
    assert e.complete is False


def test_全部に単価が付けば_complete(fixed):
    assert est([{"code": "W1", "qty": 10}], fixed).complete is True


def test_科目の並びは単価表に出てきた順(fixed):
    # 名前順にすると、表を組んだ人が意図した工事の順が崩れる
    e = est([{"code": "G1", "qty": 1}, {"code": "L1", "qty": 1},
             {"code": "W1", "qty": 1}], fixed)
    assert [d.name for d in e.divisions] == ["内装工事", "電気設備工事", "家具工事"]


def test_行の並びは数量リストの順を保つ(fixed):
    e = est([{"code": "F2", "qty": 1}, {"code": "F1", "qty": 1}], fixed)
    assert [r.code for r in e.rows] == ["F2", "F1"]


def test_材料費_0_の品目も行として残る(fixed):
    # 撤去は手間だけ。材料 0 で消えてはいけない
    r = only_row([{"code": "H1", "qty": 62.4}], fixed)
    assert r.material == 0
    assert r.labor == Decimal("59904")               # 62.4 × 0.04 × 24,000


def test_職種の無い品目は施工費_0(fixed):
    r = only_row([{"code": "G2", "qty": 1}], fixed)
    assert r.labor == 0
    assert r.amount == Decimal("18000")


def test_頭書きが明細まで運ばれる():
    e = breakdown.build(quantity.load(EXAMPLES / "quantities.json"), book())
    assert e.header.number == "2026-1013-001"
    assert e.header.identified is True


def test_単価の出どころが行まで運ばれる():
    # これは見本を見る（見本には出どころが書いてある）
    r = only_row([{"code": "FL-2000", "qty": 1}])
    assert r.source == "建設物価 2026-04"
    assert r.sourced is True


def test_見本一式が筋の通った明細になる():
    """見本は生成物なので**金額を固定しない。**整合性だけを見る。

    金額を書くと、見本を作り直すたびにここを書き換えることになり、
    「数字を直したら落ちる」はずのテストが「見本を変えたら落ちる」テストになる。
    """
    e = breakdown.build(quantity.load(EXAMPLES / "quantities.json"), book())
    assert e.complete is True
    assert e.unsourced == ()
    assert e.amount == e.material + e.labor
    assert e.amount == sum((r.amount for r in e.rows), Decimal(0))
    assert sum(e.by_tax.values(), Decimal(0)) == e.amount
    # 置き方が科目を分けていること（家具が 1 つの科目に固まらない）
    assert len(e.divisions) >= 4
