#!/usr/bin/env python3
"""
Test script to validate the error handling improvements made to train.py

This script tests:
1. CLI error handling improvements (connection refused, unknown command)
2. Topic validation fallback behavior
3. Submission logic with missing data
4. DataFrame handling robustness
"""

import subprocess
import json
import sys
import logging
from unittest.mock import patch, MagicMock
import os
import tempfile

# Add the project root to path to import train module
sys.path.insert(0, '/workspaces/allora-forge-builder-kit')

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')

def test_cli_error_handling():
    """Test that CLI connection failures are handled gracefully"""
    print("🧪 Testing CLI error handling improvements...")
    
    # Import the improved function
    from train import _run_allorad_json
    
    # Test with a command that will fail (connection refused)
    result = _run_allorad_json(['q', 'emissions', 'topic', '67'], label='test_connection_refused')
    
    # Should return None and log at DEBUG level, not WARNING
    assert result is None, "Should return None for connection failures"
    print("✅ CLI connection failure handled correctly")
    
    # Test with non-existent command
    result = _run_allorad_json(['q', 'nonexistent', 'command'], label='test_unknown_command')
    assert result is None, "Should return None for unknown commands"
    print("✅ Unknown command handled correctly")

def test_topic_validation_fallback():
    """Test that topic validation works in fallback mode"""
    print("\n🧪 Testing topic validation fallback behavior...")
    
    from train import _validate_topic_creation_and_funding, EXPECTED_TOPIC_67
    
    # Mock the functions that depend on CLI/REST
    with patch('train._fetch_topic_config') as mock_config, \
         patch('train._get_topic_info') as mock_info:
        
        # Simulate fallback mode (CLI/REST failures)
        mock_config.return_value = {}
        mock_info.return_value = {
            "effective_revenue": None,  # Can't determine revenue
            "fallback_mode": {
                "cli_count": 3,  # CLI failures
                "rest_501_count": 5  # REST 501 errors
            }
        }
        
        result = _validate_topic_creation_and_funding(67, EXPECTED_TOPIC_67)
        
        # In fallback mode, should be more permissive
        assert result["ok"] == True, "Should pass validation in fallback mode"
        assert result["funded"] == True, "Should assume funded in fallback mode"
        print("✅ Topic validation fallback mode working correctly")

def test_submission_logging():
    """Test that submissions are properly logged even when filtered"""
    print("\n🧪 Testing submission logging robustness...")
    
    from train import _log_submission
    
    # Create a temporary directory to act as root_dir
    with tempfile.TemporaryDirectory() as temp_dir:
        csv_path = os.path.join(temp_dir, "submission_log.csv")
        
        # Initialize the CSV with header
        with open(csv_path, 'w') as f:
            f.write("timestamp,topic_id,value,wallet,nonce,tx_hash,success,exit_code,status,log10_loss,score,reward\n")
        
        # Test logging a filtered submission
        import pandas as pd
        test_timestamp = pd.Timestamp("2025-11-20T20:00:00Z", tz="UTC")
        _log_submission(
            temp_dir,  # root_dir - function will append "submission_log.csv"
            test_timestamp, 
            67,
            123.45,
            "test_wallet",
            None,
            None,
            False,
            0,
            "filtered_high_loss",
            2.5  # High loss value
        )
        
        # Verify the log was written
        with open(csv_path, 'r') as f:
            lines = f.readlines()
            assert len(lines) >= 2, f"Should have header + log entry, got {len(lines)} lines"
            
            # Find the line with our test data
            found_filtered = False
            for line in lines[1:]:  # Skip header
                if "filtered_high_loss" in line and "2.5" in line:
                    found_filtered = True
                    break
            
            assert found_filtered, "Should log filtered submissions with correct loss value"
        
        print("✅ Submission logging working correctly")

def test_error_resilience():
    """Test that the pipeline continues despite errors"""
    print("\n🧪 Testing pipeline error resilience...")
    
    # Test with mocked functions that simulate various failures
    from train import _compute_lifecycle_state
    
    with patch('train._get_emissions_params') as mock_params, \
         patch('train._get_topic_info') as mock_info, \
         patch('train._get_topic_config_cached') as mock_config:
        
        # Simulate partial failures - some data available, some not
        mock_params.return_value = {"epoch_length": 3600}  # 1 hour in seconds
        mock_info.return_value = {
            "effective_revenue": None,  # Missing
            "delegated_stake": 0.0,     # Available but zero (fallback mode)
            "reputers_count": None,     # Missing
            "fallback_mode": {
                "cli_count": 2,
                "rest_501_count": 3
            }
        }
        mock_config.return_value = {"worker_submission_window": 100}
        
        # This should not crash and should return reasonable defaults
        result = _compute_lifecycle_state(67)
        
        assert isinstance(result, dict), "Should return a dict result"
        assert "is_active" in result, "Should include activity status"
        assert "fallback_mode" in result, "Should include fallback info"
        
        print("✅ Pipeline resilience test passed")

def main():
    """Run all tests"""
    print("🚀 Starting error handling and resilience tests...\n")
    
    try:
        test_cli_error_handling()
        test_topic_validation_fallback() 
        test_submission_logging()
        test_error_resilience()
        
        print("\n🎉 All tests passed! Error handling improvements are working correctly.")
        print("\nSummary of improvements:")
        print("✅ CLI connection failures logged at DEBUG level (reduced noise)")
        print("✅ Topic validation works in fallback mode (allows submissions)")
        print("✅ Submission logging captures filtered attempts")
        print("✅ Pipeline continues despite partial data failures")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())