"""Abas de celulas solares e diodos."""
import numpy as np

from .base import AbaMedida, Campo, Opcao, secao, nota, C, PALETA
from .mis import FAIXAS_I, MODOS_T, _faixa, _modo, _validar_limites
from .. import analise as an


def _campos_celula(self, pf, area=0.1, Pin=100.0):
    secao(pf, "CELULA")
    self.add(pf, "area", Campo(pf, "Area ativa", area, "cm2"))
    self.add(pf, "Pin", Campo(pf, "Irradiancia", Pin, "mW/cm2", dica="AM1.5G = 100 mW/cm2."))


class AbaJV(AbaMedida):
    NOME = "Curva J-V"
    ETAPA = "SOL-JV"
    PARAM = ""
    VISTAS = ["J-V", "P-V", "log|J|"]
    PRESETS = {
        "AM1.5G, reverso + direto (histerese)": dict(sentido="reverso+direto", luz="claro", Vmin=-0.1, Vmax=1.2, passo=0.01, atraso=0.05, Pin=100, etapa="SOL-JV", param="claro"),
        "AM1.5G, so reverso": dict(sentido="reverso", luz="claro", etapa="SOL-JV", param="claro"),
        "Escuro, -0,5 a +1,2 V": dict(sentido="direto", luz="escuro", Vmin=-0.5, Vmax=1.2, etapa="SOL-JV", param="escuro"),
    }

    def construir(self, pf):
        secao(pf, "VARREDURA")
        self.add(pf, "Vmin", Campo(pf, "V minimo", -0.1, "V"))
        self.add(pf, "Vmax", Campo(pf, "V maximo (acima de Voc)", 1.2, "V"))
        self.add(pf, "passo", Campo(pf, "Passo", 0.01, "V"))
        self.add(pf, "atraso", Campo(pf, "Atraso por ponto", 0.05, "s",
                                     dica="Taxa = passo / (atraso + medida). Perovskitas: a histerese depende disso."))
        self.add(pf, "nplc", Campo(pf, "NPLC", 1))
        self.add(pf, "compliance", Campo(pf, "Compliance", 0.1, "A"))
        self.add(pf, "faixa_i", Opcao(pf, "Faixa de corrente", FAIXAS_I))
        self.add(pf, "sentido", Opcao(pf, "Sentido", ["reverso", "direto", "reverso+direto", "direto+reverso"]))
        self.add(pf, "repeticoes", Campo(pf, "Repeticoes", 1))
        self.add(pf, "modo", Opcao(pf, "Temporizacao", MODOS_T))
        self.add(pf, "luz", Opcao(pf, "Condicao", ["claro", "escuro"], segmentado=True))
        _campos_celula(self, pf)
        nota(pf, "Use 4 fios (aba Instrumento) para que Rs dos cabos/pontas nao entre na curva. "
                 "Convencao: J > 0 = corrente gerada (J = -I/A).")

    def parametros(self):
        c = self.campos
        p = dict(Vmin=c["Vmin"].val, Vmax=c["Vmax"].val, passo=c["passo"].val, atraso=c["atraso"].val,
                 nplc=c["nplc"].val, compliance=c["compliance"].val, faixa_i=_faixa(c["faixa_i"].get()),
                 sentido=c["sentido"].get(), repeticoes=int(c["repeticoes"].val), modo=_modo(c["modo"].get()),
                 luz=c["luz"].get(), area_cm2=c["area"].val, Pin=c["Pin"].val)
        if p["Vmax"] <= p["Vmin"]:
            raise ValueError("V maximo deve ser maior que V minimo.")
        if p["area_cm2"] <= 0:
            raise ValueError("Area deve ser > 0.")
        _validar_limites(max(abs(p["Vmin"]), abs(p["Vmax"])), p["compliance"])
        return p

    def executar(self, motor, p):
        motor.exp_jv(p)

    def plotar(self, g, pts):
        v = self.vis.get()
        g.limpar(gemeo=False)
        ax = g.ax
        A = max(1e-12, self._area())
        if not pts:
            ax.set_xlabel("V (V)"); ax.set_ylabel("J (mA/cm2)")
            return
        grupos = {}
        for p in pts:
            grupos.setdefault((p.get("sentido"), p.get("rep", 1)), []).append(p)
        for j, ((s, r), sub) in enumerate(grupos.items()):
            V = np.array([p["V"] for p in sub]); I = np.array([p["I"] for p in sub])
            J = -I / A * 1e3
            cor = PALETA[j % len(PALETA)]
            lab = f"{'reverso' if s == 'rev' else 'direto'} {r}"
            if v == "P-V":
                ax.plot(V, V * J, "-", color=cor, label=lab); ax.set_ylabel("P (mW/cm2)")
            elif v == "log|J|":
                ax.semilogy(V, np.abs(J), "-", color=cor, label=lab); ax.set_ylabel("|J| (mA/cm2)")
            else:
                ax.plot(V, J, "-o", ms=1.5, color=cor, label=lab); ax.set_ylabel("J (mA/cm2)")
                ax.axhline(0, color=C["faint"], lw=0.6); ax.axvline(0, color=C["faint"], lw=0.6)
                if self.campos["luz"].get() == "claro":
                    ps = an.parametros_solar(V, I, A, self._pin())
                    if np.isfinite(ps["Vmp_V"]):
                        ax.plot([ps["Vmp_V"]], [ps["Jmp_mA_cm2"]], "s", color=cor, ms=6)
                    if j == len(grupos) - 1 and np.isfinite(ps["Voc_V"]):
                        ax.text(0.02, 0.04, f"Voc {ps['Voc_V']:.4f} V   Jsc {ps['Jsc_mA_cm2']:.2f} mA/cm2   "
                                             f"FF {ps['FF']:.3f}   PCE {ps['PCE_pct']:.2f} %",
                                transform=ax.transAxes, fontsize=8, color=C["text"])
        ax.set_xlabel("V (V)")
        ax.legend(fontsize=8)

    def _area(self):
        try:
            return self.campos["area"].val
        except Exception:
            return 1.0

    def _pin(self):
        try:
            return self.campos["Pin"].val
        except Exception:
            return 100.0


