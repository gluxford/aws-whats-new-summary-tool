#!/usr/bin/env bash
# Deletes the stack. The DynamoDB table and SES identity are kept.
#
# Usage: ./scripts/destroy.sh

source "$(dirname "$0")/common.sh"
require RECIPIENT_EMAIL

echo "==> Checking AWS credentials"
check_credentials

echo "==> Preparing CDK environment"
prepare_cdk

echo "==> Destroying stack (CDK asks you to confirm)"
cdk destroy

cat <<EOF

The DynamoDB table was kept so your processed-announcement history survives.
To delete it too:

  aws dynamodb delete-table --table-name $STACK_NAME-processed-announcements \\
    --region $AWS_REGION --profile $AWS_PROFILE

To remove the SES identity:

  aws ses delete-identity --identity $RECIPIENT_EMAIL \\
    --region $AWS_REGION --profile $AWS_PROFILE
EOF
