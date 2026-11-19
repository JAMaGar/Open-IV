"""
Teste da comunicacao com o Keithley 2400 REAL (sem interface grafica).
SO COM O RESISTOR DE TESTE nos terminais: |V| <= 1 V, compliance <= 10 mA, NPLC >= 0,01.

Uso:
    python testes/teste_serial_2400.py COM14 57600 envio  --sinc pausa --n200 50      (reproduz o -363)
    python testes/teste_serial_2400.py COM14 57600 envio  --sinc opc --n200 100 --n2500 20
    python testes/teste_serial_2400.py COM14 57600 aceite --sinc opc                  (criterios 1.1.2)
    --fluxo xonxoff exige FLOW-CTRL = XON-XOFF no 2400.
Ao fim: saida desligada (:OUTP OFF) e display ligado (:DISP:ENAB ON).
"""
import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from open_iv.keithley import Keithley2400, ErroInstrumento
from open_iv.transporte import TransporteSerial
from open_iv.medidas import Contexto, Motor

V_MAX, I_MAX, NPLC_MIN = 1.0, 0.01, 0.01


def log(msg, tag="info"):
    print(f"{time.strftime('%H:%M:%S')}  [{tag}] {msg}", flush=True)


def contar(k, rotulo, n_pontos, vezes, valor=0.0):
    """Envia 'vezes' listas de n_pontos (cache descartado) e conta erros e listas incompletas."""
    n363 = outros = incompletas = 0
    t0 = time.perf_counter()
    for i in range(vezes):
        k._cache.pop("lista_VOLT", None)
        vals = [valor * ((j + i) % 2) for j in range(n_pontos)]
        try:
            k._enviar_lista("VOLT", vals)
        except ErroInstrumento as e:
            incompletas += 1
            print(f"   lista {i + 1}: {e}")
        for e in k.erros():
            if "-363" in e:
                n363 += 1
            else:
                outros += 1
    dt = time.perf_counter() - t0
    log(f"{rotulo}: {vezes} listas de {n_pontos} pontos -> {incompletas} incompletas, {n363} erros -363, "
        f"{outros} outros erros; {dt / vezes * 1e3:.0f} ms por lista; *OPC? enviados: {k.n_sync}",
        "ok" if not (incompletas or n363 or outros) else "error")
    return incompletas + n363 + outros


def aceite(k):
    falhas = 0
    m = Motor(Contexto(k, log=log))
    # T0 10x
    T0s = []
    for i in range(10):
        T0, s = m.calibrar_sobrecarga(nplc=0.01)
        T0s.append(T0)
    e = k.erros()
    ok = (max(T0s) - min(T0s)) <= 0.04e-3 and not e
    falhas += not ok
    log(f"Medir T0 10x: {', '.join(f'{x*1e3:.3f}' for x in T0s)} ms (faixa {(max(T0s)-min(T0s))*1e3:.3f} ms)",
        "ok" if ok else "error")
    # larguras
    res = m.teste_largura([0.001, 0.002, 0.005, 0.01, 0.05, 0.1], V=1.0, nplc=0.01, compliance=0.01)
    e = k.erros()
    falhas += bool(e)
    for r in res:
        log(f"  w {r['w_nominal_ms']:6.1f} ms -> calibrada {r['w_calibrada_ms']:7.3f} ms ({r['regime']}, k={r['passos']}), "
            f"carimbos {r['w_carimbo_media_ms']:.2f} ({r['w_carimbo_min_ms']:.2f}-{r['w_carimbo_max_ms']:.2f})")
    # laco I-V 401 pontos
    m.iniciar()
    try:
        k.config_fonte_v(0.01, 0.01, "AUTO", medir_v=False, autozero=False, faixa_v=2)
        laco = [round(x, 4) for x in np.concatenate([np.arange(-1, 1, 0.01), np.arange(1, -1.0001, -0.01)])]
        assert max(abs(v) for v in laco) <= V_MAX
        r = m._lista(laco, 0.0)
        R = np.polyfit(np.asarray(laco), r["I"], 1)
        ok = len(r["I"]) == 401 and not k.erros()
        falhas += not ok
        log(f"Laco -1 -> +1 -> -1 V, 401 pontos: R ajustado = {1/R[0]/1e3:.2f} kOhm, "
            f"duracao {(r['t'][-1]-r['t'][0]):.3f} s", "ok" if ok else "error")
    finally:
        m.finalizar()
    return falhas


