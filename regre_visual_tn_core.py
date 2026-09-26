"""
regre_visual_tn_core.py
========================
Lógica PURA de comparación estructural/visual para la herramienta de
regresión visual de TN. No depende de Selenium: solo de cv2/numpy/PIL
(para el diff visual) y de la librería estándar. Se separa así para poder
testear toda la lógica de detección de falsos positivos sin necesitar un
navegador ni acceso de red.

El script que orquesta Selenium (regre_visual_tn.py) importa este módulo.
"""

import re
import math
from collections import defaultdict

# =====================================================================
# CONFIGURACIÓN DE TOLERANCIAS Y MASKING
# =====================================================================

# Antes: 0px (cualquier subpíxel de antialiasing/redondeo contaba como falla).
# Ahora: tolerancia real. Configurable por llamada, este es el default.
UMBRAL_PIXELES_TOLERANCIA_DEFAULT = 3

# Tamaño mínimo de un cluster de "desplazamiento en cascada" para
# colapsarlo en un solo hallazgo de causa raíz en vez de N hallazgos sueltos.
CASCADE_MIN_SIZE = 3

# Tolerancia (en px) para considerar que dos elementos comparten el mismo
# delta de Y dentro de un cluster de cascada.
CASCADE_Y_EPSILON = 2

# Diferencia visual (0-1, fracción de píxeles distintos normalizada) por
# debajo de la cual, aunque el DOM haya detectado una diferencia de
# posición/tamaño, se considera que no hay impacto visual real.
UMBRAL_DIFERENCIA_VISUAL = 0.03

# Patrones (substring, case-insensitive) de id/clase que identifican
# contenedores de ads o contenido de terceros no determinístico. Estos
# elementos se EXCLUYEN de la comparación DOM (no solo se ocultan para
# limpiar popups, como hacían los scripts originales).
PATRONES_EXCLUSION = [
    'ad-slot', 'parent-ad-slot', 'ad-slot-header', 'ad-slot-caja',
    'ad-slot-megalateral', 'google_ads_iframe', 'dfp-ad', 'aniBox',
    'banner-container', 'cont-sidebar-ad',
    'teads', 'outbrain', 'taboola', 'criteo', 'moat', 'doubleclick',
    'recommend', 'recomendad', 'widget-clima', 'widget-dolar',
    'cotizacion', 'contador-en-vivo', 'live-counter',
    # Bitmovin Player UI (reproductor de video, usado en "Vivo"/streaming):
    # sus controles (play/pause, seek bar, tiempo, subtítulos) se redibujan
    # con tamaños/posiciones distintos según el estado de reproducción
    # (buffering, si está pausado, tiempo transcurrido) en el momento exacto
    # de la captura — no es un cambio del sitio. Visto en v721/mobile: el
    # 100% de las 138 "fallas graves" de Vivo eran elementos bmpui-id-*.
    'bmpui',
]

_PATRONES_EXCLUSION_RE = re.compile(
    '|'.join(re.escape(p) for p in PATRONES_EXCLUSION), re.IGNORECASE
)


def elemento_excluido(item):
    """
    True si el id o clase del elemento matchea algún patrón de masking
    (ads, contenido de terceros, widgets dinámicos conocidos).
    """
    id_attr = (item.get('id_attr') or '')
    class_attr = (item.get('class_attr') or '')
    texto = f"{id_attr} {class_attr}"
    if not texto.strip():
        return False
    return bool(_PATRONES_EXCLUSION_RE.search(texto))


# =====================================================================
# FINGERPRINT DE IDENTIDAD DE ELEMENTO (reemplazo de nth-child puro)
# =====================================================================

# Clases que parecen generadas/hasheadas (CSS-in-JS, hashes de build) y no
# aportan identidad estable: se descartan del fingerprint.
_CLASE_GENERADA_RE = re.compile(r'^[a-z0-9_-]{0,3}[a-f0-9]{6,}$|^css-[a-z0-9]+$', re.IGNORECASE)


