# Model Validation and Error Recovery Guide

## Problem Solved

The pipeline was crashing when a LinearRegression or Ridge model was used without being properly fitted first. This happened when:

1. **Model not saved properly** - Model was saved before `.fit(X, y)` was called
2. **Corrupted model file** - Model file was overwritten with an uninitialized model
3. **Feature mismatch** - Saved model had different number of features than expected
4. **Silent failures** - Errors weren't caught until runtime during prediction

## Solution Implemented

### 1. **train.py - Pre-Save Validation**

**Before saving model, test it:**
```python
# Test with dummy input BEFORE saving
dummy_shape = (1, X.shape[1])
dummy_input = np.zeros(dummy_shape)
dummy_pred = model.predict(dummy_input)  # Raises error if not fitted

# Verify n_features_in_ is set
if not hasattr(model, 'n_features_in_'):
    raise RuntimeError("Model not properly fitted before saving")
```

**After saving, verify file integrity:**
```python
# Load saved model and test it
with open("model.pkl", "rb") as f:
    loaded_model = pickle.load(f)
verify_pred = loaded_model.predict(dummy_input)
```

**What happens if validation fails:**
- Raises `RuntimeError` immediately
- Prevents corrupted model.pkl from being used
- Stops training execution with clear error message

### 2. **submit_prediction.py - Post-Load Validation**

**New function: `validate_model_fitted()`**
```python
def validate_model_fitted(model, expected_features: int) -> bool:
    # Check n_features_in_ (only set by sklearn/xgboost after .fit())
    if not hasattr(model, 'n_features_in_'):
        logger.error("❌ Model not fitted: missing n_features_in_")
        return False
    
    # Verify feature count matches
    if model.n_features_in_ != expected_features:
        logger.error(f"❌ Feature mismatch: expected {expected_features}, got {model.n_features_in_}")
        return False
    
    # Test prediction on dummy input
    dummy_input = np.zeros((1, expected_features))
    test_pred = model.predict(dummy_input)  # Raises if model not usable
    
    return True
```

**Validation called immediately after loading:**
```python
if not validate_model_fitted(model, len(feature_cols)):
    logger.error("❌ Model validation failed")
    # Trigger automatic retraining
    subprocess.run([sys.executable, "train.py"])
    # Reload model and retry
    return
```

### 3. **Automatic Error Recovery**

If model validation fails in `submit_prediction.py`:

1. **Log the error** with clear details
2. **Attempt automatic retraining** via `train.py` (300s timeout)
3. **Reload the newly trained model** and validate again
4. **Proceed with prediction** if retraining successful
5. **Abort gracefully** with exit code 1 if recovery fails

```python
if not validate_model_fitted(model, len(feature_cols)):
    logger.error("❌ Model validation failed")
    logger.info("Attempting to trigger retraining...")
    
    proc = subprocess.run([sys.executable, "train.py"], 
                         timeout=300, 
                         capture_output=True, 
                         text=True)
    
    if proc.returncode == 0:
        # Reload and revalidate
        with open(args.model, "rb") as f:
            model = pickle.load(f)
        if validate_model_fitted(model, len(feature_cols)):
            # Continue with prediction
            pass
    else:
        # Recovery failed
        logger.error("❌ Retraining failed, aborting")
        return 1
```

## Model Fitting Guarantees

### What sklearn/XGBoost Sets After `.fit()`

After calling `model.fit(X, y)`:
- ✅ `n_features_in_` attribute is set to `X.shape[1]`
- ✅ Internal weights/coefficients are learned
- ✅ `model.predict()` works correctly
- ✅ `model` can be pickled and unpickled successfully

### What Happens If Not Fitted

Before `.fit()` is called:
- ❌ `n_features_in_` does NOT exist
- ❌ `model.predict()` raises: `NotFittedError`
- ❌ Model is useless for predictions
- ❌ Training code should never reach this state

## Testing the Fixes

### 1. Test Training with Validation
```bash
python3 train.py
```

**Expected output:**
```
Testing model with dummy input before saving...
✓ Test prediction successful: 0.01358050
✓ Model has n_features_in_=10
✅ Model saved via pickle.dump() to model.pkl
✅ Model saved via joblib.dump() to model.pkl
Final verification: loading and testing saved model.pkl...
✓ Loaded model prediction successful: 0.01358050
```

### 2. Test Prediction with Validation
```bash
python3 submit_prediction.py
```

