"""
Tests offline de la lógica pura (sin Selenium, sin red).
Corren contra datos sintéticos que reproducen los patrones de falsos
positivos vistos en Reporte_DOM_Estructural_v719_20260915_094945.html:
  - cascada de nth-child al insertar una nota en un listado
  - desplazamiento en cascada por un ad que cambió de alto
  - contenido de terceros (Teads) que aparece/desaparece
  - diferencia de estilo por fuente no cargada (FOUT) -> normaliza igual
  - scrollbar (12-15px de ancho) -> ejemplo de por qué la tolerancia > 0 ayuda
"""

import regre_visual_tn_core as core


def item(tag, selector, x, y, w, h, id_attr='', class_attr='', texto='', styles=None,
         data_attrs='', order_index=0, texto_subtree='', img_src='', iframe_src=''):
    return {
        'tag': tag, 'selector': selector, 'x': x, 'y': y, 'width': w, 'height': h,
        'id_attr': id_attr, 'class_attr': class_attr, 'texto': texto,
        'styles': styles or {}, 'data_attrs': data_attrs, 'order_index': order_index,
        'texto_subtree': texto_subtree, 'img_src': img_src, 'iframe_src': iframe_src,
    }


def test_fingerprint_evita_cascada_por_insercion():
    """
    Caso Listado/Juegos del reporte real: se inserta una nota nueva en la
    posición 4, y con nth-child puro TODO lo que viene después cambia de
    selector. Con fingerprint (tag+clases+texto), los artículos existentes
    deben seguir matcheando aunque su índice haya cambiado.
    """
    v1 = [
        item('article', 'article:nth-child(1)', 0, 0, 300, 100, class_attr='card', texto='Nota A', order_index=0),
        item('article', 'article:nth-child(2)', 0, 100, 300, 100, class_attr='card', texto='Nota B', order_index=1),
        item('article', 'article:nth-child(3)', 0, 200, 300, 100, class_attr='card', texto='Nota C', order_index=2),
    ]
    # V2: se insertó "Nota Nueva" al principio -> todo se corre, y con
    # nth-child el selector de B y C cambiaría, pero el fingerprint (texto)
    # sigue siendo el mismo.
    v2 = [
        item('article', 'article:nth-child(1)', 0, 0, 300, 100, class_attr='card', texto='Nota Nueva', order_index=0),
        item('article', 'article:nth-child(2)', 0, 100, 300, 100, class_attr='card', texto='Nota A', order_index=1),
        item('article', 'article:nth-child(3)', 0, 200, 300, 100, class_attr='card', texto='Nota B', order_index=2),
        item('article', 'article:nth-child(4)', 0, 300, 300, 100, class_attr='card', texto='Nota C', order_index=3),
    ]

    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=False)
    tipos = [f['tipo'] for f in fallas]

    # Con fingerprint: Nota A, B, C matchean por texto (aunque cambien de
    # posición), y solo "Nota Nueva" debería aparecer como NUEVO EN V2.
    nuevos = [f for f in fallas if f['tipo'] == 'NUEVO EN V2']
    ausentes = [f for f in fallas if f['tipo'] == 'AUSENTE V2']

    assert len(nuevos) == 1, f"Esperaba 1 NUEVO EN V2 (Nota Nueva), obtuve {len(nuevos)}: {tipos}"
    assert len(ausentes) == 0, f"No debería haber AUSENTE V2 (todo lo viejo sigue matcheando por texto), obtuve {len(ausentes)}"
    print("OK: fingerprint evita cascada de AUSENTE/NUEVO por inserción de un elemento")


def test_masking_excluye_ads_y_terceros():
    """Caso Article del reporte real: aparece/desaparece un bloque de
    Teads. Con masking, no debería generar ninguna falla."""
    v1 = [
        item('div', 'div:nth-child(5)', 0, 0, 300, 100, class_attr='content', texto='Cuerpo de la nota'),
    ]
    v2 = [
        item('div', 'div:nth-child(5)', 0, 0, 300, 100, class_attr='content', texto='Cuerpo de la nota'),
        item('div', 'div:nth-child(6)', 0, 100, 300, 250, id_attr='teads-inread', class_attr='teads-inread-item'),
    ]
    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=False)
    assert len(fallas) == 0, f"El bloque de Teads debería estar excluido por masking, pero generó: {fallas}"
    print("OK: masking excluye bloques de Teads/terceros de la comparación")


def test_masking_excluye_controles_de_video_bmpui():
    """Caso Vivo del reporte real v721/mobile: el 100% de las 138 fallas
    graves eran controles del reproductor Bitmovin (ids bmpui-id-*), que
    cambian de tamaño/posición según el estado de reproducción en el
    momento exacto de la captura, no porque el sitio haya cambiado."""
    v1 = [
        item('div', 'div#player', 0, 0, 485, 300, id_attr='player', class_attr='video-wrapper',
             texto='reproductor'),
        item('div', 'div#bmpui-id-129', 0, 300, 485, 36, id_attr='bmpui-id-129',
             texto='controles'),
    ]
    v2 = [
        item('div', 'div#player', 0, 0, 485, 300, id_attr='player', class_attr='video-wrapper',
             texto='reproductor'),
        item('div', 'div#bmpui-id-129', 0, 300, 449, 18, id_attr='bmpui-id-129',
             texto='controles'),
    ]
    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=False)
    assert len(fallas) == 0, f"Los controles bmpui deberían estar excluidos por masking, pero generó: {fallas}"
    print("OK: masking excluye controles del reproductor de video (bmpui) de la comparación")


