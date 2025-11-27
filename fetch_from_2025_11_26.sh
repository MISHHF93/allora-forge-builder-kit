#!/bin/bash

end_date="2025-11-26"
chunk_days=3
output_dir="tiingo_debug"
merged_file="${output_dir}/merged_btc_data.json"

mkdir -p "$output_dir"
> "$merged_file"

format_date() {
  date -u -d "$1" +"%Y-%m-%d"
}

for i in {0..30}; do
  chunk_end=$(format_date "$end_date - $((i * chunk_days)) days")
  chunk_start=$(format_date "$chunk_end - $((chunk_days - 1)) days")

  echo "[📡] Fetching $chunk_start to $chunk_end"

  curl -s -G "https://api.tiingo.com/tiingo/crypto/prices" \
    --data-urlencode "tickers=btcusd" \
    --data-urlencode "startDate=$chunk_start" \
    --data-urlencode "endDate=$chunk_end" \
    --data-urlencode "resampleFreq=1hour" \
    --data-urlencode "token=$TIINGO_API_KEY" \
    -o "${output_dir}/temp_chunk.json"

  # Check for valid JSON array (data) or object (error)
  if jq -e 'type == "object" and has("detail")' "${output_dir}/temp_chunk.json" >/dev/null; then
    echo "⚠️  Skipping chunk: $(jq -r '.detail' ${output_dir}/temp_chunk.json)"
    continue
  elif ! jq -e 'type == "array"' "${output_dir}/temp_chunk.json" >/dev/null; then
    echo "❌ Invalid or unexpected response format – skipping"
    continue
  fi

  # Merge valid data into final file
  if [ -s "$merged_file" ]; then
    jq -s '.[0] + .[1]' "$merged_file" "${output_dir}/temp_chunk.json" > "${output_dir}/temp_merged.json"
    mv "${output_dir}/temp_merged.json" "$merged_file"
  else
    cp "${output_dir}/temp_chunk.json" "$merged_file"
  fi

  echo "[✅] Appended $chunk_start → $chunk_end"
done

echo "[🎯] Final merged file: $merged_file"

