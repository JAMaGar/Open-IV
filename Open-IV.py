#!/usr/bin/env python3
"""
Open-IV - controle do Keithley 2400 SourceMeter (RS-232)
  - Capacitores MIS / efeito memoria (I-V, multinivel, pulsos, sinapse, ciclos, retencao, I(t), V_oc)
  - Celulas solares / diodos (J-V, diodo no escuro, estabilidade/MPPT)

Uso:
  python Open-IV.py                  (instrumento real)
  python Open-IV.py --simular mis    (simulador: capacitor MIS | solar | resistor)
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser(description="Open-IV - Keithley 2400")
    ap.add_argument("--simular", choices=["mis", "solar", "resistor"], default=None,
                    help="pre-seleciona o simulador na barra de conexao")
    a = ap.parse_args()
    from open_iv.gui.app import App
    App(simular=a.simular).mainloop()


if __name__ == "__main__":
    main()
