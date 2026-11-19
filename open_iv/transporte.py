"""
Transporte serial (RS-232) para o Keithley 2400.

No Windows usa um driver Win32 minimo, com o contorno do adaptador CH340 (o
SetCommState falha com erro 31 ou nao aplica o baud; ver _Win32Serial.configurar).
O pyserial fica como reserva no Windows e e o padrao nos outros sistemas.
"""
import sys
import time
import struct

try:
    import serial
    import serial.tools.list_ports
    HAS_PYSERIAL = True
except ImportError:  # pragma: no cover
    HAS_PYSERIAL = False


def listar_portas():
    """Lista as portas seriais: [{'device', 'desc', 'hwid', 'label'}]."""
    if not HAS_PYSERIAL:
        return []
    out = []
    for p in serial.tools.list_ports.comports():
        desc = p.description or "Desconhecido"
        out.append({"device": p.device, "desc": desc, "hwid": p.hwid or "",
                    "label": f"{p.device}  -  {desc}"})
    return out


class TransporteSerial:
    """Interface comum: open/close/write(bytes|str)/readline(timeout)/flush_input."""

    def __init__(self):
        self._ser = None
        self.metodo = None
        self.erro_pyserial = ""
        self.erro_win32 = ""
        self.xonxoff = False

    @property
    def is_open(self):
        return self._ser is not None and self._ser.is_open

    def open(self, porta, baud=9600, xonxoff=False):
        """xonxoff=True exige FLOW-CTRL = XON-XOFF no 2400 (MENU > COMMUNICATION > RS-232)."""
        erro = None
        self.xonxoff = bool(xonxoff)
        if sys.platform == "win32":
            # No Windows o driver proprio vem primeiro: o pyserial refaz o SetCommState sem a
            # sequencia de contorno do CH340 (ver _Win32Serial.configurar) e o baud pode nao valer.
            try:
                w = _Win32Serial()
                w.open(porta, baud, self.xonxoff)
                time.sleep(0.2)
                w.reset_input_buffer()
                self._ser = w
                self.metodo = "win32"
                return self.metodo
            except Exception as e:
                erro = e
                self.erro_win32 = f"{type(e).__name__}: {e}"
        if HAS_PYSERIAL:
            try:
                # timeout fixo: mudar timeout/baud/etc. depois de aberto refaz o SetCommState (CH340: erro 31)
                s = serial.Serial(port=porta, baudrate=baud, bytesize=8, parity="N",
                                  stopbits=1, timeout=0.05, write_timeout=5,
                                  xonxoff=self.xonxoff, rtscts=False, dsrdtr=False)
                time.sleep(0.2)
                s.reset_input_buffer()
                s.reset_output_buffer()
                self._ser = s
                self.metodo = "pyserial"
                return self.metodo
            except Exception as e:
                self.erro_pyserial = f"{type(e).__name__}: {e}"
                erro = f"{self.erro_win32 + '; ' if self.erro_win32 else ''}pyserial: {self.erro_pyserial}"
        raise OSError(f"Nao foi possivel abrir {porta}: {erro}")

    def close(self):
        if self._ser is not None:
            try:
                self._ser.close()
            finally:
                self._ser = None

    def write(self, data):
        if isinstance(data, str):
            data = data.encode("ascii")
        self._ser.write(data)

    def readline(self, timeout=5.0):
        """Le ate CR/LF. Retorna str sem terminador ('' em timeout)."""
        if self.metodo == "win32":
            return self._ser.readline(timeout)
        s = self._ser
        buf =bytearray(getattr(self, "_resto", b""))
        self._resto = b""
        t_lim = time.perf_counter() + timeout
        while True:
            # linha completa ja no buffer?
            for i, b in enumerate(buf):
                if b in (10, 13):
                    linha = bytes(buf[:i]).strip()
                    if linha:
                        self._resto = bytes(buf[i + 1:]).lstrip(b"\r\n")
                        return linha.decode("ascii", errors="replace").strip()
            buf = bytearray(bytes(buf).lstrip(b"\r\n"))
            if time.perf_counter() >= t_lim:
                break
            n = s.in_waiting
            chunk = s.read(n if n else 1)
            if chunk:
                buf += chunk
        self._resto = b""
        return bytes(buf).decode("ascii", errors="replace").strip()

    def flush_input(self):
        self._resto = b""
        try:
            if self.metodo == "win32":
                self._ser.reset_input_buffer()
            else:
                self._ser.reset_input_buffer()
        except Exception:
            pass


