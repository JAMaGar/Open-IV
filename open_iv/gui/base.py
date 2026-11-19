"""Tema, widgets e a classe base das abas de medida."""
import threading
import time
import traceback
from datetime import datetime
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from ..medidas import Contexto, Motor, Cancelado, parse_lista
from ..keithley import ErroInstrumento

TEMAS = {
    "Escuro": {
        "bg": "#15181C", "panel": "#1E2329", "input": "#262C33", "border": "#333B44",
        "border_hi": "#46505B", "text": "#EEF1F4", "dim": "#A9B2BC", "muted": "#7E8994",
        "faint": "#56616C", "acc": "#1F6F8B", "acc_hi": "#2A8DB0", "gold": "#E0B04A",
        "red": "#D9534F", "orange": "#E08A3C", "green": "#3FB27F", "green_dark": "#1D3B2E",
        "blue": "#4A90D9", "violet": "#9B7BD4", "danger_bg": "#4A1C1C", "danger_hi": "#6A2626",
        "danger_fg": "#FF8A80", "tip": "#2B323A", "on_acc": "#FFFFFF",
    },
    "Claro": {
        "bg": "#F7F8FA", "panel": "#FFFFFF", "input": "#EEF1F5", "border": "#D3D9E0",
        "border_hi": "#AEB8C4", "text": "#1C2430", "dim": "#3E4A58", "muted": "#5F6B78",
        "faint": "#8A95A1", "acc": "#1F6F8B", "acc_hi": "#2A8DB0", "gold": "#9A6A00",
        "red": "#C0392B", "orange": "#C46A1A", "green": "#1E8A5A", "green_dark": "#DDF2E7",
        "blue": "#1F5FAD", "violet": "#6C4BB0", "danger_bg": "#FBE3E1", "danger_hi": "#F5C6C2",
        "danger_fg": "#A12A20", "tip": "#FFFBE6", "on_acc": "#FFFFFF",
    },
}
PALETAS = {
    "Escuro": ["#4A90D9", "#E0B04A", "#D9534F", "#3FB27F", "#9B7BD4", "#E08A3C", "#5BC0DE", "#C9C9C9"],
    "Claro": ["#1F5FAD", "#B07800", "#C0392B", "#1E8A5A", "#6C4BB0", "#C46A1A", "#138496", "#555555"],
}
C = dict(TEMAS["Escuro"])
PALETA = list(PALETAS["Escuro"])
TEMA = {"nome": "Escuro"}


def aplicar_tema(nome):
    """Atualiza a paleta (C, PALETA) e o estilo do matplotlib. Widgets ja criados nao mudam."""
    nome = nome if nome in TEMAS else "Escuro"
    TEMA["nome"] = nome
    C.clear(); C.update(TEMAS[nome])
    PALETA[:] = PALETAS[nome]
    ctk.set_appearance_mode("dark" if nome == "Escuro" else "light")
    matplotlib.rcParams.update({
        "figure.facecolor": C["panel"], "axes.facecolor": C["bg"] if nome == "Escuro" else "#FFFFFF",
        "axes.edgecolor": C["border_hi"], "axes.labelcolor": C["dim"], "xtick.color": C["muted"],
        "ytick.color": C["muted"], "grid.color": C["border"], "grid.alpha": 0.6, "text.color": C["text"],
        "legend.facecolor": C["panel"], "legend.edgecolor": C["border"], "font.size": 9,
        "axes.prop_cycle": matplotlib.cycler(color=PALETA), "axes.titlecolor": C["text"],
    })


aplicar_tema("Escuro")

FONTE = "Segoe UI"


# ============================================================ widgets
class Campo(ctk.CTkFrame):
    """Campo numerico (ou texto) com rotulo e unidade."""

    def __init__(self, master, rotulo, padrao="", unidade="", dica="", largura=None):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=rotulo, font=(FONTE, 11), text_color=C["muted"], anchor="w"
                     ).grid(row=0, column=0, columnspan=2, sticky="w")
        self.var = ctk.StringVar(value=str(padrao))
        self.ent = ctk.CTkEntry(self, textvariable=self.var, height=26, font=("Consolas", 11),
                                fg_color=C["bg"], border_color=C["border"], text_color=C["text"],
                                border_width=1, corner_radius=5)
        self.ent.grid(row=1, column=0, sticky="ew", padx=(0, 4))
        if unidade:
            ctk.CTkLabel(self, text=unidade, font=("Consolas", 10), text_color=C["faint"], width=30
                         ).grid(row=1, column=1)
        if dica:
            Dica(self.ent, dica)

    @property
    def val(self):
        t = self.var.get().strip().replace(",", ".")
        try:
            return float(t)
        except ValueError:
            raise ValueError(f"Valor invalido: '{self.var.get()}'")

    @property
    def txt(self):
        return self.var.get().strip()

    def lista(self):
        return parse_lista(self.var.get())

    def get(self):
        return self.var.get()

    def set(self, v):
        self.var.set(str(v))


