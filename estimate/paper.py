"""客先に出す見積書を HTML で組む。

**PDF は自前で書かない。** 日本語を PDF に埋めるには CID フォントのサブセット埋め込みが
要り、「外部依存なし」という方針と正面衝突する。ブラウザの「PDF として保存」なら
フォントも正しく出るし、そのまま印刷もできる（MiniCAD の `print.ts` と同じ判断）。

端末の表・JSON・CSV は作業用で、**客先に出せる形はこれだけ**。

## 何を載せるか

| | |
|---|---|
| 発行者 | 社名・住所・電話・担当・登録番号。**無ければ「発行者が未記入」と紙に出す** |
| 宛先・件名・見積番号・発行日・有効期限 | 頭書き |
| 内訳 | 科目 → 中科目 → 細目の 3 段 |
| 経費と消費税 | 経費表があるときだけ |

**金額を右に、名前を左に。** 見積書は目で金額を追う文書なので、桁を揃えることを
いちばん優先する。
"""
from __future__ import annotations

import html
from datetime import date
from decimal import Decimal

from .breakdown import Estimate
from .ladder import Quote
from .quantity import Header
from .report import num, yen

#: 用紙。A4 縦
PAPER = ("210mm", "297mm")

STYLE = """
  @page { size: A4 portrait; margin: 14mm 12mm; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: "Hiragino Sans", "Noto Sans JP", "Yu Gothic", sans-serif;
    font-size: 9.5pt; line-height: 1.5; color: #111;
  }
  h1 { font-size: 16pt; letter-spacing: .3em; text-align: center;
       margin: 0 0 8mm; font-weight: 600; }
  .head { display: flex; justify-content: space-between; gap: 8mm;
          margin-bottom: 6mm; }
  .head .to { flex: 1; }
  .head .to .client { font-size: 12pt; border-bottom: 1px solid #111;
                      padding-bottom: 1mm; margin-bottom: 2mm; }
  .head .from { width: 62mm; font-size: 8.5pt; }
  .head .from .name { font-size: 10.5pt; font-weight: 600; }
  .meta { font-size: 8.5pt; color: #333; }
  .meta div { white-space: nowrap; }
  .total-box { border: 1.2px solid #111; padding: 2.5mm 4mm; margin: 4mm 0 6mm;
               display: flex; justify-content: space-between; align-items: baseline; }
  .total-box .label { font-size: 10pt; }
  .total-box .value { font-size: 16pt; font-weight: 600; }
  table { width: 100%; border-collapse: collapse; }
  th, td { padding: 1.2mm 2mm; border-bottom: .5px solid #bbb;
           vertical-align: top; }
  th { background: #f2f2f2; font-weight: 600; text-align: left;
       border-bottom: 1px solid #111; white-space: nowrap; }
  td.n, th.n { text-align: right; white-space: nowrap;
               font-variant-numeric: tabular-nums; }
  tr.division > td { background: #ececec; font-weight: 600;
                     border-top: .8px solid #111; }
  tr.section > td { background: #f7f7f7; }
  tr.item td.name { padding-left: 6mm; }
  tr.sum > td { font-weight: 600; }
  tr.grand > td { border-top: 1.2px solid #111; border-bottom: 1.2px solid #111;
                  font-size: 11pt; font-weight: 600; }
  .note { color: #555; font-size: 8pt; padding-left: 6mm; }
  .ladder { margin-top: 6mm; }
  .caution { margin-top: 6mm; font-size: 8pt; color: #555; }
  .caution strong { color: #a00; }
"""


def _e(text: str) -> str:
    return html.escape(text or "")


def _iso(d: date | None) -> str:
    return d.isoformat() if d else ""


def _head(h: Header) -> str:
    """宛先と発行者。"""
    meta = [f"見積番号 {_e(h.number)}" if h.number else "",
            f"第 {h.revision} 版" if h.revision > 1 else "",
            f"発行日 {_iso(h.issued)}" if h.issued else "",
            f"有効期限 {_iso(h.valid_until)}" if h.valid_until else ""]
    i = h.issuer
    issuer = [f'<div class="name">{_e(i.name)}</div>' if i.name
              else '<div class="name">（発行者が未記入）</div>']
    for value in (i.address, i.tel):
        if value:
            issuer.append(f"<div>{_e(value)}</div>")
    if i.person:
        issuer.append(f"<div>担当 {_e(i.person)}</div>")
    if i.registration:
        issuer.append(f"<div>登録番号 {_e(i.registration)}</div>")

    return f"""<div class="head">
  <div class="to">
    <div class="client">{_e(h.client) or "&nbsp;"} 御中</div>
    <div>{_e(h.subject)}</div>
  </div>
  <div class="from">
    {''.join(issuer)}
    <div class="meta">{''.join(f'<div>{m}</div>' for m in meta if m)}</div>
  </div>
</div>"""


