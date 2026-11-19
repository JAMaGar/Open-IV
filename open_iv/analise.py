"""
Analises rapidas exibidas na tela e gravadas no cabecalho do arquivo.

Sao indicadores para acompanhar a medida; a analise definitiva deve ser feita
nos scripts de 90_Analise a partir dos dados brutos.
"""
import math

import numpy as np

K_B = 1.380649e-23
Q_E = 1.602176634e-19


def _arr(x):
    return np.asarray(x, dtype=float)


# ============================================================ I-V / memoria
def passagens(V, I, V0):
    """Correntes interpoladas em cada passagem do caminho V(t) por V0 (ordem temporal)."""
    V, I = _arr(V), _arr(I)
    out = []
    s = np.sign(V - V0)
    k = 0
    n = len(V)
    while k < n:
        if s[k] == 0:
            j = k
            while j + 1 < n and s[j + 1] == 0:
                j += 1
            out.append(float(np.nanmean(I[k:j + 1])))
            k = j + 1
            continue
        if k + 1 < n and s[k] * s[k + 1] < 0:
            f = (V0 - V[k]) / (V[k + 1] - V[k])
            out.append(float(I[k] + f * (I[k + 1] - I[k])))
        k += 1
    return out


def razao_ba(V, I, V0):
    """Janela B/A = |I_volta| / |I_ida| em V0 (1a e 2a passagens)."""
    p = passagens(V, I, V0)
    if len(p) < 2 or p[0] == 0 or not np.isfinite(p[0]):
        return float("nan")
    return abs(p[1]) / abs(p[0])


def retificacao(V, I, Vr=2.0):
    """RR = |I(-Vr)| / |I(+Vr)| (primeiras passagens)."""
    pn = passagens(V, I, -abs(Vr))
    pp = passagens(V, I, abs(Vr))
    if not pn or not pp or pp[0] == 0:
        return float("nan")
    return abs(pn[0]) / abs(pp[0])


def _dlog(V, I):
    V, I = _arr(V), np.abs(_arr(I))
    with np.errstate(divide="ignore", invalid="ignore"):
        L = np.log10(np.where(I > 0, I, np.nan))
        dV = np.diff(V)
        dL = np.diff(L)
        d = np.where(dV != 0, dL / dV, np.nan)
    Vm = 0.5 * (V[1:] + V[:-1])
    return Vm, dV, d


def v_set(V, I, v_min=0.3):
    """V do maximo de d(log|I|)/dV no ramo de V crescente com V > v_min."""
    Vm, dV, d = _dlog(V, I)
    m = (dV > 0) & (Vm > v_min) & np.isfinite(d)
    if not np.any(m):
        return float("nan")
    idx = np.nanargmax(np.where(m, d, -np.inf))
    return float(Vm[idx])


def v_reset(V, I, v_max=-0.3):
    """Estimativa: V onde |I| mais cai enquanto V fica mais negativo (ramo -V)."""
    Vm, dV, d = _dlog(V, I)
    # indo para V mais negativo (dV < 0): queda de |I| = d log|I|/dV > 0
    m = (dV < 0) & (Vm < v_max) & np.isfinite(d)
    if not np.any(m):
        return float("nan")
    dd = np.where(m, d, -np.inf)
    idx = int(np.nanargmax(dd))
    if dd[idx] <= 0:
        return float("nan")
    return float(Vm[idx])


def taxa_real(V, t):
    """Taxa de varredura real (V/s): mediana de |dV/dt| nos passos com dV != 0."""
    V, t = _arr(V), _arr(t)
    if len(V) < 3:
        return float("nan")
    dV, dt = np.diff(V), np.diff(t)
    m = (np.abs(dV) > 1e-9) & (dt > 0)
    if not np.any(m):
        return float("nan")
    return float(np.median(np.abs(dV[m] / dt[m])))


def periodo_real(t):
    t = _arr(t)
    if len(t) < 2:
        return float("nan")
    return float(np.median(np.diff(t)))