def _clases_estables(class_attr):
    if not class_attr:
        return []
    clases = [c for c in class_attr.split() if c]
    estables = [c for c in clases if not _CLASE_GENERADA_RE.match(c)]
    return sorted(estables)  # orden estable, no depende del orden en el DOM


def _id_estable(id_attr):
    """
    Un id real asignado por el sitio (ej: 'player', 'main-nav') es la señal
    de identidad MÁS fuerte que hay — más confiable que clases o texto, que
    pueden cambiar legítimamente sin que el elemento sea "otro" (un
    reproductor de video en vivo, un ad, un ticker). Se descartan los ids
    que parecen generados/hasheados (mismo patrón que las clases generadas).
    """
    id_attr = (id_attr or '').strip()
    if not id_attr or _CLASE_GENERADA_RE.match(id_attr):
        return None
    return id_attr


def construir_fingerprint(item):
    """
    Identidad de un elemento basada en su naturaleza, no en su posición
    entre hermanos. Esto evita que insertar/mover UN elemento rompa la
    identidad de todos los que están después de él (el problema principal
    de nth-child puro).

    Si el elemento tiene un id real (no generado), ES la identidad —
    ignorando texto/clases. Caso real (v719, "Vivo"): div#player quedaba
    AUSENTE V2 + NUEVO EN V2 porque su contenido interno cambia según el
    estado de carga del video en vivo (V1 capturado antes de inicializar,
    V2 después), y antes el fingerprint dependía del texto, que difería.

    Si no hay id útil: fingerprint = tag + clases estables (sin hashes) +
    atributos data-* estables + primeros 40 caracteres del texto propio.
    """
    tag = item.get('tag', '')

    id_attr = _id_estable(item.get('id_attr'))
    if id_attr:
        return f'{tag}#{id_attr}'

    clases = _clases_estables(item.get('class_attr', ''))
    data_attrs = item.get('data_attrs', '') or ''
    texto = (item.get('texto', '') or '')[:40].strip()

    partes = [tag]
    if clases:
        partes.append('.'.join(clases))
    if data_attrs:
        partes.append(data_attrs)
    if texto:
        partes.append(texto)

    return '|'.join(partes) if len(partes) > 1 else None  # tag solo no es identidad útil


def indexar_por_fingerprint(data):
    """
    Agrupa los elementos de una corrida (V1 o V2) por fingerprint, en
    orden de aparición en el DOM. Devuelve dict fingerprint -> [items].
    Los elementos sin fingerprint útil (o excluidos por masking) se separan
    aparte para caer al fallback de selector nth-child.
    """
    grupos = defaultdict(list)
    sin_fingerprint = []
    for item in data:
        if elemento_excluido(item):
            continue
        fp = construir_fingerprint(item)
        if fp:
            grupos[fp].append(item)
        else:
            sin_fingerprint.append(item)
    return grupos, sin_fingerprint


def _identidad_es_debil(item):
    """
    True si la identidad de este item viene solo de tag+clases (sin id real
    ni texto propio) — es decir, si dos elementos distintos con la misma
    clase/tag caerían en el mismo fingerprint sin que su CONTENIDO real se
    haya comparado nunca. Caso real (v719, "Listado"/últimas-noticias): las
    tarjetas de noticia son <article class="card">, con el título en un
    <h2> anidado -> texto propio vacío -> el fingerprint es solo
    "article.card", y la tarjeta N de V1 queda emparejada con la tarjeta N
    de V2 aunque sean noticias completamente distintas (el listado se
    actualiza entre una corrida y otra).
    """
    return not _id_estable(item.get('id_attr')) and not (item.get('texto', '') or '').strip()