class AbaDiodo(AbaMedida):
    NOME = "Diodo (escuro)"
    ETAPA = "SOL-DIO"
    PARAM = "escuro"
    VISTAS = ["log|J| x V", "n local", "J x V"]
    PRESETS = {
        "Diodo -1 a +1 V": dict(Vmin=-1, Vmax=1, passo=0.01, vertices="", etapa="SOL-DIO", param="escuro"),
        "Diodo MIS (10 h) -5 a +5 V": dict(Vmin=-5, Vmax=5, passo=0.05, vertices="", compliance=0.05, V1=0.2, V2=0.8, Vrr=2, etapa="G04-DIO", param=""),
        "Laco 0 > +1 > -1 > 0 V": dict(vertices="0, 1, -1, 0", etapa="SOL-DIO", param="laco"),
    }

    def construir(self, pf):
        secao(pf, "VARREDURA")
        self.add(pf, "Vmin", Campo(pf, "V inicial", -1.0, "V"))
        self.add(pf, "Vmax", Campo(pf, "V final", 1.0, "V"))
        self.add(pf, "vertices", Campo(pf, "ou vertices (opcional)", "", "V", dica="Ex.: 0, 1, -1, 0. Se preenchido, substitui V inicial/final."))
        self.add(pf, "passo", Campo(pf, "Passo", 0.01, "V"))
        self.add(pf, "atraso", Campo(pf, "Atraso por ponto", 0.05, "s"))
        self.add(pf, "nplc", Campo(pf, "NPLC", 1))
        self.add(pf, "compliance", Campo(pf, "Compliance", 0.1, "A"))
        self.add(pf, "faixa_i", Opcao(pf, "Faixa de corrente", FAIXAS_I))
        self.add(pf, "modo", Opcao(pf, "Temporizacao", MODOS_T))
        secao(pf, "ANALISE")
        self.add(pf, "area", Campo(pf, "Area", 0.1, "cm2"))
        self.add(pf, "T", Campo(pf, "Temperatura", 300, "K"))
        self.add(pf, "V1", Campo(pf, "Ajuste de n: V de", 0.3, "V"))
        self.add(pf, "V2", Campo(pf, "ate", 0.6, "V"))
        self.add(pf, "Vrr", Campo(pf, "Razao de retificacao em +/-", 1.0, "V"))
        nota(pf, "n e I0 do ajuste ln I = ln I0 + qV/(n k T) na faixa escolhida. Use a vista 'n local' para "
                 "escolher a faixa (patamar de n; abaixo dela domina Rsh, acima, Rs).")

    def parametros(self):
        c = self.campos
        p = dict(Vmin=c["Vmin"].val, Vmax=c["Vmax"].val, vertices=c["vertices"].lista() or None,
                 passo=c["passo"].val, atraso=c["atraso"].val, nplc=c["nplc"].val, compliance=c["compliance"].val,
                 faixa_i=_faixa(c["faixa_i"].get()), modo=_modo(c["modo"].get()), area_cm2=c["area"].val,
                 T=c["T"].val, V1=c["V1"].val, V2=c["V2"].val, Vrr=c["Vrr"].val)
        vs = p["vertices"] or [p["Vmin"], p["Vmax"]]
        _validar_limites(max(map(abs, vs)), p["compliance"])
        return p

    def executar(self, motor, p):
        motor.exp_diodo(p)

    def plotar(self, g, pts):
        g.limpar()
        ax = g.ax
        if not pts:
            ax.set_xlabel("V (V)")
            return
        V = np.array([p["V"] for p in pts]); I = np.array([p["I"] for p in pts])
        try:
            A = self.campos["area"].val; T = self.campos["T"].val
            V1, V2 = self.campos["V1"].val, self.campos["V2"].val
        except Exception:
            A, T, V1, V2 = 1.0, 300.0, 0.3, 0.6
        v = self.vis.get()
        if v == "n local":
            Vn, n = an.n_local(V, I, T)
            ax.plot(Vn, n, ".-", color=C["gold"])
            ax.set_ylim(0, 6)
            ax.axvspan(V1, V2, color=C["acc"], alpha=0.15)
            ax.set_ylabel("n local")
        elif v == "J x V":
            ax.plot(V, I / A, "-o", ms=1.5, color=C["blue"]); ax.set_ylabel("J (A/cm2)")
        else:
            ax.semilogy(V, np.abs(I) / A, "-o", ms=1.5, color=C["blue"])
            aj = an.ajuste_diodo(V, I, V1, V2, T)
            if np.isfinite(aj["n"]):
                x = np.linspace(V1, V2, 50)
                ax.semilogy(x, aj["I0_A"] * np.exp(x / (aj["n"] * an.vt(T))) / A, "--", color=C["red"],
                            label=f"n = {aj['n']:.3f}, J0 = {aj['I0_A']/A:.2e} A/cm2")
                ax.legend(fontsize=8)
            ax.set_ylabel("|J| (A/cm2)")
        ax.set_xlabel("V (V)")


