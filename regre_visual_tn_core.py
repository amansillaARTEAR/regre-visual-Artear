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


def construir_fingerprint(item):
    """
    Identidad de un elemento basada en su naturaleza, no en su posición
    entre hermanos. Esto evita que insertar/mover UN elemento rompa la
    identidad de todos los que están después de él (el problema principal
    de nth-child puro).

    fingerprint = tag + clases estables (sin hashes) + atributos data-*
                  estables + primeros 40 caracteres del texto propio
    """
    tag = item.get('tag', '')
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


def emparejar_elementos(data_v1, data_v2):
    """
    Empareja elementos de V1 con V2 usando:
      1. Fingerprint + índice de ocurrencia dentro del mismo fingerprint
         (robusto a que se inserte/mueva un hermano no relacionado).
      2. Fallback: selector nth-child clásico, para elementos sin
         fingerprint útil (p. ej. <div> genérico sin clases ni texto).

    Devuelve: (pares, solo_v1, solo_v2)
      pares: lista de (item_v1, item_v2)
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
            pares.append((lista_v1[i], lista_v2[i]))
        if len(lista_v1) > n:
            solo_v1.extend(lista_v1[n:])
        if len(lista_v2) > n:
            solo_v2.extend(lista_v2[n:])

    # Fallback nth-child para elementos sin fingerprint útil
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
            pares.append((item1, candidato))
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

    for item1, item2 in pares:
        selector = item2.get('selector') or item1.get('selector')
        coords_v2 = {'x': item2['x'], 'y': item2['y'], 'width': item2['width'], 'height': item2['height']}
        coords_v1 = {'x': item1['x'], 'y': item1['y'], 'width': item1['width'], 'height': item1['height']}
        order_index = item2.get('order_index', 0)

        diff_height = abs(item1['height'] - item2['height'])
        if diff_height > umbral_pixeles:
            fallas.append(_falla(selector, 'DIFERENCIA ALTURA (H)', diff_height,
                                  item1['height'], item2['height'], coords_v2, coords_v1, order_index))

        diff_width = abs(item1['width'] - item2['width'])
        if diff_width > umbral_pixeles:
            fallas.append(_falla(selector, 'DIFERENCIA ANCHO (W)', diff_width,
                                  item1['width'], item2['width'], coords_v2, coords_v1, order_index))

        diff_y = abs(item1['y'] - item2['y'])
        if diff_y > umbral_pixeles:
            fallas.append(_falla(selector, 'DIFERENCIA POSICIÓN (Y)', diff_y,
                                  item1['y'], item2['y'], coords_v2, coords_v1, order_index,
                                  delta_y=item2['y'] - item1['y']))

        diff_x = abs(item1['x'] - item2['x'])
        if diff_x > umbral_pixeles:
            fallas.append(_falla(selector, 'DIFERENCIA POSICIÓN (X)', diff_x,
                                  item1['x'], item2['x'], coords_v2, coords_v1, order_index))

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


def _falla(selector, tipo, diff, v1, v2, coords_v2, coords_v1, order_index, delta_y=None):
    return {
        'selector': selector, 'tipo': tipo, 'diff': diff, 'v1': v1, 'v2': v2,
        'coords_v2': coords_v2, 'coords_v1': coords_v1, 'order_index': order_index,
        'delta_y': delta_y,
    }


# =====================================================================
# AGRUPACIÓN POR CAUSA RAÍZ (CASCADA)
# =====================================================================

def agrupar_cascadas(fallas):
    """
    Detecta clusters de fallas 'DIFERENCIA POSICIÓN (Y)' que comparten
    (casi) el mismo delta de Y y NO tienen ningún otro tipo de diferencia
    para ese mismo selector. Eso es la firma de un desplazamiento en
    cascada causado por UN elemento anterior que cambió de altura, no N
    regresiones independientes.

    Colapsa cada cluster de tamaño >= CASCADE_MIN_SIZE en un único
    hallazgo informativo, y deja el resto de las fallas (incluidas las Y
    que no entran en ningún cluster grande, o que coexisten con otro tipo
    de diferencia en el mismo selector) sin tocar.
    """
    # Selectores que tienen ALGÚN tipo de falla que no sea posición Y:
    # esos no son "puro efecto dominó", tratarlos como fallas reales.
    selectores_con_otra_falla = set()
    fallas_por_selector = defaultdict(list)
    for f in fallas:
        fallas_por_selector[f['selector']].append(f)

    for selector, lst in fallas_por_selector.items():
        tipos = {f['tipo'] for f in lst}
        if tipos - {'DIFERENCIA POSICIÓN (Y)'}:
            selectores_con_otra_falla.add(selector)

    candidatas_cascada = [
        f for f in fallas
        if f['tipo'] == 'DIFERENCIA POSICIÓN (Y)' and f['selector'] not in selectores_con_otra_falla
        and f.get('delta_y') is not None
    ]
    otras_fallas = [f for f in fallas if f not in candidatas_cascada]

    # Cluster por delta_y redondeado a un bucket de CASCADE_Y_EPSILON
    clusters = defaultdict(list)
    for f in candidatas_cascada:
        bucket = round(f['delta_y'] / CASCADE_Y_EPSILON) * CASCADE_Y_EPSILON
        clusters[bucket].append(f)

    resultado_cascadas = []
    for bucket, items in clusters.items():
        if len(items) >= CASCADE_MIN_SIZE:
            items_ordenados = sorted(items, key=lambda f: f['order_index'])
            primero = items_ordenados[0]
            resultado_cascadas.append({
                'tipo_cascada': True,
                'delta_y': bucket,
                'cantidad': len(items),
                'primer_selector': primero['selector'],
                'selectores': [f['selector'] for f in items_ordenados],
                'coords_v2': primero['coords_v2'],
            })
        else:
            # Cluster chico: no lo tratamos como cascada, va como falla normal.
            otras_fallas.extend(items)

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
