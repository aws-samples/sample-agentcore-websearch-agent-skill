#!/usr/bin/env bash
#
# export-env.sh — add AGENTCORE_GATEWAY_URL (and optionally AWS_PROFILE) to your
# shell profile, so the `agentcore-websearch` CLI works in every new shell without
# a local .env. Pairs with a user-space install (`uv tool install .`).
#
# Usage:
#   ./scripts/export-env.sh                       # auto-detect URL from the CFN stack
#   ./scripts/export-env.sh --profile my-profile  # also export AWS_PROFILE
#   AGENTCORE_GATEWAY_URL=https://... ./scripts/export-env.sh   # skip the AWS lookup
#
# Options:
#   --profile <name>   also write `export AWS_PROFILE=<name>`
#   --region <region>  AWS region for the stack lookup (default: us-east-1)
#   --stack <name>     CloudFormation stack name (default: agentcore-websearch)
#   --profile-file <p> shell profile to edit (default: auto-detected)
#   -h, --help         show this help
#
set -euo pipefail

REGION="${REGION:-us-east-1}"
STACK_NAME="${STACK_NAME:-agentcore-websearch}"
AWS_PROFILE_ARG=""
PROFILE_FILE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --profile)      AWS_PROFILE_ARG="$2"; shift 2 ;;
    --region)       REGION="$2"; shift 2 ;;
    --stack)        STACK_NAME="$2"; shift 2 ;;
    --profile-file) PROFILE_FILE="$2"; shift 2 ;;
    -h|--help)      sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# 1. Resolve the gateway URL: prefer an already-set env var, else read the stack.
GATEWAY_URL="${AGENTCORE_GATEWAY_URL:-}"
if [ -z "$GATEWAY_URL" ]; then
  command -v aws >/dev/null || die "aws CLI not found and AGENTCORE_GATEWAY_URL is unset"
  say "Reading GatewayUrl from CloudFormation stack '$STACK_NAME' ($REGION)..."
  AWS_ARGS=(--region "$REGION")
  [ -n "$AWS_PROFILE_ARG" ] && AWS_ARGS+=(--profile "$AWS_PROFILE_ARG")
  GATEWAY_URL="$(aws "${AWS_ARGS[@]}" cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='GatewayUrl'].OutputValue | [0]" \
    --output text 2>/dev/null || true)"
fi
[ -n "$GATEWAY_URL" ] && [ "$GATEWAY_URL" != "None" ] \
  || die "could not determine gateway URL — deploy the stack first (see README) or set AGENTCORE_GATEWAY_URL"

# 2. Pick the shell profile to edit (override with --profile-file).
if [ -z "$PROFILE_FILE" ]; then
  case "$(basename "${SHELL:-}")" in
    zsh)  PROFILE_FILE="$HOME/.zshrc" ;;
    bash) [ -f "$HOME/.bash_profile" ] && PROFILE_FILE="$HOME/.bash_profile" || PROFILE_FILE="$HOME/.bashrc" ;;
    *)    PROFILE_FILE="$HOME/.profile" ;;
  esac
fi
touch "$PROFILE_FILE"

# 3. Append the exports idempotently inside a managed block.
MARK_BEGIN="# >>> agentcore-websearch >>>"
MARK_END="# <<< agentcore-websearch <<<"
tmp="$(mktemp)"
# strip any previous managed block, then append a fresh one
awk -v b="$MARK_BEGIN" -v e="$MARK_END" '
  $0==b {skip=1} !skip {print} $0==e {skip=0}
' "$PROFILE_FILE" > "$tmp"
{
  echo "$MARK_BEGIN"
  echo "export AGENTCORE_GATEWAY_URL=\"$GATEWAY_URL\""
  [ -n "$AWS_PROFILE_ARG" ] && echo "export AWS_PROFILE=\"$AWS_PROFILE_ARG\""
  echo "$MARK_END"
} >> "$tmp"
mv "$tmp" "$PROFILE_FILE"

say "Updated $PROFILE_FILE"
echo "    export AGENTCORE_GATEWAY_URL=\"$GATEWAY_URL\""
[ -n "$AWS_PROFILE_ARG" ] && echo "    export AWS_PROFILE=\"$AWS_PROFILE_ARG\""
echo
say "Apply now with:  source \"$PROFILE_FILE\"   (or open a new terminal)"
