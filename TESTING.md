# TESTING.md — Required submission

Complete this file with test evidence from your own work. Include at least five edge cases. Do not claim a test passed unless you ran it.

## Test command and environment
- Python version: `Python 3.14.4`
- Command run: `.venv/bin/pytest -q`
- Actual test summary: **220 passed in 0.07s** (baseline: 212 tests; regression & stretch: 8 tests)

## Edge-case evidence

| # | Case / input | Expected behaviour | Actual result | Test name or evidence |
|---|---|---|---|---|
| 1 | Order in `OUT_FOR_DELIVERY` or `DELIVERED` receives `cancel_requested` | Cancellation ignored after dispatch; status unchanged, refund due remains 0 | `res["status"] == "OUT_FOR_DELIVERY"`, `refund_due_paise == 0` | `test_cancellation_after_dispatch_and_delivery_is_ignored` |
| 2 | Order rejected while `UNPAID` subsequently receives late `payment_confirmed` | Transitions `payment_status` to `PAID` and sets `refund_due_paise = total_paise` | `paid_rejected["refund_due_paise"] == 12500`, subsequent full refund succeeds | `test_late_payment_confirmed_after_rejection_or_cancellation` |
| 3 | Refund event with boolean amount (`amount_paise=True` or `False`) | Booleans rejected from numeric coercion; `refunded_paise` unchanged | `res["refunded_paise"] == 0`, `res["payment_status"] == "PAID"` | `test_refund_amount_type_safety_and_coercion_prevention` |
| 4 | Multi-step partial refunds (2500, 3500) followed by excess attempt (4500) and exact remaining (4000) on 10000 due | Cumulative tracking; excess rejected; transition to `REFUNDED` only on exact 10000 | `refunded_paise` capped at 10000; status becomes `REFUNDED` only on final step | `test_multi_step_partial_refund_accumulation` |
| 5 | Dual discrepancy: internal record has 5000 / `PLACED`, provider has 8000 / `CANCELLED` | Reported independently in both `amount_mismatches` and `status_mismatches`; absent from `matched` | `report["amount_mismatches"] == ["ORD-DUAL"]`, `report["status_mismatches"] == ["ORD-DUAL"]` | `test_simultaneous_amount_and_status_mismatch_reconciliation` |
| 6 | Event replay with identical `event_id` but conflicting/tampered refund payload | Replay ignored unconditionally based on `event_id`; state preserved | `res["refunded_paise"] == 0`, `res["processed_event_ids"] == ["EVT-100"]` | `test_idempotency_ignores_conflicting_replay_payload` |

## Regression tests added
- **Idempotency**: Fixed duplicate appending and repeated mutation on duplicate events. Protected by `test_payment_event_replay_idempotent` and `test_idempotency_ignores_conflicting_replay_payload`.
- **Refund Eligibility & Type Safety**: Blocked boolean/float/negative refund injections and refunds on unpaid orders. Protected by `test_refund_amount_type_safety_and_coercion_prevention` and `test_invalid_refund_amounts_are_ignored`.
- **Partial Refund Bounds**: Prevented cumulative refunds exceeding refundable due. Protected by `test_multi_step_partial_refund_accumulation` and `test_refunds_cannot_exceed_due`.
- **Late Payment Refund Due**: Initialized `refund_due_paise` on `payment_confirmed` for already rejected/cancelled orders. Protected by `test_late_payment_confirmed_after_rejection_or_cancellation`.
- **Reconciliation Independence**: Disentangled status and amount checks. Protected by `test_reconciliation_status_mismatch_matrix` and `test_simultaneous_amount_and_status_mismatch_reconciliation`.
- **Awaiting-Refund CSV Export (Stretch Goal)**: Verified pending refund filtering, format compliance, and file writing in `test_export_awaiting_refund_csv_filters_and_formats`.

## Remaining failures or limitations
- None. All 220 tests pass cleanly without errors or warnings.
