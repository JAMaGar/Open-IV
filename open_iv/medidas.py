"""
Motor de medidas do Open-IV (independente da interface grafica).

Primitivas (todas temporizadas pelo 2400, ver keithley.py):
    varrer()  - laco/varredura de vertices arbitrarios (lista de ate 2500 pontos)
    ler()     - leitura DC: N amostras em V_leitura por t_on, media do ultimo trecho
    pulso()   - pulso [V_base, V_pulso, V_base] com largura real pelos carimbos de tempo
Experimentos (um por guia da campanha) montados com as primitivas:
    exp_iv, exp_leitura, exp_multinivel, exp_pulsos, exp_sinapse, exp_ciclos,
    exp_retencao, exp_transiente, exp_jv, exp_diodo, exp_estabilidade
Cada experimento entrega objetos Arquivo (colunas + linhas + metadados + resumo)
ao contexto, que os grava.
"""
import math
import random
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from . import analise as an
from .arquivos import tag_v, tag_num


class Cancelado(Exception):
    pass


@dataclass
class Arquivo:
    etapa: str
    param: str
    colunas: list
    linhas: list
    meta: dict = field(default_factory=dict)
    resumo: dict = field(default_factory=dict)
    tipo: str = ""


class Contexto:
    """Liga o motor a interface: parada, log, progresso, pontos e arquivos."""

    def __init__(self, k, log=None, progresso=None, ao_ponto=None, ao_arquivo=None,
                 ao_parcial=None):
        self.k = k
        self.parar = threading.Event()
        self._log = log
        self._prog = progresso
        self._ponto = ao_ponto
        self._arq = ao_arquivo
        self._parcial = ao_parcial
        self.evento_pendente = ""
        self._t_parcial = 0.0
        # estimativas de tempo lidas pela interface (atribuicoes simples, seguras entre threads)
        self.t_inicio = time.perf_counter()
        self.t_total_est = None       # duracao total estimada da medida (s)
        self.lista_ini = None         # perf_counter do inicio da lista em execucao no 2400
        self.lista_est = None         # duracao estimada dessa lista (s)
        self.frac = 0.0
        self.etapa_txt = ""

    def log(self, msg, tag="info"):
        if self._log:
            self._log(msg, tag)

    def checar(self):
        if self.parar.is_set():
            raise Cancelado()

    def esperar(self, s):
        fim = time.perf_counter() + max(0.0, s)
        while True:
            self.checar()
            falta = fim - time.perf_counter()
            if falta <= 0:
                return
            time.sleep(min(0.05, falta))

    def esperar_ate(self, t_pc):
        self.esperar(t_pc - time.perf_counter())

    def progresso(self, frac, txt=""):
        self.frac = max(0.0, min(1.0, frac))
        self.etapa_txt = txt
        if self._prog:
            self._prog(self.frac, txt)

    def total(self, segundos):
        """Duracao total estimada (s); a interface usa para o tempo restante."""
        self.t_total_est = max(0.1, float(segundos))
        self.t_inicio = time.perf_counter()

    def ponto(self, d):
        if self._ponto:
            self._ponto(d)

    def arquivo(self, arq):
        if self._arq:
            self._arq(arq)

    def parcial(self, arq, intervalo=30.0):
        """Copia de seguranca periodica (para medidas longas)."""
        agora = time.perf_counter()
        if self._parcial and agora - self._t_parcial >= intervalo:
            self._t_parcial = agora
            self._parcial(arq)

    def pegar_evento(self):
        e, self.evento_pendente = self.evento_pendente, ""
        return e


# ============================================================ formas de onda
def pontos_varredura(vertices, passo):
    """Vertices [-5, 10, -5] e passo 0,1 -> niveis e indice do segmento."""
    vertices = [float(v) for v in vertices]
    passo = abs(float(passo))
    if len(vertices) < 2 or passo <= 0:
        raise ValueError("Informe ao menos 2 vertices e passo > 0.")
    V = [vertices[0]]
    seg = [0]
    for j in range(len(vertices) - 1):
        a, b = vertices[j], vertices[j + 1]
        n = max(1, int(round(abs(b - a) / passo)))
        for i in range(1, n + 1):
            V.append(round(a + (b - a) * i / n, 6))
            seg.append(j)
    return np.array(V), np.array(seg)


def parse_lista(txt, tipo=float):
    """'1; 2,5; 3' ou '1, 2.5, 3' -> [1.0, 2.5, 3.0] (aceita virgula decimal com ';')."""
    txt = (txt or "").strip()
    if not txt:
        return []
    if ";" in txt:
        itens = [x.strip().replace(",", ".") for x in txt.split(";")]
    else:
        itens = [x.strip() for x in txt.split(",")]
    return [tipo(float(x)) if tipo is int else tipo(x) for x in itens if x]


def tempos_log(t_max, por_decada=(1, 2, 5), t_min=1.0):
    out = []
    d = 10 ** math.floor(math.log10(t_min))
    while d <= t_max * 1.0001:
        for m in por_decada:
            t = m * d
            if t_min <= t <= t_max * 1.0001:
                out.append(float(t))
        d *= 10
    return out


