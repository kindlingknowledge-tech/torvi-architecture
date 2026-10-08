"""
Torvi admin console — recording a payment (simplified excerpt, ADR-020).

One DynamoDB transaction writes four things or nothing:
  1. an idempotency marker bound to a hash of the request
  2. the append-only payment item
  3. the ledger update, conditioned on the value we read (optimistic concurrency)
  4. an audit entry
Not deployable; validation, error mapping and table resolution are trimmed.
"""
import hashlib
import json
import time
import uuid
from decimal import Decimal

import boto3

ddb = boto3.client("dynamodb")


def record_payment(tables, actor, society_id, flat_no, month, amount: Decimal,
                   mode: str, reference: str, idem_key: str, ledger_row: dict):
    req_hash = hashlib.sha256(json.dumps(
        [society_id, flat_no, month, str(amount), mode, reference], sort_keys=True
    ).encode()).hexdigest()

    payment_id = uuid.uuid4().hex
    now = int(time.time())
    prev_received = Decimal(ledger_row["amount_received"])

    ddb.transact_write_items(TransactItems=[
        {   # 1. Same key + same body → replay; same key + different body → 422 upstream
            "Put": {
                "TableName": tables["dedup"],
                "Item": {
                    "message_id": {"S": f"IDEM#{idem_key}"},
                    "req_hash":   {"S": req_hash},
                    "payment_id": {"S": payment_id},
                    "ttl":        {"N": str(now + 7 * 86_400)},
                },
                "ConditionExpression": "attribute_not_exists(message_id)",
            }
        },
        {   # 2. Source of truth: never updated, never deleted
            "Put": {
                "TableName": tables["payments"],
                "Item": {
                    "pk":           {"S": f"{society_id}#{flat_no}"},
                    "sk":           {"S": f"{now}#{payment_id}"},
                    "amount":       {"N": str(amount)},
                    "mode":         {"S": mode},
                    "reference":    {"S": reference},
                    "ledger_month": {"S": month},
                    "status":       {"S": "active"},
                    "recorded_by":  {"S": actor["sub"]},
                },
            }
        },
        {   # 3. Derived view, guarded against concurrent writers and closed months
            "Update": {
                "TableName": tables["ledger"],
                "Key": {"flat_no": {"S": flat_no}, "month": {"S": month}},
                "UpdateExpression": "SET amount_received = :new, balance_pending = balance_pending - :amt",
                "ConditionExpression": "amount_received = :prev AND month_state = :open",
                "ExpressionAttributeValues": {
                    ":new":  {"N": str(prev_received + amount)},
                    ":amt":  {"N": str(amount)},
                    ":prev": {"N": str(prev_received)},
                    ":open": {"S": "open"},
                },
            }
        },
        {   # 4. Append-only audit (the API role has no Update/Delete on this table)
            "Put": {
                "TableName": tables["audit"],
                "Item": {
                    "society_id": {"S": society_id},
                    "sk":         {"S": f"{now}#{uuid.uuid4().hex}"},
                    "actor_sub":  {"S": actor["sub"]},
                    "action":     {"S": "payment.create"},
                    "entity":     {"S": f"{flat_no}/{month}/{payment_id}"},
                    "after":      {"S": json.dumps({"amount": str(amount), "mode": mode})},
                },
            }
        },
    ])
    return payment_id
