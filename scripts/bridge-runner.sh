#!/bin/bash
SESSION=$1
cd ~
unset OA_NAME
export ANTHROPIC_BASE_URL="http://127.0.0.1:19593"
export ANTHROPIC_AUTH_TOKEN="local"
unset ANTHROPIC_API_KEY
exec claude --model claude-opus-5
