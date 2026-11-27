#!/usr/bin/env python3
"""
regre_visual_eltrece.py
========================
Regresión visual/estructural de El Trece (eltrecetv.com.ar). Motor
genérico compartido con TN, El Doce y Ciudad Magazine en
regre_visual_motor.py — ver ese módulo para el detalle de qué hace
cada fix (tolerancia de píxeles, exclusión de ads, agrupación de
cascadas, confirmación visual, etc.).

Uso:
    python regre_visual_eltrece.py --modo desktop 719
    python regre_visual_eltrece.py --modo mobile 719
    python regre_visual_eltrece.py --modo desktop 719 --ambiente dev
    python regre_visual_eltrece.py --modo mobile 719 --ambiente sbx
    python regre_visual_eltrece.py --modo desktop 719 --urls Homepage,Listado
    python regre_visual_eltrece.py --modo desktop 719 --tolerancia 4 --sin-confirmacion-visual
"""

import os

import regre_visual_motor as motor

PRODUCTO = "El Trece"
OUTPUT_DIR_BASE = os.path.join('reportes', 'eltrece')

BASE_URLS_MAP = {
    "https://www.eltrecetv.com.ar/": "Homepage",
    "https://www.eltrecetv.com.ar/ultimas-noticias/": "Listado",
    "https://www.eltrecetv.com.ar/videos/": "Videos",
    "https://www.eltrecetv.com.ar/vivo/": "Vivo",
    "https://www.eltrecetv.com.ar/programas/": "Programas",
    "https://www.eltrecetv.com.ar/programas/entretenimiento/": "ProgramasSeccion",
    "https://www.eltrecetv.com.ar/buenos-chicos/": "PortadaDeUnPrograma",
    "https://www.eltrecetv.com.ar/capitulos/": "Capitulos",
    "https://www.eltrecetv.com.ar/capitulos/ficcion/": "CapitulosSeccion",
    "https://www.eltrecetv.com.ar/convocatorias/": "Convocatorias",
    "https://www.eltrecetv.com.ar/shorts/": "Shorts",
    # TIPOS DE NOTAS
    "https://www.eltrecetv.com.ar/arriba-argentinos/2025/04/23/miles-de-fieles-ya-le-dan-el-ultimo-adios-al-papa-francisco-en-la-basilica-de-san-pedro/": "Article",
    "https://www.eltrecetv.com.ar/arriba-argentinos/2025/04/23/miles-de-fieles-ya-le-dan-el-ultimo-adios-al-papa-francisco-en-la-basilica-de-san-pedro/?outputType=amp": "AMP",
    "https://www.eltrecetv.com.ar/videos/arriba-argentinos/2025/07/02/otra-familia-intoxicada-con-monoxido-de-carbono-seis-internados-tras-ser-rescatados-inconscientes-en-ciudad-oculta/": "Video",
    "https://www.eltrecetv.com.ar/periodismo-para-todos/2023/11/30/gladys-florimonte-con-su-humor-inigualable-a-cargo-del-ultimo-detras-de-escena-de-la-casa-del-terror/": "Longform c/fondo",
    "https://www.eltrecetv.com.ar/telenoche/2024/05/28/maximo-thomsen-en-telenoche-en-vivo-la-segunda-parte-de-la-entrevista/": "Liveblogging",
    "https://www.eltrecetv.com.ar/la-1-5-18/historia/": "Historia",
    # CUCCINARE
    "https://www.eltrecetv.com.ar/cucinare/": "Portada Cucinare",
    "https://www.eltrecetv.com.ar/cucinare/capitulos/temporada-2025/navidad-viene-con-regalo[…]-suman-a-las-cocinas-de-cucinare-video-estreno-del-111225/": "Cuccinare Temporada",
    "https://www.eltrecetv.com.ar/cucinare/noticias/": "Listado Cuccinare",
    "https://www.eltrecetv.com.ar/cucinare/recetas/": "Portada Recetas Cuccinare",
    "https://www.eltrecetv.com.ar/cucinare/capitulos/": "Capitulos Cuccinare",
    "https://www.eltrecetv.com.ar/cucinare/recetas/?q=Pastel+de+bondiola": "Busqueda por palabra clave Cuccinare",
    "https://www.eltrecetv.com.ar/cucinare/recetas/?espanola=true&pescados-y-mariscos=true&frituras=true": "Busqueda por filtro Cuccinare",
    "https://www.eltrecetv.com.ar/tags/cucinare/arandanos/": "Tags Cuccinare",
    "https://www.eltrecetv.com.ar/cucinare/receta/solomillo-de-cerdo-con-chutney-de-peras-y-pure-de-batata-con-salsa-toffee/": "Recipe Cuccinare",
}