def _contenido_distinto(item1, item2):
    """
    True si el CONTENIDO real (no la geometría) de los dos elementos
    emparejados difiere -> son en verdad DOS tarjetas/noticias distintas,
    no la misma tarjeta que cambió de tamaño/posición. Dos señales,
    cualquiera alcanza:
      1. Texto del subárbol (título/copete real, no solo el texto propio
         usado en el fingerprint).
      2. Imagen del subárbol (primer <img src> o background-image) — hay
         tarjetas (carruseles de "destacados"/"recomendados") que son casi
         puro imagen, sin texto visible ni siquiera anidado. Caso real
         (Homepage v719): un carrusel reordenó sus tarjetas entre la
         captura de V1 y V2 y, sin esta señal, se reportaban ~10 cambios de
         tamaño/posición GRAVE que en realidad eran la misma tarjeta en
         otro lugar + otra ocupando su lugar viejo.
    Si NINGUNA de las dos señales tiene dato en ambos lados, no hay forma
    de decidir y se sigue comparando geometría normalmente (más vale un
    posible falso positivo raro que ocultar un cambio real sin ninguna
    evidencia de que el contenido cambió).
    """
    t1 = (item1.get('texto_subtree', '') or '').strip()
    t2 = (item2.get('texto_subtree', '') or '').strip()
    if t1 and t2:
        return t1 != t2

    img1 = (item1.get('img_src', '') or '').strip()
    img2 = (item2.get('img_src', '') or '').strip()
    if img1 and img2:
        return img1 != img2

    return False


def emparejar_elementos(data_v1, data_v2):
    """
    Empareja elementos de V1 con V2 usando:
      1. Fingerprint + índice de ocurrencia dentro del mismo fingerprint
         (robusto a que se inserte/mueva un hermano no relacionado).
      2. Fallback: selector nth-child clásico, para elementos sin
         fingerprint útil (p. ej. <div> genérico sin clases ni texto).

    Devuelve: (pares, solo_v1, solo_v2)
      pares: lista de (item_v1, item_v2, identidad_debil) — identidad_debil
        es True cuando el emparejamiento se hizo sin ninguna señal de
        contenido (ni id real, ni texto propio, ni siquiera fingerprint:
        cayó al fallback nth-child), es decir, cuando dos elementos
        "distintos" pueden haber quedado apareados solo por ocupar la
        misma posición.
      solo_v1: items de V1 sin matcheo en V2 -> candidatos a AUSENTE V2
      solo_v2: items de V2 sin matcheo en V1 -> candidatos a NUEVO EN V2
    """
    grupos_v1, resto_v1 = indexar_por_fingerprint(data_v1)
    grupos_v2, resto_v2 = indexar_por_fingerprint(data_v2)

    pares = []
    solo_v1 = []
    solo_v2 = []

    fingerprints = set(grupos_v1.keys()) | set(grupos_v2.keys())
    for fp in fingerprints:
        lista_v1 = grupos_v1.get(fp, [])
        lista_v2 = grupos_v2.get(fp, [])
        n = min(len(lista_v1), len(lista_v2))
        for i in range(n):
            debil = _identidad_es_debil(lista_v1[i])
            pares.append((lista_v1[i], lista_v2[i], debil))
        if len(lista_v1) > n:
            solo_v1.extend(lista_v1[n:])
        if len(lista_v2) > n:
            solo_v2.extend(lista_v2[n:])

    # Fallback nth-child para elementos sin fingerprint útil: nunca hubo
    # ninguna señal de contenido en el emparejamiento -> siempre "débil".
    map_v2_selector = {}
    for item in resto_v2:
        map_v2_selector.setdefault(item.get('selector'), []).append(item)

    usados_v2 = set()
    for item1 in resto_v1:
        sel = item1.get('selector')
        candidatos = map_v2_selector.get(sel, [])
        candidato = next((c for c in candidatos if id(c) not in usados_v2), None)
        if candidato is not None:
            usados_v2.add(id(candidato))
            pares.append((item1, candidato, True))
        else:
            solo_v1.append(item1)

    for item in resto_v2:
        if id(item) not in usados_v2:
            solo_v2.append(item)

    return pares, solo_v1, solo_v2