def test_cascada_por_altura_de_ad_se_colapsa():
    """
    Caso Podcast del reporte real: un ad pasa de 250 a 600px de alto, y
    TODOS los elementos debajo se corren exactamente esos 350px. Debería
    colapsarse en un solo hallazgo de cascada, no en 30 fallas sueltas.
    """
    v1 = [item('div', f'div:nth-child({i})', 0, i * 100, 300, 100,
                class_attr=f'block-{i}', texto=f'contenido {i}', order_index=i)
          for i in range(1, 8)]
    v2 = [item('div', f'div:nth-child({i})', 0, i * 100 + 350, 300, 100,
                class_attr=f'block-{i}', texto=f'contenido {i}', order_index=i)
          for i in range(1, 8)]

    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=False)
    otras, cascadas = core.agrupar_cascadas(fallas)

    assert len(cascadas) == 1, f"Esperaba 1 cluster de cascada, obtuve {len(cascadas)}"
    assert cascadas[0]['cantidad'] == 7, f"Esperaba 7 elementos en la cascada, obtuve {cascadas[0]['cantidad']}"
    assert abs(cascadas[0]['delta_y'] - 350) <= core.CASCADE_Y_EPSILON
    assert len(otras) == 0, "No debería quedar ninguna falla suelta de posición Y fuera de la cascada"
    print("OK: cascada de 7 elementos por un mismo delta de Y se colapsa en 1 hallazgo")


def test_cascada_pequena_no_se_colapsa():
    """Un cluster de solo 2 elementos no debería tratarse como cascada
    (el umbral es CASCADE_MIN_SIZE=3): dos coincidencias podrían ser azar."""
    v1 = [item('div', f'div:nth-child({i})', 0, i * 100, 300, 100,
                class_attr=f'block-{i}', texto=f'x{i}', order_index=i) for i in range(1, 3)]
    v2 = [item('div', f'div:nth-child({i})', 0, i * 100 + 20, 300, 100,
                class_attr=f'block-{i}', texto=f'x{i}', order_index=i) for i in range(1, 3)]

    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=False)
    otras, cascadas = core.agrupar_cascadas(fallas)
    assert len(cascadas) == 0
    assert len(otras) == 2
    print("OK: cluster de 2 elementos no se trata como cascada (queda como fallas individuales)")


def test_cascada_por_altura_de_footer_se_colapsa():
    """
    Caso Homepage del reporte real v721: una fila del footer desaparece y
    el contenedor, sus 3 columnas hermanas (de igual alto por flexbox) y su
    ancestro pierden todos exactamente 20px de alto. Antes se reportaban
    como 4+ fallas graves independientes; deberían colapsarse en 1 cascada
    de tipo ALTURA (H), igual que ya pasaba para POSICIÓN (Y)."""
    nombres = ['footer-wrap', 'footer-col-1', 'footer-col-2', 'footer-col-3']
    v1 = [item('div', f'footer > div:nth-child({i})', 0, 0, 300, 300,
                class_attr=nombre, texto=nombre, order_index=i)
          for i, nombre in enumerate(nombres, start=1)]
    v2 = [item('div', f'footer > div:nth-child({i})', 0, 0, 300, 280,
                class_attr=nombre, texto=nombre, order_index=i)
          for i, nombre in enumerate(nombres, start=1)]

    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=False)
    otras, cascadas = core.agrupar_cascadas(fallas)

    assert len(cascadas) == 1, f"Esperaba 1 cluster de cascada por altura, obtuve {len(cascadas)}"
    assert cascadas[0]['tipo'] == 'DIFERENCIA ALTURA (H)'
    assert cascadas[0]['cantidad'] == 4, f"Esperaba 4 elementos en la cascada, obtuve {cascadas[0]['cantidad']}"
    assert abs(cascadas[0]['delta_y'] - (-20)) <= core.CASCADE_Y_EPSILON
    assert len(otras) == 0, "No debería quedar ninguna falla suelta de altura fuera de la cascada"
    print("OK: cascada de 4 elementos por un mismo delta de altura (footer) se colapsa en 1 hallazgo")


