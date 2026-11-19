"""Abas de capacitores MIS / efeito memoria (guias G04-G11, G16, G17 da campanha)."""
import numpy as np

from .base import AbaMedida, Campo, Opcao, Marca, secao, nota, C, PALETA, log_y

FAIXAS_I = ["AUTO", "1e-6", "1e-5", "1e-4", "1e-3", "1e-2", "1e-1", "1"]
MODOS_T = ["Instrumento (lista)", "Ponto a ponto (ao vivo)"]


def _faixa(txt):
    return "AUTO" if txt == "AUTO" else float(txt)


def _modo(txt):
    return "hw" if txt.startswith("Instrumento") else "pp"


def _vertices(campo, nome="Vertices"):
    v = campo.lista()
    if len(v) < 2:
        raise ValueError(f"{nome}: informe ao menos dois valores (ex.: -5, 10, -5).")
    return v


def _validar_limites(vmax, compliance):
    if vmax > 210:
        raise ValueError("O Keithley 2400 fonte no maximo 210 V.")
    if vmax > 21 and compliance > 0.105:
        raise ValueError("Acima de 21 V a compliance maxima do 2400 e 105 mA.")
    if compliance > 1.05:
        raise ValueError("Compliance maxima do 2400: 1,05 A.")


def _campos_dc(self, pf, compliance=0.01, nplc=1, atraso=0.1, passo=0.1, com_passo=True):
    if com_passo:
        self.add(pf, "passo", Campo(pf, "Passo de tensao", passo, "V"))
    self.add(pf, "atraso", Campo(pf, "Atraso por ponto (:SOUR:DEL)", atraso, "s",
                                 dica="Tempo entre aplicar o nivel e medir. Periodo do ponto = atraso + medida "
                                      "(NPLC/60 s, x3 com autozero, x2 se medir V)."))
    self.add(pf, "nplc", Campo(pf, "NPLC (integracao)", nplc, "", dica="1 PLC = 16,7 ms a 60 Hz."))
    self.add(pf, "compliance", Campo(pf, "Compliance", compliance, "A"))
    self.add(pf, "faixa_i", Opcao(pf, "Faixa de corrente", FAIXAS_I))


def _plot_curvas(g, pts, chave, vista, rot=lambda k: str(k)):
    g.limpar()
    ax = g.ax
    if not pts:
        ax.set_xlabel("Tensao (V)"); ax.set_ylabel("Corrente (A)")
        return
    grupos = {}
    for p in pts:
        grupos.setdefault(p.get(chave, 0), []).append(p)
    for j, (k, sub) in enumerate(grupos.items()):
        V = np.array([p["V"] for p in sub]); I = np.array([p["I"] for p in sub])
        cor = PALETA[j % len(PALETA)]
        if vista.startswith("log"):
            ax.semilogy(V, np.abs(I), "-o", ms=1.8, lw=1.0, color=cor, label=rot(k))
            ax.set_ylabel("|I| (A)")
        elif vista.startswith("R"):
            with np.errstate(divide="ignore", invalid="ignore"):
                ax.semilogy(V, np.abs(V / I), "-o", ms=1.8, lw=1.0, color=cor, label=rot(k))
            ax.set_ylabel("|V/I| (Ohm)")
        else:
            ax.plot(V, I, "-o", ms=1.8, lw=1.0, color=cor, label=rot(k))
            ax.set_ylabel("I (A)")
    ax.set_xlabel("Tensao (V)")
    if len(grupos) > 1:
        ax.legend(fontsize=8, ncol=2)


