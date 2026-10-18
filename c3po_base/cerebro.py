"""Cliente do `opencode serve`: sessões, prompt em streaming, permissões."""
import asyncio
import json
import logging
import os
import shutil
import time

import aiohttp

log = logging.getLogger("cerebro")

def porta_livre():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ambiente_opencode(dados):
    """O opencode do C3PO roda com dados/config isolados (não mexe no banco nem na config do
    opencode que o usuário usa, que pode ser de outra versão) mas enxerga as credenciais dele
    (OpenRouter, OpenCode Go...) por um link para o auth.json."""
    env = dict(os.environ)
    base = os.path.join(dados, "opencode")
    for var, sub in (("XDG_DATA_HOME", "dados"), ("XDG_CONFIG_HOME", "config"),
                     ("XDG_STATE_HOME", "estado"), ("XDG_CACHE_HOME", "cache")):
        env[var] = os.path.join(base, sub)
        os.makedirs(env[var], exist_ok=True)
    origem = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "opencode", "auth.json")
    destino = os.path.join(env["XDG_DATA_HOME"], "opencode", "auth.json")
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    if os.path.exists(origem) and not os.path.lexists(destino):
        os.symlink(origem, destino)
    # config do agente (prompt de voz) com o caminho do prompt resolvido
    pasta_app = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = json.load(open(os.path.join(pasta_app, "opencode.json")))
    cfg["agent"]["c3po"]["prompt"] = "{file:" + os.path.join(pasta_app, "prompt.md") + "}"
    cfg.pop("model", None)
    arq = os.path.join(base, "c3po-opencode.json")
    json.dump(cfg, open(arq, "w"), indent=2)
    env["OPENCODE_CONFIG"] = arq
    return env