class Opcao(ctk.CTkFrame):
    def __init__(self, master, rotulo, valores, padrao=None, comando=None, segmentado=False):
        super().__init__(master, fg_color="transparent")
        ctk.CTkLabel(self, text=rotulo, font=(FONTE, 11), text_color=C["muted"], anchor="w").pack(fill="x")
        self.var = ctk.StringVar(value=padrao or valores[0])
        cmd = (lambda _=None: comando()) if comando else None
        if segmentado:
            w = ctk.CTkSegmentedButton(self, values=valores, variable=self.var, font=(FONTE, 10),
                                       selected_color=C["acc"], selected_hover_color=C["acc_hi"],
                                       unselected_color=C["input"], unselected_hover_color=C["border"],
                                       fg_color=C["input"], text_color=C["text"], command=cmd)
        else:
            w = ctk.CTkOptionMenu(self, values=valores, variable=self.var, height=26, font=(FONTE, 11),
                                  fg_color=C["input"], button_color=C["border_hi"],
                                  button_hover_color=C["acc"], dropdown_fg_color=C["panel"],
                                  text_color=C["text"], command=cmd)
        w.pack(fill="x", pady=(1, 0))
        self.w = w

    def get(self):
        return self.var.get()

    def set(self, v):
        self.var.set(v)


class Marca(ctk.CTkCheckBox):
    def __init__(self, master, texto, padrao=False, comando=None):
        self.var = ctk.BooleanVar(value=padrao)
        super().__init__(master, text=texto, variable=self.var, font=(FONTE, 11), text_color=C["dim"],
                         fg_color=C["acc"], hover_color=C["acc_hi"], border_color=C["border_hi"],
                         checkbox_width=18, checkbox_height=18, command=comando)

    def get(self):
        return bool(self.var.get())

    def set(self, v):
        self.var.set(bool(v) if not isinstance(v, str) else v in ("1", "True", "true"))


class Btn(ctk.CTkButton):
    @staticmethod
    def _estilos():
        return {
            "primary": dict(fg_color=C["acc"], hover_color=C["acc_hi"], text_color=C["on_acc"]),
            "danger": dict(fg_color=C["danger_bg"], hover_color=C["danger_hi"], text_color=C["danger_fg"],
                           border_width=1, border_color=C["danger_hi"]),
            "secondary": dict(fg_color=C["input"], hover_color=C["border"], text_color=C["dim"],
                              border_width=1, border_color=C["border_hi"]),
            "success": dict(fg_color=C["green_dark"], hover_color=C["border"], text_color=C["green"],
                            border_width=1, border_color=C["green"]),
        }

    def __init__(self, master, texto, estilo="primary", **kw):
        est = self._estilos()
        s = est.get(estilo, est["primary"]).copy()
        s.update(kw)
        super().__init__(master, text=texto, height=30, corner_radius=6, font=(FONTE, 11, "bold"), **s)


