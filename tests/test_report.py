"""書き出し。**列がずれたら落ちる**ように書く。"""
from __future__ import annotations

import csv
import io
import json
from decimal import Decimal

from estimate import breakdown, price, quantity, report

from .conftest import EXAMPLES


def sample() -> breakdown.Estimate:
    book = price.load(EXAMPLES / "prices.csv", EXAMPLES / "trades.csv")
    return breakdown.build(quantity.load(EXAMPLES / "quantities.json"), book)


def test_全角を_2_で数える():
    assert report.width("クロス") == 6
    assert report.width("LED") == 3
    assert report.width("ダウンライト LED") == 16


def test_表示幅で揃える():
    assert report.width(report.pad("クロス", 10)) == 10
    assert report.width(report.pad("abc", 10)) == 10


def test_溢れたら切る():
    # 折り返すと行の対応が崩れる
    assert report.width(report.pad("あいうえおかきくけこ", 7)) <= 7


def test_数量は末尾の_0_を落とすが指数にしない():
    assert report.num(Decimal("48.600")) == "48.6"
    assert report.num(Decimal("1")) == "1"
    assert report.num(Decimal("1000")) == "1000"
    assert report.num(Decimal("0.250")) == "0.25"


def test_明細の列幅がそろう():
    lines = report.text(sample(), notes=False).splitlines()
    body = [l for l in lines
            if l.startswith(report.INDENT) and "└" not in l and l.strip()]
    assert len(body) >= 10
    widths = {report.width(l) for l in body}
    assert len(widths) == 1, f"行ごとに幅が違う: {widths}"


def test_小計のラベルが切れない():
    # 単価の欄に置くと「壁・天井仕上 計」が「壁・天井仕」になる
    out = report.text(sample())
    assert "壁・天井仕上 計" in out
    assert "電気設備工事 計" in out


def test_科目_中科目_細目_の_3_段で出る():
    lines = report.text(sample(), notes=False).splitlines()
    assert "内装工事" in lines
    assert "  壁・天井仕上" in lines
    assert any(l.startswith(report.INDENT + "量産クロス") for l in lines)


def test_頭書きが出る():
    out = report.text(sample())
    assert "見積番号 2026-1013-001" in out
    assert "発行 2026-10-13" in out
    assert "有効期限 2026-10-27" in out
    assert "見本 太郎 御中" in out


def test_頭書きが無ければそう言う():
    book = price.load(EXAMPLES / "prices.csv", EXAMPLES / "trades.csv")
    e = breakdown.build(quantity.parse(
        {"scan_id": "s", "name": "n", "items": [{"code": "WC-1000", "qty": 1}]}), book)
    assert "見積番号なし" in report.text(e)


def test_税区分ごとの小計が出る():
    out = report.text(sample())
    assert "税区分ごと" in out
    assert "非課税" in out and "不課税" in out


def test_合計とは名乗るが直接工事費とは名乗らない():
    # 諸費用の科目を単価表に置けるので、何が入っているか断定できない
    out = report.text(sample())
    assert "直接工事費" not in out


def test_単価の付かない行は表に出す():
    book = price.load(EXAMPLES / "prices.csv", EXAMPLES / "trades.csv")
    e = breakdown.build(quantity.parse(
        {"scan_id": "s", "name": "n",
         "items": [{"code": "WC-1000", "qty": 10}, {"code": "謎-9999", "qty": 2}]}), book)
    out = report.text(e)
    assert "謎-9999" in out
    assert "足りない" in out


def test_機械向けは金額を整数_数量を文字列で出す():
    d = report.as_dict(sample())
    assert isinstance(d["amount"], int)
    row = next(r for g in d["divisions"] for s in g["sections"]
               for r in s["rows"] if r["code"] == "WC-1000")
    assert row["qty"] == "48.6"
    assert isinstance(row["qty"], str)
    assert isinstance(row["material_unit"], int)


def test_機械向けに頭書きが入る():
    # 電子帳簿保存法の検索の手がかり（取引年月日・取引先・取引金額）
    d = report.as_dict(sample())
    assert d["estimate"]["number"] == "2026-1013-001"
    assert d["estimate"]["issued"] == "2026-10-13"
    assert d["estimate"]["client"] == "見本 太郎"
    assert d["amount"] == int(sample().amount)


def test_機械向けに税区分の小計が入る():
    d = report.as_dict(sample())
    assert set(d["by_tax"]) == {"課税", "非課税", "不課税"}
    assert sum(d["by_tax"].values()) == d["amount"]


