#!/bin/bash

echo "🧠 Checking sklearn warning in prediction phase..."

SCRIPT="submit_prediction.py"
MODEL_PATH="model.pkl"
FEATURES_PATH="features.json"

# 1. Check if model file exists
if [ ! -f "$MODEL_PATH" ]; then
  echo "❌ Model file ($MODEL_PATH) not found."
  exit 1
fi

# 2. Check if features.json exists
if [ ! -f "$FEATURES_PATH" ]; then
  echo "❌ Features file ($FEATURES_PATH) not found."
  exit 1
fi

# 3. Extract features from JSON
FEATURE_COUNT=$(jq length $FEATURES_PATH)
echo "✅ Found $FEATURE_COUNT features in $FEATURES_PATH"

# 4. Print first few lines of submit_prediction.py to check input handling
echo "🔍 Checking if input is using proper column names..."
grep -E 'predict|DataFrame|model.predict' $SCRIPT | head -n 10

echo "✅ Diagnosis complete. If predictions are using raw arrays, this is causing the warning."

echo "📌 Suggested fix: ensure you're passing a DataFrame with column names that match training."
