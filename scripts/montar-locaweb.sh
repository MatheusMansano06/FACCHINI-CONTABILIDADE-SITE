#!/usr/bin/env bash
# Monta deploy-locaweb/ com o que sobe por FTP pra hospedagem da Locaweb.
# O site inteiro (home + portal) roda no Railway; a Locaweb só redireciona
# o domínio sem www (facchiniassessoria.com.br) pro www — então é só o
# .htaccess.
set -euo pipefail
cd "$(dirname "$0")/.."

DESTINO=deploy-locaweb
rm -rf "$DESTINO"
mkdir -p "$DESTINO"
cp .htaccess-locaweb "$DESTINO/.htaccess"

echo "Pronto: $DESTINO/.htaccess (redireciona tudo pra https://www.facchiniassessoria.com.br)"