**Expected output:**
```
Loading model from model.pkl...
✓ Model loaded successfully (type: XGBRegressor)
Loading features from features.json...
✓ Features loaded: 10 columns
Validating model is properly fitted...
✓ Model validation successful (test pred: 0.01358050)
Fetching latest BTC/USD data...
✓ Fetched 84 data points
✓ Generated 13 feature rows
✓ Prepared input shape: (1, 10)
Generating prediction...
✓ Prediction: -0.00561345
Submitting prediction to blockchain...
✅ Submission success
Transaction hash: 8876764B84486338A1CD56B4D64BD5847A10BE10AF2652EAB1041CDAEA3E12C0
```

### 3. Test Continuous Mode
```bash
python3 submit_prediction.py --continuous
```

**Expected behavior:**
- Validates model on first load
- Generates prediction
- Submits to blockchain
- Sleeps for 3600s
- Repeats indefinitely
- Logs all steps with ✓/❌ indicators
- **Never crashes** due to unfitted model

## Key Files Modified

### train.py
- **Lines 234-277**: Pre-save and post-save model validation
- **Changes**: Added test prediction before saving, final verification after saving
- **Impact**: Prevents corrupted model files from being saved

### submit_prediction.py
- **Lines 294-321**: New `validate_model_fitted()` function
- **Lines 367-430**: Enhanced `main_once()` with model validation and auto-recovery
- **Changes**: Validates model after loading, triggers retraining if needed
- **Impact**: Prevents crashes and enables automatic recovery

## Error Messages Guide

### When Model Validation Passes
```
✓ Model validation successful (test pred: 0.01358050)
```
→ Safe to proceed with prediction

### When Model Validation Fails (Pre-Save)
```
❌ Test prediction failed: NotFittedError
❌ Model missing n_features_in_ attribute (unfitted)
```
→ Training code raises RuntimeError immediately

### When Model Validation Fails (Post-Load)
```
❌ Model validation failed. Model may not be fitted.
❌ Model not fitted: missing n_features_in_ attribute
```
→ Automatically triggers retraining

### After Successful Recovery
```
✓ Retraining successful, retrying prediction...
✓ Model validation successful (test pred: 0.01358050)
```
→ Prediction proceeds normally

### If Recovery Fails
```
❌ Retrained model still invalid
❌ Retraining failed: [error details]
❌ Could not retrain: [error details]
```
→ Aborts with exit code 1

## Preventing Future Issues

### 1. Always Use `.fit()` Before Saving
```python
model = XGBRegressor()
X_train, y_train = ...
model.fit(X_train, y_train)  # REQUIRED before saving
joblib.dump(model, "model.pkl")
```

### 2. Validate Before Using
```python
model = joblib.load("model.pkl")
validate_model_fitted(model, expected_features)  # Check before predict
predictions = model.predict(X_new)
```

### 3. Minimum Training Data
- **train.py**: Requires ≥ 500 rows by default (`min_training_rows`)
- **Feature engineering**: Requires ≥ 72 rows for rolling window features
- **Target creation**: Requires data - horizon_hours rows to create targets
- **Result**: Typically ≥ 1,900 rows available for training

### 4. CSV Logging Always Works
Even if prediction fails, submission status is logged:
```csv
timestamp,topic_id,prediction,worker,block_height,proof,signature,status
2025-11-23T00:34:41Z,67,-0.005613,allo1...,6642955,"{}",signature,success
```

## Success Indicators

✅ **Training successful if:**
- `model.pkl` exists and is ≥ 1 KB
- `features.json` exists with 10 column names
- Test predictions work on dummy input
- No RuntimeError raised

✅ **Prediction successful if:**
- Model loads without errors
- Model validation passes
- Features load and match expected count
- Prediction generates a float value
- CSV record is logged

✅ **Continuous mode successful if:**
- Runs indefinitely without crashes
- Each iteration logs ✓ for validation
- Sleeps for 3600s between submissions
- CSV file grows with each submission

## Summary

This solution provides:
1. **Prevention**: Validates model before saving (train.py)
2. **Detection**: Validates model after loading (submit_prediction.py)
3. **Recovery**: Automatically retrains if validation fails
4. **Logging**: All steps logged with clear error messages
5. **Resilience**: Continuous mode never crashes due to unfitted models

The pipeline now handles model issues gracefully and automatically recovers from errors.
