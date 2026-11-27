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
    python regre_visual_ciudad.py --modo desktop 719 --ambiente dev
    python regre_visual_ciudad.py --modo mobile 719 --ambiente sbx
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


# URLs de los ambientes DEV y SBX (las mismas que usaba la regresión anterior
# en cada ambiente). En dev/sbx se compara el ambiente tal cual contra el
# mismo ambiente con ?d=VERSION.
URLS_POR_AMBIENTE = {
    "dev": {
        "https://artear-ciudad-dev.web.arc-cdn.net/": "Homepage",
        "https://artear-ciudad-dev.web.arc-cdn.net/lo-ultimo/": "Listado",
        "https://artear-ciudad-dev.web.arc-cdn.net/videos/actualidad/2025/10/29/video-horizontal/": "Videos",
        "https://artear-ciudad-dev.web.arc-cdn.net/vivo/": "Vivo",
        "https://artear-ciudad-dev.web.arc-cdn.net/cine-y-series/": "Cine y series",
        "https://artear-ciudad-dev.web.arc-cdn.net/los-mas-clickeados/": "Los más clickeados",
        "https://artear-ciudad-dev.web.arc-cdn.net/espectaculos/2025/03/17/tnarc-3455-b-ciudad-magazine/": "Article",
        "https://artear-ciudad-dev.web.arc-cdn.net/espectaculos/2025/03/17/tnarc-3455-b-ciudad-magazine/?outputType=amp": "AMP",
        "https://artear-ciudad-dev.web.arc-cdn.net/exclusivo/2025/08/07/a-20-anos-de-la-noche-del-10-la-resurreccion-de-diego-maradona/": "Longform c/fondo",
        "https://artear-ciudad-dev.web.arc-cdn.net/actualidad/2025/07/17/francos-ratifico-que-vetaran-los-proyectos-que-impulsan-los-gobernadores-y-profundizo-la-tension/": "Liveblog",
        "https://artear-ciudad-dev.web.arc-cdn.net/fotos/actualidad/2024/11/19/imagenes-horizontales-ciudad/": "Galería",
    },
    "sbx": {
        "https://artear-ciudad-sandbox.web.arc-cdn.net/": "Homepage",
        "https://artear-ciudad-sandbox.web.arc-cdn.net/lo-ultimo/": "Listado",
        "https://artear-ciudad-sandbox.web.arc-cdn.net/videos/actualidad/2025/10/29/video-horizontal/": "Videos",
        "https://artear-ciudad-sandbox.web.arc-cdn.net/vivo/": "Vivo",
        "https://artear-ciudad-sandbox.web.arc-cdn.net/cine-y-series/": "Cine y series",
        "https://artear-ciudad-sandbox.web.arc-cdn.net/los-mas-clickeados/": "Los más clickeados",
        "https://artear-ciudad-sandbox.web.arc-cdn.net/espectaculos/2025/03/17/tnarc-3455-b-ciudad-magazine/": "Article",
        "https://artear-ciudad-sandbox.web.arc-cdn.net/espectaculos/2025/03/17/tnarc-3455-b-ciudad-magazine/?outputType=amp": "AMP",
        "https://artear-ciudad-sandbox.web.arc-cdn.net/exclusivo/2025/08/07/a-20-anos-de-la-noche-del-10-la-resurreccion-de-diego-maradona/": "Longform c/fondo",
        "https://artear-ciudad-sandbox.web.arc-cdn.net/actualidad/2025/07/17/francos-ratifico-que-vetaran-los-proyectos-que-impulsan-los-gobernadores-y-profundizo-la-tension/": "Liveblog",
        "https://artear-ciudad-sandbox.web.arc-cdn.net/fotos/actualidad/2024/11/19/imagenes-horizontales-ciudad/": "Galería",
    },
}


if __name__ == "__main__":
    motor.main(BASE_URLS_MAP, producto_nombre=PRODUCTO, output_dir_base=OUTPUT_DIR_BASE,
               urls_por_ambiente=URLS_POR_AMBIENTE)
