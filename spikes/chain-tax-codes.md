# Per-line tax codes by chain

Slice 2's parser reads the code printed next to each price and sets `taxable` from it.
Codes are chain-specific, so this table is the source for the per-chain map in code.

**Verified against 4 real receipts (2 Wegmans, 2 Target; Ithaca NY, Sept 2026).** Every figure below
was checked by hand: see "Evidence" at the bottom.

| Chain | Code | Meaning | Parsed as |
|---|---|---|---|
| Wegmans | `T` | taxable | `taxable: true` |
| Wegmans | `F` | food / exempt in NY (also used on deposit lines and on discount lines) | `taxable: false` |
| Wegmans | `B` | **taxable** beverage that carries a container deposit | `taxable: true` |
| Target | `T` | taxable (legend: `T = NY TAX 8.00000 on $<base>`) | `taxable: true` |
| Target | `NF` | non-taxable food | `taxable: false` |

> **Corrected 2026-09-23.** `B` was first recorded as "bottle deposit, not taxable". The solver
> disproved that: on Wegmans OP#85 only `B + T` reproduces the printed tax. The deposit itself is a
> separate `DP CONTAINER DEPOSIT 0.05 F` line and is **not** taxed. Treating `B` as exempt would
> undercharge whoever bought the beverage on every receipt.

## Rules
- Unknown or missing code -> `taxable: null` (unknown), which triggers the
  `unknown_taxability` / `tax_fallback_proportional` warnings in the allocator.
- Never infer taxability from the product name; only from the printed code, the legend, or the
  arithmetic solver.
- A zero-tax receipt proves nothing about codes (see Wegmans OP#84): no tax, no equation. Fall back
  to the stored store profile, or mark unknown.

## Chain format notes (for the Slice 2 parser)
**Wegmans**
- No `SUBTOTAL` line: only `TAX` and `**** BALANCE`. Check is `items + tax = balance`.
- Prefix column left of the item name: `SC` = Shoppers Club promo, `DP` = deposit.
- Tax code printed *after* the amount: `WB DISINFECT WIPE  3.99 T`.
- Negative amounts use a **trailing minus** and still carry a code: `... KELL WEDNESDAY CER 2.00-F`.
  It is a discount attached to the `SC` item line above it.
- Container deposit is its own line (`DP CONTAINER DEPOSIT 0.05 F`), so it maps to a `deposit` line
  that is assignable to whoever took the drink.

**Target**
- Department headers (`GROCERY`, `HEALTH AND BEAUTY`, `TOYS`) are section labels, not items.
- Each item line starts with a DPCI/item number, then the name, then the code, then the amount.
- Promotions are folded into the line price; `Regular Price $12.00` / `Buy1Get1 25%off` print
  underneath as notes. There is no separate discount line, so those sub-lines are metadata.
- Legend states the taxable base explicitly: `T = NY TAX 8.00000 on $30.74`.

## Evidence
| Receipt | Check | Result |
|---|---|---|
| Target 09/22 10:17 PM | items 0.87 + 3.99 = 4.86 = printed subtotal | OK |
| | 8% of 3.99 = 0.32 = printed tax; 4.86 + 0.32 = 5.18 = total | OK |
| Target 09/22 10:15 PM | items = 35.63 = printed subtotal | OK |
| | T-items = 30.74 = printed taxable base; 8% = 2.46 = printed tax; total 38.09 | OK |
| Wegmans 09/17 OP#84 | items = 136.58 = balance, tax 0.00, every line `F` | OK, but no code evidence |
| Wegmans 09/17 OP#85 | items 51.99 + tax 1.00 = 52.99 = balance | OK |
| | solver at 8%: `B`=0.28, `F`=3.16, `T`=0.72, `B+F`=3.44, **`B+T`=1.00**, `F+T`=3.88, `B+F+T`=4.16 | single match: `B+T` (implied rate 8.02%) |

Rounding: tax is rounded once per receipt, half-up (30.74 x 8% = 2.4592 -> 2.46; 12.47 x 8% =
0.9976 -> 1.00). The C3 tolerance of +/-1c covers this.

## PII seen on these receipts (strip before sending anywhere)
Card last-4, AUTH/RCPT codes, `REC#`, and Target's survey `User ID` / `Password`.
