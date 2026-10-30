"""Comprehensive edge-case and regression tests for OrderOps."""
import pytest
from models import new_order
from service import apply_order_event, reconcile_orders


def make_event(event_id, kind, **extra):
    return {"event_id": event_id, "type": kind, **extra}


def test_cancellation_after_dispatch_and_delivery_is_ignored():
    """Customer cancel request after dispatch or delivery must not alter order status or create refund due."""
    # Case A: Cancel requested when OUT_FOR_DELIVERY
    order_dispatched = new_order("ORD-DISP", 7500, "OUT_FOR_DELIVERY")
    order_dispatched["payment_status"] = "PAID"
    res1 = apply_order_event(order_dispatched, make_event("E-CAN-1", "cancel_requested"))
    assert res1["status"] == "OUT_FOR_DELIVERY"
    assert res1["refund_due_paise"] == 0

    # Case B: Cancel requested when DELIVERED
    order_delivered = new_order("ORD-DELV", 7500, "DELIVERED")
    order_delivered["payment_status"] = "PAID"
    res2 = apply_order_event(order_delivered, make_event("E-CAN-2", "cancel_requested"))
    assert res2["status"] == "DELIVERED"
    assert res2["refund_due_paise"] == 0


def test_late_payment_confirmed_after_rejection_or_cancellation():
    """Late payment arrival on already rejected or cancelled orders must set refund_due_paise to total_paise."""
    # Restaurant rejects before payment confirmation
    order_rejected = new_order("ORD-LATE-1", 12500, "PLACED")
    order_rejected = apply_order_event(order_rejected, make_event("E-REJ", "restaurant_rejected"))
    assert order_rejected["status"] == "REJECTED"
    assert order_rejected["payment_status"] == "UNPAID"
    assert order_rejected["refund_due_paise"] == 0

    # Late payment arrives
    paid_rejected = apply_order_event(order_rejected, make_event("E-PAY", "payment_confirmed"))
    assert paid_rejected["payment_status"] == "PAID"
    assert paid_rejected["refund_due_paise"] == 12500

    # Refund can now be processed
    refunded = apply_order_event(paid_rejected, make_event("E-REF", "refund_processed", amount_paise=12500))
    assert refunded["refunded_paise"] == 12500
    assert refunded["payment_status"] == "REFUNDED"


def test_refund_amount_type_safety_and_coercion_prevention():
    """Booleans, floats, strings, nulls and negatives must be strictly rejected from refund processing."""
    order = new_order("ORD-TYPE", 5000, "CANCELLED")
    order.update(payment_status="PAID", refund_due_paise=5000)

    # In Python, bool is a subclass of int (isinstance(True, int) is True). Must not process bools as 1 paisa.
    for invalid in [True, False, 100.5, "1000", None, -500, 0]:
        res = apply_order_event(order, make_event("E-INV", "refund_processed", amount_paise=invalid))
        assert res["refunded_paise"] == 0
        assert res["payment_status"] == "PAID"


def test_multi_step_partial_refund_accumulation():
    """Sequential partial refunds must accumulate correctly up to refund_due_paise and reject excess."""
    order = new_order("ORD-PARTIAL", 10000, "CANCELLED")
    order.update(payment_status="PAID", refund_due_paise=10000)

    # Partial refund 1: 2500 paise (Rs 25.00)
    step1 = apply_order_event(order, make_event("R-1", "refund_processed", amount_paise=2500))
    assert step1["refunded_paise"] == 2500
    assert step1["payment_status"] == "PAID"

    # Partial refund 2: 3500 paise (cumulative Rs 60.00)
    step2 = apply_order_event(step1, make_event("R-2", "refund_processed", amount_paise=3500))
    assert step2["refunded_paise"] == 6000
    assert step2["payment_status"] == "PAID"

    # Invalid refund attempt: 4500 paise exceeds remaining 4000 paise due
    step3_invalid = apply_order_event(step2, make_event("R-3-BAD", "refund_processed", amount_paise=4500))
    assert step3_invalid["refunded_paise"] == 6000
    assert step3_invalid["payment_status"] == "PAID"

    # Final partial refund: exact 4000 paise remaining
    step4 = apply_order_event(step2, make_event("R-4", "refund_processed", amount_paise=4000))
    assert step4["refunded_paise"] == 10000
    assert step4["payment_status"] == "REFUNDED"

    # Any refund after completion is rejected
    step5 = apply_order_event(step4, make_event("R-5-OVER", "refund_processed", amount_paise=1))
    assert step5["refunded_paise"] == 10000
    assert step5["payment_status"] == "REFUNDED"


def test_simultaneous_amount_and_status_mismatch_reconciliation():
    """An order with both amount mismatch and status mismatch must be reported in both lists and not in matched."""
    internal = [{"order_id": "ORD-DUAL", "amount_paise": 5000, "status": "PLACED"}]
    provider = [{"order_id": "ORD-DUAL", "amount_paise": 8000, "status": "CANCELLED"}]

    report = reconcile_orders(internal, provider)
    assert report["amount_mismatches"] == ["ORD-DUAL"]
    assert report["status_mismatches"] == ["ORD-DUAL"]
    assert report["matched"] == []
    assert report["missing_from_internal"] == []
    assert report["missing_from_provider"] == []


def test_idempotency_ignores_conflicting_replay_payload():
    """Replaying an event with the same event_id but altered payload must be ignored unconditionally."""
    order = new_order("ORD-IDEMP", 5000, "PLACED")
    first = apply_order_event(order, make_event("EVT-100", "payment_confirmed"))
    assert first["payment_status"] == "PAID"
    assert first["processed_event_ids"] == ["EVT-100"]

    # Replay with conflicting/tampered payload
    tampered_replay = make_event("EVT-100", "refund_processed", amount_paise=5000)
    second = apply_order_event(first, tampered_replay)
    assert second["payment_status"] == "PAID"
    assert second["refunded_paise"] == 0
    assert second["processed_event_ids"] == ["EVT-100"]


def test_malformed_and_missing_field_inputs():
    """Malformed non-dict inputs, missing fields, or empty structures must not raise exceptions."""
    # Non-dict order or event
    assert apply_order_event(None, {"type": "payment_confirmed"}) == {}
    order = new_order("ORD-SAFE", 3000)
    assert apply_order_event(order, None) == order

    # Event missing type and event_id
    res = apply_order_event(order, {})
    assert res["status"] == "PLACED"
    assert res["payment_status"] == "UNPAID"

    # Reconciliation with empty lists, None, or records missing order_id
    report = reconcile_orders(None, [{"status": "PLACED"}])
    assert report["matched"] == []
    assert report["missing_from_provider"] == []
    assert report["missing_from_internal"] == []
