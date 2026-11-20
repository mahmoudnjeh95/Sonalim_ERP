# Money as Decimal (WP-0.4)

## Problem

Sales orders, finance invoices and procurement purchase orders/receipts carried amounts as
`float` between the database (`NUMERIC`) and the API: rows were read with `float(...)`, domain
dataclasses and request models were typed `float`, and arithmetic ran in binary floating point.
That loses cents (0.1 + 0.2 != 0.3), and it made quantity checks wrong at the edge: receiving
0.1 t then 0.2 t against a 0.3 t line was refused as an over-receipt.

The roadmap also listed the invoice currency default (`USD`). That was already fixed by
`finance/0002_finance_invoice_currency_xof.sql` (column default `XOF`, legacy rows relabelled)
and the code defaults are `XOF`; nothing left to do there.

## Rule

- Inside the three modules, money (prices, fees, landed costs, totals, invoice amounts) and the
  quantities and rates it is computed from are `decimal.Decimal`, from the database row to the
  domain rule and back. Request models declare `Decimal`, so a JSON `0.1` arrives as
  `Decimal("0.1")`, and a string `"0.1"` is accepted too.
- `core/domain/money.py` holds the two edge helpers:
  - `to_decimal(value)`: any number (or numeric string) to `Decimal` via `str`, so a float
    caller gets the decimal it wrote, not its binary expansion. Domain dataclasses
    (`OrderLine`, `SalesOrder`, `Invoice`) coerce their fields with it, so callers outside the
    module (CRM, seed scripts) that still pass floats keep working.
  - `json_number(value)`: `Decimal` to a JSON number. FastAPI writes a `Decimal` as a string,
    and audit/outbox payloads are `Jsonb` (plain `json.dumps`, which refuses `Decimal`). The
    API and event contracts stay as they were: money goes out as JSON numbers.
- Other modules' contracts are unchanged: warehouse `reserve_stock` / `receive_stock` /
  `receive_lot` still receive a `float` quantity and unit cost (converted at the call), and
  `sales.order.confirmed`, `finance.invoice.issued|paid` and the procurement receipt event keep
  their numeric payloads.

## Not in scope

- The procurement analysis reports (`list_last_prices`, `list_price_history`, `list_supplier_leaderboard`,
  `list_confirmed_receipt_line_details`, `cost_summary`) stay `float`: they are read-only,
  multiply by `core` exchange rates that are themselves `float`, and production consumes
  `list_confirmed_receipt_line_details` and `list_last_prices` as floats. They never write money back.
- `core.exchange_rates.rate_to_base` stays `float` (core, not in this WP); procurement converts
  it with `to_decimal` where it enters a stored cost.
- Frontend: no change. Responses keep the same JSON types.
