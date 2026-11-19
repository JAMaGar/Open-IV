"""
Nomes de arquivo, pastas de destino e gravacao CSV no padrao da campanha
(01_Gestao/Padrao_Arquivos_e_Metadados.md):

    <amostra>_<pad>_<guia>-<etapa>_<parametro>_<AAAAMMDD-HHMMSS>.csv

Cabecalho com linhas '# chave: valor', separador ',', decimal '.', UTF-8.
Nunca sobrescreve: se o nome ja existir, acrescenta _2, _3...
"""
import json
import math
import os
import re
from datetime import datetime

PASTAS_GUIA = {
    "G03": "12_Substrato_Rserie", "G04": "20_IV", "G05": "21_Multinivel",
    "G06": "22_Taxa_Varredura", "G07": "23_Limiar_Volatil", "G08": "30_Ciclos",
    "G09": "31_Retencao", "G10": "32_Pulsos", "G11": "33_Sinapse",
    "G15": "60_Temperatura", "G16": "61_Luz", "G17": "62_Voc",
    "G18": "70_Estruturas_Teste",
}

CAMPOS_CABECALHO = ["amostra", "pad", "grupo", "guia_etapa", "sessao", "data_hora_inicio",
                    "operador", "instrumento", "programa_versao", "luz", "T_amb_C",
                    "UR_pct", "parametros", "observacao"]


def tag_v(v, prefixo="V"):
    """+8.0 -> 'Vp8p0'; -1.0 -> 'Vm1p0' (sinal p/m e virgula como p)."""
    s = "m" if v < 0 else "p"
    txt = f"{abs(v):.2f}".rstrip("0")
    if txt.endswith("."):
        txt += "0"
    return f"{prefixo}{s}{txt.replace('.', 'p')}"


def tag_num(x, sufixo=""):
    """0.5 -> '0p5' (sem sinal)."""
    txt = f"{x:g}".replace(".", "p").replace("-", "m")
    return txt + sufixo


def limpar(s):
    s = (s or "").strip()
    s = re.sub(r"[\\/:*?\"<>|\s]+", "-", s)
    return s.strip("-_")


def nome_arquivo(amostra, pad, guia_etapa, parametro, quando=None, ext=".csv"):
    quando = quando or datetime.now()
    partes = [limpar(amostra) or "AMOSTRA", limpar(pad) or "PAD", limpar(guia_etapa) or "G00-X"]
    if limpar(parametro):
        partes.append(limpar(parametro))
    partes.append(quando.strftime("%Y%m%d-%H%M%S"))
    return "_".join(partes) + ext


def pasta_destino(raiz, guia_etapa, amostra):
    """
    Se a raiz for a pasta da campanha (Caracterizacao_Eletrica_Definitiva) e a guia
    tiver pasta propria, grava em <raiz>/<pasta da tecnica>/dados/<amostra>/.
    Caso contrario, grava em <raiz>/<amostra>/.
    """
    raiz = raiz or os.path.join(os.path.expanduser("~"), "Documents", "Open-IV_dados")
    cod = (guia_etapa or "").split("-")[0].upper()
    am = limpar(amostra) or "AMOSTRA"
    if cod in PASTAS_GUIA and os.path.isdir(os.path.join(raiz, PASTAS_GUIA[cod])):
        return os.path.join(raiz, PASTAS_GUIA[cod], "dados", am)
    return os.path.join(raiz, am)


def caminho_livre(caminho):
    if not os.path.exists(caminho):
        return caminho
    base, ext = os.path.splitext(caminho)
    k = 2
    while os.path.exists(f"{base}_{k}{ext}"):
        k += 1
    return f"{base}_{k}{ext}"


def _fmt_val(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int,)):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v):
            return "nan"
        return f"{v:.9g}"
    try:
        import numpy as np
        if isinstance(v, np.generic):
            return _fmt_val(v.item())
    except Exception:
        pass
    return str(v)


def _fmt_cab(v):
    if isinstance(v, dict):
        return "; ".join(f"{k}={_fmt_cab(x)}" for k, x in v.items())
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, (list, tuple)):
        return ", ".join(_fmt_cab(x) for x in v)
    return str(v).replace("\n", " ")


def escrever_csv(caminho, cabecalho, colunas, linhas):
    """Grava o CSV; retorna o caminho efetivo (nunca sobrescreve)."""
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    caminho = caminho_livre(caminho)
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        for k in CAMPOS_CABECALHO:
            if k in cabecalho:
                f.write(f"# {k}: {_fmt_cab(cabecalho[k])}\n")
        for k, v in cabecalho.items():
            if k not in CAMPOS_CABECALHO:
                f.write(f"# {k}: {_fmt_cab(v)}\n")
        f.write(",".join(colunas) + "\n")
        for ln in linhas:
            f.write(",".join(_fmt_val(ln.get(c)) for c in colunas) + "\n")
    return caminho


# ============================================================ configuracao persistente
def pasta_config():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    p = os.path.join(base, "Open-IV")
    os.makedirs(p, exist_ok=True)
    return p


def carregar_config():
    try:
        with open(os.path.join(pasta_config(), "config.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def salvar_config(d):
    try:
        with open(os.path.join(pasta_config(), "config.json"), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
