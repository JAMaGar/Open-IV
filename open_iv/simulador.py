"""
Simulador do Keithley 2400 (subconjunto SCPI usado pelo Open-IV).

Serve para treinar o uso do programa e testar a logica sem o instrumento:
    python Open-IV.py --simular mis      (capacitor MIS com memoria)
    python Open-IV.py --simular solar    (celula solar / diodo)
    python Open-IV.py --simular resistor (resistor de 1 MOhm, teste de temporizacao)

O relogio do instrumento simulado avanca com o tempo de transmissao serial de
cada comando e com a duracao de cada ciclo SDM (source-delay-measure), de modo
que os carimbos de tempo reproduzem a temporizacao do aparelho real. Os modelos
de dispositivo sao qualitativos (nao representam nenhuma amostra real).
"""
import math
import time
from collections import deque

import numpy as np

VT300 = 0.025852


# ============================================================ modelos de dispositivo
class Resistor:
    nome = "Resistor 1 MOhm"

    def __init__(self, R=1e6):
        self.R = R

    def evoluir(self, V, dt):
        pass

    def corrente(self, V, t):
        return V / self.R

    def voc(self):
        return 0.0, self.R


class CapacitorMemoria:
    """Capacitor MIS qualitativo com chaveamento resistivo no ramo +V."""
    nome = "Capacitor MIS com memoria (modelo qualitativo)"

    def __init__(self, C=1e-9, rng=None):
        self.w = 0.0          # 0 = HRS, 1 = LRS
        self.C = C
        self.rng = rng or np.random.default_rng(1)
        self._degraus = deque(maxlen=60)   # (t, dV) para corrente de absorcao
        self._V_ant = 0.0

    def evoluir(self, V, dt):
        if dt <= 0:
            return
        if V > 3.0:
            r = 0.015 * math.exp((V - 4.0) / 0.5)
            self.w += (1 - self.w) * (1 - math.exp(-r * dt))
        elif V < -2.0:
            r = 0.3 * math.exp((-V - 2.0) / 0.5)
            self.w -= self.w * (1 - math.exp(-r * dt))
        self.w -= self.w * (1 - math.exp(-dt / 2e4))       # retencao finita
        self.w = min(1.0, max(0.0, self.w))

    def registrar_degrau(self, t, V):
        dV = V - self._V_ant
        if abs(dV) > 1e-9:
            self._degraus.append((t, dV))
        self._V_ant = V

    def corrente(self, V, t):
        if V >= 0:
            g = 1.0e-8 * (1 - self.w) + 6.0e-8 * self.w
            i = g * (math.exp(V / 0.9) - 1.0)
            i = i / (1.0 + i / 1.4e-3)                     # patamar em +V
        else:
            i = -1.0e-8 * (math.exp(-V / 0.7) - 1.0) * (1 + 0.07 * self.w)
        # absorcao dieletrica (Curie-von Schweidler): I = a*C*dV/(t - t_k)
        ia = 0.0
        for tk, dV in self._degraus:
            dtk = t - tk
            if dtk > 1e-4:
                ia += 0.02 * self.C * dV / dtk
        return i + ia

    def voc(self):
        # "nanobateria": fem pequena que depende do estado
        return 0.06 * (self.w - 0.4), 1e7


class CelulaSolar:
    """Diodo com Rs e Rsh; fotocorrente quando 'luz' = True."""
    nome = "Celula solar / diodo (modelo de 1 diodo)"

    def __init__(self, area_cm2=0.1, luz=True):
        self.luz = luz
        self.Iph = 0.030 * area_cm2        # 30 mA/cm2
        self.I0 = 1e-9
        self.n = 1.6
        self.Rs = 4.0
        self.Rsh = 2e4
        self.Vt = VT300

    def evoluir(self, V, dt):
        pass

    def corrente(self, V, t):
        Iph = self.Iph if self.luz else 0.0
        I = 0.0
        for _ in range(60):  # Newton em f(I) = 0
            Vd = V - I * self.Rs
            e = math.exp(min(80.0, Vd / (self.n * self.Vt)))
            f = self.I0 * (e - 1) + Vd / self.Rsh - Iph - I
            df = -self.I0 * e * self.Rs / (self.n * self.Vt) - self.Rs / self.Rsh - 1
            dI = -f / df
            I += dI
            if abs(dI) < 1e-15:
                break
        return I

    def voc(self):
        lo, hi = -1.0, 1.5
        for _ in range(80):
            m = 0.5 * (lo + hi)
            if self.corrente(m, 0) > 0:
                hi = m
            else:
                lo = m
        return 0.5 * (lo + hi), 50.0


