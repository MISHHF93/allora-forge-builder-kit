#!/bin/bash

# submission_tracker.sh — Track last submission status and leaderboard rank

JSON_FILE="latest_submission.json"
LEADERBOARD_URL="https://forge.allora.network/competitions/21"
TMP_HTML="/tmp/leaderboard.html"

echo "[TRACKER] 📝 Last submission info:"
jq '.timestamp, .status, .tx_hash' $JSON_FILE

echo
echo "[TRACKER] 🔍 Validating on-chain confirmation..."
./validate_onchain_submission.sh
TX_STATUS=$?

case $TX_STATUS in
  0) echo "✅ On-chain: Confirmed";;
  1) echo "⏳ On-chain: Pending";;
  2) echo "❌ On-chain: Failed";;
  *) echo "⚠️  On-chain: Unknown";;
esac

echo
echo "[TRACKER] 🌐 Fetching leaderboard snapshot..."
curl -s "$LEADERBOARD_URL" > "$TMP_HTML"

echo "[TRACKER] 📊 Searching for participant:"
grep -A2 "Mish or Ariel" "$TMP_HTML" | sed 's/<[^>]*>//g' || echo "❌ Participant not found in leaderboard snapshot"