def test_falla_suelta_de_wrapper_de_pagina_se_absorbe_en_cascada():
    """Caso Homepage/Elecciones del reporte real v719: un cambio de
    contenido más abajo genera una cascada de posición Y de varios
    elementos, y ADEMÁS el contenedor que envuelve toda la página (altura
    de decenas de miles de px) aparece con un cambio de alto EXACTAMENTE
    igual al delta de esa cascada. Es el mismo cambio visto desde la raíz,
    no una falla independiente: debe absorberse en la cascada, no quedar
    como GRAVE suelto."""
    v1 = [item('div', f'div:nth-child({i})', 0, i * 100, 300, 100,
                class_attr=f'block-{i}', texto=f'contenido {i}', order_index=i)
          for i in range(1, 8)]
    v2 = [item('div', f'div:nth-child({i})', 0, i * 100 + 16, 300, 100,
                class_attr=f'block-{i}', texto=f'contenido {i}', order_index=i)
          for i in range(1, 8)]
    # El wrapper de toda la página: mismo delta (16px) pero de ALTURA, no de Y.
    v1.append(item('div', 'header > div > div:nth-child(3)', 0, 0, 50000, 44367,
                    id_attr='page-wrapper', texto='wrapper', order_index=0))
    v2.append(item('div', 'header > div > div:nth-child(3)', 0, 0, 50000, 44383,
                    id_attr='page-wrapper', texto='wrapper', order_index=0))

    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=False)
    otras, cascadas = core.agrupar_cascadas(fallas)

    assert len(cascadas) == 1, f"Esperaba 1 cascada, obtuve {len(cascadas)}"
    assert cascadas[0]['cantidad'] == 8, f"Esperaba 7 elementos + el wrapper = 8, obtuve {cascadas[0]['cantidad']}"
    assert not any('page-wrapper' in (f['selector'] or '') for f in otras), \
        "El wrapper de página debería haberse absorbido en la cascada, no quedar suelto"
    print("OK: falla suelta del wrapper de página se absorbe en la cascada existente en vez de listarse como GRAVE aparte")


def test_cascada_por_altura_no_se_descalifica_por_tener_tambien_y():
    """Caso real v719: un ad-slot anidado (el div del ad, su wrapper y su
    contenedor) cambia de alto en los 3 niveles por el mismo delta, y CADA
    nivel además tiene su propio corrimiento de Y (efecto normal de que algo
    más arriba también cambió). Antes, tener Y ademas de H descalificaba al
    selector de agruparse por H — así que NINGÚN ad-slot se agrupaba nunca
    y quedaban ~3 fallas GRAVE sueltas por cada ad, todas "diciendo lo
    mismo". Deben colapsarse en 1 cascada de tipo H igual que el resto."""
    nombres = ['ad-outer', 'ad-wrapper', 'ad-inner']
    v1 = [item('div', f'main > div:nth-child(48){suf}', 0, 15000 + i * 10, 300, 600,
                class_attr=nombre, texto=nombre, order_index=i)
          for i, (nombre, suf) in enumerate(zip(nombres, ['', ' > div', ' > div > div']))]
    v2 = [item('div', f'main > div:nth-child(48){suf}', 0, 15086 + i * 10, 300, 686,
                class_attr=nombre, texto=nombre, order_index=i)
          for i, (nombre, suf) in enumerate(zip(nombres, ['', ' > div', ' > div > div']))]

    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=False)
    otras, cascadas = core.agrupar_cascadas(fallas)

    cascadas_h = [c for c in cascadas if c.get('tipo') == 'DIFERENCIA ALTURA (H)']
    assert len(cascadas_h) == 1, f"Esperaba 1 cascada de altura, obtuve {len(cascadas_h)}: {cascadas}"
    assert cascadas_h[0]['cantidad'] == 3
    print("OK: un ad-slot anidado con H+Y a la vez en cada nivel igual se agrupa por altura")


def test_cascada_de_2_se_colapsa_si_es_cadena_de_ancestros():
    """Caso real v719 (después del fix anterior): un ad-slot con solo 2
    niveles de anidamiento (el div y su hijo directo) comparte el mismo
    delta de alto, pero como son solo 2 no llegaba a CASCADE_MIN_SIZE=3 y
    quedaba como 2 fallas GRAVE sueltas — aun siendo obviamente el MISMO
    elemento. Si los selectores forman una cadena ancestro→hijo, alcanza
    con 2 para colapsar (no es coincidencia de magnitud, es el mismo caja)."""
    v1 = [
        item('div', 'main > div:nth-child(72)', 0, 15000, 1200, 737.97, order_index=1, texto='ad'),
        item('div', 'main > div:nth-child(72) > div', 0, 15000, 1200, 737.97, order_index=2, texto='ad-inner'),
    ]
    v2 = [
        item('div', 'main > div:nth-child(72)', 0, 15000, 1200, 786.98, order_index=1, texto='ad'),
        item('div', 'main > div:nth-child(72) > div', 0, 15000, 1200, 786.98, order_index=2, texto='ad-inner'),
    ]
    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=False)
    otras, cascadas = core.agrupar_cascadas(fallas)
    assert len(cascadas) == 1, f"Esperaba 1 cascada, obtuve {len(cascadas)}: fallas sueltas={otras}"
    assert cascadas[0]['cantidad'] == 2
    assert len(otras) == 0
    print("OK: 2 elementos en cadena ancestro-hijo con el mismo delta se colapsan aunque sean solo 2")


