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
    python regre_visual_eldoce.py --modo desktop 719 --ambiente dev
    python regre_visual_eldoce.py --modo mobile 719 --ambiente sbx
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


# URLs de los ambientes DEV y SBX (las mismas que usaba la regresión anterior
# en cada ambiente). En dev/sbx se compara el ambiente tal cual contra el
# mismo ambiente con ?d=VERSION.
URLS_POR_AMBIENTE = {
    "dev": {
        "https://artear-eldoce-dev.web.arc-cdn.net/": "Homepage",
        "https://artear-eldoce-dev.web.arc-cdn.net/ultimas-noticias/": "Listado",
        "https://artear-eldoce-dev.web.arc-cdn.net/videos/": "Videos",
        "https://artear-eldoce-dev.web.arc-cdn.net/vivo/": "Vivo",
        "https://artear-eldoce-dev.web.arc-cdn.net/cuarteteando/": "Cuarteteando",
        "https://artear-eldoce-dev.web.arc-cdn.net/deportes/estadisticas/": "Estadisticas",
        "https://artear-eldoce-dev.web.arc-cdn.net/deportes/estadisticas/primera-division/": "Primera división",
        "https://artear-eldoce-dev.web.arc-cdn.net/deportes/": "Deportes",
        "https://artear-eldoce-dev.web.arc-cdn.net/horoscopo/": "Horoscopo",
        "https://artear-eldoce-dev.web.arc-cdn.net/horoscopo/aries/": "Horoscopo por signo",
        "https://artear-eldoce-dev.web.arc-cdn.net/actualidad/2025/10/17/magui-olave-y-euge-quevedo-mamas-y-artistas-un-desafio-de-amor-y-equilibrio/": "Article",
        "https://artear-eldoce-dev.web.arc-cdn.net/fotos/mundo/impresionante-manhattanhenge-nueva-york-atardecer_149182-4/": "Galería",
        "https://artear-eldoce-dev.web.arc-cdn.net/cuarteteando/2025/12/10/valentino-merlo-y-su-desafio-personal-entre-el-estudio-y-la-musica-me-quede-libre-por-faltas/": "Nota Cuarteteando",
        "https://artear-eldoce-dev.web.arc-cdn.net/actualidad/2025/10/17/magui-olave-y-euge-quevedo-mamas-y-artistas-un-desafio-de-amor-y-equilibrio/?outputType=amp": "AMP",
        "https://artear-eldoce-dev.web.arc-cdn.net/videos/actualidad/2025/07/22/preocupacion-entre-las-victimas-de-los-sanadores-egipcios-por-la-reaparicion-publica-del-lider/": "Video",
        "https://artear-eldoce-dev.web.arc-cdn.net/videos/cuarteteando/2024/08/05/ya-salio-fama-de-diabla-en-vivo-por-david-bisbal-la-konga-y-emanero/": "Video cuarteteando",
        "https://artear-eldoce-dev.web.arc-cdn.net/actualidad/2024/08/26/piedra-del-molino-una-cascada-oculta-dentro-de-una-caverna-en-las-sierras-de-cordoba/": "Longform c/fondo",
        "https://artear-eldoce-dev.web.arc-cdn.net/actualidad/2024/07/15/argentina-bicampeon-de-america-le-gano-la-final-a-colombia-y-se-consagro-en-estados-unidos/": "Liveblog",
    },
    "sbx": {
        "https://artear-eldoce-sandbox.web.arc-cdn.net/": "Homepage",
        "https://artear-eldoce-sandbox.web.arc-cdn.net/ultimas-noticias/": "Listado",
        "https://artear-eldoce-sandbox.web.arc-cdn.net/videos/": "Videos",
        "https://artear-eldoce-sandbox.web.arc-cdn.net/vivo/": "Vivo",
        "https://artear-eldoce-sandbox.web.arc-cdn.net/cuarteteando/": "Cuarteteando",
        "https://artear-eldoce-sandbox.web.arc-cdn.net/deportes/estadisticas/": "Estadisticas",
        "https://artear-eldoce-sandbox.web.arc-cdn.net/deportes/estadisticas/primera-division/": "Primera división",
        "https://artear-eldoce-sandbox.web.arc-cdn.net/deportes/": "Deportes",
        "https://artear-eldoce-sandbox.web.arc-cdn.net/horoscopo/": "Horoscopo",
        "https://artear-eldoce-sandbox.web.arc-cdn.net/horoscopo/aries/": "Horoscopo por signo",
        "https://artear-eldoce-sandbox.web.arc-cdn.net/actualidad/2025/10/17/magui-olave-y-euge-quevedo-mamas-y-artistas-un-desafio-de-amor-y-equilibrio/": "Article",
        "https://artear-eldoce-sandbox.web.arc-cdn.net/fotos/mundo/impresionante-manhattanhenge-nueva-york-atardecer_149182-4/": "Galería",
        "https://artear-eldoce-sandbox.web.arc-cdn.net/cuarteteando/2025/12/10/valentino-merlo-y-su-desafio-personal-entre-el-estudio-y-la-musica-me-quede-libre-por-faltas/": "Nota Cuarteteando",
        "https://artear-eldoce-sandbox.web.arc-cdn.net/actualidad/2025/10/17/magui-olave-y-euge-quevedo-mamas-y-artistas-un-desafio-de-amor-y-equilibrio/?outputType=amp": "AMP",
        "https://artear-eldoce-sandbox.web.arc-cdn.net/videos/actualidad/2025/07/22/preocupacion-entre-las-victimas-de-los-sanadores-egipcios-por-la-reaparicion-publica-del-lider/": "Video",
        "https://artear-eldoce-sandbox.web.arc-cdn.net/videos/cuarteteando/2024/08/05/ya-salio-fama-de-diabla-en-vivo-por-david-bisbal-la-konga-y-emanero/": "Video cuarteteando",
        "https://artear-eldoce-sandbox.web.arc-cdn.net/actualidad/2024/08/26/piedra-del-molino-una-cascada-oculta-dentro-de-una-caverna-en-las-sierras-de-cordoba/": "Longform c/fondo",
        "https://artear-eldoce-sandbox.web.arc-cdn.net/actualidad/2024/07/15/argentina-bicampeon-de-america-le-gano-la-final-a-colombia-y-se-consagro-en-estados-unidos/": "Liveblog",
    },
}


if __name__ == "__main__":
    motor.main(BASE_URLS_MAP, producto_nombre=PRODUCTO, output_dir_base=OUTPUT_DIR_BASE,
               urls_por_ambiente=URLS_POR_AMBIENTE)
