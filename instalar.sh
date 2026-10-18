#!/usr/bin/env bash
# Instala o C3PO para o usuário atual (tudo local).
# uso: ./instalar.sh [--sem-configurar] [--remover]
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
RAIZ="${XDG_DATA_HOME:-$HOME/.local/share}/c3po"
APP="$RAIZ/app"
DADOS="$RAIZ/dados"
BIN="$HOME/.local/bin"
UNIDADES="$HOME/.config/systemd/user"
VOSK_URL="https://alphacephei.com/vosk/models/vosk-model-small-pt-0.3.zip"
OPENCODE_VERSAO="1.18.34"      # a API de servidor que o C3PO usa é a da série 1.x
PORTA="${C3PO_PORTA:-8791}"
CONFIGURAR=1

passo() { printf '\033[38;5;214m==>\033[0m %s\n' "$*"; }
aviso() { printf '\033[38;5;245m    %s\033[0m\n' "$*"; }
erro() { printf '\033[38;5;203mErro:\033[0m %s\n' "$*" >&2; exit 1; }
tem() { command -v "$1" >/dev/null 2>&1; }

for a in "$@"; do
  case "$a" in
    --sem-configurar) CONFIGURAR=0 ;;
    --remover)
      passo "Removendo o C3PO"
      systemctl --user disable --now c3po.service c3po-base.service 2>/dev/null || true
      rm -f "$UNIDADES/c3po.service" "$UNIDADES/c3po-base.service" "$BIN/c3po" \
            "$HOME/.local/share/applications/c3po.desktop" "$HOME/.local/share/applications/c3po-terminal.desktop" \
            "$HOME/.config/autostart/c3po.desktop" "$HOME/.config/environment.d/c3po.conf"
      systemctl --user daemon-reload 2>/dev/null || true
      printf '  A memória e as configurações ficaram em %s e ~/.config/c3po (apague se quiser).\n' "$RAIZ"
      exit 0 ;;
    *) erro "opção desconhecida: $a" ;;
  esac
done

[ "$(uname -s)" = "Linux" ] || erro "o C3PO é para Linux"
[ "$(id -u)" != "0" ] || erro "rode como o seu usuário, não como root (o sudo é pedido quando precisar)"

# ---------------------------------------------------------------- dependências do sistema
falta=()
tem python3 || falta+=(python)
tem curl || falta+=(curl)
tem unzip || tem bsdtar || falta+=(unzip)
tem ffmpeg || falta+=(ffmpeg)
tem parec && tem pacat && tem pactl || falta+=(pulse)
python3 -c 'import ctypes.util,sys; sys.exit(0 if ctypes.util.find_library("portaudio") else 1)' 2>/dev/null || falta+=(portaudio)
python3 -c 'import venv, ensurepip' 2>/dev/null || falta+=(venv)
tem notify-send || falta+=(notify)

