"""
Torvi — webhook inbound pipeline (simplified excerpt).

Shows the order of checks every WhatsApp message passes before the model is
called. Configuration, retries and message templates are trimmed. Not deployable.
"""
import hashlib
import hmac
import json
import os
import time

import boto3
from botocore.exceptions import ClientError

APP_SECRET     = os.environ["WA_APP_SECRET"]        # from Secrets Manager
AGENT_ID       = os.environ["AGENT_ID"]
AGENT_ALIAS_ID = os.environ["AGENT_ALIAS_ID"]
RATE_LIMIT_MAX = int(os.environ.get("RATE_LIMIT_MAX", "20"))  # per phone per hour

dynamodb  = boto3.resource("dynamodb")
dedup     = dynamodb.Table(os.environ["DEDUP_TABLE"])
identity  = dynamodb.Table(os.environ["IDENTITY_TABLE"])
agent_rt  = boto3.client("bedrock-agent-runtime")

# A cheap first filter, not a security boundary (see docs/security.md).
INJECTION_HINTS = (
    "ignore previous instructions", "you are now", "system prompt",
    "[role:", "make me admin", "dump database", "all flats dues",
)


def handle_message(event):
    raw = event.get("body", "")

    # 1. Authenticity: only Meta can produce this signature.
    if not verify_signature(raw, event["headers"].get("x-hub-signature-256", "")):
        return {"statusCode": 403}

    msg = parse_message(json.loads(raw))
    if msg is None:                                     # status callbacks etc.
        return ok()

    # 2. Idempotency: Meta retries; process each message once.
    if seen_before(msg["id"]):
        return ok()

    # 3. Rate limit before anything that costs money.
    if over_rate_limit(msg["from"]):
        reply(msg["from"], "Too many messages — please try again in a few minutes.")
        return ok()

    # 4. Cheap injection filter.
    if any(h in msg["text"].lower() for h in INJECTION_HINTS):
        reply(msg["from"], "Sorry, I couldn't understand that. Please rephrase.")
        return ok()

    # 5. Identity comes from our database, never from the message.
    who = identity.get_item(Key={"phone": msg["from"]}).get("Item")
    if not who:
        reply(msg["from"], "This number isn't registered. Please ask your secretary.")
        return ok()                                     # model never invoked

    # 6. Server-set session attributes are what every tool trusts.
    answer = invoke_agent(
        session_id=f"{who['token']}:{time.strftime('%Y-%m')}",
        text=msg["text"],
        attrs={
            "flat_no":    who["flat_no"],
            "role":       who["role"],
            "society_id": who["society_id"],
        },
    )
    reply(msg["from"], answer)
    return ok()


def verify_signature(body: str, signature: str) -> bool:
    if not signature:
        return False
    expected = "sha256=" + hmac.new(APP_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)    # constant-time


def seen_before(message_id: str) -> bool:
    try:
        dedup.put_item(
            Item={"message_id": message_id, "ttl": int(time.time()) + 86_400},
            ConditionExpression="attribute_not_exists(message_id)",
        )
        return False
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return True
        raise


def over_rate_limit(phone: str) -> bool:
    window = int(time.time() // 3600)
    key = "RATE#" + hashlib.sha256(f"{phone}#{window}".encode()).hexdigest()
    resp = dedup.update_item(
        Key={"message_id": key},
        UpdateExpression="ADD msg_count :one SET #ttl = if_not_exists(#ttl, :exp)",
        ExpressionAttributeNames={"#ttl": "ttl"},
        ExpressionAttributeValues={":one": 1, ":exp": int(time.time()) + 7_200},
        ReturnValues="UPDATED_NEW",
    )
    return int(resp["Attributes"]["msg_count"]) > RATE_LIMIT_MAX


def invoke_agent(session_id: str, text: str, attrs: dict) -> str:
    resp = agent_rt.invoke_agent(
        agentId=AGENT_ID,
        agentAliasId=AGENT_ALIAS_ID,
        sessionId=session_id,
        inputText=text,
        sessionState={"sessionAttributes": attrs},
    )
    return "".join(
        evt["chunk"]["bytes"].decode() for evt in resp["completion"] if "chunk" in evt
    ).strip()


# parse_message, reply and ok are omitted for brevity.
