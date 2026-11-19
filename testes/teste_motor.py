"""
Teste do motor de medidas com o instrumento simulado (sem interface grafica).
Uso:  python testes/teste_motor.py
Grava os arquivos em uma pasta temporaria e confere a temporizacao dos pulsos.
"""
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from open_iv.keithley import Keithley2400
from open_iv.simulador import SimTransporte
from open_iv.medidas import Contexto, Motor
from open_iv import arquivos as fa
from open_iv import VERSAO_COMPLETA

PASTA = tempfile.mkdtemp(prefix="openiv_teste_")
ARQS = []
FALHAS = []


def conectar(modelo, tempo_real=False, baud=57600):
    tr = SimTransporte(modelo, baud=baud, tempo_real=tempo_real)
    tr.open()
    k = Keithley2400()
    k.conectar(tr, baud)
    return k, tr


def gravar(arq):
    cab = {"amostra": "SIM", "pad": "1P1", "guia_etapa": arq.etapa,
           "programa_versao": VERSAO_COMPLETA, "parametros": arq.meta}
    for kk, v in arq.resumo.items():
        cab[f"resumo_{kk}"] = v
    nome = fa.nome_arquivo("SIM", "1P1", arq.etapa, arq.param)
    c = fa.escrever_csv(os.path.join(PASTA, nome), cab, arq.colunas, arq.linhas)
    ARQS.append((arq, c))


def checar(cond, msg):
    print(("  OK   " if cond else "  FALHA ") + msg)
    if not cond:
        FALHAS.append(msg)


def motor(k):
    ctx = Contexto(k, log=lambda m, t="info": None, ao_arquivo=gravar)
    return Motor(ctx), ctx


print("== 1. Temporizacao de pulsos (resistor, 9600 baud) ==")
k, tr = conectar("resistor", baud=9600)
m, ctx = motor(k)
T, s = m.calibrar_sobrecarga(nplc=0.01)
print(f"  T0 (passo sem atraso) {T*1e3:.3f} ms; sobrecarga {s*1e3:.3f} ms (simulado: 1,367 ms)")
checar(abs(T - 0.0013667) < 0.00005, "T0 medido com relogio de 1024 Hz em 200 passos")
res = m.teste_largura([0.002, 0.005, 0.01, 0.05, 0.1, 0.25], V=1.0, n=6)
for r in res:
    tol = max(0.5 * T * 1e3, 0.01 * r["w_nominal_ms"]) + 0.05
    checar(abs(r["w_calibrada_ms"] - r["w_nominal_ms"]) <= tol and abs(r["w_carimbo_media_ms"] - r["w_calibrada_ms"]) < 1.1,
           f"w {r['w_nominal_ms']:6.1f} ms -> calibrada {r['w_calibrada_ms']:.3f} ms ({r['regime']}, k={r['passos']}), "
           f"carimbos {r['w_carimbo_media_ms']:.2f} ms")

print("== 2. Laco I-V hardware (capacitor MIS simulado) ==")
k, tr = conectar("mis")
m, ctx = motor(k)
p = dict(vertices=[-5, 10, -5], passo=0.1, atraso=0.1, nplc=1, compliance=0.01, faixa_i="AUTO",
         medir_v=True, modo="hw", n_lacos=3, etapa="G04-E2", rotulo="L")
m.exp_iv(p)
lac = [a for a, c in ARQS if a.etapa == "G04-E2"]
checar(len(lac) == 3, f"3 arquivos de laco (tem {len(lac)})")
ba = lac[1].resumo["BA(+2V)"]
checar(ba > 1.5, f"B/A(+2 V) do L2 = {ba:.2f} (>1,5 esperado no modelo)")
per = lac[1].resumo["periodo_ponto_s"]
# medir V e I (2 funcoes) com autozero: 2 x 3 x NPLC/60 + atraso + sobrecarga
checar(abs(per - (0.1 + 2 * 3 / 60 + 0.0012)) < 0.003, f"periodo por ponto {per*1e3:.1f} ms")
print("  nomes:", [os.path.basename(c) for a, c in ARQS if a.etapa == "G04-E2"])

