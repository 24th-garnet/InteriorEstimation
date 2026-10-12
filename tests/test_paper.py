"""客先に出す見積書。**出せない状態なら紙にそう書く**ことを固定する。"""
from __future__ import annotations

import re
from decimal import Decimal

import pytest

from estimate import breakdown, ladder, markup, paper, price, quantity

from .conftest import EXAMPLES


def sample():
    book = price.load(EXAMPLES / "prices.csv", EXAMPLES / "trades.csv")
    sheet = quantity.load(EXAMPLES / "quantities.json")
    est = breakdown.build(sheet, book)
    m = markup.load(EXAMPLES / "markup.csv")
    return est, ladder.build(est, m, sheet.discount)


def text_of(html: str) -> str:
    """タグを落とした本文。見た目ではなく**載っているか**を見る。"""
    body = html.split("<body>")[1]
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))


# --- 発行者 -------------------------------------------------------------

def test_見本に発行者が入っている():
    h = quantity.load(EXAMPLES / "quantities.json").header
    assert h.issuer.name == "見本内装 株式会社"
    assert h.issuer.registration == "T0000000000000"


def test_発行者が無ければ客先に出せないと判定する():
    h = quantity.parse({"scan_id": "s", "name": "n",
                        "items": [{"code": "A", "qty": 1}],
                        "estimate": {"number": "X", "issued": "2026-10-13"}}).header
    assert h.identified is True        # 見積りとしては特定できる
    assert h.deliverable is False      # だが客先には出せない


def test_発行者を書くなら社名が要る():
    with pytest.raises(quantity.QuantityError, match="誰が出した見積りか"):
        quantity.parse({"scan_id": "s", "name": "n",
                        "items": [{"code": "A", "qty": 1}],
                        "estimate": {"number": "X", "issued": "2026-10-13",
                                     "issuer": {"tel": "03-0000-0000"}}})


def test_発行者は省略できる():
    h = quantity.parse({"scan_id": "s", "name": "n",
                        "items": [{"code": "A", "qty": 1}]}).header
    assert h.issuer.named is False


def test_登録番号の形は検査しない():
    # 形が変わる可能性のあるものを、こちらが決め打ちで断るべきではない
    h = quantity.parse({"scan_id": "s", "name": "n",
                        "items": [{"code": "A", "qty": 1}],
                        "estimate": {"number": "X", "issued": "2026-10-13",
                                     "issuer": {"name": "あ", "registration": "123"}}}).header
    assert h.issuer.registration == "123"


# --- 紙面 ---------------------------------------------------------------

def test_発行者と宛先が両方載る():
    est, q = sample()
    t = text_of(paper.html_sheet(est, quote=q))
    assert "見本内装 株式会社" in t
    assert "見本 太郎 御中" in t


def test_見積番号と発行日と有効期限が載る():
    est, q = sample()
    t = text_of(paper.html_sheet(est, quote=q))
    for word in ("見積番号 2026-1013-001", "発行日 2026-10-13", "有効期限 2026-10-27"):
        assert word in t, word


def test_合計を頭に大きく出す():
    est, q = sample()
    html = paper.html_sheet(est, quote=q)
    head = html.split("<table>")[0]
    assert f"¥{int(q.total):,}" in head


def test_科目と中科目と細目の_3_段で出る():
    est, q = sample()
    html = paper.html_sheet(est, quote=q)
    assert 'class="division"' in html
    assert 'class="section"' in html
    assert 'class="item"' in html


def test_ラダーが載る():
    est, q = sample()
    t = text_of(paper.html_sheet(est, quote=q))
    for word in ("純工事費", "工事原価", "工事価格", "課税対価の額", "見積合計"):
        assert word in t, word


def test_経費表が無ければラダーを出さない():
    est, _ = sample()
    t = text_of(paper.html_sheet(est))
    assert "純工事費" not in t
    assert "合計" in t


def test_発行者が無ければ紙にそう書く():
    # **黙って出さない。** 出せない状態のまま印刷されるのが一番困る
    est, q = sample()
    bare = breakdown.Estimate(est.scan_id, est.name, quantity.Header(),
                              est.divisions, est.unknown)
    t = text_of(paper.html_sheet(bare, quote=q))
    assert "発行者が未記入" in t


def test_単価の付かない行があれば紙にそう書く():
    book = price.load(EXAMPLES / "prices.csv", EXAMPLES / "trades.csv")
    est = breakdown.build(quantity.parse(
        {"scan_id": "s", "name": "n",
         "items": [{"code": "WC-1000", "qty": 10}, {"code": "謎-9", "qty": 1}]}), book)
    assert "合計はその分だけ足りません" in text_of(paper.html_sheet(est))


def test_認定の空欄があれば紙にそう書く():
    est, q = sample()
    t = text_of(paper.html_sheet(est, quote=q))
    assert "認定・等級の欄が空いている" in t
    assert "判定していません" in t


def test_不備が無ければ注意書きを出さない():
    book = price.load(EXAMPLES / "prices.csv", EXAMPLES / "trades.csv")
    sheet = quantity.load(EXAMPLES / "quantities.json")
    est = breakdown.build(quantity.parse(
        {"scan_id": "s", "name": "n", "estimate": {
            "number": "X", "issued": "2026-10-13",
            "issuer": {"name": "あ"}},
         "items": [{"code": "DR-0100", "qty": 1}]}), book)
    assert 'class="caution"' not in paper.html_sheet(est)


def test_品目名を_html_として埋め込まない():
    # 品目名は単価表から来る。山括弧が入っていても紙が壊れないこと
    book = price.load(EXAMPLES / "prices.csv", EXAMPLES / "trades.csv")
    item = book.items["WC-1000"]
    book.items["WC-1000"] = type(item)(**{**item.__dict__, "name": "<script>x</script>"})
    est = breakdown.build(quantity.parse(
        {"scan_id": "s", "name": "n", "items": [{"code": "WC-1000", "qty": 1}]}), book)
    assert "<script>" not in paper.html_sheet(est)
    assert "&lt;script&gt;" in paper.html_sheet(est)


def test_実寸で印刷できる():
    # PDF は自前で書かない。ブラウザの「PDF として保存」に任せる
    est, q = sample()
    assert "@page { size: A4 portrait" in paper.html_sheet(est, quote=q)
