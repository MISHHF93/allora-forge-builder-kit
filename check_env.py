import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv('.env')

print("=" * 60)
print("ENVIRONMENT VARIABLES CHECK")
print("=" * 60)

required_vars = [
    'ALLORA_API_KEY',
    'ALLORA_WALLET_ADDR',
]

optional_vars = [
    'ALLORA_WALLET_SEED_PHRASE',
    'TOPIC_ID',
    'ALLORA_RPC_URL',
    'ALLORA_REST_URL',
]

print("\n✅ REQUIRED VARIABLES:")
all_required = True
for var in required_vars:
    value = os.getenv(var)
    if value:
        display = value[:20] + "..." if len(value) > 20 else value
        print(f"  {var}: {display}")
    else:
        print(f"  ❌ {var}: MISSING")
        all_required = False

print("\n📋 OPTIONAL VARIABLES:")
for var in optional_vars:
    value = os.getenv(var)
    if value:
        display = value[:40] + "..." if len(value) > 40 else value
        print(f"  {var}: {display}")
    else:
        print(f"  {var}: Not set")

print("\n" + "=" * 60)
print("PYTHON DEPENDENCIES CHECK")
print("=" * 60)

dependencies = [
    ('pandas', 'pandas'),
    ('numpy', 'numpy'),
    ('xgboost', 'xgboost'),
    ('requests', 'requests'),
    ('python-dotenv', 'dotenv'),
    ('allora-sdk', 'allora_sdk'),
    ('pyyaml', 'yaml'),
    ('scikit-learn', 'sklearn'),
]

missing = []
for name, module in dependencies:
    try:
        __import__(module)
        print(f"  ✅ {name}")
    except ImportError as e:
        print(f"  ❌ {name}: Not installed")
        missing.append(name)

if missing:
    print(f"\n⚠️  Missing dependencies: {', '.join(missing)}")
    print(f"\nTo install: pip install {' '.join(missing)}")
else:
    print(f"\n✅ All dependencies available")

print("=" * 60)
print("FILE CHECKS")
print("=" * 60)

files_to_check = [
    ('train.py', 'Main pipeline script'),
    ('allora-keypair.pem', 'Wallet keypair'),
    ('.env', 'Environment config'),
    ('config/pipeline.yaml', 'Pipeline config'),
]

for filepath, description in files_to_check:
    if os.path.exists(filepath):
        size = os.path.getsize(filepath)
        print(f"  ✅ {filepath} ({size:,} bytes) - {description}")
    else:
        print(f"  ❌ {filepath} - MISSING - {description}")

print("=" * 60)

if all_required and not missing:
    print("✅ READY TO RUN PIPELINE")
else:
    print("⚠️  FIX ISSUES BEFORE RUNNING")
    
print("=" * 60)
