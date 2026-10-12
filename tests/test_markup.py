"""経費表の読み込みと検証。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from estimate import markup
from estimate.markup import MarkupError

from .conftest import EXAMPLES

HEAD = "kind,stage,name,base,rate,amount,after,tax,source,as_of\n"
TAX = "消費税,,消費税,課税,0.10,,,,,\n"


def load(tmp_path, body: str, tax: str = TAX):
    p = tmp_path / "m.csv"
    p.write_text(HEAD + body + tax, encoding="utf-8")
    return markup.load(p)


def bad(tmp_path, body: str, tax: str = TAX):
    p = tmp_path / "m.csv"
    p.write_text(HEAD + body + tax, encoding="utf-8")
    with pytest.raises(MarkupError) as e:
        markup.load(p)
    return e.value


def test_見本の経費表が読める():
    m = markup.load(EXAMPLES / "markup.csv")
    assert [s.name for s in m.stages] == ["共通仮設費", "現場管理費", "一般管理費等"]
    assert m.rate_for("課税") == Decimal("0.10")
    assert m.stages[0].as_of == date(2026, 4, 1)


def test_段の順は_stage_の番号で決まる(tmp_path):
    # 並べ替えても番号どおりに積む。**ラダーの順は金額を変える**
    m = load(tmp_path, "経費,2,い,累計,0.10,,,,,\n経費,1,あ,直接工事費,0.10,,,,,\n")
    assert [s.name for s in m.stages] == ["あ", "い"]


def test_段番号が飛んでいたら断る(tmp_path):
    e = bad(tmp_path, "経費,1,あ,直接工事費,0.1,,,,,\n経費,3,い,累計,0.1,,,,,\n")
    assert "連番" in str(e)


def test_段番号が重複していたら断る(tmp_path):
    assert "連番" in str(bad(tmp_path, "経費,1,あ,直接工事費,0.1,,,,,\n"
                              "経費,1,い,累計,0.1,,,,,\n"))


def test_率と額の両方は書けない(tmp_path):
    assert "両方" in str(bad(tmp_path, "経費,1,あ,直接工事費,0.1,5000,,,,\n"))


def test_率も額も無い段は断る(tmp_path):
    assert "rate も amount も無い" in str(bad(tmp_path, "経費,1,あ,直接工事費,,,,,,\n"))


def test_知らない基数は断る(tmp_path):
    assert "基数" in str(bad(tmp_path, "経費,1,あ,工事原価,0.1,,,,,\n"))


def test_最初の段に累計は使えない(tmp_path):
    # 足す前の累計は無い
    assert "足す前の累計は無い" in str(bad(tmp_path, "経費,1,あ,累計,0.1,,,,,\n"))


def test_率の段は課税だけ(tmp_path):
    # 立替金に利益を乗せた瞬間に立替ではなくなる
    e = bad(tmp_path, "経費,1,あ,直接工事費,0.1,,,不課税,,\n")
    assert "率の段なので税区分は課税だけ" in str(e)


def test_固定額の段は非課税や不課税を名乗れる(tmp_path):
    m = load(tmp_path, "経費,1,あ,直接工事費,0.1,,,,,\n"
                       "経費,2,確認申請手数料,,,18000,,不課税,,\n")
    assert m.stages[1].fixed is True
    assert m.stages[1].tax == "不課税"


def test_固定額の段に基数は書けない(tmp_path):
    assert "基数は書けない" in str(bad(tmp_path, "経費,1,あ,累計,,5000,,,,\n"))


def test_負の率は置けない(tmp_path):
    assert "0 と 1 の間" in str(bad(tmp_path, "経費,1,あ,直接工事費,-0.1,,,,,\n"))


def test_1_を超える率は置けない(tmp_path):
    assert "0 と 1 の間" in str(bad(tmp_path, "経費,1,あ,直接工事費,1.5,,,,,\n"))


def test_知らない種別は断る(tmp_path):
    assert "kind" in str(bad(tmp_path, "値引き,1,あ,直接工事費,0.1,,,,,\n"))


def test_不備は全部ためてから投げる(tmp_path):
    e = bad(tmp_path, "経費,1,あ,工事原価,0.1,,,,,\n"
                      "経費,2,い,直接工事費,0.1,5000,,,,\n"
                      "値引き,3,う,直接工事費,0.1,,,,,\n")
    assert len(e.reasons) >= 3


def test_消費税の行に段番号は書けない(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text(HEAD + "消費税,1,消費税,課税,0.10,,,,,\n", encoding="utf-8")
    with pytest.raises(MarkupError, match="stage は書けない"):
        markup.load(p)


def test_同じ税区分に消費税の行が_2_行あれば断る(tmp_path):
    assert "2 行ある" in str(bad(tmp_path, "経費,1,あ,直接工事費,0.1,,,,,\n",
                                 tax=TAX + TAX))


def test_消費税は税区分ごとに引ける(tmp_path):
    # 軽減税率が要る日に行を 1 本足すだけで済む形にしてある
    m = load(tmp_path, "経費,1,あ,直接工事費,0.1,,,,,\n",
             tax=TAX + "消費税,,消費税,非課税,0.08,,,,,\n")
    assert m.rate_for("課税") == Decimal("0.10")
    assert m.rate_for("非課税") == Decimal("0.08")


def test_消費税の行が無ければ税率を持たない(tmp_path):
    m = load(tmp_path, "経費,1,あ,直接工事費,0.1,,,,,\n", tax="")
    assert m.rate_for("課税") is None


def test_経費表が無ければ段の無い表になる(tmp_path):
    assert markup.load(tmp_path / "nope.csv").empty is True


def test_経費表を明示したのに無ければ断る(tmp_path):
    # 「諸経費 0 円」と「付け忘れ」は見積書から区別が付かない
    with pytest.raises(MarkupError, match="経費表が無い"):
        markup.load(tmp_path / "nope.csv", required=True)


def test_列が足りなければ列の名前を出す(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text("kind,stage,name\n経費,1,あ\n", encoding="utf-8")
    with pytest.raises(MarkupError, match="after"):
        markup.load(p)


def test_率の出どころが書かれていない段を数える(tmp_path):
    m = load(tmp_path, "経費,1,あ,直接工事費,0.1,,,,,\n"
                       "経費,2,い,累計,0.1,,,,X,2026-04-01\n")
    assert [s.name for s in m.unsourced] == ["あ"]