# =====================================================================
# NORMALIZACIÓN DE ESTILOS (antes: comparación de string exacto)
# =====================================================================

_RGB_RE = re.compile(r'rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)')

# font-weight: sinónimos que el navegador puede serializar distinto según
# si la fuente terminó de cargar (FOUT/FOIT) o según el motor de render.
_FONT_WEIGHT_SINONIMOS = {
    'normal': '400', '400': '400',
    'bold': '700', '700': '700',
}


def _normalizar_color(valor):
    """rgb(a,b,c) / rgba(a,b,c,d) -> tupla numérica redondeada, ignorando
    alpha=1 vs sin alpha (son el mismo color)."""
    if not valor:
        return None
    m = _RGB_RE.match(valor.strip())
    if not m:
        return valor.strip().lower()
    r, g, b, a = m.groups()
    alpha = float(a) if a is not None else 1.0
    return (round(float(r)), round(float(g)), round(float(b)), round(alpha, 2))


def _normalizar_font_weight(valor):
    if not valor:
        return None
    v = valor.strip().lower()
    return _FONT_WEIGHT_SINONIMOS.get(v, v)


def _normalizar_font_family(valor):
    """Compara solo la primera familia de la lista de fallback: si ambas
    corridas terminan resolviendo a la misma familia primaria, no es una
    regresión aunque el string completo del stack difiera."""
    if not valor:
        return None
    primera = valor.split(',')[0].strip().strip('"\'').lower()
    return primera


_NORMALIZADORES = {
    'color': _normalizar_color,
    'bgColor': _normalizar_color,
    'fontWeight': _normalizar_font_weight,
    'fontFamily': _normalizar_font_family,
}


def estilos_difieren(key, val1, val2):
    """True si, tras normalizar, los dos valores de estilo son realmente
    distintos (y no un artefacto de serialización/carga de fuente)."""
    if not val1 or not val2:
        return False  # falta de dato no es una diferencia confirmable
    normalizador = _NORMALIZADORES.get(key)
    if normalizador:
        v1n = normalizador(val1)
        v2n = normalizador(val2)
        return v1n != v2n
    return val1.strip() != val2.strip()


# =====================================================================
# COMPARACIÓN GEOMÉTRICA + DE ESTILOS
# =====================================================================

STYLE_KEYS = ['color', 'bgColor', 'fontSize', 'fontWeight', 'fontFamily', 'textAlign']


