"""数量 × 単価 → 明細。**純関数だけ。ファイルも時刻も見ない。**

| | |
|---|---|
| 材料費 | 数量 × (1 + ロス率) × 材料単価 |
| 人工 | 数量 × 歩掛り |
| 施工費 | 人工 × その職種の労務単価 |

ロス率は材料にだけ掛ける。切り代や張り代で**材料は余分に要るが、手間は増え
ない**ため。材料と手間に同じ率を掛けると、面積の大きい部屋ほど手間が実態から
離れていく。

人工は丸めない。0.1 人工を切り上げると、小さい品目が並んだときに合計が実態の
倍になる。丸めるのは円にしてからの 1 回だけ（`money.to_yen`）。

## 階層

建築工事内訳書の標準書式に合わせて **科目 → 中科目 → 細目**の 3 段で積む。

```
内装工事                        科目
  壁・天井仕上                  中科目
    量産クロス  48.6 ㎡          細目（＝明細の 1 行）
```

2 段で足りるように見えても、後から段を増やすと既存の単価表を全部棚卸しし直す
ことになる。**段は先に用意しておくほうが安い。**
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .money import ZERO, to_yen, total
from .price import CERT_PREFIX, GRADE_COLUMNS, TAX_KINDS, Item, PriceBook
from .quantity import Header, Line, Sheet

ONE = Decimal("1")


@dataclass(frozen=True)
class Row:
    """細目。明細の 1 行。金額は確定済み（丸め済み）。"""

    code: str
    name: str
    unit: str
    division: str
    section: str
    note: str
    qty: Decimal
    #: ロスを見込んだ数量。材料を拾うときの実数量
    qty_with_loss: Decimal
    loss: Decimal
    material_unit: Decimal
    material: Decimal
    #: 人工。丸めない
    days: Decimal
    trade: str
    labor_unit: Decimal
    labor: Decimal
    tax: str
    source: str
    as_of: object  # datetime.date | None
    fire: str
    fire_no: str
    f_star: str
    flame: str
    spec: str

    @property
    def amount(self) -> Decimal:
        return self.material + self.labor

    @property
    def sourced(self) -> bool:
        """単価の出どころが書いてあるか。"""
        return bool(self.source and self.as_of)

    @property
    def blank_grades(self) -> tuple[str, ...]:
        """空いている認定・等級の欄の、日本語の呼び名。

        **欄ごとに返すのは、3 つが別の法令だから。**「7 件空いている」だけでは
        内装制限を見ていないのか防炎を見ていないのかが分からず、直しようがない。

        「対象外」と書いてある欄は空欄に数えない。当たらないと判断したことが
        書いてあるので、見ていないのとは別。
        """
        return tuple(label for col, label in GRADE_COLUMNS
                     if not getattr(self, col))

    @property
    def graded(self) -> bool:
        return not self.blank_grades

    @property
    def cert_mismatch(self) -> str:
        """認定番号の接頭辞が不燃区分と食い違っていれば、その中身。

        **断らずに数えるだけ。** 番号が空なら何も言わない（令 108 条の 2 の
        例示仕様は番号を持たない）。知らない接頭辞でも何も言わない（旧書式や
        自社表記がある）。**拾うのは打ち間違いだけ**で、書き方の多様性は拾わない。
        """
        want = CERT_PREFIX.get(self.fire)
        if not (want and self.fire_no):
            return ""
        head = self.fire_no[:2].upper()
        if head in CERT_PREFIX.values() and head != want:
            return f"{self.fire} と {self.fire_no}"
        return ""


@dataclass(frozen=True)
class Unknown:
    """単価表に無かった行。**落とさずに残す。**

    黙って落とすと合計だけが静かに小さくなり、見積りが足りないことに気づけない。
    金額を持たない行として最後まで運び、人の目に触れさせる。
    """

    code: str
    qty: Decimal
    note: str = ""


class _Sums:
    """小計の持ち方。**行を足すだけで、丸め直さない。**"""

    rows: tuple[Row, ...]

    @property
    def material(self) -> Decimal:
        return total(r.material for r in self.rows)

    @property
    def labor(self) -> Decimal:
        return total(r.labor for r in self.rows)

    @property
    def days(self) -> Decimal:
        return total(r.days for r in self.rows)

    @property
    def amount(self) -> Decimal:
        return self.material + self.labor


@dataclass(frozen=True)
class Section(_Sums):
    """中科目。"""

    name: str
    rows: tuple[Row, ...]


@dataclass(frozen=True)
class Division:
    """科目。"""

    name: str
    sections: tuple[Section, ...]

    @property
    def rows(self) -> tuple[Row, ...]:
        return tuple(r for s in self.sections for r in s.rows)

    material = _Sums.material
    labor = _Sums.labor
    days = _Sums.days
    amount = _Sums.amount


@dataclass(frozen=True)
class Estimate:
    """1 件分の見積り。直接工事費まで。"""

    scan_id: str
    name: str
    header: Header
    divisions: tuple[Division, ...]
    unknown: tuple[Unknown, ...]

    @property
    def rows(self) -> tuple[Row, ...]:
        return tuple(r for d in self.divisions for r in d.rows)

    material = _Sums.material
    labor = _Sums.labor
    days = _Sums.days
    amount = _Sums.amount

    @property
    def complete(self) -> bool:
        """単価の付かなかった行が無いか。**合計を信じてよいかの判定。**"""
        return not self.unknown

    @property
    def by_tax(self) -> dict[str, Decimal]:
        """税区分ごとの金額。

        **消費税額はここでは出さない**（直接工事費までが担当）。ただし区分を
        後から行に遡って付け直すことはできないので、運んで小計だけ出しておく。
        """
        out = {k: ZERO for k in TAX_KINDS}
        for r in self.rows:
            out[r.tax] += r.amount
        return {k: v for k, v in out.items() if v}

    @property
    def unsourced(self) -> tuple[Row, ...]:
        """単価の出どころが書かれていない行。"""
        return tuple(r for r in self.rows if not r.sourced)

    @property
    def ungraded(self) -> tuple[Row, ...]:
        """認定・等級の欄が空いている行。

        **内装制限が掛かるかは、用途・規模・階数を知らないここでは判定できない。**
        空欄＝誤りとは限らない（家具に不燃認定は要らない）。数えて見せるだけ。
        """
        return tuple(r for r in self.rows if not r.graded)

    @property
    def mismatched(self) -> tuple[Row, ...]:
        """認定番号と不燃区分が食い違う行。"""
        return tuple(r for r in self.rows if r.cert_mismatch)


def row(line: Line, item: Item, book: PriceBook) -> Row:
    """1 行ぶんの金額を出す。"""
    qty_with_loss = line.qty * (ONE + item.loss)
    material = to_yen(qty_with_loss * item.material)

    days = line.qty * item.labor
    labor_unit = book.labor_unit(item)
    labor = to_yen(line.qty * labor_unit) if labor_unit else ZERO

    return Row(code=item.code, name=item.name, unit=item.unit,
               division=item.division, section=item.section,
               note=line.note, qty=line.qty, qty_with_loss=qty_with_loss,
               loss=item.loss, material_unit=item.material, material=material,
               days=days, trade=item.trade, labor_unit=labor_unit, labor=labor,
               tax=item.tax, source=item.source, as_of=item.as_of,
               fire=item.fire, fire_no=item.fire_no, f_star=item.f_star,
               flame=item.flame, spec=item.spec)


def build(sheet: Sheet, book: PriceBook) -> Estimate:
    """数量リストと単価表から明細を組む。

    **科目と中科目の並びは単価表に出てきた順。** 名前順に並べ替えると、表を
    組んだ人が意図した工事の順（下地 → 仕上げ → 設備）が崩れる。行の並びは
    数量リストの順をそのまま保つ。
    """
    order = _order(book)
    bucket: dict[tuple[str, str], list[Row]] = {}
    unknown: list[Unknown] = []

    for line in sheet.lines:
        item = book.items.get(line.code)
        if item is None:
            unknown.append(Unknown(line.code, line.qty, line.note))
            continue
        bucket.setdefault((item.division, item.section), []).append(
            row(line, item, book))

    divisions: list[Division] = []
    for div, sections in order.items():
        got = tuple(Section(sec, tuple(bucket[(div, sec)]))
                    for sec in sections if (div, sec) in bucket)
        if got:
            divisions.append(Division(div, got))

    return Estimate(sheet.scan_id, sheet.name, sheet.header,
                    tuple(divisions), tuple(unknown))


def _order(book: PriceBook) -> dict[str, list[str]]:
    """単価表に出てきた順の 科目 → 中科目。"""
    out: dict[str, list[str]] = {}
    for item in book.items.values():
        secs = out.setdefault(item.division, [])
        if item.section not in secs:
            secs.append(item.section)
    return out
