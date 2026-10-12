"""認定・等級の欄。**判定はしない。書いてあるかだけを見る。**

内装制限が掛かるかは建物の用途・規模・階数で決まり、このモジュールはそれを
知らない。だから語彙を固定して「何を名乗っているか」は決まるようにし、
「それが正しいか」は数えて人に見せるだけにする。
"""
from __future__ import annotations

import csv
import io

import pytest

from estimate import breakdown, price, quantity, report
from estimate.price import PriceError

from .conftest import EXAMPLES

HEAD = ("code,name,unit,division,section,material,loss,labor,trade,"
        "tax,source,as_of,fire,fire_no,f_star,flame,spec\n")


def write(tmp_path, body: str, head: str = HEAD):
    p, t = tmp_path / "p.csv", tmp_path / "t.csv"
    p.write_text(head + body, encoding="utf-8")
    t.write_text("trade,name,daily\n内装工,内装仕上工,24000\n", encoding="utf-8")
    return p, t


def item(tmp_path, tail: str):
    p, t = write(tmp_path, f"A,あ,㎡,内装,仕上,100,0,0,,課税,X,2026-04-01,{tail}\n")
    return price.load(p, t).items["A"]


def sample() -> breakdown.Estimate:
    """見本。**見本の回帰を見るテストだけが使う。**"""
    book = price.load(EXAMPLES / "prices.csv", EXAMPLES / "trades.csv")
    return breakdown.build(quantity.load(EXAMPLES / "quantities.json"), book)


#: 数え方を検算するための固定の表。**見本とは切り離す。**
FIXED = """\
code,name,unit,division,section,material,loss,labor,trade,tax,source,as_of,fire,fire_no,f_star,flame,spec
OK,全部書いた,㎡,内装,仕上,100,0,0,,課税,X,2026-04-01,準不燃,QM-1,F☆☆☆☆,対象外,W100×D200×H300
GAP,一部が空,㎡,内装,仕上,100,0,0,,課税,X,2026-04-01,,,F☆☆☆☆,,
NONE,全部空,㎡,内装,仕上,100,0,0,,課税,X,2026-04-01,,,,,
BAD,番号が食い違う,㎡,内装,仕上,100,0,0,,課税,X,2026-04-01,不燃,QM-9,F☆☆☆☆,対象外,
REI,例示仕様,㎡,内装,仕上,100,0,0,,課税,X,2026-04-01,不燃,令 108 条の 2 例示,規制対象外,対象外,
"""


@pytest.fixture(scope="module")
def fixed(tmp_path_factory) -> breakdown.Estimate:
    d = tmp_path_factory.mktemp("certs")
    (d / "p.csv").write_text(FIXED, encoding="utf-8")
    (d / "t.csv").write_text("trade,name,daily\n内装工,内装工,24000\n",
                             encoding="utf-8")
    book = price.load(d / "p.csv", d / "t.csv")
    sheet = quantity.parse({"scan_id": "s", "name": "n", "items": [
        {"code": c, "qty": 1} for c in ("OK", "GAP", "NONE", "BAD", "REI")]})
    return breakdown.build(sheet, book)


def test_認定の列は無くても読める(tmp_path):
    # 既にある表をそのまま読めないと、入れ替えが進まない
    head = ("code,name,unit,division,section,material,loss,labor,trade\n")
    p, t = write(tmp_path, "A,あ,㎡,内装,仕上,100,0,0,\n", head=head)
    i = price.load(p, t).items["A"]
    assert (i.fire, i.fire_no, i.f_star, i.flame, i.spec) == ("", "", "", "", "")


def test_不燃区分の語彙を固定する(tmp_path):
    assert item(tmp_path, "準不燃,QM-1,F☆☆☆☆,対象外,").fire == "準不燃"


def test_知らない不燃区分は断る(tmp_path):
    # 「不燃性」「準不燃相当」を黙って通すと、その行が何を名乗っているか決まらない
    p, t = write(tmp_path, "A,あ,㎡,内装,仕上,100,0,0,,課税,X,2026-04-01,不燃性,,,,\n")
    with pytest.raises(PriceError, match="不燃区分"):
        price.load(p, t)


def test_ホルムアルデヒド等級の語彙を固定する(tmp_path):
    assert item(tmp_path, ",,F☆☆☆,,").f_star == "F☆☆☆"


def test_全角の等級表記しか受けない(tmp_path):
    # 正規化すると「どう書いても通る」ことになり、表の中で表記が割れる
    p, t = write(tmp_path, "A,あ,㎡,内装,仕上,100,0,0,,課税,X,2026-04-01,,,F****,,\n")
    with pytest.raises(PriceError, match="ホルムアルデヒド"):
        price.load(p, t)


def test_規制対象外と無等級は別のもの(tmp_path):
    # 前者は告示の対象建材でない、後者は第一種発散建築材料で原則使えない
    assert item(tmp_path, ",,規制対象外,,").f_star == "規制対象外"
    assert item(tmp_path, ",,無等級,,").f_star == "無等級"