class _Win32Serial:
    """Driver Win32 minimo (fallback quando o pyserial nao abre a porta)."""
    GENERIC_RW = 0xC0000000
    OPEN_EXISTING = 3

    def __init__(self):
        import ctypes
        self._k = ctypes.WinDLL("kernel32", use_last_error=True)
        self._h = None

    @property
    def is_open(self):
        return self._h is not None

    def _falha(self, oque):
        import ctypes
        cod = ctypes.get_last_error()
        return OSError(f"{oque} falhou (erro Win32 {cod}: {ctypes.FormatError(cod).strip()})")

    def open(self, porta, baud, xonxoff=False):
        import ctypes
        self._k.CreateFileW.restype = ctypes.c_void_p
        h = self._k.CreateFileW(f"\\\\.\\{porta}", self.GENERIC_RW, 0, None,
                                self.OPEN_EXISTING, 0, None)
        if h in (None, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
            raise self._falha(f"CreateFile({porta})")
        self._h = ctypes.c_void_p(h)
        try:
            self._k.SetupComm(self._h, 4096, 4096)       # como o pyserial (falha nao e fatal)
            self.configurar(baud, xonxoff)
            self._set_timeouts(0.05)
            self._k.PurgeComm(self._h, 0x000F)
        except Exception:
            self.close()
            raise

    def _ler_dcb(self):
        import ctypes
        dcb = ctypes.create_string_buffer(28)
        struct.pack_into("I", dcb, 0, 28)           # DCBlength
        if not self._k.GetCommState(self._h, dcb):
            raise self._falha("GetCommState")
        return dcb

    def configurar(self, baud, xonxoff=False):
        """
        8N1, sem controle por hardware, XON/XOFF opcional. O driver CH340 desta maquina
        (medido em 19/11/2026) recusa o SetCommState com erro 31 se nem a configuracao
        anterior nem a nova estiver em 9600 baud, e as vezes aplica so parte da mudanca.
        Contorno: em caso de falha, passa por 9600 baud e repete; confere lendo de volta.
        """
        import ctypes
        dcb = self._ler_dcb()
        struct.pack_into("I", dcb, 4, int(baud))     # BaudRate
        flags = struct.unpack_from("I", dcb, 8)[0]
        flags |= 0x0001                               # fBinary
        # sem paridade, CTS, DSR, XON/XOFF, ErrorChar, Null e AbortOnError
        flags &= ~((1 << 1) | (1 << 2) | (1 << 3) | (1 << 6) | (1 << 8) | (1 << 9)
                   | (1 << 10) | (1 << 11) | (1 << 14))
        if xonxoff:
            flags |= (1 << 7) | (1 << 8) | (1 << 9)   # fTXContinueOnXoff, fOutX (obedece o XOFF do 2400), fInX
        flags = (flags & ~(0x3 << 4)) | (1 << 4)      # DTR ligado (como o pyserial)
        flags = (flags & ~(0x3 << 12)) | (1 << 12)    # RTS ligado
        struct.pack_into("I", dcb, 8, flags)
        struct.pack_into("H", dcb, 14, 512)          # XonLim (buffer de 4096)
        struct.pack_into("H", dcb, 16, 512)          # XoffLim
        struct.pack_into("B", dcb, 18, 8)            # ByteSize
        struct.pack_into("B", dcb, 19, 0)            # Parity = NONE
        struct.pack_into("B", dcb, 20, 0)            # StopBits = 1
        struct.pack_into("B", dcb, 21, 0x11)         # XonChar
        struct.pack_into("B", dcb, 22, 0x13)         # XoffChar
        # ate a 1.1.1 a falha do SetCommState era ignorada: a porta ficava com a configuracao anterior
        # Sempre a mesma sequencia (alvo -> 9600 -> alvo): um SetCommState que "passa" de primeira
        # pode nao ter mudado o baud do chip (visto com 9600 -> 57600 direto: o 2400 nao respondia).
        self.contorno_ch340 = not self._k.SetCommState(self._h, dcb)
        inter = ctypes.create_string_buffer(dcb.raw)
        struct.pack_into("I", inter, 4, 9600 if int(baud) != 9600 else 19200)
        self._k.SetCommState(self._h, inter)
        if not self._k.SetCommState(self._h, dcb):
            raise self._falha(f"SetCommState({baud} baud, xonxoff={xonxoff})")
        lido = self._ler_dcb()
        b_lido = struct.unpack_from("I", lido, 4)[0]
        x_lido = bool(struct.unpack_from("I", lido, 8)[0] & (1 << 8))
        if b_lido != int(baud) or x_lido != bool(xonxoff):
            raise OSError(f"a porta ficou com {b_lido} baud e XON/XOFF {'ligado' if x_lido else 'desligado'} "
                          f"(pedido: {baud} baud, XON/XOFF {'ligado' if xonxoff else 'desligado'})")

    def _set_timeouts(self, t):
        import ctypes
        ms = max(1, int(t * 1000))
        to = ctypes.create_string_buffer(struct.pack("IIIII", 0, 0, ms, 0, 5000))
        if not self._k.SetCommTimeouts(self._h, to):
            raise self._falha("SetCommTimeouts")

    def close(self):
        if self._h is not None:
            self._k.CloseHandle(self._h)
            self._h = None

    def write(self, data):
        import ctypes
        import ctypes.wintypes as wt
        n = wt.DWORD()
        if not self._k.WriteFile(self._h, data, len(data), ctypes.byref(n), None):
            raise self._falha("WriteFile")
        if n.value != len(data):   # com XON/XOFF, o 2400 pode segurar o envio ate o timeout de 5 s
            raise OSError(f"WriteFile enviou {n.value} de {len(data)} bytes (timeout de escrita)")
        return n.value

    def readline(self, timeout=5.0):
        import ctypes
        import ctypes.wintypes as wt
        buf = ctypes.create_string_buffer(1)
        rc = wt.DWORD()
        out = bytearray()
        t_lim = time.perf_counter() + timeout
        while time.perf_counter() < t_lim:
            self._k.ReadFile(self._h, buf, 1, ctypes.byref(rc), None)
            if rc.value == 0:
                continue
            b = buf.raw[0]
            if b in (10, 13):
                if out:
                    break
                continue
            out.append(b)
        return out.decode("ascii", errors="replace").strip()

    def reset_input_buffer(self):
        if self._h is not None:
            self._k.PurgeComm(self._h, 0x000A)