print("== 3. Serie de atrasos G06 (2 atrasos x 2 lacos, ordem sorteada) ==")
p.update(atrasos=[0.01, 0.1], aleatorio=True, n_lacos=2, etapa="G06")
m.exp_iv(p)
g6 = [os.path.basename(c) for a, c in ARQS if a.etapa == "G06"]
checar(len(g6) == 4 and any("R0p01_L2" in x for x in g6), f"arquivos G06: {g6}")

print("== 4. Pulsos G10 (amplitudes, leitura +1 V) ==")
pp = dict(modo="Amplitudes", amplitudes=[5, 7], w_fixo=0.01, n_pulsos=5, V_read=1.0, t_read=0.2,
          media_read=0.1, nplc_read=1, base=0.0, nplc_pulso=0.01, compliance=0.01, periodo=0,
          reset_ref=[0, -5, 0], etapa="G10-P1", aleatorio=False)
m.exp_pulsos(pp)
a = [a for a, c in ARQS if a.etapa == "G10-P1"][0]
w = np.array([l["w_calibrada_ms"] for l in a.linhas if l["n"] > 0])
wr = np.array([l["t_write_real_ms"] for l in a.linhas if l["n"] > 0])
checar(np.all(np.abs(w - 10) < 0.7) and np.all(np.abs(wr - w) < 1.0),
       f"larguras calibradas {w.min():.3f}-{w.max():.3f} ms, carimbos {wr.min():.2f}-{wr.max():.2f} ms (nominal 10 ms)")
I7 = [l["I_read_A"] for l in a.linhas if l["serie"] == "Vp7p0"]
checar(I7[-1] > I7[0], f"leitura sobe com pulsos de +7 V ({I7[0]:.2e} -> {I7[-1]:.2e} A)")
print("  atraso pulso->leitura (ms):", round(a.resumo["atraso_leitura_mediano_ms"], 1))

print("== 5. Sinapse LTP/LTD e PPF ==")
ps = dict(modo="LTP/LTD", n_pot=10, V_pot=7.0, n_dep=10, V_dep=-3.5, w=0.01, ciclos=2, V_read=1.0,
          t_read=0.1, media_read=0.05, nplc_read=1, compliance=0.01, etapa="G11-S1")
m.exp_sinapse(ps)
a = [a for a, c in ARQS if a.etapa == "G11-S1"][0]
checar(a.resumo["Gmax_Gmin"] > 1.2, f"Gmax/Gmin = {a.resumo['Gmax_Gmin']:.2f}")

print("== 6. Multinivel G05-M1 ==")
pm = dict(modo="Vmax", valores=[4, 6, 8], repeticoes=1, aleatorio=True, v_reset=[0, -5, 0], v_set=[0, 10, 0],
          passo=0.2, atraso=0.05, nplc=1, compliance=0.01, V_leitura=[1.0, 2.0], t_on=0.5, media=0.25,
          etapa="G05-M1")
m.exp_multinivel(pm)
a = [a for a, c in ARQS if a.etapa == "G05-M1"]
checar(len(a) == 2, f"arquivos serie + curvas ({len(a)})")

print("== 7. Ciclos DC e pulsados G08 ==")
pc = dict(modo="DC", N=4, v_set=[0, 10, 0], v_reset=[0, -5, 0], passo=0.2, atraso=0.02, nplc=0.1,
          V_read=1.0, t_read=0.2, media_read=0.1, nplc_read=1, compliance=0.01, bloco=2, etapa="G08-C1")