MODELOS = {"mis": CapacitorMemoria, "solar": CelulaSolar, "resistor": Resistor}


# ============================================================ instrumento
class SimTransporte:
    """Substitui o TransporteSerial; interpreta SCPI e devolve respostas."""
    metodo = "simulador"

    def __init__(self, modelo="mis", baud=57600, tempo_real=True, ruido=True, tick=1.0 / 1024,
                 atraso_minimo=0.009, buffer_bytes=128, custo_cmd_s=0.0005, custo_valor_s=0.001,
                 xonxoff=False):
        self.dev = MODELOS.get(modelo, CapacitorMemoria)()
        self.baud = baud
        self.tempo_real = tempo_real
        self.ruido = ruido
        self.tick = tick                    # resolucao do carimbo TIME (2400 real: 1/1024 s)
        self.atraso_minimo = atraso_minimo  # comportamento observado com :SOUR:DEL pequeno
        # Buffer de entrada RS-232 (modelo da 1.1.2, qualitativo). O interpretador le os bytes
        # enquanto chegam se estiver livre; ocupado (processando um comando), os bytes ficam no
        # buffer. Passando de buffer_bytes, o que chega e descartado com -363 e a linha em curso
        # se perde. Processar custa custo_cmd_s por comando + custo_valor_s por valor de lista.
        # Com xonxoff=True o "PC" espera (XOFF) em vez de transbordar. buffer_bytes=None desliga.
        self.buffer_bytes = buffer_bytes
        self.custo_cmd_s = custo_cmd_s
        self.custo_valor_s = custo_valor_s
        self.xonxoff = xonxoff
        self.n_overrun = 0
        self.rng = np.random.default_rng(7)
        self._open = False
        self._out = deque()
        self._prontos = deque()            # instante (relogio simulado) em que cada resposta fica pronta
        self.erros = deque()
        self._em_lista = None
        self._rx = ""                     # linha parcial (comandos chegam em blocos)
        self._ocupado_ate = 0.0           # interpretador ocupado ate este instante
        self._fila = deque()              # linhas completas esperando: (inicio, bytes)
        self._parcial_ocup = 0            # bytes da linha parcial que chegaram com o interpretador ocupado
        self._descartando = False         # linha corrompida por overrun: ignora ate o proximo LF
        self._inicio_cmd = 0.0
        self.reset()

    # ---- interface de transporte
    @property
    def is_open(self):
        return self._open

    def open(self, porta=None, baud=None):
        self._open = True
        self._w0 = time.perf_counter()
        self.t = 0.0
        return self.metodo

    def close(self):
        self._open = False

    def flush_input(self):
        self._out.clear()
        self._prontos.clear()

    def _erro(self, txt):
        """Fila de erros de 10 posicoes, como no 2400 (a ultima vira -350 ao transbordar)."""
        if len(self.erros) >= 10:
            self.erros[-1] = '-350,"Queue overflow"'
        else:
            self.erros.append(txt)

    def _custo(self, linha):
        c = self.custo_cmd_s * max(1, linha.count(";") + 1)
        if ":LIST:" in linha.upper():
            c += self.custo_valor_s * (linha.count(",") + 1)
        if linha.upper().startswith("*RST"):
            c += 0.1
        return c

    def write(self, data):
        if isinstance(data, bytes):
            data = data.decode("ascii")
        self._sincronizar()
        self._avancar(len(data) * 10.0 / self.baud)
        t = self.t
        if self.buffer_bytes:
            while self._fila and self._fila[0][0] <= t:
                self._fila.popleft()
            livre = not self._fila and self._ocupado_ate <= t
            if livre:
                self._parcial_ocup = 0
            else:
                ocup = sum(b for _, b in self._fila) + self._parcial_ocup
                if ocup + len(data) > self.buffer_bytes:
                    if self.xonxoff:     # o 2400 manda XOFF; o PC espera o buffer esvaziar
                        self._avancar(self._ocupado_ate - self.t)
                        t = self.t
                        self._fila.clear()
                        self._parcial_ocup = 0
                    else:
                        self.n_overrun += 1
                        self._erro('-363,"Input buffer overrun"')
                        self._descartando = True
                        return
                else:
                    self._parcial_ocup += len(data)
        self._rx += data.replace("\r", "\n")
        *linhas, self._rx = self._rx.split("\n")
        for linha in linhas:
            if self._descartando:          # resto de uma linha que perdeu bytes
                self._descartando = False
                self._erro('-113,"Undefined header"')
                continue
            linha = linha.strip()
            if not linha:
                continue
            inicio = max(t, self._ocupado_ate)
            self._ocupado_ate = inicio + self._custo(linha)
            if inicio > t and self.buffer_bytes:
                self._fila.append((inicio, len(linha) + 1))
            self._parcial_ocup = 0
            self._inicio_cmd = inicio
            for cmd in linha.split(";"):
                self._executar(cmd.strip())

    def _responder(self, txt):
        self._out.append(txt)
        self._prontos.append(self._ocupado_ate if self.buffer_bytes else self.t)

    def readline(self, timeout=5.0):
        if not self._out:
            if self.tempo_real:
                time.sleep(min(timeout, 0.05))
            return ""
        resp = self._out.popleft()
        pronto = self._prontos.popleft() if self._prontos else self.t
        if pronto - self.t > timeout:      # o 2400 ainda nao respondeu
            self._out.appendleft(resp)
            self._prontos.appendleft(pronto)
            self._avancar(timeout)
            return ""
        self._avancar(pronto - self.t)
        self._avancar(len(resp) * 10.0 / self.baud)
        if self.tempo_real:
            atraso = self.t - (time.perf_counter() - self._w0)
            if atraso > 0:
                time.sleep(min(atraso, timeout))
        return resp

    # ---- relogio
    def _sincronizar(self):
        """O tempo de parede que passou (PC esperando) tambem conta."""
        agora = time.perf_counter() - self._w0
        if agora > self.t:
            self._avancar(agora - self.t)

    def _avancar(self, dt):
        if dt <= 0:
            return
        V = self._nivel_atual()
        passo = 0.05
        n = max(1, int(dt / passo))
        for _ in range(min(n, 2000)):
            self.dev.evoluir(V, dt / min(n, 2000))
        self.t += dt

    def _nivel_atual(self):
        if not self.s["saida"]:
            return 0.0
        if self.s["func"] == "VOLT":
            if self._em_lista is not None:
                return self._em_lista
            return self.s["lev"]["VOLT"]
        return 0.0

    # ---- estado
    def reset(self):
        self.s = {
            "func": "VOLT", "modo": {"VOLT": "FIX", "CURR": "FIX"},
            "lev": {"VOLT": 0.0, "CURR": 0.0}, "lista": {"VOLT": [0.0], "CURR": [0.0]},
            "sdel": 0.0, "tdel": 0.0, "tcoun": 1, "nplc": 1.0, "azer": True,
            "iprot": 1.05e-4, "vprot": 21.0, "elems": ["VOLT", "CURR", "TIME", "STAT"],
            "saida": False, "display": True, "funcs": ["CURR"], "t0": 0.0,
        }
        self.erros.clear() if hasattr(self, "erros") else None

    def _tempo_medida(self):
        f = 3.0 if self.s["azer"] else 1.0
        n = max(1, len(self.s["funcs"]))
        sobre = 0.0012 + (0.0006 if self.s["display"] else 0.0)
        return n * self.s["nplc"] / 60.0 * f + sobre

    def _executar(self, cmd):
        if not cmd:
            return
        c = cmd.upper()
        partes = c.split(None, 1)
        h = partes[0]
        arg = partes[1].strip() if len(partes) > 1 else ""
        if not h.startswith(":") and not h.startswith("*"):
            h = ":" + h
        s = self.s

        def num(x=arg):
            return float(x.split(",")[0])

        if h == "*IDN?":
            self._responder("KEITHLEY INSTRUMENTS INC.,MODEL 2400,SIMULADO,C32 (Open-IV)")
        elif h == "*RST":
            self.reset(); s = self.s
        elif h in ("*CLS",):
            self.erros.clear()
        elif h == "*OPC?":
            self._responder("1")
        elif h.startswith(":SYST:ERR"):
            self._responder(self.erros.popleft() if self.erros else '0,"No error"')
        elif h == ":SYST:LFR?":
            self._responder("60")
        elif h == ":SYST:TIME:RES":
            s["t0"] = max(self.t, self._inicio_cmd)
        elif h.startswith(":SYST:AZER"):
            s["azer"] = arg in ("ON", "1", "ONCE") and arg != "ONCE"
        elif h.startswith(":DISP:ENAB"):
            s["display"] = arg in ("ON", "1")
        elif h == ":OUTP" or h == ":OUTP:STAT":
            liga = arg in ("ON", "1")
            if liga and not s["saida"] and hasattr(self.dev, "registrar_degrau"):
                self.dev.registrar_degrau(self.t, s["lev"]["VOLT"] if s["func"] == "VOLT" else 0)
            s["saida"] = liga
        elif h == ":SOUR:FUNC" or h == ":SOUR:FUNC:MODE":
            s["func"] = "CURR" if arg.startswith("CURR") else "VOLT"
        elif h in (":SOUR:VOLT:MODE", ":SOUR:CURR:MODE"):
            f = "VOLT" if "VOLT" in h else "CURR"
            s["modo"][f] = "LIST" if arg.startswith("LIST") else ("SWE" if arg.startswith("SWE") else "FIX")
        elif h in (":SOUR:VOLT:LEV", ":SOUR:VOLT", ":SOUR:CURR:LEV", ":SOUR:CURR"):
            f = "VOLT" if "VOLT" in h else "CURR"
            s["lev"][f] = num()
            if f == "VOLT" and s["saida"] and hasattr(self.dev, "registrar_degrau"):
                self.dev.registrar_degrau(self.t, s["lev"]["VOLT"])
        elif h in (":SOUR:LIST:VOLT", ":SOUR:LIST:CURR", ":SOUR:LIST:VOLT:APP", ":SOUR:LIST:CURR:APP"):
            f = "VOLT" if "VOLT" in h else "CURR"
            vals = [float(x) for x in arg.split(",")]
            if len(vals) > 100:          # como no 2400 real: comando rejeitado
                self._erro('-223,"Too much data"')
            elif h.endswith(":APP"):
                if len(s["lista"][f]) + len(vals) > 2500:
                    self._erro('-223,"Too much data"')
                else:
                    s["lista"][f] += vals
            else:
                s["lista"][f] = vals
        elif h in (":SOUR:LIST:VOLT:POIN?", ":SOUR:LIST:CURR:POIN?"):
            self._responder(str(len(s["lista"]["VOLT" if "VOLT" in h else "CURR"])))
        elif h == ":INIT":
            self._ler(devolver=False)
        elif h == ":SOUR:DEL?":
            self._responder(f"{s['sdel']:+.6E}")
        elif h == ":TRIG:COUN?":
            self._responder(f"{s['tcoun']:+d}")
        elif h in (":SOUR:VOLT:MODE?", ":SOUR:CURR:MODE?"):
            self._responder(s["modo"]["VOLT" if "VOLT" in h else "CURR"])
        elif h == ":SOUR:DEL":
            s["sdel"] = num()
        elif h == ":TRIG:DEL":
            s["tdel"] = num()
        elif h == ":TRIG:COUN":
            s["tcoun"] = int(num())
        elif h.endswith(":NPLC"):
            s["nplc"] = num()
        elif h == ":SENS:CURR:PROT":
            s["iprot"] = num()
        elif h == ":SENS:VOLT:PROT":
            s["vprot"] = num()
        elif h == ":SENS:FUNC:OFF:ALL":
            s["funcs"] = []
        elif h == ":SENS:FUNC:ON":
            s["funcs"] = [x.strip().strip('"') for x in arg.split(",")]
        elif h == ":FORM:ELEM":
            s["elems"] = [x.strip() for x in arg.split(",")]
        elif h == ":READ?":
            self._ler()
        else:
            pass  # demais comandos: aceitos sem efeito no modelo

    def _ler(self, devolver=True):
        s = self.s
        # a varredura so comeca quando o interpretador chega ao :READ?/:INIT
        self._avancar(self._inicio_cmd - self.t)
        try:
            self._ler_lista(s, devolver)
        finally:
            self._ocupado_ate = max(self._ocupado_ate, self.t)
        if self._prontos:
            self._prontos[-1] = max(self._prontos[-1], self.t)

    def _ler_lista(self, s, devolver):
        if not s["saida"]:
            self._erro('803,"Output disabled"')
            self._responder("")
            return
        f = s["func"]
        if s["modo"][f] == "LIST":
            niveis = list(s["lista"][f])
            n = s["tcoun"]
            niveis = [niveis[k % len(niveis)] for k in range(n)]
        else:
            niveis = [s["lev"][f]] * s["tcoun"]
        tm = self._tempo_medida()
        vals = []
        for lv in niveis:
            self._avancar(s["tdel"])
            if f == "VOLT":
                self._em_lista = lv
                if hasattr(self.dev, "registrar_degrau"):
                    self.dev.registrar_degrau(self.t, lv)
            sd = s["sdel"]
            if self.atraso_minimo and 0 < sd < self.atraso_minimo:
                sd = self.atraso_minimo          # hipotese do 2400 real: atraso pequeno arredonda para cima
            self._avancar(sd)
            ts = self.t - s["t0"]
            if self.tick:
                ts = math.floor(ts / self.tick) * self.tick   # relogio de 1024 Hz
            stat = 0
            if f == "VOLT":
                i = self.dev.corrente(lv, self.t)
                if self.ruido:
                    i += self.rng.normal(0, 2e-12 / math.sqrt(max(s["nplc"], 0.01))) + i * self.rng.normal(0, 0.0003)
                if abs(i) > s["iprot"]:
                    i = math.copysign(s["iprot"], i)
                    stat |= 8
                v = lv
            else:
                voc, rint = self.dev.voc()
                v = voc + lv * rint
                if self.ruido:
                    v += self.rng.normal(0, 2e-5)
                i = lv
                if abs(v) > s["vprot"]:
                    v = math.copysign(s["vprot"], v)
                    stat |= 8
            self._avancar(tm)
            for e in s["elems"]:
                if e == "VOLT":
                    vals.append(v)
                elif e == "CURR":
                    vals.append(i)
                elif e == "TIME":
                    vals.append(ts)
                elif e == "STAT":
                    vals.append(float(stat))
        # depois da lista o instrumento volta ao bias (nivel programado em FIX)
        self._em_lista = None
        if f == "VOLT" and hasattr(self.dev, "registrar_degrau"):
            self.dev.registrar_degrau(self.t, s["lev"]["VOLT"])
        if devolver:
            self._responder(",".join(f"{x:+.6E}" for x in vals))
