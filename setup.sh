#!/usr/bin/env bash
#
# setup.sh — provision AgentCore Web Search via AWS CloudFormation.
#
# Deploys cfn/agentcore-websearch.yaml, which creates:
#   1. An IAM service role the gateway assumes (InvokeGateway + InvokeWebSearch).
#   2. An AgentCore Gateway with AWS_IAM inbound auth (callers use local creds).
#   3. A web-search connector target exposing the WebSearch tool.
#
# Then reads the stack's GatewayUrl output and writes it into the search skill's
# .env (skills/agentcore-websearch/.env) so the websearch CLI works immediately.
#
# Configuration via environment (all optional except credentials):
#   AWS_PROFILE     AWS profile to use (or rely on the default credential chain)
#   REGION          default: us-east-1  (Web Search is only in us-east-1)
#   STACK_NAME      default: agentcore-websearch
#   GATEWAY_NAME    default: WebSearchGateway   (CFN parameter)
#   TARGET_NAME     default: web-search-tool    (CFN parameter)
#
# Requirements: AWS CLI v2 >= 2.35.0 (older versions lack the gateway "connector"
# target shape needed for the Web Search tool — the script checks and tells you).
#
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

REGION="${REGION:-us-east-1}"
STACK_NAME="${STACK_NAME:-agentcore-websearch}"
GATEWAY_NAME="${GATEWAY_NAME:-WebSearchGateway}"
TARGET_NAME="${TARGET_NAME:-web-search-tool}"
TEMPLATE="$HERE/cfn/agentcore-websearch.yaml"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

command -v aws >/dev/null || die "aws CLI not found (install AWS CLI v2 >= 2.35.0)"
[ -f "$TEMPLATE" ] || die "template not found: $TEMPLATE"

# The web-search connector target shape was added to the AgentCore CloudFormation
# model in AWS CLI v2 2.35.0. Verify rather than failing mid-deploy.
if ! aws bedrock-agentcore-control create-gateway-target help 2>/dev/null | grep -q "connector"; then
  die "your AWS CLI does not support the 'connector' gateway target.
       Upgrade to AWS CLI v2 >= 2.35.0:  https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
       (current: $(aws --version 2>&1))"
fi

AWS_ARGS=(--region "$REGION")
[ -n "${AWS_PROFILE:-}" ] && AWS_ARGS+=(--profile "$AWS_PROFILE")

say "Account: $(aws "${AWS_ARGS[@]}" sts get-caller-identity --query Account --output text)   Region: $REGION   ($(aws --version 2>&1 | cut -d' ' -f1))"
say "Deploying CloudFormation stack '$STACK_NAME'..."
aws "${AWS_ARGS[@]}" cloudformation deploy \
  --stack-name "$STACK_NAME" \
  --template-file "$TEMPLATE" \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides "GatewayName=$GATEWAY_NAME" "TargetName=$TARGET_NAME" \
  || die "stack deploy failed — see: aws cloudformation describe-stack-events --stack-name $STACK_NAME --region $REGION"

GATEWAY_URL="$(aws "${AWS_ARGS[@]}" cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='GatewayUrl'].OutputValue | [0]" --output text)"
[ -n "$GATEWAY_URL" ] && [ "$GATEWAY_URL" != "None" ] || die "could not read GatewayUrl output"

echo
say "✅ AgentCore Web Search is ready."
echo
echo "  Gateway URL:"
echo "    $GATEWAY_URL"
echo

# Write the gateway URL into the search skill's .env so the websearch CLI works now.
SKILL_DIR="$HERE/skills/agentcore-websearch"
ENV_FILE="$SKILL_DIR/.env"
if [ -d "$SKILL_DIR" ]; then
  if [ -f "$ENV_FILE" ]; then
    warn ".env already exists at $ENV_FILE — not overwriting."
    warn "Update AGENTCORE_GATEWAY_URL there if the gateway changed."
  else
    {
      echo "AGENTCORE_GATEWAY_URL=$GATEWAY_URL"
      [ -n "${AWS_PROFILE:-}" ] && echo "AWS_PROFILE=$AWS_PROFILE"
    } > "$ENV_FILE"
    say "Wrote $ENV_FILE"
  fi
fi

echo
say "Test it:  cd skills/agentcore-websearch && agentcore-websearch \"latest AWS news\""
