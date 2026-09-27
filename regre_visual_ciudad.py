#!/usr/bin/env python3
"""
regre_visual_ciudad.py
========================
Regresión visual/estructural de Ciudad Magazine (ciudad.com.ar). Motor
genérico compartido con TN, El Trece y El Doce en
regre_visual_motor.py — ver ese módulo para el detalle de qué hace
cada fix (tolerancia de píxeles, exclusión de ads, agrupación de
cascadas, confirmación visual, etc.).

Uso:
    python regre_visual_ciudad.py --modo desktop 719
    python regre_visual_ciudad.py --modo mobile 719
    python regre_visual_ciudad.py --modo desktop 719 --urls Homepage,Vivo
    python regre_visual_ciudad.py --modo desktop 719 --tolerancia 4 --sin-confirmacion-visual
"""

import os

import regre_visual_motor as motor

PRODUCTO = "Ciudad Magazine"
OUTPUT_DIR_BASE = os.path.join('reportes', 'ciudad')

BASE_URLS_MAP = {
    "https://www.ciudad.com.ar/": "Homepage",
    "https://www.ciudad.com.ar/cine-y-series/": "Cine y series",
    "https://www.ciudad.com.ar/lo-ultimo/": "Listado",
    "https://www.ciudad.com.ar/vivo/": "Vivo",
    # TIPOS DE NOTAS
    "https://www.ciudad.com.ar/espectaculos/2025/12/23/el-feroz-descargo-de-mauro-icardi-contra-nicolas-payarola-y-wanda-nara-felices-fiestas/": "Article",
    "https://www.ciudad.com.ar/videos/magazine/2025/12/23/empezar-el-dia-programa-del-231225-recibimos-a-brenda-di-aloy/?outputType=amp": "AMP",
    "https://www.ciudad.com.ar/videos/magazine/2025/12/23/empezar-el-dia-programa-del-231225-recibimos-a-brenda-di-aloy/": "Video",
    "https://www.ciudad.com.ar/espectaculos/2025/08/15/a-20-anos-de-la-noche-del-10-la-resurreccion-de-diego-maradona/": "Longform",
}


if __name__ == "__main__":
    motor.main(BASE_URLS_MAP, producto_nombre=PRODUCTO, output_dir_base=OUTPUT_DIR_BASE)