def comparar_estructura_dom(data_v1, data_v2, umbral_pixeles=UMBRAL_PIXELES_TOLERANCIA_DEFAULT,
                             comparar_estilos=True):
    """
    Compara V1 vs V2 usando emparejamiento por fingerprint (no nth-child
    puro), tolerancia real de píxeles, y estilos normalizados.

    Devuelve una lista de "fallas individuales" (sin agrupar todavía):
    cada una es un dict con selector, tipo, v1, v2, diff, coords_v2,
    order_index (posición en el DOM de V2, para la agrupación por
    cascada) y coords_v1 (para la confirmación visual posterior).
    """
    pares, solo_v1, solo_v2 = emparejar_elementos(data_v1, data_v2)

    fallas = []

    for item1, item2, debil in pares:
        # Emparejamiento sin ninguna señal de contenido (mismo tag+clase o
        # misma posición nth-child) + texto de subárbol realmente distinto
        # -> no es el mismo elemento "que cambió", son dos elementos DISTINTOS
        # que casualmente cayeron en la misma posición (caso real: tarjetas
        # de un listado de noticias en vivo, donde la noticia de ese lugar
        # cambió entre la captura de V1 y la de V2). Comparar su geometría o
        # estilo no sería un bug real, sería comparar peras con manzanas.
        if debil and _contenido_distinto(item1, item2):
            continue

        selector = item2.get('selector') or item1.get('selector')
        coords_v2 = {'x': item2['x'], 'y': item2['y'], 'width': item2['width'], 'height': item2['height']}
        coords_v1 = {'x': item1['x'], 'y': item1['y'], 'width': item1['width'], 'height': item1['height']}
        order_index = item2.get('order_index', 0)

        diff_height = abs(item1['height'] - item2['height'])
        if diff_height > umbral_pixeles:
            fallas.append(_falla(selector, 'DIFERENCIA ALTURA (H)', diff_height,
                                  item1['height'], item2['height'], coords_v2, coords_v1, order_index,
                                  delta=item2['height'] - item1['height']))

        diff_width = abs(item1['width'] - item2['width'])
        if diff_width > umbral_pixeles:
            fallas.append(_falla(selector, 'DIFERENCIA ANCHO (W)', diff_width,
                                  item1['width'], item2['width'], coords_v2, coords_v1, order_index,
                                  delta=item2['width'] - item1['width']))

        diff_y = abs(item1['y'] - item2['y'])
        if diff_y > umbral_pixeles:
            fallas.append(_falla(selector, 'DIFERENCIA POSICIÓN (Y)', diff_y,
                                  item1['y'], item2['y'], coords_v2, coords_v1, order_index,
                                  delta_y=item2['y'] - item1['y'], delta=item2['y'] - item1['y']))

        diff_x = abs(item1['x'] - item2['x'])
        if diff_x > umbral_pixeles:
            fallas.append(_falla(selector, 'DIFERENCIA POSICIÓN (X)', diff_x,
                                  item1['x'], item2['x'], coords_v2, coords_v1, order_index,
                                  delta=item2['x'] - item1['x']))

        if comparar_estilos:
            styles1 = item1.get('styles', {}) or {}
            styles2 = item2.get('styles', {}) or {}
            for key in STYLE_KEYS:
                val1, val2 = styles1.get(key), styles2.get(key)
                if estilos_difieren(key, val1, val2):
                    fallas.append(_falla(selector, f'DIFERENCIA ESTILO ({key.upper()})', 'N/A',
                                          val1, val2, coords_v2, coords_v1, order_index))

    for item1 in solo_v1:
        coords_v1 = {'x': item1['x'], 'y': item1['y'], 'width': item1['width'], 'height': item1['height']}
        fallas.append(_falla(item1.get('selector'), 'AUSENTE V2', 'N/A', 'N/A', 'N/A',
                              coords_v1, coords_v1, item1.get('order_index', 0)))

    for item2 in solo_v2:
        coords_v2 = {'x': item2['x'], 'y': item2['y'], 'width': item2['width'], 'height': item2['height']}
        fallas.append(_falla(item2.get('selector'), 'NUEVO EN V2', 'N/A', 'N/A', 'N/A',
                              coords_v2, coords_v2, item2.get('order_index', 0)))

    return fallas


def _falla(selector, tipo, diff, v1, v2, coords_v2, coords_v1, order_index, delta_y=None, delta=None):
    return {
        'selector': selector, 'tipo': tipo, 'diff': diff, 'v1': v1, 'v2': v2,
        'coords_v2': coords_v2, 'coords_v1': coords_v1, 'order_index': order_index,
        # 'delta_y' se mantiene por compatibilidad (código/tests viejos lo usan
        # para el tipo Y específicamente); 'delta' es el equivalente genérico
        # (con signo) para cualquier tipo agrupable en cascada (Y, H o W).
        'delta_y': delta_y,
        'delta': delta if delta is not None else delta_y,
    }


# =====================================================================
# AGRUPACIÓN POR CAUSA RAÍZ (CASCADA)
# =====================================================================

