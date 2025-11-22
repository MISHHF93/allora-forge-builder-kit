# Use Ubuntu 24.04 as base image
FROM ubuntu:24.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.12 \
    python3.12-venv \
    python3-pip \
    wget \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Allora CLI
RUN wget https://github.com/allora-network/allora-chain/releases/download/v0.3.0/allorad-linux-amd64 -O /usr/local/bin/allorad \
    && chmod +x /usr/local/bin/allorad

# Set up Python virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt /tmp/
RUN pip install --upgrade pip && pip install -r /tmp/requirements.txt

# Create app directory
WORKDIR /app

# Copy application code
COPY . /app/

# Configure Allora CLI
RUN allorad config set client chain-id allora-testnet-1 && \
    allorad config set client node https://allora-rpc.testnet.allora.network/

# Expose any necessary ports (if needed)
# EXPOSE 8000

# Default command
CMD ["./launch_pipeline.sh"]