m.exp_ciclos(pc)
a = [os.path.basename(c) for a, c in ARQS if a.etapa == "G08-C1"]
checar(len(a) == 4, f"blocos B1/B2 + curvas: {a}")
pc.update(modo="Pulsado", Vp_set=7.0, Vp_reset=-4.0, w=0.02, etapa="G08-C2", N=5, bloco=100)
m.exp_ciclos(pc)
a = [a for a, c in ARQS if a.etapa == "G08-C2"][0]
checar(abs(a.linhas[0]["w_calibrada_ms"] - 20) < 0.7, f"pulso de ciclo: calibrada {a.linhas[0]['w_calibrada_ms']:.3f} ms, carimbos {a.linhas[0]['t_write_real_ms']:.2f} ms")

print("== 8. Retencao (tempo real, curta) ==")
k2, tr2 = conectar("mis", tempo_real=True)
m2, ctx2 = motor(k2)
pr = dict(preparo="varredura", prep_vertices=[0, 10, 0], prep_passo=0.5, prep_atraso=0.01, V_read=1.0,
          t_on=0.2, media=0.1, nplc=1, compliance=0.01, tempos=[1, 2, 5], entre="0V", etapa="G09-R2", param="LRS")
m2.exp_retencao(pr)
a = [a for a, c in ARQS if a.etapa == "G09-R2"][0]
ts = [round(l["t_s"], 2) for l in a.linhas]
checar(all(abs(x - y) < 0.15 for x, y in zip(ts, [1, 2, 5])), f"tempos das leituras apos a escrita: {ts}")

print("== 9. V_oc apos SET (G17) e I(t) a V fixo ==")
pt = dict(modo="Voc", dur_voc=1.0, intervalo=0.2, rapida_n=20, rapida_dt=0.005, nplc=0.1, compliance=0.01,
          limite_v=5, preparo="varredura", prep_vertices=[0, 10, 0], prep_passo=0.5, prep_atraso=0.01,
          etapa="G17", param="VOC_LRS")
m2.exp_transiente(pt)
a = [a for a, c in ARQS if a.etapa == "G17"][0]
checar(len(a.linhas) > 20, f"{len(a.linhas)} pontos de V_oc; atraso preparo->1a leitura "
       f"{a.resumo.get('atraso_preparo_para_1a_leitura_s', float('nan'))*1e3:.1f} ms")
pt = dict(modo="V", segmentos=[(1.0, 1.0), (0.0, 1.0)], intervalo=0.1, rapida_n=50, rapida_dt=0.002, nplc=0.01,
          compliance=0.01, etapa="G16-L1", param="IT")
m2.exp_transiente(pt)
a = [a for a, c in ARQS if a.etapa == "G16-L1"][0]
checar("Q_seg1_C" in a.resumo, f"carga integrada seg1 = {a.resumo.get('Q_seg1_C', float('nan')):.3e} C")

print("== 10. Celula solar J-V (reverso+direto) e diodo ==")
k3, tr3 = conectar("solar")
m3, ctx3 = motor(k3)
pj = dict(Vmin=-0.2, Vmax=0.8, passo=0.01, atraso=0.01, nplc=1, compliance=0.1, sentido="reverso+direto",
          area_cm2=0.1, Pin=100.0, luz="claro", etapa="SOL-JV")
m3.exp_jv(pj)
a = [a for a, c in ARQS if a.etapa == "SOL-JV"][0]
r = a.resumo
print(f"  Voc={r['rev1_Voc_V']:.4f} V Jsc={r['rev1_Jsc_mA_cm2']:.2f} mA/cm2 FF={r['rev1_FF']:.3f} "
      f"PCE={r['rev1_PCE_pct']:.2f} % Rs={r['rev1_Rs_ohm']:.1f} Rsh={r['rev1_Rsh_ohm']:.0f}")
