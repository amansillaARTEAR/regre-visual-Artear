#!/usr/bin/env python3
"""
regre_visual_eldoce.py
========================
Regresión visual/estructural de El Doce (eldoce.tv). Motor genérico
compartido con TN, El Trece y Ciudad Magazine en regre_visual_motor.py
— ver ese módulo para el detalle de qué hace cada fix (tolerancia de
píxeles, exclusión de ads, agrupación de cascadas, confirmación
visual, etc.).

Uso:
    python regre_visual_eldoce.py --modo desktop 719
    python regre_visual_eldoce.py --modo mobile 719
    python regre_visual_eldoce.py --modo desktop 719 --urls Homepage,Vivo
    python regre_visual_eldoce.py --modo desktop 719 --tolerancia 4 --sin-confirmacion-visual
"""

import os

import regre_visual_motor as motor

PRODUCTO = "El Doce"
OUTPUT_DIR_BASE = os.path.join('reportes', 'eldoce')

BASE_URLS_MAP = {
    "https://eldoce.tv/": "Homepage",
    "https://eldoce.tv/cuarteteando/": "Cuartetenado",
    "https://eldoce.tv/videos/": "Videos",
    "https://eldoce.tv/vivo": "Vivo",
    "https://eldoce.tv/cuarteteando/agenda/": "Agenda",
    "https://eldoce.tv/deportes/": "Deportes",
    "https://eldoce.tv/deportes/estadisticas/": "Estadísticas deportes",
    "https://eldoce.tv/deportes/estadisticas/primera-division/": "Torneo deportes",
    "https://eldoce.tv/horoscopo/": "Horóscopo",
    "https://eldoce.tv/horoscopo/aries/": "Horóscopo signo",
    # TIPOS DE NOTAS
    "https://eldoce.tv/show/2025/12/11/operativo-para-shakira-en-el-kempes-que-pasara-con-los-naranjitas-a-que-hora-abren-las-puertas-y-ubicaciones/": "Article",
    "https://eldoce.tv/show/2025/12/11/operativo-para-shakira-en-el-kempes-que-pasara-con-los-naranjitas-a-que-hora-abren-las-puertas-y-ubicaciones/?outputType=amp": "AMP",
    "https://eldoce.tv/videos/show/2025/12/14/aca-en-cordoba-el-inicio-feroz-de-shakira-en-el-kempes/": "Video",
    "https://eldoce.tv/cuarteteando/2025/12/12/los-herrera-emocionaron-a-sus-fans-con-una-version-acustica-de-la-primera-cancion-que-aprendio-fran-en-la-guit/": "Cuarteteando",
    "https://eldoce.tv/videos/cuarteteando/2025/12/10/dale-q-va-lanzo-un-ft-junto-a-jolgorio/": "Video cuarteteando",
    "https://eldoce.tv/tendencias/2024/08/22/piedra-del-molino-una-cascada-oculta-dentro-de-una-caverna-de-valor-incalculable-en-las-sierras-de-cordoba/": "Longform c/fondo",
    "https://eldoce.tv/actualidad/2024/09/11/melisa-la-maestra-que-viaja-80-kilometros-para-dar-clases-a-cinco-alumnos-de-agua-hedionda/": "Longform s/fondo",
    "https://eldoce.tv/actualidad/2024/07/15/busqueda-de-loan-en-vivo-se-conocio-una-foto-inedita-del-almuerzo-previo-a-la-desaparicion/": "Liveblogging",
    "https://eldoce.tv/fotos/show/2025/12/14/furor-por-shakira-en-su-primer-show-en-el-kempes/": "Galería",
    # Recipe => no está en prod
}


if __name__ == "__main__":
    motor.main(BASE_URLS_MAP, producto_nombre=PRODUCTO, output_dir_base=OUTPUT_DIR_BASE)
