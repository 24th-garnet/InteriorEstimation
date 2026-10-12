"""数量リストの読み込みと検証。**上流に依存しない形だけを受ける。**

受けるのは「品目コードと数量」の並びだけ。スキャンの `room.json` も図面の
`plan.json` も、呼ぶ側で**この形に直してから**渡す。上流の形を直に受けると、
上流が増えるたびに読み方が増え、同じ見積りが入口の数だけ別の道を通ることに
なる。

```json
{
  "scan_id": "room-0a3f",
  "name": "ワンルーム 改装",
  "items": [
    {"code": "WC-1000", "qty": 48.6, "note": "開口部 2 箇所を差し引き済み"},
    {"code": "SOFA-3P", "qty": 1}
  ]
}
```

**数量の単位は書かない。** 単位は単価表が持っている。両方が持つと、食い違った
ときにどちらが正かを決められない。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from .money import MoneyError, dec


class QuantityError(ValueError):
    """数量リストが読めない。**理由を全部ためてから投げる。**"""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("\n".join(reasons))
        self.reasons = reasons


@dataclass(frozen=True)
class Line:
    """内訳の 1 行。"""

    code: str
    qty: Decimal
    note: str = ""


@dataclass(frozen=True)
class Issuer:
    """発行者。**宛先があるのに発行者が無い文書は見積書として成立しない。**

    `registration` は適格請求書発行事業者の登録番号（`T` ＋ 13 桁）。見積書は
    適格請求書ではないので必須ではないが、**後から請求書に起こすときに要る**ので
    ここで持っておく。番号の検査はしない——形が変わる可能性のあるものを、
    こちらが決め打ちで断るべきではない。
    """

    name: str = ""
    address: str = ""
    tel: str = ""
    person: str = ""
    #: 適格請求書発行事業者の登録番号
    registration: str = ""

    @property
    def named(self) -> bool:
        return bool(self.name)


@dataclass(frozen=True)
class Header:
    """見積書としての身分証明。

    **明細を作ってから足せない。** 既に出した見積りを後から識別できないし、
    どの単価で出したのかも復元できない。電子帳簿保存法が電子で授受した
    見積書に求める検索の手がかりは**取引年月日・取引金額・取引先**の 3 つで、
    金額は明細から出るが、残り 2 つはここにしか無い。
    """

    #: 見積番号
    number: str = ""
    #: 版。出し直すたびに上げる
    revision: int = 1
    #: 発行日（取引年月日）
    issued: date | None = None
    #: 有効期限
    valid_until: date | None = None
    #: 取引先
    client: str = ""
    #: 件名
    subject: str = ""
    #: 発行者
    issuer: Issuer = Issuer()

    @property
    def identified(self) -> bool:
        """見積書として名乗れるか。"""
        return bool(self.number and self.issued)

    @property
    def deliverable(self) -> bool:
        """客先に出せるか。**番号と発行日に加えて、発行者が要る。**"""
        return self.identified and self.issuer.named


#: 端数調整の基準
GROSS, NET = "税込", "税抜"
BASES = (GROSS, NET)


@dataclass(frozen=True)
class Discount:
    """案件ごとの値引き。**額で書くのを勧める。**

    端数調整（「税込 1,810,000 ちょうどに」）も書けるが、目標額から逆算した
    値引き額は税率に依存して決まるので、税率が変わると過去の見積りを同じ数で
    再現できない。額で書いてあれば何年後でも同じ数が出る。
    """

    name: str = "お値引き"
    #: 値引き額（円、正の数）
    amount: Decimal | None = None
    #: 端数調整の目標額。amount と**両方は書けない**
    target: Decimal | None = None
    #: 目標額の基準
    basis: str = GROSS


@dataclass(frozen=True)
class Sheet:
    """1 スキャン分の数量リスト。"""

    scan_id: str
    name: str
    lines: tuple[Line, ...]
    header: Header = Header()
    #: 値引き。**Header には入れない**（身分証明に金額を混ぜない）
    discount: Discount | None = None


def parse(data: object, *, where: str = "数量リスト") -> Sheet:
    """読み込み済みの JSON から組む。

    **同じコードが 2 行あっても合算しない。** 「居間の壁」と「寝室の壁」は
    同じクロスでも別の行として見せたい。合算すると見積書から現場が消える。
    """
    reasons: list[str] = []
    if not isinstance(data, dict):
        raise QuantityError([f"{where}: 一番外が辞書ではない"])

    items = data.get("items")
    if not isinstance(items, list):
        raise QuantityError([f"{where}: items が配列ではない"])
    if not items:
        raise QuantityError([f"{where}: items が空"])

    lines: list[Line] = []
    for n, raw in enumerate(items, start=1):
        at = f"{where} items[{n - 1}]"
        if not isinstance(raw, dict):
            reasons.append(f"{at}: 辞書ではない")
            continue
        code = str(raw.get("code") or "").strip()
        if not code:
            reasons.append(f"{at}: code が空")
            continue
        if "qty" not in raw:
            reasons.append(f"{at}: {code} に qty が無い")
            continue
        try:
            qty = dec(raw["qty"], field=f"{at} qty")
        except MoneyError as e:
            reasons.append(str(e))
            continue
        if qty <= 0:
            reasons.append(f"{at}: {code} の qty が 0 以下 ({qty})。"
                           "拾えなかった行は落としてから渡す")
            continue
        lines.append(Line(code, qty, str(raw.get("note") or "").strip()))

    raw_est = data.get("estimate")
    header = _header(raw_est, reasons, where)
    discount = _discount(raw_est, reasons, where)

    if reasons:
        raise QuantityError(reasons)
    return Sheet(str(data.get("scan_id") or "").strip(),
                 str(data.get("name") or "").strip(),
                 tuple(lines), header, discount)


def _discount(raw: object, reasons: list[str], where: str) -> Discount | None:
    """`estimate.discount` を読む。**額と目標の両方は書けない。**"""
    if not isinstance(raw, dict) or raw.get("discount") is None:
        return None
    d = raw["discount"]
    at = f"{where} estimate.discount"
    if not isinstance(d, dict):
        reasons.append(f"{at}: 辞書ではない")
        return None

    amount = target = None
    for key in ("amount", "target"):
        if d.get(key) is None:
            continue
        try:
            v = dec(d[key], field=f"{at}.{key}")
        except MoneyError as e:
            reasons.append(str(e))
            continue
        if v <= 0:
            reasons.append(f"{at}.{key} は 0 より大きい額 ({v})")
            continue
        if key == "amount":
            amount = v
        else:
            target = v

    if amount is not None and target is not None:
        reasons.append(f"{at}: amount と target の両方は書けない")
        return None
    if amount is None and target is None:
        reasons.append(f"{at}: amount か target のどちらかが要る")
        return None

    basis = str(d.get("basis") or GROSS).strip()
    if basis not in BASES:
        reasons.append(f"{at}.basis {basis} は {' / '.join(BASES)} のどちらでもない")
        return None

    return Discount(str(d.get("name") or "お値引き").strip(), amount, target, basis)


def _date(raw: object, *, at: str, reasons: list[str]) -> date | None:
    if raw in (None, ""):
        return None
    try:
        return date.fromisoformat(str(raw).strip())
    except ValueError:
        reasons.append(f"{at} が日付ではない ({raw!r})。YYYY-MM-DD で書く")
        return None


def _header(raw: object, reasons: list[str], where: str) -> Header:
    """`estimate` は**省略できる**。検算だけしたいときに番号を切りたくない。

    ただし書くなら、番号と発行日の両方が要る。片方だけでは後から見積りを
    特定できない。
    """
    if raw is None:
        return Header()
    at = f"{where} estimate"
    if not isinstance(raw, dict):
        reasons.append(f"{at}: 辞書ではない")
        return Header()

    number = str(raw.get("number") or "").strip()
    issued = _date(raw.get("issued"), at=f"{at}.issued", reasons=reasons)
    if (number and issued is None) or (issued and not number):
        reasons.append(f"{at}: number と issued は揃えて書く。"
                       "片方だけでは後から見積りを特定できない")

    revision = raw.get("revision", 1)
    try:
        revision = int(revision)
    except (TypeError, ValueError):
        reasons.append(f"{at}.revision が整数ではない ({revision!r})")
        revision = 1
    if revision < 1:
        reasons.append(f"{at}.revision は 1 以上 ({revision})")
        revision = 1

    valid_until = _date(raw.get("valid_until"), at=f"{at}.valid_until",
                        reasons=reasons)
    days = raw.get("valid_days")
    if days is not None and valid_until is not None:
        reasons.append(f"{at}: valid_until と valid_days の両方は書けない")
    elif days is not None:
        try:
            n = int(days)
        except (TypeError, ValueError):
            reasons.append(f"{at}.valid_days が整数ではない ({days!r})")
        else:
            if n < 1:
                reasons.append(f"{at}.valid_days は 1 以上 ({n})")
            elif issued is None:
                reasons.append(f"{at}: valid_days は issued が無いと日付にできない")
            else:
                valid_until = issued + timedelta(days=n)

    if issued and valid_until and valid_until < issued:
        reasons.append(f"{at}: 有効期限 {valid_until} が発行日 {issued} より前")

    return Header(number, revision, issued, valid_until,
                  str(raw.get("client") or "").strip(),
                  str(raw.get("subject") or "").strip(),
                  _issuer(raw.get("issuer"), reasons, at))


def _issuer(raw: object, reasons: list[str], at: str) -> Issuer:
    """`estimate.issuer`。**省略できるが、書くなら社名が要る。**"""
    if raw is None:
        return Issuer()
    if not isinstance(raw, dict):
        reasons.append(f"{at}.issuer: 辞書ではない")
        return Issuer()
    name = str(raw.get("name") or "").strip()
    if not name:
        reasons.append(f"{at}.issuer: name が空。誰が出した見積りか分からない")
    return Issuer(name,
                  str(raw.get("address") or "").strip(),
                  str(raw.get("tel") or "").strip(),
                  str(raw.get("person") or "").strip(),
                  str(raw.get("registration") or "").strip())


def load(path: Path) -> Sheet:
    """**float を通さずに読む。** `parse_float=Decimal` で 48.6 を 48.6 のまま受ける。"""
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh, parse_float=Decimal, parse_int=Decimal)
    except FileNotFoundError:
        raise QuantityError([f"数量リストが無い: {path}"]) from None
    except json.JSONDecodeError as e:
        raise QuantityError([f"{path.name}: JSON として読めない ({e})"]) from None
    return parse(data, where=path.name)
