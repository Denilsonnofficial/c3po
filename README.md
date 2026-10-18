# C3PO

Assistente de voz para Linux que roda **inteiro na sua máquina**: fica ouvindo, acorda quando
você diz o nome dele, conversa por voz e controla o computador pelo terminal. É o fork local do
[Jarvis](https://github.com/Denilsonnofficial/jarvis): mesma base (opencode, memória em três camadas,
modo conversa, interrupção por voz, harness de terminal, skills), sem servidor, sem Docker e sem SSH.

Estado: **1.1.1**. Instalação testada do zero num Ubuntu 24.04 limpo (dependências, opencode
próprio, escolha automática do MiMo, base, assistente de configuração, harness e uma pergunta
respondida); gadget e temas testados no Arch/GNOME.

## Instalar

```
curl -fsSL https://raw.githubusercontent.com/Denilsonnofficial/c3po/main/install.sh | bash
```

Outras formas: `git clone` + `./instalar.sh`, ou o instalador offline `run/c3po-<versão>.run`
(`sh c3po-1.0.0.run`). Para remover: `./instalar.sh --remover` (a memória fica, se você quiser
voltar).

O instalador, como usuário comum (pede sudo só se faltar pacote do sistema):

1. Detecta a distro (apt, pacman, dnf, zypper) e instala só o que falta: python3/venv, ffmpeg,
   PortAudio, utilitários do PulseAudio/PipeWire, libnotify e as bibliotecas do Qt.
2. Cria um ambiente Python próprio em `~/.local/share/c3po/venv` (aiohttp, edge-tts, vosk,
   sounddevice, websockets, numpy; PySide6 se o sistema não tiver; Piper como voz offline de reserva
   se instalar).
3. **opencode:** se o da máquina for da série 1.x, usa esse. Se não houver, ou se for o 2.x (que
   trocou a API do servidor), instala uma cópia 1.x só para o C3PO em
   `~/.local/share/c3po/opencode-home`, sem mexer no seu.
4. Baixa o reconhecedor local do nome (Vosk PT, 31 MB).
5. Cria a base local (`c3po-base.service`, só em 127.0.0.1:8791, com token), o gadget
   (`c3po.service`, abre no login), o comando `c3po`, os atalhos **C3PO** e **C3PO Terminal** com
   ícone, e põe `~/.local/bin` no PATH.
6. Abre o assistente de configuração no terminal: nome, gênero/voz, como te chamar, personalidade,
   autonomia, microfone e calibração do nome com a sua voz.

Sem systemd de usuário (WSL, containers), o comando `c3po` sobe a base sozinho quando precisa.

## Modelos

- Padrão: **MiMo grátis** do OpenCode (a versão mais nova disponível). Se ele sumir ou falhar,
  o C3PO passa sozinho para outro grátis (outros grátis do OpenCode, depois os `:free` do
  OpenRouter) e tenta o pedido de novo.
- O opencode do C3PO roda com dados e configuração isolados em `~/.local/share/c3po/dados/opencode`
  (não toca no banco nem na config do seu opencode), mas enxerga as suas credenciais por um link
  para `~/.local/share/opencode/auth.json`: se você tem **OpenRouter** ou **OpenCode Go**
  configurados, esses modelos aparecem também.
- Trocar: por voz ("troca para o deepseek"), no harness (`/modelo` com busca) ou
  `c3po-modelo trocar <nome>`. Pagos pedem confirmação.

## Uso

```
c3po                 num terminal: harness (conversa por texto e comandos /); fora dele: gadget
c3po gadget          o gadget flutuante
c3po terminal        abre o harness numa janela de terminal (atalho do menu)
c3po configurar      refaz a configuração
c3po atualizar       baixa a versão mais nova do GitHub (mantém configuração e memória)
c3po texto "..."     pergunta digitada
```

No harness: `/modelo`, `/nome`, `/genero`, `/personalidade`, `/autonomia`, `/skill`, `/memoria`,
`/lembrar`, `/tema`, `/volume`, `/microfone`, `/voz`, `/base`, `/gadget`, `/status`. `/` sozinho
abre a lista com busca.

