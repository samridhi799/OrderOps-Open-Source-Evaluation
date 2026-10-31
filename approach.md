# approach.md - Required submission

Complete this file in your own words. Be concise and specific to the work you actually performed.

## 1. Baseline
- Commands run before editing:
  - `python3 -m venv .venv`
  - `.venv/bin/pip install -r requirements-dev.txt`
  - `.venv/bin/pytest -q`
  - `.venv/bin/python main.py`
- Initial test result (include the actual summary):
  - **62 failed, 150 passed in 0.21s** (out of 212 total tests).
  - Key failures: Event idempotency replay, invalid/negative/boolean refund amounts accepted, refund eligibility for unpaid/active orders, cumulative refund exceeding due amount, reconciliation missing status mismatches.
- Demo/output observed:
  ```text
  matched: []
  missing_from_provider: ['ORD-103']
  missing_from_internal: ['ORD-104']
  amount_mismatches: ['ORD-101', 'ORD-102']
  status_mismatches: []
  ```
  `ORD-101` and `ORD-102` were incorrectly flagged as amount mismatches because internal records use `total_paise` while provider summaries use `amount_paise`. Status mismatches were ignored because mismatched statuses were categorized as matched.

## 2. Codebase understanding
- Important files and functions inspected:
  - `service.py`: `apply_order_event(order, event)` (state transitions and refund tracking) and `reconcile_orders(internal, provider)` (reconciliation engine).
  - `models.py`: `new_order(order_id, total_paise, status)` order constructor.
  - `fixtures.py` & `data/records.json`: Demo fixtures and expanded 219-event synthetic dataset with 150 orders and 163 provider records.
  - `main.py`: Demo runner executing reconciliation on sample fixture data.
  - `tests/test_contract.py` & `tests/test_acceptance_matrix.py`: Contract and parameterized acceptance test suites.
  - `.github/workflows/tests.yml`: CI workflow validating test outcomes.
- Order lifecycle or data flow traced:
  - Normal flow: `PLACED` -> `ACCEPTED` -> `OUT_FOR_DELIVERY` -> `DELIVERED`.
  - Cancellation: `PLACED` or `ACCEPTED` + `cancel_requested` -> `CANCELLED`. If paid, `refund_due_paise = total_paise`. Cancellation requested after dispatch (`OUT_FOR_DELIVERY`) or after delivery (`DELIVERED`) is ignored.
  - Rejection: `PLACED` + `restaurant_rejected` -> `REJECTED`. If paid, `refund_due_paise = total_paise`.
  - Payment timing: `payment_confirmed` may arrive before restaurant acceptance, or late after cancellation/rejection. If late, `refund_due_paise` must be set to `total_paise`.
  - Refunds: Applied only to `CANCELLED` or `REJECTED` orders with `payment_status == "PAID"`. Amounts must be positive integer paise and cannot exceed outstanding refundable due. `payment_status` transitions to `REFUNDED` only when full due amount is refunded.
  - Reconciliation: Compares internal and provider records by `order_id`, sorting deterministically and separating missing records, amount mismatches, and status mismatches.
- How you confirmed your understanding:
  - Executed tests individually, traced assertion failures in `test_acceptance_matrix.py`, and inspected the edge cases catalog in `data/records.json`.

## 3. Investigation and implementation strategy
For each major defect, describe the observed symptom, the hypothesis you tested, evidence from a test/log/example, and the fix chosen.
- Issue 1: Missing Event Idempotency
  - *Symptom*: Duplicate events caused duplicate entries in `processed_event_ids` and repeated state mutations.
  - *Hypothesis*: The function appended `event_id` without verifying prior processing.
  - *Evidence*: `test_duplicate_event_is_idempotent` failed with `AssertionError: assert ['e1', 'e1'] == ['e1']`.
  - *Fix*: Added an early return check: if `event_id is not None and event_id in out["processed_event_ids"]`, return `out` immediately. Append `event_id` only upon successful processing.
