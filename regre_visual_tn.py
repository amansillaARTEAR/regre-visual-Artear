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
    "https://tn.com.ar/deportes/automovilismo/2025/11/07/el-posteo-que-williams-le-dedico-a-colapinto-despues-de-ser-confirmado-en-alpine-para-la-temporada-2026-de-f1/": "Article",
    "https://tn.com.ar/videos/videos/2026/04/26/asi-se-ve-una-tormenta-electrica-desde-las-alturas/": "Video",
    "https://tn.com.ar/economia/2025/11/09/vivir-a-credito-crece-el-endeudamiento-cotidiano-y-hasta-el-40-del-sueldo-se-destina-a-pagar-la-tarjeta/": "Longform c/fondo",
    "https://tn.com.ar/sociedad/2023/02/12/mapa-de-los-incendios-en-la-argentina-por-que-cada-verano-se-recrudece-el-fuego/": "Longform s/fondo",
    "https://tn.com.ar/deportes/futbol/2025/11/07/franco-colapinto-corre-la-primera-practica-y-la-clasificacion-sprint-del-gp-de-brasil/": "Liveblogging",
}


if __name__ == "__main__":
    motor.main(BASE_URLS_MAP, producto_nombre=PRODUCTO, output_dir_base=OUTPUT_DIR_BASE)
