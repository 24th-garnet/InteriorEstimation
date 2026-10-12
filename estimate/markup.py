"""経費の段と税率の読み込み。**率はリポジトリに持たない。**

共通仮設費も現場管理費も一般管理費等も、会社と年と工事の規模で変わる。単価と
同じ理由で手元の CSV を指して使う（`.gitignore` 済み）。

段の数も名前も率も、この表を組んだ人が決める。公共建築工事共通費積算基準なら
3 段、民間リフォームなら「諸経費 15%」の 1 段になる。

**段の順は表に書かせる。** 科目の並びは見た目の問題だが、ラダーの順は
**金額を変える**。行を入れ替えたら静かに総額が変わる表は持ちたくないので、
番号を書かせて 1..N の連番を検査する。

**消費税率もこの表に置く。** 案件ごとではないので数量リストには置けないが、
価格と同じで年と制度で変わるのでコードにも置けない。`base` 列が「何に掛けるか」
で一貫するので、軽減税率が要る日に行を 1 本足すだけで済む。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from .money import ONE, ZERO, MoneyError, dec
from .price import TAX_KINDS, TAXED

MARKUP_COLUMNS = ("kind", "stage", "name", "base", "rate", "amount", "after")

#: 無くても読めるが、**入れておくべき**列
OPTIONAL_COLUMNS = ("tax", "source", "as_of")

#: 行の種別
EXPENSE, CONSUMPTION = "経費", "消費税"
KINDS = (EXPENSE, CONSUMPTION)

#: 率の基数
DIRECT, RUNNING = "直接工事費", "累計"
BASES = (DIRECT, RUNNING)


class MarkupError(ValueError):
    """経費表が読めない。**理由を全部ためてから投げる。**"""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("\n".join(reasons))
        self.reasons = reasons


@dataclass(frozen=True)
class Stage:
    """経費の 1 段。**率か固定額のどちらか一方だけを持つ。**"""

    #: 段の順。1 から連番
    order: int
    name: str
    #: 率の基数（直接工事費 / 累計）。固定額の段は空
    base: str
    #: 率。0.062 で 6.2%。**丸めない**
    rate: Decimal | None
    #: 固定額（円）
    amount: Decimal | None
    #: この段を足したあとの累計の呼び名（純工事費 / 工事原価 / 工事価格）。
    #: 空なら節目を出さない
    after: str
    #: 段の金額の税区分。**率の段は課税だけ**
    tax: str = TAXED
    source: str = ""
    as_of: date | None = None

    @property
    def fixed(self) -> bool:
        return self.rate is None

    @property
    def sourced(self) -> bool:
        return bool(self.source and self.as_of)


@dataclass(frozen=True)
class TaxRate:
    """消費税の率。**掛ける税区分とひとそろいで持つ。**

    今は課税の 1 行だけだが、税区分ごとに持つ形にしておくと、軽減税率が要る日に
    行を 1 本足すだけで済む。率だけを単独で持つと、何に掛かる率なのかが分からなく
    なり、後から区分を付け直せない。
    """

    on: str
    rate: Decimal
    source: str = ""
    as_of: date | None = None


@dataclass(frozen=True)
class Markup:
    """経費表。段の並びと税率。"""

    stages: tuple[Stage, ...] = ()
    taxes: tuple[TaxRate, ...] = ()

    def rate_for(self, tax: str) -> Decimal | None:
        """その税区分に掛かる消費税率。行が無ければ None（＝税を出さない）。"""
        for t in self.taxes:
            if t.on == tax:
                return t.rate
        return None

    @property
    def empty(self) -> bool:
        return not self.stages and not self.taxes

    @property
    def unsourced(self) -> tuple[Stage, ...]:
        """率の出どころが書かれていない段。"""
        return tuple(s for s in self.stages if not s.sourced)


#: 経費表が無いとき。段も税率も無く、出力は直接工事費までで止まる
EMPTY = Markup()


def _opt(row: dict, key: str) -> str:
    return (row.get(key) or "").strip()


def load(path: Path, *, required: bool = False) -> Markup:
    """経費表を読む。**不備は全部ためてから投げる。**

    `required` は `--markup` を明示したときに立てる。明示したのに無ければ断り、
    既定の `markup.csv` が単に無いだけなら段の無い表を返す。

    **黙って 0 にしない。**「諸経費 0 円の見積り」と「諸経費を付け忘れた見積り」は、
    単価の付かない行と同じで、見積書からは区別が付かない。
    """
    if not path.exists():
        if required:
            raise MarkupError([f"経費表が無い: {path}"])
        return EMPTY

    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        names = reader.fieldnames or []
        missing = [c for c in MARKUP_COLUMNS if c not in names]
        if missing:
            raise MarkupError([f"{path.name}: 列が足りない: {', '.join(missing)}"])
        rows = [r for r in reader if any((v or "").strip() for v in r.values())]

    reasons: list[str] = []
    stages: list[Stage] = []
    taxes: list[TaxRate] = []

    for n, row in enumerate(rows, start=2):
        where = f"{path.name}:{n}"
        kind = _opt(row, "kind")
        if kind not in KINDS:
            reasons.append(f"{where}: kind {kind or '（空）'} は "
                           f"{' / '.join(KINDS)} のどちらでもない")
        elif kind == CONSUMPTION:
            _tax_row(row, where, reasons, taxes)
        else:
            _stage_row(row, where, reasons, stages)

    stages.sort(key=lambda s: s.order)
    _check_order(stages, path.name, reasons)

    if reasons:
        raise MarkupError(reasons)
    return Markup(tuple(stages), tuple(taxes))


def _stage_row(row: dict, where: str, reasons: list[str],
               stages: list[Stage]) -> None:
    name = _opt(row, "name")
    try:
        order = int(_opt(row, "stage"))
    except ValueError:
        reasons.append(f"{where}: stage が整数ではない ({_opt(row, 'stage')!r})")
        return
    if order < 1:
        reasons.append(f"{where}: stage は 1 以上 ({order})")
        return

    rate_raw, amount_raw = _opt(row, "rate"), _opt(row, "amount")
    if rate_raw and amount_raw:
        reasons.append(f"{where}: {name} に rate と amount の両方は書けない")
        return
    if not rate_raw and not amount_raw:
        reasons.append(f"{where}: {name} に rate も amount も無い")
        return

    base, tax = _opt(row, "base"), _opt(row, "tax") or TAXED
    if tax not in TAX_KINDS:
        reasons.append(f"{where}: {name} の税区分 {tax} は "
                       f"{' / '.join(TAX_KINDS)} のどれでもない")
        return

    rate = amount = None
    try:
        if rate_raw:
            rate = dec(rate_raw, field=f"{where} rate")
            if rate < 0 or rate > ONE:
                reasons.append(f"{where}: {name} の率 {rate} は 0 と 1 の間に無い")
                return
            if base not in BASES:
                reasons.append(f"{where}: {name} の基数 {base or '（空）'} は "
                               f"{' / '.join(BASES)} のどちらでもない")
                return
            if tax != TAXED:
                # 率の段は課税だけ（詳しくは ladder の docstring）
                reasons.append(f"{where}: {name} は率の段なので税区分は"
                               f"{TAXED}だけ。実費の段なら amount で書く")
                return
        else:
            amount = dec(amount_raw, field=f"{where} amount")
            if amount < 0:
                reasons.append(f"{where}: {name} の額は負にできない ({amount})")
                return
            if base:
                reasons.append(f"{where}: {name} は固定額の段なので基数は書けない")
                return
    except MoneyError as e:
        reasons.append(str(e))
        return

    as_of = _date(_opt(row, "as_of"), where, reasons)
    stages.append(Stage(order, name, base, rate, amount, _opt(row, "after"),
                        tax, _opt(row, "source"), as_of))


def _tax_row(row: dict, where: str, reasons: list[str],
             taxes: list[TaxRate]) -> None:
    for col in ("stage", "amount", "after"):
        if _opt(row, col):
            reasons.append(f"{where}: 消費税の行に {col} は書けない")
            return
    on = _opt(row, "base")
    if on not in TAX_KINDS:
        reasons.append(f"{where}: 消費税を掛ける区分 {on or '（空）'} は "
                       f"{' / '.join(TAX_KINDS)} のどれでもない")
        return
    if any(t.on == on for t in taxes):
        reasons.append(f"{where}: {on} の消費税の行が 2 行ある")
        return
    try:
        rate = dec(_opt(row, "rate"), field=f"{where} rate")
    except MoneyError as e:
        reasons.append(str(e))
        return
    if rate < 0 or rate > ONE:
        reasons.append(f"{where}: 税率 {rate} は 0 と 1 の間に無い")
        return
    taxes.append(TaxRate(on, rate, _opt(row, "source"),
                         _date(_opt(row, "as_of"), where, reasons)))


def _date(raw: str, where: str, reasons: list[str]) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        reasons.append(f"{where}: as_of が日付ではない ({raw})。YYYY-MM-DD で書く")
        return None


def _check_order(stages: list[Stage], name: str, reasons: list[str]) -> None:
    """段番号が 1 から連番か。**欠番も重複も断る。**"""
    seen = [s.order for s in stages]
    for want, got in enumerate(seen, start=1):
        if got != want:
            reasons.append(f"{name}: 段番号が 1 からの連番になっていない "
                           f"({', '.join(map(str, seen))})")
            return
    if stages and stages[0].base == RUNNING:
        reasons.append(f"{name}: 最初の段に「{RUNNING}」は使えない。"
                       "足す前の累計は無い")
