#!/usr/bin/env bash
# Lista as pastas do FTP da Locaweb (só leitura) — pra descobrir qual
# pasta o servidor publica. A senha é digitada aqui e não fica salva.
set -euo pipefail

HOST=${FTP_HOST:-ftp.facchiniassessoria.com.br}
USUARIO=facchiniassessoria1

read -r -s -p "Senha do FTP ($USUARIO): " SENHA; echo
CONFIG=$(mktemp); trap 'rm -f "$CONFIG"' EXIT
SENHA=${SENHA//\\/\\\\}; SENHA=${SENHA//\"/\\\"}
printf 'user = "%s:%s"\n' "$USUARIO" "$SENHA" > "$CONFIG"
unset SENHA

for pasta in "" "public_html/"; do
  echo "=== /$pasta ==="
  curl -sS --ssl -K "$CONFIG" "ftp://$HOST/$pasta" | head -40
done
