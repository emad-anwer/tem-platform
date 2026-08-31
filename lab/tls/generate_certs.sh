#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERTS_DIR="${SCRIPT_DIR}/certs"

mkdir -p "${CERTS_DIR}"

# Ensure generated certificates are ignored by Git
echo "*" > "${CERTS_DIR}/.gitignore"

echo "Generating self-signed certificate with Subject Alternative Names (SAN)..."

openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout "${CERTS_DIR}/server.key" \
    -out "${CERTS_DIR}/server.crt" \
    -subj "/C=US/ST=Cairo/L=Cairo/O=TEM-Platform/OU=Target-Lab/CN=target4.lab.local" \
    -addext "subjectAltName=DNS:target4.lab.local,DNS:sub1.target4.lab.local,DNS:api.target4.lab.local,DNS:admin.internal.tem.local,IP:127.0.0.1"

echo "Certificate and private key generated successfully in ${CERTS_DIR}:"
echo "  - ${CERTS_DIR}/server.crt"
echo "  - ${CERTS_DIR}/server.key"

echo -e "\n=== Certificate Details & SANs ==="
openssl x509 -in "${CERTS_DIR}/server.crt" -noout -subject -issuer -ext subjectAltName
