# Headless deployment (Linux VM)

This repo includes scripts to submit predictions continuously without keeping your PC on. Use a small Linux VM (AWS, Azure, GCP, etc.).

## Prerequisites
- Python 3.10+
- git
- allora-sdk (installed via requirements.txt)
- A worker wallet key file `~/.allora_key` with restrictive permissions (chmod 600)
- `.env` in the repo root with:
  - `ALLORA_API_KEY=...`
  - `TIINGO_API_KEY=...`

## Setup
```
# SSH to the VM
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip git

# Clone repo
cd ~
git clone https://github.com/allora-network/allora-forge-builder-kit.git
cd allora-forge-builder-kit

# Copy your ~/.allora_key here via scp or create anew, then:
chmod 600 ~/.allora_key

# Create .env (paste your keys)
cat > .env <<'EOF'
ALLORA_API_KEY=YOUR_API_KEY
TIINGO_API_KEY=YOUR_TIINGO_KEY
EOF

# Install deps
python3 -m pip install -U pip
python3 -m pip install -r requirements.txt

# Optional: run one training to build the artifact and model bundle
python3 -u train.py
```

## Run on cadence with cron (recommended)
Submit every 30 minutes using saved model + live features; retrain nightly.
```
crontab -e
```
Add lines (adjust paths and python path if needed):
```
# Submit every 30 minutes
*/30 * * * * cd /home/ubuntu/allora-forge-builder-kit && ALLORA_CHAIN_ID=allora-testnet-1 ALLORA_RPC_URL=https://allora-rpc.testnet.allora.network /usr/bin/python3 -u submit_prediction.py --mode sdk --topic-id 67 --timeout 240 --source model >> /home/ubuntu/allora-forge-builder-kit/data/cron_submit.log 2>&1

# Retrain daily at 02:05
5 2 * * * cd /home/ubuntu/allora-forge-builder-kit && /usr/bin/python3 -u train.py >> /home/ubuntu/allora-forge-builder-kit/data/cron_train.log 2>&1
```

Alternatively, use the included wrappers:
```
*/30 * * * * /home/ubuntu/allora-forge-builder-kit/scripts/cron_submit.sh
5 2 * * * /home/ubuntu/allora-forge-builder-kit/scripts/cron_train.sh
```

Logs:
- `data/cron_submit.log`
- `data/cron_train.log`

## Optional: systemd service
Create `/etc/systemd/system/allora-submit.service`:
```
[Unit]
Description=Allora SDK submit loop (cron-like)
After=network.target

[Service]
Type=oneshot
Environment=ALLORA_CHAIN_ID=allora-testnet-1
Environment=ALLORA_RPC_URL=https://allora-rpc.testnet.allora.network
WorkingDirectory=/home/ubuntu/allora-forge-builder-kit
ExecStart=/usr/bin/python3 -u submit_prediction.py --mode sdk --topic-id 67 --timeout 240 --source model

[Install]
WantedBy=multi-user.target
```
Then schedule with a timer `/etc/systemd/system/allora-submit.timer`:
```
[Unit]
Description=Run Allora submit every 30 minutes

[Timer]
OnCalendar=*:0/30
Persistent=true

[Install]
WantedBy=timers.target
```
Enable and start:
```
sudo systemctl daemon-reload
sudo systemctl enable --now allora-submit.timer
```

## Health checks
Use the CLI from any machine (replace address):
```
allorad --node https://allora-rpc.testnet.allora.network query emissions worker-info <wallet>
allorad --node https://allora-rpc.testnet.allora.network query emissions unfulfilled-worker-nonces 67
allorad --node https://allora-rpc.testnet.allora.network query emissions worker-latest-inference 67 <wallet>
```

That’s it—your submissions continue while your local computer is off.