# Tipos de falla que pueden ser causa raíz de una cascada: un desplazamiento
# en Y o X (efecto dominó de un elemento anterior que cambió de tamaño,
# vertical u horizontal — ej: un carrusel/scroller horizontal donde varios
# links se corren el mismo delta de X) o un cambio de alto/ancho que se
# repite idéntico en varios selectores porque en realidad es UN solo cambio
# (ej: una fila del footer que desaparece hace que el contenedor, sus
# hermanos de igual altura y sus ancestros pierdan todos los mismos px de
# alto).
TIPOS_CASCADABLES = (
    'DIFERENCIA POSICIÓN (Y)', 'DIFERENCIA POSICIÓN (X)',
    'DIFERENCIA ALTURA (H)', 'DIFERENCIA ANCHO (W)',
)


def _es_cadena_de_ancestros(selectores):
    """
    True si cada selector de la lista es ancestro/descendiente directo del
    anterior en la jerarquía del DOM (ej: 'div:nth-child(48)',
    'div:nth-child(48) > div', 'div:nth-child(48) > div > div'). Es decir:
    es literalmente EL MISMO elemento visto en distintas profundidades de
    anidamiento (el box de un ad + su wrapper + su contenedor), no una
    coincidencia de magnitud entre selectores sin relación. Visto en el
    reporte real v719: un ad-slot solo tiene 2 niveles (no 3+), así que
    nunca llegaba a CASCADE_MIN_SIZE aunque fuera clarísimamente el mismo
    elemento.
    """
    if len(selectores) < 2:
        return False
    partes = sorted((s.split(' > ') for s in selectores if s), key=len)
    if len(partes) != len(selectores):
        return False
    for i in range(len(partes) - 1):
        corto, largo = partes[i], partes[i + 1]
        if largo[:len(corto)] != corto:
            return False
    return True


