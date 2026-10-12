"""単価表の読み込みと検証。

**単価はリポジトリに持たない。** 価格は出どころと使用条件が物ごとに違い、
年ごとに改定される。手元の CSV を指して使う（[TemplateMaker][tm] が GLB を
持たないのと同じ理由）。

表は 2 枚に分けてある。

| | |
|---|---|
| 単価表 `prices.csv` | 品目ごとの材料単価・ロス率・歩掛り・職種 |
| 労務単価表 `trades.csv` | 職種ごとの 1 人工あたりの円 |

**施工費を円で直に持たない。** 歩掛り（単位あたりの人工）と労務単価を分けて
持つと、労務単価が改定されたとき 1 行直せば全品目に行き渡る。円で持つと
品目の数だけ直すことになり、直し漏れた品目が古い相場のまま残る。

[tm]: https://github.com/24th-garnet/TemplateMaker
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from .money import ZERO, MoneyError, dec

PRICE_COLUMNS = ("code", "name", "unit", "division", "section",
                 "material", "loss", "labor", "trade")
TRADE_COLUMNS = ("trade", "name", "daily")

#: 無くても読めるが、**入れておくべき**列
OPTIONAL_COLUMNS = ("tax", "source", "as_of",
                    "fire", "fire_no", "f_star", "flame", "spec")

#: 不燃区分（建築基準法 35 条の 2、令 128 条の 4・128 条の 5 の内装制限）
FIRE_KINDS = ("不燃", "準不燃", "難燃", "対象外")

#: ホルムアルデヒド等級（建築基準法 28 条の 2 ほか、シックハウス規制）。
#: **規制対象外と無等級は別のもの。** 前者は告示の対象建材ではない（金属・
#: ガラス・無垢材）、後者は第一種発散建築材料で原則使えない。混ぜると、
#: 使える建材と使えない建材が同じ欄になる
F_STARS = ("F☆☆☆☆", "F☆☆☆", "F☆☆", "規制対象外", "無等級")

#: 防炎（消防法 8 条の 3）
FLAME_KINDS = ("防炎", "非防炎", "対象外")

#: 認定番号の接頭辞と不燃区分の対応。**打ち間違いを拾うためだけに使う。**
#: 令 108 条の 2 の例示仕様（コンクリート・ガラス・金属板など）は認定番号を
#: 持たないので、番号が空の行には何も言わない
CERT_PREFIX = {"不燃": "NM", "準不燃": "QM", "難燃": "RM"}

#: 認定・等級の欄と、その日本語の呼び名。**法令が別なので欄も別に数える**
GRADE_COLUMNS = (("fire", "不燃区分"), ("f_star", "ホルムアルデヒド等級"),
                 ("flame", "防炎"))

#: 税区分。消費税額はここでは出さないが、**後から分離できないので今持つ**
TAXED, EXEMPT, OUTSIDE = "課税", "非課税", "不課税"
TAX_KINDS = (TAXED, EXEMPT, OUTSIDE)


class PriceError(ValueError):
    """単価表が読めない。**理由を全部ためてから投げる。**

    1 つ直すたびに次の 1 つが出るのでは、表を直す側が何度も往復する。
    """

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("\n".join(reasons))
        self.reasons = reasons


@dataclass(frozen=True)
class Item:
    """単価表の 1 品目。"""

    code: str
    name: str
    unit: str
    #: 科目。内訳書の一番上の段（内装工事 / 電気設備工事）
    division: str
    #: 中科目。科目の中の区分（壁・天井仕上 / 床仕上）
    section: str
    #: 材料単価（円 / 単位）
    material: Decimal
    #: ロス率。0.05 で 5%。材料だけに掛かり、手間には掛からない
    loss: Decimal
    #: 歩掛り（人工 / 単位）
    labor: Decimal
    #: 職種。労務単価表の `trade` を指す
    trade: str
    #: 税区分。課税 / 非課税 / 不課税
    tax: str = TAXED
    #: 単価の出どころ。「建設物価 2026-04」「A 社見積 2026-03-11」など
    source: str = ""
    #: その単価を採った日。**後から復元できないので表に書く**
    as_of: date | None = None
    #: 不燃区分。**語彙を固定する。**「対象外」は「この品目に内装制限は
    #: 当たらない」と表を組んだ人が判断したという意味で、空欄（まだ誰も
    #: 見ていない）とは別のもの
    fire: str = ""
    #: 認定番号。**自由記述で検証しない。** 令 108 条の 2 の例示仕様は番号を
    #: 持たず、枝番・複合認定・旧書式もある。形を強制すると実データが通らない
    fire_no: str = ""
    #: ホルムアルデヒド等級。語彙を固定する（表記ゆれが混ざると判定できない）
    f_star: str = ""
    #: 防炎。語彙を固定する
    flame: str = ""
    #: 寸法・仕様の自由記述。「W2209×D895×H768」など
    spec: str = ""


@dataclass(frozen=True)
class Trade:
    """職種と 1 人工あたりの円。"""

    code: str
    name: str
    daily: Decimal


@dataclass(frozen=True)
class PriceBook:
    """単価表と労務単価表の組。"""

    items: dict[str, Item]
    trades: dict[str, Trade]
    #: 単価表に実際にあった任意列。**表を入れ替える人が、自分の表がどこまで
    #: 届いているかを知る手段がこれしかない**
    optional: tuple[str, ...] = ()

    def __contains__(self, code: str) -> bool:
        return code in self.items

    def labor_unit(self, item: Item) -> Decimal:
        """施工費の単価（円 / 単位）。歩掛り × その職種の労務単価。

        手間の要らない品目（`trade` が空）は 0。支給品や施主手配がこれにあたる。
        """
        if not item.trade:
            return ZERO
        return item.labor * self.trades[item.trade].daily


def _seen_optional(path: Path) -> tuple[str, ...]:
    """単価表にあった任意列を拾う。"""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        names = csv.DictReader(fh).fieldnames or []
    return tuple(c for c in OPTIONAL_COLUMNS if c in names)


def _rows(path: Path, columns: tuple[str, ...], what: str) -> list[dict[str, str]]:
    if not path.exists():
        raise PriceError([f"{what}が無い: {path}"])
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in columns if c not in (reader.fieldnames or [])]
        if missing:
            raise PriceError([f"{path.name}: 列が足りない: {', '.join(missing)}"])
        return [r for r in reader if any((v or "").strip() for v in r.values())]


def _positive(value: str, *, field: str, allow_zero: bool = True) -> Decimal:
    d = dec(value, field=field)
    if d < 0 or (d == 0 and not allow_zero):
        raise MoneyError(f"{field}: 負の値は置けない ({value})")
    return d


def load(prices: Path, trades: Path) -> PriceBook:
    """2 枚の CSV を読む。**不備は全部ためてから投げる。**"""
    reasons: list[str] = []

    trade_map: dict[str, Trade] = {}
    for n, row in enumerate(_rows(trades, TRADE_COLUMNS, "労務単価表"), start=2):
        code = (row["trade"] or "").strip()
        where = f"{trades.name}:{n}"
        if not code:
            reasons.append(f"{where}: trade が空")
            continue
        if code in trade_map:
            reasons.append(f"{where}: 職種 {code} が重複している")
            continue
        try:
            daily = _positive(row["daily"], field=f"{where} daily")
        except MoneyError as e:
            reasons.append(str(e))
            continue
        trade_map[code] = Trade(code, (row["name"] or code).strip(), daily)

    item_map: dict[str, Item] = {}
    for n, row in enumerate(_rows(prices, PRICE_COLUMNS, "単価表"), start=2):
        code = (row["code"] or "").strip()
        where = f"{prices.name}:{n}"
        if not code:
            reasons.append(f"{where}: code が空")
            continue
        if code in item_map:
            reasons.append(f"{where}: 品目 {code} が重複している")
            continue
        unit = (row["unit"] or "").strip()
        if not unit:
            reasons.append(f"{where}: {code} の unit が空。数量の意味が決まらない")
            continue
        tax = (row.get("tax") or TAXED).strip() or TAXED
        if tax not in TAX_KINDS:
            reasons.append(f"{where}: {code} の税区分 {tax} は "
                           f"{' / '.join(TAX_KINDS)} のどれでもない")
            continue
        grades, bad = {}, False
        for col, label, vocab in (("fire", "不燃区分", FIRE_KINDS),
                                  ("f_star", "ホルムアルデヒド等級", F_STARS),
                                  ("flame", "防炎", FLAME_KINDS)):
            v = (row.get(col) or "").strip()
            if v and v not in vocab:
                reasons.append(f"{where}: {code} の{label} {v} は "
                               f"{' / '.join(vocab)} のどれでもない")
                bad = True
            grades[col] = v
        if bad:
            continue
        as_of_raw = (row.get("as_of") or "").strip()
        as_of = None
        if as_of_raw:
            try:
                as_of = date.fromisoformat(as_of_raw)
            except ValueError:
                reasons.append(f"{where}: {code} の as_of が日付ではない "
                               f"({as_of_raw})。YYYY-MM-DD で書く")
                continue
        trade = (row["trade"] or "").strip()
        if trade and trade not in trade_map:
            reasons.append(f"{where}: {code} の職種 {trade} が労務単価表に無い")
            continue
        try:
            material = _positive(row["material"], field=f"{where} material")
            loss = _positive(row["loss"] or "0", field=f"{where} loss")
            labor = _positive(row["labor"] or "0", field=f"{where} labor")
        except MoneyError as e:
            reasons.append(str(e))
            continue
        if labor > 0 and not trade:
            reasons.append(f"{where}: {code} に歩掛りがあるのに職種が空")
            continue
        item_map[code] = Item(code, (row["name"] or code).strip(), unit,
                              (row["division"] or "その他").strip(),
                              (row["section"] or "—").strip(),
                              material, loss, labor, trade,
                              tax, (row.get("source") or "").strip(), as_of,
                              grades["fire"], (row.get("fire_no") or "").strip(),
                              grades["f_star"], grades["flame"],
                              (row.get("spec") or "").strip())

    if reasons:
        raise PriceError(reasons)
    return PriceBook(item_map, trade_map, _seen_optional(prices))
