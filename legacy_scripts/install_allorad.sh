#!/bin/bash
# Install Allora CLI (allorad) for the current system
# Automatically detects architecture and downloads correct binary

set -e

echo "╔════════════════════════════════════════════════════════════╗"
echo "║     ALLORA CLI (allorad) INSTALLATION SCRIPT              ║"
echo "╚════════════════════════════════════════════════════════════╝"

# Detect system architecture
echo ""
echo "📋 Detecting system architecture..."
ARCH=$(uname -m)
OS=$(uname -s | tr '[:upper:]' '[:lower:]')

echo "   OS: $OS"
echo "   Architecture: $ARCH"

# Map architecture to Allora release names
case "$ARCH" in
  x86_64)
    ARCH_NAME="amd64"
    echo "   ✅ x86_64 architecture detected"
    ;;
  arm64|aarch64)
    ARCH_NAME="arm64"
    echo "   ✅ ARM64 architecture detected"
    ;;
  *)
    echo "   ❌ Unsupported architecture: $ARCH"
    exit 1
    ;;
esac

# Determine OS
if [ "$OS" != "linux" ] && [ "$OS" != "darwin" ]; then
  echo "   ❌ Unsupported OS: $OS (must be linux or darwin)"
  exit 1
fi

echo "   ✅ $OS platform detected"

# Version to install
VERSION="v0.14.0"
RELEASE_NAME="allora-chain_0.14.0_${OS}_${ARCH_NAME}"
DOWNLOAD_URL="https://github.com/allora-network/allora-chain/releases/download/${VERSION}/${RELEASE_NAME}"

echo ""
echo "📥 Downloading allorad binary..."
echo "   Version: $VERSION"
echo "   Binary: $RELEASE_NAME"
echo "   URL: $DOWNLOAD_URL"

# Create bin directory
mkdir -p ~/.local/bin

# Download binary
echo ""
echo "⏳ Downloading... (this may take a minute)"
if ! curl -L "$DOWNLOAD_URL" -o ~/.local/bin/allorad --progress-bar; then
  echo "❌ Download failed"
  echo "   Check the URL or try again"
  exit 1
fi

echo "✅ Downloaded"

# Make executable
echo ""
echo "🔧 Making binary executable..."
chmod +x ~/.local/bin/allorad

# Verify installation
echo ""
echo "✅ Testing installation..."
if ~/.local/bin/allorad version 2>&1 | head -5; then
  echo "✅ Installation successful!"
else
  echo "⚠️  allorad installed but version check failed"
fi

# Check if ~/.local/bin is in PATH
echo ""
echo "📋 Checking PATH..."
if echo "$PATH" | grep -q "$HOME/.local/bin"; then
  echo "✅ ~/.local/bin is in PATH"
else
  echo "⚠️  ~/.local/bin is NOT in PATH"
  echo "   Add this to your ~/.bashrc or ~/.zshrc:"
  echo "   export PATH=\"$HOME/.local/bin:\$PATH\""
  echo ""
  echo "   Then run: source ~/.bashrc"
fi

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║  ✅ INSTALLATION COMPLETE                                 ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "Next steps:"
echo "1. Verify installation: allorad version"
echo "2. Run diagnostic: python3 diagnose_env_wallet.py"
echo "3. Start daemon: nohup python3 submit_prediction.py --daemon > logs/submission.log 2>&1 &"
echo ""
