#cat > docker/grafana/entrypoint.sh <<'ENDOFFILE'
#!/bin/sh
# Generates /etc/grafana/grafana.ini at container startup using env vars.
# No hardcoded hostnames — Azure passes them via GF_SERVER_DOMAIN and GF_SERVER_ROOT_URL.

set -e

#: "${GF_SERVER_DOMAIN:?ERROR: GF_SERVER_DOMAIN env var not set}"
#: "${GF_SERVER_ROOT_URL:?ERROR: GF_SERVER_ROOT_URL env var not set}"
GF_SERVER_DOMAIN="${GF_SERVER_DOMAIN:-localhost}"
GF_SERVER_ROOT_URL="${GF_SERVER_ROOT_URL:-http://localhost:3000/grafana/}"

cat > /etc/grafana/grafana.ini <<EOF
[server]
protocol             = http
http_port            = 3000
domain               = ${GF_SERVER_DOMAIN}
root_url             = ${GF_SERVER_ROOT_URL}
serve_from_sub_path  = true
enable_gzip          = true

[security]
admin_user           = admin
allow_embedding      = true
cookie_secure        = false
cookie_samesite      = disabled

[users]
allow_sign_up        = false
auto_assign_org      = true
auto_assign_org_role = Viewer

[auth]
disable_login_form   = false

[auth.anonymous]
enabled              = false

[live]
allowed_origins      = *

[log]
mode                 = console
level                = info

[dataproxy]
timeout              = 300
EOF

echo "[entrypoint] Generated /etc/grafana/grafana.ini"
echo "  domain             = ${GF_SERVER_DOMAIN}"
echo "  root_url           = ${GF_SERVER_ROOT_URL}"
echo "  serve_from_sub_path = true"

# Hand off to Grafana's real entrypoint (starts grafana-server)
exec /run.sh "$@"
#ENDOFFILE

#chmod +x docker/grafana/entrypoint.sh