def test_防炎の語彙を固定する(tmp_path):
    assert item(tmp_path, ",,,防炎,").flame == "防炎"
    p, t = write(tmp_path, "A,あ,㎡,内装,仕上,100,0,0,,課税,X,2026-04-01,,,,防炎物品,\n")
    with pytest.raises(PriceError, match="防炎"):
        price.load(p, t)


def test_認定番号は自由記述で検証しない(tmp_path):
    # 令 108 条の 2 の例示仕様は認定番号を持たない。形を強制すると通らなくなる
    assert item(tmp_path, "不燃,令 108 条の 2 例示,,,").fire_no == "令 108 条の 2 例示"


def test_寸法仕様は自由記述(tmp_path):
    assert item(tmp_path, ",,,,W2209×D895×H768").spec == "W2209×D895×H768"


def test_認定の不備も全部ためてから投げる(tmp_path):
    p, t = write(tmp_path,
                 "A,あ,㎡,内装,仕上,100,0,0,,課税,X,2026-04-01,不燃性,,,,\n"
                 "B,い,㎡,内装,仕上,100,0,0,,課税,X,2026-04-01,,,F4,,\n"
                 "C,う,㎡,内装,仕上,100,0,0,,課税,X,2026-04-01,,,,もえない,\n")
    with pytest.raises(PriceError) as e:
        price.load(p, t)
    assert len(e.value.reasons) == 3


# --- 運ばれ方と数え方 ---------------------------------------------------

def test_認定と等級が行まで運ばれる(fixed):
    r = next(r for r in fixed.rows if r.code == "OK")
    assert (r.fire, r.fire_no, r.f_star, r.flame) == ("準不燃", "QM-1", "F☆☆☆☆", "対象外")


def test_対象外と書いた欄は空欄に数えない(fixed):
    # 当たらないと判断したことが書いてあるので、見ていないのとは別
    r = next(r for r in fixed.rows if r.code == "OK")
    assert r.blank_grades == () and r.graded is True


def test_どの欄が空いているかを欄の名前で返す(fixed):
    # 3 つは別の法令。件数だけでは、どれを見ていないのか直しようがない
    rows = {r.code: r for r in fixed.rows}
    assert rows["GAP"].blank_grades == ("不燃区分", "防炎")
    assert rows["NONE"].blank_grades == ("不燃区分", "ホルムアルデヒド等級", "防炎")


def test_空欄の行だけを数える(fixed):
    assert [r.code for r in fixed.ungraded] == ["GAP", "NONE"]


def test_認定番号と不燃区分の食い違いを数える(fixed):
    # 不燃なのに QM-（準不燃）の番号。**断らずに数える**
    assert [r.code for r in fixed.mismatched] == ["BAD"]
    assert fixed.mismatched[0].cert_mismatch == "不燃 と QM-9"


def test_認定番号が空なら食い違いを言わない(fixed):
    assert next(r for r in fixed.rows if r.code == "NONE").cert_mismatch == ""


def test_知らない接頭辞では食い違いを言わない(fixed):
    # 令 108 条の 2 例示・旧書式・自社表記を拾わない
    r = next(r for r in fixed.rows if r.code == "REI")
    assert r.fire == "不燃" and r.fire_no.startswith("令")
    assert r.cert_mismatch == ""


def test_認定が空でも合計は変わらない(fixed):
    assert fixed.amount == 500          # 100 円 × 5 行


# --- 出し方 -------------------------------------------------------------

def test_認定欄の空いている行を表に出す(fixed):
    out = report.text(fixed)
    assert "認定・等級の欄が空いている行が 2 件ある" in out
    assert "判定できない" in out


def test_報告に対象外と書けと書いてある(fixed):
    # 直し方を知らないと直せない報告は、誰も直さない
    assert "「対象外」と書く" in report.text(fixed)


def test_食い違いを表に出す(fixed):
    assert "不燃 と QM-9" in report.text(fixed)


def test_寸法仕様が明細の下に出る(fixed):
    assert "└ W100×D200×H300" in report.text(fixed)


def test_機械向けの行に認定と等級が入る(fixed):
    d = report.as_dict(fixed)
    row = next(r for g in d["divisions"] for s in g["sections"]
               for r in s["rows"] if r["code"] == "OK")
    assert row["fire"] == "準不燃" and row["fire_no"] == "QM-1"
    assert row["f_star"] == "F☆☆☆☆" and row["flame"] == "対象外"


def test_csv_に認定と等級が入り_note_は最後の列のまま(fixed):
    rows = list(csv.DictReader(io.StringIO(report.csv_text(fixed))))
    assert report.CSV_COLUMNS[-1] == "note"
    r = next(r for r in rows if r["code"] == "OK")
    assert r["fire"] == "準不燃" and r["spec"] == "W100×D200×H300"
