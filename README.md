# AWS What's New Summary Tool

Automatically fetches the [AWS What's New](https://aws.amazon.com/about-aws/whats-new/recent/) RSS feed, summarises new announcements using Amazon Bedrock, and emails a clean daily digest to your inbox — formatted for easy sharing on LinkedIn or Microsoft Teams.

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
6. Processed item GUIDs are recorded in DynamoDB to prevent reprocessing on the next run.

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
| Amazon S3 | Lambda deployment package storage |
| AWS CloudFormation | Infrastructure as code |
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

### S3 (deployment package)

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
2. **S3 bucket** in `ap-southeast-2` to stage the Lambda deployment package:
   ```bash
   aws s3 mb s3://YOUR-DEPLOYMENT-BUCKET --region ap-southeast-2 --profile mymlpg
   ```
3. **Bedrock Nova Lite access** — enable the model in your account:
   - Open the [Bedrock Model Access console](https://ap-southeast-2.console.aws.amazon.com/bedrock/home?region=ap-southeast-2#/modelaccess)
   - Request access for **Amazon Nova Lite** (approval is usually instant).
4. **Python 3** and **pip** installed locally.
5. **Git** installed locally.

---

## Deployment

### Step 1 — Clone the repository

```bash
git clone git@github.com:gluxford/aws-whats-new-summary-tool.git
cd aws-whats-new-summary-tool
```

### Step 2 — Package and upload the Lambda function

```bash
chmod +x scripts/package.sh
./scripts/package.sh YOUR-DEPLOYMENT-BUCKET mymlpg
```

This installs Python dependencies, zips the Lambda code, and uploads the package to your S3 bucket.

### Step 3 — Deploy the CloudFormation stack

```bash
aws cloudformation deploy \
  --template-file cloudformation/template.yaml \
  --stack-name aws-whats-new-summary-tool \
  --capabilities CAPABILITY_NAMED_IAM \
  --region ap-southeast-2 \
  --parameter-overrides \
    DeploymentBucket=YOUR-DEPLOYMENT-BUCKET \
    SenderEmail=gluxford@gmail.com \
    RecipientEmail=gluxford@gmail.com \
  --profile mymlpg
```

### Step 4 — Verify your email address

After the stack deploys, AWS SES sends a **verification email** to the address you supplied. Click the confirmation link in that email. The tool will not send emails until this step is complete.

> **SES sandbox note:** New AWS accounts start in SES sandbox mode, which restricts sending to verified addresses only. For personal use this is fine. See [Moving out of SES sandbox](#moving-out-of-ses-sandbox) if you ever need to send to additional recipients.

### Step 5 — Confirm the stack deployed correctly

```bash
aws cloudformation describe-stacks \
  --stack-name aws-whats-new-summary-tool \
  --region ap-southeast-2 \
  --query "Stacks[0].Outputs" \
  --profile mymlpg
```

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

The default schedule is **daily at 03:00 AEST (17:00 UTC)**. To change it, redeploy with a new `ScheduleExpression`:

```bash
aws cloudformation deploy \
  --template-file cloudformation/template.yaml \
  --stack-name aws-whats-new-summary-tool \
  --capabilities CAPABILITY_NAMED_IAM \
  --region ap-southeast-2 \
  --parameter-overrides \
    DeploymentBucket=YOUR-DEPLOYMENT-BUCKET \
    SenderEmail=gluxford@gmail.com \
    RecipientEmail=gluxford@gmail.com \
    ScheduleExpression="cron(0 5,17 * * ? *)" \
  --profile mymlpg
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

Delete the stack (the DynamoDB table is retained by default to preserve deduplication history):

```bash
aws cloudformation delete-stack \
  --stack-name aws-whats-new-summary-tool \
  --region ap-southeast-2 \
  --profile mymlpg
```

To also remove the DynamoDB table after the stack is deleted:

```bash
aws dynamodb delete-table \
  --table-name aws-whats-new-summary-tool-processed-announcements \
  --region ap-southeast-2 \
  --profile mymlpg
```

---

## Project structure

```
aws-whats-new-summary-tool/
├── cloudformation/
│   └── template.yaml        # All AWS infrastructure
├── lambda/
│   ├── handler.py           # Lambda function
│   └── requirements.txt     # Python dependencies
├── scripts/
│   └── package.sh           # Build and upload Lambda ZIP
├── .gitignore
└── README.md
```

---

## Contributing

Pull requests are welcome. Please open an issue first to discuss significant changes.

## Licence

[MIT](https://opensource.org/licenses/MIT)
