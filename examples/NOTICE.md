# examples/ の見本データについて

**このディレクトリのファイルは生成物。手で直さない。** 作り直すには:

```bash
uv run python tools/make_examples.py \
    --manifest ../TemplateMaker/catalog/abo.tier-b.json
```

`--check` を付けると、生成せずに今の `examples/` と一致するかだけを見る。

## 単価と歩掛りは架空

Amazon Berkeley Objects (ABO) に価格は入っていない。この表の単価は**カテゴリごとの基準額に
寸法の比を掛けて機械的に作った架空の値**で、実勢価格ではない。歩掛りも同じく
架空で、置き方の 4 区分（床置き・敷物・壁付け・天井）から決めている。
単価の出どころを書く列（`source`）に、行ごとに「架空単価」と書いてある。

仕上げ材・建具・電気設備・諸費用の行はカタログに無いので、**手で書いた架空の
まま**残っている。

## Amazon Berkeley Objects (ABO)

- ライセンス: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- 収録数: 13 体
- 変更: 3D 形状そのものは同梱していない。ここで使ったのは識別子・商品名・
  ブランド・外形寸法で、品目名は日本語に置き換え、寸法は 10mm に丸めている。
  **単価・歩掛り・工種はカタログに無く、こちらで架空に作ったもの。**
- 色違いの 37 体は、見積書の行として区別が付かないので畳んである。

<details><summary>内訳</summary>

- `B00NUS53CY` Amazon Basics 4 Tier Assembled Shelf, Chrome — Amazonベーシック(AmazonBasics)
- `B01LYBQXRH` Amazon Basic 4-Tier Unit Shelf Metal Wire Rack, Black — Amazonベーシック(AmazonBasics)
- `B071777YL9` Amazon Brand – Rivet Diamond Trellis Tassel Wool Rug, 5' x 8', Ivory — Rivet
- `B0718ZKMW1` Amazon Brand – Stone & Beam Wall Decor Mirror, 30" x 40", Champagne Gold — Stone & Beam
- `B0719H3LG2` Amazon Brand – Stone & Beam Modern Industrial Round Ceiling Pendant Chandelier Fixture - 6.5 Inch Shade, 10 - 58 Inch Cord, Chrome and Black — Stone & Beam
- `B071F6WK9K` Amazon Brand – Rivet Mid Century Modern Glass Ceiling Pendant Chandelier Fixture With Edison Light Bulb - 9.75 Inch Shade, 12-58 Inch Cord, Black and Chrome — Rivet
- `B071FMSY5S` Amazon Brand – Rivet Revolve Modern Upholstered Loveseat Sofa, 56"W, Denim Blue — Rivet
- `B071J7Q6KD` Amazon Brand – Rivet Revolve Modern Upholstered Armchair with Tapered Legs, 33"W, Grey Weave — Rivet
- `B072Y6Y96S` AmazonBasics Classic Reception Office Chair with Mahogany Wood Finish Legs - Black — AmazonBasics
- `B072ZMHBKQ` Amazon Brand – Rivet Mid-Century Modern Lacquer Side End Table Nightstand, Grey and Walnut — Rivet
- `B07374M818` Amazon Brand – Rivet Modern Table Desk Lamp With Light Bulb - 8 x 8 x 16 Inches, Marble and Brass — Rivet
- `B075HR7DM7` Amazon Brand – Rivet Modern Angled Stoneware Vase, 5.25"H, White — Rivet
- `B075HWDSFH` Amazon Brand – Rivet Pyramid-Shaped Wall Planter, 7.5"H, Modern Earthenware, Aqua — Rivet

</details>