# =============================================================== I-V e lacos
class AbaIV(AbaMedida):
    NOME = "I-V e Lacos"
    ETAPA = "G04-E2"
    VISTAS = ["log|I| x V", "I x V", "R x V"]
    PRESETS = {
        "G04-E1 pad virgem 0>+1>0 V": dict(vertices="0, 1, 0", passo=0.1, atraso=0.1, n_lacos=1, etapa="G04-E1", param="p1V", atrasos=""),
        "G04-E1 pad virgem 0>-1>0 V": dict(vertices="0, -1, 0", passo=0.1, atraso=0.1, n_lacos=1, etapa="G04-E1", param="m1V", atrasos=""),
        "G04-E2 PS551-0h  -5>+10>-5 V (3 lacos)": dict(vertices="-5, 10, -5", passo=0.1, atraso=0.1, nplc=1, compliance=0.01, n_lacos=3, etapa="G04-E2", param="", atrasos=""),
        "G04-E2 PS550-0h  -10>+10>-10 V, 50 mA": dict(vertices="-10, 10, -10", passo=0.1, atraso=0.1, compliance=0.05, n_lacos=3, etapa="G04-E2", param="", atrasos=""),
        "G04-E2 10 h  -5>+5>-5 V, 50 mA": dict(vertices="-5, 5, -5", passo=0.1, atraso=0.1, compliance=0.05, n_lacos=3, etapa="G04-E2", param="", atrasos=""),
        "G04-E3 RESET 0>-5>0 V": dict(vertices="0, -5, 0", passo=0.1, atraso=0.1, n_lacos=1, etapa="G04-E3", param="RESET", atrasos=""),
        "G04-E3 leitura lenta 0>+3>0 V (0,05 V)": dict(vertices="0, 3, 0", passo=0.05, atraso=0.1, n_lacos=1, etapa="G04-E3", param="HRS1", atrasos=""),
        "G04-E3 leitura lenta 0>-1>0 V (0,05 V)": dict(vertices="0, -1, 0", passo=0.05, atraso=0.1, n_lacos=1, etapa="G04-E3", param="HRSneg", atrasos=""),
        "G04-E3 SET 0>+10>0 V": dict(vertices="0, 10, 0", passo=0.1, atraso=0.1, n_lacos=1, etapa="G04-E3", param="SET", atrasos=""),
        "G06 taxa: 5 atrasos sorteados x 2 lacos": dict(vertices="-5, 10, -5", passo=0.1, n_lacos=2, etapa="G06", param="", atrasos="0.01, 0.03, 0.1, 0.3, 1", aleatorio=True),
        "G06 PS550-0h: +10>+20>+10 V": dict(vertices="10, 20, 10", passo=0.1, n_lacos=2, compliance=0.05, etapa="G06", param="", atrasos="0.03, 0.1, 0.3", aleatorio=True),
        "G07-T1 formacao 0>+25>0 V, 50 mA": dict(vertices="0, 25, 0", passo=0.1, atraso=0.1, compliance=0.05, n_lacos=1, etapa="G07-T1", param="", atrasos=""),
        "G07-T2 limiar +10>+20>+10 V (5 lacos)": dict(vertices="10, 20, 10", passo=0.1, atraso=0.1, compliance=0.05, n_lacos=5, etapa="G07-T2", param="", atrasos=""),
        "G07-T6 lado negativo 0>-20>0 V": dict(vertices="0, -20, 0", passo=0.1, atraso=0.1, compliance=0.05, n_lacos=1, etapa="G07-T6", param="", atrasos=""),
        "G15 HRS/LRS leitura lenta 0>+3>0 V": dict(vertices="0, 3, 0", passo=0.05, atraso=0.1, n_lacos=1, etapa="G15", param="HRS_T300", atrasos=""),
        "G16-L2 I-V 0>+10>0 V (escuro/luz)": dict(vertices="0, 10, 0", passo=0.1, atraso=0.1, n_lacos=1, etapa="G16-L2", param="escuro", atrasos=""),
        "G16-L3 ramo -V 0>-5>0 V": dict(vertices="0, -5, 0", passo=0.1, atraso=0.1, n_lacos=1, etapa="G16-L3", param="escuro", atrasos=""),
    }

    def construir(self, pf):
        secao(pf, "VARREDURA")
        self.add(pf, "vertices", Campo(pf, "Vertices (V)", "-5, 10, -5",
                                       dica="Caminho da varredura. Ex.: '0, 1, 0'  '-5, 10, -5'  '0, 10, 0, -5, 0'. "
                                            "Com virgula decimal, separe por ';' (ex.: '0; 0,5; 0')."))
        _campos_dc(self, pf)
        self.add(pf, "medir_v", Marca(pf, "Medir V (readback; dobra o tempo de medida)", True))
        self.add(pf, "modo", Opcao(pf, "Temporizacao", MODOS_T))
        nota(pf, "Instrumento: a lista inteira roda no 2400 (taxa constante; dados ao fim de cada lista). "
                 "Ponto a ponto: grafico ao vivo, periodo maior e irregular (comunicacao serial).")
        secao(pf, "REPETICOES")
        self.add(pf, "n_lacos", Campo(pf, "Numero de lacos seguidos", 3))
        self.add(pf, "rotulo", Campo(pf, "Rotulo do laco no nome", "L"))
        self.add(pf, "atrasos", Campo(pf, "Serie de atrasos G06 (opcional)", "",
                                      dica="Lista de atrasos por ponto (s). Para cada um, roda os lacos; "
                                           "arquivos R<atraso>_L1, _L2..."))
        self.add(pf, "aleatorio", Marca(pf, "Ordem sorteada", True))
        secao(pf, "ANALISE NA TELA")
        self.add(pf, "V_ba", Campo(pf, "Janela B/A em (V)", "0.5, 1, 2, 3, 4, -1"))

    def parametros(self):
        c = self.campos
        vert = _vertices(c["vertices"])
        comp = c["compliance"].val
        _validar_limites(max(abs(v) for v in vert), comp)
        return dict(vertices=vert, passo=c["passo"].val, atraso=c["atraso"].val, nplc=c["nplc"].val,
                    compliance=comp, faixa_i=_faixa(c["faixa_i"].get()), medir_v=c["medir_v"].get(),
                    modo=_modo(c["modo"].get()), n_lacos=int(c["n_lacos"].val), rotulo=c["rotulo"].txt or "L",
                    atrasos=c["atrasos"].lista(), aleatorio=c["aleatorio"].get(), V_ba=c["V_ba"].lista())

    def executar(self, motor, p):
        motor.exp_iv(p)

    def plotar(self, g, pts):
        _plot_curvas(g, pts, "laco", self.vis.get(), rot=lambda k: f"laco {k}")
        g.ax.set_title("I-V", color=C["gold"], fontsize=10)


