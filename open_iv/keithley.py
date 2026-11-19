"""
Driver SCPI do Keithley 2400 SourceMeter para o Open-IV.

Principio de projeto (correcao da largura de pulso)
---------------------------------------------------
No MemristorProbe 1.3 o pulso era feito pelo PC:
    :SOUR:VOLT v  ->  :OUTP ON  ->  time.sleep(w)  ->  :OUTP OFF
A largura real ficava em ~50-60 ms para QUALQUER valor nominal, porque somava
o tempo de transmissao dos comandos a 9600 baud (~1 ms por caractere), a pausa
fixa de 15 ms apos cada comando, a granularidade do time.sleep() no Windows
(~15,6 ms) e o chaveamento do rele de saida.

No Open-IV TODA forma de onda (pulso, leitura, varredura, laco) e executada
pelo proprio instrumento como uma varredura de lista (custom sweep, ate 2500
pontos). Cada ponto da lista dura um ciclo SDM (source-delay-measure):
    T_passo = :SOUR:DEL + tempo de medida (NPLC/f_rede, autozero) + sobrecarga
A saida fica ligada no nivel de base (bias) e o instrumento volta ao bias ao
fim da lista; o PC nao participa da temporizacao. A largura REAL e obtida dos
carimbos de tempo (TIME) do proprio 2400: para a lista [V_base, V_pulso, V_base]
a largura e t[2] - t[1] (inicio do passo do pulso ate o inicio do passo seguinte).
"""
import threading
import time

import numpy as np

STAT_COMPLIANCE = 1 << 3        # bit 3 da palavra de status: compliance real
OVERFLOW = 9.0e37               # o 2400 devolve +9.91E37 em overflow
MAX_PONTOS_LISTA = 2500
MAX_VALORES_CMD = 50            # o 2400 aceita no maximo ~100 valores por comando de lista (-223)
BLOCO_BYTES = 32                # comandos longos sao enviados em blocos com pausa (evita -363)
MAX_BYTES_SEM_SYNC = 96         # modo "opc": no maximo isto em transito antes de esperar o *OPC?


def fmt(v):
    """Numero -> texto SCPI curto e exato o bastante."""
    if v == 0:
        return "0"
    return f"{v:.7G}"


class ErroInstrumento(RuntimeError):
    pass


