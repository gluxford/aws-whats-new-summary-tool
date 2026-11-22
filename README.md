# AWS What's New Summary Tool

Automatically fetches the [AWS What's New](https://aws.amazon.com/about-aws/whats-new/recent/) RSS feed, summarises new announcements using Amazon Bedrock Nova Lite, and emails a clean daily digest to your inbox — formatted for easy sharing on LinkedIn or Microsoft Teams.

---

## Table of Contents

1. [How it works](#how-it-works)
2. [Architecture](#architecture)
3. [Estimated costs](#estimated-costs)
4. [Prerequisites](#prerequisites)
5. [Deployment](#deployment)
6. [On-demand invocation](#on-demand-invocation)
7. [Changing the schedule](#changing-the-schedule)
8. [Moving out of SES sandbox](#moving-out-of-ses-sandbox)
9. [Teardown](#teardown)
10. [Project structure](#project-structure)

---

## How it works

1. **EventBridge Scheduler** triggers the Lambda function daily at 03:00 AEST (17:00 UTC).
2. The **Lambda function** fetches the AWS What's New RSS feed.
3. Each announcement is checked against a **DynamoDB table** — items already processed in a previous run are skipped, ensuring no duplicate emails.
4. New announcements are sent to **Amazon Bedrock (Nova Lite)** for a concise 2–3 sentence summary.
5. **Amazon SES** sends a formatted HTML email listing every new announcement with its summary and a direct link to the announcement page.
6. Processed item GUIDs are written back to DynamoDB to prevent reprocessing on the next run.

---

## Architecture

```
EventBridge Scheduler (daily, 03:00 AEST)
        │
        ▼
  Lambda Function  ──── HTTPS ────►  AWS What's New RSS Feed
        │
        ├── DynamoDB Table  (read processed GUIDs, write new GUIDs)
        │
        ├── Bedrock Nova Lite  (summarise each new announcement)
        │
        └── SES  (send HTML summary email)
```

**AWS services used:**

| Service | Purpose |
|---|---|
| AWS Lambda (Python 3.12) | Core processing |
| Amazon EventBridge Scheduler | Daily cron trigger |
| Amazon DynamoDB (on-demand) | Deduplication tracking |
| Amazon Bedrock — Nova Lite | AI summarisation |
| Amazon SES | Email delivery |
| Amazon S3 (CDK bootstrap bucket) | Lambda deployment package |
| AWS CloudFormation (via CDK) | Infrastructure as code |
| Amazon CloudWatch Logs | Lambda execution logs (30-day retention) |

**Region:** `ap-southeast-2` (Sydney)

---

## Estimated costs

All estimates assume **20 new announcements per day** in `ap-southeast-2`. Prices are AWS public list prices.

### Lambda

| Metric | Value |
|---|---|
| Invocations | ~30/month |
| Duration | ~60 s average at 256 MB |
| GB-seconds/month | ~450 |
| **Monthly cost** | **< $0.01** (well within free tier) |

### Amazon Bedrock — Nova Lite

| Metric | Value |
|---|---|
| Input tokens per run | ~10,000 |
| Output tokens per run | ~2,000 |
| Input price | $0.00006 / 1K tokens |
| Output price | $0.00024 / 1K tokens |
| **Monthly cost** | **~$0.03** |

### DynamoDB (on-demand)

| Metric | Value |
|---|---|
| Write request units/day | ~20 |
| Read request units/day | < 100 (scan) |
| Storage | < 1 MB |
| **Monthly cost** | **< $0.01** |

### Amazon SES

| Metric | Value |
|---|---|
| Emails sent/month | ~30 |
| Price | $0.10 / 1,000 emails |
| **Monthly cost** | **< $0.01** |

### S3 (CDK bootstrap bucket)

| Metric | Value |
|---|---|
| Storage | ~5 MB ZIP |
| **Monthly cost** | **< $0.01** |

### CloudWatch Logs

| Metric | Value |
|---|---|
| Log ingestion | ~1 MB/month |
| **Monthly cost** | **< $0.01** |

### Total estimated monthly cost

| Scenario | Cost |
|---|---|
| Normal (20 announcements/day) | **~$0.05 / month** |
| re:Invent peak (50 announcements/day) | **~$0.12 / month** |

> AWS Free Tier covers Lambda, DynamoDB, and CloudWatch Logs for new accounts during the first 12 months, reducing actual costs further.

---

## Prerequisites

1. **AWS account** with an SSO profile configured locally (`mymlpg`).
2. **CDK bootstrapped** in `ap-southeast-2` (one-time per account/region):
   ```bash
   cdk bootstrap aws://YOUR-ACCOUNT-ID/ap-southeast-2 --profile mymlpg
   ```
3. **SES email verification** — verify your recipient address before the first run:
   ```bash
   aws ses verify-email-identity \
     --email-address gluxford@gmail.com \
     --region ap-southeast-2 \
     --profile mymlpg
   ```
   Then click the confirmation link in the email AWS sends you.
4. **Docker** installed and running (CDK uses it to bundle the Lambda package).
5. **Python 3** and **CDK CLI** installed locally:
   ```bash
   npm install -g aws-cdk
   ```

---

## Deployment

### Step 1 — Clone the repository

```bash
git clone git@github.com:gluxford/aws-whats-new-summary-tool.git
cd aws-whats-new-summary-tool
```

### Step 2 — Set up the Python environment

```bash
cd cdk
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Step 3 — Synthesise (validate before deploying)

```bash
cdk synth --profile mymlpg
```

This generates the CloudFormation template locally without touching AWS. Review the output for any issues.

### Step 4 — Deploy

```bash
cdk deploy --profile mymlpg
```

CDK will show you a resource summary and prompt for confirmation before deploying.

### Step 5 — Verify your email address

If not already done, verify your recipient address:

```bash
aws ses verify-email-identity \
  --email-address gluxford@gmail.com \
  --region ap-southeast-2 \
  --profile mymlpg
```

Check your inbox and click the verification link. The tool will not send emails until this is done.

---

## On-demand invocation

Trigger the function at any time without waiting for the daily schedule — useful during re:Invent or any period with high announcement volume.

### From AWS CloudShell (no local credentials needed)

Open [AWS CloudShell](https://ap-southeast-2.console.aws.amazon.com/cloudshell/home?region=ap-southeast-2) in the AWS Console and run:

```bash
aws lambda invoke \
  --function-name aws-whats-new-summary-tool-summary \
  --region ap-southeast-2 \
  --payload '{"source": "manual"}' \
  --cli-binary-format raw-in-base64-out \
  response.json && cat response.json
```

A successful response:
```json
{"statusCode": 200, "body": "Processed and emailed 5 announcements."}
```

If nothing is new since the last run:
```json
{"statusCode": 200, "body": "No new announcements."}
```

### From your local machine

```bash
aws lambda invoke \
  --function-name aws-whats-new-summary-tool-summary \
  --region ap-southeast-2 \
  --payload '{"source": "manual"}' \
  --cli-binary-format raw-in-base64-out \
  --profile mymlpg \
  response.json && cat response.json
```

---

## Changing the schedule

The default schedule is **daily at 03:00 AEST (17:00 UTC)**. To change it, redeploy with a context override:

```bash
cdk deploy \
  --profile mymlpg \
  --context schedule_expression="cron(0 5,17 * * ? *)"
```

Cron reference — all times in UTC:

| Goal | Expression |
|---|---|
| Daily 03:00 AEST | `cron(0 17 * * ? *)` |
| Every 12 h (03:00 & 15:00 AEST) | `cron(0 5,17 * * ? *)` |
| Every 6 h | `cron(0 1,7,13,19 * * ? *)` |

---

## Moving out of SES sandbox

SES sandbox mode restricts sending to verified addresses only. For personal use with a single recipient this is not a limitation. If you need to send to other addresses, raise a production access request:

1. Open the [SES console](https://ap-southeast-2.console.aws.amazon.com/ses/home?region=ap-southeast-2) and go to **Account dashboard**.
2. Click **Request production access** and complete the support case:
   - **Mail type:** Transactional
   - **Website URL:** `https://github.com/gluxford/aws-whats-new-summary-tool`
   - **Use case:** Personal tool sending daily AWS announcement summaries to opted-in recipients.
   - **Expected volume:** ~30 emails/day.
3. AWS Support typically responds within 24 hours.

---

## Teardown

```bash
cdk destroy --profile mymlpg
```

> The DynamoDB table is retained after destroy to preserve your deduplication history. To remove it manually:
> ```bash
> aws dynamodb delete-table \
>   --table-name aws-whats-new-summary-tool-processed-announcements \
>   --region ap-southeast-2 \
>   --profile mymlpg
> ```

---

## Project structure

```
aws-whats-new-summary-tool/
├── cdk/
│   ├── app.py           # CDK app entry point
│   ├── stack.py         # All AWS infrastructure defined in Python
│   ├── cdk.json         # CDK configuration
│   └── requirements.txt # CDK Python dependencies
├── lambda/
│   ├── handler.py       # Lambda function
│   └── requirements.txt # Lambda Python dependencies (boto3)
├── .gitignore
└── README.md
```

---

## Contributing

Pull requests are welcome. Please open an issue first to discuss significant changes.

## Licence

[MIT](https://opensource.org/licenses/MIT)
