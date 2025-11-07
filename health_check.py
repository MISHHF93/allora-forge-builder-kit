#!/usr/bin/env python3
"""Comprehensive health check for train.py pipeline"""
import os
import sys
from pathlib import Path

# Load environment
from dotenv import load_dotenv
load_dotenv()

def check_environment_variables():
    """Validate required environment variables"""
    print("=" * 60)
    print("1. ENVIRONMENT VARIABLES")
    print("=" * 60)
    
    required = {
        'ALLORA_API_KEY': 'Market data API key',
        'ALLORA_WALLET_ADDR': 'Wallet address',
        'ALLORA_WALLET_SEED_PHRASE': 'Wallet seed phrase'
    }
    
    optional = {
        'ALLORA_RPC_URL': 'RPC endpoint',
        'ALLORA_GRPC_URL': 'gRPC endpoint',
        'ALLORA_REST_URL': 'REST endpoint'
    }
    
    all_ok = True
    
    for var, desc in required.items():
        value = os.getenv(var)
        if value:
            if 'KEY' in var or 'SEED' in var:
                display = f"{value[:10]}...***"
            else:
                display = value
            print(f"✅ {var}: {display}")
        else:
            print(f"❌ {var}: MISSING - {desc}")
            all_ok = False
    
    print("\nOptional variables:")
    for var, desc in optional.items():
        value = os.getenv(var)
        if value:
            print(f"✅ {var}: {value}")
        else:
            print(f"ℹ️  {var}: Using default")
    
    return all_ok

