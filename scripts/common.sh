#!/usr/bin/env bash
# Shared setup for the scripts in this folder. Sourced by them, not run directly.
#
# Loads config.env from the repository root, applies defaults, and exports the
# values so the AWS CLI, the CDK CLI and cdk/app.py all see the same settings.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="$REPO_ROOT/config.env"
STACK_NAME="aws-whats-new-summary-tool"
FUNCTION_NAME="$STACK_NAME-summary"

if [[ -f "$CONFIG_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
  set +a
else
  echo "config.env not found. Create it from the template and set your values:"
  echo
  echo "  cp config.env.example config.env"
  echo
  exit 1
fi

: "${AWS_REGION:=ap-southeast-2}"
: "${SENDER_EMAIL:=${RECIPIENT_EMAIL:-}}"
export AWS_REGION SENDER_EMAIL
export AWS_DEFAULT_REGION="$AWS_REGION"

# Fails if any named variable is empty or still holds the template value.
require() {
  local name value
  for name in "$@"; do
    value="${!name:-}"
    if [[ -z "$value" || "$value" == "your-profile-name" || "$value" == *"@example.com" ]]; then
      echo "Set $name in config.env (current value: '${value}')."
      exit 1
    fi
  done
}

require AWS_PROFILE
export AWS_PROFILE

# Confirms the profile can authenticate and sets ACCOUNT_ID.
check_credentials() {
  if ! ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text 2>/dev/null)"; then
    echo "Could not authenticate with AWS profile '$AWS_PROFILE'."
    echo "If it is an SSO profile, sign in first:"
    echo
    echo "  aws sso login --profile $AWS_PROFILE"
    echo
    exit 1
  fi
  echo "    account $ACCOUNT_ID, region $AWS_REGION, profile $AWS_PROFILE"
}

# Creates the CDK virtual environment if needed and puts it first on PATH.
prepare_cdk() {
  cd "$REPO_ROOT/cdk"
  [[ -d .venv ]] || python3 -m venv .venv
  .venv/bin/pip install --quiet --disable-pip-version-check -r requirements.txt
  export PATH="$REPO_ROOT/cdk/.venv/bin:$PATH"
}
