#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ -z "${LLM_API_KEY:-}" ]; then
  printf "DeepSeek API key: "
  stty -echo
  read -r LLM_API_KEY
  stty echo
  printf "\n"
  export LLM_API_KEY
fi

export LLM_BASE_URL="${LLM_BASE_URL:-https://api.deepseek.com/chat/completions}"
export LLM_MODEL="${LLM_MODEL:-deepseek-chat}"
export LLM_SSL_VERIFY="${LLM_SSL_VERIFY:-0}"

python3 app.py