**Voz:** diga o nome ("C3PO", "cê três pê ó", "si tri pi ó") e o pedido. Depois disso a conversa
fica aberta: fale sem repetir o nome; ela fecha após 20 s de silêncio. Fale por cima para
interromper. Calibrar o nome no `c3po configurar` ajuda muito.

## Botões do gadget

Microfone, **foco** (escuta direto, sem nome e sem fechar a conversa), **raciocínio** (Padrão, Baixo,
Médio, Alto, Máximo: vira a variante que o modelo aceita, ou instrução no prompt quando ele não tem),
tema, volume e liga/desliga. Os botões aparecem com o mouse em cima. No harness: `/foco` e
`/raciocinio`; por voz: "pensa mais/menos".

## Gadgets

Botão de paleta (ou `/tema`). Star Wars: **C-3PO** (padrão: rosto dourado, olhos que acendem e
piscam, boca de grade que acende ao falar), **R2-D2**, **Sabre de luz** (azul pronto, vermelho
pensando, verde executando), **Holograma rebelde**, **BB-8**, **Estrela da Morte**. E os do Jarvis:
Holograma dourado, Azul, Reator, HAL, Âmbar, Esmeralda, Neon, Retrô, Aurora, Grafite. Desenhados à
mão em Qt (nenhuma imagem dos filmes).

## Agentes de trabalho

Skills internas (`skills/`, instaladas em `.opencode/skills` da pasta de trabalho dele):
`c3po-claude-code`, `c3po-codex`, `c3po-opencode`, `c3po-orquestrar-agentes`. Com `c3po-agentes`
ele dispara o Claude Code, o Codex ou o opencode desta máquina em segundo plano (vários ao mesmo
tempo), acompanha log e diff, para os que travarem e avisa por voz quando terminam.

## Memória

`~/.local/share/c3po/dados`: `perfil.md` (fatos permanentes), `memoria_curta.md` (resumo dinâmico
reescrito a cada conversa, até 700 palavras) e `longo_prazo.db` (tudo desde o primeiro dia, SQLite
+ FTS5, consultado com `c3po-lembrar` só quando precisa).

## O que vai para a internet

O nome é detectado localmente (Vosk) e nada sai antes disso. Depois do nome: o áudio do pedido vai
para o reconhecimento de voz do Google, o texto vai para o modelo (OpenCode/OpenRouter) e a resposta
é sintetizada pelo Edge-TTS da Microsoft (com Piper offline de reserva, se instalado).

## Estrutura

```
install.sh        instalador de uma linha (baixa o repositório e roda instalar.sh)
instalar.sh       instalação de verdade (também --remover)
c3po_base/        base local: opencode, voz, memória, WebSocket
c3po_cliente/     gadget (PySide6), microfone/detector do nome, harness, configuração
bin/              c3po-lembrar, c3po-anotar, c3po-modelo, c3po-agentes (no PATH do agente)
skills/           skills internas
construir-run.sh  gera run/c3po-<versão>.run
```

Armadilhas herdadas do Jarvis estão documentadas no README dele; as específicas daqui:

- **"Corta e depois volta" em conversa entre dois assistentes na mesma sala**: a interrupção por
  voz (feita para o usuário) disparava com a voz do outro assistente. O corte ficou mais exigente
  (4+ palavras claramente diferentes, ou 0,8 s de fala junto), a espera de fim de fala subiu para
  1,2 s e `/interromper` desliga a interrupção por voz (o clique no gadget continua cortando).
  O "Só um instante" de um não vira pergunta para o outro. A voz agora é sintetizada adiantada
  (até 3 frases), o que não muda nada hoje (medido: zero buraco) mas protege se a síntese ficar lenta.

- **opencode 2.x mudou a API do servidor** (fica sob `/api`, com senha). O C3PO fala a 1.x; com
  2.x instalado ele usa uma cópia 1.x isolada e reaproveita só o `auth.json`.
- **Nome com número:** o detector converte dígitos em palavras ("C3PO" → "c três po") nos dois
  lados; pedaço curto do nome ("se três") não acorda.
