#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# package.sh
#
# Packages the Lambda function and uploads it to the deployment S3 bucket.
# Run this before deploying or updating the CloudFormation stack.
#
# Usage:
#   ./scripts/package.sh <s3-bucket-name> [aws-profile]
#
# Example:
#   ./scripts/package.sh my-deployment-bucket mymlpg
# -----------------------------------------------------------------------------
set -euo pipefail

BUCKET="${1:?Usage: $0 <s3-bucket-name> [aws-profile]}"
PROFILE="${2:-}"
LAMBDA_DIR="lambda"
BUILD_DIR=".build"
ZIP_NAME="whats_new_summary.zip"

PROFILE_ARG=""
if [[ -n "$PROFILE" ]]; then
  PROFILE_ARG="--profile $PROFILE"
fi

echo "==> Cleaning build directory..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

echo "==> Installing Python dependencies..."
pip3 install \
  --quiet \
  --target "$BUILD_DIR" \
  --requirement "$LAMBDA_DIR/requirements.txt"

echo "==> Copying Lambda handler..."
cp "$LAMBDA_DIR/handler.py" "$BUILD_DIR/"

echo "==> Creating deployment ZIP..."
(cd "$BUILD_DIR" && zip -r -q "../$ZIP_NAME" .)

echo "==> Uploading to s3://$BUCKET/$ZIP_NAME ..."
# shellcheck disable=SC2086
aws s3 cp "$ZIP_NAME" "s3://$BUCKET/$ZIP_NAME" $PROFILE_ARG

echo "==> Cleaning up local ZIP..."
rm -f "$ZIP_NAME"

echo ""
echo "Done. Deployment package uploaded to s3://$BUCKET/$ZIP_NAME"
echo ""
echo "Next step — deploy the CloudFormation stack:"
echo ""
echo "  aws cloudformation deploy \\"
echo "    --template-file cloudformation/template.yaml \\"
echo "    --stack-name aws-whats-new-summary-tool \\"
echo "    --capabilities CAPABILITY_NAMED_IAM \\"
echo "    --region ap-southeast-2 \\"
echo "    --parameter-overrides \\"
echo "      DeploymentBucket=\$BUCKET \\"
echo "      SenderEmail=gluxford@gmail.com \\"
echo "      RecipientEmail=gluxford@gmail.com \\"
echo "    \$PROFILE_ARG"