checar(abs(r["rev1_Jsc_mA_cm2"] - 30) < 1.0, "Jsc ~ 30 mA/cm2 (modelo)")
tr3.dev.luz = False
pdd = dict(Vmin=-0.5, Vmax=0.7, passo=0.01, atraso=0.005, nplc=1, compliance=0.1, area_cm2=0.1, T=300,
           V1=0.5, V2=0.6, Vrr=0.5, etapa="SOL-DIO")
m3.exp_diodo(pdd)
a = [a for a, c in ARQS if a.etapa == "SOL-DIO"][0]
checar(abs(a.resumo["n"] - 1.6) < 0.2, f"n ajustado = {a.resumo['n']:.3f} (modelo 1,6)")
tr3.dev.luz = True
pe = dict(modo="MPPT", V0=0.4, dV=0.01, duracao=3, intervalo=0.05, nplc=1, compliance=0.1, area_cm2=0.1,
          Pin=100.0, etapa="SOL-MPPT")
m3.exp_estabilidade(pe)
a = [a for a, c in ARQS if a.etapa == "SOL-MPPT"][0]
checar(a.linhas[-1]["P_mW_cm2"] > a.linhas[0]["P_mW_cm2"] * 0.98, f"MPPT: P {a.linhas[0]['P_mW_cm2']:.2f} -> {a.linhas[-1]['P_mW_cm2']:.2f} mW/cm2")

print("== 10b. Diagnostico do atraso de fonte (resistor) ==")
k4, tr4 = conectar("resistor")
m4, ctx4 = motor(k4)
dg = m4.diag_atraso(V=1.0, atrasos_ms=(0, 1, 5, 20))
checar(dg[1]["T_alt_ms"] > 9 and abs(dg[3]["T_alt_ms"] - 21.37) < 0.2,
       "diagnostico revela o piso de atraso simulado: " + ", ".join(f"{d['atraso_ms']:g}->{d['T_alt_ms']:.2f}" for d in dg))

print("== 10c. Lista longa em blocos, erro do 2400 interrompe, trem p/ osciloscopio ==")
k5, tr5 = conectar("resistor", tempo_real=True)
checar(k5.max_lista_verificada == 300, f"sonda de lista na conexao: {k5.max_lista_verificada} de 300 pontos")
m5, ctx5 = motor(k5)
m5.iniciar()
k5.config_fonte_v(0.01, 0.01, 0.01, medir_v=False, autozero=False, faixa_v=2)
r5 = m5._lista([0.0, 1.0] * 400, 0.0)
checar(len(r5["I"]) == 800, "lista de 800 pontos enviada em comandos de 50 valores")
from open_iv.keithley import ErroInstrumento
avisos = []
k5.log = lambda msg, tag="info": avisos.append(msg)
tr5.erros.append('-363,"Input buffer overrun"')
k5.set(":SENS:CURR:NPLC", 0.02)
r5 = m5._lista([0.0] * 10, 0.0)
checar(len(r5["I"]) == 10 and any("Reenviando" in a for a in avisos) and not tr5.erros,
       "erro na fila: cache descartado, configuracao reenviada e preparo refeito antes do :READ?")
# cache dessincronizado (comando perdido sem erro): a conferencia por consulta detecta e corrige
tr5.s["sdel"] = 0.01
k5.set(":SENS:CURR:NPLC", 0.03)
avisos.clear()
r5 = m5._lista([0.0] * 10, 0.0)
checar(tr5.s["sdel"] == 0.0 and any(":SOUR:DEL" in a for a in avisos),
       "atraso de fonte diferente do cache: detectado por :SOUR:DEL? e reenviado")
# erro que persiste: a medida e interrompida (nunca segue com estado desconhecido)
k5.recuperar = False
tr5.erros.append('-363,"Input buffer overrun"')
k5.set(":SENS:CURR:NPLC", 0.02)
try:
    m5._lista([0.0] * 10, 0.0); parou = False
except ErroInstrumento as e:
    parou = "-363" in str(e)
