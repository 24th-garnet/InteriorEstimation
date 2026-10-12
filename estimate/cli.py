"""コマンド。

```bash
uv run estimate run q.json                  # 端末に表で出す
uv run estimate run q.json --format json -o out.json
uv run estimate check q.json                # 数量と単価の突き合わせだけ
uv run estimate prices                      # 単価表を確かめる
```
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

from . import breakdown, ladder, markup, paper, price, quantity, report
from .money import by_rate, to_yen
from .price import TAXED

DEFAULT_PRICES = Path("prices.csv")
DEFAULT_TRADES = Path("trades.csv")
DEFAULT_MARKUP = Path("markup.csv")


def _book(args: argparse.Namespace) -> price.PriceBook:
    return price.load(args.prices, args.trades)


def _markup(args: argparse.Namespace) -> markup.Markup:
    """`--markup` を明示したときだけ、無ければ断る。"""
    given = args.markup != DEFAULT_MARKUP
    return markup.load(args.markup, required=given)


def _run(args: argparse.Namespace) -> int:
    book = _book(args)
    sheet = quantity.load(args.quantities)
    est = breakdown.build(sheet, book)

    m = _markup(args)
    quote = None if m.empty else ladder.build(est, m, sheet.discount)

    if args.format == "json":
        out = json.dumps(report.as_dict(est, quote=quote),
                         ensure_ascii=False, indent=2) + "\n"
    elif args.format == "csv":
        out = report.csv_text(est, quote=quote)
    elif args.format == "html":
        out = paper.html_sheet(est, quote=quote)
    else:
        out = report.text(est, quote=quote) + "\n"

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(out, encoding="utf-8")
        print(f"書き出した: {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(out)

    if args.strict:
        if est.unknown:
            print(f"単価の付かない行が {len(est.unknown)} 件あるので失敗にする",
                  file=sys.stderr)
            return 1
        if m.unsourced:
            print(f"率の出どころが書かれていない段が {len(m.unsourced)} 件"
                  "あるので失敗にする", file=sys.stderr)
            return 1
    return 0


def _check(args: argparse.Namespace) -> int:
    book = _book(args)
    sheet = quantity.load(args.quantities)
    missing = [l for l in sheet.lines if l.code not in book]
    print(f"{len(sheet.lines)} 行。単価の付く行 {len(sheet.lines) - len(missing)}、"
          f"付かない行 {len(missing)}")
    for l in missing:
        print(f"  単価なし  {l.code}  {report.num(l.qty)}")
    return 1 if missing else 0


def _prices(args: argparse.Namespace) -> int:
    book = _book(args)
    unsourced = [i for i in book.items.values() if not (i.source and i.as_of)]
    ungraded = [(i, [lab for col, lab in price.GRADE_COLUMNS
                     if not getattr(i, col)]) for i in book.items.values()]
    ungraded = [(i, blanks) for i, blanks in ungraded if blanks]
    print(f"{len(book.items)} 品目、{len(book.trades)} 職種")
    print(f"読めた任意列: {', '.join(book.optional) or '無し'}")

    where = (None, None)
    for item in book.items.values():
        if (item.division, item.section) != where:
            if item.division != where[0]:
                print(f"\n{item.division}")
            print(f"  {item.section}")
            where = (item.division, item.section)
        unit_labor = book.labor_unit(item)
        print(f"    {report.pad(item.code, 12)} {report.pad(item.name, 24)} "
              f"{report.pad(item.unit, 4)} "
              f"材料 {report.pad(report.yen(item.material), 9, right=True)} "
              f"施工 {report.pad(report.yen(unit_labor), 9, right=True)} "
              f"({report.num(item.labor)} 人工 × {item.trade or '—'}) "
              f"{report.pad(item.tax, 6)}")

    if unsourced:
        print(f"\n単価の出どころが書かれていない品目が {len(unsourced)} 件ある。"
              "後から金額の根拠をたどれない。")
        for i in unsourced:
            print(f"  {i.code}  {i.name}")

    if ungraded:
        print(f"\n認定・等級の欄が空いている品目が {len(ungraded)} 件ある。"
              "当たらないなら「対象外」と書く。")
        for i, blanks in ungraded:
            print(f"  {report.pad(i.code, 12)}{report.pad(i.name, 24)}"
                  f"（{'・'.join(blanks)}）")
    return 0


def _markup_cmd(args: argparse.Namespace) -> int:
    """経費表を確かめる。**任意の基数に段を積んで見せる。**

    率だけ並べても、実際にいくらになるかは見えない。基数を 1 つ与えて端から
    積むと、段の順と基数の選び方が金額をどう変えるかがその場で分かる。
    """
    m = _markup(args)
    if m.empty:
        print(f"経費表が無い: {args.markup}")
        return 0

    print(f"{len(m.stages)} 段、消費税 {len(m.taxes)} 件")
    running = args.base
    print(f"  {report.pad('基数', 16)}"
          f"{report.pad(report.yen(running), 14, right=True)}")

    for st in m.stages:
        base = args.base if st.base == markup.DIRECT else running
        amount = to_yen(st.amount) if st.fixed else by_rate(base, st.rate)
        if st.tax == TAXED:
            running += amount
        mid = "実費" if st.fixed else f"{report.num(st.rate * 100, 3)}%"
        print(f"  {report.pad(st.name, 16)}"
              f"{report.pad(report.yen(amount), 14, right=True)}  "
              f"{report.pad(mid, 6)} {st.base or '—'} → {st.after or '—'} "
              f"[{st.tax}]")

    print(f"  {report.pad('工事価格', 16)}"
          f"{report.pad(report.yen(running), 14, right=True)}")
    for t in m.taxes:
        print(f"  消費税（{t.on}） {report.num(t.rate * 100, 3)}%")

    if m.unsourced:
        print(f"\n率の出どころが書かれていない段が {len(m.unsourced)} 件ある。"
              "後から金額の根拠をたどれない。")
        for st in m.unsourced:
            print(f"  {st.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="estimate",
                                description="数量と単価から内装の見積りを組む")
    sub = p.add_subparsers(dest="cmd", required=True)

    # 単価表はどのコマンドでも要る。**サブコマンド側に置く**ので
    # `estimate run q.json --prices p.csv` と後ろに書ける
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--prices", type=Path, default=DEFAULT_PRICES,
                        help="単価表 CSV（既定 prices.csv）")
    common.add_argument("--trades", type=Path, default=DEFAULT_TRADES,
                        help="労務単価表 CSV（既定 trades.csv）")
    common.add_argument("--markup", type=Path, default=DEFAULT_MARKUP,
                        help="経費表 CSV（既定 markup.csv）。"
                             "無ければ明細の合計まで")

    r = sub.add_parser("run", help="見積りを組む", parents=[common])
    r.add_argument("quantities", type=Path, help="数量リスト JSON")
    r.add_argument("--format", choices=("text", "json", "csv", "html"),
                   default="text",
                   help="html は客先に出せる見積書。ブラウザで開いて印刷・PDF 保存")
    r.add_argument("-o", "--out", type=Path, help="書き出し先。省略すると標準出力")
    r.add_argument("--strict", action="store_true",
                   help="単価の付かない行があれば失敗にする")
    r.set_defaults(fn=_run)

    c = sub.add_parser("check", help="数量リストと単価表を突き合わせる",
                       parents=[common])
    c.add_argument("quantities", type=Path)
    c.set_defaults(fn=_check)

    s = sub.add_parser("prices", help="単価表を確かめる", parents=[common])
    s.set_defaults(fn=_prices)

    k = sub.add_parser("markup", help="経費表を確かめる", parents=[common])
    k.add_argument("--base", type=Decimal, default=Decimal("1000000"),
                   help="段を積んで見せるときの基数（既定 1,000,000）")
    k.set_defaults(fn=_markup_cmd)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except (price.PriceError, quantity.QuantityError,
            markup.MarkupError, ladder.LadderError) as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