# =============================================================== leitura e multinivel
class AbaMultinivel(AbaMedida):
    NOME = "Leitura e Multinivel"
    ETAPA = "G05-M1"
    VISTAS = ["I_leitura", "Curvas"]
    MODOS = ["Leitura simples", "M1: serie de V_max", "M2: serie de compliance", "M3: serie de V_reset"]
    PRESETS = {
        "Leitura +1 V e +2 V (1 s, media 0,5 s)": dict(modo="Leitura simples", V_leitura="1, 2", t_on=1, media=0.5, repeticoes=1, etapa="G05", param="RD"),
        "G05-M1 V_max 4,5,6,7,8,10 V (2 rep.)": dict(modo="M1: serie de V_max", valores="4, 5, 6, 7, 8, 10", repeticoes=2, aleatorio=True, v_reset="0, -5, 0", etapa="G05-M1"),
        "G05-M1 reduzido (6 e 10 V)": dict(modo="M1: serie de V_max", valores="6, 10", repeticoes=2, aleatorio=True, etapa="G05-M1"),
        "G05-M2 compliance 0,2..5 mA": dict(modo="M2: serie de compliance", valores="0.0002, 0.0005, 0.001, 0.002, 0.005", repeticoes=1, aleatorio=True, v_set="0, 10, 0", v_reset="0, -5, 0", etapa="G05-M2"),
        "G05-M3 V_reset -1..-5 V": dict(modo="M3: serie de V_reset", valores="-1, -2, -3, -4, -5", repeticoes=1, aleatorio=True, v_set="0, 10, 0", etapa="G05-M3"),
    }

    def construir(self, pf):
        self.add(pf, "modo", Opcao(pf, "Modo", self.MODOS))
        secao(pf, "LEITURA (tensao constante)")
        self.add(pf, "V_leitura", Campo(pf, "Tensoes de leitura", "1, 2", "V"))
        self.add(pf, "t_on", Campo(pf, "Tempo em V_leitura", 1.0, "s"))
        self.add(pf, "media", Campo(pf, "Media do ultimo trecho", 0.5, "s"))
        self.add(pf, "nplc_l", Campo(pf, "NPLC da leitura", 1))
        self.add(pf, "n_amostras", Campo(pf, "Amostras por leitura", 10))
        self.add(pf, "repeticoes", Campo(pf, "Repeticoes", 1))
        self.add(pf, "intervalo", Campo(pf, "Intervalo (leitura simples)", 0, "s"))
        secao(pf, "SERIE (M1 / M2 / M3)")
        self.add(pf, "valores", Campo(pf, "Valores (V, A ou V)", "4, 5, 6, 7, 8, 10"))
        self.add(pf, "aleatorio", Marca(pf, "Ordem sorteada (anotada no log e no arquivo)", True))
        self.add(pf, "v_reset", Campo(pf, "RESET (vertices)", "0, -5, 0", "V"))
        self.add(pf, "v_set", Campo(pf, "SET (vertices)", "0, 10, 0", "V"))
        _campos_dc(self, pf)

    def parametros(self):
        c = self.campos
        p = dict(V_leitura=c["V_leitura"].lista(), t_on=c["t_on"].val, media=c["media"].val,
                 nplc=c["nplc_l"].val, compliance=c["compliance"].val, n_amostras=int(c["n_amostras"].val),
                 repeticoes=int(c["repeticoes"].val), intervalo=c["intervalo"].val, faixa_i=_faixa(c["faixa_i"].get()))
        m = c["modo"].get()
        if m.startswith("Leitura"):
            p["tipo"] = "leitura"
        else:
            modo = {"M1": "Vmax", "M2": "compliance", "M3": "Vreset"}[m[:2]]
            p.update(tipo="serie", modo=modo, valores=c["valores"].lista(), aleatorio=c["aleatorio"].get(),
                     v_reset=_vertices(c["v_reset"], "RESET"), v_set=_vertices(c["v_set"], "SET"),
                     passo=c["passo"].val, atraso=c["atraso"].val, nplc_leitura=p["nplc"], nplc=c["nplc"].val)
            if not p["valores"]:
                raise ValueError("Informe os valores da serie.")
            vs = p["v_set"] + p["v_reset"] + (p["valores"] if modo != "compliance" else [])
            comp = max(p["valores"]) if modo == "compliance" else p["compliance"]
            _validar_limites(max(abs(x) for x in vs), comp)
        return p

    def executar(self, motor, p):
        if p["tipo"] == "leitura":
            motor.exp_leitura(p)
        else:
            motor.exp_multinivel(p)

    def plotar(self, g, pts):
        g.limpar()
        ax = g.ax
        if self.vis.get() == "Curvas":
            _plot_curvas(g, [p for p in pts if "curva" in p], "curva", "log")
            return
        lei = [p for p in pts if "I_A" in p]
        if not lei:
            ax.set_xlabel("leitura #"); ax.set_ylabel("I (A)")
            return
        if "valor" in lei[0]:
            for j, (et, mk) in enumerate((("RD-pre", "o"), ("RD-pos", "s"))):
                for jj, V in enumerate(sorted({p["V_read_V"] for p in lei})):
                    sub = [p for p in lei if p["etapa"] == et and p["V_read_V"] == V]
                    if sub:
                        ax.semilogy([p["valor"] for p in sub], [abs(p["I_A"]) for p in sub], mk,
                                    color=PALETA[(2 * jj + j) % len(PALETA)], label=f"{et} {V:+g} V", ms=5)
            ax.set_xlabel("valor do parametro (V_max / compliance / V_reset)")
            ax.legend(fontsize=8)
        else:
            for jj, V in enumerate(sorted({p["V_read_V"] for p in lei})):
                sub = [p for p in lei if p["V_read_V"] == V]
                ax.semilogy([p["n"] for p in sub], [abs(p["I_A"]) for p in sub], "o-", ms=4,
                            color=PALETA[jj % len(PALETA)], label=f"{V:+g} V")
            ax.set_xlabel("leitura #")
            ax.legend(fontsize=8)
        ax.set_ylabel("|I_leitura| (A)")


# =============================================================== pulsos
def _campos_leitura_pulso(self, pf):
    secao(pf, "LEITURA APOS CADA PULSO")
    self.add(pf, "V_read", Campo(pf, "V de leitura", 1.0, "V"))
    self.add(pf, "t_read", Campo(pf, "Tempo de leitura", 0.2, "s"))
    self.add(pf, "media_read", Campo(pf, "Media do ultimo trecho", 0.1, "s"))
    self.add(pf, "nplc_read", Campo(pf, "NPLC da leitura", 1))
    self.add(pf, "faixa_i", Opcao(pf, "Faixa de corrente da leitura", FAIXAS_I))


def _campos_pulso_comuns(self, pf):
    secao(pf, "PULSO (temporizado pelo 2400)")
    self.add(pf, "base", Campo(pf, "V de base (repouso)", 0.0, "V"))
    self.add(pf, "nplc_pulso", Campo(pf, "NPLC durante o pulso", 0.01,
                                     dica="Define T0 (largura minima e resolucao das larguras ate ~60 ms): "
                                          "T0 ~ NPLC/60 s + ~0,8 ms. T0 e medido no inicio de cada medida."))
    self.add(pf, "compliance", Campo(pf, "Compliance (faixa fixa no pulso)", 0.01, "A"))
    self.add(pf, "auto_corrigir", Marca(pf, "Pulsos > 60 ms: ajustar o atraso pela media dos carimbos", True))


