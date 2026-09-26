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
         data_attrs='', order_index=0):
    return {
        'tag': tag, 'selector': selector, 'x': x, 'y': y, 'width': w, 'height': h,
        'id_attr': id_attr, 'class_attr': class_attr, 'texto': texto,
        'styles': styles or {}, 'data_attrs': data_attrs, 'order_index': order_index,
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
