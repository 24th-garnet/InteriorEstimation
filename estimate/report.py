"""明細を人が読む形と、機械が読む形に落とす。

**端末の表は全角を 2 で数える。** 品目名が日本語なので、文字数で揃えると列が
必ずずれる。`unicodedata.east_asian_width` が W / F を返す文字を 2 幅として
数える。

機械向けの形では**金額を整数、数量と人工を文字列**で出す。円は整数なので
数として出して安全だが、数量の 48.6 を JSON の数にすると読み手が float で
受けて末尾が濁る。受け手が Decimal で読み直せるよう文字列で渡す。
"""
from __future__ import annotations

import csv
import io
import unicodedata
from collections import Counter
from datetime import date
from decimal import Decimal

from .breakdown import Division, Estimate, Row, Section
from .ladder import Quote
from .quantity import Header

#: 明細の列。(見出し, 幅, 右寄せか)
COLUMNS = (
    ("品目", 26, False),
    ("単位", 4, False),
    ("数量", 9, True),
    ("材料単価", 10, True),
    ("材料費", 11, True),
    ("人工", 7, True),
    ("施工費", 11, True),
    ("金額", 12, True),
)

#: 細目は中科目の下に 1 段下げて置く
INDENT = "    "


def width(s: str) -> int:
    """全角を 2、半角を 1 で数える。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s: str, n: int, *, right: bool = False) -> str:
    """表示幅 `n` に合わせる。**溢れたら切る。** 折り返すと行の対応が崩れる。"""
    while width(s) > n:
        s = s[:-1]
    fill = " " * max(0, n - width(s))
    return fill + s if right else s + fill


def num(d: Decimal, places: int = 3) -> str:
    """数量・人工・率。**末尾の 0 を落とすが、指数にはしない。**"""
    s = format(d.quantize(Decimal(1).scaleb(-places)), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def yen(d: Decimal) -> str:
    """円。3 桁区切り。"""
    return f"{int(d):,}"


def _line(cells: list[str]) -> str:
    return " ".join(pad(c, n, right=r)
                    for c, (_, n, r) in zip(cells, COLUMNS)).rstrip()


def _row_cells(r: Row, indent: str = "") -> list[str]:
    return [indent + r.name, r.unit, num(r.qty), yen(r.material_unit),
            yen(r.material), num(r.days), yen(r.labor), yen(r.amount)]


def _sum_cells(label: str, obj, indent: str = "") -> list[str]:
    """小計のラベルは**品目の欄に置く。**

    単価の欄に置くと、科目名の長さが列幅を超えて切れる（「壁・天井仕上 計」が
    「壁・天井仕」になる）。内訳書の標準書式でも名称は一番左の欄にある。
    """
    return [indent + label, "", "", "", yen(obj.material), num(obj.days),
            yen(obj.labor), yen(obj.amount)]


TOTAL_WIDTH = sum(n for _, n, _ in COLUMNS) + len(COLUMNS) - 1


def _header_lines(h: Header, name: str, scan_id: str) -> list[str]:
    """見積書としての頭書き。"""
    out: list[str] = []
    title = h.subject or name or scan_id or "見積"
    out.append(title)

    if h.identified:
        bits = [f"見積番号 {h.number}"]
        if h.revision > 1:
            bits.append(f"第 {h.revision} 版")
        bits.append(f"発行 {h.issued}")
        if h.valid_until:
            bits.append(f"有効期限 {h.valid_until}")
        out.append("  ".join(bits))
    if h.client:
        out.append(f"{h.client} 御中")
    if scan_id:
        out.append(f"対象 {scan_id}")
    if not h.identified:
        out.append("（見積番号なし。見積書として出すには estimate を付ける）")
    return out


def text(est: Estimate, *, notes: bool = True,
         quote: Quote | None = None) -> str:
    """端末に出す表。"""
    out = _header_lines(est.header, est.name, est.scan_id)
    out.append("")
    out.append(_line([c for c, _, _ in COLUMNS]))
    out.append("=" * TOTAL_WIDTH)

    for d in est.divisions:
        out.append(d.name)
        for s in d.sections:
            out.append("  " + s.name)
            for r in s.rows:
                out.append(_line(_row_cells(r, INDENT)))
                for extra in _row_notes(r, notes):
                    out.append(INDENT + "  └ " + extra)
            out.append(_line(_sum_cells(f"{s.name} 計", s, "  ")))
        out.append(_line(_sum_cells(f"{d.name} 計", d)))
        out.append("-" * TOTAL_WIDTH)

    # 「直接工事費」とは名乗らない。諸費用の科目を単価表に置けるので、
    # 何が入っているかは表を組んだ人しか知らない
    out.append(_line(_sum_cells("合計", est)))

    if quote is not None:
        out += _quote_lines(quote)
    else:
        by_tax = est.by_tax
        if len(by_tax) > 1:
            out.append("")
            out.append("税区分ごと（消費税額はここでは出さない）")
            for kind, amount in by_tax.items():
                out.append(f"  {pad(kind, 6)} {pad(yen(amount), 12, right=True)}")
        out.append("")
        # 「直接工事費まで」とは書かない。諸費用の科目を単価表に置けるので、
        # 明細の合計が直接工事費とは限らない（総計を「合計」としか名乗らないのと同じ）
        out.append("経費表が無いので明細の合計まで。"
                   "markup.csv を置くと諸経費と消費税が乗る")

    if est.unknown:
        out.append("")
        out.append(f"単価が付かなかった行が {len(est.unknown)} 件ある。"
                   "合計はその分だけ足りない。")
        for u in est.unknown:
            out.append(f"  {u.code}  {num(u.qty)}"
                       + (f"  {u.note}" if u.note else ""))

    if est.unsourced:
        out.append("")
        out.append(f"単価の出どころが書かれていない行が {len(est.unsourced)} 件ある。"
                   "後から金額の根拠をたどれない。")
        for r in est.unsourced[:10]:
            out.append(f"  {r.code}  {r.name}")
        if len(est.unsourced) > 10:
            out.append(f"  ほか {len(est.unsourced) - 10} 件")

    out += _grade_lines(est)
    return "\n".join(out)


def _grade_lines(est: Estimate) -> list[str]:
    """認定・等級の報告。**判定はしない。書いてあるかだけを見る。**"""
    out: list[str] = []
    if est.ungraded:
        tally = Counter(label for r in est.ungraded for label in r.blank_grades)
        out.append("")
        out.append(f"認定・等級の欄が空いている行が {len(est.ungraded)} 件ある。")
        out.append("内装制限が掛かるかは、用途・規模・階数を知らないここでは"
                   "判定できない。")
        out.append("  " + " / ".join(f"{k} {v} 件" for k, v in tally.items()))
        for r in est.ungraded[:10]:
            out.append(f"  {pad(r.code, 12)}{pad(r.name, 24)}"
                       f"（{'・'.join(r.blank_grades)}）")
        if len(est.ungraded) > 10:
            out.append(f"  ほか {len(est.ungraded) - 10} 件")
        out.append("当たらないと判断した欄には「対象外」と書く。空欄のままだと、"
                   "見ていないのか")
        out.append("当たらないのかが見積書から分からない。")

    if est.mismatched:
        out.append("")
        out.append(f"認定番号と不燃区分が食い違う行が {len(est.mismatched)} 件ある。"
                   "どちらが正かはここでは決められない。")
        for r in est.mismatched:
            out.append(f"  {pad(r.code, 12)}{r.cert_mismatch}")
    return out


def _row_notes(r: Row, notes: bool) -> list[str]:
    out = []
    if notes and r.note:
        out.append(r.note)
    if r.loss:
        out.append(f"ロス {num(r.loss * 100, 1)}% → 材料 {num(r.qty_with_loss)} {r.unit}")
    if notes and r.spec:
        out.append(r.spec)
    if notes and r.source:
        out.append(f"単価 {r.source}" + (f"（{r.as_of}）" if r.as_of else ""))
    return out


def _quote_lines(q: Quote) -> list[str]:
    """ラダー。段は字下げ 2、節目は字下げ 0（明細の中科目／科目と同じ上下関係）。"""
    out = ["", "経費と消費税"]

    def money(label: str, amount: Decimal, mid: str = "", indent: str = "") -> str:
        cells = [indent + label, "", "", mid, "", "", "", yen(amount)]
        return _line(cells)

    # 「課税分」と呼ぶ。「直接工事費」とは呼ばない（諸費用の科目を置けるため）
    out.append(money("課税分", q.direct_taxable, indent="  "))
    for s in q.steps:
        mid = f"{num(s.rate * 100, 3)}%" if s.rate is not None else "実費"
        out.append(money(s.name, s.amount, mid, indent="  "))
        if s.base_name:
            out.append(INDENT + f"  └ {s.base_name} {yen(s.base)} に掛ける")
        if s.tax != "課税":
            out.append(INDENT + f"  └ {s.tax}。累計には入らない")
        if s.after:
            out.append(money(s.after, s.running))

    if q.cut:
        out.append(money(q.cut.name, -q.cut.amount, indent="  "))
        if q.cut.target is not None:
            out.append(INDENT + f"  └ {q.cut.basis} {yen(q.cut.target)} ちょうどに合わせた")
        out.append(money("課税対価の額", q.taxable))

    for t in q.taxes:
        out.append(money(f"消費税（{t.on}）", t.amount,
                         f"{num(t.rate * 100, 3)}%", indent="  "))
    for kind, amount in q.untaxed.items():
        out.append(money(kind, amount, indent="  "))

    out.append("=" * TOTAL_WIDTH)
    out.append(money("見積合計（税込）" if q.taxed else "見積合計（税抜）", q.total))
    return out


def as_dict(est: Estimate, *, quote: Quote | None = None) -> dict:
    """機械向けの形。"""
    h = est.header
    return {
        "estimate": {
            "number": h.number,
            "revision": h.revision,
            "issued": _iso(h.issued),
            "valid_until": _iso(h.valid_until),
            "client": h.client,
            "subject": h.subject,
            "identified": h.identified,
        },
        "scan_id": est.scan_id,
        "name": est.name,
        "complete": est.complete,
        "divisions": [_division_dict(d) for d in est.divisions],
        "unknown": [{"code": u.code, "qty": num(u.qty), "note": u.note}
                    for u in est.unknown],
        "by_tax": {k: int(v) for k, v in est.by_tax.items()},
        "material": int(est.material),
        "labor": int(est.labor),
        "days": num(est.days),
        "amount": int(est.amount),
        "quote": _quote_dict(quote) if quote is not None else None,
    }


def _quote_dict(q: Quote) -> dict:
    return {
        "direct_taxable": int(q.direct_taxable),
        "steps": [{"name": s.name, "base": s.base_name,
                   "base_amount": int(s.base),
                   "rate": num(s.rate, 6) if s.rate is not None else None,
                   "amount": int(s.amount), "running": int(s.running),
                   "after": s.after, "tax": s.tax} for s in q.steps],
        "works": int(q.works),
        "discount": None if q.cut is None else {
            "name": q.cut.name, "amount": int(q.cut.amount),
            "target": int(q.cut.target) if q.cut.target is not None else None,
            "basis": q.cut.basis},
        "taxable": int(q.taxable),
        "untaxed": {k: int(v) for k, v in q.untaxed.items()},
        "taxes": [{"on": t.on, "rate": num(t.rate, 6),
                   "base": int(t.base), "amount": int(t.amount)}
                  for t in q.taxes],
        "subtotal": int(q.subtotal),
        "tax_total": int(q.tax_total),
        "total": int(q.total),
        "taxed": q.taxed,
    }


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _division_dict(d: Division) -> dict:
    return {"name": d.name,
            "sections": [_section_dict(s) for s in d.sections],
            "material": int(d.material), "labor": int(d.labor),
            "days": num(d.days), "amount": int(d.amount)}


def _section_dict(s: Section) -> dict:
    return {"name": s.name, "rows": [_row_dict(r) for r in s.rows],
            "material": int(s.material), "labor": int(s.labor),
            "days": num(s.days), "amount": int(s.amount)}


def _row_dict(r: Row) -> dict:
    return {
        "code": r.code, "name": r.name, "unit": r.unit, "note": r.note,
        "qty": num(r.qty), "loss": num(r.loss), "qty_with_loss": num(r.qty_with_loss),
        "material_unit": int(r.material_unit), "material": int(r.material),
        "trade": r.trade, "days": num(r.days),
        "labor_unit": int(r.labor_unit), "labor": int(r.labor),
        "amount": int(r.amount), "tax": r.tax,
        "source": r.source, "as_of": _iso(r.as_of),
        "fire": r.fire, "fire_no": r.fire_no, "f_star": r.f_star,
        "flame": r.flame, "spec": r.spec,
    }


CSV_COLUMNS = ("division", "section", "code", "name", "unit", "qty", "loss",
               "qty_with_loss", "material_unit", "material", "trade", "days",
               "labor_unit", "labor", "amount", "tax", "source", "as_of",
               "fire", "fire_no", "f_star", "flame", "spec", "note")


def csv_text(est: Estimate, *, quote: Quote | None = None) -> str:
    """表計算へ渡す形。**明細と段だけ。小計は入れない。**

    小計の行を混ぜると、取り込んだ先で合計を取り直したときに二重に数える。

    **段の金額は小計ではなく、直接工事費の上に新しく足す額**なので入れる。
    節目（純工事費・工事原価・工事価格）と累計は小計なので入れない。この線を
    守ると、取り込んだ先で `amount` を合計したとき税込合計にちょうど一致する。

    ラダーを一切出さない案もあったが、表計算で合計を取った人の手元の数が
    見積書と合わなくなる。**合わない数が 2 つある方が危ない。**
    """
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_COLUMNS)
    for d in est.divisions:
        for s in d.sections:
            for r in s.rows:
                w.writerow([d.name, s.name, r.code, r.name, r.unit, num(r.qty),
                            num(r.loss), num(r.qty_with_loss), int(r.material_unit),
                            int(r.material), r.trade, num(r.days),
                            int(r.labor_unit), int(r.labor), int(r.amount),
                            r.tax, r.source, _iso(r.as_of) or "",
                            r.fire, r.fire_no, r.f_star, r.flame, r.spec,
                            r.note])
    for u in est.unknown:
        w.writerow(["単価なし", "", u.code, "", "", num(u.qty)]
                   + [""] * (len(CSV_COLUMNS) - 7) + [u.note])
    if quote is not None:
        for row in _quote_rows(quote):
            w.writerow(row)
    return buf.getvalue()


def _quote_rows(q: Quote) -> list[list]:
    """段・値引き・消費税の行。**節目と累計は入れない。**"""
    blank = [""] * 8          # material_unit 〜 as_of の手前まで埋める用
    out: list[list] = []

    def row(div: str, sec: str, name: str, amount: Decimal, note: str) -> list:
        return [div, sec, "", name, "式", "1", "", "", "", "", "", "", "",
                "", int(amount), "課税", "", "", "", "", "", "", "", note]

    for s in q.steps:
        note = (f"率 {num(s.rate * 100, 3)}% × {yen(s.base)}"
                if s.rate is not None else "実費")
        r = row("経費", s.base_name or "実費", s.name, s.amount, note)
        r[15] = s.tax
        out.append(r)
    if q.cut:
        note = (f"{q.cut.basis} {yen(q.cut.target)} ちょうどに合わせた"
                if q.cut.target is not None else "")
        out.append(row("値引き", "", q.cut.name, -q.cut.amount, note))
    for t in q.taxes:
        out.append(row("消費税", t.on, f"消費税（{t.on}）", t.amount,
                       f"率 {num(t.rate * 100, 3)}% × {yen(t.base)}"))
    return out
