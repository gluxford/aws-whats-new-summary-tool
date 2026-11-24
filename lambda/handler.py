"""
AWS What's New Summary Tool - Lambda Handler

Fetches the AWS What's New RSS feed, identifies new announcements since the
last run, summarises each using Amazon Bedrock Nova Lite, and emails the
summary via Amazon SES.
"""

import html
import json
import os
import hashlib
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

# ---------------------------------------------------------------------------
# Configuration (injected via Lambda environment variables)
# ---------------------------------------------------------------------------
RSS_URL = "https://aws.amazon.com/about-aws/whats-new/recent/feed/"
DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE"]
SES_SENDER = os.environ["SES_SENDER"]
SES_RECIPIENT = os.environ["SES_RECIPIENT"]
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
AWS_REGION = os.environ.get("AWS_REGION", "ap-southeast-2")
MAX_ANNOUNCEMENTS = int(os.environ.get("MAX_ANNOUNCEMENTS", "50"))

# ---------------------------------------------------------------------------
# AWS clients
# ---------------------------------------------------------------------------
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
ses = boto3.client("ses", region_name=AWS_REGION)


# ---------------------------------------------------------------------------
# RSS parsing
# ---------------------------------------------------------------------------
def fetch_feed(url: str) -> list[dict]:
    """Fetch and parse the AWS What's New RSS feed."""
    with urllib.request.urlopen(url, timeout=30) as response:
        content = response.read()

    root = ET.fromstring(content)
    channel = root.find("channel")
    items = []

    for item in channel.findall("item"):
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        description = item.findtext("description", "").strip()
        pub_date = item.findtext("pubDate", "").strip()
        guid = item.findtext("guid", "").strip()

        # Fall back to a hash of the link if guid is missing
        if not guid:
            guid = hashlib.md5(link.encode()).hexdigest()

        items.append(
            {
                "guid": guid,
                "title": title,
                "link": link,
                "description": description,
                "pub_date": pub_date,
            }
        )

    return items[:MAX_ANNOUNCEMENTS]


# ---------------------------------------------------------------------------
# DynamoDB deduplication
# ---------------------------------------------------------------------------
def get_processed_guids(table_name: str) -> set[str]:
    """Return all GUIDs already stored in the tracking table."""
    table = dynamodb.Table(table_name)
    guids = set()
    response = table.scan(ProjectionExpression="guid")
    guids.update(item["guid"] for item in response.get("Items", []))

    # Handle pagination
    while "LastEvaluatedKey" in response:
        response = table.scan(
            ProjectionExpression="guid",
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        guids.update(item["guid"] for item in response.get("Items", []))

    return guids


def mark_guids_processed(table_name: str, items: list[dict]) -> None:
    """Write new GUIDs to the tracking table with a timestamp."""
    table = dynamodb.Table(table_name)
    now = datetime.now(timezone.utc).isoformat()

    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(
                Item={
                    "guid": item["guid"],
                    "title": item["title"],
                    "processed_at": now,
                }
            )


# ---------------------------------------------------------------------------
# Bedrock summarisation
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are a concise AWS technical writer. "
    "Your job is to summarise AWS What's New announcements clearly and plainly. "
    "For each announcement write exactly 2-3 sentences: "
    "first explain what has been announced, "
    "then explain what problem it solves or what capability it adds. "
    "Do not use marketing language. Do not add bullet points or headers. "
    "Write in plain English suitable for a LinkedIn post or Teams message."
)