def check_wallet_balance():
    """Check wallet balance"""
    print("\n" + "=" * 60)
    print("2. WALLET BALANCE")
    print("=" * 60)
    
    wallet_addr = os.getenv('ALLORA_WALLET_ADDR')
    if not wallet_addr:
        print("❌ No wallet address configured")
        return False
    
    import subprocess
    
    cmd = [
        'allorad', 'q', 'bank', 'balances', wallet_addr,
        '--node', 'https://rpc.lavender-five.allora-testnet.com:443',
        '--output', 'json'
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            balances = data.get('balances', [])
            if balances:
                for bal in balances:
                    amount = int(bal.get('amount', 0))
                    denom = bal.get('denom', 'unknown')
                    if denom == 'uallo':
                        allo = amount / 1_000_000
                        print(f"✅ Balance: {allo:.6f} ALLO ({amount} uallo)")
                        if amount > 1000:
                            return True
                        else:
                            print("⚠️  Balance is low (< 0.001 ALLO)")
                            return False
            else:
                print("⚠️  No balances found")
                return False
        else:
            print(f"⚠️  Could not query balance: {result.stderr[:100]}")
            return False
    except FileNotFoundError:
        print("⚠️  allorad not found (this is optional for Python-only operation)")
        return True  # Not critical
    except Exception as e:
        print(f"⚠️  Balance check error: {e}")
        return True  # Not critical

def check_topic_status():
    """Check topic 67 status"""
    print("\n" + "=" * 60)
    print("3. TOPIC STATUS")
    print("=" * 60)
    
    import subprocess
    
    cmd = [
        'allorad', 'q', 'emissions', 'topic', '67',
        '--node', 'https://rpc.lavender-five.allora-testnet.com:443',
        '--output', 'json'
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            topic = data.get('topic', {})
            
            print(f"✅ Topic ID: {topic.get('id', 'unknown')}")
            print(f"✅ Metadata: {topic.get('metadata', 'N/A')}")
            print(f"✅ Active: {topic.get('active', False)}")
            print(f"✅ Epoch Length: {topic.get('epoch_length', 'N/A')}")
            
            return topic.get('active', False)
        else:
            print(f"⚠️  Could not query topic: {result.stderr[:100]}")
            return False
    except FileNotFoundError:
        print("ℹ️  allorad not found (topic check skipped)")
        return True  # Not critical
    except Exception as e:
        print(f"⚠️  Topic check error: {e}")
        return True  # Not critical

def check_running_processes():
    """Check for running train.py processes"""
    print("\n" + "=" * 60)
    print("4. RUNNING PROCESSES")
    print("=" * 60)
    
    import subprocess
    
    try:
        result = subprocess.run(
            ['ps', 'aux'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        lines = [line for line in result.stdout.split('\n') 
                if 'train.py' in line and 'grep' not in line]
        
        if lines:
            print(f"⚠️  Found {len(lines)} running train.py process(es):")
            for line in lines:
                parts = line.split()
                if len(parts) >= 2:
                    print(f"   PID {parts[1]}: {' '.join(parts[10:])}")
            return False
        else:
            print("✅ No conflicting train.py processes running")
            return True
    except Exception as e:
        print(f"⚠️  Process check error: {e}")
        return True

def check_file_integrity():
    """Check critical files exist"""
    print("\n" + "=" * 60)
    print("5. FILE INTEGRITY")
    print("=" * 60)
    
    files = {
        'train.py': 'Main pipeline script',
        'simple_submit.py': 'Submission helper',
        'config/pipeline.yaml': 'Configuration',
        '.env': 'Environment variables'
    }
    
    all_ok = True
    for file_path, desc in files.items():
        if Path(file_path).exists():
            size = Path(file_path).stat().st_size
            print(f"✅ {file_path}: {size:,} bytes - {desc}")
        else:
            print(f"❌ {file_path}: MISSING - {desc}")
            all_ok = False
    
    # Check no shell scripts
    sh_files = list(Path('.').glob('*.sh'))
    if sh_files:
        print(f"\n⚠️  Found {len(sh_files)} shell scripts (should be zero):")
        for sh in sh_files:
            print(f"   - {sh}")
        all_ok = False
    else:
        print("\n✅ No shell scripts found (pure Python)")
    
    return all_ok

def check_imports():
    """Test critical imports"""
    print("\n" + "=" * 60)
    print("6. PYTHON DEPENDENCIES")
    print("=" * 60)
    
    imports = {
        'pandas': 'Data processing',
        'numpy': 'Numerical computing',
        'xgboost': 'ML model',
        'requests': 'HTTP client',
        'dotenv': 'Environment loading',
        'allora_sdk': 'Allora SDK'
    }
    
    all_ok = True
    for module, desc in imports.items():
        try:
            __import__(module)
            print(f"✅ {module}: Available - {desc}")
        except ImportError as e:
            print(f"❌ {module}: MISSING - {desc} ({e})")
            all_ok = False
    
    return all_ok

def check_submission_log():
    """Check submission log status"""
    print("\n" + "=" * 60)
    print("7. SUBMISSION LOG")
    print("=" * 60)
    
    log_path = Path('data/artifacts/logs/submission_log.csv')
    
    if not log_path.exists():
        print("ℹ️  No submission log yet (will be created on first submission)")
        return True
    
    try:
        with open(log_path, 'r') as f:
            lines = f.readlines()
        
        total = len(lines) - 1  # Exclude header
        if total > 0:
            print(f"✅ Submission log exists: {total} entries")
            
            # Count successes
            successes = sum(1 for line in lines if ',true,' in line)
            failures = total - successes
            
            print(f"   Successful: {successes}")
            print(f"   Failed: {failures}")
            if successes > 0:
                rate = (successes / total) * 100
                print(f"   Success rate: {rate:.1f}%")
            
            # Show last entry
            if total > 0:
                last = lines[-1].strip()
                parts = last.split(',')
                if len(parts) >= 3:
                    print(f"\n   Last submission:")
                    print(f"   Time: {parts[0]}")
                    print(f"   Success: {parts[6] if len(parts) > 6 else 'unknown'}")
        else:
            print("ℹ️  Submission log is empty")
        
        return True
    except Exception as e:
        print(f"⚠️  Could not read submission log: {e}")
        return True

def main():
    print("╔════════════════════════════════════════════════════════════╗")
    print("║       TRAIN.PY PIPELINE HEALTH CHECK                      ║")
    print("╚════════════════════════════════════════════════════════════╝")
    print()
    
    checks = [
        check_environment_variables,
        check_wallet_balance,
        check_topic_status,
        check_running_processes,
        check_file_integrity,
        check_imports,
        check_submission_log
    ]
    
    results = []
    for check in checks:
        try:
            result = check()
            results.append(result)
        except Exception as e:
            print(f"❌ Check failed with error: {e}")
            results.append(False)
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for r in results if r)
    total = len(results)
    
    print(f"Passed: {passed}/{total}")
    
    if all(results):
        print("\n🎉 ALL CHECKS PASSED - PIPELINE IS HEALTHY!")
        print("\nReady to run:")
        print("  python3 train.py --loop --submit")
        return 0
    else:
        print("\n⚠️  Some checks failed. Review above for details.")
        print("\nYou may still be able to run, but review warnings.")
        return 1

if __name__ == '__main__':
    sys.exit(main())