class Keithley2400:
    def __init__(self, transporte=None):
        self.t = transporte
        self.lock = threading.RLock()
        self.idn_str = ""
        self.lfr = 60.0                 # frequencia da rede (lida de :SYST:LFR?)
        self.sobrecarga_s = 0.0015      # sobrecarga por ciclo SDM (calibravel)
        self.T0 = {}                    # periodo do passo sem atraso, por NPLC (calibrado)
        self.pausa_cmd_s = 0.002        # pausa apos cada linha enviada
        self.baud = 9600
        self.log = None                 # callable(msg, tag)
        self.log_scpi = False
        self._cache = {}
        self.cfg = {
            "terminais": "FRON",        # FRON | REAR
            "quatro_fios": False,
            "modo_off": "NORM",         # NORM | HIMP | ZERO
            "display_off": True,
            "autozero": True,           # para leituras DC (pulsos sempre OFF)
        }
        self._display_desligado = False
        self._sujo = False              # houve mudanca de configuracao desde a ultima checagem de erros
        self.pausa_bloco_s = 0.008      # pausa entre blocos de 32 bytes de um comando longo
        self.max_lista_verificada = None
        # Sincronismo (1.1.2). Sem controle de fluxo o 2400 perde bytes (-363) quando recebe
        # um comando enquanto ainda processa o anterior (ex.: um bloco de 50 valores de lista).
        #   "opc":   depois de cada comando longo, e sempre que ~96 bytes estiverem em transito,
        #            espera o '1' do *OPC? (o 2400 so responde depois de processar tudo antes dele)
        #   "pausa": so as pausas fixas (comportamento da 1.1.1, sujeito a -363)
        self.sincronismo = "opc"
        self.max_bytes_sem_sync = MAX_BYTES_SEM_SYNC
        self._pendentes = 0             # bytes enviados desde a ultima resposta do 2400
        self.n_sync = 0                 # contador de *OPC? (diagnostico)
        self.conferir_estado = True     # le de volta :SOUR:DEL?, :TRIG:COUN? etc. quando a config muda
        self.recuperar = True           # erro na fila -> reenvia a configuracao completa e repete o preparo
        self._ultima_cfg = None         # (metodo, kwargs) da ultima config_fonte_v/config_fonte_i

    # ------------------------------------------------------------------ baixo nivel
    @property
    def connected(self):
        return self.t is not None and self.t.is_open

    def _log(self, msg, tag="info"):
        if self.log:
            try:
                self.log(msg, tag)
            except Exception:
                pass

    def write(self, cmd):
        with self.lock:
            if self.log_scpi:
                self._log(f">> {cmd[:160]}{'...' if len(cmd) > 160 else ''}", "tx")
            dados = (cmd.strip() + "\n").encode("ascii")
            opc = self.sincronismo == "opc"
            if opc and self._pendentes and self._pendentes + len(dados) > self.max_bytes_sem_sync:
                self.sincronizar()
            self._tx(dados)
            self._pendentes += len(dados)
            # comando longo (bloco de lista): so segue quando o 2400 terminar de processa-lo
            if opc and len(dados) > self.max_bytes_sem_sync and "?" not in cmd:
                self.sincronizar()

    def _tx(self, dados):
        if len(dados) <= BLOCO_BYTES:
            self.t.write(dados)
        else:  # o buffer de entrada RS-232 do 2400 e pequeno: envia em blocos
            for i in range(0, len(dados), BLOCO_BYTES):
                self.t.write(dados[i:i + BLOCO_BYTES])
                time.sleep(max(self.pausa_bloco_s, 1.5 * self.tempo_transmissao(BLOCO_BYTES)))
        if self.pausa_cmd_s:
            time.sleep(self.pausa_cmd_s)

    def sincronizar(self, timeout=5.0):
        """
        Espera o 2400 processar tudo o que ja foi enviado (*OPC? -> '1'). Sem resposta
        significa que bytes se perderam (o proprio *OPC? pode ter sido corrompido).
        """
        with self.lock:
            if self.log_scpi:
                self._log(">> *OPC?", "tx")
            self._tx(b"*OPC?\n")
            self.n_sync += 1
            r = self.readline(timeout)
            if r.strip() not in ("1", "+1"):
                self.invalidar_cache()
                raise ErroInstrumento(f"o 2400 nao confirmou os comandos (*OPC? -> {r!r}); "
                                      "comunicacao perdida ou bytes descartados")

    def readline(self, timeout=5.0):
        with self.lock:
            r = self.t.readline(timeout)
            if r:
                self._pendentes = 0     # o 2400 ja processou tudo ate a consulta
            if self.log_scpi:
                self._log(f"<< {r[:160]}{'...' if len(r) > 160 else ''}", "rx")
            return r

    def query(self, cmd, timeout=5.0):
        with self.lock:
            self.write(cmd)
            return self.readline(timeout)

    def set(self, header, valor):
        """Envia 'header valor' somente se mudou desde o ultimo envio."""
        v = valor if isinstance(valor, str) else fmt(valor)
        if self._cache.get(header) == v:
            return
        self.write(f"{header} {v}")
        self._cache[header] = v
        self._sujo = True

    def invalidar_cache(self):
        self._cache.clear()

    def tempo_transmissao(self, n_chars):
        """Tempo para transmitir n caracteres (8N1 = 10 bits/caractere)."""
        return n_chars * 10.0 / max(300, self.baud)

    # ------------------------------------------------------------------ conexao
    def conectar(self, transporte, baud):
        self.t = transporte
        self.baud = baud
        self.invalidar_cache()
        self.t.flush_input()
        idn = self.query("*IDN?", timeout=3.0)
        if not idn:
            raise ErroInstrumento("Sem resposta ao *IDN? (confira cabo, baud e terminador)")
        self.idn_str = idn
        self.inicializar()
        return idn

    def desconectar(self):
        if not self.connected:
            return
        try:
            self.write(":OUTP OFF")
            self.write(":DISP:ENAB ON")
            self.write(":SYST:LOC")
        except Exception:
            pass
        self.t.close()

    def inicializar(self):
        """Estado conhecido: *RST e configuracoes fixas da sessao."""
        with self.lock:
            self.write("*RST")
            time.sleep(0.5)
            self.write("*CLS")
            self.invalidar_cache()
            self.write(":SYST:BEEP:STAT OFF")
            try:
                lf = self.query(":SYST:LFR?", timeout=2.0)
                self.lfr = float(lf) if lf else 60.0
            except ValueError:
                self.lfr = 60.0
            self.aplicar_cfg_instrumento()
            self._cfg_sessao()
            self.write(":SYST:TIME:RES")
            self.erros()
            m = self.sondar_lista()
            if m == 300:
                self._log("Lista do 2400: 300 pontos aceitos em blocos de 50 (OK)", "info")
            else:
                self._log(f"ATENCAO: o 2400 aceitou {m} de 300 pontos de lista. Laços longos podem falhar.", "warn")

    def _cfg_sessao(self):
        self.write(":SOUR:CLE:AUTO OFF")     # saida NAO desliga entre leituras
        self.write(":SOUR:DEL:AUTO OFF")
        self.write(":TRIG:DEL 0")
        self.write(":ARM:COUN 1")

    def restaurar_estado(self):
        """
        Depois de um erro: descarta o cache e reenvia TODA a configuracao (sessao,
        terminais, display e a ultima config_fonte_v/i). As listas sao reenviadas pelo
        chamador, que tambem confere a fila de erros antes de medir.
        """
        with self.lock:
            self.invalidar_cache()
            self._tx(b"\n")             # encerra uma linha que tenha ficado pela metade no 2400
            time.sleep(0.1)
            self.t.flush_input()
            self._pendentes = 0
            self.write("*CLS")
            self.aplicar_cfg_instrumento()
            self._cfg_sessao()
            if self._display_desligado:
                self.write(":DISP:ENAB OFF")
            if self._ultima_cfg:
                f, kw = self._ultima_cfg
                f(**kw)
            self._sujo = True

    def aplicar_cfg_instrumento(self):
        c = self.cfg
        self.write(f":ROUT:TERM {c['terminais']}")
        self.write(f":SYST:RSEN {'ON' if c['quatro_fios'] else 'OFF'}")
        self.write(f":OUTP:SMOD {c['modo_off']}")

    def erros(self):
        """
        Esvazia a fila de erros; registra no log e retorna a lista. Havendo erro, algum
        comando pode nao ter sido aplicado: o cache e descartado (senao ele passaria a
        descrever um estado que o 2400 nao tem, como o :SOUR:DEL do T0 de 10,5 ms).
        """
        lst = []
        for _ in range(25):
            r = self.query(":SYST:ERR?", timeout=2.0)
            if not r or r.startswith("0") or r.startswith("+0"):
                break
            lst.append(r)
        for e in lst:
            self._log(f"Erro do instrumento: {e}", "error")
        if lst:
            self.invalidar_cache()
        self._sujo = False
        return lst

    def verificar(self):
        """
        Antes de medir: se a configuracao mudou, confere a fila de erros. Qualquer erro
        significa que algum comando nao foi aplicado; a medida e interrompida (o estado
        do 2400 seria desconhecido) e o cache e descartado.
        """
        if not self._sujo:
            return
        e = self.erros()
        if e:
            raise ErroInstrumento("o 2400 recusou comandos de configuracao: " + "; ".join(e[:4]))

    def _consultar_num(self, cmd):
        r = self.query(cmd, timeout=3.0)
        try:
            return float(r)
        except ValueError:
            raise ErroInstrumento(f"resposta invalida a {cmd}: {r!r}")

    def conferir(self, func, n, sour_del):
        """Le de volta os parametros criticos de uma lista; diferenca -> ErroInstrumento."""
        dif = []
        sd = self._consultar_num(":SOUR:DEL?")
        if abs(sd - sour_del) > 1.5e-5 + 1e-4 * sour_del:
            dif.append(f":SOUR:DEL {sd:g} (esperado {sour_del:g})")
        tc = self._consultar_num(":TRIG:COUN?")
        if int(round(tc)) != n:
            dif.append(f":TRIG:COUN {tc:g} (esperado {n})")
        pts = self._consultar_num(f":SOUR:LIST:{func}:POIN?")
        if int(round(pts)) != n:
            dif.append(f"lista com {pts:g} pontos (esperado {n})")
        modo = self.query(f":SOUR:{func}:MODE?", timeout=3.0).strip().upper()
        if not modo.startswith("LIST"):
            dif.append(f":SOUR:{func}:MODE {modo!r} (esperado LIST)")
        if dif:
            self.invalidar_cache()
            raise ErroInstrumento("estado do 2400 diferente do programado: " + "; ".join(dif))

    def sondar_lista(self, n=300):
        """Confere se o 2400 aceita listas longas enviadas em blocos (:APPend)."""
        self._cache.pop("lista_VOLT", None)
        self._enviar_lista("VOLT", [0.0] * n, verificar=False)
        try:
            m = int(float(self.query(":SOUR:LIST:VOLT:POIN?", timeout=3.0)))
        except ValueError:
            m = None
        self.max_lista_verificada = m
        self._cache.pop("lista_VOLT", None)
        self.erros()
        return m

    # ------------------------------------------------------------------ saida
    def saida(self, ligar):
        self.write(":OUTP ON" if ligar else ":OUTP OFF")
        self._cache[":OUTP"] = "ON" if ligar else "OFF"

    def display(self, ligar):
        self.write(":DISP:ENAB ON" if ligar else ":DISP:ENAB OFF")
        self._display_desligado = not ligar

    def inicio_medida(self):
        if self.cfg.get("display_off"):
            self.display(False)

    def fim_medida(self, desligar_saida=True):
        """Volta a 0 V e desliga a saida (padrao da campanha: OFF entre arquivos)."""
        try:
            self.set(":SOUR:VOLT:MODE", "FIX")
            self.write(":SOUR:VOLT:LEV 0")
            if desligar_saida:
                self.saida(False)
            if self._display_desligado:
                self.display(True)
        except Exception:
            pass

    # ------------------------------------------------------------------ tempos
    def tempo_medida(self, nplc, autozero, n_funcoes=1):
        """Estimativa do tempo de medida de um ciclo SDM (sem o :SOUR:DEL)."""
        t_int = nplc / self.lfr
        fator = 3.0 if autozero else 1.0
        return n_funcoes * t_int * fator + self.sobrecarga_s

    # ------------------------------------------------------------------ configuracao
    def config_fonte_v(self, compliance, nplc, faixa_i="AUTO", medir_v=False,
                       autozero=None, faixa_v=None):
        """Fonte de tensao, mede corrente."""
        self._ultima_cfg = (self.config_fonte_v, dict(compliance=compliance, nplc=nplc, faixa_i=faixa_i,
                                                      medir_v=medir_v, autozero=autozero, faixa_v=faixa_v))
        az = self.cfg["autozero"] if autozero is None else autozero
        if self._cache.get(":SOUR:FUNC") != "VOLT":
            self._cache.pop(":OUTP", None)     # religa a saida na proxima lista
        self.set(":SOUR:FUNC", "VOLT")
        self.set(":SENS:FUNC:CONC", "ON")
        funcs = '"VOLT","CURR"' if medir_v else '"CURR"'
        if self._cache.get("funcs") != funcs:
            self.write(":SENS:FUNC:OFF:ALL")
            self.write(f":SENS:FUNC:ON {funcs}")
            self._cache["funcs"] = funcs
        self.set(":SENS:CURR:PROT", float(compliance))
        if isinstance(faixa_i, str) and faixa_i.upper() == "AUTO":
            self.set(":SENS:CURR:RANG:AUTO", "ON")
        else:
            self.set(":SENS:CURR:RANG:AUTO", "OFF")
            self.set(":SENS:CURR:RANG", float(faixa_i))
        self.set(":SENS:CURR:NPLC", float(nplc))
        if medir_v:
            self.set(":SENS:VOLT:NPLC", float(nplc))
        self.set(":SYST:AZER:STAT", "ON" if az else "OFF")
        if faixa_v is not None:
            self.set(":SOUR:VOLT:RANG:AUTO", "OFF")
            self.set(":SOUR:VOLT:RANG", max(0.2, float(faixa_v)))
        self.set(":SOUR:SWE:RANG", "BEST")
        elems = "VOLT,CURR,TIME,STAT" if medir_v else "CURR,TIME,STAT"
        self.set(":FORM:ELEM", elems)
        self._modo = "V"
        self._medir_v = medir_v
        self._nfunc = 2 if medir_v else 1
        self._az = az
        self._nplc = nplc

    def config_fonte_i(self, limite_v, nplc, faixa_v="AUTO", corrente=0.0, faixa_i=1e-6,
                       autozero=None):
        """Fonte de corrente (I = 0 para V_oc), mede tensao."""
        self._ultima_cfg = (self.config_fonte_i, dict(limite_v=limite_v, nplc=nplc, faixa_v=faixa_v,
                                                      corrente=corrente, faixa_i=faixa_i, autozero=autozero))
        az = self.cfg["autozero"] if autozero is None else autozero
        if self._cache.get(":SOUR:FUNC") != "CURR":
            self._cache.pop(":OUTP", None)
        self.set(":SOUR:FUNC", "CURR")
        self.set(":SOUR:CURR:MODE", "FIX")
        self.set(":SOUR:CURR:RANG:AUTO", "OFF")
        self.set(":SOUR:CURR:RANG", float(faixa_i))
        self.write(f":SOUR:CURR:LEV {fmt(corrente)}")
        self.set(":SENS:FUNC:CONC", "ON")
        if self._cache.get("funcs") != '"VOLT"':
            self.write(":SENS:FUNC:OFF:ALL")
            self.write(':SENS:FUNC:ON "VOLT"')
            self._cache["funcs"] = '"VOLT"'
        self.set(":SENS:VOLT:PROT", float(limite_v))
        if isinstance(faixa_v, str) and faixa_v.upper() == "AUTO":
            self.set(":SENS:VOLT:RANG:AUTO", "ON")
        else:
            self.set(":SENS:VOLT:RANG:AUTO", "OFF")
            self.set(":SENS:VOLT:RANG", float(faixa_v))
        self.set(":SENS:VOLT:NPLC", float(nplc))
        self.set(":SYST:AZER:STAT", "ON" if az else "OFF")
        self.set(":SOUR:SWE:RANG", "BEST")
        self.set(":FORM:ELEM", "VOLT,TIME,STAT")
        self._modo = "I"
        self._medir_v = True
        self._nfunc = 1
        self._az = az
        self._nplc = nplc

    # ------------------------------------------------------------------ execucao
    def _parse(self, resp, n_esperado):
        try:
            vals = [float(x) for x in resp.split(",") if x.strip()]
        except ValueError:
            raise ErroInstrumento(f"Resposta invalida: {resp[:80]}")
        if self._modo == "V":
            ne = 4 if self._medir_v else 3
        else:
            ne = 3
        if len(vals) != ne * n_esperado:
            raise ErroInstrumento(
                f"Esperava {ne * n_esperado} valores, recebi {len(vals)} "
                f"(timeout curto ou baud incorreto?)")
        a = np.array(vals, dtype=float).reshape(n_esperado, ne)
        a[np.abs(a) > OVERFLOW] = np.nan
        out = {}
        if self._modo == "V":
            if self._medir_v:
                out["V"], out["I"], out["t"], st = a[:, 0], a[:, 1], a[:, 2], a[:, 3]
            else:
                out["V"] = None
                out["I"], out["t"], st = a[:, 0], a[:, 1], a[:, 2]
        else:
            out["V"], out["t"], st = a[:, 0], a[:, 1], a[:, 2]
            out["I"] = None
        st = np.nan_to_num(st).astype(np.int64)
        out["stat"] = st
        out["compliance"] = (st & STAT_COMPLIANCE) != 0
        return out

    def _enviar_lista(self, func, valores, verificar=True):
        """:SOUR:LIST:<func> em comandos de ate 50 valores (:APPend) e conferencia do total."""
        txt = [fmt(v) for v in valores]
        chave = f"lista_{func}"
        assinatura = ",".join(txt)
        if self._cache.get(chave) == assinatura:
            return
        self._cache.pop(chave, None)
        blocos = [txt[i:i + MAX_VALORES_CMD] for i in range(0, len(txt), MAX_VALORES_CMD)]
        self.write(f":SOUR:LIST:{func} " + ",".join(blocos[0]))
        for b in blocos[1:]:
            self.write(f":SOUR:LIST:{func}:APP " + ",".join(b))
        self._sujo = True
        if verificar:
            r = self.query(f":SOUR:LIST:{func}:POIN?", timeout=3.0)
            try:
                m = int(float(r))
            except ValueError:
                m = -1
            if m != len(valores):
                e = self.erros()
                self.invalidar_cache()
                raise ErroInstrumento(f"o 2400 ficou com {m} de {len(valores)} pontos na lista"
                                      + (f" ({'; '.join(e[:3])})" if e else ""))
        self._cache[chave] = assinatura

    def executar_lista(self, valores, sour_del, trig_del=0.0, bias=0.0, func="VOLT", ler_dados=True):
        """
        Executa uma varredura de lista temporizada pelo instrumento.
        valores: niveis (V ou A); sour_del: atraso de fonte por ponto (s);
        bias: nivel de repouso antes e depois da lista.
        Retorna dict com arrays V, I, t (carimbo do 2400, s), stat, compliance,
        mais 'V_prog' (niveis programados) e 't_pc' (perf_counter ao fim da resposta).
        """
        n = len(valores)
        if n < 1 or n > MAX_PONTOS_LISTA:
            raise ValueError(f"A lista deve ter de 1 a {MAX_PONTOS_LISTA} pontos (tem {n}).")
        sour_del = max(0.0, float(sour_del))
        with self.lock:
            for tentativa in (1, 2):
                try:
                    self._preparar_lista(valores, sour_del, trig_del, bias, func)
                    break
                except ErroInstrumento as e:
                    if tentativa == 2 or not self.recuperar:
                        raise ErroInstrumento(f"{e}. Medida interrompida (estado do 2400 desconhecido).")
                    # nada foi executado ainda (sem :READ?): reenviar tudo e preparar de novo e seguro
                    self._log(f"Comunicacao: {e}. Reenviando a configuracao completa.", "warn")
                    self.restaurar_estado()
            passo = sour_del + max(0.0, trig_del) + self.tempo_medida(self._nplc, self._az, self._nfunc)
            ne = (4 if self._medir_v else 3) if self._modo == "V" else 3
            t_tx = self.tempo_transmissao(n * ne * 15)
            timeout = n * passo * 1.5 + t_tx * 1.5 + 5.0
            if not ler_dados:   # executa sem devolver dados (ex.: trem para osciloscopio)
                self.write(":INIT")
                r = self.query("*OPC?", timeout=n * passo * 1.5 + 5.0)
                if not r:
                    raise ErroInstrumento("Sem resposta ao *OPC? apos :INIT")
                return None
            self.write(":READ?")
            resp = self.readline(timeout=timeout)
            t_pc = time.perf_counter()
            if not resp:
                raise ErroInstrumento(f"Sem resposta ao :READ? (timeout {timeout:.1f} s)")
            out = self._parse(resp, n)
            out["V_prog"] = np.asarray(valores, dtype=float)
            if out["V"] is None:
                out["V"] = out["V_prog"].copy()
            out["t_pc"] = t_pc
            out["t_tx"] = t_tx
            return out

    def _preparar_lista(self, valores, sour_del, trig_del, bias, func):
        n = len(valores)
        modo = f":SOUR:{func}:MODE"
        # bias primeiro (em modo FIX o nivel e aplicado imediatamente)
        self.set(modo, "FIX")
        self.write(f":SOUR:{func}:LEV {fmt(bias)}")
        self._enviar_lista(func, valores)
        self.set(modo, "LIST")
        self.set(":SOUR:DEL", round(sour_del, 5))
        self.set(":TRIG:DEL", round(max(0.0, trig_del), 5))
        self.set(":TRIG:COUN", n)
        if self._cache.get(":OUTP") != "ON":
            self.saida(True)
        mudou = self._sujo
        self.verificar()
        if mudou and self.conferir_estado:
            self.conferir(func, n, round(sour_del, 5))

    def ponto_fixo(self, nivel, func="VOLT"):
        """Ponto a ponto (modo FIX): aplica o nivel e mede uma vez."""
        with self.lock:
            self.set(f":SOUR:{func}:MODE", "FIX")
            self.set(":TRIG:COUN", 1)
            if self._cache.get(":OUTP") != "ON":
                self.saida(True)
            self.write(f":SOUR:{func}:LEV {fmt(nivel)}")
            self._cache.pop("lista_" + func, None)
            passo = float(self._cache.get(":SOUR:DEL", "0")) + self.tempo_medida(self._nplc, self._az, self._nfunc)
            self.verificar()
            self.write(":READ?")
            resp = self.readline(timeout=passo * 2 + 5.0)
            if not resp:
                raise ErroInstrumento("Sem resposta ao :READ?")
            out = self._parse(resp, 1)
            if out["V"] is None:
                out["V"] = np.array([nivel], dtype=float)
            out["V_prog"] = np.array([nivel], dtype=float)
            out["t_pc"] = time.perf_counter()
            return out

    def nivel(self, valor, func="VOLT"):
        """Aplica um nivel DC (modo FIX) sem medir."""
        self.set(f":SOUR:{func}:MODE", "FIX")
        self.write(f":SOUR:{func}:LEV {fmt(valor)}")

    def atraso_fonte(self, s):
        self.set(":SOUR:DEL", round(max(0.0, s), 5))
