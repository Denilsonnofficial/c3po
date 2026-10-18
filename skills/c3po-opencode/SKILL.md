---
name: c3po-opencode
description: Use quando o usuário pedir para colocar o OpenCode (com qualquer modelo do OpenCode ou OpenRouter: deepseek, glm, mimo, kimi...) para trabalhar em algum projeto ou tarefa de código, em segundo plano.
---

# OpenCode como agente de trabalho

Use o opencode instalado na máquina (`opencode`). Não confunda com você: você roda num opencode próprio do C3PO; este é o do usuário.

## Disparar (em segundo plano)
```
c3po-agentes iniciar opencode <pasta> "<tarefa completa>" --modelo opencode/deepseek-v4.1-flash-free --nome <apelido>
```
- Roda `opencode run --auto --dir <pasta>`; `--modelo` no formato `provedor/modelo`
  (os grátis `opencode/...-free` não custam nada; os do OpenRouter podem custar).
- Escreva a tarefa completa: ele não vê a conversa.

## Acompanhar e fiscalizar
`c3po-agentes lista`, `c3po-agentes ver <id> 60`, `c3po-agentes mudancas <id>`,
`c3po-agentes parar <id>`. Ao terminar, resuma o que mudou e aponte o que parecer errado.
