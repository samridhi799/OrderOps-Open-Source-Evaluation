# ORDER_FLOW_NOTES.md — Required submission

Complete this file with your own actual examples and results. Do not leave prompts unanswered.

## 1. Example order-event sequence
Order initialized as `new_order("ORD-FLOW-01", 49900)` ($₹499.00$, initially `PLACED`, `UNPAID`).

| Step | Event | Expected order/payment/refund state | Actual result |
|---|---|---|---|
| 1 | `{"event_id": "EV-1", "type": "payment_confirmed"}` | `status="PLACED"`, `payment_status="PAID"`, `refund_due_paise=0`, `refunded_paise=0` | `status="PLACED"`, `payment_status="PAID"`, `refund_due_paise=0`, `refunded_paise=0`, `processed_event_ids=["EV-1"]` |
| 2 | `{"event_id": "EV-2", "type": "restaurant_accepted"}` | `status="ACCEPTED"`, `payment_status="PAID"`, `refund_due_paise=0`, `refunded_paise=0` | `status="ACCEPTED"`, `payment_status="PAID"`, `refund_due_paise=0`, `refunded_paise=0`, `processed_event_ids=["EV-1", "EV-2"]` |
| 3 | `{"event_id": "EV-3", "type": "cancel_requested"}` | `status="CANCELLED"`, `payment_status="PAID"`, `refund_due_paise=49900`, `refunded_paise=0` | `status="CANCELLED"`, `payment_status="PAID"`, `refund_due_paise=49900`, `refunded_paise=0`, `processed_event_ids=["EV-1", "EV-2", "EV-3"]` |
| 4 | `{"event_id": "EV-4", "type": "refund_processed", "amount_paise": 20000}` | `status="CANCELLED"`, `payment_status="PAID"`, `refund_due_paise=49900`, `refunded_paise=20000` | `status="CANCELLED"`, `payment_status="PAID"`, `refund_due_paise=49900`, `refunded_paise=20000`, `processed_event_ids=[..., "EV-4"]` |
| 5 | `{"event_id": "EV-5", "type": "refund_processed", "amount_paise": 29900}` | `status="CANCELLED"`, `payment_status="REFUNDED"`, `refund_due_paise=49900`, `refunded_paise=49900` | `status="CANCELLED"`, `payment_status="REFUNDED"`, `refund_due_paise=49900`, `refunded_paise=49900`, `processed_event_ids=[..., "EV-5"]` |

## 2. Three edge cases
For each, state the input/event sequence, expected behaviour, actual observed result, and test that verifies it.

1. **Cancellation Attempt After Dispatch (`OUT_FOR_DELIVERY`)**:
   - *Input*: Order in `OUT_FOR_DELIVERY` receives `{"event_id": "E-CAN-1", "type": "cancel_requested"}`.
   - *Expected Behaviour*: Cancellation must be silently rejected. The order must remain `OUT_FOR_DELIVERY` and `refund_due_paise` must stay 0.
   - *Actual Observed Result*: `res["status"] == "OUT_FOR_DELIVERY"` and `res["refund_due_paise"] == 0`.
   - *Verifying Test*: `test_cancellation_after_dispatch_and_delivery_is_ignored` in `tests/test_edge_cases.py`.

2. **Late Payment Confirmation Arriving After Restaurant Rejection**:
   - *Input*: Order `ORD-LATE` in `PLACED` receives `restaurant_rejected` while `payment_status="UNPAID"`, followed later by `payment_confirmed`.
   - *Expected Behaviour*: On rejection, status becomes `REJECTED` and `refund_due_paise=0`. When `payment_confirmed` arrives later, `payment_status` becomes `PAID` and `refund_due_paise` is initialized to `total_paise` (12500 paise), enabling subsequent customer refund.
   - *Actual Observed Result*: `paid_rejected["payment_status"] == "PAID"`, `paid_rejected["refund_due_paise"] == 12500`, and refund completes successfully.
   - *Verifying Test*: `test_late_payment_confirmed_after_rejection_or_cancellation` in `tests/test_edge_cases.py`.

3. **Replay of Processed Refund Event (Duplicate `event_id`)**:
   - *Input*: Order receives `{"event_id": "R-1", "type": "refund_processed", "amount_paise": 2000}`. Then the identical event is replayed.
   - *Expected Behaviour*: The first event processes the 2000 paise refund. The duplicate replay is detected via `processed_event_ids` and returned immediately without duplicating the refund or adding to `processed_event_ids`.
   - *Actual Observed Result*: Second run preserves `refunded_paise == 2000` and `processed_event_ids == ["R-1"]`.
   - *Verifying Test*: `test_duplicate_event_is_idempotent` in `tests/test_contract.py` and `test_idempotency_ignores_conflicting_replay_payload` in `tests/test_edge_cases.py`.

## 3. Assumptions and limitations
- **Monetary Unit**: All monetary fields (`total_paise`, `amount_paise`, `refund_due_paise`, `refunded_paise`) are strictly non-negative integers representing paise.
- **Terminal States**: `DELIVERED`, `REJECTED`, and `CANCELLED` are terminal lifecycle states. Once an order reaches `DELIVERED`, it cannot be cancelled or refunded through the standard lifecycle pipeline.
- **Idempotency Keying**: Idempotency is keyed strictly by `event_id`. Any replayed event with an identical `event_id` is considered already applied and dropped.
- **Scope Limitations**: The system runs as a pure in-memory state transition library for offline batch reconciliation and does not handle database transactions or real-time network retries.