# URLs de los ambientes DEV y SBX (las mismas que usaba la regresión anterior
# en cada ambiente). En dev/sbx se compara el ambiente tal cual contra el
# mismo ambiente con ?d=VERSION.
URLS_POR_AMBIENTE = {
    "dev": {
        "https://artear-eltrece-dev.cdn.arcpublishing.com/": "Homepage",
        "https://artear-eltrece-dev.cdn.arcpublishing.com/ultimas-noticias/": "Listado",
        "https://artear-eltrece-dev.cdn.arcpublishing.com/virales/": "Portada",
        "https://artear-eltrece-dev.cdn.arcpublishing.com/videos/": "Videos",
        "https://artear-eltrece-dev.cdn.arcpublishing.com/vivo/": "Vivo",
        "https://artear-eltrece-dev.cdn.arcpublishing.com/cucinare/": "Cucinare",
        "https://artear-eltrece-dev.cdn.arcpublishing.com/programas/": "Programas",
        "https://artear-eltrece-dev.cdn.arcpublishing.com/programas/entretenimiento/": "Programa sección",
        "https://artear-eltrece-dev.cdn.arcpublishing.com/ahora-caigo/": "Programa",
        "https://artear-eltrece-dev.cdn.arcpublishing.com/capitulos/": "Capitulos",
        "https://artear-eltrece-dev.cdn.arcpublishing.com/capitulos/retrotrece/": "Capitulo sección",
        "https://artear-eltrece-dev.cdn.arcpublishing.com/convocatorias/": "Convocatorias",
        "https://artear-eltrece-dev.cdn.arcpublishing.com/shorts/": "Shorts",
        "https://artear-eltrece-dev.cdn.arcpublishing.com/virales/2025/02/17/quiso-mandarle-un-mensaje-a-un-amigo-se-lo-envio-al-peluquero-y-la-respuesta-se-volvio-viral/": "Article",
        "https://artear-eltrece-dev.cdn.arcpublishing.com/virales/2025/01/27/invito-a-su-mama-al-boliche-en-la-costa-y-se-llevo-una-tremenda-sorpresa/?outputType=amp": "AMP",
        "https://artear-eltrece-dev.cdn.arcpublishing.com/videos/otro-dia-perdido/2025/12/11/kevin-johansen-y-liniers-en-otro-dia-perdido/": "Video",
        "https://artear-eltrece-dev.cdn.arcpublishing.com/noticias-y-actualidad/2024/11/11/guillermo-francella-lamento-en-la-divina-noche-de-dante-la-crispacion-por-la-grieta/": "Longform c/fondo",
        "https://artear-eltrece-dev.cdn.arcpublishing.com/cucinare/2025/10/20/liveblogging-los-cinco-datos-mas-impactantes-sobre-las-joyas-robadas-en-el-museo-del-louvre-clone/": "Liveblog",
        "https://artear-eltrece-dev.cdn.arcpublishing.com/la-1-518/historia/": "Historia",
    },
    "sbx": {
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/": "Homepage",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/ultimas-noticias/": "Listado",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/virales/": "Portada",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/videos/": "Videos",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/vivo/": "Vivo",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/programas/": "Programas",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/programas/entretenimiento/": "Programa sección",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/ahora-caigo/": "Programa",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/capitulos/": "Capitulos",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/capitulos/retrotrece/": "Capitulo sección",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/convocatorias/": "Convocatorias",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/shorts/": "Shorts",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/virales/2025/02/17/quiso-mandarle-un-mensaje-a-un-amigo-se-lo-envio-al-peluquero-y-la-respuesta-se-volvio-viral/": "Article",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/virales/2025/01/27/invito-a-su-mama-al-boliche-en-la-costa-y-se-llevo-una-tremenda-sorpresa/?outputType=amp": "AMP",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/videos/otro-dia-perdido/2025/12/11/kevin-johansen-y-liniers-en-otro-dia-perdido/": "Video",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/noticias-y-actualidad/2024/11/11/guillermo-francella-lamento-en-la-divina-noche-de-dante-la-crispacion-por-la-grieta/": "Longform c/fondo",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/cucinare/2025/10/20/liveblogging-los-cinco-datos-mas-impactantes-sobre-las-joyas-robadas-en-el-museo-del-louvre-clone/": "Liveblog",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/la-1-518/historia/": "Historia",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/cucinare/": "Portada Cucinare",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/cucinare/capitulos/temporada-2025/navidad-viene-con-regalo[…]-suman-a-las-cocinas-de-cucinare-video-estreno-del-111225/": "Cuccinare Temporada",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/cucinare/noticias/": "Listado Cuccinare",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/cucinare/recetas/": "Portada Recetas Cuccinare",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/cucinare/capitulos/": "Capitulos Cuccinare",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/cucinare/recetas/?q=Pastel+de+bondiola": "Busqueda por palabra clave Cuccinare",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/cucinare/recetas/?espanola=true&pescados-y-mariscos=true&frituras=true": "Busqueda por filtro Cuccinare",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/tags/cucinare/arandanos/": "Tags Cuccinare",
        "https://artear-eltrece-sandbox.cdn.arcpublishing.com/cucinare/receta/solomillo-de-cerdo-con-chutney-de-peras-y-pure-de-batata-con-salsa-toffee/": "Recipe Cuccinare",
    },
}


if __name__ == "__main__":
    motor.main(BASE_URLS_MAP, producto_nombre=PRODUCTO, output_dir_base=OUTPUT_DIR_BASE,
               urls_por_ambiente=URLS_POR_AMBIENTE)
