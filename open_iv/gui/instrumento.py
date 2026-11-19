"""Aba 'Instrumento e Arquivos': metadados, pasta, configuracao do 2400, temporizacao e console SCPI."""
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .base import Campo, Opcao, Marca, Btn, secao, nota, C, FONTE
from ..medidas import Contexto, Motor, Cancelado

SINCRONISMOS = ["*OPC? (recomendado)", "So pausas (1.1.1)"]
FLUXOS = ["Nenhum", "XON/XOFF"]

TEXTO_TEMPORIZACAO = (
    "Como o Open-IV temporiza as medidas\n"
    "- Toda forma de onda (pulso, leitura, laco) e enviada ao 2400 como uma lista (custom sweep, ate 2500 pontos)\n"
    "  e executada pelo proprio instrumento; o PC so envia a lista e recebe os dados no fim.\n"
    "- Cada ponto dura: atraso de fonte (:SOUR:DEL) + medida (NPLC/60 s; x3 com autozero; x2 se medir V) + sobrecarga.\n"
    "- Pulso ate ~60 ms = lista [V_base, V_pulso x k, V_base] com atraso 0: largura = k x T0 (T0 ~1 ms, calibrado\n"
    "  em 60 passos no nivel de base no inicio de cada medida) -> w_calibrada_ms. Pulsos mais longos: um passo com\n"
    "  atraso de fonte. Os carimbos do 2400 (resolucao 1/1024 s) dao t_write_real_ms (+-1 ms) como conferencia.\n"
    "- Largura minima = T0 (~1 ms com NPLC 0,01). Pulsos < 1 ms exigem gerador + osciloscopio (G10-P3).\n"
    "- A saida fica ligada no nivel de base durante a medida e volta a 0 V / desligada no fim (padrao da campanha).\n"
    "- A comunicacao serial so afeta os intervalos ENTRE listas (ex.: pulso -> leitura): use 57600 baud no 2400\n"
    "  (MENU > COMMUNICATION > RS-232 > BAUD) e no programa para reduzi-los. Os atrasos reais sao gravados."
)


