#!/usr/bin/env bash
#
# teardown.sh — delete the AgentCore Web Search CloudFormation stack and everything
# it created (web-search target, gateway, IAM service role).
#
# Configuration (must match what setup.sh used):
#   AWS_PROFILE, REGION, STACK_NAME (default: agentcore-websearch)
#
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

REGION="${REGION:-us-east-1}"
STACK_NAME="${STACK_NAME:-agentcore-websearch}"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

command -v aws >/dev/null || die "aws CLI not found"

AWS_ARGS=(--region "$REGION")
[ -n "${AWS_PROFILE:-}" ] && AWS_ARGS+=(--profile "$AWS_PROFILE")

if ! aws "${AWS_ARGS[@]}" cloudformation describe-stacks --stack-name "$STACK_NAME" >/dev/null 2>&1; then
  warn "No stack named '$STACK_NAME' found in $REGION — nothing to delete."
  exit 0
fi

say "Deleting CloudFormation stack '$STACK_NAME'..."
aws "${AWS_ARGS[@]}" cloudformation delete-stack --stack-name "$STACK_NAME"
say "Waiting for stack deletion to complete..."
aws "${AWS_ARGS[@]}" cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" \
  && say "Teardown complete." \
  || die "stack deletion did not complete — check the CloudFormation console."

# Remove the local .env written by setup.sh (gateway no longer exists).
ENV_FILE="$HERE/skills/agentcore-websearch/.env"
[ -f "$ENV_FILE" ] && { rm -f "$ENV_FILE"; say "Removed $ENV_FILE"; }
