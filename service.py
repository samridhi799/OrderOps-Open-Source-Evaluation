"""Starter order lifecycle and refund service; all data is synthetic."""
from copy import deepcopy


def apply_order_event(order: dict, event: dict) -> dict:
    """Return an updated copy of order.

    Order keys: order_id, total_paise, status, payment_status, refund_due_paise,
    refunded_paise, processed_event_ids.
    """
    if not isinstance(order, dict):
        return {}
    if not isinstance(event, dict):
        return deepcopy(order)

    out = deepcopy(order)
    out.setdefault("status", "PLACED")
    out.setdefault("payment_status", "UNPAID")
    out.setdefault("refund_due_paise", 0)
    out.setdefault("refunded_paise", 0)
    out.setdefault("processed_event_ids", [])

    event_id = event.get("event_id")
    if event_id is not None and event_id in out["processed_event_ids"]:
        return out

    kind = event.get("type")

    if kind == "payment_confirmed":
        out["payment_status"] = "PAID"
        if out.get("status") in ("REJECTED", "CANCELLED"):
            out["refund_due_paise"] = out.get("total_paise", 0)
    elif kind == "restaurant_accepted" and out.get("status") == "PLACED":
        out["status"] = "ACCEPTED"
    elif kind == "restaurant_rejected" and out.get("status") == "PLACED":
        out["status"] = "REJECTED"
        if out["payment_status"] == "PAID":
            out["refund_due_paise"] = out.get("total_paise", 0)
    elif kind == "cancel_requested" and out.get("status") in ("PLACED", "ACCEPTED"):
        out["status"] = "CANCELLED"
        if out["payment_status"] == "PAID":
            out["refund_due_paise"] = out.get("total_paise", 0)
    elif kind == "dispatch_started" and out.get("status") == "ACCEPTED":
        out["status"] = "OUT_FOR_DELIVERY"
    elif kind == "order_delivered" and out.get("status") == "OUT_FOR_DELIVERY":
        out["status"] = "DELIVERED"
    elif kind == "refund_processed":
        if (
            out.get("status") in ("CANCELLED", "REJECTED")
            and out.get("payment_status") == "PAID"
            and out.get("refund_due_paise", 0) > 0
        ):
            amount = event.get("amount_paise")
            if isinstance(amount, int) and not isinstance(amount, bool) and amount > 0:
                refundable = out["refund_due_paise"] - out["refunded_paise"]
                if amount <= refundable:
                    out["refunded_paise"] += amount
                    if out["refunded_paise"] == out["refund_due_paise"]:
                        out["payment_status"] = "REFUNDED"

    if event_id is not None:
        out["processed_event_ids"].append(event_id)
    return out


def reconcile_orders(internal: list[dict], provider: list[dict]) -> dict:
    """Compare transaction summaries keyed by order_id."""
    def _extract_amount(record: dict):
        if "amount_paise" in record:
            return record.get("amount_paise")
        return record.get("total_paise")

    left = {r.get("order_id"): r for r in (internal or []) if isinstance(r, dict) and r.get("order_id") is not None}
    right = {r.get("order_id"): r for r in (provider or []) if isinstance(r, dict) and r.get("order_id") is not None}
    report = {
        "matched": [],
        "missing_from_provider": [],
        "missing_from_internal": [],
        "amount_mismatches": [],
        "status_mismatches": [],
    }

    for key in sorted(set(left) | set(right), key=lambda x: str(x)):
        if key not in right:
            report["missing_from_provider"].append(key)
        elif key not in left:
            report["missing_from_internal"].append(key)
        else:
            a, b = left[key], right[key]
            a_amount = _extract_amount(a)
            b_amount = _extract_amount(b)
            amount_mismatch = (a_amount != b_amount)
            status_mismatch = (a.get("status") != b.get("status"))

            if amount_mismatch:
                report["amount_mismatches"].append(key)
            if status_mismatch:
                report["status_mismatches"].append(key)
            if not amount_mismatch and not status_mismatch:
                report["matched"].append(key)

    return report