class Dica:
    """Tooltip simples."""

    def __init__(self, w, texto):
        self.w, self.texto, self.tip = w, texto, None
        w.bind("<Enter>", self._mostrar, add="+")
        w.bind("<Leave>", self._esconder, add="+")

    def _mostrar(self, _=None):
        if self.tip:
            return
        x = self.w.winfo_rootx() + 10
        y = self.w.winfo_rooty() + self.w.winfo_height() + 4
        self.tip = tk.Toplevel(self.w)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.texto, justify="left", bg=C["tip"], fg=C["text"],
                 relief="solid", borderwidth=1, font=(FONTE, 9), wraplength=360, padx=6, pady=4).pack()

    def _esconder(self, _=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


def secao(master, texto):
    ctk.CTkLabel(master, text=texto, font=(FONTE, 10, "bold"), text_color=C["gold"], anchor="w"
                 ).pack(fill="x", pady=(10, 2))


def nota(master, texto):
    ctk.CTkLabel(master, text=texto, font=(FONTE, 10), text_color=C["faint"], justify="left",
                 anchor="w", wraplength=270).pack(fill="x", pady=(0, 4))


class LogView(ctk.CTkFrame):
    def __init__(self, master, tamanho=10):
        super().__init__(master, fg_color=C["panel"], corner_radius=8, border_width=1, border_color=C["border"])
        self.tamanho = tamanho
        self.txt = tk.Text(self, bg=C["bg"], fg=C["dim"], insertbackground=C["text"], font=("Consolas", tamanho),
                           wrap="word", bd=0, highlightthickness=0, padx=8, pady=6, state="disabled")
        sb = ctk.CTkScrollbar(self, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y", padx=(0, 3), pady=3)
        tags = {"tx": C["blue"], "rx": C["green"], "info": C["dim"], "warn": C["gold"], "error": C["red"]}
        for t, c in tags.items():
            self.txt.tag_configure(t, foreground=c)
        self.txt.tag_configure("hora", foreground=C["faint"])

    def fonte(self, tamanho):
        self.tamanho = max(7, min(28, int(tamanho)))
        self.txt.configure(font=("Consolas", self.tamanho))

    def log(self, msg, tag="info", hora=None):
        self.txt.configure(state="normal")
        self.txt.insert("end", (hora or datetime.now().strftime("%H:%M:%S")) + "  ", "hora")
        self.txt.insert("end", f"{msg}\n", tag)
        n = int(self.txt.index("end-1c").split(".")[0])
        if n > 4000:
            self.txt.delete("1.0", f"{n - 3000}.0")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def limpar(self):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")


class Grafico(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color=C["panel"], corner_radius=8, border_width=1, border_color=C["border"])
        self.fig = Figure(figsize=(6, 4), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax2 = None
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=(4, 0))
        barra = tk.Frame(self, bg=C["panel"])
        barra.pack(fill="x", padx=4)
        self.tb = NavigationToolbar2Tk(self.canvas, barra)
        self.tb.config(bg=C["panel"])
        for w in self.tb.winfo_children():
            try:
                w.config(bg=C["panel"])
            except Exception:
                pass
        self.tb.update()

    def limpar(self, gemeo=False):
        self.fig.clear()
        self.ax = self.fig.add_subplot(111)
        self.ax2 = self.ax.twinx() if gemeo else None
        self.ax.grid(True, ls="--", alpha=0.35)

    def desenhar(self):
        try:
            self.fig.tight_layout()
        except Exception:
            pass
        self.canvas.draw_idle()


# ============================================================ aba de medida
class AbaMedida(ctk.CTkFrame):
    """
    Layout: painel de parametros (esquerda) + grafico e resumo (direita).
    Subclasses definem: NOME, ETAPA, construir(pf), parametros(), executar(motor, p),
    plotar(g, pontos), opcionalmente PRESETS = {nome: {campo: valor}}.
    """
    NOME = "Medida"
    ETAPA = "G00-X"
    PARAM = ""
    PRESETS = {}
    EVENTOS = False

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.campos = {}
        self.pontos = []
        self._lock = threading.Lock()
        self._novos = False
        self._rodando = False
        self.ctx = None
        self.ultimos_arquivos = []
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        esq = ctk.CTkScrollableFrame(self, fg_color=C["panel"], corner_radius=8, border_width=1,
                                     border_color=C["border"], width=300)
        esq.grid(row=0, column=0, sticky="ns", padx=(0, 6))
        pf = ctk.CTkFrame(esq, fg_color="transparent")
        pf.pack(fill="x", padx=10, pady=(4, 4))
        if self.PRESETS:
            self.preset = Opcao(pf, "Predefinicao (guias da campanha)", ["(manual)"] + list(self.PRESETS),
                                comando=self._aplicar_preset)
            self.preset.pack(fill="x", pady=(4, 2))
        secao(pf, "ARQUIVO")
        self.c_etapa = self.add(pf, "etapa", Campo(pf, "Guia-etapa (nome do arquivo)", self.ETAPA,
                                                  dica="Ex.: G04-E2, G10-P1, SOL-JV. Define a pasta de destino."))
        self.c_param = self.add(pf, "param", Campo(pf, "Parametro (nome do arquivo)", self.PARAM,
                                                  dica="Distingue arquivos da mesma etapa (ex.: L1, LRS, Vp8p0). "
                                                       "Vazio = automatico."))
        self.construir(pf)

        bf = ctk.CTkFrame(esq, fg_color="transparent")
        bf.pack(fill="x", padx=10, pady=(8, 10))
        self.b_ini = Btn(bf, "Iniciar", "primary", command=self.iniciar)
        self.b_ini.pack(fill="x", pady=2)
        Btn(bf, "Parar", "danger", command=self.parar).pack(fill="x", pady=2)
        if self.EVENTOS:
            self.c_evento = Campo(bf, "Evento (marca no arquivo)", "luz ON")
            self.c_evento.pack(fill="x", pady=(6, 0))
            Btn(bf, "Marcar evento", "secondary", command=self.marcar_evento).pack(fill="x", pady=2)
        Btn(bf, "Salvar copia como...", "secondary", command=self.salvar_como).pack(fill="x", pady=2)

        dir_ = ctk.CTkFrame(self, fg_color="transparent")
        dir_.grid(row=0, column=1, sticky="nsew")
        dir_.grid_rowconfigure(0, weight=1)
        dir_.grid_columnconfigure(0, weight=1)
        self.g = Grafico(dir_)
        self.g.grid(row=0, column=0, sticky="nsew")
        barra = ctk.CTkFrame(dir_, fg_color="transparent")
        barra.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.vis = Opcao(barra, "", self.VISTAS, comando=self.redesenhar, segmentado=True) if hasattr(self, "VISTAS") else None
        if self.vis:
            self.vis.pack(side="left")
        self.progresso = PainelProgresso(dir_)
        self.progresso.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        self.resumo = ctk.CTkLabel(dir_, text="", font=("Consolas", 10), text_color=C["dim"], justify="left",
                                   anchor="w", wraplength=900)
        self.resumo.grid(row=3, column=0, sticky="ew", pady=(2, 0))
        self.redesenhar()

    # ---------------------------------------------------------------- campos
    def add(self, pf, chave, w, pack=True):
        self.campos[chave] = w
        if pack:
            w.pack(fill="x", pady=2)
        return w

    def estado(self):
        return {k: w.get() for k, w in self.campos.items()}

    def restaurar(self, d):
        for k, v in (d or {}).items():
            if k in self.campos:
                try:
                    self.campos[k].set(v)
                except Exception:
                    pass

    def _aplicar_preset(self):
        nome = self.preset.get()
        if nome in self.PRESETS:
            self.restaurar(self.PRESETS[nome])
            self.app.log(f"[{self.NOME}] predefinicao aplicada: {nome}", "info")

    # ---------------------------------------------------------------- execucao
    def construir(self, pf):
        pass

    def parametros(self):
        return {}

    def executar(self, motor, p):
        raise NotImplementedError

    def iniciar(self):
        if self._rodando:
            messagebox.showinfo("Em andamento", "Esta medida ainda esta rodando.")
            return
        if self.app.ocupado():
            messagebox.showwarning("Instrumento ocupado", "Outra medida esta rodando. Pare-a antes.")
            return
        if not self.app.k.connected:
            messagebox.showwarning("Sem conexao", "Conecte o Keithley 2400 (ou o simulador) no topo da janela.")
            return
        try:
            p = self.parametros()
            p["etapa"] = self.c_etapa.txt or self.ETAPA
            if self.c_param.txt:
                p["param"] = self.c_param.txt
        except Exception as e:
            messagebox.showerror("Parametro invalido", str(e))
            return
        meta = self.app.metadados()
        if self.app.autosalvar() and not meta.get("pad"):
            if not messagebox.askyesno("Pad nao informado",
                                       "O campo Pad esta vazio (a campanha exige registrar o pad).\nContinuar assim mesmo?"):
                return
        with self._lock:
            self.pontos = []
        self.ultimos_arquivos = []
        self.resumo.configure(text="")
        self.redesenhar()
        ctx = Contexto(self.app.k, log=self.app.log, progresso=None,
                       ao_ponto=self._ao_ponto,
                       ao_arquivo=lambda a, m=meta: self._ao_arquivo(a, m),
                       ao_parcial=lambda a, m=meta: self.app.salvar_parcial(a, m))
        self.ctx = ctx
        self._rodando = True
        self.app.marcar_ocupado(self)
        self.progresso.iniciar(ctx)
        self.b_ini.configure(state="disabled", text="Medindo...")
        threading.Thread(target=self._rodar, args=(ctx, p, meta), daemon=True).start()
        self.after(300, self._tick)

    def _rodar(self, ctx, p, meta):
        t0 = time.perf_counter()
        self.app.log(f"[{self.NOME}] inicio ({p['etapa']})", "info")
        try:
            self.executar(Motor(ctx), p)
            self.app.log(f"[{self.NOME}] concluida em {time.perf_counter() - t0:.1f} s", "info")
        except Cancelado:
            self.app.log(f"[{self.NOME}] interrompida pelo usuario (dados parciais gravados)", "warn")
        except ErroInstrumento as e:
            self.app.log(f"[{self.NOME}] ERRO do instrumento: {e}", "error")
        except Exception as e:
            self.app.log(f"[{self.NOME}] ERRO: {e}", "error")
            self.app.log(traceback.format_exc(limit=3), "error")
        finally:
            try:
                self.app.k.fim_medida(True)
            except Exception:
                pass
            self.app.after(0, self._fim)

    def _fim(self):
        self._rodando = False
        self.progresso.terminar(cancelado=bool(self.ctx and self.ctx.parar.is_set()))
        self.app.marcar_ocupado(None)
        self.b_ini.configure(state="normal", text="Iniciar")
        self.app.progresso(0, "")
        self.app.limpar_parciais()
        self.redesenhar()
        if self.ultimos_arquivos and self.app.salvar_png():
            base = self.ultimos_arquivos[-1]
            try:
                self.g.fig.savefig(base.rsplit(".", 1)[0] + ".png", dpi=150, facecolor=C["panel"])
            except Exception:
                pass

    def parar(self):
        if self.ctx:
            self.ctx.parar.set()
            self.app.log(f"[{self.NOME}] parada solicitada (termina a lista em execucao no instrumento)", "warn")

    def marcar_evento(self):
        if self.ctx and self._rodando:
            self.ctx.evento_pendente = self.c_evento.txt or "evento"
            self.app.log(f"Evento marcado: {self.ctx.evento_pendente}", "info")

    def _ao_ponto(self, d):
        with self._lock:
            self.pontos.append(d)
            self._novos = True

    def _ao_arquivo(self, arq, meta):
        caminho = self.app.salvar_arquivo(arq, meta)
        if caminho:
            self.ultimos_arquivos.append(caminho)
        if arq.resumo:
            txt = "  |  ".join(f"{k}: {v:.4g}" if isinstance(v, float) else f"{k}: {v}"
                               for k, v in list(arq.resumo.items())[:14])
            self.app.after(0, lambda: self.resumo.configure(text=f"{arq.param}:  {txt}"))

    def _tick(self):
        if self._novos:
            self._novos = False
            self.redesenhar()
        if self._rodando:
            txt = self.progresso.atualizar()
            self.app.progresso(self.progresso.frac, txt)
            self.after(400, self._tick)

    def redesenhar(self):
        with self._lock:
            pts = list(self.pontos)
        try:
            self.plotar(self.g, pts)
        except Exception as e:
            self.g.limpar()
            self.g.ax.text(0.5, 0.5, f"(grafico: {e})", transform=self.g.ax.transAxes, ha="center")
        self.g.desenhar()

    def plotar(self, g, pts):
        g.limpar()

    def salvar_como(self):
        if not self.ultimos_arquivos:
            messagebox.showinfo("Nada para salvar", "Nenhum arquivo foi gerado nesta aba ainda.")
            return
        from tkinter import filedialog
        import shutil
        import os
        d = filedialog.askdirectory(title="Copiar os arquivos da ultima medida para...")
        if d:
            for c in self.ultimos_arquivos:
                shutil.copy2(c, os.path.join(d, os.path.basename(c)))
            self.app.log(f"{len(self.ultimos_arquivos)} arquivo(s) copiado(s) para {d}", "info")


def _hms(seg):
    seg = int(max(0, round(seg)))
    h, r = divmod(seg, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class PainelProgresso(ctk.CTkFrame):
    """
    Barra de progresso da medida: fracao (pelas etapas e pelo tempo estimado), decorrido,
    restante e horario previsto de termino; barra fina para a lista que o 2400 esta executando.
    """

    def __init__(self, master):
        super().__init__(master, fg_color=C["panel"], corner_radius=8, border_width=1, border_color=C["border"])
        self.grid_columnconfigure(0, weight=1)
        self.lbl = ctk.CTkLabel(self, text="Pronto.", font=(FONTE, 13, "bold"), text_color=C["dim"], anchor="w")
        self.lbl.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 2))
        self.pct = ctk.CTkLabel(self, text="", font=(FONTE, 13, "bold"), text_color=C["acc_hi"], width=70, anchor="e")
        self.pct.grid(row=0, column=1, padx=10, pady=(6, 2))
        self.barra = ctk.CTkProgressBar(self, height=16, corner_radius=6, progress_color=C["acc_hi"],
                                        fg_color=C["input"])
        self.barra.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10)
        self.barra.set(0)
        self.sub = ctk.CTkProgressBar(self, height=5, corner_radius=3, progress_color=C["gold"], fg_color=C["input"])
        self.sub.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(4, 0))
        self.sub.set(0)
        self.det = ctk.CTkLabel(self, text="", font=("Consolas", 11), text_color=C["muted"], anchor="w")
        self.det.grid(row=3, column=0, columnspan=2, sticky="ew", padx=10, pady=(2, 6))
        self.ctx = None
        self.frac = 0.0
        self._giro = 0

    GIRO = "\u25d0\u25d3\u25d1\u25d2"     # indicador de atividade (gira a cada atualizacao)

    def iniciar(self, ctx):
        self.ctx = ctx
        self.frac = 0.0
        self._giro = 0
        self.barra.set(0)
        self.sub.set(0)
        self.barra.configure(progress_color=C["acc_hi"])
        self.lbl.configure(text="Iniciando...", text_color=C["text"])
        self.pct.configure(text="0 %")
        self.det.configure(text="")

    def atualizar(self):
        c = self.ctx
        if c is None:
            return ""
        agora = time.perf_counter()
        dec = agora - c.t_inicio
        f_it = c.frac
        tot = c.t_total_est
        if tot:
            # a estimativa de tempo de cada lista e boa: a barra segue o tempo
            if dec <= tot:
                f = min(0.99, dec / tot)
                rest = tot - dec
            else:  # passou da estimativa: extrapola pelo andamento das etapas
                f = 0.99
                rest = dec * (1 - f_it) / f_it if f_it > 0.02 else None
        else:
            f = f_it
            rest = dec * (1 - f) / f if f > 0.02 else None
        f = max(self.frac, min(0.995, f))          # nunca volta para tras
        self.frac = f
        self.barra.set(f)
        self.pct.configure(text=f"{f*100:4.0f} %")
        etapa = c.etapa_txt or "medindo"
        self._giro += 1
        self.lbl.configure(text=f"{self.GIRO[self._giro % 4]}  {etapa}")
        partes = [f"decorrido {_hms(dec)}"]
        if rest is not None:
            fim = datetime.fromtimestamp(time.time() + rest).strftime("%H:%M")
            partes += [f"restante ~{_hms(rest)}", f"termino ~{fim}"]
        if c.lista_ini is not None and c.lista_est:
            dl = agora - c.lista_ini
            self.sub.set(min(0.99, dl / c.lista_est))
            partes.append(f"lista no 2400: {dl:4.1f} / ~{c.lista_est:.1f} s")
        else:
            # entre listas (esperando a proxima leitura, comunicacao): barra fina em vai-e-vem
            x = (self._giro % 20) / 10.0
            self.sub.set(x if x <= 1 else 2 - x)
        txt = "   |   ".join(partes)
        self.det.configure(text=txt)
        return f"{etapa}  {f*100:.0f} %  restante ~{_hms(rest)}" if rest is not None else etapa

    def terminar(self, cancelado=False):
        dec = (time.perf_counter() - self.ctx.t_inicio) if self.ctx else 0.0
        self.frac = 1.0 if not cancelado else self.frac
        self.barra.set(self.frac)
        self.sub.set(0)
        if cancelado:
            self.barra.configure(progress_color=C["gold"])
            self.lbl.configure(text="Interrompida", text_color=C["gold"])
        else:
            self.barra.configure(progress_color=C["green"])
            self.lbl.configure(text="Concluida", text_color=C["green"])
        self.pct.configure(text=f"{self.frac*100:.0f} %")
        self.det.configure(text=f"duracao {_hms(dec)}   |   fim as {datetime.now():%H:%M:%S}")


def log_y(ax, valores):
    """Escala log se todos os valores forem positivos."""
    import numpy as np
    v = np.asarray(valores, float)
    if len(v) and np.all(v[np.isfinite(v)] > 0):
        ax.set_yscale("log")