def _p_leitura(c):
    return dict(V_read=c["V_read"].val, t_read=c["t_read"].val, media_read=c["media_read"].val,
                nplc_read=c["nplc_read"].val, faixa_i=_faixa(c["faixa_i"].get()),
                base=c["base"].val, nplc_pulso=c["nplc_pulso"].val, compliance=c["compliance"].val,
                auto_corrigir=c["auto_corrigir"].get())


class AbaPulsos(AbaMedida):
    NOME = "Pulsos"
    ETAPA = "G10-P1"
    VISTAS = ["I_leitura", "R", "Largura real"]
    MODOS = ["SET", "RESET", "Alternado", "Amplitudes", "Larguras"]
    PRESETS = {
        "G10-P1 SET +4..+9 V (10 pulsos cada)": dict(modo="Amplitudes", amplitudes="4, 5, 6, 7, 8, 9", w_fixo=50, n_pulsos=10, aleatorio=True, reset_ref="0, -5, 0", V_read=1, etapa="G10-P1", param="SET"),
        "G10-P1 RESET -1..-5 V (partindo de LRS)": dict(modo="Amplitudes", amplitudes="-1, -2, -3, -4, -5", w_fixo=50, n_pulsos=10, aleatorio=True, reset_ref="0, 10, 0", V_read=1, etapa="G10-P1", param="RESET"),
        "G10-P2 larguras a +7 V": dict(modo="Larguras", V_fixo=7, larguras="1, 2, 5, 10, 50, 100", n_pulsos=10, aleatorio=True, reset_ref="0, -5, 0", etapa="G10-P2", param="Vp7p0"),
        "G10-P2 larguras a -3,5 V": dict(modo="Larguras", V_fixo=-3.5, larguras="1, 2, 5, 10, 50, 100", n_pulsos=10, aleatorio=True, reset_ref="0, 10, 0", etapa="G10-P2", param="Vm3p5"),
        "G10-P4 comparacao 13/05/2026 (+7/-3,5 V, leitura +4 V)": dict(modo="Amplitudes", amplitudes="7, -3.5", w_fixo=50, n_pulsos=100, aleatorio=False, reset_ref="", V_read=4, etapa="G10-P4", param=""),
        "Alternado SET/RESET": dict(modo="Alternado", V_set=7, V_reset=-3.5, w_set=50, w_reset=50, n_pulsos=20, reset_ref="", etapa="G10", param="ALT"),
    }

    def construir(self, pf):
        self.add(pf, "modo", Opcao(pf, "Modo", self.MODOS, segmentado=False))
        secao(pf, "SET / RESET / ALTERNADO")
        self.add(pf, "V_set", Campo(pf, "V do pulso SET", 7.0, "V"))
        self.add(pf, "w_set", Campo(pf, "Largura SET", 50, "ms"))
        self.add(pf, "V_reset", Campo(pf, "V do pulso RESET", -3.5, "V"))
        self.add(pf, "w_reset", Campo(pf, "Largura RESET", 50, "ms"))
        secao(pf, "SERIES (Amplitudes / Larguras)")
        self.add(pf, "amplitudes", Campo(pf, "Amplitudes", "4, 5, 6, 7, 8, 9", "V"))
        self.add(pf, "w_fixo", Campo(pf, "Largura fixa (Amplitudes)", 50, "ms"))
        self.add(pf, "larguras", Campo(pf, "Larguras", "1, 2, 5, 10, 50, 100", "ms"))
        self.add(pf, "V_fixo", Campo(pf, "V fixo (Larguras)", 7.0, "V"))
        self.add(pf, "aleatorio", Marca(pf, "Ordem sorteada", True))
        self.add(pf, "reset_ref", Campo(pf, "Preparo antes de cada serie (vertices)", "0, -5, 0", "V",
                                        dica="Varredura de referencia (ex.: RESET 0,-5,0). Vazio = nenhum."))
        secao(pf, "GERAL")
        self.add(pf, "n_pulsos", Campo(pf, "Pulsos por serie / nivel", 10))
        self.add(pf, "periodo", Campo(pf, "Periodo minimo entre pulsos (0 = o menor)", 0, "s",
                                      dica="G10: periodo >= 5 x largura."))
        _campos_pulso_comuns(self, pf)
        _campos_leitura_pulso(self, pf)

    def parametros(self):
        c = self.campos
        p = _p_leitura(c)
        p.update(modo=c["modo"].get(), V_set=c["V_set"].val, w_set=c["w_set"].val / 1e3,
                 V_reset=c["V_reset"].val, w_reset=c["w_reset"].val / 1e3,
                 amplitudes=c["amplitudes"].lista(), w_fixo=c["w_fixo"].val / 1e3,
                 larguras=[x / 1e3 for x in c["larguras"].lista()], V_fixo=c["V_fixo"].val,
                 aleatorio=c["aleatorio"].get(), n_pulsos=int(c["n_pulsos"].val), periodo=c["periodo"].val,
                 reset_ref=c["reset_ref"].lista() or None)
        vs = [p["V_set"], p["V_reset"], p["V_fixo"]] + p["amplitudes"]
        _validar_limites(max(abs(v) for v in vs), p["compliance"])
        return p

    def executar(self, motor, p):
        motor.exp_pulsos(p)

    def plotar(self, g, pts):
        g.limpar()
        ax = g.ax
        v = self.vis.get()
        pts = [p for p in pts if "I_read_A" in p]
        if not pts:
            ax.set_xlabel("pulso #")
            return
        series = []
        for p in pts:
            if p["serie"] not in series:
                series.append(p["serie"])
        x0 = 0
        for j, s in enumerate(series):
            sub = [p for p in pts if p["serie"] == s]
            x = np.arange(x0, x0 + len(sub))
            x0 += len(sub)
            if v == "R":
                y = [p["R_ohm"] for p in sub]; ax.set_ylabel("R (Ohm)")
            elif v == "Largura real":
                y = [p["t_write_real_ms"] for p in sub]; ax.set_ylabel("largura real (ms)")
            else:
                y = [abs(p["I_read_A"]) for p in sub]; ax.set_ylabel("|I_leitura| (A)")
            ax.plot(x, y, "o-", ms=3, lw=0.8, color=PALETA[j % len(PALETA)], label=s)
        if v != "Largura real":
            log_y(ax, [1])
        ax.set_xlabel("pulso # (sequencia)")
        ax.legend(fontsize=8, ncol=3)


