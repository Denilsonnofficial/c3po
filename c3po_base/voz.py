"""Fala -> texto (faster-whisper, CPU) e texto -> fala (Edge-TTS com reserva Piper offline).

Toda a saída de voz é PCM s16le, 24 kHz, mono.
"""
import asyncio
import logging
import os
import re
import time

try:
    import numpy as np
except ImportError:          # só o whisper e o corte de áudio longo usam
    np = None

log = logging.getLogger("voz")
TAXA_SAIDA = 24000
MODELOS = os.environ.get("C3PO_MODELOS", os.path.join(os.environ.get("C3PO_DADOS", os.path.expanduser("~/.local/share/c3po/dados")), "modelos"))

VOZES_EDGE = {"feminino": "pt-BR-FranciscaNeural", "masculino": "pt-BR-AntonioNeural"}
VOZ_PIPER = "pt_BR-faber-medium"
URL_PIPER = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/"


class Ouvido:
    def __init__(self, tamanho="small", threads=None):
        from faster_whisper import WhisperModel

        t0 = time.time()
        self.modelo = WhisperModel(
            tamanho, device="cpu", compute_type="int8",
            cpu_threads=threads or os.cpu_count() or 4, download_root=os.path.join(MODELOS, "whisper"),
        )
        log.info("whisper %s carregado em %.1fs", tamanho, time.time() - t0)

    def transcrever(self, pcm16k: bytes, nome=""):
        """Reserva local (CPU). Só o nome vai como dica: o texto do Vosk puxava o Whisper para o erro."""
        audio = np.frombuffer(pcm16k, dtype=np.int16).astype(np.float32) / 32768.0
        if audio.size < 16000 * 0.3:
            return ""
        pico = float(np.max(np.abs(audio))) or 1.0
        if pico < 0.5:                      # microfone baixo: normaliza antes
            audio = audio * min(8.0, 0.7 / pico)
        segs, _ = self.modelo.transcribe(
            audio, language="pt", beam_size=3, best_of=1, temperature=0.0,
            condition_on_previous_text=False, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500, "threshold": 0.35, "speech_pad_ms": 400},
            initial_prompt=f"{nome}," if nome else None, without_timestamps=True,
        )
        return " ".join(s.text.strip() for s in segs).strip()


URL_GOOGLE = ("http://www.google.com/speech-api/v2/recognize?client=chromium&lang=pt-BR"
              "&key=AIzaSyBOti4mM-6x9WDnZIjIeyEU21OpBXqWBgw&pFilter=0")


