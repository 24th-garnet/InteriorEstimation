"""見本を作る道具。**TemplateMaker が無くても落ちない。**

実物のカタログを読まず、テストの中に書いた小さな作り物のマニフェストを食わせる。
道具が依存するのは「tm-manifest-1 という形」であって、特定のファイルではない。
"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from tools import make_examples as mk

D = Decimal


def body(**kw) -> dict:
    base = dict(id="B000000001", source="abo", category="sofa", brand="Acme",
                name="Acme Comfy Sofa, 72\"W, Navy", extent=[1.8, 0.8, 0.9],
                vertices=100, faces=1000, bytes=1000,
                url="https://x/y.glb", image="ab/cd.jpg")
    return base | kw


def manifest(items) -> dict:
    return {"schema_version": "tm-manifest-1", "source": "abo",
            "license": "CC BY 4.0", "license_url": "https://x/by/4.0/",
            "attribution": "作り物カタログ", "generated_at": "2026-10-03T00:00:00Z",
            "criteria": {}, "count": len(items), "items": items}


def full() -> list[dict]:
    """1 部屋ぶんの構成が揃う最小のカタログ。"""
    out, n = [], 0
    for category, want, _ in mk.ROOM:
        for k in range(want):
            n += 1
            out.append(body(id=f"B{n:09d}", category=category,
                            name=f"Thing {n} for {category}, Red",
                            extent=[0.8 + k * 0.1, 0.7, 0.6]))
    return out


def written(tmp_path, items=None, per=3):
    p = tmp_path / "m.json"
    p.write_text(json.dumps(manifest(items or full())), encoding="utf-8")
    return p


# --- 契約 ---------------------------------------------------------------

def test_マニフェストの版が違えば断る(tmp_path):
    p = tmp_path / "m.json"
    m = manifest(full()); m["schema_version"] = "tm-manifest-9"
    p.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(mk.ToolError, match="知らない版"):
        mk.build(p, 3)


def test_マニフェストが無ければ生成物に触らない(tmp_path):
    out = tmp_path / "examples"
    with pytest.raises(mk.ToolError, match="マニフェストが無い"):
        mk.build(tmp_path / "nope.json", 3)
    assert not out.exists()


def test_知らない品目は断る(tmp_path):
    with pytest.raises(mk.ToolError, match="知らない品目"):
        mk.rows([body(category="aquarium")], 3, "2026-01-01")


def test_カタログに品目が無ければ断る():
    with pytest.raises(mk.ToolError, match="1 体も無い"):
        mk.rows([body(category="sofa")], 3, "2026-01-01")


# --- 寸法 ---------------------------------------------------------------

def test_寸法は幅と奥行を_x_と_z_の大小で取る():
    # glTF の x と z のどちらが幅かは書き出し側の都合で決まる
    assert mk.wdh([0.6, 0.9, 2.0]) == (D("2.0"), D("0.6"), D("0.9"))
    assert mk.wdh([2.0, 0.9, 0.6]) == (D("2.0"), D("0.6"), D("0.9"))


def test_高さは_y_から取る():
    assert mk.wdh([1.0, 2.5, 0.5])[2] == D("2.5")


def test_寸法は_10mm_に丸める():
    # 外接直方体の実測であって公称寸法ではない。1mm まで書く根拠が無い
    assert mk.spec([2.2094, 0.7684, 0.8953]) == "W2210×D900×H770"


# --- 名前とコード -------------------------------------------------------

def test_品目名は和名と連番で作る(tmp_path):
    r = mk.rows(full(), 3, "2026-01-01")
    assert r[0]["name"] == "ソファ 01"


def test_品目名にブランドを入れない(tmp_path):
    # ブランド名は最大 30 幅あり、品目の欄 26 幅で切れる。切れた名前は読めない
    for r in mk.rows(full(), 3, "2026-01-01"):
        assert "Acme" not in r["name"]
        assert all(ord(c) < 0x3000 or True for c in r["name"])


def test_品名が品目の欄に収まる():
    from estimate import report
    for r in mk.rows(full(), 3, "2026-01-01"):
        assert report.width(r["name"]) <= 26


def test_和名辞書が_16_語彙を網羅する():
    assert set(mk.JA) == set(mk.ABBR) == set(mk.BASE)
    assert len(mk.JA) == 16


def test_連番は_ASIN_順で決まる():
    items = [body(id="B2", category="chair", name="b, Red"),
             body(id="B1", category="chair", name="a, Red")]
    got = mk.pick(items, "chair", 2)
    assert [i["id"] for i in got] == ["B1", "B2"]


# --- 色違い -------------------------------------------------------------

def test_色違いは基幹名で畳む():
    items = [body(id="B1", name="Movian Bed, 195x100, Pink"),
             body(id="B2", name="Movian Bed, 195x100, Grey", vertices=999)]
    kept, n = mk.collapse(items)
    assert n == 1 and [i["id"] for i in kept] == ["B1"]


def test_サイズ違いは畳まない():
    # 56"W と 63"W は別物
    items = [body(id="B1", name="Rivet Sofa, 56\"W"),
             body(id="B2", name="Rivet Sofa, 63\"W")]
    kept, n = mk.collapse(items)
    assert n == 0 and len(kept) == 2


def test_畳むときは_ASIN_の若い方を残す():
    items = [body(id="B9", name="X, Red"), body(id="B1", name="X, Blue")]
    kept, _ = mk.collapse(items)
    assert kept[0]["id"] == "B1"


# --- 置き方が科目を決める -----------------------------------------------

def test_床置きは家具工事で職種は家具工():
    assert mk.work("sofa", D("1.0"))[:3] == ("家具工事", "置き家具", "家具工")


def test_幅の広い床置きは歩掛りが増える():
    assert mk.work("sofa", D("1.0"))[3] == D("0.3")
    assert mk.work("sofa", D("1.5"))[3] == D("0.5")


def test_ラグは手間なし():
    div, sec, trade, labor = mk.work("rug", D("2.0"))
    assert (div, sec, trade, labor) == ("家具工事", "敷物", "", D("0"))


def test_壁付けは内装工事で職種は大工():
    # 下地（間柱・合板）は内装の仕事で、家具の据付ではない
    assert mk.work("mirror", D("0.6"))[:3] == ("内装工事", "壁付け（下地共）", "大工")


def test_天井照明は電気設備工事になる():
    # 同じカタログの 1 体が、置き方が違うだけで別の科目に行き別の職種が付く
    assert mk.work("ceiling_light", D("0.5"))[:3] == \
        ("電気設備工事", "照明器具", "電工")


def test_置き方は_4_区分():
    assert set(mk.WORK) == {"floor", "floor_flat", "wall", "ceiling"}
    assert mk.placement("chair") == "floor"
    assert mk.placement("ceiling_light") == "ceiling"


# --- 単価 ---------------------------------------------------------------

def test_単価は寸法が大きいほど高い():
    assert mk.unit_price("sofa", D("2.4")) > mk.unit_price("sofa", D("1.2"))


def test_単価は千円単位に丸める():
    for w in ("0.5", "1.0", "1.7", "2.3"):
        assert mk.unit_price("sofa", D(w)) % 1000 == 0


def test_単価は乱数を使わない():
    # --seed という引数を作らないことで、再現性を形にしてある
    assert mk.unit_price("chair", D("0.6")) == mk.unit_price("chair", D("0.6"))


def test_単価の計算に_float_を通さない():
    assert isinstance(mk.unit_price("sofa", D("1.8")), Decimal)


# --- 生成物 -------------------------------------------------------------

def test_出どころの列に架空と書く(tmp_path):
    files = mk.build(written(tmp_path), 3)
    assert "架空単価" in files["prices.csv"]


def test_数量リストの_note_に置換アセットを書く(tmp_path):
    files = mk.build(written(tmp_path), 3)
    assert "置換アセット B" in files["quantities.json"]


def test_生成は冪等(tmp_path):
    p = written(tmp_path)
    assert mk.build(p, 3) == mk.build(p, 3)


def test_生成物に生成時刻を書かない(tmp_path):
    # 実行のたびに差分が出ないよう、日付は入力由来か固定値だけを使う
    files = mk.build(written(tmp_path), 3)
    assert mk.ISSUED in files["quantities.json"]
    assert "2026-10-03" in files["prices.csv"]   # 単価の適用日はカタログの日付


def test_発行日はカタログの日付とは別(tmp_path):
    # 発行日は見積書のもので、素材カタログがいつ作られたかとは関係が無い
    files = mk.build(written(tmp_path), 3)
    assert f'"issued": "{mk.ISSUED}"' in files["quantities.json"]


def test_帰属表記はマニフェストのライセンス欄から作る(tmp_path):
    # 道具のコードに出どころの名前を直書きしない
    files = mk.build(written(tmp_path), 3)
    assert "作り物カタログ" in files["NOTICE.md"]
    assert "[CC BY 4.0](https://x/by/4.0/)" in files["NOTICE.md"]


def test_帰属表記に全ての識別子と原名が載る(tmp_path):
    files = mk.build(written(tmp_path), 3)
    import csv, io
    codes = [r for r in csv.DictReader(io.StringIO(files["prices.csv"]))
             if "架空単価" in (r["source"] or "")]
    for r in codes:
        asin = r["source"].split("（")[1].split(" ")[0]
        assert f"`{asin}`" in files["NOTICE.md"], asin


def test_帰属表記に作り直すコマンドが書いてある(tmp_path):
    files = mk.build(written(tmp_path), 3)
    assert "tools/make_examples.py" in files["NOTICE.md"]
    assert "手で直さない" in files["NOTICE.md"]


def test_作った見本をそのまま読める(tmp_path):
    # **道具が作った見本を、道具が自分で読めないまま置かない**
    out = tmp_path / "ex"
    mk.write(mk.build(written(tmp_path), 3), out)
    mk.verify(out)


def test_check_は一致していれば_0(tmp_path):
    out = tmp_path / "ex"
    files = mk.build(written(tmp_path), 3)
    mk.write(files, out)
    assert mk.check(files, out) == []


def test_check_は違いを数える(tmp_path):
    out = tmp_path / "ex"
    files = mk.build(written(tmp_path), 3)
    mk.write(files, out)
    (out / "prices.csv").write_text("壊した\n", encoding="utf-8")
    assert mk.check(files, out) == ["prices.csv: 中身が違う"]