def test_機械向けが_json_にできる():
    json.dumps(report.as_dict(sample()), ensure_ascii=False)


def test_機械向けの合計は行の和と一致する():
    d = report.as_dict(sample())
    rows = [r for g in d["divisions"] for s in g["sections"] for r in s["rows"]]
    assert d["amount"] == sum(r["amount"] for r in rows)


def test_csv_は明細だけで小計を入れない():
    # 小計を混ぜると、取り込んだ先で合計を取り直したとき二重に数える
    e = sample()
    rows = list(csv.DictReader(io.StringIO(report.csv_text(e))))
    assert len(rows) == len(e.rows)
    assert all(r["code"] for r in rows)
    assert sum(int(r["amount"]) for r in rows) == int(e.amount)


def test_csv_に科目_中科目_税区分_出典が入る():
    rows = list(csv.DictReader(io.StringIO(report.csv_text(sample()))))
    r = next(r for r in rows if r["code"] == "FL-2000")
    assert r["division"] == "内装工事"
    assert r["section"] == "床仕上"
    assert r["tax"] == "課税"
    assert r["source"] == "建設物価 2026-04"
    assert r["as_of"] == "2026-04-01"


# --- ラダー -------------------------------------------------------------

def quoted():
    from decimal import Decimal
    from estimate import ladder, markup
    e = sample()
    m = markup.load(EXAMPLES / "markup.csv")
    return e, ladder.build(e, m, quantity.load(EXAMPLES / "quantities.json").discount)


def test_経費表が無ければ明細の合計までで止まる():
    out = report.text(sample())
    assert "経費と消費税" not in out.splitlines()   # ラダーの見出し行
    assert "markup.csv を置くと" in out


def test_ラダーが端末に出る():
    e, q = quoted()
    out = report.text(e, quote=q)
    assert "経費と消費税" in out.splitlines()
    for word in ("純工事費", "工事原価", "工事価格", "課税対価の額", "見積合計（税込）"):
        assert word in out, word


def test_ラダーの基数は課税分と名乗る():
    # 単価表に課税の諸費用科目を置けるので「直接工事費」とは名乗れない
    e, q = quoted()
    out = report.text(e, quote=q)
    assert "課税分" in out
    assert "直接工事費" not in out.split("経費と消費税")[1].splitlines()[1]


def test_値引きが負の数で出る():
    e, q = quoted()
    assert f"-{int(q.cut.amount):,}" in report.text(e, quote=q)


def test_端数調整の根拠が添えられる():
    e, q = quoted()
    assert f"税込 {int(q.cut.target):,} ちょうどに合わせた" in report.text(e, quote=q)


def test_機械向けの明細合計は経費を足しても変わらない():
    e, q = quoted()
    assert report.as_dict(e, quote=q)["amount"] == int(e.amount)
    assert report.as_dict(e)["amount"] == int(e.amount)


def test_機械向けに_quote_が入る():
    e, q = quoted()
    d = report.as_dict(e, quote=q)["quote"]
    assert d["works"] == int(q.works) and d["taxable"] == int(q.taxable)
    assert d["total"] == int(q.total) and d["taxed"] is True
    # 税込合計が万円ちょうどに着地していること（端数調整が効いている）
    assert d["total"] % 10000 == 0


def test_機械向けの率は文字列で出す():
    e, q = quoted()
    step = report.as_dict(e, quote=q)["quote"]["steps"][0]
    assert step["rate"] == "0.062"
    assert isinstance(step["rate"], str)


def test_機械向けの段の累計で検算できる():
    e, q = quoted()
    steps = report.as_dict(e, quote=q)["quote"]["steps"]
    assert steps[1]["base_amount"] == steps[0]["running"]


def test_経費表が無ければ_quote_は_null():
    assert report.as_dict(sample())["quote"] is None


def test_csv_の金額の和が税込合計に一致する():
    e, q = quoted()
    rows = list(csv.DictReader(io.StringIO(report.csv_text(e, quote=q))))
    assert sum(int(r["amount"]) for r in rows) == int(q.total)


def test_csv_に節目の小計は入れない():
    # 小計を混ぜると、取り込んだ先で合計を取り直したとき二重に数える
    e, q = quoted()
    rows = list(csv.DictReader(io.StringIO(report.csv_text(e, quote=q))))
    names = {r["name"] for r in rows}
    assert not ({"純工事費", "工事原価", "工事価格", "課税対価の額"} & names)
