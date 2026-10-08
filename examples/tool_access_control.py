"""
Torvi — tool-level access control (simplified excerpt of getDues).

The agent may *ask* for any flat. The tool decides, using session attributes
the webhook set from the database. The model's opinion of who the user is
never matters. Not deployable.
"""
import json

from boto3.dynamodb.conditions import Key

from common import ledger_table_for, respond   # resolver + Bedrock response builder


def get_dues(event):
    session   = event.get("sessionAttributes", {})
    my_flat   = session.get("flat_no", "").upper()
    my_role   = session.get("role", "resident")
    society   = session.get("society_id")

    params    = {p["name"]: p["value"] for p in event.get("parameters", [])}
    requested = str(params.get("flat_no") or my_flat).strip().upper()

    # Hard check first — before any query runs.
    if not society or not requested:
        return respond(event, {"error": "bad_request"})
    if my_role != "admin" and requested != my_flat:
        return respond(event, {
            "error": "access_denied",
            "message": "You can only view your own flat's dues. Please contact your admin.",
        })

    table = ledger_table_for(society)              # unknown society → raises, never a default
    rows = table.query(
        KeyConditionExpression=Key("flat_no").eq(requested),
        ScanIndexForward=False,
        Limit=1,
    )["Items"]
    if not rows:
        return respond(event, {"error": "not_found"})

    latest = rows[0]
    return respond(event, {
        "flat_no":         requested,
        "month":           latest["month"],
        "balance_pending": float(latest["balance_pending"]),
        "status":          latest["status"],
    })


ROUTES = {"getDues": get_dues}                     # ADR-008: one Lambda, internal router


def lambda_handler(event, context):
    handler = ROUTES.get(event.get("function"))
    if handler is None:
        return respond(event, {"error": "unknown_function"})
    return handler(event)