def test_id_real_evita_ausente_nuevo_por_contenido_dinamico():
    """Caso real v719: 'Vivo' tiene un reproductor de video en vivo cuyo
    contenido interno se inicializa de forma asíncrona — en V1 la captura
    lo agarra vacío/negro (sin texto todavía) y en V2 ya cargado (con el
    logo/texto). Antes esto rompía el fingerprint (basado en texto) y el
    div#player quedaba como AUSENTE V2 + NUEVO EN V2 (2 fallas GRAVE) en
    vez de matchear como el mismo elemento. Con id real, debe matchear
    (y al no cambiar tamaño/posición, no generar ninguna falla)."""
    v1 = [item('div', 'div#player', 100, 200, 974, 547, id_attr='player', texto='')]
    v2 = [item('div', 'div#player', 100, 200, 974, 547, id_attr='player', texto='TN en vivo')]
    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=False)
    assert len(fallas) == 0, f"div#player debería matchear por id y no generar fallas, obtuve: {fallas}"
    print("OK: un id real evita el falso AUSENTE+NUEVO cuando el contenido interno cambia por carga asíncrona")


def test_cascada_por_posicion_x_se_colapsa():
    """Caso real v719 (Homepage): un carrusel horizontal de links se corre
    todo el mismo delta de X (370.03px) porque algo antes de él cambió de
    ancho — igual que la cascada de Y, pero en el eje horizontal. Antes,
    'DIFERENCIA POSICIÓN (X)' no estaba en TIPOS_CASCADABLES, así que
    ninguna cascada horizontal se agrupaba nunca: quedaban N fallas MENOR
    sueltas 'diciendo lo mismo' (visto: ~15 links con Diff idéntico)."""
    v1 = [item('a', f'nav > a:nth-child({i})', i * 200, 50, 180, 40,
                class_attr=f'link-{i}', texto=f'link {i}', order_index=i)
          for i in range(1, 8)]
    v2 = [item('a', f'nav > a:nth-child({i})', i * 200 + 370, 50, 180, 40,
                class_attr=f'link-{i}', texto=f'link {i}', order_index=i)
          for i in range(1, 8)]
    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=False)
    otras, cascadas = core.agrupar_cascadas(fallas)
    cascadas_x = [c for c in cascadas if c.get('tipo') == 'DIFERENCIA POSICIÓN (X)']
    assert len(cascadas_x) == 1, f"Esperaba 1 cascada de X, obtuve {len(cascadas_x)}: {cascadas}"
    assert cascadas_x[0]['cantidad'] == 7
    assert len(otras) == 0
    print("OK: un carrusel horizontal que se corre en X se colapsa en 1 cascada, igual que en Y")


def test_estilo_normaliza_font_weight_y_color():
    """Caso: FOUT/FOIT hace que V1 diga font-weight:normal y V2 diga 400
    (son lo mismo), y que el color venga como rgb(0,0,0) vs rgba(0,0,0,1)
    (también son lo mismo). No debería marcarse como diferencia."""
    v1 = [item('p', 'p:nth-child(1)', 0, 0, 100, 20, class_attr='texto', texto='hola',
                styles={'color': 'rgb(0, 0, 0)', 'fontWeight': 'normal', 'fontSize': '14px',
                        'fontFamily': 'Arial, sans-serif', 'bgColor': '', 'textAlign': 'left'})]
    v2 = [item('p', 'p:nth-child(1)', 0, 0, 100, 20, class_attr='texto', texto='hola',
                styles={'color': 'rgba(0, 0, 0, 1)', 'fontWeight': '400', 'fontSize': '14px',
                        'fontFamily': 'Arial, Helvetica, sans-serif', 'bgColor': '', 'textAlign': 'left'})]

    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=True)
    estilos = [f for f in fallas if 'ESTILO' in f['tipo']]
    assert len(estilos) == 0, f"No debería haber diferencia de estilo tras normalizar, obtuve: {estilos}"
    print("OK: normalización de estilos evita falsos positivos de FOUT/color/font-family")


def test_estilo_real_si_se_detecta():
    """Control: un cambio de color real (rojo vs negro) SÍ debe marcarse."""
    v1 = [item('p', 'p:nth-child(1)', 0, 0, 100, 20, class_attr='texto', texto='hola',
                styles={'color': 'rgb(0, 0, 0)', 'fontWeight': '400', 'fontSize': '14px',
                        'fontFamily': 'Arial', 'bgColor': '', 'textAlign': 'left'})]
    v2 = [item('p', 'p:nth-child(1)', 0, 0, 100, 20, class_attr='texto', texto='hola',
                styles={'color': 'rgb(255, 0, 0)', 'fontWeight': '400', 'fontSize': '14px',
                        'fontFamily': 'Arial', 'bgColor': '', 'textAlign': 'left'})]
    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=True)
    estilos = [f for f in fallas if 'ESTILO' in f['tipo']]
    assert len(estilos) == 1, f"Un cambio real de color debería detectarse, obtuve: {estilos}"
    print("OK: un cambio de estilo real (no artefacto) sigue detectándose")


