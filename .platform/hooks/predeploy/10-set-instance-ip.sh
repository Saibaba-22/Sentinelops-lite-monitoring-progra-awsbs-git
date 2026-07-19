#!/bin/bash
set -euo pipefail

TOKEN=$(curl -sS -X PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")

IP=$(curl -sS -H "X-aws-ec2-metadata-token: $TOKEN" \
  "http://169.254.169.254/latest/meta-data/local-ipv4")

cat > /var/app/staging/.env <<EOF
INSTANCE_PRIVATE_IP=$IP
EOF