def clean_text(raw: str) -> str:
    """Remove HTML tags and entities from RSS text and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def trim_to_sentence(text: str, max_chars: int = 600) -> str:
    """
    Shorten text to at most max_chars, ending on a complete sentence.
    If no sentence ends within the limit, end on a whole word instead.
    """
    if len(text) <= max_chars and re.search(r"[.!?]$", text):
        return text
    window = text[:max_chars]
    sentence_ends = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", window)]
    if sentence_ends:
        return window[: sentence_ends[-1]].strip()
    if len(text) <= max_chars:
        return text
    return window.rsplit(" ", 1)[0].rstrip(",;:") + "..."


def summarise_announcements(items: list[dict]) -> tuple[list[dict], int]:
    """
    Call Bedrock to summarise each announcement individually.
    Returns the items with a 'summary' key added, and the number of
    announcements Bedrock failed to summarise.
    """
    summarised = []
    failures = 0

    for item in items:
        description = clean_text(item["description"])
        user_message = (
            f"Title: {item['title']}\n\n"
            f"Description: {description}\n\n"
            "Write a 2-3 sentence summary of this announcement."
        )

        # Nova models require content to be a list of content blocks.
        payload = {
            "messages": [{"role": "user", "content": [{"text": user_message}]}],
            "system": [{"text": SYSTEM_PROMPT}],
            "inferenceConfig": {
                "maxTokens": 300,
                "temperature": 0.3,
            },
        }

        try:
            response = bedrock.invoke_model(
                modelId=BEDROCK_MODEL_ID,
                body=json.dumps(payload),
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(response["body"].read())
            summary = result["output"]["message"]["content"][0]["text"].strip()
            if result.get("stopReason") == "max_tokens":
                summary = trim_to_sentence(summary)
        except (ClientError, KeyError, IndexError, ValueError) as exc:
            failures += 1
            print(f"Bedrock error for '{item['title']}': {exc}")
            summary = trim_to_sentence(description)

        summarised.append({**item, "summary": summary})

    return summarised, failures


# ---------------------------------------------------------------------------
# Email composition
# ---------------------------------------------------------------------------
def build_email(items: list[dict], run_time: str) -> tuple[str, str, str]:
    """
    Build plain-text and HTML versions of the summary email.
    Returns (subject, html_body, text_body).
    """
    count = len(items)
    plural = "s" if count != 1 else ""
    subject = f"AWS What's New \u2014 {count} announcement{plural} ({run_time})"

    # --- Plain text ---
    text_lines = [
        "AWS What's New Summary",
        f"Run time: {run_time} UTC",
        f"New announcements: {count}",
        "",
        "=" * 60,
        "",
    ]
    for idx, item in enumerate(items, start=1):
        text_lines += [
            f"{idx}. {item['title']}",
            "",
            item["summary"],
            "",
            f"Read more: {item['link']}",
            "",
            "-" * 60,
            "",
        ]
    text_lines += [
        "This summary was generated automatically by the AWS What's New Summary Tool.",
        "https://github.com/gluxford/aws-whats-new-summary-tool",
    ]
    text_body = "\n".join(text_lines)

    # --- HTML (table-based for email client compatibility) ---
    # Feed text is escaped so it cannot inject markup into the email.
    html_items = ""
    for idx, item in enumerate(items, start=1):
        title = html.escape(item["title"])
        summary = html.escape(item["summary"])
        link = html.escape(item["link"], quote=True)
        html_items += (
            '<div style="margin-bottom:28px;padding-bottom:20px;border-bottom:1px solid #e0e0e0;">'
            f'<h3 style="margin:0 0 6px 0;font-size:16px;color:#232f3e;">{idx}. {title}</h3>'
            f'<p style="margin:0 0 10px 0;color:#333;line-height:1.6;">{summary}</p>'
            f'<a href="{link}" style="color:#ff9900;font-weight:bold;text-decoration:none;">'
            "Read the full announcement &rarr;</a>"
            "</div>\n"
        )

    html_body = (
        '<!DOCTYPE html><html lang="en">'
        '<head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        '<body style="font-family:Arial,sans-serif;background:#f4f4f4;margin:0;padding:0;">'
        '<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:30px 0;">'
        '<tr><td align="center">'
        '<table width="640" cellpadding="0" cellspacing="0" '
        'style="background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">'
        '<tr><td style="background:#232f3e;padding:24px 32px;">'
        '<h1 style="margin:0;color:#ff9900;font-size:22px;">AWS What\'s New</h1>'
        f'<p style="margin:4px 0 0 0;color:#aab7c4;font-size:13px;">'
        f"{count} new announcement{plural} &nbsp;&middot;&nbsp; {run_time} UTC</p>"
        "</td></tr>"
        f'<tr><td style="padding:32px;">{html_items}</td></tr>'
        '<tr><td style="background:#f8f8f8;padding:16px 32px;border-top:1px solid #e0e0e0;">'
        '<p style="margin:0;font-size:11px;color:#999;text-align:center;">'
        'Generated by <a href="https://github.com/gluxford/aws-whats-new-summary-tool" '
        'style="color:#999;">aws-whats-new-summary-tool</a>'
        "</p></td></tr>"
        "</table></td></tr></table></body></html>"
    )

    return subject, html_body, text_body


# ---------------------------------------------------------------------------
# SES sending
# ---------------------------------------------------------------------------
def send_email(subject: str, html_body: str, text_body: str) -> None:
    """Send the summary email via Amazon SES."""
    ses.send_email(
        Source=SES_SENDER,
        Destination={"ToAddresses": [SES_RECIPIENT]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {
                "Text": {"Data": text_body, "Charset": "UTF-8"},
                "Html": {"Data": html_body, "Charset": "UTF-8"},
            },
        },
    )


# ---------------------------------------------------------------------------
# Lambda entrypoint
# ---------------------------------------------------------------------------
def lambda_handler(event, context):
    """Main Lambda handler."""
    run_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    print(f"Starting run at {run_time} UTC")

    # 1. Fetch RSS feed
    print("Fetching RSS feed...")
    all_items = fetch_feed(RSS_URL)
    print(f"Feed contains {len(all_items)} items")

    # 2. Filter to only new items
    processed_guids = get_processed_guids(DYNAMODB_TABLE)
    new_items = [i for i in all_items if i["guid"] not in processed_guids]
    print(f"New items since last run: {len(new_items)}")

    if not new_items:
        print("No new announcements \u2014 skipping email.")
        return {"statusCode": 200, "body": "No new announcements."}

    # 3. Summarise with Bedrock
    print(f"Summarising with Amazon Bedrock ({BEDROCK_MODEL_ID})...")
    summarised, failures = summarise_announcements(new_items)
    print(f"Bedrock summarised {len(new_items) - failures} of {len(new_items)} items.")

    # If every call failed, Bedrock is broken (permissions, model access,
    # request format). Fail the run without emailing or marking anything
    # processed, so the next run retries these announcements.
    if failures == len(new_items):
        raise RuntimeError(
            f"Bedrock failed for all {failures} announcements. "
            "No email sent; the items will be retried on the next run."
        )

    # 4. Build and send email
    subject, html_body, text_body = build_email(summarised, run_time)
    print(f"Sending email: '{subject}'")
    send_email(subject, html_body, text_body)
    print("Email sent successfully.")

    # 5. Mark items as processed (after successful send)
    mark_guids_processed(DYNAMODB_TABLE, new_items)
    print(f"Marked {len(new_items)} items as processed.")

    return {
        "statusCode": 200,
        "body": f"Processed and emailed {len(new_items)} announcements.",
    }