def test_tolerancia_evita_ruido_de_scrollbar():
    """Caso Homepage/Juegos/Longform del reporte real: ancho de página
    difiere ~12-15px por aparición/desaparición de la scrollbar. Con
    tolerancia 0 (original) esto marcaba falla; con tolerancia >=3 (o el
    fix de overflow:hidden) no debería, dentro de rango normal de layout."""
    v1 = [item('div', 'div:nth-child(1)', 0, 0, 1904, 50, class_attr='header', texto='header')]
    v2 = [item('div', 'div:nth-child(1)', 0, 0, 1901, 50, class_attr='header', texto='header')]  # 3px, dentro de tolerancia
    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=False)
    assert len(fallas) == 0, f"3px de diferencia debería estar dentro de tolerancia, obtuve: {fallas}"

    v1b = [item('div', 'div:nth-child(1)', 0, 0, 1904, 50, class_attr='header', texto='header')]
    v2b = [item('div', 'div:nth-child(1)', 0, 0, 1889, 50, class_attr='header', texto='header')]  # 15px, real (scrollbar)
    fallas_b = core.comparar_estructura_dom(v1b, v2b, umbral_pixeles=3, comparar_estilos=False)
    assert len(fallas_b) == 1, "15px de diferencia real (scrollbar sin fix) debe seguir detectándose para poder aplicar el fix de overflow:hidden"
    print("OK: tolerancia absorbe subpíxeles de layout sin ocultar diferencias reales mayores")


def test_confirmacion_visual_degrada_falsos_positivos():
    """
    Simula el caso 'el DOM dice que cambió pero visualmente es idéntico':
    dos imágenes idénticas -> diferencia visual ~0 -> debe degradar a
    'informativo' aunque el DOM haya detectado un cambio de ALTURA.
    """
    import numpy as np
    img_v1 = np.zeros((200, 200, 3), dtype='uint8')
    img_v2 = img_v1.copy()  # exactamente igual

    falla = core._falla('div.card', 'DIFERENCIA ALTURA (H)', 10, 100, 110,
                          coords_v2={'x': 0, 'y': 0, 'width': 50, 'height': 50},
                          coords_v1={'x': 0, 'y': 0, 'width': 50, 'height': 50},
                          order_index=0)
    fallas = core.confirmar_visualmente(img_v1, img_v2, [falla])
    assert fallas[0].get('degradado_por_visual') is True

    consolidado = core.consolidar_fallas(fallas)
    assert consolidado[0]['gravedad'] == 'informativo', consolidado

    # Control: si las imágenes SÍ difieren en esa región, debe seguir grave.
    img_v2_distinta = img_v1.copy()
    img_v2_distinta[0:50, 0:50] = 255
    falla2 = core._falla('div.card2', 'DIFERENCIA ALTURA (H)', 10, 100, 110,
                           coords_v2={'x': 0, 'y': 0, 'width': 50, 'height': 50},
                           coords_v1={'x': 0, 'y': 0, 'width': 50, 'height': 50},
                           order_index=0)
    fallas2 = core.confirmar_visualmente(img_v1, img_v2_distinta, [falla2])
    consolidado2 = core.consolidar_fallas(fallas2)
    assert consolidado2[0]['gravedad'] == 'grave', consolidado2
    print("OK: confirmación visual degrada falsos positivos y mantiene fallas visualmente reales")


def test_ausente_y_nuevo_siguen_siendo_graves():
    """Control: un elemento realmente ausente (no matchea por fingerprint
    NI por fallback) debe seguir marcándose grave, sin degradar de más."""
    v1 = [item('div', 'div:nth-child(1)', 0, 0, 300, 100, class_attr='promo-especial', texto='Promo única')]
    v2 = []
    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=False)
    consolidado = core.consolidar_fallas(fallas)
    assert len(consolidado) == 1
    assert consolidado[0]['gravedad'] == 'grave'
    print("OK: un elemento realmente ausente sigue clasificado como grave")


def test_listado_con_noticias_distintas_no_reporta_geometria():
    """
    Caso real (v719, "Listado"/últimas-noticias, mobile): las tarjetas son
    <article class="card"> con el título en un <h2> anidado -> texto propio
    vacío -> fingerprint = solo 'article.card', igual para las 3 tarjetas.
    Entre la captura de V1 y la de V2 el listado (que se actualiza en vivo)
    mostró OTRAS noticias en esos mismos lugares. Antes del fix esto se
    reportaba como que la tarjeta "cambió" de tamaño/posición; en realidad
    son dos noticias distintas y no hay nada que comparar geométricamente.
    """
    v1 = [
        item('article', 'article:nth-child(1)', 0, 0, 300, 120, class_attr='card',
             texto_subtree='Noticia A: se cayó un avión', order_index=0),
        item('article', 'article:nth-child(2)', 0, 120, 300, 120, class_attr='card',
             texto_subtree='Noticia B: sube el dólar', order_index=1),
    ]
    v2 = [
        item('article', 'article:nth-child(1)', 0, 0, 300, 150, class_attr='card',
             texto_subtree='Noticia C: nuevo escandalo politico', order_index=0),
        item('article', 'article:nth-child(2)', 0, 150, 300, 95, class_attr='card',
             texto_subtree='Noticia D: resultado de futbol', order_index=1),
    ]
    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=True)
    assert fallas == [], f"no debería reportar nada, son noticias distintas: {fallas}"
    print("OK: tarjetas de listado con noticias distintas no generan fallas de geometría/estilo")


