#!/usr/bin/env bash
# Runs the summary function immediately, outside the schedule.
#
# Usage: ./scripts/invoke.sh

source "$(dirname "$0")/common.sh"

echo "==> Checking AWS credentials"
check_credentials

echo "==> Invoking $FUNCTION_NAME (this can take a minute)"
RESPONSE_FILE="$(mktemp)"
trap 'rm -f "$RESPONSE_FILE"' EXIT

# The read timeout is longer than the function's 300 s timeout so the CLI
# does not give up and retry, which would trigger a second run.
FUNCTION_ERROR="$(aws lambda invoke \
  --function-name "$FUNCTION_NAME" \
  --payload '{"source": "manual"}' \
  --cli-binary-format raw-in-base64-out \
  --cli-read-timeout 310 \
  --query FunctionError \
  --output text \
  "$RESPONSE_FILE")"

cat "$RESPONSE_FILE"
echo

if [[ "$FUNCTION_ERROR" != "None" ]]; then
  echo
  echo "The function returned an error. Recent logs:"
  aws logs tail "/aws/lambda/$FUNCTION_NAME" --since 15m
  exit 1
fi