class Cerebro:
    def __init__(self, modelo, porta=None, pasta_trabalho=None):
        from .memoria import DADOS

        self.definir_modelo(modelo)
        porta = porta or porta_livre()
        self.url = f"http://127.0.0.1:{porta}"
        self.porta = porta
        pasta_trabalho = pasta_trabalho or os.path.join(DADOS, "trabalho")
        self.binario = os.environ.get("C3PO_OPENCODE") or shutil.which("opencode") or "opencode"
        self.env = ambiente_opencode(DADOS)
        self.pasta = pasta_trabalho
        self.proc = None
        self.http = None
        self.filas = {}          # sessionID -> asyncio.Queue de eventos
        self.tipo_parte = {}     # partID -> tipo (text, reasoning, tool...)
        self.papel_msg = {}      # messageID -> role
        self.pai_msg = {}        # messageID -> parentID (resposta -> pergunta)
        self.msgs_sessao = {}    # sessionID -> ids de mensagens já vistas
        self._tarefa_eventos = None

    def definir_modelo(self, modelo):
        prov, _, mod = modelo.partition("/")
        self.nome_modelo = modelo
        self.modelo = {"providerID": prov, "modelID": mod}

    async def listar_modelos(self):
        cache = getattr(self, "_modelos", None)
        if cache and time.time() - cache[0] < 300:
            return cache[1]
        p = await asyncio.create_subprocess_exec(self.binario, "models", cwd=self.pasta, env=self.env,
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        saida, _ = await p.communicate()
        lista = sorted(l.strip() for l in saida.decode().splitlines() if "/" in l)
        if lista:
            self._modelos = (time.time(), lista)
        return lista

    async def variantes(self, modelo):
        """Níveis de raciocínio que o modelo aceita (campo variants do opencode)."""
        cache = getattr(self, "_variantes", None)
        if cache is None or time.time() - cache[0] > 600:
            p = await asyncio.create_subprocess_exec(self.binario, "models", "--verbose", cwd=self.pasta, env=self.env,
                                                     stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            saida, _ = await p.communicate()
            mapa, atual, buf, nivel = {}, None, [], 0
            for linha in saida.decode(errors="replace").splitlines():
                if nivel == 0 and "/" in linha and not linha.startswith((" ", "{")):
                    atual, buf = linha.strip(), []
                    continue
                if atual is not None:
                    buf.append(linha)
                    nivel += linha.count("{") - linha.count("}")
                    if nivel == 0 and buf:
                        try:
                            mapa[atual] = list((json.loads("\n".join(buf)).get("variants") or {}).keys())
                        except ValueError:
                            pass
                        atual, buf = None, []
            cache = self._variantes = (time.time(), mapa)
        return cache[1].get(modelo, [])

    async def iniciar(self):
        os.makedirs(self.pasta, exist_ok=True)
        self.proc = await asyncio.create_subprocess_exec(
            self.binario, "serve", "--port", str(self.porta), "--hostname", "127.0.0.1",
            cwd=self.pasta, env=self.env,
        )
        self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=10))
        for _ in range(120):
            try:
                async with self.http.get(self.url + "/global/health", timeout=aiohttp.ClientTimeout(total=3)) as r:
                    if r.status == 200:
                        break
            except (aiohttp.ClientError, asyncio.TimeoutError):
                pass
            await asyncio.sleep(0.5)
        else:
            raise RuntimeError("opencode serve não subiu")
        self._tarefa_eventos = asyncio.create_task(self._ouvir_eventos())
        log.info("opencode pronto em %s", self.url)

    async def parar(self):
        if self._tarefa_eventos:
            self._tarefa_eventos.cancel()
        if self.http:
            await self.http.close()
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            await self.proc.wait()

    async def _post(self, caminho, corpo):
        async with self.http.post(self.url + caminho, json=corpo) as r:
            txt = await r.text()
            if r.status >= 400:
                raise RuntimeError(f"{caminho}: HTTP {r.status} {txt[:300]}")
            return json.loads(txt) if txt else None

    async def _ouvir_eventos(self):
        while True:
            try:
                async with self.http.get(self.url + "/event") as r:
                    async for linha in r.content:
                        linha = linha.decode(errors="replace").strip()
                        if linha.startswith("data:"):
                            try:
                                self._despachar(json.loads(linha[5:]))
                            except Exception:
                                log.exception("evento inválido")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("fluxo de eventos caiu (%s), reconectando", e)
                await asyncio.sleep(1)

    def _despachar(self, ev):
        tipo = ev.get("type", "")
        p = ev.get("properties") or {}
        if tipo == "message.updated":
            info = p.get("info") or {}
            self.papel_msg[info.get("id")] = info.get("role")
            self.pai_msg[info.get("id")] = info.get("parentID")
            self.msgs_sessao.setdefault(info.get("sessionID"), set()).add(info.get("id"))
        elif tipo == "message.part.updated":
            parte = p.get("part") or {}
            self.tipo_parte[parte.get("id")] = parte.get("type")
        sid = p.get("sessionID") or (p.get("part") or {}).get("sessionID") or (p.get("info") or {}).get("sessionID")
        fila = self.filas.get(sid)
        if fila is not None:
            fila.put_nowait(ev)

    async def nova_sessao(self, titulo):
        r = await self._post("/session", {"title": titulo})
        return r["id"]

    async def abortar(self, sid):
        """Aborta e espera a sessão ficar livre, para o aviso de "abortado" não cair no próximo pedido."""
        fila = asyncio.Queue()
        self.filas[sid] = fila
        try:
            await self._post(f"/session/{sid}/abort", {})
            fim = time.time() + 4
            while time.time() < fim:
                try:
                    ev = await asyncio.wait_for(fila.get(), timeout=fim - time.time())
                except asyncio.TimeoutError:
                    break
                st = ((ev.get("properties") or {}).get("status") or {}).get("type")
                if ev.get("type") == "session.idle" or st == "idle":
                    break
        except Exception as e:
            log.warning("abortar: %s", e)
        finally:
            if self.filas.get(sid) is fila:
                self.filas.pop(sid, None)

    async def responder_permissao(self, pid, aprovar):
        await self._post(f"/permission/{pid}/reply", {"reply": "once" if aprovar else "reject"})

    async def perguntar(self, sid, texto, system=None, variante=None, agente="c3po", ferramentas=None, tempo_max=600):
        """Gera eventos simples:
        ("texto", delta) | ("ferramenta", nome, status, titulo) | ("permissao", props) | ("erro", msg) | ("fim",)
        """
        fila = asyncio.Queue()
        self.filas[sid] = fila
        corpo = {"model": self.modelo, "agent": agente, "parts": [{"type": "text", "text": texto}]}
        if system:
            corpo["system"] = system
        if ferramentas is not None:
            corpo["tools"] = ferramentas
        if variante:
            corpo["variant"] = variante
        acumulado = {}     # partID -> texto já emitido
        pendentes = {}     # partID -> deltas que chegaram antes de sabermos o tipo
        estado_ferr = {}
        # só valem eventos da resposta a ESTA pergunta: um "idle" ou texto atrasado do pedido que
        # acabou de ser interrompido não pode encerrar nem sujar o pedido novo
        antes = set(self.msgs_sessao.get(sid, set()))
        minha_pergunta, minhas, deu_erro = None, set(), False
        guardados = {}     # messageID ainda desconhecido -> eventos
        inicio = time.time()
        try:
            await self._post(f"/session/{sid}/prompt_async", corpo)
            replay = []
            while True:
                if replay:
                    ev = replay.pop(0)
                else:
                    restante = tempo_max - (time.time() - inicio)
                    if restante <= 0:
                        yield ("erro", "tempo esgotado")
                        await self.abortar(sid)
                        return
                    try:
                        ev = await asyncio.wait_for(fila.get(), timeout=restante)
                    except asyncio.TimeoutError:
                        continue
                tipo = ev.get("type", "")
                p = ev.get("properties") or {}
                if tipo == "message.updated":
                    info = p.get("info") or {}
                    mid = info.get("id")
                    if info.get("role") == "user" and minha_pergunta is None and mid not in antes:
                        minha_pergunta = mid
                    elif info.get("role") == "assistant" and minha_pergunta and info.get("parentID") == minha_pergunta:
                        minhas.add(mid)
                    if mid in guardados and (mid in minhas or self.papel_msg.get(mid) == "user"):
                        replay.extend(guardados.pop(mid))
                    continue
                if tipo in ("message.part.delta", "message.part.updated"):
                    mid = p.get("messageID") or (p.get("part") or {}).get("messageID")
                    if mid not in minhas:
                        if mid not in self.papel_msg:
                            guardados.setdefault(mid, []).append(ev)
                        continue
                if tipo == "message.part.delta":
                    pid = p.get("partID")
                    if p.get("field") != "text":
                        continue
                    t = self.tipo_parte.get(pid)
                    if t is None:
                        pendentes.setdefault(pid, []).append(p.get("delta", ""))
                    elif t == "text":
                        if pid not in acumulado and acumulado:
                            yield ("texto", "\n")      # trecho novo depois de uma ferramenta
                        acumulado[pid] = acumulado.get(pid, "") + p.get("delta", "")
                        yield ("texto", p.get("delta", ""))
                elif tipo == "message.part.updated":
                    parte = p.get("part") or {}
                    pid, t = parte.get("id"), parte.get("type")
                    if pid in pendentes:
                        deltas = pendentes.pop(pid)
                        if t == "text":
                            d = "".join(deltas)
                            if acumulado and pid not in acumulado:
                                yield ("texto", "\n")
                            acumulado[pid] = acumulado.get(pid, "") + d
                            yield ("texto", d)
                    if t == "text":
                        # provedor que não manda delta: emite o que faltou
                        cheio = parte.get("text") or ""
                        ja = acumulado.get(pid, "")
                        if (parte.get("time") or {}).get("end") and len(cheio) > len(ja) and cheio.startswith(ja):
                            acumulado[pid] = cheio
                            yield ("texto", cheio[len(ja):])
                    elif t == "tool":
                        st = (parte.get("state") or {}).get("status")
                        if estado_ferr.get(pid) != st:
                            estado_ferr[pid] = st
                            titulo = (parte.get("state") or {}).get("title") or ""
                            yield ("ferramenta", parte.get("tool"), st, titulo)
                elif tipo in ("permission.asked", "permission.v2.asked"):
                    yield ("permissao", p)
                elif tipo == "session.error":
                    err = p.get("error") or {}
                    msg = (err.get("data") or {}).get("message") or err.get("name") or "erro do modelo"
                    if "abort" in f"{err.get('name', '')} {msg}".lower() or minha_pergunta is None:
                        continue        # sobra do pedido anterior que foi interrompido
                    deu_erro = True
                    yield ("erro", msg)
                elif tipo == "session.idle":
                    if minha_pergunta is None or not (minhas or deu_erro):
                        continue        # idle atrasado do pedido anterior
                    yield ("fim",)
                    return
        finally:
            self.filas.pop(sid, None)

    async def completar(self, texto, system=None, titulo="tarefa interna", tempo_max=180):
        """Pergunta isolada, sem ferramentas; devolve o texto inteiro."""
        # o plano gratuito recusa pedidos com as ferramentas desligadas; elas ficam ligadas
        # e qualquer tentativa de comando é recusada aqui
        sid = await self.nova_sessao(titulo)
        partes = []
        async for ev in self.perguntar(sid, texto, system=system, tempo_max=tempo_max):
            if ev[0] == "texto":
                partes.append(ev[1])
            elif ev[0] == "permissao":
                await self.responder_permissao(ev[1]["id"], False)
            elif ev[0] == "erro":
                raise RuntimeError(ev[1])
        try:
            async with self.http.delete(f"{self.url}/session/{sid}"):
                pass
        except Exception:
            pass
        return "".join(partes).strip()