def test_carrusel_de_imagenes_reordenado_no_reporta_geometria():
    """
    Caso real (Homepage v719 mobile): un carrusel de tarjetas "destacadas"
    (imagen grande + poco/nada de texto propio o anidado) se reordenó entre
    la captura de V1 y la de V2 -> dos tarjetas literalmente intercambiaron
    tamaño (una pasó de 675px a 219px de alto y la otra al revés), y sin
    señal de texto (texto_subtree vacío en ambas) se reportaban como
    cambios de layout reales. La imagen (img_src) es la señal que falta.
    """
    v1 = [
        item('div', 'div:nth-child(38) > div > div', 0, 100, 300, 675,
             img_src='/img/nota-colapinto.jpg', order_index=0),
        item('div', 'div:nth-child(39) > div > div', 0, 775, 300, 219,
             img_src='/img/nota-racing.jpg', order_index=1),
    ]
    # V2: se reordenó el carrusel -> la tarjeta grande ahora es la de Racing
    # (era la chica) y la chica ahora es la de Colapinto (era la grande).
    v2 = [
        item('div', 'div:nth-child(38) > div > div', 0, 100, 300, 219,
             img_src='/img/nota-racing.jpg', order_index=0),
        item('div', 'div:nth-child(39) > div > div', 0, 319, 300, 675,
             img_src='/img/nota-colapinto.jpg', order_index=1),
    ]
    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=True)
    assert fallas == [], f"no debería reportar nada, son tarjetas distintas reordenadas: {fallas}"
    print("OK: carrusel de tarjetas-imagen reordenado no genera fallas de geometría/estilo")


def test_misma_imagen_que_cambia_de_tamano_si_reporta_diferencia_real():
    """Control: si es la MISMA imagen (mismo img_src) y cambia de alto, sigue
    siendo una falla real — el fix no debe volverse ciego a regresiones
    reales solo porque el elemento no tiene texto."""
    v1 = [item('div', 'div:nth-child(1)', 0, 0, 300, 200, img_src='/img/nota-x.jpg', order_index=0)]
    v2 = [item('div', 'div:nth-child(1)', 0, 0, 300, 260, img_src='/img/nota-x.jpg', order_index=0)]
    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=False)
    tipos = [f['tipo'] for f in fallas]
    assert tipos == ['DIFERENCIA ALTURA (H)'], fallas
    print("OK: la misma imagen (mismo img_src) que cambia de alto sigue siendo una falla real")


def test_modulo_de_noticias_con_texto_propio_no_reporta_ausente_nuevo_por_cada_titular():
    """
    Caso real (Homepage v719 mobile, módulo "últimas noticias" embebido,
    reportado por el usuario con captura mostrando los titulares distintos
    resaltados en rojo): a diferencia de las tarjetas de Listado (título
    anidado, texto propio vacío), acá el titular ES el texto propio del
    elemento -> el fingerprint (que incluye texto) ya es distinto de
    entrada entre una noticia y otra, así que NUNCA llegan a compararse
    como "el mismo elemento que cambió" — la vieja queda suelta como
    AUSENTE V2 y la nueva suelta como NUEVO EN V2, aunque ocupen el mismo
    lugar en el módulo. Deben quedar emparejadas por posición dentro del
    mismo padre y descartadas (mismo criterio de contenido distinto).
    """
    v1 = [
        item('a', 'div.modulo-noticias > a:nth-child(1)', 0, 0, 300, 60,
             texto='Un jugador de Racing se lesionó a horas del partido...', order_index=0),
        item('a', 'div.modulo-noticias > a:nth-child(2)', 0, 60, 300, 60,
             texto='George Russell salió en apoyo de Franco Colapinto...', order_index=1),
        item('a', 'div.modulo-noticias > a:nth-child(3)', 0, 120, 300, 60,
             texto='El secretario de Defensa británico dijo que...', order_index=2),
    ]
    # V2: entró 1 noticia nueva arriba (mismo lugar que "Racing", que cayó
    # del feed), las otras 2 son las mismas de siempre -> matchean normal
    # por fingerprint y solo se corren de posición.
    v2 = [
        item('a', 'div.modulo-noticias > a:nth-child(1)', 0, 0, 300, 90,
             texto='Benjamín Vicuña apuntó contra la China Suárez...', order_index=0),
        item('a', 'div.modulo-noticias > a:nth-child(2)', 0, 90, 300, 60,
             texto='George Russell salió en apoyo de Franco Colapinto...', order_index=1),
        item('a', 'div.modulo-noticias > a:nth-child(3)', 0, 150, 300, 60,
             texto='El secretario de Defensa británico dijo que...', order_index=2),
    ]
    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=True)
    tipos = [f['tipo'] for f in fallas]
    assert 'AUSENTE V2' not in tipos and 'NUEVO EN V2' not in tipos, fallas
    print("OK: módulo de noticias con texto propio no genera AUSENTE/NUEVO por cada titular que rotó")


