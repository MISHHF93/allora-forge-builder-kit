#!/usr/bin/env python3
import subprocess
import shutil

def check_cli_version():
    """Check allorad version and available commands"""
    cli = shutil.which("allorad")
    if not cli:
        print("❌ allorad not found in PATH")
        return
    
    print(f"✅ allorad found at: {cli}")
    
    # Check version
    try:
        result = subprocess.run([cli, "version"], capture_output=True, text=True)
        print(f"📋 Version: {result.stdout.strip()}")
    except Exception as e:
        print(f"❌ Version check failed: {e}")
    
    # Check available flags for key commands
    commands = [
        "query emissions is-topic-active --help",
        "query emissions worker-submission-window-status --help", 
        "query emissions unfulfilled-worker-nonces --help"
    ]
    
    for cmd in commands:
        print(f"\n🔍 Checking: {cmd}")
        try:
            result = subprocess.run([cli] + cmd.split(), capture_output=True, text=True)
            if result.returncode == 0:
                # Extract flag information
                lines = result.stdout.split('\n')
                flags = [line for line in lines if '--' in line]
                print("Available flags:")
                for flag in flags[:5]:  # Show first 5 flags
                    print(f"  {flag}")
            else:
                print(f"❌ Command failed: {result.stderr}")
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    check_cli_version()
