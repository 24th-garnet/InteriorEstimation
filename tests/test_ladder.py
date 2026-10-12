"""段の積み方。**計算の規約を直したら落ちる**ように書く。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from estimate import breakdown, ladder, markup, price, quantity
from estimate.ladder import LadderError

from .conftest import EXAMPLES

D = Decimal


#: 段の積み方を検算するための固定の明細。**見本とは切り離す。**
#:
#: 課税 1,293,233 / 非課税 32,000 / 不課税 18,000 をそのまま作る。見本の中身が
#: 変わっても、ここの数字は動かない。「数字を直したら落ちる」ようにしたいのは
#: **規約**であって、見本ではない。
FIXED_PRICES = """\
code,name,unit,division,section,material,loss,labor,trade,tax
A,工事,式,内装工事,仕上,1293233,0,0,,課税
B,保険料,式,諸費用,保険,32000,0,0,,非課税
C,立替金,式,諸費用,立替金,18000,0,0,,不課税
"""


@pytest.fixture(scope="module")
def fixed_est(tmp_path_factory):
    d = tmp_path_factory.mktemp("fixed")
    (d / "p.csv").write_text(FIXED_PRICES, encoding="utf-8")
    (d / "t.csv").write_text("trade,name,daily\n内装工,内装工,24000\n",
                             encoding="utf-8")
    book = price.load(d / "p.csv", d / "t.csv")
    sheet = quantity.parse({"scan_id": "s", "name": "n", "items": [
        {"code": "A", "qty": 1}, {"code": "B", "qty": 1}, {"code": "C", "qty": 1}]})
    return breakdown.build(sheet, book)


def table(body: str, tmp_path, tax: str = "消費税,,消費税,課税,0.10,,,,,\n"):
    p = tmp_path / "m.csv"
    p.write_text("kind,stage,name,base,rate,amount,after,tax,source,as_of\n"
                 + body + tax, encoding="utf-8")
    return markup.load(p)


def three():
    return markup.load(EXAMPLES / "markup.csv")


def q(est, m=None, discount=None):
    return ladder.build(est, m if m is not None else three(), discount)


# --- 段と丸め -----------------------------------------------------------

def test_段は基数に率を掛けて円未満を切り捨てる(fixed_est):
    # 1,293,233 × 0.062 = 80,180.446
    assert q(fixed_est).steps[0].amount == D("80180")


def test_累計は丸め済みの段を足すだけ(fixed_est):
    s = q(fixed_est).steps
    assert s[0].running == D("1373413")          # 1,293,233 + 80,180
    assert s[1].running == D("1503887")          # 1,373,413 + 130,474


def test_基数は直前の累計になる(fixed_est):
    s = q(fixed_est).steps
    assert s[1].base == D("1373413")
    assert s[1].base_name == markup.RUNNING


def test_基数を直接工事費に戻せる(fixed_est, tmp_path):
    m = table("経費,1,あ,直接工事費,0.10,,,,,\n"
              "経費,2,い,直接工事費,0.10,,工事価格,,,\n", tmp_path)
    s = q(fixed_est, m).steps
    assert s[0].base == s[1].base == D("1293233")


def test_共通費の_3_段で工事価格が_1_627_205_になる(fixed_est):
    assert q(fixed_est).works == D("1627205")


def test_民間の諸経費_1_段でも積める(fixed_est, tmp_path):
    m = table("経費,1,諸経費,直接工事費,0.15,,工事価格,,,\n", tmp_path)
    x = q(fixed_est, m)
    assert x.steps[0].amount == D("193984")      # 1,293,233 × 0.15 = 193,984.95
    assert x.works == D("1487217")


def test_率は丸めない(fixed_est):
    assert q(fixed_est).steps[0].rate == D("0.062")


def test_段の金額の和が工事価格と課税分の差に一致する(fixed_est):
    x = q(fixed_est)
    assert sum((s.amount for s in x.steps), D(0)) == x.works - x.direct_taxable


def test_基数を残すので後から検算できる(fixed_est):
    # 率だけ残しても「この 130,474 は何に掛けたのか」が分からない
    s = q(fixed_est).steps[1]
    assert s.base * s.rate == D("130474.235")


# --- 税区分 -------------------------------------------------------------

def test_率の基数は課税分だけ(fixed_est):
    # 明細の合計は 1,343,233 だが、基数は課税分の 1,293,233
    assert q(fixed_est).direct_taxable == D("1293233")
    assert fixed_est.amount == D("1343233")


def test_非課税と不課税は素通りして税抜合計に合流する(fixed_est):
    x = q(fixed_est)
    assert x.untaxed == {"非課税": D("32000"), "不課税": D("18000")}
    assert x.subtotal == x.taxable + D("50000")


def test_不課税の固定額の段は累計に入らない(fixed_est, tmp_path):
    # 確認申請手数料のような実費。立替に利益を乗せない
    m = table("経費,1,あ,直接工事費,0.10,,工事価格,,,\n"
              "経費,2,確認申請手数料,,,18000,,不課税,,\n", tmp_path)
    x = q(fixed_est, m)
    assert x.steps[1].amount == D("18000")
    assert x.steps[1].running == x.steps[0].running   # 累計は増えない
    assert x.untaxed["不課税"] == D("36000")          # 明細の 18,000 と合流


def test_消費税は課税分にだけ掛かる(fixed_est):
    # 非課税 32,000 と不課税 18,000 には掛からない。1,627,205 × 10% = 162,720.5
    x = q(fixed_est)
    assert [(t.on, t.amount) for t in x.taxes] == [("課税", D("162720"))]
    assert x.total == x.taxable + D("50000") + D("162720")


def test_消費税の基数は値引き後の額(fixed_est):
    x = q(fixed_est, discount=quantity.Discount("値引き", amount=D("27205")))
    assert x.taxes[0].base == D("1600000")
    assert x.taxes[0].amount == D("160000")


def test_消費税の行が無ければ税込を出さない(fixed_est, tmp_path):
    m = table("経費,1,諸経費,直接工事費,0.15,,工事価格,,,\n", tmp_path, tax="")
    x = q(fixed_est, m)
    assert x.taxed is False
    assert x.total == x.subtotal


def test_段が無ければ工事価格は明細の課税分(fixed_est, tmp_path):
    assert q(fixed_est, markup.EMPTY).works == D("1293233")


# --- 値引き -------------------------------------------------------------

def test_値引きは課税分から引く(fixed_est):
    x = q(fixed_est, discount=quantity.Discount("値引き", amount=D("27205")))
    assert x.taxable == D("1600000")
    assert x.untaxed == {"非課税": D("32000"), "不課税": D("18000")}


def test_端数調整は税込をちょうどに合わせる(fixed_est):
    x = q(fixed_est, discount=quantity.Discount("端数", target=D("1810000")))
    assert x.cut.amount == D("27205")
    assert x.total == D("1810000")


def test_端数調整は税抜にも合わせられる(fixed_est):
    x = q(fixed_est, discount=quantity.Discount("端数", target=D("1650000"), basis="税抜"))
    assert x.subtotal == D("1650000")


def test_端数調整で到達できない額は断る(fixed_est):
    # X を 1 増やすと税込は 1 か 2 増える。1,810,010 は存在しない
    with pytest.raises(LadderError, match="1,810,009 か 1,810,011"):
        q(fixed_est, discount=quantity.Discount("端数", target=D("1810010")))


def test_値引きが工事価格を超えたら断る(fixed_est):
    with pytest.raises(LadderError, match="超えて"):
        q(fixed_est, discount=quantity.Discount("値引き", amount=D("9999999")))


def test_値上げになる端数調整は断る(fixed_est):
    with pytest.raises(LadderError, match="値上げ"):
        q(fixed_est, discount=quantity.Discount("端数", target=D("9999999"), basis="税抜"))


# --- 全体 ---------------------------------------------------------------

def test_税込合計は段と値引きと消費税の和に一致する(fixed_est):
    x = q(fixed_est, discount=quantity.Discount("端数", target=D("1810000")))
    built = (x.direct_taxable
             + sum((s.amount for s in x.steps), D(0))
             - x.cut.amount
             + sum(x.untaxed.values(), D(0))
             + x.tax_total)
    assert built == x.total == D("1810000")


def test_積み上げの通し(fixed_est):
    x = q(fixed_est, discount=quantity.Discount("端数お値引き", target=D("1810000")))
    assert (x.direct_taxable, x.works, x.taxable,
            x.tax_total, x.subtotal, x.total) == \
        (D("1293233"), D("1627205"), D("1600000"),
         D("160000"), D("1650000"), D("1810000"))
