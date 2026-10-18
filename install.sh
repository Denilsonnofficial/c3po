#!/usr/bin/env bash
# Instalador de uma linha do C3PO (repositório privado: precisa de um token do GitHub com leitura).
#   read -rsp "Token do GitHub: " T; echo          (primeiro este, sozinho)
#   curl -fsSL -H "Authorization: Bearer $T" -H "Accept: application/vnd.github.raw" \
#     https://api.github.com/repos/Denilsonnofficial/c3po/contents/install.sh | C3PO_TOKEN_GITHUB="$T" bash
# Baixa o projeto e roda o instalador; a configuração (nome, voz, personalidade) usa o terminal.
set -euo pipefail
REPO="${C3PO_REPO:-Denilsonnofficial/c3po}"
RAMO="${C3PO_RAMO:-main}"
TOKEN="${C3PO_TOKEN_GITHUB:-${GITHUB_TOKEN:-}}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
if [ -n "${C3PO_FONTE:-}" ]; then                 # teste: instala de uma pasta local
  cp -r "$C3PO_FONTE"/. "$tmp/c3po"
else
  printf '\033[38;5;214m==>\033[0m Baixando o C3PO (%s)\n' "$REPO"
  auth=()
  [ -n "$TOKEN" ] && auth=(-H "Authorization: Bearer $TOKEN")
  if ! curl -fsSL "${auth[@]}" "https://api.github.com/repos/$REPO/tarball/$RAMO" -o "$tmp/c3po.tar.gz"; then
    printf '\033[38;5;203mErro:\033[0m não consegui baixar %s. O repositório é privado: confira o token\n' "$REPO" >&2
    printf '      (precisa de acesso de leitura a "Contents" desse repositório).\n' >&2
    exit 1
  fi
  mkdir -p "$tmp/x" && tar -xzf "$tmp/c3po.tar.gz" -C "$tmp/x"
  mv "$tmp"/x/* "$tmp/c3po"
fi
unset TOKEN C3PO_TOKEN_GITHUB GITHUB_TOKEN    # o resto da instalação não precisa do token
# com "curl | bash" a entrada é o pipe: a configuração lê do terminal de verdade
if [ -t 1 ] && [ -e /dev/tty ] && : < /dev/tty 2>/dev/null; then
  bash "$tmp/c3po/instalar.sh" "$@" < /dev/tty
else
  bash "$tmp/c3po/instalar.sh" --sem-configurar "$@"
fi