def _partes(pcm16k: bytes, max_s=24):
    """Corta áudio longo em pedaços de até `max_s` s, no trecho mais silencioso perto do limite."""
    a = np.frombuffer(pcm16k, dtype=np.int16)
    taxa, partes, ini = 16000, [], 0
    while len(a) - ini > max_s * taxa:
        janela = a[ini + (max_s - 6) * taxa: ini + max_s * taxa].astype(np.float32)
        quadros = janela[: len(janela) // 1600 * 1600].reshape(-1, 1600)
        corte = ini + (max_s - 6) * taxa + int(np.argmin((quadros ** 2).mean(axis=1))) * 1600 + 800
        partes.append(a[ini:corte].tobytes())
        ini = corte
    partes.append(a[ini:].tobytes())
    return partes


async def transcrever_google(pcm16k: bytes, http):
    """Reconhecimento de voz do Chrome: gratuito, sem chave própria, ~2 s e muito melhor que o
    Whisper pequeno em CPU. Áudio longo vai em pedaços em paralelo (o serviço engasga com fala
    de mais de ~30 s). Devolve "" se não entendeu; levanta exceção se o serviço falhou."""
    partes = _partes(pcm16k)
    textos = await asyncio.gather(*(_google_um(p, http, 6 + len(p) / 32000 * 0.4) for p in partes))
    return " ".join(t for t in textos if t).strip()


async def _google_um(pcm16k: bytes, http, tempo):
    ff = await asyncio.create_subprocess_exec(
        "ffmpeg", "-loglevel", "error", "-f", "s16le", "-ar", "16000", "-ac", "1", "-i", "pipe:0",
        "-af", "dynaudnorm=f=150:g=15", "-f", "flac", "pipe:1",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
    )
    flac, _ = await ff.communicate(pcm16k)
    async with http.post(URL_GOOGLE, data=flac, headers={"Content-Type": "audio/x-flac; rate=16000"},
                         timeout=aiohttp_timeout(tempo)) as r:
        if r.status != 200:
            raise RuntimeError(f"google stt HTTP {r.status}")
        corpo = await r.text()
    import json

    for linha in corpo.splitlines():
        try:
            d = json.loads(linha)
        except ValueError:
            continue
        for res in d.get("result", []):
            alts = res.get("alternative") or []
            if alts:
                return alts[0].get("transcript", "").strip()
    return ""


def aiohttp_timeout(s):
    import aiohttp

    return aiohttp.ClientTimeout(total=s)


def limpar_para_fala(texto):
    texto = re.sub(r"```.*?```", " ", texto, flags=re.S)
    texto = re.sub(r"`([^`]*)`", r"\1", texto)
    texto = re.sub(r"https?://\S+", "o link", texto)
    texto = re.sub(r"^\s*[-*•]\s+", "", texto, flags=re.M)
    texto = re.sub(r"^\s*#+\s*", "", texto, flags=re.M)
    texto = re.sub(r"[*_~|>#]", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


class Boca:
    def __init__(self, genero="feminino"):
        self.voz_edge = VOZES_EDGE.get(genero, VOZES_EDGE["feminino"])
        self.falhas_edge = 0

    def definir_genero(self, genero):
        self.voz_edge = VOZES_EDGE.get(genero, VOZES_EDGE["feminino"])

    async def falar(self, texto):
        """Gera blocos PCM 24 kHz para uma frase."""
        texto = limpar_para_fala(texto)
        if not re.search(r"\w", texto):
            return
        if self.falhas_edge < 3:
            try:
                n = 0
                async for bloco in self._edge(texto):
                    n += len(bloco)
                    yield bloco
                if n:
                    self.falhas_edge = 0
                    return
            except Exception as e:
                log.warning("edge-tts falhou (%s), usando piper", e)
            self.falhas_edge += 1
        else:
            # tenta o edge de novo de vez em quando
            self.falhas_edge = self.falhas_edge + 1 if self.falhas_edge < 20 else 0
        async for bloco in self._piper(texto):
            yield bloco

    async def _ffmpeg(self, formato_entrada):
        return await asyncio.create_subprocess_exec(
            "ffmpeg", "-loglevel", "error", *formato_entrada, "-i", "pipe:0",
            "-f", "s16le", "-ac", "1", "-ar", str(TAXA_SAIDA), "pipe:1",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        )

    async def _edge(self, texto):
        import edge_tts

        proc = await self._ffmpeg(["-f", "mp3"])

        async def alimentar():
            try:
                com = edge_tts.Communicate(texto, self.voz_edge, rate="+8%")
                async for c in com.stream():
                    if c["type"] == "audio":
                        proc.stdin.write(c["data"])
                        await proc.stdin.drain()
            finally:
                proc.stdin.close()

        tarefa = asyncio.create_task(alimentar())
        try:
            while True:
                bloco = await proc.stdout.read(9600)
                if not bloco:
                    break
                yield bloco
            await tarefa  # propaga erro de rede
        finally:
            if not tarefa.done():
                tarefa.cancel()
            if proc.returncode is None:
                proc.kill()
            await proc.wait()

    async def _baixar_piper(self):
        pasta = os.path.join(MODELOS, "piper")
        os.makedirs(pasta, exist_ok=True)
        onnx = os.path.join(pasta, VOZ_PIPER + ".onnx")
        for nome in (VOZ_PIPER + ".onnx", VOZ_PIPER + ".onnx.json"):
            destino = os.path.join(pasta, nome)
            if not os.path.exists(destino):
                p = await asyncio.create_subprocess_exec("curl", "-fsSL", "-o", destino + ".tmp", URL_PIPER + nome)
                if await p.wait() != 0:
                    raise RuntimeError("não consegui baixar a voz piper")
                os.replace(destino + ".tmp", destino)
        return onnx

    async def _piper(self, texto):
        onnx = await self._baixar_piper()
        piper = await asyncio.create_subprocess_exec(
            "piper", "-m", onnx, "--output-raw",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        ff = await self._ffmpeg(["-f", "s16le", "-ar", "22050", "-ac", "1"])
        piper.stdin.write(texto.encode() + b"\n")
        piper.stdin.close()

        async def ligar():
            while True:
                b = await piper.stdout.read(8192)
                if not b:
                    break
                ff.stdin.write(b)
                await ff.stdin.drain()
            ff.stdin.close()

        tarefa = asyncio.create_task(ligar())
        while True:
            b = await ff.stdout.read(9600)
            if not b:
                break
            yield b
        await tarefa
        await piper.wait()
        await ff.wait()


class Fatiador:
    """Corta o texto que chega em streaming em frases para falar uma por vez."""

    FIM = re.compile(r"([.!?…:;]+[\"')\]]*\s+|\n+)")

    def __init__(self):
        self.buf = ""
        self.primeira = True

    def alimentar(self, delta):
        self.buf += delta
        frases = []
        while True:
            minimo = 12 if self.primeira else 40
            corte = None
            for m in self.FIM.finditer(self.buf):
                if m.end() >= minimo:
                    corte = m.end()
                    break
            if corte is None:
                break
            frases.append(self.buf[:corte].strip())
            self.buf = self.buf[corte:]
            self.primeira = False
        return [f for f in frases if f]

    def resto(self):
        f, self.buf = self.buf.strip(), ""
        return [f] if f else []