# =============================================================== sinapse
class AbaSinapse(AbaMedida):
    NOME = "Sinapse"
    ETAPA = "G11-S1"
    VISTAS = ["G", "PPF"]
    PRESETS = {
        "G11-S1 LTP/LTD 50x(+7 V) / 50x(-3,5 V), 10 ciclos": dict(modo="LTP/LTD", n_pot=50, V_pot=7, n_dep=50, V_dep=-3.5, ciclos=10, V_read=1, etapa="G11-S1", param="LTP-LTD"),
        "G11-S1 ciclo extra com leitura +4 V": dict(modo="LTP/LTD", n_pot=50, V_pot=7, n_dep=50, V_dep=-3.5, ciclos=1, V_read=4, etapa="G11-S1", param="RD4V"),
        "G11-S2 amplitude (3 ciclos)": dict(modo="LTP/LTD", n_pot=50, V_pot=6, n_dep=50, V_dep=-2.5, ciclos=3, etapa="G11-S2", param="Vp6p0"),
        "G11-S3 PPF +6 V, dt 0,1..10 s (5 rep.)": dict(modo="PPF", V=6, dts="0.1, 0.2, 0.5, 1, 2, 5, 10", reps=5, reset_ref="0, -5, 0", etapa="G11-S3", param="PPF"),
    }

    def construir(self, pf):
        self.add(pf, "modo", Opcao(pf, "Modo", ["LTP/LTD", "PPF"], segmentado=True))
        secao(pf, "LTP / LTD")
        self.add(pf, "n_pot", Campo(pf, "Pulsos de potenciacao", 50))
        self.add(pf, "V_pot", Campo(pf, "V potenciacao", 7.0, "V"))
        self.add(pf, "n_dep", Campo(pf, "Pulsos de depressao", 50))
        self.add(pf, "V_dep", Campo(pf, "V depressao", -3.5, "V"))
        self.add(pf, "ciclos", Campo(pf, "Ciclos", 10))
        secao(pf, "PPF (pares de pulsos)")
        self.add(pf, "V", Campo(pf, "V do par", 6.0, "V"))
        self.add(pf, "dts", Campo(pf, "Intervalos dt", "0.1, 0.2, 0.5, 1, 2, 5, 10", "s",
                                  dica="O dt minimo = pulso + leitura + comunicacao; o dt real vai para o arquivo."))
        self.add(pf, "reps", Campo(pf, "Repeticoes por dt", 5))
        self.add(pf, "reset_ref", Campo(pf, "RESET entre pares (vertices)", "0, -5, 0", "V"))
        self.add(pf, "aleatorio", Marca(pf, "Ordem sorteada dos dt", True))
        self.add(pf, "w", Campo(pf, "Largura dos pulsos", 50, "ms"))
        _campos_pulso_comuns(self, pf)
        _campos_leitura_pulso(self, pf)

    def parametros(self):
        c = self.campos
        p = _p_leitura(c)
        p.update(modo=c["modo"].get(), n_pot=int(c["n_pot"].val), V_pot=c["V_pot"].val, n_dep=int(c["n_dep"].val),
                 V_dep=c["V_dep"].val, ciclos=int(c["ciclos"].val), V=c["V"].val, dts=c["dts"].lista(),
                 reps=int(c["reps"].val), reset_ref=c["reset_ref"].lista() or None, aleatorio=c["aleatorio"].get(),
                 w=c["w"].val / 1e3)
        _validar_limites(max(abs(p["V_pot"]), abs(p["V_dep"]), abs(p["V"])), p["compliance"])
        return p

    def executar(self, motor, p):
        motor.exp_sinapse(p)

    def plotar(self, g, pts):
        g.limpar()
        ax = g.ax
        pts = [p for p in pts if "G_S" in p]
        if not pts:
            return
        if self.vis.get() == "PPF" and "PPF_A2_A1" in pts[-1]:
            d = [p for p in pts if p["n"] == 2 and "PPF_A2_A1" in p]
            ax.semilogx([p["dt_real_s"] for p in d], [p["PPF_A2_A1"] for p in d], "o", color=C["gold"])
            ax.set_xlabel("dt real (s)"); ax.set_ylabel("A2/A1")
            return
        cores = {"P": C["red"], "D": C["blue"]}
        x = np.arange(len(pts))
        ax.scatter(x, [p["G_S"] for p in pts], s=8, c=[cores.get(p.get("fase"), C["gold"]) for p in pts])
        ax.plot(x, [p["G_S"] for p in pts], "-", lw=0.5, color=C["faint"])
        ax.set_xlabel("pulso # (sequencia)"); ax.set_ylabel("G = I/V_leitura (S)")