def alternado(k, duracao=300.0):
    """Aba Pulsos, modo Alternado, +-1 V, 10 ms, leitura a 0,5 V, por 'duracao' segundos."""
    linhas, erros_log = [], []

    def lg(msg, tag="info"):
        if tag in ("error", "warn"):
            erros_log.append(msg)
            log(msg, tag)

    m = Motor(Contexto(k, log=lg, ao_arquivo=lambda a: linhas.extend(a.linhas)))
    p = dict(modo="Alternado", V_set=1.0, V_reset=-1.0, w_set=0.01, w_reset=0.01, n_pulsos=40, V_read=0.5,
             t_read=0.2, media_read=0.1, nplc_read=1, base=0.0, nplc_pulso=0.01, compliance=0.01, periodo=0,
             reset_ref=None, etapa="TESTE-ALT", param="ALT", aleatorio=False)
    assert max(abs(p["V_set"]), abs(p["V_reset"]), abs(p["V_read"])) <= V_MAX and p["compliance"] <= I_MAX
    t0 = time.perf_counter()
    blocos = 0
    while time.perf_counter() - t0 < duracao:
        m.exp_pulsos(p)
        blocos += 1
    e = k.erros()
    pul = [l for l in linhas if l.get("n", 0) > 0]
    w = np.array([l["w_calibrada_ms"] for l in pul])
    R = np.array([l["R_ohm"] for l in pul])
    ok = not e and not erros_log and len(pul) > 0
    log(f"Alternado +-1 V, 10 ms, {time.perf_counter() - t0:.0f} s: {len(pul)} pulsos em {blocos} blocos, "
        f"w_calibrada {w.min():.3f}-{w.max():.3f} ms, R_leitura {np.nanmin(R)/1e3:.2f}-{np.nanmax(R)/1e3:.2f} kOhm, "
        f"erros {len(e) + len(erros_log)}", "ok" if ok else "error")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("porta")
    ap.add_argument("baud", type=int)
    ap.add_argument("teste", choices=["envio", "aceite", "alternado", "conexao"])
    ap.add_argument("--sinc", choices=["opc", "pausa"], default="opc")
    ap.add_argument("--fluxo", choices=["nenhum", "xonxoff"], default="nenhum")
    ap.add_argument("--n200", type=int, default=0)
    ap.add_argument("--n2500", type=int, default=0)
    a = ap.parse_args()

    tr = TransporteSerial()
    metodo = tr.open(a.porta, a.baud, xonxoff=a.fluxo == "xonxoff")
    log(f"porta {a.porta} aberta via {metodo} @ {a.baud} baud, fluxo {a.fluxo}"
        + (f" (pyserial: {tr.erro_pyserial})" if tr.erro_pyserial else ""))
    k = Keithley2400()
    k.log = log
    k.sincronismo = a.sinc
    falhas = 0
    try:
        idn = k.conectar(tr, a.baud)
        log(f"*IDN? -> {idn}")
        k.config_fonte_v(I_MAX, NPLC_MIN, I_MAX, medir_v=False, autozero=False, faixa_v=2)
        k.erros()
        if a.teste == "envio":
            if a.n200:
                falhas += contar(k, f"sinc={a.sinc}", 200, a.n200)
            if a.n2500:
                falhas += contar(k, f"sinc={a.sinc}", 2500, a.n2500, valor=-0.987654)
        elif a.teste == "aceite":
            falhas += contar(k, f"sinc={a.sinc}", 200, a.n200 or 100)
            falhas += contar(k, f"sinc={a.sinc}", 2500, a.n2500 or 20, valor=-0.987654)
            falhas += aceite(k)
        elif a.teste == "alternado":
            falhas += alternado(k)
    finally:
        try:
            k.write(":OUTP OFF")
            k.write(":DISP:ENAB ON")
            k.erros()
        finally:
            tr.close()
    log("RESULTADO: " + ("SEM ERROS" if not falhas else f"{falhas} problema(s)"), "ok" if not falhas else "error")
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()
