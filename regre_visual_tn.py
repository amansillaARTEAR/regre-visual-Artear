#!/usr/bin/env python3
"""
regre_visual_tn.py
===================
Regresión visual/estructural de TN (tn.com.ar). Motor genérico
compartido con los demás productos (El Trece, El Doce, Ciudad Magazine)
en regre_visual_motor.py — ver ese módulo para el detalle de qué hace
cada fix.

Uso:
    python regre_visual_tn.py --modo desktop 719
    python regre_visual_tn.py --modo mobile 719
    python regre_visual_tn.py --modo desktop 719 --ambiente dev
    python regre_visual_tn.py --modo mobile 719 --ambiente sbx
    python regre_visual_tn.py --modo desktop 719 --urls Homepage,Listado,Juegos
    python regre_visual_tn.py --modo desktop 719 --tolerancia 4 --sin-confirmacion-visual
"""

import os

import regre_visual_motor as motor

PRODUCTO = "TN"
OUTPUT_DIR_BASE = os.path.join('reportes', 'tn')

BASE_URLS_MAP = {
    "https://tn.com.ar/": "Homepage",
    "https://tn.com.ar/ultimas-noticias/": "Listado",
    "https://tn.com.ar/videos/": "Videos",
    "https://tn.com.ar/envivo/24hs/": "Vivo",
    "https://tn.com.ar/clima/": "Clima",
    "https://tn.com.ar/economia/divisas": "Economia",
    "https://tn.com.ar/economia/divisas/dolar-oficial-hoy/": "Divisas",
    "https://tn.com.ar/podcasts/2025/05/14/soy-adoptada-una-identidad-dicha-con-orgullo/": "Podcast",
    "https://tn.com.ar/deportes/": "deportivo",
    "https://tn.com.ar/deportes/estadisticas/": "Estadisticas",
    "https://tn.com.ar/quinielas-loterias/": "Quinielas",
    "https://tn.com.ar/juegos/": "Juegos",
    "https://tn.com.ar/elecciones-2025/": "Elecciones",
    "https://tn.com.ar/internacional/": "Internacional",
    "https://tn.com.ar/anses/": "Anses",
    "https://tn.com.ar/feriados/": "Feriados",
    "https://tn.com.ar/deportes/automovilismo/2025/11/07/el-posteo-que-williams-le-dedico-a-colapinto-despues-de-ser-confirmado-en-alpine-para-la-temporada-2026-de-f1/": "Article",
    "https://tn.com.ar/videos/videos/2026/04/26/asi-se-ve-una-tormenta-electrica-desde-las-alturas/": "Video",
    "https://tn.com.ar/economia/2025/11/09/vivir-a-credito-crece-el-endeudamiento-cotidiano-y-hasta-el-40-del-sueldo-se-destina-a-pagar-la-tarjeta/": "Longform c/fondo",
    "https://tn.com.ar/sociedad/2023/02/12/mapa-de-los-incendios-en-la-argentina-por-que-cada-verano-se-recrudece-el-fuego/": "Longform s/fondo",
    "https://tn.com.ar/deportes/futbol/2025/11/07/franco-colapinto-corre-la-primera-practica-y-la-clasificacion-sprint-del-gp-de-brasil/": "Liveblogging",
}