- Issue 2: Unsafe and Ineligible Refund Processing
  - *Symptom*: Negative amounts, non-integers, booleans (`True`/`False`), and excessive refund amounts were processed. Refunds were also applied to unpaid or active orders.
  - *Hypothesis*: Refund logic lacked type and boundary checks. In Python, `isinstance(True, int)` is `True`, allowing boolean values to alter refund amounts unless `not isinstance(amount, bool)` is explicitly checked.
  - *Evidence*: `test_invalid_refund_amounts_are_ignored[True]` and `test_refund_eligibility_matrix` failed.
  - *Fix*: Enforced preconditions: `status in ("CANCELLED", "REJECTED")`, `payment_status == "PAID"`, and `refund_due_paise > 0`. Validated amount with `isinstance(amount, int) and not isinstance(amount, bool) and amount > 0`. Capped at `amount <= (refund_due_paise - refunded_paise)`. Set `payment_status = "REFUNDED"` only when `refunded_paise == refund_due_paise`.
- Issue 3: Flawed Reconciliation Logic & Key Discrepancies
  - *Symptom*: Status mismatches were ignored; mismatched records were placed into `matched`. Demo flagged `ORD-101` and `ORD-102` as amount mismatches.
  - *Hypothesis*: `reconcile_orders` checked only `amount_paise`, missing `total_paise` from internal records, and grouped all amount matches into `matched` without checking status.
  - *Evidence*: `test_reconcile_reports_status_difference` failed with `assert [] == ['A']`.
  - *Fix*: Created helper `_extract_amount` checking `amount_paise` then `total_paise`. Separately checked `amount_mismatch` and `status_mismatch`. If both mismatch, recorded in both lists. Added to `matched` only when both match.

## 4. Implementation decisions
- Main changes and why:
  - Updated `service.py` to preserve pure function behavior (deepcopy on inputs, no side effects).
  - Added type guards against boolean-as-int coercion.
  - Handled late payments on cancelled/rejected orders by initializing `refund_due_paise = total_paise`.
  - Implemented the optional stretch feature: `export_awaiting_refund_csv(orders, filepath)` to generate operational CSV reports of orders with pending refund balances.
- Alternatives considered and why rejected:
  - Class-based state machine / Pydantic models: Rejected to maintain project structure, avoid heavy external dependencies, and honor existing function signatures and dict schemas.
  - Raising exceptions on invalid events: Rejected because requirements state malformed/invalid events should not corrupt state or crash the pipeline.
- Assumptions:
  - Currency values are represented strictly in integer paise.
  - `event_id` uniquely identifies events across the order lifecycle.

## 5. Verification
- Tests added or changed:
  - Created `tests/test_edge_cases.py` with 8 dedicated regression and stretch tests:
    - `test_cancellation_after_dispatch_and_delivery_is_ignored`
    - `test_late_payment_confirmed_after_rejection_or_cancellation`
    - `test_refund_amount_type_safety_and_coercion_prevention`
    - `test_multi_step_partial_refund_accumulation`
    - `test_simultaneous_amount_and_status_mismatch_reconciliation`
    - `test_idempotency_ignores_conflicting_replay_payload`
    - `test_malformed_and_missing_field_inputs`
    - `test_export_awaiting_refund_csv_filters_and_formats`
- Commands run and actual results:
  - `.venv/bin/pytest -q`: **220 passed in 0.07s** (100% pass rate).
  - `.venv/bin/python main.py`:
    ```text
    matched: ['ORD-101']
    missing_from_provider: ['ORD-103']
    missing_from_internal: ['ORD-104']
    amount_mismatches: []
    status_mismatches: ['ORD-102']
    ```
- Edge cases verified:
  - Cancellation after dispatch/delivery is ignored.
  - Late payments on cancelled/rejected orders initialize refund due.
  - Float, boolean, string, negative, and zero refund amounts are ignored.
  - Cumulative partial refunds cannot exceed outstanding due amount.
  - Dual status and amount discrepancies reported independently.
  - Awaiting-refund CSV export correctly filters orders with positive pending balances and outputs standard RFC 4180 CSV.
- Remaining failures or known limitations:
  - None. All visible tests and added edge cases pass.