def agrupar_cascadas(fallas):
    """
    Detecta clusters de fallas que comparten (casi) el mismo delta con
    signo para un mismo tipo (Y, H o W) y NO tienen ningún otro tipo de
    diferencia para ese mismo selector. Eso es la firma de un cambio en
    cascada causado por UNA sola causa raíz (un elemento que se movió, o
    que cambió de tamaño y arrastró a sus contenedores/hermanos), no N
    regresiones independientes.

    Colapsa cada cluster de tamaño >= CASCADE_MIN_SIZE en un único
    hallazgo informativo, y deja el resto de las fallas (incluidas las que
    no entran en ningún cluster grande, o que coexisten con otro tipo de
    diferencia en el mismo selector) sin tocar.
    """
    otras_fallas = list(fallas)
    resultado_cascadas = []

    for tipo in TIPOS_CASCADABLES:
        # Selectores que tienen, ADEMÁS, un tipo de falla NO cascadeable
        # (estilo, posición X, ausente/nuevo): esos sí son un cambio real
        # propio del elemento, no "puro efecto dominó", y se tratan como
        # fallas reales (se decide sobre las fallas ORIGINALES, no sobre lo
        # que ya fue colapsado por un tipo anterior en este mismo loop).
        #
        # OJO: que un mismo elemento tenga a la vez H Y Y (o W y H) NO lo
        # descalifica — es exactamente lo esperable en un ad-slot anidado:
        # el contenedor cambia de alto (su propia causa) Y además se corre
        # en Y (efecto de lo que cambió arriba). Descalificarlo por eso
        # hacía que NINGÚN ad-slot calificara nunca para agruparse (visto
        # en el reporte real v719: 7 ad-slots x 2-3 niveles de anidamiento
        # quedaban como ~20 fallas "graves" sueltas en vez de agruparse).
        selectores_con_otra_falla = set()
        fallas_por_selector = defaultdict(list)
        for f in fallas:
            fallas_por_selector[f['selector']].append(f)
        for selector, lst in fallas_por_selector.items():
            tipos_del_selector = {f['tipo'] for f in lst}
            if tipos_del_selector - set(TIPOS_CASCADABLES):
                selectores_con_otra_falla.add(selector)

        candidatas_cascada = [
            f for f in otras_fallas
            if f['tipo'] == tipo and f['selector'] not in selectores_con_otra_falla
            and f.get('delta') is not None
        ]
        restantes = [f for f in otras_fallas if f not in candidatas_cascada]

        # Cluster por delta redondeado a un bucket de CASCADE_Y_EPSILON
        # (misma tolerancia de bucketing para Y/H/W: son todas medidas en px).
        clusters = defaultdict(list)
        for f in candidatas_cascada:
            bucket = round(f['delta'] / CASCADE_Y_EPSILON) * CASCADE_Y_EPSILON
            clusters[bucket].append(f)

        for bucket, items in clusters.items():
            cadena_ancestros = _es_cadena_de_ancestros([f['selector'] for f in items])
            if len(items) >= CASCADE_MIN_SIZE or cadena_ancestros:
                items_ordenados = sorted(items, key=lambda f: f['order_index'])
                primero = items_ordenados[0]
                resultado_cascadas.append({
                    'tipo_cascada': True,
                    'tipo': tipo,
                    'delta_y': bucket,  # compatibilidad: mismo nombre de campo para los 3 tipos
                    'cantidad': len(items),
                    'primer_selector': primero['selector'],
                    'selectores': [f['selector'] for f in items_ordenados],
                    'coords_v2': primero['coords_v2'],
                })
            else:
                # Cluster chico: no lo tratamos como cascada, va como falla normal.
                restantes.extend(items)

        otras_fallas = restantes

    # Pass final: un contenedor que envuelve TODA la página (ej: el wrapper
    # raíz del body) cambia de alto/ancho exactamente lo mismo que la causa
    # raíz real de más abajo, porque su tamaño es la suma de su contenido.
    # Visto en varios reportes reales: "header > div > div:nth-child(3)"
    # (miles/decenas de miles de px de alto) queda como GRAVE suelto con el
    # mismo delta que una cascada ya detectada en esa misma página. Es el
    # mismo cambio visto desde la raíz, no una regresión adicional — se
    # absorbe en la cascada existente en vez de listarse aparte.
    if resultado_cascadas:
        aun_sueltas = []
        for f in otras_fallas:
            if f['tipo'] not in TIPOS_CASCADABLES or f.get('delta') is None:
                aun_sueltas.append(f)
                continue
            cascada_match = next(
                (c for c in resultado_cascadas
                 if abs(abs(c['delta_y']) - abs(f['delta'])) <= CASCADE_Y_EPSILON),
                None,
            )
            if cascada_match:
                cascada_match['cantidad'] += 1
                cascada_match['selectores'].append(f['selector'])
            else:
                aun_sueltas.append(f)
        otras_fallas = aun_sueltas

    return otras_fallas, resultado_cascadas


# =====================================================================
# CONFIRMACIÓN VISUAL (crop + diff) — requiere cv2/numpy, opcional
# =====================================================================

def _crop_seguro(img, x, y, w, h):
    alto, ancho = img.shape[:2]
    x1, y1 = max(0, int(x)), max(0, int(y))
    x2, y2 = min(ancho, int(x + w)), min(alto, int(y + h))
    if x2 <= x1 or y2 <= y1:
        return None
    return img[y1:y2, x1:x2]