# =============================================================== ciclos
class AbaCiclos(AbaMedida):
    NOME = "Ciclos"
    ETAPA = "G08-C1"
    VISTAS = ["Correntes", "Razao"]
    PRESETS = {
        "G08-C1 DC 500 ciclos (+10 / -5 V, leitura +1 V)": dict(modo="DC", N=500, v_set="0, 10, 0", v_reset="0, -5, 0", V_read=1, t_read=0.2, bloco=100, etapa="G08-C1"),
        "G08-C2 pulsado 1000 ciclos (+7 / -4 V)": dict(modo="Pulsado", N=1000, Vp_set=7, Vp_reset=-4, w=50, V_read=1, t_read=0.2, bloco=100, etapa="G08-C2"),
        "G08-C3 recuperacao: 50 ciclos DC": dict(modo="DC", N=50, v_set="0, 10, 0", v_reset="0, -5, 0", bloco=100, etapa="G08-C3"),
    }

    def construir(self, pf):
        self.add(pf, "modo", Opcao(pf, "Modo", ["DC", "Pulsado"], segmentado=True))
        self.add(pf, "N", Campo(pf, "Numero de ciclos", 500))
        secao(pf, "DC (varreduras)")
        self.add(pf, "v_set", Campo(pf, "SET (vertices)", "0, 10, 0", "V"))
        self.add(pf, "v_reset", Campo(pf, "RESET (vertices)", "0, -5, 0", "V"))
        self.add(pf, "guardar_curvas", Marca(pf, "Gravar as curvas (arquivo <B>-curvas)", True))
        _campos_dc(self, pf)
        secao(pf, "PULSADO")
        self.add(pf, "Vp_set", Campo(pf, "Pulso SET", 7.0, "V"))
        self.add(pf, "Vp_reset", Campo(pf, "Pulso RESET", -4.0, "V"))
        self.add(pf, "w", Campo(pf, "Largura", 50, "ms"))
        self.add(pf, "nplc_pulso", Campo(pf, "NPLC no pulso", 0.01))
        secao(pf, "LEITURA E ARQUIVOS")
        self.add(pf, "V_read", Campo(pf, "V de leitura", 1.0, "V"))
        self.add(pf, "t_read", Campo(pf, "Tempo de leitura", 0.2, "s"))
        self.add(pf, "media_read", Campo(pf, "Media do ultimo trecho", 0.1, "s"))
        self.add(pf, "nplc_read", Campo(pf, "NPLC da leitura", 1))
        self.add(pf, "bloco", Campo(pf, "Ciclos por arquivo (B1, B2...)", 100))
        self.add(pf, "parar_ruptura", Marca(pf, "Parar se leitura > 0,9 x compliance", True))

    def parametros(self):
        c = self.campos
        p = dict(modo=c["modo"].get(), N=int(c["N"].val), v_set=_vertices(c["v_set"]), v_reset=_vertices(c["v_reset"]),
                 guardar_curvas=c["guardar_curvas"].get(), passo=c["passo"].val, atraso=c["atraso"].val,
                 nplc=c["nplc"].val, compliance=c["compliance"].val, faixa_i=_faixa(c["faixa_i"].get()),
                 Vp_set=c["Vp_set"].val, Vp_reset=c["Vp_reset"].val, w=c["w"].val / 1e3,
                 nplc_pulso=c["nplc_pulso"].val, V_read=c["V_read"].val, t_read=c["t_read"].val,
                 media_read=c["media_read"].val, nplc_read=c["nplc_read"].val, bloco=int(c["bloco"].val),
                 parar_ruptura=c["parar_ruptura"].get())
        _validar_limites(max(map(abs, p["v_set"] + p["v_reset"] + [p["Vp_set"], p["Vp_reset"]])), p["compliance"])
        return p

    def executar(self, motor, p):
        motor.exp_ciclos(p)

    def plotar(self, g, pts):
        g.limpar()
        ax = g.ax
        pts = [p for p in pts if "ciclo" in p and "razao" in p]
        if not pts:
            ax.set_xlabel("ciclo")
            return
        x = [p["ciclo"] for p in pts]
        if self.vis.get() == "Razao":
            ax.plot(x, [p["razao"] for p in pts], "o-", ms=2, color=C["gold"])
            ax.set_ylabel("I_LRS / I_HRS")
        else:
            ax.semilogy(x, [abs(p["I_LRS_read_A"]) for p in pts], "o-", ms=2, color=C["red"], label="apos SET")
            ax.semilogy(x, [abs(p["I_HRS_read_A"]) for p in pts], "o-", ms=2, color=C["blue"], label="apos RESET")
            ax.set_ylabel("|I_leitura| (A)")
            ax.legend(fontsize=8)
        ax.set_xlabel("ciclo")


# =============================================================== retencao
def _campos_preparo(self, pf):
    secao(pf, "PREPARO (escrita imediatamente antes)")
    self.add(pf, "preparo", Opcao(pf, "Preparo", ["nenhum", "varredura", "pulsos"], segmentado=True))
    self.add(pf, "prep_vertices", Campo(pf, "Varredura (vertices)", "0, 10, 0", "V"))
    self.add(pf, "prep_passo", Campo(pf, "Passo da varredura", 0.1, "V"))
    self.add(pf, "prep_atraso", Campo(pf, "Atraso por ponto", 0.1, "s"))
    self.add(pf, "prep_V", Campo(pf, "Pulsos: V", 7.0, "V"))
    self.add(pf, "prep_w", Campo(pf, "Pulsos: largura", 50, "ms"))
    self.add(pf, "prep_n", Campo(pf, "Pulsos: numero (trem)", 1))


def _p_preparo(c):
    p = dict(preparo=c["preparo"].get(), prep_passo=c["prep_passo"].val, prep_atraso=c["prep_atraso"].val,
             prep_V=c["prep_V"].val, prep_w=c["prep_w"].val / 1e3, prep_n=int(c["prep_n"].val))
    if p["preparo"] == "varredura":
        p["prep_vertices"] = _vertices(c["prep_vertices"], "Preparo")
    return p


