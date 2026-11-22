#!/usr/bin/env bash
# Deploys or updates the stack using the values in config.env.
#
# Usage:
#   ./scripts/deploy.sh          check prerequisites, then deploy
#   ./scripts/deploy.sh --diff   check prerequisites, show what would change, deploy nothing

source "$(dirname "$0")/common.sh"
require RECIPIENT_EMAIL SENDER_EMAIL

MODE="deploy"
if [[ "${1:-}" == "--diff" ]]; then
  MODE="diff"
fi

echo "==> Checking tools"
for tool in aws cdk python3 docker; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "    $tool is not installed. See Prerequisites in README.md."
    exit 1
  fi
done
if ! docker info >/dev/null 2>&1; then
  echo "    Docker is installed but not running. Start Docker and re-run."
  exit 1
fi
echo "    aws, cdk, python3 and docker found"

echo "==> Checking AWS credentials"
check_credentials

echo "==> Checking SES email verification"
NEEDS_VERIFICATION=0
for email in $(printf '%s\n' "$SENDER_EMAIL" "$RECIPIENT_EMAIL" | sort -u); do
  status="$(aws ses get-identity-verification-attributes \
    --identities "$email" \
    --query "VerificationAttributes.\"$email\".VerificationStatus" \
    --output text)"
  if [[ "$status" == "Success" ]]; then
    echo "    $email: verified"
  elif [[ "$MODE" == "diff" ]]; then
    echo "    $email: not verified (status: $status)"
    NEEDS_VERIFICATION=1
  else
    echo "    $email: not verified (status: $status), sending verification email"
    aws ses verify-email-identity --email-address "$email"
    NEEDS_VERIFICATION=1
  fi
done

echo "==> Checking CDK bootstrap"
if aws cloudformation describe-stacks --stack-name CDKToolkit >/dev/null 2>&1; then
  echo "    already bootstrapped in $AWS_REGION"
elif [[ "$MODE" == "diff" ]]; then
  echo "    not bootstrapped in $AWS_REGION (a normal deploy will do this)"
else
  echo "    bootstrapping $ACCOUNT_ID/$AWS_REGION"
  (cd "$REPO_ROOT" && cdk bootstrap "aws://$ACCOUNT_ID/$AWS_REGION")
fi

echo "==> Preparing CDK environment"
prepare_cdk

if [[ "$MODE" == "diff" ]]; then
  echo "==> Changes that a deploy would make"
  cdk diff
  exit 0
fi

echo "==> Deploying (CDK asks you to confirm any IAM changes)"
cdk deploy

echo
echo "Deployed. Recipient: $RECIPIENT_EMAIL, schedule: ${SCHEDULE_EXPRESSION:-cron(0 17 * * ? *)} (UTC)."
if [[ "$NEEDS_VERIFICATION" -eq 1 ]]; then
  echo
  echo "ACTION NEEDED: open the verification email from AWS and click the link."
  echo "Emails will not send until you do."
fi
echo
echo "To run it now: ./scripts/invoke.sh"
