#!/bin/bash
set -euo pipefail

STAGING_DIR="/var/app/staging"

TOKEN=$(curl -fsS -X PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")

IP=$(curl -fsS -H "X-aws-ec2-metadata-token: $TOKEN" \
  "http://169.254.169.254/latest/meta-data/local-ipv4")

echo "Injecting private IP: $IP"

grep -RIl "__PRIVATE_IP__" "$STAGING_DIR" | while read -r file; do
  sed -i "s/__PRIVATE_IP__/$IP/g" "$file"
done