class AbaRetencao(AbaMedida):
    NOME = "Retencao"
    ETAPA = "G09-R2"
    EVENTOS = True
    VISTAS = ["log-log", "I x t"]
    T_LOG = "1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000"
    PRESETS = {
        "G09-R1 perturbacao +1 V (1000 x 0,1 s, 0,9 s a 0 V)": dict(preparo="varredura", prep_vertices="0, 10, 0", V_read=1, t_on=0.1, media=0.05, agenda="Periodica", periodo=1.0, n_leituras=1000, entre="0 V", etapa="G09-R1", param="RD1V"),
        "G09-R1 perturbacao +0,5 V": dict(preparo="varredura", prep_vertices="0, 10, 0", V_read=0.5, t_on=0.1, media=0.05, agenda="Periodica", periodo=1.0, n_leituras=1000, entre="0 V", etapa="G09-R1", param="RD0p5V"),
        "G09-R2 retencao LRS (SET, ate 10^4 s)": dict(preparo="varredura", prep_vertices="0, 10, 0", V_read=1, t_on=1, media=0.5, agenda="Tempos (lista)", tempos=T_LOG, entre="0 V", etapa="G09-R2", param="LRS"),
        "G09-R2 retencao HRS (RESET, ate 10^4 s)": dict(preparo="varredura", prep_vertices="0, -5, 0", V_read=1, t_on=1, media=0.5, agenda="Tempos (lista)", tempos=T_LOG, entre="0 V", etapa="G09-R2", param="HRS"),
        "G09-R3 pad de referencia (sem escrita)": dict(preparo="nenhum", V_read=1, t_on=1, media=0.5, agenda="Tempos (lista)", tempos=T_LOG, entre="0 V", etapa="G09-R3", param="REF"),
        "G11-S4 trem de 5 pulsos +7 V, leituras 1..1000 s": dict(preparo="pulsos", prep_V=7, prep_w=50, prep_n=5, V_read=1, t_on=0.2, media=0.1, agenda="Tempos (lista)", tempos="1, 3, 10, 30, 100, 300, 1000", entre="0 V", etapa="G11-S4", param="N5"),
    }

    def construir(self, pf):
        _campos_preparo(self, pf)
        secao(pf, "LEITURAS")
        self.add(pf, "V_read", Campo(pf, "V de leitura", 1.0, "V"))
        self.add(pf, "t_on", Campo(pf, "Tempo em V_leitura", 1.0, "s"))
        self.add(pf, "media", Campo(pf, "Media do ultimo trecho", 0.5, "s"))
        self.add(pf, "nplc", Campo(pf, "NPLC", 1))
        self.add(pf, "compliance", Campo(pf, "Compliance", 0.01, "A"))
        self.add(pf, "faixa_i", Opcao(pf, "Faixa de corrente", FAIXAS_I))
        self.add(pf, "agenda", Opcao(pf, "Agenda", ["Tempos (lista)", "Periodica"], segmentado=True))
        self.add(pf, "tempos", Campo(pf, "Tempos apos a escrita", self.T_LOG, "s"))
        self.add(pf, "periodo", Campo(pf, "Periodo (periodica)", 1.0, "s"))
        self.add(pf, "n_leituras", Campo(pf, "Numero de leituras (periodica)", 100))
        self.add(pf, "entre", Opcao(pf, "Entre leituras", ["0 V", "flutuante (HIMP)"], segmentado=True))
        nota(pf, "Flutuante abre o rele de saida entre as leituras (o capacitor fica em aberto e retem a carga).")

    def parametros(self):
        c = self.campos
        p = _p_preparo(c)
        p.update(V_read=c["V_read"].val, t_on=c["t_on"].val, media=c["media"].val, nplc=c["nplc"].val,
                 compliance=c["compliance"].val, faixa_i=_faixa(c["faixa_i"].get()),
                 entre="flutuante" if c["entre"].get().startswith("flut") else "0V")
        if c["agenda"].get().startswith("Tempos"):
            p["tempos"] = c["tempos"].lista()
        else:
            p["tempos"] = None
            p["periodo"] = c["periodo"].val
            p["n_leituras"] = int(c["n_leituras"].val)
            if p["periodo"] < p["t_on"] + 0.05:
                raise ValueError("O periodo deve ser maior que o tempo de leitura (+ ~50 ms de comunicacao).")
        return p

    def executar(self, motor, p):
        motor.exp_retencao(p)

    def plotar(self, g, pts):
        g.limpar()
        ax = g.ax
        pts = [p for p in pts if "I_A" in p and "t_s" in p]
        if not pts:
            ax.set_xlabel("t apos a escrita (s)")
            return
        t = np.array([p["t_s"] for p in pts]); I = np.abs([p["I_A"] for p in pts])
        if self.vis.get() == "log-log":
            m = t > 0
            ax.loglog(t[m], I[m], "o-", ms=3, color=C["gold"])
        else:
            ax.plot(t, I, "o-", ms=3, color=C["gold"])
            log_y(ax, I)
        for p in pts:
            if p.get("evento"):
                ax.axvline(p["t_s"], color=C["red"], lw=0.7, ls=":")
        ax.set_xlabel("t apos a escrita (s)"); ax.set_ylabel("|I_leitura| (A)")


# =============================================================== transientes / V fixo / Voc
def _segmentos(txt):
    txt = (txt or "").strip()
    if not txt:
        raise ValueError("Informe os segmentos 'V:duracao' (ex.: 8:30, 0:30).")
    sep = ";" if ";" in txt else ","
    out = []
    for item in txt.split(sep):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(f"Segmento '{item}' sem ':' (formato V:duracao).")
        a, b = item.split(":", 1)
        out.append((float(a.replace(",", ".")), float(b.replace(",", "."))))
    return out