def diferencia_visual_normalizada(img_v1, img_v2, coords_v1, coords_v2):
    """
    Recorta la región de la falla en V1 y en V2, las lleva al mismo
    tamaño y devuelve la fracción de diferencia (0 = idéntico, 1 = todo
    distinto). Se usa para degradar una falla "grave" por DOM cuando el
    contenido visual de esa región no cambió realmente (p. ej. cambió un
    atributo invisible, o el nth-child viejo apuntaba a algo levemente
    distinto pero visualmente igual).
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None  # sin cv2 no podemos confirmar; el caller debe asumir "no confirmado"

    crop1 = _crop_seguro(img_v1, coords_v1['x'], coords_v1['y'], coords_v1['width'], coords_v1['height'])
    crop2 = _crop_seguro(img_v2, coords_v2['x'], coords_v2['y'], coords_v2['width'], coords_v2['height'])
    if crop1 is None or crop2 is None:
        return None

    alto_ref, ancho_ref = crop1.shape[:2]
    if alto_ref == 0 or ancho_ref == 0:
        return None
    crop2_resized = cv2.resize(crop2, (ancho_ref, alto_ref))

    diff = cv2.absdiff(crop1, crop2_resized)
    return float(np.mean(diff)) / 255.0


def confirmar_visualmente(img_v1, img_v2, fallas, umbral=UMBRAL_DIFERENCIA_VISUAL):
    """
    Para cada falla de tipo dimensión/posición (no estilo, no ausente/
    nuevo, no cascada), corre el diff visual y, si por debajo del umbral,
    la reclasifica como 'informativo' en vez de 'grave'.

    Devuelve la misma lista de fallas con un campo nuevo 'confirmado_visualmente'.
    """
    tipos_confirmables = {
        'DIFERENCIA ALTURA (H)', 'DIFERENCIA ANCHO (W)',
        'DIFERENCIA POSICIÓN (Y)', 'DIFERENCIA POSICIÓN (X)',
    }
    for f in fallas:
        f.setdefault('confirmado_visualmente', None)
        if f['tipo'] not in tipos_confirmables:
            continue
        ratio = diferencia_visual_normalizada(img_v1, img_v2, f['coords_v1'], f['coords_v2'])
        if ratio is None:
            continue
        f['confirmado_visualmente'] = ratio
        if ratio < umbral:
            f['degradado_por_visual'] = True
    return fallas


# =====================================================================
# CLASIFICACIÓN DE GRAVEDAD Y CONSOLIDACIÓN FINAL
# =====================================================================

def clasificar_gravedad(fallas_selector):
    """
    Dado el conjunto de fallas de UN selector, decide la gravedad:
      - grave: AUSENTE/NUEVO, o cambio de dimensión/estilo confirmado
        visualmente (no degradado).
      - informativo: la diferencia fue degradada por confirmación visual
        (el DOM cambió pero visualmente es igual) o es puro reordenamiento
        sin cambio real de contenido.
      - menor: cambios de posición sin cambio de dimensión (efecto dominó
        chico, no agrupado en cascada).
    """
    tipos = [f['tipo'] for f in fallas_selector]

    if any(t in ('AUSENTE V2', 'NUEVO EN V2') for t in tipos):
        return 'grave'

    hay_dimension_o_estilo = any(
        'ALTURA' in t or 'ANCHO' in t or 'ESTILO' in t for t in tipos
    )
    if hay_dimension_o_estilo:
        # Si TODAS las fallas de dimensión/estilo fueron degradadas por
        # confirmación visual, no es grave.
        relevantes = [f for f in fallas_selector if 'ALTURA' in f['tipo'] or 'ANCHO' in f['tipo'] or 'ESTILO' in f['tipo']]
        if relevantes and all(f.get('degradado_por_visual') for f in relevantes):
            return 'informativo'
        return 'grave'

    return 'menor'


def consolidar_fallas(fallas):
    """
    Agrupa las fallas individuales (ya pasadas por cascada + confirmación
    visual) por selector, en el mismo formato que consumía el reporte
    HTML original: una entrada por selector con su gravedad final.
    """
    agrupadas = defaultdict(list)
    for f in fallas:
        agrupadas[f['selector']].append(f)

    resultado = []
    for selector, lst in agrupadas.items():
        gravedad = clasificar_gravedad(lst)
        resultado.append({
            'selector': selector,
            'gravedad': gravedad,
            'fallas': lst,
            'coords_v2': lst[0]['coords_v2'],
        })
    return resultado