# ============================================================ motor
class Motor:
    def __init__(self, ctx):
        self.ctx = ctx
        self.k = ctx.k
        self._off = None          # perf_counter - tempo do instrumento
        self._t0 = None           # referencia de tempo do arquivo (tempo do instrumento)
        self._base = 0.0          # tempo acumulado antes do ultimo :SYST:TIME:RES
        self.reset_timer_s = 50.0 # zera o relogio do 2400 a cada ~50 s
        self._off_longo = {}      # offset do regime 'atraso' (pulsos longos), por NPLC
        self._n_longo = {}

    # ---------------------------------------------------------------- relogios
    def _atualizar_offset(self, r):
        tm = self.k.tempo_medida(self.k._nplc, self.k._az, self.k._nfunc)
        t_fim_inst = float(r["t"][-1]) + tm
        t_fim_pc = r["t_pc"] - r.get("t_tx", 0.0)
        self._off = t_fim_pc - t_fim_inst

    def inst_para_pc(self, t_inst):
        return t_inst + (self._off or 0.0)

    def agora_inst(self):
        return time.perf_counter() - (self._off or 0.0)

    def _zerar_relogio_se_preciso(self):
        """
        O 2400 devolve o carimbo de tempo em ASCII com ~7 algarismos: com o relogio em
        100 s a resolucao cai para 0,1 ms, em 1000 s para 1 ms. O relogio e zerado
        periodicamente e o tempo continuo e mantido aqui (self._base).
        """
        if self._off is None:
            self.k.write(":SYST:TIME:RES")
            self._base = 0.0
            return
        agora = self.agora_inst()
        if agora - self._base > self.reset_timer_s:
            self.k.write(":SYST:TIME:RES")
            self._base = agora + self.k.tempo_transmissao(16)

    def _est_lista(self, n, sd, trig_del=0.0):
        k = self.k
        ne = (4 if k._medir_v else 3) if k._modo == "V" else 3
        sd_ef = max(sd, 0.009) if 0 < sd < 0.009 else sd
        return n * (sd_ef + trig_del + k.tempo_medida(k._nplc, k._az, k._nfunc)) + k.tempo_transmissao(n * ne * 14) + 0.05

    def _lista(self, valores, sour_del, bias=0.0, func="VOLT", trig_del=0.0):
        self.ctx.checar()
        self._zerar_relogio_se_preciso()
        self.ctx.lista_est = self._est_lista(len(valores), sour_del, trig_del)
        self.ctx.lista_ini = time.perf_counter()
        try:
            r = self.k.executar_lista(list(valores), sour_del, trig_del=trig_del, bias=bias, func=func)
        finally:
            self.ctx.lista_ini = None
        r["t"] = r["t"] + self._base
        self._atualizar_offset(r)
        if self._t0 is None:
            self._t0 = float(r["t"][0])
        return r

    def rel(self, t):
        return np.asarray(t, dtype=float) - (self._t0 or 0.0)

    def iniciar(self):
        self._t0 = None
        self._off = None
        self._base = 0.0
        self.k.T0 = {}            # T0 e recalibrado no 1o pulso de cada medida
        self.k.inicio_medida()

    def finalizar(self):
        self.k.fim_medida(desligar_saida=True)

    # ---------------------------------------------------------------- estimativas de tempo
    def est_varredura(self, vertices, passo, atraso, nplc, medir_v=True, n_lacos=1):
        try:
            n = len(pontos_varredura(vertices, passo)[0]) * max(1, int(n_lacos))
        except Exception:
            return 0.0
        az = self.k.cfg["autozero"]
        nf = 2 if medir_v else 1
        sd = max(atraso, 0.009) if 0 < atraso < 0.009 else atraso
        tm = self.k.tempo_medida(nplc, az, nf)
        return n * (sd + tm) + self.k.tempo_transmissao(n * (nf + 2) * 14) + 0.3

    def est_leitura(self, t_on):
        return t_on + self.k.tempo_transmissao(10 * 3 * 14) + 0.1

    def est_pulso(self, w):
        k = min(self.MAX_PASSOS_PULSO, max(1, int(w / 0.001)))
        return w + 0.004 + self.k.tempo_transmissao((k + 2) * 3 * 14) + 0.1

    # ---------------------------------------------------------------- primitivas
    def varrer(self, vertices, passo, atraso, nplc, compliance, faixa_i="AUTO",
               medir_v=True, modo="hw", n_lacos=1, bias=0.0, ao_lote=None):
        V1, seg1 = pontos_varredura(vertices, passo)
        npt = len(V1)
        vmax = float(np.max(np.abs(V1)))
        self.k.config_fonte_v(compliance, nplc, faixa_i, medir_v, faixa_v=vmax)
        res = {k: [] for k in ("t", "Vset", "Vmed", "I", "comp", "laco", "seg")}

        def guardar(r, lacos, segs, Vp):
            res["t"] += list(r["t"]); res["Vset"] += list(Vp); res["Vmed"] += list(r["V"])
            res["I"] += list(r["I"]); res["comp"] += list(r["compliance"])
            res["laco"] += list(lacos); res["seg"] += list(segs)
            if ao_lote:
                ao_lote(r, lacos, segs)

        if modo == "hw":
            if npt > 2500:
                raise ValueError(f"O laco tem {npt} pontos; o limite do 2400 e 2500. Aumente o passo.")
            por_lista = max(1, min(n_lacos, 2500 // npt))
            j = 0
            while j < n_lacos:
                m = min(por_lista, n_lacos - j)
                Vp = np.tile(V1, m)
                lacos = np.repeat(np.arange(j + 1, j + m + 1), npt)
                segs = np.tile(seg1, m)
                est = len(Vp) * (atraso + self.k.tempo_medida(nplc, self.k._az, self.k._nfunc))
                self.ctx.log(f"Lista de {len(Vp)} pontos (~{est:.1f} s no instrumento + transferencia)")
                r = self._lista(Vp, atraso, bias=bias)
                guardar(r, lacos, segs, Vp)
                j += m
                self.ctx.progresso(j / n_lacos, f"laco {j}/{n_lacos}")
        else:  # ponto a ponto: grafico ao vivo, temporizacao limitada pela serial
            self.k.atraso_fonte(atraso)
            total = npt * n_lacos
            c = 0
            for j in range(n_lacos):
                for v, s in zip(V1, seg1):
                    self.ctx.checar()
                    r = self.k.ponto_fixo(float(v))
                    r["t"] = r["t"] + self._base
                    self._atualizar_offset(r)
                    if self._t0 is None:
                        self._t0 = float(r["t"][0])
                    guardar(r, [j + 1], [int(s)], [float(v)])
                    c += 1
                    if c % 5 == 0:
                        self.ctx.progresso(c / total, f"{c}/{total}")
            self.k.nivel(bias)
        return {k: np.asarray(v) for k, v in res.items()}

    def config_leitura(self, V, nplc, compliance, faixa_i="AUTO", bias=0.0, autozero=None):
        """Configura a leitura (pode ser chamado antes de esperar o instante da leitura)."""
        az = self.k.cfg["autozero"] if autozero is None else autozero
        self.k.config_fonte_v(compliance, nplc, faixa_i, medir_v=False, autozero=az,
                              faixa_v=max(abs(V), abs(bias), 0.2))
        return az

    def ler(self, V, t_on, media, nplc, compliance, faixa_i="AUTO", n_amostras=10,
            bias=0.0, autozero=None):
        az = self.config_leitura(V, nplc, compliance, faixa_i, bias, autozero)
        tm = self.k.tempo_medida(nplc, az, 1)
        N = int(max(1, min(n_amostras, math.floor(t_on / tm)))) if t_on > tm else 1
        sd = max(0.0, t_on / N - tm)
        r = self._lista([V] * N, sd, bias=bias)
        t, I = r["t"], r["I"]
        if 0 < media < t_on and N > 1:
            sel = t >= (t[-1] - media + 0.5 * (t[1] - t[0]) - 1e-9)
            if not np.any(sel):
                sel = np.ones_like(t, bool)
        else:
            sel = np.ones_like(t, bool)
        per = float(np.median(np.diff(t))) if N > 1 else sd + tm
        return {"V": V, "I": float(np.nanmean(I[sel])), "I_std": float(np.nanstd(I[sel])),
                "n": int(np.sum(sel)), "t_ini": float(t[0] - sd), "t_fim": float(t[-1] - sd + per),
                "t_on_real": float(per * N), "comp": bool(np.any(r["compliance"])), "r": r}

    # ---------------------------------------------------------------- pulsos
    RESOLUCAO_CARIMBO = 1.0 / 1024     # relogio do 2400: 1024 Hz (observado em 12/11/2026)
    MAX_PASSOS_PULSO = 60              # ate ~60 ms o pulso e feito com k passos sem atraso

    def calibrar_T0(self, nplc=0.01, base=0.0, compliance=0.01, faixa_i=None, n=60):
        """
        Periodo de um passo da lista com atraso de fonte = 0 (T0), medido em n passos
        no nivel de base: T0 = (t[n-1] - t[0]) / (n - 1), resolucao ~0,98 ms / (n - 1).
        So aplica V_base, entao pode ser feito com a amostra ligada.
        """
        self.k.config_fonte_v(compliance, nplc, faixa_i or compliance, medir_v=False, autozero=False,
                              faixa_v=max(abs(base), 0.2))
        r = self._lista([base] * n, 0.0, bias=base)
        T0 = float((r["t"][-1] - r["t"][0]) / (n - 1))
        self.k.T0[nplc] = T0
        self.k.sobrecarga_s = max(0.0, T0 - nplc / self.k.lfr)
        self.ctx.log(f"T0 (passo sem atraso, NPLC {nplc:g}) = {T0*1e3:.3f} ms", "info")
        return T0

    def pulso(self, Vw, largura, base=0.0, nplc=0.01, compliance=0.01, faixa_i=None,
              auto_corrigir=True):
        """
        Pulso temporizado pelo 2400.
          largura <= MAX_PASSOS x T0: lista [base, Vw x k, base] com atraso 0; largura = k x T0
          largura maior: lista [base, Vw, base] com atraso = largura - offset (offset medido)
        Retorna W_cal (largura pela calibracao, resolucao ~T0) e W_real (carimbos, +-0,98 ms).
        """
        faixa = faixa_i if faixa_i else compliance
        T0 = self.k.T0.get(nplc) or self.calibrar_T0(nplc, base, compliance, faixa)
        self.k.config_fonte_v(compliance, nplc, faixa, medir_v=False, autozero=False,
                              faixa_v=max(abs(Vw), abs(base), 0.2))
        aviso = ""
        if largura <= self.MAX_PASSOS_PULSO * T0 + 0.5 * T0:
            k = max(1, int(round(largura / T0)))
            sd = 0.0
            W_cal = k * T0
            if largura < 0.5 * T0:
                aviso = f"largura pedida {largura*1e3:.3g} ms < minima ({T0*1e3:.2f} ms com NPLC {nplc:g})"
            regime = "passos"
        else:
            k = 1
            off = self._off_longo.get(nplc, T0 + 0.001)
            sd = max(0.0, largura - off)
            W_cal = sd + off
            regime = "atraso"
        lista = [base] + [Vw] * k + [base]
        r = self._lista(lista, sd, bias=base)
        t = r["t"]
        W = float(t[k + 1] - t[1])
        if regime == "atraso" and auto_corrigir and np.isfinite(W):
            # media acumulada (o erro de quantizacao do carimbo se cancela na media)
            n_, m_ = self._n_longo.get(nplc, 0), self._off_longo.get(nplc, T0 + 0.001)
            obs = W - sd
            if 0 < obs < 0.05:
                self._n_longo[nplc] = n_ + 1
                self._off_longo[nplc] = m_ + (obs - m_) / (n_ + 1)
        Ip = r["I"][1:k + 1]
        Iw = float(np.nanmean(Ip[len(Ip) // 2:])) if len(Ip) else float("nan")
        return {"W_real": W, "W_cal": float(W_cal), "k": k, "regime": regime, "I_pulso": Iw,
                "comp": bool(np.any(r["compliance"][1:k + 1])),
                "t_ini": float(t[1] - sd), "t_fim": float(t[k + 1] - sd), "sour_del": sd, "aviso": aviso}

    def trem_osciloscopio(self, V=1.0, largura=0.01, periodo=0.05, duracao=20.0, nplc=0.01, compliance=0.01):
        """
        Trem continuo de pulsos para ver no osciloscopio (use um RESISTOR): pulsos de
        k x T0 com periodo (k + m) x T0, repetidos ate preencher listas de ate 2500 passos,
        executadas com :INIT (sem devolver dados) uma apos a outra ate 'duracao'.
        O osciloscopio em disparo NORMAL fica redesenhando o pulso; a medida automatica de
        largura (+Width) do osciloscopio da a media. Retorna a largura e o periodo esperados.
        """
        self.iniciar()
        try:
            T0 = self.calibrar_T0(nplc, 0.0, compliance, compliance)
            k = max(1, int(round(largura / T0)))
            m = max(1, int(round(periodo / T0)) - k)
            padrao = [V] * k + [0.0] * m
            if len(padrao) > 2500:
                raise ValueError(f"Periodo longo demais para o modo de passos (max ~{2500 * T0:.2f} s).")
            lista = padrao * max(1, 2500 // len(padrao))
            self.k.config_fonte_v(compliance, nplc, compliance, medir_v=False, autozero=False,
                                  faixa_v=max(abs(V), 0.2))
            self.ctx.log(f"Trem para osciloscopio: largura esperada {k * T0 * 1e3:.3f} ms (k = {k}), "
                         f"periodo {(k + m) * T0 * 1e3:.3f} ms, {len(lista) // len(padrao)} pulsos por lista "
                         f"({len(lista) * T0:.2f} s); entre listas ha uma pausa extra a 0 V.", "info")
            self.ctx.total(duracao)
            t_fim = time.perf_counter() + duracao
            n = 0
            while time.perf_counter() < t_fim:
                self.ctx.checar()
                self.k.executar_lista(lista, 0.0, bias=0.0, ler_dados=False)
                n += 1
                self.ctx.progresso(1 - max(0.0, t_fim - time.perf_counter()) / duracao, f"trem: lista {n}")
            self.ctx.log(f"Trem concluido: {n} listas, ~{n * (len(lista) // len(padrao))} pulsos.", "info")
            return k * T0, (k + m) * T0
        finally:
            self.finalizar()

    def diag_atraso(self, V=1.0, nplc=0.01, atrasos_ms=(0, 0.1, 0.2, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30, 50, 100),
                    compliance=0.01):
        """
        Periodo real do passo da lista em funcao do atraso de fonte, com o nivel
        constante e alternando 0/V (como num pulso). Use um RESISTOR ou a ponta levantada.
        """
        linhas = []
        self.iniciar()
        try:
            self.k.config_fonte_v(compliance, nplc, compliance, medir_v=False, autozero=False,
                                  faixa_v=max(abs(V), 0.2))
            for j, d in enumerate(atrasos_ms, 1):
                sd = d / 1e3
                n = int(min(200, max(20, round(0.4 / (sd + 0.001)))))
                n += n % 2
                res = {}
                for rot, lista in (("const", [0.0] * n), ("alt", [0.0, V] * (n // 2))):
                    r = self._lista(lista, sd, bias=0.0)
                    dt = np.diff(r["t"])
                    res[rot] = (float((r["t"][-1] - r["t"][0]) / (n - 1)), float(dt.min()), float(dt.max()))
                ln = {"atraso_ms": d, "n_passos": n,
                      "T_const_ms": res["const"][0] * 1e3, "T_alt_ms": res["alt"][0] * 1e3,
                      "excesso_alt_ms": (res["alt"][0] - sd) * 1e3,
                      "dt_min_alt_ms": res["alt"][1] * 1e3, "dt_max_alt_ms": res["alt"][2] * 1e3}
                linhas.append(ln)
                self.ctx.ponto(ln)
                self.ctx.progresso(j / len(atrasos_ms), f"atraso {d:g} ms")
                self.ctx.log(f"atraso {d:7.2f} ms -> passo {ln['T_const_ms']:8.3f} ms (constante) | "
                             f"{ln['T_alt_ms']:8.3f} ms (alternando 0/{V:g} V)", "rx")
        finally:
            self.finalizar()
        self.ctx.arquivo(Arquivo("DIAG", "atraso_fonte", _cols(linhas), linhas,
                                 {"V": V, "NPLC": nplc, "compliance_A": compliance}, {}, "diag"))
        return linhas

    # ---------------------------------------------------------------- utilitarios
    @staticmethod
    def _sem_zero(I):
        return I if I not in (0, 0.0) and np.isfinite(I) else float("nan")

    def _linhas_iv(self, d, mask=None):
        m = np.ones(len(d["t"]), bool) if mask is None else mask
        t = self.rel(d["t"])
        return [{"t_s": t[i], "V_set_V": d["Vset"][i], "V_med_V": d["Vmed"][i],
                 "I_A": d["I"][i], "compliance_flag": int(d["comp"][i]),
                 "laco": int(d["laco"][i]), "segmento": int(d["seg"][i])}
                for i in np.where(m)[0]]

    # ================================================================ EXPERIMENTOS
    # ---------------------------------------------------------------- G04/G06/G07: I-V
    def exp_iv(self, p):
        """
        p: vertices, passo, atraso, nplc, compliance, faixa_i, medir_v, modo,
           n_lacos, etapa, rotulo ('L'), atrasos (lista opcional, G06), aleatorio, V_ba
        """
        atrasos = p.get("atrasos") or [p["atraso"]]
        if p.get("aleatorio") and len(atrasos) > 1:
            atrasos = random.sample(atrasos, len(atrasos))
            self.ctx.log("Ordem sorteada dos atrasos: " + ", ".join(f"{a:g}" for a in atrasos))
        serie = len(p.get("atrasos") or []) > 0
        self.ctx.total(sum(self.est_varredura(p["vertices"], p["passo"], a, p["nplc"], p.get("medir_v", True),
                                              int(p.get("n_lacos", 1))) for a in atrasos))
        self.iniciar()
        try:
            for ia, atr in enumerate(atrasos):
                self.ctx.log(f"Varredura {p['vertices']} V, passo {p['passo']} V, atraso {atr} s")

                def lote(r, lacos, segs):
                    for v, i in zip(r["V"], r["I"]):
                        self.ctx.ponto({"V": float(v), "I": float(i), "laco": int(lacos[0]), "serie": ia})

                d = self.varrer(p["vertices"], p["passo"], atr, p["nplc"], p["compliance"],
                                p.get("faixa_i", "AUTO"), p.get("medir_v", True), p.get("modo", "hw"),
                                int(p.get("n_lacos", 1)), ao_lote=lote)
                for L in range(1, int(p.get("n_lacos", 1)) + 1):
                    m = d["laco"] == L
                    linhas = self._linhas_iv(d, m)
                    rs = an.resumo_laco(d["Vmed"][m], d["I"][m], d["t"][m], d["comp"][m],
                                        V_ba=p.get("V_ba", (0.5, 1, 2, 3, 4, -1)))
                    rot = f"{p.get('rotulo', 'L')}{L}"
                    if serie:
                        par = f"R{tag_num(atr)}_{rot}"
                    elif int(p.get("n_lacos", 1)) > 1:
                        par = f"{p['param']}-{rot}" if p.get("param") else rot
                    else:
                        par = p.get("param") or rot
                    meta = {"vertices_V": p["vertices"], "passo_V": p["passo"], "atraso_s": atr,
                            "NPLC": p["nplc"], "compliance_A": p["compliance"],
                            "faixa_I": p.get("faixa_i", "AUTO"), "modo_temporizacao": p.get("modo", "hw"),
                            "laco": L, "n_lacos_seguidos": p.get("n_lacos", 1)}
                    self.ctx.arquivo(Arquivo(p["etapa"], par, ["t_s", "V_set_V", "V_med_V", "I_A",
                                             "compliance_flag", "laco", "segmento"], linhas, meta, rs, "iv"))
                    self.ctx.log("  " + "; ".join(f"{k}={v:.3g}" if isinstance(v, float) else f"{k}={v}"
                                                  for k, v in rs.items()))
        finally:
            self.finalizar()

    # ---------------------------------------------------------------- leitura (G05/G09)
    def exp_leitura(self, p):
        """p: V_leitura (lista), t_on, media, nplc, compliance, repeticoes, intervalo, etapa, param."""
        linhas = []
        tot = len(p["V_leitura"]) * int(p.get("repeticoes", 1))
        self.ctx.total(tot * (self.est_leitura(p["t_on"]) + p.get("intervalo", 0)))
        self.iniciar()
        try:
            n = 0
            for rep in range(int(p.get("repeticoes", 1))):
                for V in p["V_leitura"]:
                    L = self.ler(V, p["t_on"], p["media"], p["nplc"], p["compliance"],
                                 p.get("faixa_i", "AUTO"), int(p.get("n_amostras", 10)))
                    n += 1
                    ln = {"n": n, "t_s": float(self.rel(L["t_ini"])), "V_read_V": V, "I_A": L["I"],
                          "I_std_A": L["I_std"], "n_amostras": L["n"], "t_on_real_s": L["t_on_real"],
                          "compliance_flag": int(L["comp"])}
                    linhas.append(ln)
                    self.ctx.ponto(ln)
                    self.ctx.log(f"Leitura {V:+g} V: I = {L['I']:.4e} A (sd {L['I_std']:.1e}, n={L['n']})", "rx")
                    self.ctx.progresso(n / tot, f"{n}/{tot}")
                    if p.get("intervalo", 0) > 0:
                        self.ctx.esperar(p["intervalo"])
        finally:
            self.finalizar()
            meta = {k: p[k] for k in ("V_leitura", "t_on", "media", "nplc", "compliance") if k in p}
            if linhas:
                self.ctx.arquivo(Arquivo(p["etapa"], p.get("param", "RD"), _cols(linhas), linhas, meta, {}, "leitura"))

    def _leituras(self, p, rotulo, extra, linhas):
        out = []
        for V in p["V_leitura"]:
            L = self.ler(V, p["t_on"], p["media"], p.get("nplc_leitura", p["nplc"]), p["compliance"],
                         p.get("faixa_i", "AUTO"), int(p.get("n_amostras", 10)))
            ln = dict(extra)
            ln.update({"etapa": rotulo, "t_s": float(self.rel(L["t_ini"])), "V_read_V": V,
                       "I_A": L["I"], "I_std_A": L["I_std"], "compliance_flag": int(L["comp"])})
            linhas.append(ln)
            out.append(L)
            self.ctx.ponto(ln)
        return out

    # ---------------------------------------------------------------- G05 multinivel
    def exp_multinivel(self, p):
        """
        p: modo ('Vmax'|'compliance'|'Vreset'), valores, repeticoes, aleatorio,
           v_reset (vertices), v_set (vertices), passo, atraso, nplc, compliance,
           V_leitura, t_on, media, etapa
        """
        modo = p["modo"]
        resumo_l, curvas = [], []
        nl = len(p["V_leitura"])
        t_it = []
        for x in p["valores"]:
            v1 = p["v_set"] if modo == "Vreset" else p["v_reset"]
            v2 = [0.0, x, 0.0] if modo in ("Vmax", "Vreset") else p["v_set"]
            t_it.append(self.est_varredura(v1, p["passo"], p["atraso"], p["nplc"]) +
                        self.est_varredura(v2, p["passo"], p["atraso"], p["nplc"]) + 2 * nl * self.est_leitura(p["t_on"]))
        self.ctx.total(int(p.get("repeticoes", 1)) * sum(t_it))
        self.iniciar()
        try:
            reps = int(p.get("repeticoes", 1))
            tot = reps * len(p["valores"])
            c = 0
            for rep in range(1, reps + 1):
                vals = list(p["valores"])
                if p.get("aleatorio"):
                    random.shuffle(vals)
                self.ctx.log(f"Repeticao {rep}: ordem {vals}")
                for ordem, x in enumerate(vals, 1):
                    base = {"rep": rep, "ordem": ordem, "valor": x}

                    def curva(vert, compl, rot):
                        d = self.varrer(vert, p["passo"], p["atraso"], p["nplc"], compl,
                                        p.get("faixa_i", "AUTO"), True, "hw", 1)
                        for ln in self._linhas_iv(d):
                            ln.update(base); ln["etapa"] = rot
                            curvas.append(ln)
                        for v, i in zip(d["Vmed"], d["I"]):
                            self.ctx.ponto({"V": float(v), "I": float(i), "curva": rot, "valor": x})

                    if modo == "Vmax":
                        curva(p["v_reset"], p["compliance"], "RESET")
                        self._leituras(p, "RD-pre", base, resumo_l)
                        curva([0.0, x, 0.0], p["compliance"], f"W{tag_num(x)}")
                        self._leituras(p, "RD-pos", base, resumo_l)
                    elif modo == "compliance":
                        curva(p["v_reset"], p["compliance"], "RESET")
                        self._leituras(p, "RD-pre", base, resumo_l)
                        curva(p["v_set"], x, f"C{tag_num(x * 1e3)}mA")
                        self._leituras(p, "RD-pos", base, resumo_l)
                    else:  # Vreset
                        curva(p["v_set"], p["compliance"], "SET")
                        self._leituras(p, "RD-pre", base, resumo_l)
                        curva([0.0, x, 0.0], p["compliance"], f"R{tag_v(x, '')}")
                        self._leituras(p, "RD-pos", base, resumo_l)
                    c += 1
                    self.ctx.progresso(c / tot, f"{c}/{tot}")
                    self.ctx.parcial(Arquivo(p["etapa"], "serie", _cols(resumo_l), resumo_l, {}, {}, "multinivel"))
        finally:
            self.finalizar()
            meta = {k: p.get(k) for k in ("modo", "valores", "repeticoes", "v_reset", "v_set", "passo",
                                         "atraso", "nplc", "compliance", "V_leitura", "t_on", "media")}
            if resumo_l:
                self.ctx.arquivo(Arquivo(p["etapa"], f"{modo}-serie", _cols(resumo_l), resumo_l, meta, {}, "multinivel"))
            if curvas:
                self.ctx.arquivo(Arquivo(p["etapa"], f"{modo}-curvas", _cols(curvas), curvas, meta, {}, "iv"))

    # ---------------------------------------------------------------- pulso + leitura
    def _pulso_leitura(self, Vw, w, p, n, extra):
        P = self.pulso(Vw, w, p.get("base", 0.0), p.get("nplc_pulso", 0.01), p["compliance"],
                       p.get("faixa_pulso"), p.get("auto_corrigir", True))
        if P["aviso"]:
            self.ctx.log("AVISO: " + P["aviso"], "warn")
        L = self.ler(p["V_read"], p["t_read"], p["media_read"], p["nplc_read"], p["compliance"],
                     p.get("faixa_i", "AUTO"), int(p.get("n_amostras", 10)), bias=p.get("base", 0.0))
        G = abs(L["I"] / p["V_read"]) if p["V_read"] else float("nan")
        R = 1.0 / G if G > 0 else float("nan")
        ln = dict(extra)
        ln.update({"n": n, "V_write_V": Vw, "w_nominal_ms": w * 1e3, "t_write_real_ms": P["W_real"] * 1e3,
                   "w_calibrada_ms": P["W_cal"] * 1e3, "passos_pulso": P["k"],
                   "I_write_A": P["I_pulso"], "atraso_leitura_ms": (L["t_ini"] - P["t_fim"]) * 1e3,
                   "V_read_V": p["V_read"], "I_read_A": L["I"], "R_ohm": R, "G_S": G,
                   "t_s": float(self.rel(P["t_ini"])), "compliance_flag": int(P["comp"] or L["comp"])})
        self.ctx.ponto(ln)
        return ln, P

    def _resumo_larguras(self, linhas):
        linhas = [l for l in linhas if l.get("w_nominal_ms", 0) > 0]
        if not linhas:
            return {}
        w = np.array([l["t_write_real_ms"] for l in linhas], float)
        wc = np.array([l.get("w_calibrada_ms", np.nan) for l in linhas], float)
        wn = np.array([l["w_nominal_ms"] for l in linhas], float)
        a = np.array([l["atraso_leitura_ms"] for l in linhas], float)
        return {"largura_calibrada_mediana_ms": float(np.nanmedian(wc)),
                "erro_largura_calibrada_max_ms": float(np.nanmax(np.abs(wc - wn))),
                "largura_carimbo_media_ms": float(np.nanmean(w)),
                "resolucao_carimbo_ms": self.RESOLUCAO_CARIMBO * 1e3,
                "T0_ms": float(np.nanmin(wc / np.maximum(1, [l.get("passos_pulso", 1) for l in linhas]))) if len(wc) else float("nan"),
                "atraso_leitura_mediano_ms": float(np.nanmedian(a))}

    # ---------------------------------------------------------------- G10 pulsos
    def exp_pulsos(self, p):
        """
        p: modo ('SET','RESET','Alternado','Amplitudes','Larguras'), V_set, V_reset, w_set,
           w_reset, amplitudes, larguras, V_fixo, n_pulsos, V_read, t_read, media_read,
           nplc_read, base, nplc_pulso, compliance, periodo, aleatorio, reset_ref, etapa, param
        """
        modo = p["modo"]
        n_p = int(p.get("n_pulsos", 10))
        if modo == "SET":
            series = [("SET", [(p["V_set"], p["w_set"])] * n_p)]
        elif modo == "RESET":
            series = [("RESET", [(p["V_reset"], p["w_reset"])] * n_p)]
        elif modo == "Alternado":
            seq = []
            for i in range(n_p):
                seq.append((p["V_set"], p["w_set"]) if i % 2 == 0 else (p["V_reset"], p["w_reset"]))
            series = [("ALT", seq)]
        elif modo == "Amplitudes":
            amps = list(p["amplitudes"])
            if p.get("aleatorio"):
                random.shuffle(amps)
            series = [(tag_v(a), [(a, p["w_fixo"])] * n_p) for a in amps]
        else:  # Larguras
            ws = list(p["larguras"])
            if p.get("aleatorio"):
                random.shuffle(ws)
            series = [(f"w{tag_num(w * 1e3)}ms", [(p["V_fixo"], w)] * n_p) for w in ws]
        linhas = []
        tot = sum(len(s[1]) for s in series)
        n = 0
        t_ref = self.est_varredura(p["reset_ref"], p.get("passo_ref", 0.1), p.get("atraso_ref", 0.1),
                                   p.get("nplc_ref", 1)) if p.get("reset_ref") else 0.0
        self.ctx.total(sum(t_ref + self.est_leitura(p["t_read"]) +
                           sum(max(self.est_pulso(w) + self.est_leitura(p["t_read"]), p.get("periodo", 0))
                               for _, w in seq) for _, seq in series))
        self.iniciar()
        try:
            for nome, seq in series:
                if p.get("reset_ref"):
                    self.ctx.log(f"Serie {nome}: RESET de referencia {p['reset_ref']}")
                    self.varrer(p["reset_ref"], p.get("passo_ref", 0.1), p.get("atraso_ref", 0.1),
                                p.get("nplc_ref", 1), p["compliance"], "AUTO", True, "hw", 1)
                if p.get("leitura_inicial", True):
                    L = self.ler(p["V_read"], p["t_read"], p["media_read"], p["nplc_read"], p["compliance"])
                    ln = {"serie": nome, "n": 0, "V_write_V": 0.0, "w_nominal_ms": 0.0, "t_write_real_ms": 0.0,
                          "I_write_A": float("nan"), "atraso_leitura_ms": float("nan"), "V_read_V": p["V_read"],
                          "I_read_A": L["I"], "R_ohm": abs(p["V_read"] / L["I"]) if L["I"] else float("nan"),
                          "G_S": abs(L["I"] / p["V_read"]), "t_s": float(self.rel(L["t_ini"])),
                          "compliance_flag": int(L["comp"])}
                    linhas.append(ln); self.ctx.ponto(ln)
                t_ult = None
                for (Vw, w) in seq:
                    if p.get("periodo", 0) > 0 and t_ult is not None:
                        self.ctx.esperar_ate(self.inst_para_pc(t_ult + p["periodo"]) - 0.02)
                    n += 1
                    ln, P = self._pulso_leitura(Vw, w, p, n, {"serie": nome})
                    t_ult = P["t_ini"]
                    linhas.append(ln)
                    self.ctx.progresso(n / tot, f"pulso {n}/{tot}")
                    if n % 10 == 0 or n == 1:
                        self.ctx.log(f"Pulso {n}: {Vw:+g} V, w nominal {w*1e3:.3g} ms, calibrada {P['W_cal']*1e3:.3f} ms "
                                     f"({P['k']} passo(s)), carimbos {P['W_real']*1e3:.2f} ms; "
                                     f"I_read = {ln['I_read_A']:.3e} A", "rx")
                    self.ctx.parcial(Arquivo(p["etapa"], p.get("param", modo), _cols(linhas), linhas, {}, {}, "pulsos"))
        finally:
            self.finalizar()
            if linhas:
                meta = {k: p.get(k) for k in ("modo", "V_set", "V_reset", "w_set", "w_reset", "amplitudes",
                                             "larguras", "V_fixo", "w_fixo", "n_pulsos", "V_read", "t_read",
                                             "media_read", "nplc_read", "base", "nplc_pulso", "compliance",
                                             "periodo", "reset_ref")}
                self.ctx.arquivo(Arquivo(p["etapa"], p.get("param") or modo, _cols(linhas), linhas, meta,
                                         self._resumo_larguras([l for l in linhas if l["n"] > 0]), "pulsos"))

    # ---------------------------------------------------------------- G11 sinapse
    def exp_sinapse(self, p):
        linhas = []
        tp = self.est_pulso(p["w"]) + self.est_leitura(p["t_read"])
        if p["modo"] == "LTP/LTD":
            self.ctx.total(int(p["ciclos"]) * (int(p["n_pot"]) + int(p["n_dep"])) * tp)
        else:
            tr = self.est_varredura(p["reset_ref"], 0.1, 0.1, 1) if p.get("reset_ref") else 0.0
            self.ctx.total(int(p["reps"]) * sum(tr + self.est_leitura(p["t_read"]) + max(dt, tp) + tp for dt in p["dts"]))
        self.iniciar()
        try:
            if p["modo"] == "LTP/LTD":
                tot = int(p["ciclos"]) * (int(p["n_pot"]) + int(p["n_dep"]))
                n = 0
                for c in range(1, int(p["ciclos"]) + 1):
                    for fase, V, N in (("P", p["V_pot"], int(p["n_pot"])), ("D", p["V_dep"], int(p["n_dep"]))):
                        for j in range(1, N + 1):
                            n += 1
                            ln, P = self._pulso_leitura(V, p["w"], p, j, {"ciclo": c, "fase": fase})
                            linhas.append(ln)
                            self.ctx.progresso(n / tot, f"ciclo {c} {fase}{j}")
                            self.ctx.parcial(Arquivo(p["etapa"], "LTP-LTD", _cols(linhas), linhas, {}, {}, "sinapse"))
                    Gp = [l["G_S"] for l in linhas if l["ciclo"] == c]
                    if Gp:
                        self.ctx.log(f"Ciclo {c}: Gmax/Gmin = {np.nanmax(Gp)/np.nanmin(Gp):.2f}")
            else:  # PPF
                dts = list(p["dts"])
                tot = len(dts) * int(p["reps"])
                n = 0
                for rep in range(1, int(p["reps"]) + 1):
                    ordem = random.sample(dts, len(dts)) if p.get("aleatorio") else dts
                    for dt in ordem:
                        n += 1
                        if p.get("reset_ref"):
                            self.varrer(p["reset_ref"], 0.1, 0.1, 1, p["compliance"], "AUTO", True, "hw", 1)
                        L0 = self.ler(p["V_read"], p["t_read"], p["media_read"], p["nplc_read"], p["compliance"])
                        ln1, P1 = self._pulso_leitura(p["V"], p["w"], p, 1, {"rep": rep, "dt_nominal_s": dt})
                        alvo = P1["t_ini"] + dt
                        if self.agora_inst() > alvo - 0.03:
                            self.ctx.log(f"AVISO: dt = {dt} s menor que o minimo (pulso + leitura)", "warn")
                        self.ctx.esperar_ate(self.inst_para_pc(alvo) - 0.02)
                        ln2, P2 = self._pulso_leitura(p["V"], p["w"], p, 2, {"rep": rep, "dt_nominal_s": dt})
                        G0 = abs(L0["I"] / p["V_read"])
                        A1, A2 = ln1["G_S"] - G0, ln2["G_S"] - ln1["G_S"]
                        for ln in (ln1, ln2):
                            ln["G0_S"] = G0
                            ln["dt_real_s"] = P2["t_ini"] - P1["t_ini"]
                            ln["PPF_A2_A1"] = A2 / A1 if A1 != 0 else float("nan")
                            linhas.append(ln)
                        self.ctx.log(f"PPF dt={dt} s (real {P2['t_ini']-P1['t_ini']:.3f} s): A2/A1 = {ln2['PPF_A2_A1']:.3f}")
                        self.ctx.progresso(n / tot, f"par {n}/{tot}")
        finally:
            self.finalizar()
            meta = {k: v for k, v in p.items() if k not in ("etapa", "param")}
            if linhas:
                resumo = self._resumo_larguras(linhas)
                if p["modo"] == "LTP/LTD":
                    G = np.array([l["G_S"] for l in linhas], float)
                    resumo.update({"Gmax_S": float(np.nanmax(G)), "Gmin_S": float(np.nanmin(G)),
                                   "Gmax_Gmin": float(np.nanmax(G) / np.nanmin(G))})
                par = p.get("param") or ("LTP-LTD" if p["modo"] == "LTP/LTD" else "PPF")
                self.ctx.arquivo(Arquivo(p["etapa"], par, _cols(linhas), linhas, meta, resumo, "sinapse"))

    # ---------------------------------------------------------------- G08 ciclos
    def exp_ciclos(self, p):
        """
        p: modo ('DC'|'Pulsado'), N, v_set, v_reset (vertices, DC), passo, atraso, nplc,
           Vp_set, Vp_reset, w (pulsado), V_read, t_read, media_read, nplc_read, compliance,
           bloco (ciclos por arquivo), parar_ruptura, etapa
        """
        N = int(p["N"])
        bloco = max(1, int(p.get("bloco", 100)))
        linhas, curvas = [], []
        nb = 1
        if p["modo"] == "DC":
            tc = (self.est_varredura(p["v_set"], p["passo"], p["atraso"], p["nplc"]) +
                  self.est_varredura(p["v_reset"], p["passo"], p["atraso"], p["nplc"]))
        else:
            tc = 2 * self.est_pulso(p["w"])
        self.ctx.total(N * (tc + 2 * self.est_leitura(p["t_read"])))
        self.iniciar()

        def fechar_bloco(final=False):
            nonlocal linhas, curvas, nb
            if not linhas:
                return
            meta = {k: v for k, v in p.items() if k not in ("etapa",)}
            rz = np.array([l["razao"] for l in linhas], float)
            res = {"ciclos_no_arquivo": len(linhas), "razao_mediana": float(np.nanmedian(rz))}
            self.ctx.arquivo(Arquivo(p["etapa"], f"B{nb}", _cols(linhas), linhas, meta, res, "ciclos"))
            if curvas:
                self.ctx.arquivo(Arquivo(p["etapa"], f"B{nb}-curvas", _cols(curvas), curvas, meta, {}, "iv"))
            linhas, curvas = [], []
            nb += 1

        try:
            for c in range(1, N + 1):
                ln = {"ciclo": c}
                if p["modo"] == "DC":
                    dS = self.varrer(p["v_set"], p["passo"], p["atraso"], p["nplc"], p["compliance"])
                    LS = self.ler(p["V_read"], p["t_read"], p["media_read"], p["nplc_read"], p["compliance"])
                    dR = self.varrer(p["v_reset"], p["passo"], p["atraso"], p["nplc"], p["compliance"])
                    LR = self.ler(p["V_read"], p["t_read"], p["media_read"], p["nplc_read"], p["compliance"])
                    ln["V_set_V"] = an.v_set(dS["Vmed"], dS["I"])
                    ln["V_reset_V"] = an.v_reset(dR["Vmed"], dR["I"])
                    ln["t_s"] = float(self.rel(dS["t"][0]))
                    if p.get("guardar_curvas", True):
                        for rot, d in (("SET", dS), ("RESET", dR)):
                            for x in self._linhas_iv(d):
                                x["ciclo"] = c; x["etapa"] = rot
                                curvas.append(x)
                else:
                    PS = self.pulso(p["Vp_set"], p["w"], 0.0, p.get("nplc_pulso", 0.01), p["compliance"])
                    LS = self.ler(p["V_read"], p["t_read"], p["media_read"], p["nplc_read"], p["compliance"])
                    PR = self.pulso(p["Vp_reset"], p["w"], 0.0, p.get("nplc_pulso", 0.01), p["compliance"])
                    LR = self.ler(p["V_read"], p["t_read"], p["media_read"], p["nplc_read"], p["compliance"])
                    ln["V_set_V"] = p["Vp_set"]; ln["V_reset_V"] = p["Vp_reset"]
                    ln["t_write_real_ms"] = PS["W_real"] * 1e3
                    ln["t_erase_real_ms"] = PR["W_real"] * 1e3
                    ln["w_calibrada_ms"] = PS["W_cal"] * 1e3
                    ln["t_s"] = float(self.rel(PS["t_ini"]))
                ln["I_LRS_read_A"] = LS["I"]; ln["I_HRS_read_A"] = LR["I"]
                ln["razao"] = abs(LS["I"] / LR["I"]) if LR["I"] else float("nan")
                ln["compliance_flag"] = int(LS["comp"] or LR["comp"])
                linhas.append(ln)
                self.ctx.ponto(ln)
                self.ctx.progresso(c / N, f"ciclo {c}/{N}")
                if c % 10 == 0 or c == 1:
                    self.ctx.log(f"Ciclo {c}: I_LRS={LS['I']:.3e} A, I_HRS={LR['I']:.3e} A, razao={ln['razao']:.2f}", "rx")
                self.ctx.parcial(Arquivo(p["etapa"], f"B{nb}", _cols(linhas), linhas, {}, {}, "ciclos"))
                if p.get("parar_ruptura", True) and max(abs(LS["I"]), abs(LR["I"])) > 0.9 * p["compliance"]:
                    self.ctx.log(f"Parada automatica: leitura > 0,9 x compliance no ciclo {c} (ruptura?)", "warn")
                    break
                if c % bloco == 0:
                    fechar_bloco()
        finally:
            self.finalizar()
            fechar_bloco(final=True)

    # ---------------------------------------------------------------- G09 retencao
    def _preparo(self, p):
        """Escrita antes de retencao/V_oc. Retorna o instante (tempo do instrumento) do fim."""
        tipo = p.get("preparo", "nenhum")
        if tipo == "varredura":
            d = self.varrer(p["prep_vertices"], p.get("prep_passo", 0.1), p.get("prep_atraso", 0.1),
                            p.get("prep_nplc", 1), p["compliance"], "AUTO", True, "hw", 1)
            per = an.periodo_real(d["t"])
            self.ctx.log(f"Preparo: varredura {p['prep_vertices']} concluida")
            return float(d["t"][-1] + (per if np.isfinite(per) else 0.0))
        if tipo == "pulsos":
            fim = None
            for j in range(int(p.get("prep_n", 1))):
                P = self.pulso(p["prep_V"], p["prep_w"], 0.0, p.get("nplc_pulso", 0.01), p["compliance"])
                fim = P["t_fim"]
            self.ctx.log(f"Preparo: {p.get('prep_n', 1)} pulso(s) de {p['prep_V']:+g} V")
            return fim
        return None

    def _est_preparo(self, p):
        tipo = p.get("preparo", "nenhum")
        if tipo == "varredura":
            return self.est_varredura(p["prep_vertices"], p.get("prep_passo", 0.1), p.get("prep_atraso", 0.1),
                                      p.get("prep_nplc", 1))
        if tipo == "pulsos":
            return int(p.get("prep_n", 1)) * self.est_pulso(p["prep_w"])
        return 0.0

    def exp_retencao(self, p):
        """
        p: preparo, prep_*, V_read, t_on, media, nplc, compliance, tempos (lista, s apos a escrita)
           ou periodo + n_leituras, entre ('0V'|'flutuante'), etapa, param
        """
        linhas = []
        flutuante = p.get("entre") == "flutuante"
        smod_orig = self.k.cfg["modo_off"]
        ult = max(p["tempos"]) if p.get("tempos") else p["periodo"] * (int(p["n_leituras"]) - 1)
        self.ctx.total(self._est_preparo(p) + ult + self.est_leitura(p["t_on"]))
        self.iniciar()
        try:
            t_ref = self._preparo(p)
            pc_ref = time.perf_counter() if t_ref is None else None
            if t_ref is not None:
                self._t0 = t_ref
            if p.get("tempos"):
                alvos = sorted(p["tempos"])
            else:
                alvos = [i * p["periodo"] for i in range(int(p["n_leituras"]))]
            if flutuante:
                self.k.write(":OUTP:SMOD HIMP")
            for j, ta in enumerate(alvos, 1):
                if flutuante:
                    self.k.saida(False)
                self.config_leitura(p["V_read"], p["nplc"], p["compliance"], p.get("faixa_i", "AUTO"))
                alvo_pc = (pc_ref + ta) if t_ref is None else self.inst_para_pc(t_ref + ta)
                self.ctx.esperar_ate(alvo_pc - 0.01)
                if flutuante:
                    self.k.saida(True)
                L = self.ler(p["V_read"], p["t_on"], p["media"], p["nplc"], p["compliance"],
                             p.get("faixa_i", "AUTO"), int(p.get("n_amostras", 10)))
                if t_ref is None:
                    t_ref = pc_ref - self._off
                    self._t0 = t_ref
                ln = {"n": j, "t_alvo_s": ta, "t_s": float(L["t_ini"] - t_ref), "V_read_V": p["V_read"],
                      "I_A": L["I"], "I_std_A": L["I_std"], "t_on_real_s": L["t_on_real"],
                      "compliance_flag": int(L["comp"]), "evento": self.ctx.pegar_evento()}
                linhas.append(ln)
                self.ctx.ponto(ln)
                self.ctx.progresso(j / len(alvos), f"leitura {j}/{len(alvos)} (t = {ln['t_s']:.1f} s)")
                if j <= 3 or j % 10 == 0:
                    self.ctx.log(f"Retencao t={ln['t_s']:.2f} s: I={L['I']:.4e} A", "rx")
                self.ctx.parcial(Arquivo(p["etapa"], p.get("param", "RET"), _cols(linhas), linhas, {}, {}, "retencao"), 10)
        finally:
            if flutuante:
                self.k.write(f":OUTP:SMOD {smod_orig}")
            self.finalizar()
            if linhas:
                I = np.array([l["I_A"] for l in linhas], float)
                t = np.array([l["t_s"] for l in linhas], float)
                res = {"primeira_leitura_s": float(t[0]), "deriva_pct": float((I[-1] / I[0] - 1) * 100) if I[0] else float("nan"),
                       "inclinacao_dlogI_dlogt": an.inclinacao_loglog(t, I)}
                meta = {k: v for k, v in p.items() if k not in ("etapa", "param")}
                self.ctx.arquivo(Arquivo(p["etapa"], p.get("param") or "RET", _cols(linhas), linhas, meta, res, "retencao"))

    # ---------------------------------------------------------------- transientes, V fixo, V_oc
    def exp_transiente(self, p):
        """
        p: modo ('V'|'Voc'), segmentos [(V, dur)], dur_voc, intervalo, rapida_n, rapida_dt,
           nplc, compliance, limite_v, preparo..., etapa, param
        """
        linhas = []
        dur = p["dur_voc"] if p["modo"] == "Voc" else sum(d for _, d in p["segmentos"])
        self.ctx.total(self._est_preparo(p) + dur + 0.5)
        self.iniciar()
        try:
            t_prep = self._preparo(p)
            if t_prep is not None:
                self._t0 = t_prep
            if p["modo"] == "Voc":
                segs = [(0.0, p["dur_voc"])]
                self.k.config_fonte_i(p.get("limite_v", 20.0), p["nplc"], "AUTO", 0.0,
                                      faixa_i=p.get("faixa_i_fonte", 1e-6))
                self.k.saida(True)
                func = "CURR"
            else:
                segs = p["segmentos"]
                vmax = max(abs(v) for v, _ in segs)
                self.k.config_fonte_v(p["compliance"], p["nplc"], p.get("faixa_i", "AUTO"), medir_v=False,
                                      faixa_v=max(vmax, 0.2))
                func = "VOLT"
            tm = self.k.tempo_medida(p["nplc"], self.k._az, 1)
            V_ant = 0.0
            dur_tot = sum(d for _, d in segs)
            t_acum = 0.0
            resumo = {}
            for js, (Vs, dur) in enumerate(segs, 1):
                t_ini_seg = None
                amostras = []
                if p.get("rapida_n", 0) > 0:
                    nr = int(min(2500, p["rapida_n"]))
                    tdel = max(0.0, p["rapida_dt"] - tm)
                    r = self._lista([Vs] * nr, 0.0, bias=Vs, func=func, trig_del=tdel)
                    amostras.append(r)
                    t_ini_seg = float(r["t"][0] - tdel)
                    self._emitir_transiente(r, js, Vs, func, linhas)
                if t_ini_seg is None:
                    r = self._lista([Vs], 0.0, bias=Vs, func=func)
                    t_ini_seg = float(r["t"][0])
                    self._emitir_transiente(r, js, Vs, func, linhas)
                if js == 1 and t_prep is not None:
                    resumo["atraso_preparo_para_1a_leitura_s"] = t_ini_seg - t_prep
                while True:
                    t_prox = self.agora_inst() + p["intervalo"]
                    if t_prox - t_ini_seg > dur:
                        break
                    self.ctx.esperar_ate(self.inst_para_pc(t_prox) - 0.01)
                    r = self._lista([Vs], 0.0, bias=Vs, func=func)
                    self._emitir_transiente(r, js, Vs, func, linhas)
                    t_acum = sum(d for _, d in segs[:js - 1]) + (float(r["t"][0]) - t_ini_seg)
                    self.ctx.progresso(t_acum / dur_tot, f"segmento {js}: {float(r['t'][0]) - t_ini_seg:.1f}/{dur:g} s")
                    self.ctx.parcial(Arquivo(p["etapa"], p.get("param", "IT"), _cols(linhas), linhas, {}, {}, "transiente"), 15)
                # carga integrada no segmento (inclui fuga)
                if func == "VOLT":
                    seg = [l for l in linhas if l["segmento"] == js]
                    if len(seg) > 2:
                        tt = np.array([l["t_s"] for l in seg]); ii = np.array([l["I_A"] for l in seg])
                        Q = float(np.sum(0.5 * (ii[1:] + ii[:-1]) * np.diff(tt)))
                        resumo[f"Q_seg{js}_C"] = Q
                        if abs(Vs - V_ant) > 1e-9:
                            resumo[f"C_eff_seg{js}_F"] = Q / (Vs - V_ant)
                V_ant = Vs
        finally:
            self.finalizar()
            if linhas:
                meta = {k: v for k, v in p.items() if k not in ("etapa", "param")}
                if p["modo"] == "Voc":
                    v = np.array([l["V_V"] for l in linhas])
                    resumo.update({"Voc_inicial_V": float(v[0]), "Voc_final_V": float(v[-1])})
                self.ctx.arquivo(Arquivo(p["etapa"], p.get("param") or ("VOC" if p["modo"] == "Voc" else "IT"),
                                         _cols(linhas), linhas, meta, resumo, "transiente"))

    def _emitir_transiente(self, r, js, Vs, func, linhas):
        t = self.rel(r["t"])
        for i in range(len(t)):
            ln = {"t_s": float(t[i]), "segmento": js,
                  "V_V": float(r["V"][i]) if func == "CURR" else Vs,
                  "I_A": 0.0 if func == "CURR" else float(r["I"][i]),
                  "compliance_flag": int(r["compliance"][i]), "evento": self.ctx.pegar_evento()}
            linhas.append(ln)
            self.ctx.ponto(ln)

    # ================================================================ celulas solares / diodos
    def exp_jv(self, p):
        """
        p: Vmin, Vmax, passo, atraso, nplc, compliance, sentido ('reverso'|'direto'|'reverso+direto'
           |'direto+reverso'), area_cm2, Pin, luz, repeticoes, modo, etapa, param
        """
        sent = p["sentido"]
        ordem = {"reverso": ["rev"], "direto": ["fwd"], "reverso+direto": ["rev", "fwd"],
                 "direto+reverso": ["fwd", "rev"]}[sent]
        A = p["area_cm2"]
        self.ctx.total(int(p.get("repeticoes", 1)) * len(ordem) *
                       self.est_varredura([p["Vmin"], p["Vmax"]], p["passo"], p["atraso"], p["nplc"]))
        self.iniciar()
        linhas = []
        resumo = {}
        try:
            for rep in range(1, int(p.get("repeticoes", 1)) + 1):
                for s in ordem:
                    vert = [p["Vmax"], p["Vmin"]] if s == "rev" else [p["Vmin"], p["Vmax"]]

                    def lote(r, lacos, segs, s=s):
                        for v, i in zip(r["V"], r["I"]):
                            self.ctx.ponto({"V": float(v), "I": float(i), "sentido": s, "rep": rep})

                    d = self.varrer(vert, p["passo"], p["atraso"], p["nplc"], p["compliance"],
                                    p.get("faixa_i", "AUTO"), True, p.get("modo", "hw"), 1, ao_lote=lote)
                    t = self.rel(d["t"])
                    for i in range(len(t)):
                        V, I = float(d["Vmed"][i]), float(d["I"][i])
                        linhas.append({"t_s": float(t[i]), "V_V": V, "I_A": I, "J_mA_cm2": -I / A * 1e3,
                                       "P_mW_cm2": -V * I / A * 1e3, "sentido": s, "rep": rep,
                                       "compliance_flag": int(d["comp"][i])})
                    if p.get("luz", "claro") != "escuro":
                        ps = an.parametros_solar(d["Vmed"], d["I"], A, p["Pin"])
                        for k, v in ps.items():
                            resumo[f"{s}{rep}_{k}"] = v
                        self.ctx.log(f"[{s}] Voc={ps['Voc_V']:.4f} V  Jsc={ps['Jsc_mA_cm2']:.3f} mA/cm2  "
                                     f"FF={ps['FF']:.3f}  PCE={ps['PCE_pct']:.3f} %")
                if len(ordem) == 2 and p.get("luz", "claro") != "escuro":
                    hi = an.indice_histerese(resumo.get(f"rev{rep}_PCE_pct", float("nan")),
                                             resumo.get(f"fwd{rep}_PCE_pct", float("nan")))
                    resumo[f"HI{rep}"] = hi
                    self.ctx.log(f"Indice de histerese HI = {hi:.3f}")
        finally:
            self.finalizar()
            meta = {k: v for k, v in p.items() if k not in ("etapa", "param")}
            if linhas:
                self.ctx.arquivo(Arquivo(p["etapa"], p.get("param") or p.get("luz", "claro"), _cols(linhas),
                                         linhas, meta, resumo, "jv"))

    def exp_diodo(self, p):
        """p: Vmin, Vmax, passo, atraso, nplc, compliance, area_cm2, T, V1, V2, Vrr, modo, etapa, param"""
        self.ctx.total(self.est_varredura(p.get("vertices") or [p["Vmin"], p["Vmax"]], p["passo"], p["atraso"], p["nplc"]))
        self.iniciar()
        linhas = []
        try:
            def lote(r, lacos, segs):
                for v, i in zip(r["V"], r["I"]):
                    self.ctx.ponto({"V": float(v), "I": float(i)})
            vert = p.get("vertices") or [p["Vmin"], p["Vmax"]]
            d = self.varrer(vert, p["passo"], p["atraso"], p["nplc"], p["compliance"],
                            p.get("faixa_i", "AUTO"), True, p.get("modo", "hw"), 1, ao_lote=lote)
        finally:
            self.finalizar()
        V, I = d["Vmed"], d["I"]
        A = p["area_cm2"]
        Vn, nloc = an.n_local(V, I, p["T"])
        nmap = dict(zip(np.round(Vn, 6), nloc))
        t = self.rel(d["t"])
        for i in range(len(t)):
            linhas.append({"t_s": float(t[i]), "V_V": float(V[i]), "I_A": float(I[i]),
                           "J_A_cm2": float(I[i]) / A, "n_local": nmap.get(round(float(V[i]), 6), float("nan")),
                           "compliance_flag": int(d["comp"][i])})
        aj = an.ajuste_diodo(V, I, p["V1"], p["V2"], p["T"])
        resumo = {"n": aj["n"], "I0_A": aj["I0_A"], "J0_A_cm2": aj["I0_A"] / A, "R2_ajuste": aj["R2"],
                  "faixa_ajuste_V": f"{p['V1']}..{p['V2']}", f"RR({p['Vrr']:g}V)": an.razao_retificacao_diodo(V, I, p["Vrr"])}
        rr = resumo[f"RR({p['Vrr']:g}V)"]
        self.ctx.log(f"Diodo: n = {aj['n']:.3f}, I0 = {aj['I0_A']:.3e} A (R2 {aj['R2']:.4f}); "
                     f"RR({p['Vrr']:g} V) = {rr:.3g}")
        meta = {k: v for k, v in p.items() if k not in ("etapa", "param")}
        self.ctx.arquivo(Arquivo(p["etapa"], p.get("param") or "escuro", _cols(linhas), linhas, meta, resumo, "diodo"))

    def exp_estabilidade(self, p):
        """p: modo ('MPPT'|'V fixo'|'Voc'|'Isc'), V0, dV, duracao, intervalo, nplc, compliance, area_cm2, Pin, etapa"""
        modo = p["modo"]
        A, Pin = p["area_cm2"], p["Pin"]
        linhas = []
        self.ctx.total(p["duracao"] + 0.5)
        self.iniciar()
        try:
            if modo == "Voc":
                self.k.config_fonte_i(p.get("limite_v", 5.0), p["nplc"], "AUTO", 0.0, faixa_i=1e-6)
                self.k.saida(True)
                func, V = "CURR", 0.0
            else:
                self.k.config_fonte_v(p["compliance"], p["nplc"], "AUTO", medir_v=True,
                                      faixa_v=max(abs(p.get("V0", 0.0)) + 1.0, 2.0))
                func = "VOLT"
                V = 0.0 if modo == "Isc" else float(p["V0"])
            direc, P_ant = 1.0, None
            t_ini = None
            while True:
                r = self._lista([V], 0.0, bias=V, func=func)
                t = float(r["t"][0])
                if t_ini is None:
                    t_ini = t
                Vm = float(r["V"][0]); Im = 0.0 if func == "CURR" else float(r["I"][0])
                P = -Vm * Im / A * 1e3
                ln = {"t_s": float(self.rel(t)), "V_V": Vm, "I_A": Im, "J_mA_cm2": -Im / A * 1e3,
                      "P_mW_cm2": P, "PCE_pct": P / Pin * 100 if Pin else float("nan"),
                      "evento": self.ctx.pegar_evento()}
                linhas.append(ln)
                self.ctx.ponto(ln)
                if modo == "MPPT":
                    if P_ant is not None and P < P_ant:
                        direc = -direc
                    P_ant = P
                    V = V + direc * p["dV"]
                if t - t_ini >= p["duracao"]:
                    break
                self.ctx.progresso((t - t_ini) / p["duracao"], f"{t - t_ini:.0f}/{p['duracao']:g} s")
                self.ctx.parcial(Arquivo(p["etapa"], modo, _cols(linhas), linhas, {}, {}, "estab"), 15)
                self.ctx.esperar_ate(self.inst_para_pc(t + p["intervalo"]) - 0.01)
        finally:
            self.finalizar()
            if linhas:
                Ps = np.array([l["P_mW_cm2"] for l in linhas])
                res = {"P_inicial_mW_cm2": float(Ps[0]), "P_final_mW_cm2": float(Ps[-1]),
                       "P_final_sobre_inicial": float(Ps[-1] / Ps[0]) if Ps[0] else float("nan")}
                meta = {k: v for k, v in p.items() if k not in ("etapa", "param")}
                self.ctx.arquivo(Arquivo(p["etapa"], p.get("param") or modo.replace(" ", ""), _cols(linhas),
                                         linhas, meta, res, "estab"))

    # ================================================================ diagnostico
    def teste_largura(self, larguras, V=1.0, nplc=0.01, compliance=0.01, n=10):
        """Mede cada largura nominal n vezes (use um resistor ou a ponta levantada)."""
        out = []
        self.iniciar()
        try:
            for w in larguras:
                P = [self.pulso(V, w, 0.0, nplc, compliance) for _ in range(n)]
                wr = np.array([p["W_real"] for p in P]); wc = np.array([p["W_cal"] for p in P])
                out.append({"w_nominal_ms": w * 1e3, "regime": P[-1]["regime"], "passos": P[-1]["k"],
                            "w_calibrada_ms": float(np.median(wc) * 1e3),
                            "w_carimbo_media_ms": float(np.mean(wr) * 1e3),
                            "w_carimbo_min_ms": float(wr.min() * 1e3), "w_carimbo_max_ms": float(wr.max() * 1e3)})
                o = out[-1]
                self.ctx.log(f"w = {w*1e3:7.2f} ms -> calibrada {o['w_calibrada_ms']:8.3f} ms ({o['regime']}, k={o['passos']}); "
                             f"carimbos {o['w_carimbo_media_ms']:.2f} ms (min {o['w_carimbo_min_ms']:.2f}, max {o['w_carimbo_max_ms']:.2f})")
        finally:
            self.finalizar()
        return out

    def calibrar_sobrecarga(self, nplc=0.01, n=200):
        """T0 (passo sem atraso) com n passos a 0 V. Retorna (T0, sobrecarga)."""
        self.iniciar()
        try:
            T0 = self.calibrar_T0(nplc, 0.0, 0.01, 0.01, n=n)
            return T0, self.k.sobrecarga_s
        finally:
            self.finalizar()


def _cols(linhas):
    cols = []
    for l in linhas:
        for k in l.keys():
            if k not in cols:
                cols.append(k)
    return cols