def _rows(est: Estimate) -> str:
    out: list[str] = []
    for d in est.divisions:
        out.append(f'<tr class="division"><td colspan="5">{_e(d.name)}</td></tr>')
        for s in d.sections:
            out.append(f'<tr class="section"><td colspan="5">{_e(s.name)}</td></tr>')
            for r in s.rows:
                out.append(
                    f'<tr class="item"><td class="name">{_e(r.name)}</td>'
                    f'<td class="n">{num(r.qty)}</td><td>{_e(r.unit)}</td>'
                    f'<td class="n">{yen(r.material_unit + r.labor_unit)}</td>'
                    f'<td class="n">{yen(r.amount)}</td></tr>')
                if r.note or r.spec:
                    bits = " / ".join(x for x in (r.spec, r.note) if x)
                    out.append(f'<tr><td class="note" colspan="5">{_e(bits)}</td></tr>')
            out.append(f'<tr class="sum"><td colspan="4">{_e(s.name)} 計</td>'
                       f'<td class="n">{yen(s.amount)}</td></tr>')
        out.append(f'<tr class="sum"><td colspan="4">{_e(d.name)} 計</td>'
                   f'<td class="n">{yen(d.amount)}</td></tr>')
    out.append(f'<tr class="grand"><td colspan="4">合計</td>'
               f'<td class="n">{yen(est.amount)}</td></tr>')
    return "\n".join(out)


def _ladder(q: Quote) -> str:
    rows = [f'<tr><td>課税分</td><td class="n">{yen(q.direct_taxable)}</td></tr>']
    for s in q.steps:
        label = _e(s.name)
        if s.rate is not None:
            label += f"（{num(s.rate * 100, 3)}%）"
        rows.append(f'<tr><td>{label}</td><td class="n">{yen(s.amount)}</td></tr>')
        if s.after:
            rows.append(f'<tr class="sum"><td>{_e(s.after)}</td>'
                        f'<td class="n">{yen(s.running)}</td></tr>')
    if q.cut:
        rows.append(f'<tr><td>{_e(q.cut.name)}</td>'
                    f'<td class="n">-{yen(q.cut.amount)}</td></tr>')
        rows.append(f'<tr class="sum"><td>課税対価の額</td>'
                    f'<td class="n">{yen(q.taxable)}</td></tr>')
    for t in q.taxes:
        rows.append(f'<tr><td>消費税（{_e(t.on)} {num(t.rate * 100, 3)}%）</td>'
                    f'<td class="n">{yen(t.amount)}</td></tr>')
    for kind, amount in q.untaxed.items():
        rows.append(f'<tr><td>{_e(kind)}</td><td class="n">{yen(amount)}</td></tr>')
    rows.append(f'<tr class="grand"><td>見積合計</td>'
                f'<td class="n">{yen(q.total)}</td></tr>')
    return ('<table class="ladder"><col><col style="width:38mm">'
            + "\n".join(rows) + "</table>")


def _cautions(est: Estimate, h: Header) -> str:
    """紙に残す注意書き。**黙って出さない。**"""
    out: list[str] = []
    if not h.issuer.named:
        out.append("<strong>発行者が未記入です。</strong>"
                   "このままでは見積書として出せません。")
    if not est.complete:
        out.append(f"<strong>単価の付かない行が {len(est.unknown)} 件あります。</strong>"
                   "合計はその分だけ足りません。")
    if est.ungraded:
        out.append(f"認定・等級の欄が空いている品目が {len(est.ungraded)} 件あります。"
                   "内装制限が掛かるかはこの見積りでは判定していません。")
    if not out:
        return ""
    return ('<div class="caution">'
            + "".join(f"<div>{line}</div>" for line in out) + "</div>")


def html_sheet(est: Estimate, *, quote: Quote | None = None) -> str:
    """見積書 1 枚。"""
    h = est.header
    total = quote.total if quote is not None else est.amount
    label = "見積合計（税込）" if (quote is not None and quote.taxed) else "合計"

    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>{_e(h.subject or est.name or "御見積書")}</title>
<style>{STYLE}</style>
</head>
<body>
<h1>御見積書</h1>
{_head(h)}
<div class="total-box">
  <span class="label">{label}</span>
  <span class="value">¥{yen(total)}</span>
</div>
<table>
<thead><tr><th>品目</th><th class="n">数量</th><th>単位</th>
<th class="n">単価</th><th class="n">金額</th></tr></thead>
<tbody>
{_rows(est)}
</tbody>
</table>
{_ladder(quote) if quote is not None else ""}
{_cautions(est, h)}
</body>
</html>
"""