if [ ${#falta[@]} -gt 0 ]; then
  if tem apt-get; then
    declare -A P=([python]=python3 [curl]=curl [unzip]=unzip [ffmpeg]=ffmpeg [pulse]=pulseaudio-utils
                  [portaudio]=libportaudio2 [venv]="python3-venv python3-pip" [notify]=libnotify-bin)
    extra="libxcb-cursor0 libegl1 libxkbcommon-x11-0 libgl1"
    cmd="apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y"
  elif tem pacman; then
    declare -A P=([python]=python [curl]=curl [unzip]=unzip [ffmpeg]=ffmpeg [pulse]=libpulse
                  [portaudio]=portaudio [venv]=python [notify]=libnotify)
    extra="xcb-util-cursor"
    cmd="pacman -S --needed --noconfirm"
  elif tem dnf; then
    declare -A P=([python]=python3 [curl]=curl [unzip]=unzip [ffmpeg]=ffmpeg-free [pulse]=pulseaudio-utils
                  [portaudio]=portaudio [venv]=python3-pip [notify]=libnotify)
    extra="xcb-util-cursor"
    cmd="dnf install -y"
  elif tem zypper; then
    declare -A P=([python]=python3 [curl]=curl [unzip]=unzip [ffmpeg]=ffmpeg [pulse]=pulseaudio-utils
                  [portaudio]=portaudio [venv]=python3-pip [notify]=libnotify-tools)
    extra="libxcb-cursor0"
    cmd="zypper install -y"
  else
    erro "instale: ${falta[*]} (não reconheci o gerenciador de pacotes)"
  fi
  pacotes=""
  for f in "${falta[@]}"; do pacotes="$pacotes ${P[$f]}"; done
  passo "Instalando dependências do sistema:$pacotes"
  aviso "vai pedir a sua senha (sudo)"
  if [ "$(id -u)" = "0" ]; then sh -c "$cmd $pacotes $extra"; else sudo sh -c "$cmd $pacotes $extra" || sudo sh -c "$cmd $pacotes"; fi
fi

# ---------------------------------------------------------------- ambiente python
passo "Ambiente Python em $RAIZ/venv"
mkdir -p "$RAIZ" "$DADOS" "$BIN"
[ -x "$RAIZ/venv/bin/python" ] || python3 -m venv --system-site-packages "$RAIZ/venv"
PY="$RAIZ/venv/bin/python"
"$PY" -m pip install -q --disable-pip-version-check --upgrade pip >/dev/null 2>&1 || true
"$PY" -m pip install -q --disable-pip-version-check aiohttp edge-tts vosk sounddevice websockets numpy requests
if ! "$PY" -c 'import PySide6.QtWidgets' 2>/dev/null; then
  passo "Instalando a interface (PySide6, uns 150 MB)"
  "$PY" -m pip install -q --disable-pip-version-check PySide6-Essentials
fi
"$PY" -m pip install -q --disable-pip-version-check piper-tts >/dev/null 2>&1 \
  && aviso "voz offline (Piper) disponível como reserva" || aviso "sem voz offline (Piper não instalou); a voz usa a internet"

# ---------------------------------------------------------------- programa
passo "Copiando o programa"
rm -rf "$APP"; mkdir -p "$APP"
cp -r "$AQUI/c3po_base" "$AQUI/c3po_cliente" "$AQUI/bin" "$AQUI/skills" "$AQUI/prompt.md" "$AQUI/opencode.json" "$AQUI/c3po.svg" "$APP/"
find "$APP" -name __pycache__ -prune -exec rm -rf {} +
chmod +x "$APP"/bin/*

# ---------------------------------------------------------------- opencode
OPENCODE=""
if tem opencode && opencode --version 2>/dev/null | grep -qE '^v?1\.'; then
  OPENCODE="$(command -v opencode)"
  passo "Usando o opencode que já está instalado ($("$OPENCODE" --version))"
else
  PRIV="$RAIZ/opencode-home/.opencode/bin/opencode"
  if tem opencode; then
    aviso "o opencode desta máquina é $(opencode --version 2>/dev/null | head -1); o C3PO usa a API da série 1.x"
    aviso "e instala uma cópia só dele (o seu fica intacto; as suas credenciais são reaproveitadas)"
  fi
  if [ ! -x "$PRIV" ]; then
    passo "Instalando o opencode $OPENCODE_VERSAO para o C3PO"
    mkdir -p "$RAIZ/opencode-home"
    curl -fsSL https://opencode.ai/install | HOME="$RAIZ/opencode-home" bash -s -- --version "$OPENCODE_VERSAO" --no-modify-path >/dev/null 2>&1
  fi
  OPENCODE="$PRIV"
fi
[ -x "$OPENCODE" ] || erro "não consegui instalar o opencode"

# ---------------------------------------------------------------- reconhecedor do nome
if [ ! -f "$DADOS/modelos/vosk-pt/final.mdl" ] && [ ! -f "$DADOS/modelos/vosk-pt/am/final.mdl" ]; then
  passo "Baixando o reconhecedor local do nome (Vosk PT, 31 MB)"
  mkdir -p "$DADOS/modelos"; tmp="$(mktemp -d)"
  curl -fsSL -o "$tmp/m.zip" "$VOSK_URL"
  (cd "$tmp" && (unzip -q m.zip || bsdtar -xf m.zip))
  rm -rf "$DADOS/modelos/vosk-pt"; mv "$tmp"/vosk-model-small-pt-* "$DADOS/modelos/vosk-pt"; rm -rf "$tmp"
fi

# ---------------------------------------------------------------- base local
[ -s "$DADOS/token" ] || "$PY" -c 'import secrets;print(secrets.token_urlsafe(24))' > "$DADOS/token"
chmod 600 "$DADOS/token"
cat > "$DADOS/base.env" <<ENV
C3PO_TOKEN=$(cat "$DADOS/token")
C3PO_DADOS=$DADOS
C3PO_PORTA=$PORTA
C3PO_OPENCODE=$OPENCODE
PATH=$APP/bin:$BIN:/usr/local/bin:/usr/bin:/bin
PYTHONPATH=$APP
PYTHONUNBUFFERED=1
ENV
chmod 600 "$DADOS/base.env"

cat > "$BIN/c3po" <<SH
#!/bin/sh
export PYTHONPATH="$APP"
exec "$PY" -m c3po_cliente "\$@"
SH
chmod +x "$BIN/c3po"

passo "Atalhos, ícone e início automático"
mkdir -p "$HOME/.local/share/applications" "$UNIDADES" "$HOME/.local/share/icons/hicolor/scalable/apps"
cp "$AQUI/c3po.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/c3po.svg"
cat > "$HOME/.local/share/applications/c3po.desktop" <<DSK
[Desktop Entry]
Type=Application
Name=C3PO
Comment=Assistente de voz local
Exec=$BIN/c3po gadget
Icon=$APP/c3po.svg
Terminal=false
Categories=Utility;
StartupNotify=false
DSK
cat > "$HOME/.local/share/applications/c3po-terminal.desktop" <<DSK
[Desktop Entry]
Type=Application
Name=C3PO Terminal
Comment=Conversa por texto e comandos (modelo, skills, persona)
Exec=$BIN/c3po terminal
Icon=$APP/c3po.svg
Terminal=false
Categories=Utility;
DSK
cat > "$UNIDADES/c3po-base.service" <<UNIT
[Unit]
Description=C3PO (base local: opencode, memória, voz)
After=network-online.target

[Service]
EnvironmentFile=$DADOS/base.env
ExecStart=$PY -m c3po_base.servidor
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT
cat > "$UNIDADES/c3po.service" <<UNIT
[Unit]
Description=C3PO (gadget de voz)
PartOf=graphical-session.target
After=graphical-session.target c3po-base.service

[Service]
ExecStart=$BIN/c3po gadget
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
UNIT
if systemctl --user daemon-reload 2>/dev/null; then
  systemctl --user enable --now c3po-base.service >/dev/null 2>&1 && aviso "base local rodando (systemctl --user status c3po-base)"
  systemctl --user enable c3po.service >/dev/null 2>&1 && aviso "o gadget abre sozinho ao entrar na sessão"
else
  aviso "sem systemd de usuário: o comando c3po sobe a base quando precisar"
fi

# PATH
for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
  [ -f "$rc" ] && ! grep -qs 'c3po: ~/.local/bin' "$rc" && printf '\nexport PATH="$HOME/.local/bin:$PATH"  # c3po: ~/.local/bin\n' >> "$rc"
done
mkdir -p "$HOME/.config/environment.d"
printf 'PATH=%s:${PATH}\n' "$BIN" > "$HOME/.config/environment.d/c3po.conf"

passo "Pronto. Comando: c3po   (num terminal abre o harness; fora dele, o gadget)"
if [ "$CONFIGURAR" = 1 ] && [ -t 0 ] && [ -t 1 ]; then
  exec "$BIN/c3po" configurar
elif [ "$CONFIGURAR" = 1 ]; then
  aviso "rode 'c3po configurar' num terminal para escolher nome, voz, personalidade e microfone"
fi