class AbaInstrumento(ctk.CTkScrollableFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.campos = {}
        self.grid_columnconfigure((0, 1, 2), weight=1, uniform="col")

        # ------------------------------------------------------------ coluna 1: metadados
        c1 = self._coluna(0, "AMOSTRA E ARQUIVOS")
        for k, rot, pad in (("operador", "Operador", ""), ("luz", "Luz", "escuro"), ("T_amb_C", "T ambiente (C)", ""),
                            ("UR_pct", "Umidade relativa (%)", ""), ("instrumento_sn", "N. de serie do 2400", ""),
                            ("observacao", "Observacao (vai no cabecalho)", "")):
            self.campos[k] = Campo(c1, rot, pad)
            self.campos[k].pack(fill="x", pady=2)
        secao(c1, "PASTA DE DESTINO")
        self.campos["raiz"] = Campo(c1, "Pasta raiz", "")
        self.campos["raiz"].pack(fill="x", pady=2)
        Btn(c1, "Procurar...", "secondary", command=self._procurar).pack(fill="x", pady=2)
        nota(c1, "Se a raiz for 'Caracterizacao_Eletrica_Definitiva', cada guia grava em "
                 "<pasta da tecnica>/dados/<amostra>/ (ex.: G04 -> 20_IV). Outras etapas: <raiz>/<amostra>/.")
        self.campos["autosalvar"] = Marca(c1, "Gravar automaticamente cada arquivo", True)
        self.campos["autosalvar"].pack(fill="x", pady=3)
        self.campos["png"] = Marca(c1, "Gravar tambem o PNG do grafico", True)
        self.campos["png"].pack(fill="x", pady=3)

        # ------------------------------------------------------------ coluna 2: instrumento
        c2 = self._coluna(1, "CONFIGURACAO DO 2400")
        self.campos["terminais"] = Opcao(c2, "Terminais", ["Frontal", "Traseiro"], segmentado=True)
        self.campos["terminais"].pack(fill="x", pady=2)
        self.campos["fios"] = Opcao(c2, "Ligacao", ["2 fios", "4 fios (remote sense)"], segmentado=True)
        self.campos["fios"].pack(fill="x", pady=2)
        self.campos["modo_off"] = Opcao(c2, "Saida desligada (:OUTP:SMOD)",
                                        ["NORMAL (0 V)", "HIMP (flutuante)", "ZERO"], segmentado=False)
        self.campos["modo_off"].pack(fill="x", pady=2)
        self.campos["display_off"] = Marca(c2, "Desligar o display durante a medida (mais rapido)", True)
        self.campos["display_off"].pack(fill="x", pady=3)
        self.campos["autozero"] = Marca(c2, "Autozero nas leituras DC (mais exato, x3 no tempo)", True)
        self.campos["autozero"].pack(fill="x", pady=3)
        self.campos["pausa_ms"] = Campo(c2, "Pausa apos cada comando", 2, "ms")
        self.campos["pausa_ms"].pack(fill="x", pady=2)
        self.campos["sincronismo"] = Opcao(c2, "Sincronismo dos comandos", SINCRONISMOS, segmentado=True)
        self.campos["sincronismo"].pack(fill="x", pady=2)
        self.campos["fluxo"] = Opcao(c2, "Controle de fluxo (vale ao conectar)", FLUXOS, segmentado=True)
        self.campos["fluxo"].pack(fill="x", pady=2)
        self.campos["conferir"] = Marca(c2, "Conferir o estado do 2400 quando a configuracao muda", True)
        self.campos["conferir"].pack(fill="x", pady=3)
        nota(c2, "*OPC?: cada bloco de lista espera a confirmacao do 2400 (evita o -363). XON/XOFF e a reserva: "
                 "exige FLOW-CTRL = XON-XOFF no 2400 (MENU > COMMUNICATION > RS-232). A conferencia le de volta "
                 ":SOUR:DEL, :TRIG:COUN e a lista (alguns ms a mais entre pulso e leitura quando algo muda).")
        Btn(c2, "Aplicar configuracao", "primary", command=self.aplicar).pack(fill="x", pady=(6, 2))
        secao(c2, "TEMPORIZACAO DOS PULSOS")
        self.campos["sobrecarga_ms"] = Campo(c2, "Sobrecarga por ponto (calibrada)", 1.5, "ms")
        self.campos["sobrecarga_ms"].pack(fill="x", pady=2)
        nota(c2, "O T0 (passo sem atraso) e recalibrado automaticamente no 1o pulso de cada medida, "
                 "no nivel de base. Os botoes abaixo servem para conferir o instrumento.")
        Btn(c2, "Medir T0 (200 passos a 0 V)", "secondary", command=self.calibrar).pack(fill="x", pady=2)
        self.campos["teste_w"] = Campo(c2, "Testar larguras", "1, 2, 5, 10, 50, 100", "ms")
        self.campos["teste_w"].pack(fill="x", pady=2)
        self.campos["teste_V"] = Campo(c2, "V do teste (use um resistor)", 1.0, "V")
        self.campos["teste_V"].pack(fill="x", pady=2)
        Btn(c2, "Testar larguras de pulso", "secondary", command=self.testar).pack(fill="x", pady=2)
        Btn(c2, "Diagnostico do atraso de fonte", "secondary", command=self.diagnostico).pack(fill="x", pady=2)
        secao(c2, "OSCILOSCOPIO (trem continuo de pulsos)")
        self.campos["osc_w"] = Campo(c2, "Largura", 10, "ms")
        self.campos["osc_w"].pack(fill="x", pady=2)
        self.campos["osc_T"] = Campo(c2, "Periodo", 50, "ms")
        self.campos["osc_T"].pack(fill="x", pady=2)
        self.campos["osc_dur"] = Campo(c2, "Duracao", 30, "s")
        self.campos["osc_dur"].pack(fill="x", pady=2)
        lin = ctk.CTkFrame(c2, fg_color="transparent")
        lin.pack(fill="x", pady=2)
        Btn(lin, "Iniciar trem", "secondary", width=130, command=self.trem).pack(side="left", padx=(0, 4))
        Btn(lin, "Parar", "danger", width=80, command=self.parar).pack(side="left")
        nota(c2, "Usa o V do teste. Osciloscopio sobre o resistor, disparo NORMAL (nao AUTO), borda de "
                 "subida em ~metade de V; use a medida automatica +Width (media) ou o botao SINGLE.")
        nota(c2, "O diagnostico mede o periodo real do passo para atrasos de 0 a 100 ms (nivel constante e "
                 "alternando 0/V) e grava DIAG_atraso_fonte.csv. Use um resistor ou a ponta levantada.")

        # ------------------------------------------------------------ coluna 3: console
        c3 = self._coluna(2, "CONSOLE SCPI")
        self.cmd = Campo(c3, "Comando", "*IDN?")
        self.cmd.pack(fill="x", pady=2)
        lin = ctk.CTkFrame(c3, fg_color="transparent")
        lin.pack(fill="x")
        Btn(lin, "Enviar", "secondary", width=90, command=self._enviar).pack(side="left", padx=(0, 4))
        Btn(lin, "Consultar (?)", "secondary", width=110, command=self._consultar).pack(side="left", padx=(0, 4))
        Btn(lin, "Erros", "secondary", width=70, command=self._erros).pack(side="left")
        self.campos["log_scpi"] = Marca(c3, "Mostrar todo o trafego SCPI no log", False,
                                        comando=lambda: setattr(self.app.k, "log_scpi", self.campos["log_scpi"].get()))
        self.campos["log_scpi"].pack(fill="x", pady=4)
        secao(c3, "SOBRE A TEMPORIZACAO")
        ctk.CTkLabel(c3, text=TEXTO_TEMPORIZACAO, font=(FONTE, 10), text_color=C["dim"], justify="left",
                     wraplength=380, anchor="w").pack(fill="x")

    def _coluna(self, col, titulo):
        f = ctk.CTkFrame(self, fg_color=C["panel"], corner_radius=8, border_width=1, border_color=C["border"])
        f.grid(row=0, column=col, sticky="nsew", padx=4, pady=4)
        inner = ctk.CTkFrame(f, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=12, pady=8)
        secao(inner, titulo)
        return inner

    # ------------------------------------------------------------ estado
    def estado(self):
        return {k: w.get() for k, w in self.campos.items()}

    def restaurar(self, d):
        for k, v in (d or {}).items():
            if k in self.campos:
                try:
                    self.campos[k].set(v)
                except Exception:
                    pass

    def cfg_instrumento(self):
        c = self.campos
        return {"terminais": "FRON" if c["terminais"].get() == "Frontal" else "REAR",
                "quatro_fios": c["fios"].get().startswith("4"),
                "modo_off": c["modo_off"].get().split()[0].replace("NORMAL", "NORM"),
                "display_off": c["display_off"].get(), "autozero": c["autozero"].get()}

    def aplicar(self, silencioso=False):
        k = self.app.k
        k.cfg.update(self.cfg_instrumento())
        try:
            k.pausa_cmd_s = max(0.0, self.campos["pausa_ms"].val / 1e3)
            k.sincronismo = "opc" if self.campos["sincronismo"].get() == SINCRONISMOS[0] else "pausa"
            k.conferir_estado = bool(self.campos["conferir"].get())
            k.sobrecarga_s = max(0.0, self.campos["sobrecarga_ms"].val / 1e3)
        except ValueError as e:
            messagebox.showerror("Valor invalido", str(e))
            return
        if k.connected and not self.app.ocupado():
            try:
                k.aplicar_cfg_instrumento()
                k.erros()
            except Exception as e:
                self.app.log(f"Erro ao aplicar a configuracao: {e}", "error")
        if not silencioso:
            self.app.log(f"Configuracao: {k.cfg}; sobrecarga {k.sobrecarga_s*1e3:.3f} ms; sincronismo {k.sincronismo}; "
                         f"conferencia {'ligada' if k.conferir_estado else 'desligada'}", "info")

    def xonxoff(self):
        return self.campos["fluxo"].get() == FLUXOS[1]

    def _procurar(self):
        d = filedialog.askdirectory(title="Pasta raiz dos dados")
        if d:
            self.campos["raiz"].set(d)
            self.app.atualizar_destino()

    # ------------------------------------------------------------ temporizacao
    def trem(self):
        try:
            w = self.campos["osc_w"].val / 1e3
            T = self.campos["osc_T"].val / 1e3
            dur = self.campos["osc_dur"].val
            V = self.campos["teste_V"].val
        except ValueError as e:
            messagebox.showerror("Valor invalido", str(e))
            return
        if T <= w:
            messagebox.showerror("Valor invalido", "O periodo deve ser maior que a largura.")
            return
        self._rodar(lambda m: m.trem_osciloscopio(V, w, T, dur))

    def parar(self):
        ctx = getattr(self, "_ctx", None)
        if ctx is not None:
            ctx.parar.set()
            self.app.log("Parada solicitada (termina a lista em execucao, ~1-2 s).", "warn")

    def _rodar(self, alvo):
        if not self.app.k.connected:
            messagebox.showwarning("Sem conexao", "Conecte o instrumento primeiro.")
            return
        if self.app.ocupado():
            messagebox.showwarning("Ocupado", "Ha uma medida rodando.")
            return
        self.aplicar(silencioso=True)
        self.app.marcar_ocupado(self)

        ctx = Contexto(self.app.k, log=self.app.log, progresso=self.app.progresso_ts)
        self._ctx = ctx

        def run():
            try:
                alvo(Motor(ctx))
            except Cancelado:
                self.app.log("Interrompido pelo usuario.", "warn")
            except Exception as e:
                self.app.log(f"ERRO: {e}", "error")
            finally:
                self._ctx = None
                self.app.after(0, lambda: (self.app.marcar_ocupado(None), self.app.progresso(0, "")))
        threading.Thread(target=run, daemon=True).start()

    def calibrar(self):
        def f(m):
            T, s = m.calibrar_sobrecarga(nplc=0.01)
            self.app.log(f"T0 (NPLC 0,01, atraso 0, 200 passos) = {T*1e3:.3f} ms -> sobrecarga {s*1e3:.3f} ms; "
                         f"largura minima de pulso = T0, resolucao das larguras = T0", "info")
            self.app.after(0, lambda: self.campos["sobrecarga_ms"].set(f"{s*1e3:.3f}"))
        self._rodar(f)

    def diagnostico(self):
        try:
            V = self.campos["teste_V"].val
        except ValueError as e:
            messagebox.showerror("Valor invalido", str(e))
            return
        meta = self.app.metadados()

        def f(m):
            m.ctx._arq = lambda a: self.app.salvar_arquivo(a, meta)
            m.diag_atraso(V=V)
        self._rodar(f)

    def testar(self):
        try:
            ws = [x / 1e3 for x in self.campos["teste_w"].lista()]
            V = self.campos["teste_V"].val
        except ValueError as e:
            messagebox.showerror("Valor invalido", str(e))
            return

        def f(m):
            res = m.teste_largura(ws, V=V)
            self.app.log("w_nominal_ms | regime  k  | w_calibrada_ms | carimbos: media (min-max) ms", "info")
            for r in res:
                self.app.log(f"{r['w_nominal_ms']:12.3f} | {r['regime']:7s} {r['passos']:3d} | {r['w_calibrada_ms']:14.3f} | "
                             f"{r['w_carimbo_media_ms']:.2f} ({r['w_carimbo_min_ms']:.2f}-{r['w_carimbo_max_ms']:.2f})", "rx")
            self.app.log("Os carimbos do 2400 tem resolucao de 1/1024 s (0,977 ms): cada valor individual oscila "
                         "um tique; a media de varios pulsos converge para a largura real.", "info")
            s = self.app.k.sobrecarga_s
            self.app.after(0, lambda: self.campos["sobrecarga_ms"].set(f"{s*1e3:.3f}"))
        self._rodar(f)

    # ------------------------------------------------------------ console
    def _enviar(self):
        if self._ok():
            self.app.k.write(self.cmd.txt)
            self.app.log(f">> {self.cmd.txt}", "tx")

    def _consultar(self):
        if self._ok():
            r = self.app.k.query(self.cmd.txt, timeout=5.0)
            self.app.log(f">> {self.cmd.txt}", "tx")
            self.app.log(f"<< {r}", "rx")

    def _erros(self):
        if self._ok():
            e = self.app.k.erros()
            if not e:
                self.app.log("Fila de erros vazia", "info")

    def _ok(self):
        if not self.app.k.connected:
            messagebox.showwarning("Sem conexao", "Conecte o instrumento primeiro.")
            return False
        if self.app.ocupado():
            messagebox.showwarning("Ocupado", "Ha uma medida rodando.")
            return False
        self.app.k.invalidar_cache()
        return True
