"""`examples/` の見本データを、家具の 3D カタログから作り直す道具。

見積りモジュールの見本に、手で書いた架空の家具が並んでいると、**寸法も品目の
幅も作り手の想像の範囲に収まる**。実在する家具のカタログから引くと、寸法のばらつき
も品目の偏りも実物のものになり、表示幅や科目の分かれ方が本当に耐えるか分かる。

    uv run python tools/make_examples.py \
        --manifest ../TemplateMaker/catalog/abo.tier-b.json

**読むのはマニフェスト 1 枚だけ。** `tm-manifest-1` の形をしていれば出どころは
問わない（この道具のコードに「ABO」という語は出てこない。ライセンスも帰属表記も
マニフェストから読んで写すだけ）。3D の実体も商品画像も読まない。見積書は文字しか
出さないので、読んでも置き場所が無い。

**単価と歩掛りは架空。** カタログに価格は入っていないので、カテゴリごとの基準額に
寸法の比を掛けて機械的に作る。架空であることは `source` 列と `examples/NOTICE.md`
の 2 箇所に書く（CSV にコメント行は書けない。`#` 行は 1 行として読まれて
`code が空` で落ちる）。

**乱数を使わない。** 同じマニフェストと同じ引数なら、出力は 1 バイトも変わらない。
`--seed` という引数を作らないことで、それを形にしてある。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from estimate import breakdown, price, quantity  # noqa: E402

SCHEMA = "tm-manifest-1"

#: 品目の和名。カタログの名前は英語・蘭語・仏語が混じり、**日本語は 1 つも無い**
JA = {
    "chair": "椅子", "sofa": "ソファ", "stool": "スツール", "bench": "ベンチ",
    "table": "テーブル", "desk": "デスク", "bed": "ベッド", "storage": "収納家具",
    "lamp": "スタンド照明", "planter": "プランター", "decor": "装飾小物",
    "rug": "ラグ", "headboard": "ヘッドボード", "mirror": "ミラー",
    "wall_decor": "壁装飾", "ceiling_light": "天井照明",
}

#: 品目コードの頭
ABBR = {
    "chair": "CHR", "sofa": "SOF", "stool": "STL", "bench": "BNC",
    "table": "TBL", "desk": "DSK", "bed": "BED", "storage": "STG",
    "lamp": "LMP", "planter": "PLT", "decor": "DCR", "rug": "RUG",
    "headboard": "HDB", "mirror": "MIR", "wall_decor": "WDC",
    "ceiling_light": "CLT",
}

#: 置き方。**ここが科目・職種・歩掛りのすべてを決める。**
#: 同じカタログの 1 体が、置き方が違うだけで別の科目に行き、別の職種が付く
PLACEMENT = {"rug": "floor_flat",
             "headboard": "wall", "mirror": "wall", "wall_decor": "wall",
             "ceiling_light": "ceiling"}

#: 置き方 → (科目, 中科目, 職種, 歩掛り)
#:
#: 壁付けを家具工事でなく内装工事に置くのは、下地（間柱・合板）が要るため。
#: 下地は内装の仕事で、家具の据付ではない。**手間の性質が違うものを同じ中科目に
#: 入れると、後から歩掛りを直すときに巻き添えが出る。**
#:
#: 天井照明が電気設備工事に行くのは、引掛シーリングからの吊り込みが電気工事だから。
WORK = {
    "floor":      ("家具工事", "置き家具", "家具工", Decimal("0.3")),
    "floor_flat": ("家具工事", "敷物", "", Decimal("0")),
    "wall":       ("内装工事", "壁付け（下地共）", "大工", Decimal("0.6")),
    "ceiling":    ("電気設備工事", "照明器具", "電工", Decimal("0.4")),
}

#: 幅 1.2m 以上の床置きは据付に人手が要る
WIDE, WIDE_LABOR = Decimal("1.2"), Decimal("0.5")

#: 単位
UNIT = {"rug": "枚", "mirror": "枚", "wall_decor": "枚", "headboard": "枚",
        "planter": "個", "decor": "個"}

#: カテゴリごとの (基準額 円, 基準幅 m)。**架空の値。**
BASE = {
    "chair": (28000, "0.60"), "sofa": (120000, "1.80"),
    "stool": (16000, "0.45"), "bench": (34000, "1.20"),
    "table": (58000, "1.20"), "desk": (46000, "1.20"),
    "bed": (78000, "1.40"), "storage": (52000, "0.90"),
    "lamp": (18000, "0.40"), "planter": (9000, "0.35"),
    "decor": (6000, "0.30"), "rug": (24000, "2.00"),
    "headboard": (32000, "1.50"), "mirror": (22000, "0.60"),
    "wall_decor": (12000, "0.60"), "ceiling_light": (26000, "0.50"),
}

#: 1 部屋ぶんの構成。(カテゴリ, 何体使うか, 1 体あたりの数量)
ROOM = (("sofa", 1, 1), ("table", 1, 1), ("chair", 2, 2), ("storage", 2, 1),
        ("rug", 1, 1), ("lamp", 1, 1), ("mirror", 1, 1),
        ("ceiling_light", 2, 1), ("planter", 1, 1), ("decor", 1, 2))

#: カタログに無い工事。**架空のまま残す。**
FIXED_ROWS = """\
CL-0100,既存クロス剥がし,㎡,内装工事,下地・撤去,0,0,0.04,内装工,課税,自社実績 2026 上期,2026-04-01,対象外,,規制対象外,対象外,
WC-1000,量産クロス,㎡,内装工事,壁・天井仕上,450,0.05,0.10,内装工,課税,A 商事 見積,2026-03-11,準不燃,QM-9876,F☆☆☆☆,対象外,厚 0.2mm
WC-2000,織物調クロス,㎡,内装工事,壁・天井仕上,1200,0.05,0.12,内装工,課税,A 商事 見積,2026-03-11,不燃,NM-8591,F☆☆☆☆,防炎,
FL-2000,複合フローリング,㎡,内装工事,床仕上,4200,0.05,0.25,大工,課税,建設物価 2026-04,2026-04-01,,,F☆☆☆☆,対象外,t12 直貼り
FL-3000,クッションフロア,㎡,内装工事,床仕上,1800,0.08,0.15,内装工,課税,建設物価 2026-04,2026-04-01,,,,,t1.8
BB-0100,ソフト巾木 H60,m,内装工事,造作,180,0.05,0.04,内装工,課税,建設物価 2026-04,2026-04-01,対象外,,F☆☆☆☆,対象外,H60
CN-0100,回り縁,m,内装工事,造作,420,0.05,0.06,大工,課税,建設物価 2026-04,2026-04-01,対象外,,F☆☆☆☆,対象外,
DR-0100,片開き戸(枠・金物共),箇所,建具工事,木製建具,42000,0,0.8,建具工,課税,B 建材 見積,2026-02-20,対象外,,F☆☆☆☆,対象外,W780×H2000
DR-0200,引違い戸(枠・金物共),箇所,建具工事,木製建具,68000,0,1.2,建具工,課税,B 建材 見積,2026-02-20,対象外,,F☆☆☆☆,対象外,W1640×H2000
WD-0100,アルミ樹脂複合窓,箇所,建具工事,金属建具,58000,0,1.0,建具工,課税,B 建材 見積,2026-02-20,不燃,令 108 条の 2 例示,規制対象外,対象外,W1690×H1170
SW-0100,スイッチ・コンセント,箇所,電気設備工事,配線器具,1800,0,0.2,電工,課税,C 電材 見積,2026-03-05,対象外,,規制対象外,対象外,
INS-0100,工事保険料,式,諸費用,保険,32000,0,0,,非課税,保険料率表,2026-04-01,対象外,,規制対象外,対象外,
WST-0100,廃棄物処理手数料(自治体・立替),式,諸費用,立替金,18000,0,0,,不課税,自治体公表,2026-04-01,対象外,,規制対象外,対象外,
"""

FIXED_ITEMS = (
    ("CL-0100", "62.4", "壁・天井 既存クロス"), ("WC-1000", "48.6", "壁。開口部 3 箇所を差し引き済み"),
    ("WC-2000", "13.8", "天井"), ("FL-2000", "19.4", "居室"), ("FL-3000", "3.2", "洗面脱衣"),
    ("DR-0100", "2", ""), ("DR-0200", "1", "居室・洋室間"), ("WD-0100", "2", ""),
    ("SW-0100", "9", ""), ("INS-0100", "1", ""), ("WST-0100", "1", ""),
)

TRADES = """\
trade,name,daily
内装工,内装仕上工,24000
大工,大工,26000
建具工,建具工,25000
電工,電気工事士,27000
家具工,家具設置,20000
"""

MARKUP = """\
kind,stage,name,base,rate,amount,after,tax,source,as_of
経費,1,共通仮設費,直接工事費,0.062,,純工事費,課税,共通費積算基準（架空）,2026-04-01
経費,2,現場管理費,累計,0.095,,工事原価,課税,共通費積算基準（架空）,2026-04-01
経費,3,一般管理費等,累計,0.082,,工事価格,課税,自社 2026 期（架空）,2026-04-01
消費税,,消費税,課税,0.10,,,,国税庁 消費税法,2019-10-01
"""

HEAD = ("code,name,unit,division,section,material,loss,labor,trade,"
        "tax,source,as_of,fire,fire_no,f_star,flame,spec")


class ToolError(Exception):
    """道具が進めない。"""


# --- 純関数 -------------------------------------------------------------

def wdh(extent: list) -> tuple[Decimal, Decimal, Decimal]:
    """外形 [x, y, z] (m) から (幅, 奥行, 高さ)。

    glTF の x と z のどちらが幅かは書き出し側の都合で決まるので**大小で取る**。
    高さだけは Y-up が保証される。
    """
    x, y, z = (Decimal(str(v)) for v in extent)
    return (max(x, z), min(x, z), y)


def spec(extent: list) -> str:
    """寸法の表示。**10mm に丸める。**

    これは外接直方体の実測であって公称寸法ではない。クッションの膨らみ込みで
    `W2209` と書くとカタログの公称値だと誤解される。10mm 丸めなら「おおよその
    外形」と読める。
    """
    w, d, h = (int(v * 1000 / 10 + Decimal("0.5")) * 10 for v in wdh(extent))
    return f"W{w}×D{d}×H{h}"


def placement(category: str) -> str:
    return PLACEMENT.get(category, "floor")


def work(category: str, width: Decimal) -> tuple[str, str, str, Decimal]:
    """科目・中科目・職種・歩掛り。**置き方から決まる。**"""
    div, sec, trade, labor = WORK[placement(category)]
    if placement(category) == "floor" and width >= WIDE:
        labor = WIDE_LABOR
    return div, sec, trade, labor


def unit_price(category: str, width: Decimal) -> Decimal:
    """架空の単価。**カテゴリの基準額に幅の比を掛け、千円に丸める。**

    カテゴリ辞書だけだと同じ品目の 3 体が全部同じ額になり、隣の寸法欄と矛盾した
    表が見本になる。幅だけだとカテゴリ間の桁が出ない。指数 0.7 は、体積比
    （≒3 乗）だと差が開きすぎ、0 乗だと辞書だけに戻るための間を取った**近似**。

    千円に丸めるのは、1 円単位だと「どこかの実勢値を引いた」ように見えるため。
    **架空らしく見せるのも誠実さのうち。**
    """
    base, ref = BASE[category]
    ratio = (width / Decimal(ref)) ** Decimal("0.7")
    yen = Decimal(base) * ratio
    return (yen / 1000).quantize(Decimal(1)) * 1000


def pick(items: list[dict], category: str, n: int) -> list[dict]:
    """カテゴリから n 体。**ASIN 昇順の先頭から。乱数を使わない。**"""
    got = sorted((i for i in items if i["category"] == category),
                 key=lambda i: i["id"])
    return got[:n]


def collapse(items: list[dict]) -> tuple[list[dict], int]:
    """色違いを畳む。

    カタログは頂点数・面数・寸法では畳み済みだが、**名前の末尾の色だけが違う体**
    が残っている（実測で 42 組）。頂点数が違うので形としては別物だが、見積書の行
    としては「ベッド 01」と「ベッド 02」で区別が付かない。

    商品名は色が最後のカンマ区切りに来るので、そこだけ落として畳む。ただし
    **落とすのは数字を含まない区切りだけ**。`56"W` のような寸法が最後に来る名前
    （色を書いていない商品）でサイズ違いまで畳んでしまうのを防ぐ。色名に数字は
    入らないので、数字の有無で分けられる。
    """
    seen: dict[tuple, dict] = {}
    for it in sorted(items, key=lambda i: i["id"]):
        seen.setdefault((it.get("brand") or "", _stem(it.get("name") or "")), it)
    kept = sorted(seen.values(), key=lambda i: i["id"])
    return kept, len(items) - len(kept)


def _stem(name: str) -> str:
    """色を落とした基幹名。"""
    head, sep, tail = name.rpartition(",")
    if sep and not any(c.isdigit() for c in tail):
        name = head
    return name.strip().lower()


# --- 組み立て -----------------------------------------------------------

def rows(items: list[dict], per_category: int, as_of: str) -> list[dict]:
    """カタログから家具の行を組む。"""
    unknown = sorted({i["category"] for i in items} - set(JA))
    if unknown:
        # 語彙が変わったことに気づけるようにする。黙って無視すると、
        # 新しい品目が見本から静かに落ちる
        raise ToolError(f"知らない品目: {', '.join(unknown)}")

    kept, _ = collapse(items)
    out: list[dict] = []
    for category, n, qty in ROOM:
        got = pick(kept, category, min(n, per_category))
        if not got:
            raise ToolError(f"カタログに {category} が 1 体も無い")
        if len(got) < n:
            print(f"{category} は {len(got)} 体しか無い（{n} 体ほしかった）",
                  file=sys.stderr)
        for k, it in enumerate(got, start=1):
            w, _, _ = wdh(it["extent"])
            div, sec, trade, labor = work(category, w)
            out.append({
                "code": f"{ABBR[category]}-{k:02d}",
                "name": f"{JA[category]} {k:02d}",
                "unit": UNIT.get(category, "台"),
                "division": div, "section": sec,
                "material": unit_price(category, w),
                "labor": labor, "trade": trade,
                "spec": spec(it["extent"]),
                "asin": it["id"], "qty": qty,
                "source": f"架空単価（{it['id']} の寸法から生成）",
                "as_of": as_of,
            })
    return out


def prices_csv(furniture: list[dict]) -> str:
    """単価表。**家具はカタログ由来、他は架空のまま。**"""
    lines = [HEAD]
    fixed = FIXED_ROWS.strip().splitlines()
    # 工事の順に並べる。家具は最後
    lines += [r for r in fixed if not r.startswith(("INS-", "WST-"))]
    for f in furniture:
        lines.append(",".join([
            f["code"], f["name"], f["unit"], f["division"], f["section"],
            str(f["material"]), "0", str(f["labor"]), f["trade"],
            "課税", f["source"], f["as_of"],
            "対象外", "", "無等級", "対象外", f["spec"],
        ]))
    lines += [r for r in fixed if r.startswith(("INS-", "WST-"))]
    return "\n".join(lines) + "\n"


def round_target(out: Path) -> int:
    """値引き前の税込合計から、端数調整の目標額を決める。

    **目標額を決め打ちにしない。** 見本の中身が変われば合計も変わるので、固定して
    おくと「17% 値引き」のような見積書が黙って出来上がる。値引き前の合計を万円に
    切り下げ、そこから**到達できる額まで下げる**（税込の目標は 1 円刻みでは届かない
    ことがある）。
    """
    from estimate import ladder, markup
    book = price.load(out / "prices.csv", out / "trades.csv")
    sheet = quantity.load(out / "quantities.json")
    est = breakdown.build(sheet, book)
    m = markup.load(out / "markup.csv")
    bare = ladder.build(est, m, None)

    target = int(bare.total) // 10000 * 10000
    for t in range(target, target - 100, -1):
        try:
            ladder.build(est, m, quantity.Discount("端数お値引き",
                                                   target=Decimal(t)))
        except ladder.LadderError:
            continue
        return t
    raise ToolError("端数調整の目標額を決められなかった")


#: 見本の見積書の発行日。**カタログの日付とは別。** 発行日は見積書のもので、
#: 素材カタログがいつ作られたかとは関係が無い
ISSUED = "2026-10-13"


def quantities_json(furniture: list[dict], issued: str = ISSUED,
                    target: int | None = None) -> str:
    items = [{"code": c, "qty": _num(q), "note": n} if n
             else {"code": c, "qty": _num(q)} for c, q, n in FIXED_ITEMS]
    items += [{"code": f["code"], "qty": f["qty"],
               "note": f"置換アセット {f['asin']}"} for f in furniture]
    return json.dumps({
        "scan_id": "room-0a3f",
        "name": "ワンルーム 内装改修（形式の見本）",
        "estimate": {
            "number": "2026-1013-001", "revision": 1, "issued": issued,
            "valid_days": 14, "client": "見本 太郎",
            "subject": "ワンルーム 内装改修工事 お見積書（形式の見本）",
            "issuer": {
                "name": "見本内装 株式会社",
                "address": "東京都千代田区（見本）1-2-3",
                "tel": "03-0000-0000",
                "person": "積算 花子",
                "registration": "T0000000000000",
            },
            **({} if target is None else
               {"discount": {"name": "端数お値引き", "target": target,
                             "basis": "税込"}}),
        },
        "items": items,
    }, ensure_ascii=False, indent=2) + "\n"


def _num(s: str):
    return float(s) if "." in s else int(s)


def notice(man: dict, furniture: list[dict], collapsed: int) -> str:
    """帰属表記。**ライセンスも出所もマニフェストから写すだけ。**

    CC BY の 4 要素（出所名 / ライセンス名とリンク / 変更の有無 / 個々の作品の
    特定）をここで満たす。見積書に出る名前は日本語だけにして、原名は帰属表記の
    側に置く。**2 つの要求（読める見積書 / 作品の特定）を 1 つの欄に押し込まない。**
    """
    by_id = {i["id"]: i for i in man["items"]}
    lines = [
        "# examples/ の見本データについて",
        "",
        "**このディレクトリのファイルは生成物。手で直さない。** 作り直すには:",
        "",
        "```bash",
        "uv run python tools/make_examples.py \\",
        "    --manifest ../TemplateMaker/catalog/abo.tier-b.json",
        "```",
        "",
        "`--check` を付けると、生成せずに今の `examples/` と一致するかだけを見る。",
        "",
        "## 単価と歩掛りは架空",
        "",
        f"{man['attribution']} に価格は入っていない。この表の単価は**カテゴリごとの"
        "基準額に",
        "寸法の比を掛けて機械的に作った架空の値**で、実勢価格ではない。歩掛りも同じく",
        "架空で、置き方の 4 区分（床置き・敷物・壁付け・天井）から決めている。",
        "単価の出どころを書く列（`source`）に、行ごとに「架空単価」と書いてある。",
        "",
        "仕上げ材・建具・電気設備・諸費用の行はカタログに無いので、**手で書いた架空の",
        "まま**残っている。",
        "",
        f"## {man['attribution']}",
        "",
        f"- ライセンス: [{man['license']}]({man['license_url']})",
        f"- 収録数: {len(furniture)} 体",
        "- 変更: 3D 形状そのものは同梱していない。ここで使ったのは識別子・商品名・",
        "  ブランド・外形寸法で、品目名は日本語に置き換え、寸法は 10mm に丸めている。",
        "  **単価・歩掛り・工種はカタログに無く、こちらで架空に作ったもの。**",
    ]
    if collapsed:
        lines.append(f"- 色違いの {collapsed} 体は、見積書の行として区別が付かない"
                     "ので畳んである。")
    lines += ["", "<details><summary>内訳</summary>", ""]
    for f in sorted(furniture, key=lambda f: f["asin"]):
        it = by_id[f["asin"]]
        name = (it.get("name") or "").replace("|", "/")
        brand = it.get("brand") or ""
        lines.append(f"- `{f['asin']}` {name}" + (f" — {brand}" if brand else ""))
    lines += ["", "</details>", ""]
    return "\n".join(lines)


# --- 書き戻し -----------------------------------------------------------

def build(manifest: Path, per_category: int) -> dict[str, str]:
    """3 ファイル分の文字列を組む。**まだ書かない。**"""
    try:
        man = json.loads(manifest.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ToolError(
            f"マニフェストが無い: {manifest}\n"
            "TemplateMaker の catalog/abo.tier-b.json が要る（git 管理下にある）。\n"
            "別の場所にあるなら --manifest で指す。") from None
    except json.JSONDecodeError as e:
        raise ToolError(f"{manifest.name}: JSON として読めない ({e})") from None

    if man.get("schema_version") != SCHEMA:
        raise ToolError(f"{manifest.name}: 知らない版 "
                        f"{man.get('schema_version')!r}（{SCHEMA} が要る）")

    as_of = str(man.get("generated_at", ""))[:10] or "2026-01-01"
    _, collapsed = collapse(man["items"])
    furniture = rows(man["items"], per_category, as_of)
    if collapsed:
        print(f"色違いを {collapsed} 件畳んだ", file=sys.stderr)

    files = {
        "prices.csv": prices_csv(furniture),
        "trades.csv": TRADES,
        "markup.csv": MARKUP,
        "quantities.json": quantities_json(furniture),
        "NOTICE.md": notice(man, furniture, collapsed),
    }
    # 値引き前の合計が決まってからでないと端数調整の目標を出せないので、
    # 一度仮に書いて計算し、数量リストだけ書き直す
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for name, text in files.items():
            (tmp / name).write_text(text, encoding="utf-8")
        target = round_target(tmp)
    files["quantities.json"] = quantities_json(furniture, target=target)
    return files


def verify(out: Path) -> None:
    """**道具が作った見本を、道具が自分で読めないまま置かない。**"""
    book = price.load(out / "prices.csv", out / "trades.csv")
    sheet = quantity.load(out / "quantities.json")
    est = breakdown.build(sheet, book)
    if not est.complete:
        raise ToolError("作った見本に単価の付かない行がある: "
                        + ", ".join(u.code for u in est.unknown))


def write(files: dict[str, str], out: Path) -> None:
    """`.part` に書いて、検証が通ってから置き換える。

    途中で失敗したとき半端な見本が残らない。TemplateMaker が取得に使っている
    作法と同じ。
    """
    out.mkdir(parents=True, exist_ok=True)
    parts = {}
    for name, text in files.items():
        tmp = out / (name + ".part")
        tmp.write_text(text, encoding="utf-8")
        parts[name] = tmp

    keep = {name: (out / name).read_text(encoding="utf-8")
            if (out / name).exists() else None for name in files}
    try:
        for name, tmp in parts.items():
            os.replace(tmp, out / name)
        verify(out)
    except Exception:
        for name, old in keep.items():
            if old is None:
                (out / name).unlink(missing_ok=True)
            else:
                (out / name).write_text(old, encoding="utf-8")
        for tmp in parts.values():
            tmp.unlink(missing_ok=True)
        raise


def check(files: dict[str, str], out: Path) -> list[str]:
    """生成せずに、今の見本と一致するかだけ見る。"""
    bad = []
    for name, text in files.items():
        got = out / name
        if not got.exists():
            bad.append(f"{name}: 無い")
        elif got.read_text(encoding="utf-8") != text:
            bad.append(f"{name}: 中身が違う")
    return bad


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="make_examples",
        description="家具の 3D カタログから examples/ を作り直す")
    p.add_argument("--manifest", type=Path,
                   default=ROOT.parent / "TemplateMaker/catalog/abo.tier-b.json",
                   help="tm-manifest-1 形式のマニフェスト")
    p.add_argument("--per-category", type=int, default=3,
                   help="1 品目あたりの上限（既定 3）")
    p.add_argument("--out", type=Path, default=ROOT / "examples")
    p.add_argument("--check", action="store_true",
                   help="生成せず、今の examples と一致するかだけ見る")
    args = p.parse_args(argv)

    try:
        files = build(args.manifest, args.per_category)
        if args.check:
            bad = check(files, args.out)
            for b in bad:
                print(b, file=sys.stderr)
            print("一致している" if not bad else f"{len(bad)} 件違う")
            return 1 if bad else 0
        write(files, args.out)
    except ToolError as e:
        print(str(e), file=sys.stderr)
        return 2
    except (price.PriceError, quantity.QuantityError) as e:
        print(f"作った見本が読めない:\n{e}", file=sys.stderr)
        return 2

    print(f"書き出した: {', '.join(sorted(files))} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