checar(parou, "sem recuperacao, erro na fila interrompe a medida antes do :READ?")
k5.recuperar = True
k5.log = None
m5.finalizar()
w_, T_ = m5.trem_osciloscopio(V=1.0, largura=0.01, periodo=0.05, duracao=2.0)
checar(abs(w_ - 0.01) < 0.0014 and abs(T_ - 0.05) < 0.0014, f"trem: largura {w_*1e3:.3f} ms, periodo {T_*1e3:.3f} ms")

print("== 10d. Overrun do buffer de entrada (57600 baud, sem controle de fluxo) ==")


def enviar_listas(k, n_pontos, vezes, valor=0.0):
    """Reenvia uma lista 'vezes' vezes (cache descartado); devolve quantas ficaram incompletas."""
    falhas = 0
    for i in range(vezes):
        k._cache.pop("lista_VOLT", None)
        try:
            k._enviar_lista("VOLT", [valor * ((j + i) % 2) for j in range(n_pontos)])
        except ErroInstrumento:
            falhas += 1
        k.erros()
    return falhas


k6, tr6 = conectar("resistor")
k6.sincronismo = "pausa"                       # comportamento da 1.1.1
tr6.n_overrun = 0
f6 = enviar_listas(k6, 200, 10)
checar(tr6.n_overrun > 0 and f6 > 0, f"sem *OPC?: o simulador reproduz o erro ({tr6.n_overrun} overruns, "
                                     f"{f6} de 10 listas incompletas)")
k6.sincronismo = "opc"
tr6.n_overrun = 0
f6 = enviar_listas(k6, 200, 100)
checar(tr6.n_overrun == 0 and f6 == 0, f"com *OPC?: 100 listas de 200 pontos sem erro ({tr6.n_overrun} overruns)")
f6 = enviar_listas(k6, 2500, 20, valor=-0.987654)
checar(tr6.n_overrun == 0 and f6 == 0, "com *OPC?: 20 listas de 2500 pontos (valores longos) sem erro")
tr7 = SimTransporte("resistor", baud=57600, tempo_real=False, xonxoff=True)
tr7.open()
k7 = Keithley2400()
k7.conectar(tr7, 57600)
k7.sincronismo = "pausa"
f7 = enviar_listas(k7, 200, 20)
checar(tr7.n_overrun == 0 and f7 == 0, "XON/XOFF (reserva): 20 listas de 200 pontos sem *OPC? e sem erro")
m6, _ = motor(k6)
T0s = [m6.calibrar_sobrecarga(nplc=0.01)[0] for _ in range(10)]
checar(max(T0s) - min(T0s) < 2e-5 and not k6.erros(), f"Medir T0 10x: {min(T0s)*1e3:.3f}-{max(T0s)*1e3:.3f} ms, sem erro")
m6.iniciar()
k6.config_fonte_v(0.01, 0.01, 0.01, medir_v=False, autozero=False, faixa_v=2)
laco = [round(x, 4) for x in np.concatenate([np.arange(-1, 1, 0.01), np.arange(1, -1.0001, -0.01)])]
r6 = m6._lista(laco, 0.0)
checar(len(laco) == 401 and len(r6["I"]) == 401 and not k6.erros(), "laco -1 -> +1 -> -1 V, 401 pontos, em uma lista")
m6.finalizar()

print("== 11. Cabecalho de um arquivo ==")
c = [c for a, c in ARQS if a.etapa == "G10-P1"][0]
with open(c, encoding="utf-8") as f:
    for i, ln in enumerate(f):
        if i < 8 or ln.startswith("n,"):
            print("   ", ln.rstrip()[:150])
        if i > 14:
            break
print()
print(f"Arquivos gravados em {PASTA}: {len(ARQS)}")
print("RESULTADO:", "TODOS OS TESTES PASSARAM" if not FALHAS else f"{len(FALHAS)} FALHA(S)")
sys.exit(1 if FALHAS else 0)
