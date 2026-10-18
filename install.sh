#!/usr/bin/env bash
# Instalador de uma linha do C3PO:
#   curl -fsSL https://raw.githubusercontent.com/Denilsonnofficial/c3po/main/install.sh | bash
# (se o repositório voltar a ser privado: C3PO_TOKEN_GITHUB=<token> para baixar)
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
  if [ -n "$TOKEN" ]; then
    url="https://api.github.com/repos/$REPO/tarball/$RAMO"
    ok=$(curl -fsSL -H "Authorization: Bearer $TOKEN" "$url" -o "$tmp/c3po.tar.gz" && echo s || echo n)
  else
    url="https://codeload.github.com/$REPO/tar.gz/refs/heads/$RAMO"
    ok=$(curl -fsSL "$url" -o "$tmp/c3po.tar.gz" && echo s || echo n)
  fi
  if [ "$ok" != s ]; then
    printf '\033[38;5;203mErro:\033[0m não consegui baixar %s (sem internet, ou o repositório ficou privado:\n' "$REPO" >&2
    printf '      nesse caso rode com C3PO_TOKEN_GITHUB=<token>).\n' >&2
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