def fechamento(I):
    """|I_ultimo - I_primeiro| / |I_primeiro| (controle de qualidade do laco)."""
    I = _arr(I)
    if len(I) < 2 or I[0] == 0:
        return float("nan")
    return abs(I[-1] - I[0]) / abs(I[0])


def v_compliance(V, comp):
    comp = np.asarray(comp, dtype=bool)
    if not np.any(comp):
        return None
    return float(_arr(V)[np.argmax(comp)])


def resumo_laco(V, I, t, comp, V_ba=(0.5, 1.0, 2.0, 3.0, 4.0, -1.0), Vrr=2.0):
    r = {}
    for v0 in V_ba:
        r[f"BA({v0:+g}V)"] = razao_ba(V, I, v0)
    r[f"RR({Vrr:g}V)"] = retificacao(V, I, Vrr)
    r["V_set_V"] = v_set(V, I)
    r["V_reset_V"] = v_reset(V, I)
    r["taxa_real_V_s"] = taxa_real(V, t)
    r["periodo_ponto_s"] = periodo_real(t)
    r["fechamento"] = fechamento(I)
    vc = v_compliance(V, comp)
    r["compliance_em_V"] = vc if vc is not None else "nao"
    return r


def inclinacao_loglog(t, I):
    """Inclinacao d log|I| / d log t (taxa de decaimento na retencao)."""
    t, I = _arr(t), np.abs(_arr(I))
    m = (t > 0) & (I > 0) & np.isfinite(I)
    if np.sum(m) < 3:
        return float("nan")
    p = np.polyfit(np.log10(t[m]), np.log10(I[m]), 1)
    return float(p[0])


# ============================================================ celulas solares / diodos
def vt(T=300.0):
    return K_B * T / Q_E


def parametros_solar(V, I, area_cm2=1.0, Pin_mW_cm2=100.0):
    """
    Parametros de uma curva J-V sob iluminacao (convencao da SMU: a corrente
    gerada e negativa no 4o quadrante). Retorna dict com Voc, Isc, Jsc, Vmp,
    Jmp, Pmax, FF, PCE, Rs e Rsh (por inclinacao local).
    """
    V, I = _arr(V), _arr(I)
    o = np.argsort(V)
    V, I = V[o], I[o]
    r = {k: float("nan") for k in ("Voc_V", "Isc_A", "Jsc_mA_cm2", "Vmp_V", "Imp_A",
                                    "Jmp_mA_cm2", "Pmax_W", "FF", "PCE_pct", "Rs_ohm",
                                    "Rsh_ohm", "Rs_ohm_cm2", "Rsh_ohm_cm2")}
    if len(V) < 4:
        return r
    if V.min() <= 0 <= V.max():
        Isc = -float(np.interp(0.0, V, I))
        r["Isc_A"] = Isc
        r["Jsc_mA_cm2"] = Isc / area_cm2 * 1e3
    # Voc: primeira troca de sinal de I (de negativo para positivo) com V crescente
    k = np.where((I[:-1] <= 0) & (I[1:] > 0))[0]
    if len(k):
        k = k[0]
        Voc = V[k] - I[k] * (V[k + 1] - V[k]) / (I[k + 1] - I[k])
        r["Voc_V"] = float(Voc)
    Voc, Isc = r["Voc_V"], r["Isc_A"]
    if np.isfinite(Voc) and np.isfinite(Isc) and Voc > 0 and Isc > 0:
        Vf = np.linspace(0, Voc, 2001)
        If = np.interp(Vf, V, I)
        P = -Vf * If
        j = int(np.argmax(P))
        r["Vmp_V"], r["Imp_A"], r["Pmax_W"] = float(Vf[j]), float(If[j]), float(P[j])
        r["Jmp_mA_cm2"] = -float(If[j]) / area_cm2 * 1e3
        r["FF"] = float(P[j] / (Voc * Isc))
        Pin = Pin_mW_cm2 * 1e-3 * area_cm2
        r["PCE_pct"] = float(P[j] / Pin * 100) if Pin > 0 else float("nan")
        # Rs: inclinacao dV/dI perto de Voc; Rsh: perto de V = 0
        # Rs: inclinacao dV/dI em Voc (inclui a resistencia dinamica do diodo:
        # e um limite superior de Rs). Rsh: inclinacao em V = 0 (janela de 15 % de Voc).
        jv = np.where(np.abs(V - Voc) <= max(0.02, 0.03 * Voc))[0]
        if len(jv) < 3:
            jv = np.argsort(np.abs(V - Voc))[:3]
        if len(np.unique(I[jv])) > 1:
            r["Rs_ohm"] = abs(float(np.polyfit(I[jv], V[jv], 1)[0]))
        j0 = np.where(np.abs(V) <= max(0.05, 0.15 * Voc))[0]
        if len(j0) < 3:
            j0 = np.argsort(np.abs(V))[:3]
        if len(np.unique(I[j0])) > 1:
            s = np.polyfit(V[j0], I[j0], 1)[0]
            r["Rsh_ohm"] = abs(1.0 / s) if s != 0 else float("inf")
        r["Rs_ohm_cm2"] = r["Rs_ohm"] * area_cm2
        r["Rsh_ohm_cm2"] = r["Rsh_ohm"] * area_cm2
    return r


