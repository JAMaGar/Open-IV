"""Janela principal do Open-IV."""
import os
import threading
from datetime import datetime
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from .. import VERSAO_COMPLETA
from .. import arquivos as fa
from ..keithley import Keithley2400
from ..transporte import TransporteSerial, listar_portas
from ..simulador import SimTransporte
from .base import C, FONTE, Btn, LogView, aplicar_tema, TEMA
from .mis import AbaIV, AbaMultinivel, AbaPulsos, AbaSinapse, AbaCiclos, AbaRetencao, AbaTransiente
from .solar import AbaJV, AbaDiodo, AbaEstabilidade
from .instrumento import AbaInstrumento

ABAS_MIS = [AbaIV, AbaMultinivel, AbaPulsos, AbaSinapse, AbaCiclos, AbaRetencao, AbaTransiente]
ABAS_SOLAR = [AbaJV, AbaDiodo, AbaEstabilidade]
SIMULADORES = ["(instrumento real)", "simulador: capacitor MIS", "simulador: celula solar", "simulador: resistor 1 MOhm"]


class App(ctk.CTk):
    def __init__(self, simular=None):
        self.cfg = fa.carregar_config()
        aplicar_tema(self.cfg.get("tema", "Escuro"))
        super().__init__()
        self.title(f"{VERSAO_COMPLETA}  |  Keithley 2400 SourceMeter")
        self.geometry("1400x900")
        self.minsize(1100, 700)
        self.k = Keithley2400()
        self.k.log = self.log
        self._ocupado = None
        self._parciais = set()
        self._portas = []
        self._linhas_log = []          # (hora, msg, tag): preservado ao trocar o tema
        self._fonte_reg = int(self.cfg.get("fonte_registros", 13))
        self.abas = {}
        self._montar()
        self._atualizar_portas()
        self.log(f"{VERSAO_COMPLETA} pronto. Conecte o cabo RS-232 e clique em Atualizar / Conectar.")
        if simular:
            self._sim_var.set({"mis": SIMULADORES[1], "solar": SIMULADORES[2], "resistor": SIMULADORES[3]}.get(simular, SIMULADORES[1]))
        self.protocol("WM_DELETE_WINDOW", self._fechar)

    # ================================================================ interface
    def _montar(self):
        self.configure(fg_color=C["bg"])
        self.abas = {}
        self._construir()
        self._restaurar()
        if self.k.connected:
            self._estado_conexao(True, self._st_txt_salvo)

    def _trocar_tema(self, nome):
        if nome == TEMA["nome"]:
            return
        if self._ocupado is not None:
            messagebox.showwarning("Medida em andamento", "Troque o tema depois que a medida terminar.")
            self._tema_var.set(TEMA["nome"])
            return
        self._salvar_estado()
        self.cfg["tema"] = nome
        aba_atual = self._tv.get()
        for w in self.winfo_children():
            w.destroy()
        aplicar_tema(nome)
        self._montar()
        try:
            self._tv.set(aba_atual)
        except Exception:
            pass
        self._porta.configure(values=[p["label"] for p in self._portas] or ["Nenhuma porta encontrada"])
        self._porta_var.set(self.cfg.get("porta", ""))
        self._salvar_estado()

    def _construir(self):
        self._st_txt_salvo = getattr(self, "_st_txt_salvo", "")
        cab = ctk.CTkFrame(self, fg_color=C["panel"], corner_radius=0)
        cab.pack(fill="x")
        l1 = ctk.CTkFrame(cab, fg_color="transparent")
        l1.pack(fill="x", padx=14, pady=(8, 0))
        logo = ctk.CTkFrame(l1, fg_color=C["acc"], corner_radius=6, width=40, height=36)
        logo.pack(side="left", padx=(0, 10)); logo.pack_propagate(False)
        ctk.CTkLabel(logo, text="IV", font=("Georgia", 15, "bold"), text_color=C["text"]).place(relx=.5, rely=.5, anchor="center")
        tf = ctk.CTkFrame(l1, fg_color="transparent"); tf.pack(side="left")
        ctk.CTkLabel(tf, text="Open-IV", font=(FONTE, 18, "bold"), text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(tf, text="Keithley 2400  |  capacitores MIS e memoria  |  celulas solares e diodos",
                     font=(FONTE, 10), text_color=C["muted"]).pack(anchor="w")
        self._tema_var = ctk.StringVar(value=TEMA["nome"])
        ctk.CTkSegmentedButton(l1, values=["Escuro", "Claro"], variable=self._tema_var, font=(FONTE, 10),
                               selected_color=C["acc"], selected_hover_color=C["acc_hi"],
                               unselected_color=C["input"], unselected_hover_color=C["border"],
                               fg_color=C["input"], text_color=C["text"],
                               command=self._trocar_tema).pack(side="right", padx=(12, 0))
        ctk.CTkLabel(l1, text="Tema:", font=(FONTE, 10), text_color=C["muted"]).pack(side="right", padx=(12, 4))
        self._st_lbl = ctk.CTkLabel(l1, text="Desconectado", font=(FONTE, 11), text_color=C["faint"])
        self._st_lbl.pack(side="right")
        self._st_dot = ctk.CTkLabel(l1, text="\u25cf ", font=(FONTE, 15), text_color=C["faint"])
        self._st_dot.pack(side="right")

        l2 = ctk.CTkFrame(cab, fg_color="transparent")
        l2.pack(fill="x", padx=14, pady=(6, 4))
        ctk.CTkLabel(l2, text="Porta:", font=(FONTE, 11), text_color=C["muted"]).pack(side="left", padx=(0, 4))
        self._porta_var = ctk.StringVar()
        self._porta = ctk.CTkComboBox(l2, variable=self._porta_var, width=330, height=28, font=("Consolas", 11),
                                      fg_color=C["bg"], border_color=C["border"], button_color=C["border_hi"],
                                      dropdown_fg_color=C["panel"], text_color=C["text"], values=[""])
        self._porta.pack(side="left", padx=(0, 6))
        Btn(l2, "Atualizar", "secondary", width=80, command=self._atualizar_portas).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(l2, text="Baud:", font=(FONTE, 11), text_color=C["muted"]).pack(side="left", padx=(0, 4))
        self._baud_var = ctk.StringVar(value="9600")
        ctk.CTkComboBox(l2, variable=self._baud_var, width=90, height=28, font=("Consolas", 11), fg_color=C["bg"],
                        border_color=C["border"], button_color=C["border_hi"], dropdown_fg_color=C["panel"],
                        text_color=C["text"], values=["9600", "19200", "38400", "57600"]).pack(side="left", padx=(0, 10))
        self._sim_var = ctk.StringVar(value=SIMULADORES[0])
        ctk.CTkOptionMenu(l2, variable=self._sim_var, values=SIMULADORES, width=210, height=28, font=(FONTE, 11),
                          fg_color=C["input"], button_color=C["border_hi"], dropdown_fg_color=C["panel"],
                          text_color=C["text"]).pack(side="left", padx=(0, 10))
        self._b_con = Btn(l2, "Conectar", "success", width=120, command=self._conectar)
        self._b_con.pack(side="left")

        l3 = ctk.CTkFrame(cab, fg_color="transparent")
        l3.pack(fill="x", padx=14, pady=(2, 8))
        self.meta = {}
        for k, rot, w in (("amostra", "Amostra", 130), ("pad", "Pad", 70), ("grupo", "Grupo", 50), ("sessao", "Sessao", 70)):
            ctk.CTkLabel(l3, text=rot + ":", font=(FONTE, 11), text_color=C["muted"]).pack(side="left", padx=(0, 3))
            v = ctk.StringVar()
            e = ctk.CTkEntry(l3, textvariable=v, width=w, height=26, font=("Consolas", 11), fg_color=C["bg"],
                             border_color=C["border_hi"], text_color=C["gold"])
            e.pack(side="left", padx=(0, 10))
            v.trace_add("write", lambda *_: self.atualizar_destino())
            self.meta[k] = v
        self._destino = ctk.CTkLabel(l3, text="", font=("Consolas", 9), text_color=C["faint"], anchor="w")
        self._destino.pack(side="left", fill="x", expand=True)
        ctk.CTkFrame(cab, fg_color=C["border"], height=1).pack(fill="x")

        corpo = tk.PanedWindow(self, orient="vertical", bg=C["bg"], bd=0, sashwidth=5)
        corpo.pack(fill="both", expand=True)
        topo = ctk.CTkFrame(corpo, fg_color=C["bg"])
        tv_kw = dict(fg_color=C["bg"], segmented_button_fg_color=C["panel"], segmented_button_selected_color=C["acc"],
                     segmented_button_selected_hover_color=C["acc_hi"], segmented_button_unselected_color=C["panel"],
                     segmented_button_unselected_hover_color=C["border"], text_color=C["text"], corner_radius=8)
        self._tv = ctk.CTkTabview(topo, **tv_kw)
        self._tv.pack(fill="both", expand=True, padx=6, pady=(4, 0))
        for titulo, classes in (("Capacitor MIS / Memoria", ABAS_MIS), ("Celula Solar / Diodo", ABAS_SOLAR)):
            fr = self._tv.add(titulo)
            sub = ctk.CTkTabview(fr, **tv_kw)
            sub.pack(fill="both", expand=True)
            for cls in classes:
                f = sub.add(cls.NOME)
                aba = cls(f, self)
                aba.pack(fill="both", expand=True)
                self.abas[cls.__name__] = aba
        fr = self._tv.add("Registros")
        self._construir_registros(fr)
        fr = self._tv.add("Instrumento e Arquivos")
        self.inst = AbaInstrumento(fr, self)
        self.inst.pack(fill="both", expand=True)
        corpo.add(topo, stretch="always")

        baixo = ctk.CTkFrame(corpo, fg_color=C["bg"])
        lh = ctk.CTkFrame(baixo, fg_color="transparent"); lh.pack(fill="x", padx=10, pady=(4, 2))
        ctk.CTkLabel(lh, text="REGISTRO", font=(FONTE, 10, "bold"), text_color=C["gold"]).pack(side="left")
        Btn(lh, "Limpar", "secondary", width=70, command=lambda: self._logv.limpar()).pack(side="right")
        self._logv = LogView(baixo); self._logv.pack(fill="both", expand=True, padx=6, pady=(0, 4))
        corpo.add(baixo, stretch="never", height=170)

        sb = ctk.CTkFrame(self, fg_color=C["panel"], height=24, corner_radius=0)
        sb.pack(fill="x", side="bottom"); sb.pack_propagate(False)
        self._prog = ctk.CTkProgressBar(sb, width=240, height=6, progress_color=C["acc_hi"])
        self._prog.pack(side="right", padx=10); self._prog.set(0)
        self._plbl = ctk.CTkLabel(sb, text="", font=("Consolas", 9), text_color=C["dim"])
        self._plbl.pack(side="right", padx=(0, 4))
        ctk.CTkLabel(sb, text=f"{VERSAO_COMPLETA}  |  baseado no MemristorProbe 1.3", font=(FONTE, 9),
                     text_color=C["faint"]).pack(side="left", padx=10)
        for h, m, t in self._linhas_log[-3000:]:
            self._logv.log(m, t, hora=h)
            if self._filtro_ok(t):
                self._regv.log(m, t, hora=h)

    def _construir_registros(self, fr):
        barra = ctk.CTkFrame(fr, fg_color="transparent")
        barra.pack(fill="x", padx=6, pady=(4, 4))
        ctk.CTkLabel(barra, text="Registro da sessao", font=(FONTE, 13, "bold"), text_color=C["gold"]).pack(side="left")
        Btn(barra, "Salvar em arquivo...", "secondary", width=150, command=self._salvar_registro).pack(side="right", padx=(6, 0))
        Btn(barra, "Limpar", "secondary", width=80, command=self._limpar_registros).pack(side="right", padx=(6, 0))
        Btn(barra, "A+", "secondary", width=44, command=lambda: self._mudar_fonte(+1)).pack(side="right", padx=(6, 0))
        Btn(barra, "A-", "secondary", width=44, command=lambda: self._mudar_fonte(-1)).pack(side="right", padx=(6, 0))
        self._filtro_var = ctk.StringVar(value=self.cfg.get("filtro_registros", "Tudo"))
        ctk.CTkSegmentedButton(barra, values=["Tudo", "Sem SCPI", "Avisos e erros"], variable=self._filtro_var,
                               font=(FONTE, 10), selected_color=C["acc"], selected_hover_color=C["acc_hi"],
                               unselected_color=C["input"], unselected_hover_color=C["border"], fg_color=C["input"],
                               text_color=C["text"], command=lambda _=None: self._refiltrar()).pack(side="right", padx=(6, 12))
        self._regv = LogView(fr, tamanho=self._fonte_reg)
        self._regv.pack(fill="both", expand=True, padx=6, pady=(0, 6))

    def _filtro_ok(self, tag):
        f = self._filtro_var.get() if hasattr(self, "_filtro_var") else "Tudo"
        if f == "Avisos e erros":
            return tag in ("warn", "error")
        if f == "Sem SCPI":
            return tag not in ("tx",)
        return True

    def _refiltrar(self):
        self._regv.limpar()
        for h, m, t in self._linhas_log[-3000:]:
            if self._filtro_ok(t):
                self._regv.log(m, t, hora=h)
        self.cfg["filtro_registros"] = self._filtro_var.get()

    def _mudar_fonte(self, d):
        self._fonte_reg = max(8, min(24, self._fonte_reg + d))
        self._regv.fonte(self._fonte_reg)
        self.cfg["fonte_registros"] = self._fonte_reg

    def _limpar_registros(self):
        self._linhas_log.clear()
        self._regv.limpar()
        self._logv.limpar()

    def _salvar_registro(self):
        from tkinter import filedialog
        fp = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Texto", "*.txt")],
                                          initialfile=f"Open-IV_registro_{datetime.now():%Y%m%d-%H%M%S}.txt")
        if fp:
            with open(fp, "w", encoding="utf-8") as f:
                for h, m, t in self._linhas_log:
                    f.write(f"{h}  [{t}] {m}\n")
            self.log(f"Registro salvo em {fp}")

    # ================================================================ estado persistente
    def _restaurar(self):
        c = self.cfg
        if c.get("baud"):
            self._baud_var.set(str(c["baud"]))
        for k, v in (c.get("meta") or {}).items():
            if k in self.meta:
                self.meta[k].set(v)
        self.inst.restaurar(c.get("instrumento"))
        for nome, aba in self.abas.items():
            aba.restaurar((c.get("abas") or {}).get(nome))
        self.inst.aplicar(silencioso=True)
        self.atualizar_destino()

    def _salvar_estado(self):
        self.cfg.update({"porta": self._porta_var.get(), "baud": self._baud_var.get(), "tema": TEMA["nome"],
                         "fonte_registros": self._fonte_reg,
                         "meta": {k: v.get() for k, v in self.meta.items()},
                         "instrumento": self.inst.estado(),
                         "abas": {n: a.estado() for n, a in self.abas.items()}})
        fa.salvar_config(self.cfg)

    def _fechar(self):
        if self._ocupado is not None:
            if not messagebox.askyesno("Medida em andamento", "Ha uma medida rodando. Parar e sair?"):
                return
            try:
                self._ocupado.parar()
            except Exception:
                pass
        self._salvar_estado()
        try:
            if self.k.connected:
                self.k.desconectar()
        except Exception:
            pass
        self.destroy()

    # ================================================================ conexao
    def _atualizar_portas(self):
        self._portas = listar_portas()
        rot = [p["label"] for p in self._portas] or ["Nenhuma porta encontrada"]
        self._porta.configure(values=rot)
        ant = self.cfg.get("porta")
        self._porta_var.set(ant if ant in rot else rot[0])
        self.log(f"Portas: {len(self._portas)}" + "".join(f"\n   {p['device']}  {p['desc']}" for p in self._portas))

    def _conectar(self):
        if self.k.connected:
            if self._ocupado is not None:
                messagebox.showwarning("Ocupado", "Pare a medida antes de desconectar.")
                return
            self.k.desconectar()
            self._estado_conexao(False)
            self.log("Desconectado")
            return
        baud = int(self._baud_var.get())
        sim = self._sim_var.get()
        try:
            if sim != SIMULADORES[0]:
                modelo = {SIMULADORES[1]: "mis", SIMULADORES[2]: "solar", SIMULADORES[3]: "resistor"}[sim]
                tr = SimTransporte(modelo, baud=baud, tempo_real=True, xonxoff=self.inst.xonxoff())
                tr.open()
                metodo = f"simulador ({tr.dev.nome})"
            else:
                porta = None
                for p in self._portas:
                    if p["label"] == self._porta_var.get():
                        porta = p["device"]
                if porta is None and self._porta_var.get().upper().startswith(("COM", "/DEV/")):
                    porta = self._porta_var.get().split()[0]
                if not porta:
                    messagebox.showwarning("Sem porta", "Selecione a porta do adaptador USB-RS232 (clique Atualizar).")
                    return
                tr = TransporteSerial()
                metodo = tr.open(porta, baud, xonxoff=self.inst.xonxoff())
            self.inst.aplicar(silencioso=True)
            idn = self.k.conectar(tr, baud)
            if getattr(tr, "erro_win32", ""):
                self.log(f"driver Win32 nao abriu a porta ({tr.erro_win32}); usando o pyserial.", "warn")
            self.log(f"Conectado via {metodo} @ {baud} baud, controle de fluxo "
                     f"{'XON/XOFF' if getattr(tr, 'xonxoff', False) else 'nenhum'}, sincronismo {self.k.sincronismo}", "info")
            self.log(f"*IDN? -> {idn}; rede {self.k.lfr:g} Hz", "rx")
            if baud < 38400:
                self.log("Dica: 57600 baud (no 2400 e aqui) reduz o intervalo entre listas (ex.: pulso -> leitura).", "warn")
            self._simulado = sim != SIMULADORES[0]
            self._estado_conexao(True, idn[:60])
        except Exception as e:
            self.log(f"ERRO ao conectar: {e}", "error")
            try:
                tr.close()
            except Exception:
                pass
            messagebox.showerror("Erro de conexao", f"{e}\n\nConfira: cabo, porta, baud igual ao do 2400 "
                                                    "(MENU > COMMUNICATION > RS-232) e terminador <CR+LF>/<LF>.")

    def _estado_conexao(self, conectado, txt=""):
        if conectado:
            self._st_txt_salvo = txt
            cor = C["gold"] if getattr(self, "_simulado", False) else C["green"]
            self._b_con.configure(text="Desconectar")
            self._st_dot.configure(text_color=cor)
            self._st_lbl.configure(text=txt, text_color=cor)
        else:
            self._b_con.configure(text="Conectar")
            self._st_dot.configure(text_color=C["faint"])
            self._st_lbl.configure(text="Desconectado", text_color=C["faint"])

    # ================================================================ servicos para as abas
    def log(self, msg, tag="info"):
        if threading.current_thread() is threading.main_thread():
            self._log_main(msg, tag)
        else:
            self.after(0, self._log_main, msg, tag)

    def _log_main(self, msg, tag="info"):
        h = datetime.now().strftime("%H:%M:%S")
        self._linhas_log.append((h, msg, tag))
        if len(self._linhas_log) > 20000:
            del self._linhas_log[:5000]
        try:
            self._logv.log(msg, tag, hora=h)
            if self._filtro_ok(tag):
                self._regv.log(msg, tag, hora=h)
        except Exception:
            pass

    def progresso(self, frac, txt=""):
        self._prog.set(frac)
        self._plbl.configure(text=txt)

    def progresso_ts(self, frac, txt=""):
        self.after(0, self.progresso, frac, txt)

    def ocupado(self):
        return self._ocupado is not None

    def marcar_ocupado(self, quem):
        self._ocupado = quem

    def autosalvar(self):
        return self.inst.campos["autosalvar"].get()

    def salvar_png(self):
        return self.inst.campos["png"].get() and self.autosalvar()

    def metadados(self):
        """Instantaneo dos metadados (lido na thread principal, antes da medida)."""
        i = self.inst.campos
        sn = i["instrumento_sn"].txt
        return {"amostra": self.meta["amostra"].get().strip(), "pad": self.meta["pad"].get().strip(),
                "grupo": self.meta["grupo"].get().strip(), "sessao": self.meta["sessao"].get().strip(),
                "operador": i["operador"].txt, "luz": i["luz"].txt, "T_amb_C": i["T_amb_C"].txt,
                "UR_pct": i["UR_pct"].txt, "observacao": i["observacao"].txt, "raiz": i["raiz"].txt,
                "autosalvar": self.autosalvar(),
                "instrumento": f"{self.k.idn_str}" + (f" (SN {sn})" if sn else ""),
                "inicio": datetime.now()}

    def atualizar_destino(self):
        try:
            am = self.meta["amostra"].get()
            raiz = self.inst.campos["raiz"].txt
            self._destino.configure(text=f"destino G04: {fa.pasta_destino(raiz, 'G04', am)}")
        except Exception:
            pass

    def _cabecalho(self, arq, meta):
        k = self.k
        cab = {"amostra": meta["amostra"], "pad": meta["pad"], "grupo": meta["grupo"],
               "guia_etapa": arq.etapa, "sessao": meta["sessao"],
               "data_hora_inicio": meta["inicio"].isoformat(timespec="seconds"),
               "operador": meta["operador"], "instrumento": meta["instrumento"],
               "programa_versao": VERSAO_COMPLETA, "luz": meta["luz"], "T_amb_C": meta["T_amb_C"],
               "UR_pct": meta["UR_pct"], "parametros": arq.meta, "observacao": meta["observacao"],
               "config_instrumento": {"terminais": k.cfg["terminais"], "quatro_fios": k.cfg["quatro_fios"],
                                      "saida_off": k.cfg["modo_off"], "autozero_DC": k.cfg["autozero"],
                                      "display_off": k.cfg["display_off"], "baud": k.baud, "rede_Hz": k.lfr,
                                      "sobrecarga_SDM_ms": round(k.sobrecarga_s * 1e3, 4)},
               "temporizacao": "listas executadas pelo 2400 (custom sweep); t_s = carimbo de tempo do 2400",
               "arquivo_gravado_em": datetime.now().isoformat(timespec="seconds")}
        for kk, v in (arq.resumo or {}).items():
            cab[f"resumo_{kk}"] = v
        return cab

    def salvar_arquivo(self, arq, meta):
        if not meta.get("autosalvar", True) or not arq.linhas:
            if arq.linhas:
                self.log(f"(nao gravado: autosalvar desligado) {arq.etapa} {arq.param}", "warn")
            return None
        pasta = fa.pasta_destino(meta["raiz"], arq.etapa, meta["amostra"])
        nome = fa.nome_arquivo(meta["amostra"], meta["pad"], arq.etapa, arq.param)
        try:
            c = fa.escrever_csv(os.path.join(pasta, nome), self._cabecalho(arq, meta), arq.colunas, arq.linhas)
            self.log(f"Gravado: {c}", "info")
            return c
        except Exception as e:
            self.log(f"ERRO ao gravar {nome}: {e}", "error")
            return None

    def salvar_parcial(self, arq, meta):
        """Copia de seguranca (sobrescrita a cada chamada; apagada ao fim da medida)."""
        if not meta.get("autosalvar", True) or not arq.linhas:
            return
        pasta = fa.pasta_destino(meta["raiz"], arq.etapa, meta["amostra"])
        nome = "_parcial_" + fa.nome_arquivo(meta["amostra"], meta["pad"], arq.etapa, arq.param,
                                            quando=meta["inicio"])
        c = os.path.join(pasta, nome)
        try:
            os.makedirs(pasta, exist_ok=True)
            tmp = c + ".tmp"
            if os.path.exists(tmp):
                os.remove(tmp)
            fa.escrever_csv(tmp, self._cabecalho(arq, meta), arq.colunas, list(arq.linhas))
            os.replace(tmp, c)
            self._parciais.add(c)
        except Exception as e:
            self.log(f"(copia parcial falhou: {e})", "warn")

    def limpar_parciais(self):
        for c in list(self._parciais):
            try:
                if os.path.exists(c):
                    os.remove(c)
            except Exception:
                pass
            self._parciais.discard(c)
