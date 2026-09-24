# Per-line tax codes by chain

Slice 2's parser reads the code printed next to each price and sets `taxable` from it.
Codes are chain-specific, so this table is the source for the per-chain map in code.

| Chain | Code | Meaning | Parsed as |
|---|---|---|---|
| Wegmans | `T` | taxable | `taxable: true` |
| Wegmans | `F` | food (NY: exempt) | `taxable: false` |
| Wegmans | `B` | bottle deposit, $0.05 per canned/bottled beverage | separate `deposit` line, `taxable: false` |
| Target | `T` | taxable | `taxable: true` |
| Target | `NF` | non-taxable food | `taxable: false` |

Source: 2 Wegmans + 2 Target receipts (Ithaca, NY), Sept 2026. Confirmed by the owner, not yet
cross-checked against the printed tax total.

## Rules
- Unknown or missing code -> `taxable: null` (unknown), which triggers the
  `unknown_taxability` / `tax_fallback_proportional` warnings in the allocator.
- Never infer taxability from the product name; only from the printed code.
- A chain's map is only trusted when the soft tax check passes: taxable subtotal x inferred
  rate should equal the printed tax (Tompkins County, NY is 8%).

## Open questions (need the photos)
- Where does the code sit on the line (trailing column, before/after price)?
- Does either receipt print a legend (e.g. "T = TAXABLE")?
- How do weighted items print (e.g. `0.73 lb @ $2.99/lb`)?
- How do coupons/discounts print, and do they carry a code?
- Are deposits one line per beverage, or one grouped line?
- Is an item count printed (useful as an extra check)?
