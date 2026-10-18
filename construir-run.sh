#!/usr/bin/env bash
# Gera run/c3po-<versão>.run: instalador autoextraível (offline do código; baixa o resto).
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
VER=$(sed -n 's/^VERSAO = "\(.*\)"/\1/p' "$AQUI/c3po_cliente/__main__.py")
SAIDA="$AQUI/run/c3po-$VER.run"
mkdir -p "$AQUI/run"
rm -f "$AQUI"/run/c3po-*.run
{
cat <<'HDR'
#!/bin/sh
# Instalador do C3PO. uso: sh c3po.run [--sem-configurar | --remover]
set -e
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
L=$(awk '/^__CARGA__$/{print NR+1; exit}' "$0")
tail -n +"$L" "$0" | tar -xz -C "$T"
bash "$T/instalar.sh" "$@"
exit $?
__CARGA__
HDR
tar -cz -C "$AQUI" --exclude=__pycache__ instalar.sh c3po.svg prompt.md opencode.json c3po_base c3po_cliente bin skills
} > "$SAIDA"
chmod +x "$SAIDA"
echo "$SAIDA"
