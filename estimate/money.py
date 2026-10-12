"""円の算術と丸め。**丸めの規約はここに集約する。**

金額を float で持たない。0.1 + 0.2 が 0.3 にならない型で単価を積むと合計が
1 円ずれる。1 円ずれた見積書は根拠を説明できないので、数量も単価も Decimal
で持つ。JSON は `parse_float=Decimal` で読み、CSV は文字列から直に起こす。

丸めるのは**行の金額だけ**。小計と合計は丸め済みの行を足すだけで、二度目の
丸めをしない。先に小計を丸めてから足すと、合計と行の和が食い違い、どの行から
来た差なのか説明できなくなる。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Iterable

#: 円の刻み。内装の見積りで銭を使うことはない
YEN = Decimal("1")

ZERO = Decimal("0")
ONE = Decimal("1")


class MoneyError(ValueError):
    """数として読めなかった。どの欄かを必ず添える。"""


def dec(value: object, *, field: str) -> Decimal:
    """数を Decimal で受ける。**float は文字列に落としてから渡す。**

    `Decimal(48.6)` は 48.600000000000001421... になる。JSON を
    `parse_float=Decimal` で読んでいれば float は来ないが、ここは外から
    呼ばれる入口なので受けたものを必ず文字列経由で畳む。
    """
    if isinstance(value, Decimal):
        return value
    if value is None or isinstance(value, bool):
        raise MoneyError(f"{field}: 数ではない ({value!r})")
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ArithmeticError) as e:
        raise MoneyError(f"{field}: 数として読めない ({value!r})") from e


def to_yen(value: Decimal) -> Decimal:
    """円未満を切り捨てる。**金額を作るのはここだけ。**

    積算の慣習に合わせて切り捨てる。四捨五入にすると、行数の多い見積りで
    合計が数量の合計より大きくなることがあり、客先で説明できない。
    """
    return value.quantize(YEN, rounding=ROUND_DOWN)


def by_rate(base: Decimal, rate: Decimal) -> Decimal:
    """基数に率を掛けて円にする。**段の金額を作るのはここだけ。**

    経費の段は、見積書の上では小計ではなく**新しく足す 1 行**なので、行と同じ
    丸め方（円未満切り捨て）をする。累計は丸め済みの段を足すだけで、二度目の
    丸めをしない。

    基数は常に丸め済みの整数（明細の課税分＝丸め済み行の和、累計＝丸め済み段の
    和）なので、丸めは構造的に「整数 × 率」の 1 回しか起きない。二重丸めの余地が
    無いのが要点で、基数に丸める前の値を使うと**表示された段の金額を足しても
    累計にならない**。
    """
    return to_yen(base * rate)


def total(values: Iterable[Decimal]) -> Decimal:
    """小計・合計。**足すだけで、丸めない。**"""
    out = ZERO
    for v in values:
        out += v
    return out