class AbaTransiente(AbaMedida):
    NOME = "I(t), V fixo e V_oc"
    ETAPA = "G17"
    EVENTOS = True
    VISTAS = ["linear", "log|y|", "log-log"]
    PRESETS = {
        "G07-T4 manutencao 14 V/60 s -> 9 V/30 s": dict(modo="V fixo -> I(t)", segmentos="14:60, 9:30", intervalo=0.2, compliance=0.05, preparo="nenhum", etapa="G07-T4", param="IT"),
        "G09-R1 DC +1 V por 600 s": dict(modo="V fixo -> I(t)", segmentos="1:600", intervalo=1.0, preparo="varredura", prep_vertices="0, 10, 0", etapa="G09-R1", param="DC1V"),
        "G16-L1 +8 V por 150 s (marque luz ON/OFF)": dict(modo="V fixo -> I(t)", segmentos="8:150", intervalo=0.2, preparo="nenhum", etapa="G16-L1", param="Vp8p0"),
        "G16-L5 / patamar +8 V por 10 s": dict(modo="V fixo -> I(t)", segmentos="8:10", intervalo=0.1, preparo="nenhum", etapa="G15", param="PLAT"),
        "G17 VOC_LRS (SET -> I = 0, 300 s)": dict(modo="I = 0 -> V_oc(t)", dur_voc=300, intervalo=0.5, rapida_n=100, rapida_dt=0.01, preparo="varredura", prep_vertices="0, 10, 0", etapa="G17", param="VOC_LRS"),
        "G17 VOC_HRS (RESET -> I = 0, 300 s)": dict(modo="I = 0 -> V_oc(t)", dur_voc=300, intervalo=0.5, rapida_n=100, rapida_dt=0.01, preparo="varredura", prep_vertices="0, -5, 0", etapa="G17", param="VOC_HRS"),
        "G17 ISC_LRS (SET -> 0 V, 120 s)": dict(modo="V fixo -> I(t)", segmentos="0:120", intervalo=0.5, rapida_n=100, rapida_dt=0.01, preparo="varredura", prep_vertices="0, 10, 0", etapa="G17", param="ISC_LRS"),
        "G17 ISC_HRS (RESET -> 0 V, 120 s)": dict(modo="V fixo -> I(t)", segmentos="0:120", intervalo=0.5, rapida_n=100, rapida_dt=0.01, preparo="varredura", prep_vertices="0, -5, 0", etapa="G17", param="ISC_HRS"),
        "G17 VOC_virgem (120 s)": dict(modo="I = 0 -> V_oc(t)", dur_voc=120, intervalo=0.5, preparo="nenhum", etapa="G17", param="VOC_virgem"),
        "Capacitor: degrau 0 -> +1 V -> 0 (carga e absorcao)": dict(modo="V fixo -> I(t)", segmentos="1:60, 0:60", intervalo=0.5, rapida_n=500, rapida_dt=0.002, nplc=0.01, preparo="nenhum", etapa="CAP", param="degrau1V"),
    }

    def construir(self, pf):
        self.add(pf, "modo", Opcao(pf, "Modo", ["V fixo -> I(t)", "I = 0 -> V_oc(t)"], segmentado=False))
        self.add(pf, "segmentos", Campo(pf, "Segmentos V:duracao (V fixo)", "8:30, 0:30",
                                        dica="Ex.: '14:60, 9:30' = 14 V por 60 s e 9 V por 30 s, sem desligar."))
        self.add(pf, "dur_voc", Campo(pf, "Duracao (V_oc)", 300, "s"))
        self.add(pf, "limite_v", Campo(pf, "Limite de V (V_oc)", 5.0, "V"))
        self.add(pf, "intervalo", Campo(pf, "Intervalo entre amostras", 0.5, "s"))
        self.add(pf, "rapida_n", Campo(pf, "Captura rapida inicial: pontos", 0,
                                       dica="Rajada temporizada pelo 2400 no inicio de cada segmento (ate 2500 pontos)."))
        self.add(pf, "rapida_dt", Campo(pf, "Captura rapida: intervalo", 0.002, "s"))
        self.add(pf, "nplc", Campo(pf, "NPLC", 1))
        self.add(pf, "compliance", Campo(pf, "Compliance", 0.01, "A"))
        self.add(pf, "faixa_i", Opcao(pf, "Faixa de corrente", FAIXAS_I))
        _campos_preparo(self, pf)
        self.campos["preparo"].set("nenhum")

    def parametros(self):
        c = self.campos
        p = _p_preparo(c)
        modo = "Voc" if c["modo"].get().startswith("I = 0") else "V"
        p.update(modo=modo, dur_voc=c["dur_voc"].val, limite_v=c["limite_v"].val, intervalo=c["intervalo"].val,
                 rapida_n=int(c["rapida_n"].val), rapida_dt=c["rapida_dt"].val, nplc=c["nplc"].val,
                 compliance=c["compliance"].val, faixa_i=_faixa(c["faixa_i"].get()))
        if modo == "V":
            p["segmentos"] = _segmentos(c["segmentos"].txt)
            _validar_limites(max(abs(v) for v, _ in p["segmentos"]), p["compliance"])
        return p

    def executar(self, motor, p):
        motor.exp_transiente(p)

    def plotar(self, g, pts):
        g.limpar()
        ax = g.ax
        if not pts:
            ax.set_xlabel("t (s)")
            return
        voc = all(p.get("I_A", 0) == 0 for p in pts[:5]) and self.campos["modo"].get().startswith("I = 0")
        t = np.array([p["t_s"] for p in pts])
        y = np.array([p["V_V"] if voc else p["I_A"] for p in pts])
        v = self.vis.get()
        if v == "log-log":
            m = (t > 0) & (np.abs(y) > 0)
            ax.loglog(t[m], np.abs(y[m]), ".", ms=3, color=C["gold"])
        elif v == "log|y|":
            ax.semilogy(t, np.abs(y), ".-", ms=3, lw=0.6, color=C["gold"])
        else:
            ax.plot(t, y, ".-", ms=3, lw=0.6, color=C["gold"])
        for p in pts:
            if p.get("evento"):
                ax.axvline(p["t_s"], color=C["red"], lw=0.8, ls=":")
                ax.text(p["t_s"], ax.get_ylim()[1], p["evento"], fontsize=7, color=C["red"], va="top", rotation=90)
        ax.set_xlabel("t (s)")
        ax.set_ylabel("V_oc (V)" if voc else "I (A)")