# URLs de los ambientes DEV y SBX (las mismas que usaba la regresión anterior
# en cada ambiente). En dev/sbx se compara el ambiente tal cual contra el
# mismo ambiente con ?d=VERSION.
URLS_POR_AMBIENTE = {
    "dev": {
        "https://artear-tn-dev.cdn.arcpublishing.com/": "Homepage",
        "https://artear-tn-dev.cdn.arcpublishing.com/ultimas-noticias/": "Listado",
        "https://artear-tn-dev.cdn.arcpublishing.com/videos/": "Videos",
        "https://artear-tn-dev.cdn.arcpublishing.com/envivo/24hs/": "Vivo",
        "https://artear-tn-dev.cdn.arcpublishing.com/clima/": "Clima",
        "https://artear-tn-dev.cdn.arcpublishing.com/economia/divisas/dolar-oficial-hoy/": "Divisas",
        "https://artear-tn-dev.cdn.arcpublishing.com/podcasts/2025/05/14/soy-adoptada-una-identidad-dicha-con-orgullo/": "Podcast",
        "https://artear-tn-dev.cdn.arcpublishing.com/juegos/": "Juegos",
        "https://artear-tn-dev.cdn.arcpublishing.com/elecciones-2025/": "Elecciones",
        "https://artear-tn-dev.cdn.arcpublishing.com/internacional/2024/12/09/los-rebeldes-sirios-apuran-la-transicion-para-evitar-conflictos-internos-y-la-irrupcion-del-estado-islamico/": "Article",
        "https://artear-tn-dev.cdn.arcpublishing.com/videos/deportes/futbol/2025/11/10/preocupacion-en-river-maxi-meza-se-lesiono-en-el-superclasico-y-salio-de-la-cancha-llorando/": "Video",
        "https://artear-tn-dev.cdn.arcpublishing.com/videos/autos/clasicos/2024/05/09/la-inedita-foto-del-nuevo-suv-con-estilo-coupe-que-este-ano-llegara-a-la-argentina/": "Video Dark",
        "https://artear-tn-dev.cdn.arcpublishing.com/policiales/2025/05/13/estafadores-de-america-asi-opera-la-banda-que-ofrece-prestamos-millonarios-con-el-cuento-de-la-caja-fuerte/": "Longform c/fondo",
        "https://artear-tn-dev.cdn.arcpublishing.com/politica/2024/12/09/el-gobierno-salio-al-cruce-de-kicillof-tras-el-anuncio-de-que-quiere-quedarse-con-aerolineas-argentinas/?outputType=amp": "AMP",
        "https://artear-tn-dev.cdn.arcpublishing.com/deportes/2025/01/30/se-avecina-un-temporal-que-pondra-a-prueba-a-varias-regiones-del-pais/": "Longform s/fondo",
        "https://artear-tn-dev.cdn.arcpublishing.com/deportes/futbol/2025/11/13/inglaterra-vs-serbia-en-vivo-por-la-fase-de-grupos-de-las-eliminatorias-uefa-hora-donde-ver-y-formaciones/": "Liveblogging",
    },
    "sbx": {
        "https://artear-tn-sandbox.cdn.arcpublishing.com/homepage-dynamic-4141/": "Portada",
        "https://artear-tn-sandbox.cdn.arcpublishing.com/": "Homepage",
        "https://artear-tn-sandbox.cdn.arcpublishing.com/ultimas-noticias/": "Listado",
        "https://artear-tn-sandbox.cdn.arcpublishing.com/videos/": "Videos",
        "https://artear-tn-sandbox.cdn.arcpublishing.com/envivo/24hs/": "Vivo",
        "https://artear-tn-sandbox.cdn.arcpublishing.com/clima/": "Clima",
        "https://artear-tn-sandbox.cdn.arcpublishing.com/economia/divisas/dolar-oficial-hoy/": "Divisas",
        "https://artear-tn-sandbox.cdn.arcpublishing.com/podcasts/2025/05/14/soy-adoptada-una-identidad-dicha-con-orgullo/": "Podcast",
        "https://artear-tn-sandbox.cdn.arcpublishing.com/juegos/": "Juegos",
        "https://artear-tn-sandbox.cdn.arcpublishing.com/elecciones-2025/": "Elecciones",
        "https://artear-tn-sandbox.cdn.arcpublishing.com/internacional/2024/12/09/los-rebeldes-sirios-apuran-la-transicion-para-evitar-conflictos-internos-y-la-irrupcion-del-estado-islamico/": "Article",
        "https://artear-tn-sandbox.cdn.arcpublishing.com/videos/deportes/futbol/2025/11/10/preocupacion-en-river-maxi-meza-se-lesiono-en-el-superclasico-y-salio-de-la-cancha-llorando/": "Video",
        "https://artear-tn-sandbox.cdn.arcpublishing.com/videos/autos/clasicos/2024/05/09/la-inedita-foto-del-nuevo-suv-con-estilo-coupe-que-este-ano-llegara-a-la-argentina/": "Video Dark",
        "https://artear-tn-sandbox.cdn.arcpublishing.com/policiales/2025/05/13/estafadores-de-america-asi-opera-la-banda-que-ofrece-prestamos-millonarios-con-el-cuento-de-la-caja-fuerte/": "Longform c/fondo",
        "https://artear-tn-sandbox.cdn.arcpublishing.com/politica/2024/12/09/el-gobierno-salio-al-cruce-de-kicillof-tras-el-anuncio-de-que-quiere-quedarse-con-aerolineas-argentinas/?outputType=amp": "AMP",
        "https://artear-tn-sandbox.cdn.arcpublishing.com/deportes/2025/01/30/se-avecina-un-temporal-que-pondra-a-prueba-a-varias-regiones-del-pais/": "Longform s/fondo",
        "https://artear-tn-sandbox.cdn.arcpublishing.com/deportes/futbol/2025/11/13/inglaterra-vs-serbia-en-vivo-por-la-fase-de-grupos-de-las-eliminatorias-uefa-hora-donde-ver-y-formaciones/": "Liveblogging",
    },
}


if __name__ == "__main__":
    motor.main(BASE_URLS_MAP, producto_nombre=PRODUCTO, output_dir_base=OUTPUT_DIR_BASE,
               urls_por_ambiente=URLS_POR_AMBIENTE)