def test_listado_con_desparejo_de_cantidad_no_fuerza_emparejamiento_por_padre():
    """
    Regresión real (v719, commit 332065b): la tercera pasada de
    emparejar_elementos (agrupar leftovers por selector del padre) rompió
    Listado, que ya estaba en 0 graves gracias al fix de
    _identidad_es_debil/_contenido_distinto. Causa: Listado tiene tarjetas
    de identidad DÉBIL (article.card con título anidado, texto propio
    vacío) y el listado se actualiza en vivo, así que V1 y V2 pueden tener
    distinta CANTIDAD de tarjetas bajo el mismo padre (p. ej. entraron 2
    noticias nuevas). Las tarjetas que sobran del emparejamiento por
    fingerprint (pasada 1) quedan en solo_v1/solo_v2 -- ese desparejo de
    cantidad es a propósito fuera de alcance (AUSENTE V2 / NUEVO EN V2).
    Si la tercera pasada las vuelve a emparejar por posición dentro del
    padre, dos tarjetas de noticias completamente distintas terminan
    comparadas geométricamente y, si no hay señal de texto/imagen para
    descartarlas, se reportan como GRAVE de posición/ancho falsos -- que es
    exactamente lo que pasó en producción.
    """
    padre = 'div#fusion-app > div:nth-child(7) > main > div:nth-child(7) > div'
    v1 = [
        item('article', f'{padre} > article:nth-child(1)', 0, 0, 300, 120,
             class_attr='card', texto_subtree='Noticia A: se cayó un avión', order_index=0),
        item('article', f'{padre} > article:nth-child(2)', 0, 120, 300, 120,
             class_attr='card', texto_subtree='Noticia B: sube el dólar', order_index=1),
    ]
    # V2: entraron 2 noticias nuevas arriba del listado (se actualizó en
    # vivo) -> 4 tarjetas en vez de 2, todas bajo el mismo padre exacto, y
    # las 2 que ya estaban (B y A) se corrieron de posición/tamaño (efecto
    # secundario normal de que se sumaron tarjetas arriba, no un bug).
    v2 = [
        item('article', f'{padre} > article:nth-child(1)', 0, 0, 300, 90,
             class_attr='card', texto_subtree='Noticia C: nuevo escandalo politico', order_index=0),
        item('article', f'{padre} > article:nth-child(2)', 0, 90, 300, 140,
             class_attr='card', texto_subtree='Noticia D: resultado de futbol', order_index=1),
        item('article', f'{padre} > article:nth-child(3)', 0, 230, 300, 120,
             class_attr='card', texto_subtree='Noticia A: se cayó un avión', order_index=2),
        item('article', f'{padre} > article:nth-child(4)', 0, 350, 300, 120,
             class_attr='card', texto_subtree='Noticia B: sube el dólar', order_index=3),
    ]
    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=False)
    tipos = [f['tipo'] for f in fallas]
    graves_geometria = [t for t in tipos if t not in ('AUSENTE V2', 'NUEVO EN V2')]
    assert graves_geometria == [], (
        f"no debería forzar comparación geométrica entre tarjetas de identidad "
        f"débil desparejadas en cantidad: {fallas}"
    )
    print("OK: desparejo de cantidad en tarjetas de identidad débil no fuerza comparación geométrica falsa")


def test_misma_tarjeta_con_mismo_contenido_si_reporta_diferencia_real():
    """
    Control: si el contenido (texto de subárbol) es el MISMO en V1 y V2,
    sigue siendo la misma tarjeta -> un cambio real de alto (ej: un bug de
    CSS) debe seguir reportándose como antes."""
    v1 = [item('article', 'article:nth-child(1)', 0, 0, 300, 120, class_attr='card',
                texto_subtree='Noticia A: se cayó un avión', order_index=0)]
    v2 = [item('article', 'article:nth-child(1)', 0, 0, 300, 180, class_attr='card',
                texto_subtree='Noticia A: se cayó un avión', order_index=0)]
    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=False)
    tipos = [f['tipo'] for f in fallas]
    assert tipos == ['DIFERENCIA ALTURA (H)'], fallas
    print("OK: misma noticia (mismo texto real) que cambia de alto sigue siendo una falla real")