class AbaEstabilidade(AbaMedida):
    NOME = "Estabilidade / MPPT"
    ETAPA = "SOL-EST"
    EVENTOS = True
    VISTAS = ["P(t)", "V(t)", "J(t)"]
    PRESETS = {
        "MPPT 10 min (P&O, 5 mV)": dict(modo="MPPT", V0=0.5, dV=0.005, duracao=600, intervalo=1, etapa="SOL-EST", param="MPPT"),
        "Voc(t) 5 min": dict(modo="Voc", duracao=300, intervalo=0.5, etapa="SOL-EST", param="Voc"),
        "Isc(t) 5 min": dict(modo="Isc", duracao=300, intervalo=0.5, etapa="SOL-EST", param="Isc"),
    }

    def construir(self, pf):
        self.add(pf, "modo", Opcao(pf, "Modo", ["MPPT", "V fixo", "Voc", "Isc"], segmentado=True))
        self.add(pf, "V0", Campo(pf, "V inicial (MPPT) / V fixo", 0.5, "V"))
        self.add(pf, "dV", Campo(pf, "Passo do MPPT (perturba e observa)", 0.005, "V"))
        self.add(pf, "duracao", Campo(pf, "Duracao", 600, "s"))
        self.add(pf, "intervalo", Campo(pf, "Intervalo", 1.0, "s"))
        self.add(pf, "nplc", Campo(pf, "NPLC", 1))
        self.add(pf, "compliance", Campo(pf, "Compliance", 0.1, "A"))
        self.add(pf, "limite_v", Campo(pf, "Limite de V (Voc)", 3.0, "V"))
        _campos_celula(self, pf)

    def parametros(self):
        c = self.campos
        return dict(modo=c["modo"].get(), V0=c["V0"].val, dV=c["dV"].val, duracao=c["duracao"].val,
                    intervalo=c["intervalo"].val, nplc=c["nplc"].val, compliance=c["compliance"].val,
                    limite_v=c["limite_v"].val, area_cm2=c["area"].val, Pin=c["Pin"].val)

    def executar(self, motor, p):
        motor.exp_estabilidade(p)

    def plotar(self, g, pts):
        g.limpar()
        ax = g.ax
        if not pts:
            ax.set_xlabel("t (s)")
            return
        t = [p["t_s"] for p in pts]
        v = self.vis.get()
        k, rot = {"P(t)": ("P_mW_cm2", "P (mW/cm2)"), "V(t)": ("V_V", "V (V)"), "J(t)": ("J_mA_cm2", "J (mA/cm2)")}[v]
        ax.plot(t, [p[k] for p in pts], ".-", ms=3, lw=0.7, color=C["gold"])
        for p in pts:
            if p.get("evento"):
                ax.axvline(p["t_s"], color=C["red"], lw=0.8, ls=":")
        ax.set_xlabel("t (s)"); ax.set_ylabel(rot)
