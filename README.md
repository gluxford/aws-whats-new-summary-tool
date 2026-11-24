# AWS What's New Summary Tool

Fetches the [AWS What's New](https://aws.amazon.com/about-aws/whats-new/recent/) RSS feed, summarises new announcements with Amazon Bedrock (Nova Lite), and emails you a digest that is easy to paste into a LinkedIn post or Teams message. Each run only includes announcements it has not already sent.

---

## Table of contents

1. [How it works](#how-it-works)
2. [Architecture](#architecture)
3. [Estimated costs](#estimated-costs)
4. [Prerequisites](#prerequisites)
5. [Deployment](#deployment)
6. [Invoking the solution manually](#invoking-the-solution-manually)
7. [Changing settings and the schedule](#changing-settings-and-the-schedule)
8. [Moving out of the SES sandbox](#moving-out-of-the-ses-sandbox)
9. [Teardown](#teardown)
10. [Deploying without the scripts](#deploying-without-the-scripts)
11. [Project structure](#project-structure)

---

## How it works

1. **EventBridge Scheduler** invokes the Lambda function once a day at 03:00 AEST (17:00 UTC) by default.
2. The **Lambda function** downloads the AWS What's New RSS feed.
3. It compares each item's GUID with a **DynamoDB** table and skips anything already processed.
4. It sends each new item to **Amazon Bedrock (Nova Lite)** for a 2-3 sentence summary.
5. It emails the summaries, each with a link to the announcement, through **Amazon SES**.
6. After the email is sent, it records the new GUIDs in DynamoDB so the next run does not repeat them.

---

## Architecture

```
EventBridge Scheduler (default: daily, 03:00 AEST)
        |
        v
  Lambda function ---- HTTPS ----> AWS What's New RSS feed
        |
        |-- DynamoDB   (read processed GUIDs, write new GUIDs)
        |-- Bedrock    (Nova Lite summarises each new announcement)
        '-- SES        (sends the summary email)
```

| Service | Purpose |
|---|---|
| AWS Lambda (Python 3.12) | Runs the logic |
| Amazon EventBridge Scheduler | Triggers the run on a schedule |
| Amazon DynamoDB (on-demand) | Tracks processed announcements |
| Amazon Bedrock, Nova Lite | Summarisation |
| Amazon SES | Email delivery |
| Amazon S3 (CDK bootstrap bucket) | Stores the Lambda package |
| AWS CloudFormation (via CDK) | Deploys the infrastructure |
| Amazon CloudWatch Logs | Lambda logs, 30-day retention |

Default region: `ap-southeast-2` (Sydney). You can change it in `config.env`.

---

## Estimated costs

Assumes 20 new announcements per day and one run per day, using public list prices.

| Service | Basis | Monthly cost |
|---|---|---|
| Lambda | ~30 runs, ~60 s each at 256 MB | < $0.01 (free tier) |
| Bedrock Nova Lite | ~10,000 input and ~2,000 output tokens per run | ~$0.03 |
| DynamoDB on-demand | ~20 writes and a small scan per day | < $0.01 |
| SES | ~30 emails at $0.10 per 1,000 | < $0.01 |
| S3 | ~20 MB package in the CDK bootstrap bucket | < $0.01 |
| CloudWatch Logs | ~1 MB ingested | < $0.01 |
| **Total (normal)** | | **about $0.05** |
| **Total (re:Invent peak, ~50 per day)** | | **about $0.12** |

These are estimates, so check current pricing for your region. The AWS Free Tier reduces the cost further for new accounts.

---

## Prerequisites

### 1. Install the tools

| Tool | Notes |
|---|---|
| [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) | Authentication and SES verification |
| [Node.js](https://nodejs.org/) | Required by the CDK CLI |
| [AWS CDK CLI](https://docs.aws.amazon.com/cdk/v2/guide/getting-started.html) | `npm install -g aws-cdk` |
| [Python 3.9+](https://www.python.org/downloads/) | Runs the CDK app |
| [Docker](https://docs.docker.com/get-docker/) | Bundles the Lambda dependencies. It must be **running** when you deploy |
| [Git](https://git-scm.com/) | To clone the repository |
| Bash | Runs the scripts. Built into macOS and Linux; on Windows use WSL or Git Bash |

Use a recent CDK CLI. If a deploy reports a "Cloud assembly schema version mismatch", run `npm install -g aws-cdk` again.

### 2. Create a local AWS CLI profile

The scripts sign in to AWS with a named profile. Create one for the account you want to deploy into. You choose the profile name, for example `whats-new-deploy`.

**With IAM Identity Center (SSO):**

```bash
aws configure sso --profile whats-new-deploy
```

The CLI asks for your SSO start URL, SSO region, account and role, then opens a browser to sign in. SSO sessions expire, so sign in again when the scripts report an authentication error:

```bash
aws sso login --profile whats-new-deploy
```

**With IAM user access keys:** run `aws configure --profile whats-new-deploy` instead.

Check that the profile works:

```bash
aws sts get-caller-identity --profile whats-new-deploy
```

The role needs permission to create IAM roles, Lambda functions, DynamoDB tables, EventBridge schedules and CloudWatch log groups, and to use SES and CloudFormation. An administrator role is simplest for a personal account.

### 3. Bedrock access

Bedrock serverless models such as Nova Lite are enabled automatically the first time they are invoked, and the old "Model access" page has been retired. If the first run fails with a Bedrock access error, open Nova Lite in the [Bedrock console](https://ap-southeast-2.console.aws.amazon.com/bedrock/home?region=ap-southeast-2#/model-catalog) and send one prompt in the playground. Organisation policies (SCPs) can also block Bedrock, so check with your administrator if you use a managed account.

---

## Deployment

### Step 1. Clone the repository

```bash
git clone https://github.com/gluxford/aws-whats-new-summary-tool.git
cd aws-whats-new-summary-tool
```

### Step 2. Create your config file

```bash
cp config.env.example config.env
```

Open `config.env` and set at least these two values:

| Variable | Set it to |
|---|---|
| `AWS_PROFILE` | The profile name you created in [Prerequisites](#2-create-a-local-aws-cli-profile) |
| `RECIPIENT_EMAIL` | Your real email address. The summaries go here |

The other variables are optional and documented in the file:

| Variable | Default | Purpose |
|---|---|---|
| `AWS_REGION` | `ap-southeast-2` | Region to deploy into |
| `SENDER_EMAIL` | same as `RECIPIENT_EMAIL` | The From address |
| `SCHEDULE_EXPRESSION` | `cron(0 17 * * ? *)` | When to run, in UTC |
| `MAX_ANNOUNCEMENTS` | `50` | Maximum RSS items checked per run |
| `BEDROCK_MODEL_ID` | `amazon.nova-lite-v1:0` | Model used for summaries |

`config.env` is listed in `.gitignore`, so your details are never committed. The scripts stop with a message if a required value is missing or still set to the template value.

### Step 3. Start Docker and sign in

Start Docker. If your profile uses SSO, sign in:

```bash
aws sso login --profile YOUR_PROFILE_NAME
```

### Step 4. Deploy

```bash
./scripts/deploy.sh
```

The script:

1. Checks that the AWS CLI, CDK CLI, Python and Docker are installed and that Docker is running.
2. Checks that your profile can sign in to AWS.
3. Checks whether your email address is verified in SES. If it is not, the script asks SES to send you a verification email.
4. Bootstraps CDK in your account and region if that has not been done.
5. Creates a Python virtual environment for CDK and installs its dependencies.
6. Runs `cdk deploy`, which shows the IAM changes and asks you to confirm. Enter `y`.

Deployment takes about two minutes. To preview the changes without deploying anything, run `./scripts/deploy.sh --diff`.

### Step 5. Verify your email address

If the script reported that your address was not verified, find the email from Amazon Web Services (subject "Amazon Web Services – Email Address Verification Request") and **click the link in it**. Check your spam folder if it has not arrived after a few minutes.

SES does not send any email until the address is verified. Run `./scripts/deploy.sh --diff` to confirm the status now shows `verified`. The address is verified per region, so it has to be verified in the region set in `config.env`.

### Step 6. Run it once

```bash
./scripts/invoke.sh
```

The first run summarises up to 50 of the latest announcements, so expect a long email. After that, each run only sends announcements published since the previous run.

---

## Invoking the solution manually

You can run the function at any time without waiting for the schedule, for example during re:Invent when announcements arrive outside the normal window.

### From your machine

```bash
./scripts/invoke.sh
```

The script uses the profile and region in `config.env`, prints the result, and shows recent logs if the function fails.

### From AWS CloudShell

CloudShell uses the credentials of the account you are signed in to, so it needs no profile or config file. Open CloudShell in the AWS Console, in the region you deployed to, and paste:

```bash
aws lambda invoke \
  --function-name aws-whats-new-summary-tool-summary \
  --payload '{"source": "manual"}' \
  --cli-binary-format raw-in-base64-out \
  --cli-read-timeout 310 \
  response.json && cat response.json
```

The `--cli-read-timeout 310` option stops the CLI from timing out and retrying, which would trigger a second run.

### Reading the result

If there are new announcements, the email arrives within a minute or so and the command prints:

```json
{"statusCode": 200, "body": "Processed and emailed 5 announcements."}
```

If nothing has been published since the last run, no email is sent:

```json
{"statusCode": 200, "body": "No new announcements."}
```

To read the logs in CloudShell:

```bash
aws logs tail /aws/lambda/aws-whats-new-summary-tool-summary --since 15m
```

---

## Changing settings and the schedule

Edit `config.env` and run `./scripts/deploy.sh` again. For example, to run twice a day during re:Invent:

```bash
SCHEDULE_EXPRESSION="cron(0 5,17 * * ? *)"
```

Cron expressions are in UTC:

| Goal | Expression |
|---|---|
| Daily at 03:00 AEST | `cron(0 17 * * ? *)` |
| Every 12 hours (03:00 and 15:00 AEST) | `cron(0 5,17 * * ? *)` |
| Every 6 hours | `cron(0 1,7,13,19 * * ? *)` |

Australian daylight saving moves Sydney to UTC+11 from October to April, so a fixed UTC time runs an hour later in local time during that period.

---

## Moving out of the SES sandbox

In sandbox mode SES only delivers to verified addresses. That is enough for a single recipient. To send to unverified addresses such as a team list, request production access:

1. Open the SES console in your deployment region and choose **Account dashboard**.
2. Choose **Request production access**.
3. Fill in the form:
   - **Mail type:** Transactional
   - **Website URL:** this repository's URL
   - **Use case:** describe the tool, who receives the email, and that recipients have opted in
   - **Expected volume:** about 30 emails per month
4. Submit. AWS typically replies within 24 hours, and the request opens a case you can follow in the AWS Support Center.

---

## Teardown

```bash
./scripts/destroy.sh
```

CDK asks you to confirm. The DynamoDB table and your SES identity are kept, and the script prints the commands to delete them if you want to.

---

## Deploying without the scripts

The CDK app reads the same variables from the environment, so you can run CDK directly:

```bash
set -a; source config.env; set +a
cd cdk
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export PATH="$PWD/.venv/bin:$PATH"
cdk deploy
```

A `--context` value overrides the matching variable, for example `cdk deploy --context recipient_email=you@yourdomain.com`. The context keys are `recipient_email`, `sender_email`, `schedule_expression`, `max_announcements` and `bedrock_model_id`. In this case you need to verify the SES address and bootstrap CDK yourself.

---

## Project structure

```
aws-whats-new-summary-tool/
├── config.env.example      # Template for your settings (copy to config.env)
├── scripts/
│   ├── common.sh           # Loads config.env and shared checks
│   ├── deploy.sh           # Checks prerequisites, verifies SES, deploys
│   ├── invoke.sh           # Runs the function on demand
│   └── destroy.sh          # Removes the stack
├── cdk/
│   ├── app.py              # CDK app entry point
│   ├── stack.py            # All AWS resources
│   ├── cdk.json            # CDK configuration
│   └── requirements.txt    # CDK dependencies
├── lambda/
│   ├── handler.py          # Lambda function
│   └── requirements.txt    # Lambda dependencies
├── .gitignore
└── README.md
```

---

## Contributing

Pull requests are welcome. Please open an issue first to discuss significant changes.

The `main` branch is protected. Every change goes through a pull request and needs approval from the code owner listed in `.github/CODEOWNERS`. Force pushes and branch deletion are blocked.

If you fork this repository and want the same protection, import `.github/rulesets/protect-main.json` under **Settings → Rules → Rulesets → New ruleset → Import a ruleset**, and change the owner in `.github/CODEOWNERS` to your GitHub username.

## Licence

[MIT](https://opensource.org/licenses/MIT)