def indice_histerese(pce_rev, pce_fwd):
    if not (np.isfinite(pce_rev) and np.isfinite(pce_fwd)) or pce_rev == 0:
        return float("nan")
    return (pce_rev - pce_fwd) / pce_rev


def ajuste_diodo(V, I, V1, V2, T=300.0):
    """Ajuste ln I = ln I0 + V/(n Vt) entre V1 e V2 (direto). Retorna n, I0, R2."""
    V, I = _arr(V), _arr(I)
    a, b = min(V1, V2), max(V1, V2)
    m = (V >= a) & (V <= b) & (I > 0)
    if np.sum(m) < 3:
        return {"n": float("nan"), "I0_A": float("nan"), "R2": float("nan"), "pontos": int(np.sum(m))}
    x, y = V[m], np.log(I[m])
    p = np.polyfit(x, y, 1)
    yf = np.polyval(p, x)
    ss = np.sum((y - y.mean()) ** 2)
    r2 = 1 - np.sum((y - yf) ** 2) / ss if ss > 0 else float("nan")
    n = 1.0 / (p[0] * vt(T)) if p[0] > 0 else float("nan")
    return {"n": float(n), "I0_A": float(math.exp(p[1])), "R2": float(r2), "pontos": int(np.sum(m))}


def n_local(V, I, T=300.0):
    """Fator de idealidade local n(V) = (1/Vt) dV/d ln I (ramo direto, I > 0)."""
    V, I = _arr(V), _arr(I)
    o = np.argsort(V)
    V, I = V[o], I[o]
    m = I > 0
    V, I = V[m], I[m]
    if len(V) < 3:
        return np.array([]), np.array([])
    lnI = np.log(I)
    d = np.gradient(lnI, V)
    with np.errstate(divide="ignore", invalid="ignore"):
        n = np.where(d > 0, 1.0 / (d * vt(T)), np.nan)
    return V, n


def razao_retificacao_diodo(V, I, Vr):
    """|I(+Vr)| / |I(-Vr)| (diodo: direto sobre reverso)."""
    V, I = _arr(V), _arr(I)
    o = np.argsort(V)
    V, I = V[o], I[o]
    if not (V.min() <= -abs(Vr) and V.max() >= abs(Vr)):
        return float("nan")
    ip = np.interp(abs(Vr), V, I)
    ineg = np.interp(-abs(Vr), V, I)
    return abs(ip) / abs(ineg) if ineg != 0 else float("nan")
