#!/usr/bin/env bash
# Instalador de uma linha do C3PO:
#   curl -fsSL https://raw.githubusercontent.com/Denilsonnofficial/c3po/main/install.sh | bash
# Baixa o projeto e roda o instalador; a configuração (nome, voz, personalidade) usa o terminal.
set -euo pipefail
REPO="${C3PO_REPO:-Denilsonnofficial/c3po}"
RAMO="${C3PO_RAMO:-main}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
if [ -n "${C3PO_FONTE:-}" ]; then                 # teste: instala de uma pasta local
  cp -r "$C3PO_FONTE"/. "$tmp/c3po"
else
  printf '\033[38;5;214m==>\033[0m Baixando o C3PO (%s)\n' "$REPO"
  curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$RAMO" | tar -xz -C "$tmp"
  mv "$tmp"/c3po-* "$tmp/c3po"
fi
# com "curl | bash" a entrada é o pipe: a configuração lê do terminal de verdade
if [ -t 1 ] && [ -e /dev/tty ] && : < /dev/tty 2>/dev/null; then
  bash "$tmp/c3po/instalar.sh" "$@" < /dev/tty
else
  bash "$tmp/c3po/instalar.sh" --sem-configurar "$@"
fi