def test_cascada_calcula_rango_completo_para_dibujar_en_la_imagen():
    """
    Pedido del usuario: el recuadro de la cascada en la imagen debe marcar
    TODO lo que abarca (desde el primer hasta el último elemento afectado),
    no solo el elemento "causa raíz". agrupar_cascadas debe calcular ese
    bounding box (coords_rango_v2) a partir de los coords_v2 de TODOS los
    elementos del cluster.
    """
    v1 = [item('div', f'div:nth-child({i})', 0, i * 100, 300, 100,
                class_attr=f'block-{i}', texto=f'contenido {i}', order_index=i)
          for i in range(1, 8)]
    v2 = [item('div', f'div:nth-child({i})', 0, i * 100 + 350, 300, 100,
                class_attr=f'block-{i}', texto=f'contenido {i}', order_index=i)
          for i in range(1, 8)]
    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=False)
    _, cascadas = core.agrupar_cascadas(fallas)
    assert len(cascadas) == 1
    rango = cascadas[0]['coords_rango_v2']
    # El primer elemento cambiado es i=1 (v2 y=450), el último i=7 (v2 y=1050+100=1150)
    assert rango['y'] == 450, rango
    assert rango['y'] + rango['height'] == 1150, rango
    assert rango['x'] == 0 and rango['width'] == 300, rango
    print("OK: la cascada calcula el rango completo (bounding box de todos sus elementos) para dibujar en la imagen")


def test_ad_slot_contenedor_no_reporta_por_rotacion_normal_de_creatividad():
    """
    Pedido del usuario: en vez de excluir los ad-slots por completo (fix #3/
    histórico), ahora el CONTENEDOR/slot del ad sí se compara -- pero su
    contenido interno (la creatividad, en un <iframe> de otro origen que no
    se puede inspeccionar por CORS) se sigue ignorando vía la señal
    iframe_src: si el iframe de adentro cambió de src (rotó de creativo,
    lo normal en cualquier corrida real, incluso con tamaño distinto), no
    debe reportarse nada.
    """
    v1 = [item('div', 'div.ad-slot-caja', 0, 500, 300, 250, class_attr='ad-slot-caja',
                iframe_src='https://ads.example.com/serve?id=AAA111', order_index=0)]
    v2 = [item('div', 'div.ad-slot-caja', 0, 500, 300, 600, class_attr='ad-slot-caja',
                iframe_src='https://ads.example.com/serve?id=ZZZ999', order_index=0)]
    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=False)
    assert fallas == [], f"la rotación normal de la creatividad del ad no debería reportar nada: {fallas}"
    print("OK: contenedor de ad-slot no reporta cambio de tamaño explicado por rotación normal de creatividad")


def test_ad_slot_contenedor_si_reporta_cambio_de_tamano_con_mismo_creativo():
    """
    Control: si el MISMO iframe (mismo src, no rotó) queda en un contenedor
    de otro tamaño, es un bug real de integración (el slot no está
    reservando el espacio que el creativo necesita) y se debe seguir
    reportando -- a diferencia de antes, cuando el ad-slot se excluía
    completo y esto era invisible para la herramienta.
    """
    v1 = [item('div', 'div.ad-slot-caja', 0, 500, 300, 250, class_attr='ad-slot-caja',
                iframe_src='https://ads.example.com/serve?id=AAA111', order_index=0)]
    v2 = [item('div', 'div.ad-slot-caja', 0, 500, 300, 600, class_attr='ad-slot-caja',
                iframe_src='https://ads.example.com/serve?id=AAA111', order_index=0)]
    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=False)
    tipos = [f['tipo'] for f in fallas]
    assert 'DIFERENCIA ALTURA (H)' in tipos, (
        f"un cambio de tamaño del slot con el MISMO creativo adentro es un bug real "
        f"de integración y debería reportarse: {fallas}"
    )
    print("OK: contenedor de ad-slot con el mismo creativo adentro sigue reportando cambios reales de tamaño")


def test_renderer_interno_del_ad_sigue_excluido():
    """El renderer interno (google_ads_iframe, dfp-ad, aniBox) sigue
    completamente excluido -- ya lo cubre (con contenido ignorado) el
    contenedor/slot que lo envuelve, no aporta nada compararlo aparte."""
    v1 = [
        item('div', 'div.ad-slot-caja', 0, 500, 300, 250, class_attr='ad-slot-caja', order_index=0),
        item('div', 'div.ad-slot-caja > div#google_ads_iframe-1', 10, 510, 280, 230,
             id_attr='google_ads_iframe-1', order_index=1),
    ]
    v2 = [
        item('div', 'div.ad-slot-caja', 0, 500, 300, 250, class_attr='ad-slot-caja', order_index=0),
        item('div', 'div.ad-slot-caja > div#google_ads_iframe-2', 10, 510, 250, 200,
             id_attr='google_ads_iframe-2', order_index=1),
    ]
    fallas = core.comparar_estructura_dom(v1, v2, umbral_pixeles=3, comparar_estilos=False)
    assert fallas == [], f"el renderer interno del ad debería seguir excluido: {fallas}"
    print("OK: el renderer interno del ad (google_ads_iframe/dfp-ad/aniBox) sigue excluido de la comparación")


if __name__ == '__main__':
    tests = [v for k, v in list(globals().items()) if k.startswith('test_')]
    fallidos = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            fallidos += 1
            print(f"FALLÓ: {t.__name__}: {e}")
        except Exception as e:
            fallidos += 1
            print(f"ERROR: {t.__name__}: {e!r}")
    print(f"\n{len(tests) - fallidos}/{len(tests)} tests OK")
    if fallidos:
        raise SystemExit(1)
