#!/usr/bin/env bash
# Sobe deploy-locaweb/ (gerada por montar-locaweb.sh) pro FTP da Locaweb.
# A senha é digitada aqui, no terminal, e não fica salva em lugar nenhum.
set -euo pipefail
cd "$(dirname "$0")/.."

HOST=${FTP_HOST:-ftp.facchiniassessoria.com.br}
USUARIO=facchiniassessoria1
PASTA_SITE=public_html
ORIGEM=deploy-locaweb

[[ -d "$ORIGEM" ]] || { echo "Rode antes: scripts/montar-locaweb.sh"; exit 1; }

read -r -s -p "Senha do FTP ($USUARIO): " SENHA; echo
CONFIG=$(mktemp); trap 'rm -f "$CONFIG"' EXIT
SENHA=${SENHA//\\/\\\\}; SENHA=${SENHA//\"/\\\"}
printf 'user = "%s:%s"\n' "$USUARIO" "$SENHA" > "$CONFIG"
unset SENHA

echo "Conferindo acesso..."
curl -s --ssl -K "$CONFIG" "ftp://$HOST/" --list-only | grep -qx "$PASTA_SITE" \
  || { echo "Login falhou ou a pasta $PASTA_SITE não existe no FTP."; exit 1; }

total=$(find "$ORIGEM" -type f | wc -l | tr -d ' ')
n=0
while IFS= read -r arquivo; do
  n=$((n + 1))
  destino="${arquivo#"$ORIGEM"/}"
  printf "[%s/%s] %s\n" "$n" "$total" "$destino"
  curl -s --ssl --ftp-create-dirs -K "$CONFIG" -T "$arquivo" "ftp://$HOST/$PASTA_SITE/$destino"
done < <(find "$ORIGEM" -type f | sort)

echo "Pronto: $total arquivos enviados para $PASTA_SITE/."
