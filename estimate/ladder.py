"""直接工事費の上に段を積む。**純関数だけ。ファイルも時刻も見ない。**

```
直接工事費（課税分）
 ＋共通仮設費   = 直接工事費 × 率
 ＝純工事費
 ＋現場管理費   = 純工事費 × 率        ← 基数が直前の累計
 ＝工事原価
 ＋一般管理費等 = 工事原価 × 率
 ＝工事価格
```

**率の基数は課税分だけ。** 非課税（保険料）と不課税（立替金）は段に触れず、
税抜合計で合流する。立替金は自治体に納める実費を預かっただけなので、そこに
管理費を乗せた瞬間に立替ではなくなる。保険料の手配に手数料を取りたいなら、
固定額の段か課税の品目として**別の行で**見せる。

だから**率の段の税区分は課税だけ**で、非課税・不課税を名乗れるのは固定額の段
（確認申請手数料のような実費）に限る。これは「ロス率は材料にだけ掛ける」と同じ
性質の決めで、設定で選べるようにすると誤った方を選べてしまう。

**段は行である。** 見積書の上で共通仮設費 80,180 は小計ではなく新しく足す 1 行
なので、行と同じく 1 回だけ丸め（`money.by_rate`）、累計は丸め済みの段を足す
だけで丸め直さない。基数は常に丸め済みの整数なので、丸めは構造的に
「整数 × 率」の 1 回しか起きない。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .breakdown import Estimate
from .markup import DIRECT, RUNNING, Markup
from .money import ZERO, by_rate, to_yen, total
from .price import TAXED
from .quantity import GROSS, Discount


class LadderError(ValueError):
    """段を積めない。"""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("\n".join(reasons))
        self.reasons = reasons


@dataclass(frozen=True)
class Step:
    """ラダーの 1 段。金額は確定済み（丸め済み）。"""

    name: str
    #: 基数の呼び名（直接工事費 / 累計 / 空）
    base_name: str
    #: 基数の額。**「この 130,474 は何に 9.5% を掛けたのか」を残すために持つ。**
    #: 率だけでは後から検算できない
    base: Decimal
    rate: Decimal | None
    amount: Decimal
    #: この段を足したあとの課税分の累計
    running: Decimal
    #: 累計の呼び名。空なら節目を出さない
    after: str
    tax: str

    @property
    def fixed(self) -> bool:
        return self.rate is None


@dataclass(frozen=True)
class Cut:
    """値引き。**課税分からだけ引く。**

    課税売上に係る対価の返還なので、課税対価を減らしてから消費税を掛ける。
    """

    name: str
    #: 値引き額（正の数で持つ。引くのは Quote 側）
    amount: Decimal
    target: Decimal | None = None
    basis: str = ""


@dataclass(frozen=True)
class Tax:
    """消費税。税区分ごとに 1 件。"""

    on: str
    rate: Decimal
    #: 税の基数（値引き後の課税対価）
    base: Decimal
    amount: Decimal


@dataclass(frozen=True)
class Quote:
    """直接工事費の上に乗る段。**明細は持たない。**

    `Estimate` は直接工事費までが担当という境界を動かさないので、その上は別の
    値として持つ。`Estimate` から読むのは `by_tax` だけ。
    """

    direct: dict[str, Decimal]
    steps: tuple[Step, ...]
    cut: Cut | None
    taxes: tuple[Tax, ...]

    @property
    def direct_taxable(self) -> Decimal:
        """ラダーの基数。明細の課税分。

        **「直接工事費」とは名乗らない。** 単価表に課税の諸費用科目を置けるので、
        明細の課税分は直接工事費とは限らない。総計を「合計」としか名乗らないのと
        同じ理由。
        """
        return self.direct.get(TAXED, ZERO)

    @property
    def works(self) -> Decimal:
        """工事価格（課税分、値引き前）。段が無ければ明細の課税分そのまま。"""
        return self.steps[-1].running if self.steps else self.direct_taxable

    @property
    def taxable(self) -> Decimal:
        """課税対価の額（値引き後）。消費税の基数。"""
        return self.works - (self.cut.amount if self.cut else ZERO)

    @property
    def untaxed(self) -> dict[str, Decimal]:
        """ラダーを素通りした分。固定額の段の非課税・不課税もここに合流する。"""
        out = {k: v for k, v in self.direct.items() if k != TAXED and v}
        for s in self.steps:
            if s.tax != TAXED:
                out[s.tax] = out.get(s.tax, ZERO) + s.amount
        return out

    @property
    def subtotal(self) -> Decimal:
        """税抜合計。"""
        return self.taxable + total(self.untaxed.values())

    @property
    def tax_total(self) -> Decimal:
        return total(t.amount for t in self.taxes)

    @property
    def total(self) -> Decimal:
        """見積合計（税込）。"""
        return self.subtotal + self.tax_total

    @property
    def taxed(self) -> bool:
        """消費税を出せるか。経費表に消費税の行が無ければ False。"""
        return bool(self.taxes)


def steps(direct_taxable: Decimal, markup: Markup) -> tuple[Step, ...]:
    """段を順に積む。**累計は丸め済みの段を足すだけ。**"""
    out: list[Step] = []
    running = direct_taxable
    for st in markup.stages:
        if st.fixed:
            amount, base, base_name = to_yen(st.amount), ZERO, ""
        else:
            base = direct_taxable if st.base == DIRECT else running
            base_name = DIRECT if st.base == DIRECT else RUNNING
            amount = by_rate(base, st.rate)
        if st.tax == TAXED:
            running += amount
        out.append(Step(st.name, base_name, base, st.rate, amount,
                        running, st.after, st.tax))
    return tuple(out)


def cut(works: Decimal, discount: Discount | None,
        rate: Decimal | None, untaxed: Decimal) -> Cut | None:
    """値引きを額に直す。**端数調整は整数で解く。**

    税込を目標にすると、課税対価を 1 増やしたとき税込は 1 か 2 増えるので、
    **到達できない目標がある**（税率 10% で測ると 9.1%）。1 円ずれた額を黙って
    返さず、到達できる前後の額を添えて断る。
    """
    if discount is None:
        return None
    if discount.amount is not None:
        amount = to_yen(discount.amount)
        _check(works, amount, discount.name)
        return Cut(discount.name, amount)

    target = discount.target
    if discount.basis != GROSS or rate is None:
        # 税抜の目標、または消費税を出さない表。そのまま引ける
        want = target - untaxed
        amount = works - want
        _check(works, amount, discount.name,
               extra=f"（{discount.basis} {target:,} に合わせる）")
        return Cut(discount.name, amount, target, discount.basis)

    def gross(x: Decimal) -> Decimal:
        return x + by_rate(x, rate) + untaxed

    # 解析解から ±2 だけ歩いて、ちょうど当たる課税対価を探す
    start = int((target - untaxed) / (1 + rate))
    for x in range(start - 2, start + 3):
        if x > 0 and gross(Decimal(x)) == target:
            amount = works - Decimal(x)
            _check(works, amount, discount.name,
                   extra=f"（税込 {target:,} に合わせる）")
            return Cut(discount.name, amount, target, discount.basis)

    near = sorted({int(gross(Decimal(x)))
                   for x in range(start - 3, start + 4) if x > 0})
    below = [n for n in near if n < target]
    above = [n for n in near if n > target]
    hint = " か ".join(f"{n:,}" for n in (below[-1:] + above[:1]))
    raise LadderError([
        f"値引き: 税込 {target:,} ちょうどにはできない。{hint} になる"])


def _check(works: Decimal, amount: Decimal, name: str, extra: str = "") -> None:
    if amount <= 0:
        raise LadderError([f"値引き: {name} が 0 以下になる ({amount:,}){extra}。"
                           "値上げは値引きで書けない"])
    if amount > works:
        raise LadderError([f"値引き: {name} {amount:,} が工事価格 {works:,} を"
                           f"超えている{extra}"])


def build(est: Estimate, markup: Markup,
          discount: Discount | None = None) -> Quote:
    """直接工事費の上に段を積む。**Estimate から読むのは by_tax だけ。**"""
    direct = est.by_tax
    taxable = direct.get(TAXED, ZERO)
    built = steps(taxable, markup)

    # 値引きを決めるには工事価格と素通り分が要るので、税を付けずに一度組む
    bare = Quote(direct, built, None, ())
    c = cut(bare.works, discount, markup.rate_for(TAXED),
            total(bare.untaxed.values()))
    q = Quote(direct, built, c, ())

    taxes: list[Tax] = []
    rate = markup.rate_for(TAXED)
    if rate is not None:
        taxes.append(Tax(TAXED, rate, q.taxable, by_rate(q.taxable, rate)))
    for kind, amount in q.untaxed.items():
        kr = markup.rate_for(kind)
        if kr is not None:
            taxes.append(Tax(kind, kr, amount, by_rate(amount, kr)))
    return Quote(direct, built, c, tuple(taxes))
