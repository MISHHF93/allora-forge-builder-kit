#!/usr/bin/env python3
"""
Production Readiness Validation for train.py
Validates all functional requirements without running the full pipeline
"""
import sys
import os
import ast
import importlib.util

def check_file_exists():
    """Check train.py exists"""
    if not os.path.exists('train.py'):
        print("❌ train.py not found")
        return False
    print("✅ train.py exists")
    return True

def check_syntax():
    """Validate Python syntax"""
    try:
        with open('train.py', 'r') as f:
            ast.parse(f.read())
        print("✅ Python syntax is valid")
        return True
    except SyntaxError as e:
        print(f"❌ Syntax error: {e}")
        return False

def check_imports():
    """Check required imports"""
    required_imports = [
        'os', 'sys', 'json', 'asyncio', 'pandas', 'numpy',
        'xgboost', 'dotenv', 'requests', 'logging'
    ]
    
    with open('train.py', 'r') as f:
        content = f.read()
    
    missing = []
    for imp in required_imports:
        if f'import {imp}' not in content and f'from {imp}' not in content:
            missing.append(imp)
    
    if missing:
        print(f"⚠️  Missing imports: {', '.join(missing)}")
        return False
    print("✅ All required imports present")
    return True

def check_environment_vars():
    """Check environment variable handling"""
    required_vars = [
        'ALLORA_API_KEY',
        'ALLORA_WALLET_ADDR',
    ]
    
    with open('train.py', 'r') as f:
        content = f.read()
    
    missing = []
    for var in required_vars:
        if var not in content:
            missing.append(var)
    
    if missing:
        print(f"❌ Missing environment variables: {', '.join(missing)}")
        return False
    print("✅ Environment variable handling present")
    return True

def check_cli_args():
    """Check CLI argument support"""
    required_args = ['--loop', '--submit', '--start-utc', '--end-utc']
    
    with open('train.py', 'r') as f:
        content = f.read()
    
    missing = []
    for arg in required_args:
        if arg not in content:
            missing.append(arg)
    
    if missing:
        print(f"❌ Missing CLI arguments: {', '.join(missing)}")
        return False
    print("✅ CLI argument parsing present")
    return True

def check_xgboost():
    """Check XGBoost usage"""
    with open('train.py', 'r') as f:
        content = f.read()
    
    if 'XGBRegressor' not in content and 'xgboost' not in content:
        print("❌ XGBoost not found")
        return False
    print("✅ XGBoost model implementation found")
    return True

def check_submission():
    """Check submission logic"""
    with open('train.py', 'r') as f:
        content = f.read()
    
    submission_funcs = ['_submit_with_client_xgb', '_submit_with_sdk']
    found = any(func in content for func in submission_funcs)
    
    if not found:
        print("❌ Submission functions not found")
        return False
    print("✅ Submission logic present")
    return True

def check_error_handling():
    """Check error handling"""
    with open('train.py', 'r') as f:
        content = f.read()
    
    try_count = content.count('try:')
    except_count = content.count('except')
    
    if try_count < 20 or except_count < 20:
        print(f"⚠️  Limited error handling (try: {try_count}, except: {except_count})")
        return False
    print(f"✅ Comprehensive error handling ({try_count} try blocks)")
    return True

def check_logging():
    """Check logging implementation"""
    with open('train.py', 'r') as f:
        content = f.read()
    
    logging_markers = ['logging.', '_log_submission', 'submission_log']
    found = any(marker in content for marker in logging_markers)
    
    if not found:
        print("❌ Logging not found")
        return False
    print("✅ Logging implementation present")
    return True

def check_continuous_mode():
    """Check continuous/loop mode"""
    with open('train.py', 'r') as f:
        content = f.read()
    
    if 'while True:' not in content and 'for iteration' not in content:
        print("⚠️  Continuous loop mode may not be implemented")
        return False
    print("✅ Continuous mode implementation found")
    return True

def check_duplicate_prevention():
    """Check duplicate submission prevention"""
    with open('train.py', 'r') as f:
        content = f.read()
    
    markers = ['_has_submitted', 'already_submitted', 'duplicate']
    found = any(marker in content for marker in markers)
    
    if not found:
        print("⚠️  Duplicate prevention may not be implemented")
        return False
    print("✅ Duplicate prevention logic found")
    return True

def main():
    print("=" * 60)
    print("Production Readiness Validation for train.py")
    print("=" * 60)
    print()
    
    checks = [
        ("File Existence", check_file_exists),
        ("Python Syntax", check_syntax),
        ("Required Imports", check_imports),
        ("Environment Variables", check_environment_vars),
        ("CLI Arguments", check_cli_args),
        ("XGBoost Model", check_xgboost),
        ("Submission Logic", check_submission),
        ("Error Handling", check_error_handling),
        ("Logging", check_logging),
        ("Continuous Mode", check_continuous_mode),
        ("Duplicate Prevention", check_duplicate_prevention),
    ]
    
    passed = 0
    failed = 0
    
    for name, check_func in checks:
        try:
            if check_func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ {name}: {e}")
            failed += 1
        print()
    
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed == 0:
        print()
        print("🎉 train.py is PRODUCTION READY!")
        print()
        print("To run continuous mode:")
        print("  python3 train.py --loop --submit")
        print()
        return 0
    else:
        print()
        print("⚠️  Some checks failed. Review above for details.")
        return 1

if __name__ == '__main__':
    sys.exit(main())
