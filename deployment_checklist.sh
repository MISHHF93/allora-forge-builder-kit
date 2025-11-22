#!/bin/bash
# Allora Competition Deployment Checklist
# Run this before going live with cron jobs

set -e

cd /workspaces/allora-forge-builder-kit

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  ALLORA COMPETITION - DEPLOYMENT CHECKLIST                    ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

FAILED=0

# 1. Environment checks
echo "📋 Checking environment..."
if [ ! -f ".env" ]; then
    echo "  ❌ Missing .env file"
    FAILED=$((FAILED+1))
else
    echo "  ✅ .env file present"
fi

if [ ! -f ".allora_key" ]; then
    echo "  ❌ Missing .allora_key (wallet mnemonic)"
    FAILED=$((FAILED+1))
else
    echo "  ✅ .allora_key file present"
fi

if [ ! -f "config/pipeline.yaml" ]; then
    echo "  ❌ Missing config/pipeline.yaml"
    FAILED=$((FAILED+1))
else
    echo "  ✅ config/pipeline.yaml present"
fi

# 2. Virtual environment
echo ""
echo "🐍 Checking Python environment..."
if [ ! -d ".venv" ]; then
    echo "  ❌ Virtual environment not found"
    FAILED=$((FAILED+1))
else
    echo "  ✅ Virtual environment exists"
fi

if [ ! -f ".venv/bin/python" ]; then
    echo "  ❌ Python executable not found in venv"
    FAILED=$((FAILED+1))
else
    echo "  ✅ Python executable found"
    python_version=$(.venv/bin/python --version 2>&1)
    echo "     Version: $python_version"
fi

# 3. Required scripts
echo ""
echo "🔧 Checking required scripts..."
for script in competition_submission.py logs/rotate_logs.sh logs/healthcheck.sh setup_cron.sh train.py; do
    if [ ! -f "$script" ]; then
        echo "  ❌ Missing $script"
        FAILED=$((FAILED+1))
    elif [ ! -x "$script" ] && [[ "$script" == *.sh || "$script" == *_submission.py ]]; then
        echo "  ⚠️  $script not executable"
    else
        echo "  ✅ $script exists"
    fi
done

# 4. Documentation
echo ""
echo "📖 Checking documentation..."
for doc in AUTOMATION_GUIDE.md AUTOMATION_COMPLETE.md; do
    if [ ! -f "$doc" ]; then
        echo "  ❌ Missing $doc"
        FAILED=$((FAILED+1))
    else
        lines=$(wc -l < "$doc")
        echo "  ✅ $doc ($lines lines)"
    fi
done

# 5. Syntax validation
echo ""
echo "✓ Validating Python syntax..."
if .venv/bin/python -m py_compile train.py 2>/dev/null; then
    echo "  ✅ train.py syntax OK"
else
    echo "  ❌ train.py syntax error"
    FAILED=$((FAILED+1))
fi

if .venv/bin/python -m py_compile competition_submission.py 2>/dev/null; then
    echo "  ✅ competition_submission.py syntax OK"
else
    echo "  ❌ competition_submission.py syntax error"
    FAILED=$((FAILED+1))
fi

# 6. Required functions
echo ""
echo "🔍 Checking critical functions..."
if .venv/bin/python -c "from train import validate_predictions; print('OK')" 2>/dev/null | grep -q "OK"; then
    echo "  ✅ validate_predictions() function found"
else
    echo "  ❌ validate_predictions() function not found"
    FAILED=$((FAILED+1))
fi

# 7. Disk space
echo ""
echo "💾 Checking disk space..."
available=$(df -BG /workspaces/ | tail -1 | awk '{print $4}' | sed 's/G//')
if [ "$available" -lt 5 ]; then
    echo "  ⚠️  Low disk space: ${available}GB available"
else
    echo "  ✅ Disk space OK: ${available}GB available"
fi

# 8. Cron readiness
echo ""
echo "⏰ Checking cron readiness..."
if command -v crontab &> /dev/null; then
    echo "  ✅ Crontab available"
else
    echo "  ❌ Crontab not found"
    FAILED=$((FAILED+1))
fi

# 9. Permissions
echo ""
echo "🔐 Checking file permissions..."
if [ -r ".env" ]; then
    echo "  ✅ .env readable"
else
    echo "  ❌ .env not readable"
    FAILED=$((FAILED+1))
fi

if [ -r ".allora_key" ]; then
    echo "  ✅ .allora_key readable"
else
    echo "  ❌ .allora_key not readable"
    FAILED=$((FAILED+1))
fi

# Summary
echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
if [ $FAILED -eq 0 ]; then
    echo "║  ✅ ALL CHECKS PASSED - READY FOR DEPLOYMENT                   ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Next steps:"
    echo "  1. Run:  python3 competition_submission.py --validate-only"
    echo "  2. Run:  ./setup_cron.sh"
    echo "  3. Run:  crontab -e"
    echo "  4. Add the cron entries shown by setup_cron.sh"
    echo "  5. Verify: crontab -l"
    echo ""
    exit 0
else
    echo "║  ❌ $FAILED CHECK(S) FAILED - PLEASE FIX BEFORE DEPLOYING      ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""
    exit 1
fi
