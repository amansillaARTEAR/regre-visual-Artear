#!/usr/bin/env python3
"""
regre_visual_motor.py
======================
Motor genérico (product-agnostic) de regresión visual/estructural,
usado por regre_visual_tn.py, regre_visual_eltrece.py,
regre_visual_eldoce.py y regre_visual_ciudad.py.

Cada script de producto solo define su propio BASE_URLS_MAP (y el
dominio/nombre del producto) y llama a `main(...)` de este módulo. Toda
la lógica de extracción DOM, comparación, agrupación de cascadas,
marcado visual y reporte HTML vive acá, una sola vez, para que un fix
aplicado a un producto (ej. tolerancia de píxeles, exclusión de ads,
confirmación visual) beneficie a los cuatro sin duplicar código.

Uso (desde un script de producto):
    python regre_visual_tn.py --modo desktop 719
    python regre_visual_eltrece.py --modo mobile 719 --urls Homepage,Listado
    python regre_visual_eldoce.py --modo desktop 719 --tolerancia 4 --sin-confirmacion-visual

Qué resuelve este motor respecto a los scripts originales por producto
(cada uno tenía su propia copia de esta lógica, con fixes aplicados en
unos y no en otros — p.ej. TN webmobile/desktop duplicados, y El Trece/
El Doce/Ciudad con una versión mucho más simple, sin tolerancia de
píxeles, sin agrupación de cascadas ni confirmación visual):
  1. Un solo script parametrizable (antes: dos scripts duplicados, con
     fixes aplicados en uno y no en el otro — p.ej. overflow:hidden solo
     estaba en webmobile).
  2. Tolerancia de píxeles real (antes: 0, cualquier subpíxel fallaba).
  3. Reintentos automáticos ante timeout/red antes de marcar FATAL ERROR.
  4. Masking real de ads/terceros (Teads, google_ads_iframe, etc.):
     se EXCLUYEN de la comparación, no solo se ocultan para limpiar popups.
  5. Identidad de elemento por fingerprint (tag+clases+texto), no
     nth-child puro: insertar/mover un elemento ya no rompe la
     identidad de todos los que están después.
  6. Normalización de estilos (color rgb/rgba, font-weight, font-family)
     para no marcar como falla lo que es solo FOUT/redondeo del navegador.
  7. Agrupación por causa raíz: un desplazamiento en cascada (un ad que
     cambió de alto arrastrando 30 elementos debajo) se reporta como
     UN hallazgo, no 30.
  8. Confirmación visual: antes de marcar "grave" una diferencia de
     tamaño/posición, se recorta esa región en V1 y V2 y se compara
     visualmente; si es idéntica, se degrada a "informativo".

La lógica de comparación pura vive en regre_visual_tn_core.py (testeada
en test_core.py sin necesidad de Selenium/red).
"""

import os
import io
import re
import sys
import time
import argparse
import datetime
from collections import defaultdict
from html import escape as esc

from PIL import Image

import regre_visual_tn_core as core

# =====================================================================
# CONFIGURACIÓN POR MODO
# =====================================================================

def config_modos(output_dir_base):
    """Devuelve la config desktop/mobile con el output_dir anclado a la
    carpeta del producto (ej. reportes/eltrece/desktop), para que los
    reportes de los distintos productos no se pisen entre sí."""
    return {
        'desktop': {
            'output_dir': os.path.join(output_dir_base, 'desktop'),
            'window_size': (1920, 1080),
            'user_agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                            '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'),
            'bloquear_imagenes': False,
            'ancho_referencia_js': 1920,
            'page_load_timeout': 90,
        },
        'mobile': {
            'output_dir': os.path.join(output_dir_base, 'mobile'),
            'window_size': (412, 892),
            'user_agent': ('Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 '
                            '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'),
            'bloquear_imagenes': True,
            'ancho_referencia_js': 412,
            'page_load_timeout': 240,
        },
    }


# Dominios de terceros a bloquear a nivel de red (además del masking a
# nivel de comparación DOM). Bloquearlos de raíz reduce aún más la
# variabilidad entre corridas V1/V2.
DOMINIOS_BLOQUEADOS = [
    "*google-analytics.com*", "*googlesyndication.com*",
    "*googletagservices.com*", "*googleadservices.com*",
    "*doubleclick.net*", "*adnxs.com*", "*taboola.com*",
    "*outbrain.com*", "*facebook.net*", "*scorecardresearch.com*",
    "*.amazon-adsystem.com*", "*.ads-twitter.com*",
]

REINTENTOS_MAX = 2  # intentos totales por URL (1 original + 1 reintento)


# =====================================================================
# UTILIDADES
# =====================================================================

def format_time(seconds):
    try:
        return str(datetime.timedelta(seconds=int(seconds)))
    except (ValueError, TypeError):
        return "00:00:00"


def format_date(timestamp):
    try:
        dt_object = datetime.datetime.strptime(timestamp.split('_')[0], "%Y%m%d")
        return dt_object.strftime("%d/%m/%Y")
    except ValueError:
        return timestamp.split('_')[0]


def ejecutar_js_manipulacion(driver, script):
    try:
        driver.execute_script(script)
    except Exception:
        pass


# =====================================================================
# LIMPIEZA DE POPUPS (se mantiene: cookies/suscripciones SÍ se eliminan
# del layout porque son intervenciones nuestras, no contenido dinámico
# del sitio; el masking de ads/terceros va aparte, a nivel de comparación)
# =====================================================================

JS_ELIMINAR_POPUPS = """
    // FIX SCROLLBAR (antes solo estaba en el script mobile)
    document.documentElement.style.overflow = 'hidden';
    document.body.style.overflow = 'hidden';

    var btn_close = document.querySelector('button.onetrust-close-btn-handler'); if (btn_close) { btn_close.click(); }
    var os_cancel = document.getElementById('onesignal-slidedown-cancel-button'); if (os_cancel) { os_cancel.click(); }

    var os_container = document.getElementById('onesignal-slidedown-container'); if (os_container) { os_container.remove(); }
    var alert_news = document.getElementById('alertNews'); if (alert_news) { alert_news.remove(); }
    var cookie_modal = document.getElementById('onetrust-consent-sdk'); if (cookie_modal) { cookie_modal.remove(); }

    var subscribe_modal_content = document.querySelector('.modal-content-subscribe');
    if (subscribe_modal_content) { subscribe_modal_content.remove(); }
    var modal_overlay = document.querySelector('.modal-backdrop');
    if (modal_overlay) { modal_overlay.remove(); }

    var high_z_index_items = document.querySelectorAll('*[style*="z-index"]:not(body):not(html)');
    high_z_index_items.forEach(function(el) {
        var style = window.getComputedStyle(el);
        if (parseInt(style.zIndex) > 1000 || el.classList.contains('popup')) {
            el.style.display = 'none';
        }
    });

    document.body.style.overflowX = 'hidden';
    document.body.style.maxWidth = '100vw';
"""


def limpiar_entorno(driver):
    ejecutar_js_manipulacion(driver, JS_ELIMINAR_POPUPS)


def forzar_carga_contenido(driver, espera_scroll=2):
    """Scrolls para forzar lazy-loading. Antes: sleeps fijos de 10-15s en
    desktop (rígido: mucho si la red va rápido, poco si va lenta). Se
    mantiene un sleep corto porque medir 'estabilidad del DOM' de forma
    100% basada en eventos requeriría instrumentar cada componente lazy
    del sitio; este es un punto a seguir afinando con datos reales."""
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(espera_scroll)
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(espera_scroll)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
    time.sleep(espera_scroll)
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(espera_scroll)


# =====================================================================
# EXTRACCIÓN DEL DOM (con fingerprint: tag, clases, data-*, texto)
# =====================================================================

JS_EXTRACCION = """
    function getCssSelector(el) {
        if (!(el instanceof Element)) return;
        var path = [];
        while (el.nodeType === Node.ELEMENT_NODE) {
            var selector = el.tagName.toLowerCase();
            if (el.id) {
                selector += '#' + el.id;
                path.unshift(selector);
                break;
            } else {
                var sib = el, nth = 1;
                while (sib = sib.previousElementSibling) {
                    if (sib.tagName.toLowerCase() == selector) nth++;
                }
                if (nth != 1) selector += ":nth-child(" + nth + ")";
            }
            path.unshift(selector);
            el = el.parentNode;
        }
        return path.join(' > ');
    }

    function getDataAttrs(el) {
        var out = [];
        for (var i = 0; i < el.attributes.length; i++) {
            var attr = el.attributes[i];
            if (attr.name.indexOf('data-') === 0 && attr.name.indexOf('data-react') !== 0) {
                out.push(attr.name + '=' + attr.value);
            }
        }
        return out.sort().join(';');
    }

    var selectorTags = INCLUIR_TEXTO ?
        'div, h1, h2, h3, h4, h5, h6, p, span, a, button, label, li, article' :
        'div, article';
    var elements = document.querySelectorAll(selectorTags);
    var data = [];
    var orderIndex = 0;

    for (var i = 0; i < elements.length; i++) {
        var el = elements[i];
        var rect = el.getBoundingClientRect();
        var compStyle = window.getComputedStyle(el);

        if (rect.height < 3 || rect.width < 3 || compStyle.display === 'none' || compStyle.visibility === 'hidden') continue;

        if (el.classList && (
            el.classList.contains('fusion-app') ||
            el.classList.contains('common-layout') ||
            el.classList.contains('col-megalateral') ||
            el.classList.contains('default-article-color') ||
            el.classList.contains('col-content')
        )) continue;

        var texto = '';
        for (var c = 0; c < el.childNodes.length; c++) {
            if (el.childNodes[c].nodeType === Node.TEXT_NODE) {
                texto += el.childNodes[c].textContent;
            }
        }
        texto = texto.trim().slice(0, 60);

        // Texto de todo el subárbol (no solo hijos de texto directos), para
        // detectar contenido real distinto en wrappers de tarjetas cuyo
        // título/texto está anidado (ej: <article> con un <h2> adentro, que
        // por eso tiene texto propio vacío). Se usa SOLO para decidir si dos
        // elementos emparejados por posición son en verdad "la misma tarjeta"
        // o dos noticias distintas de un listado que se actualiza en vivo —
        // no forma parte del fingerprint de identidad.
        var textoSubtree = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 80);

        // Identidad visual del subárbol: muchas tarjetas de un carrusel/grilla
        // "destacados"/"recomendados" son solo una imagen + poco o nada de
        // texto propio (el título puede estar como atributo alt, o directamente
        // no haber texto visible). texto_subtree solo no alcanza para detectar
        // que son tarjetas distintas ahí -> se usa además la URL de la imagen
        // (primer <img> del subárbol, o el background-image del propio
        // elemento) como señal de contenido. Caso real (Homepage v719): un
        // carrusel reordenó sus tarjetas entre la captura de V1 y la de V2 y
        // se reportaron ~10 cambios de tamaño/posición "GRAVE" que en
        // realidad eran la misma tarjeta en otro lugar + otra tarjeta ocupando
        // su lugar viejo, no un cambio real de layout.
        var imgSrc = '';
        var imgEl = el.querySelector('img');
        if (imgEl) {
            imgSrc = imgEl.currentSrc || imgEl.getAttribute('src') || '';
        }
        if (!imgSrc) {
            var bg = compStyle.backgroundImage;
            if (bg && bg !== 'none') imgSrc = bg;
        }
        // Solo el path (sin query params de cache-busting/resize) para que no
        // cuente como "distinta" la misma imagen servida con otro tamaño.
        imgSrc = imgSrc.split('?')[0].slice(-120);

        // Señal de contenido para contenedores de ads (ad-slot, banner-container,
        // etc.): la creatividad se renderiza en un <iframe> de otro origen, así
        // que no se puede leer texto/imagen de ADENTRO (bloqueado por CORS),
        // pero el atributo src/id/name del iframe SÍ es legible desde el padre
        // y cambia en cada request de ad -> sirve para saber "rotó de creativo"
        // sin poder ver el contenido. A diferencia de imgSrc, acá NO se recorta
        // el query string: en URLs de ad servers casi todo lo distintivo está
        // en los parámetros, no en el path.
        var iframeSrc = '';
        var iframeEl = el.querySelector('iframe');
        if (iframeEl) {
            iframeSrc = iframeEl.getAttribute('src') || iframeEl.getAttribute('id') || iframeEl.getAttribute('name') || '';
        }
        iframeSrc = iframeSrc.slice(-200);

        data.push({
            tag: el.tagName.toLowerCase(),
            selector: getCssSelector(el),
            id_attr: el.id,
            class_attr: el.className,
            data_attrs: getDataAttrs(el),
            texto: texto,
            texto_subtree: textoSubtree,
            img_src: imgSrc,
            iframe_src: iframeSrc,
            order_index: orderIndex++,
            y: window.pageYOffset + rect.top,
            height: rect.height,
            x: window.pageXOffset + rect.left,
            width: rect.width,
            styles: {
                color: compStyle.color,
                bgColor: compStyle.backgroundColor,
                fontSize: compStyle.fontSize,
                fontWeight: compStyle.fontWeight,
                fontFamily: compStyle.fontFamily,
                textAlign: compStyle.textAlign,
                marginTop: compStyle.marginTop,
                marginRight: compStyle.marginRight,
                marginBottom: compStyle.marginBottom,
                marginLeft: compStyle.marginLeft,
                paddingTop: compStyle.paddingTop,
                paddingRight: compStyle.paddingRight,
                paddingBottom: compStyle.paddingBottom,
                paddingLeft: compStyle.paddingLeft
            }
        });
    }
    return { dpr: window.devicePixelRatio || 1, elements: data };
"""


def esperar_fuentes(driver, timeout=5):
    """
    Espera a que las tipografías web (WOFF/WOFF2 custom del sitio) terminen
    de cargar (Promise `document.fonts.ready`), best-effort con timeout corto.

    Sin esto: si la captura de V1 (o V2) ocurre antes de que la fuente
    custom termine de cargar, el navegador renderiza ese texto con la
    fuente de fallback -> las métricas (ancho de carácter, alto de línea)
    son distintas aunque el CSS `font-size` en px sea IDÉNTICO entre V1 y
    V2. Resultado: un título se ve visiblemente más grande/chico en la
    captura, pero `getComputedStyle().fontSize` no cambió -> la comparación
    de estilos no lo detecta como diferencia (fix #19, reportado por el
    usuario viendo un título con fuente visualmente más grande en Homepage
    desktop v719 que no generó ningún hallazgo de ESTILO/FONTSIZE).
    """
    try:
        driver.set_script_timeout(timeout)
        driver.execute_async_script(
            "var cb = arguments[arguments.length - 1];"
            "if (!window.document.fonts) { cb(); return; }"
            "document.fonts.ready.then(function () { cb(); }).catch(function () { cb(); });"
        )
    except Exception:
        pass  # no bloqueamos la corrida por esto; es una mejora best-effort


def obtener_estructura_dom(driver, incluir_texto=True, espera_scroll=2):
    """Devuelve (data, png) para la URL actualmente cargada en el driver."""
    from selenium.webdriver.support.ui import WebDriverWait

    data, png = [], None
    try:
        WebDriverWait(driver, 20).until(lambda d: d.execute_script("return document.readyState") == "complete")
        esperar_fuentes(driver)

        limpiar_entorno(driver)
        time.sleep(1)
        limpiar_entorno(driver)
        forzar_carga_contenido(driver, espera_scroll=espera_scroll)

        total_height = driver.execute_script(
            "return Math.max(document.body.scrollHeight, document.body.offsetHeight, "
            "document.documentElement.clientHeight, document.documentElement.scrollHeight, "
            "document.documentElement.offsetHeight);"
        )
        original_size = driver.get_window_size()
        driver.set_window_size(original_size['width'], total_height)
        time.sleep(1)
        esperar_fuentes(driver)  # el resize puede revelar contenido lazy-loaded con su propia fuente

        js = JS_EXTRACCION.replace('INCLUIR_TEXTO', 'true' if incluir_texto else 'false')
        result = driver.execute_script(js)
        data = result.get('elements', [])

        png = driver.get_screenshot_as_png()
        driver.set_window_size(original_size['width'], original_size['height'])

    except Exception as e:
        print(f"     ❌ Error en la extracción/captura: {e}")
        data = [{'selector': 'FATAL ERROR'}]

    return data, png


def ejecutar_selenium_para_estructura(url, modo, config):
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    options = webdriver.ChromeOptions()
    if config['bloquear_imagenes']:
        options.add_experimental_option("prefs", {"profile.managed_default_content_settings.images": 1})

    # 'eager' = driver.get() vuelve apenas el DOM está listo (DOMContentLoaded),
    # sin esperar a que TERMINEN de cargar ads/trackers/iframes de terceros.
    # Antes (estrategia 'normal', default): en desktop, sin bloqueo de dominios
    # de ads, la home de TN no siempre llega a "load" completo dentro del
    # page_load_timeout -> Selenium tira "Timed out receiving message from
    # renderer". Con 'eager' evitamos depender de que esos recursos lentos
    # terminen; el WebDriverWait posterior sobre document.readyState y los
    # scrolls de forzar_carga_contenido igual dan tiempo a que lo importante
    # (el layout real) se asiente antes de medir.
    options.page_load_strategy = 'eager'

    w, h = config['window_size']
    options.add_argument("--headless=new")
    options.add_argument(f"--window-size={w},{h}")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--log-level=3")
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    options.add_argument(f"--user-agent={config['user_agent']}")
    options.add_argument("--disable-features=site-per-process")

    driver = None
    data, png = [], None
    try:
        os.environ['WDM_LOG_LEVEL'] = '0'
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

        # Antes: el bloqueo de dominios de ads/trackers via CDP solo estaba en
        # mobile (copiado del script viejo). Eso dejaba a desktop cargando
        # TODOS los ads sin filtrar, más lento y con más chance de timeout
        # en un runner compartido de CI. Ahora se aplica en los dos modos.
        driver.execute_cdp_cmd('Network.enable', {})
        driver.execute_cdp_cmd('Network.setBlockedURLs', {"urls": DOMINIOS_BLOQUEADOS})

        driver.set_page_load_timeout(config['page_load_timeout'])
        driver.get(url)

        # Antes: incluir_texto=(modo == 'mobile') -> desktop solo extraía
        # div/article, nunca h1-h6/p/span/a/button/label/li. Remanente de
        # cuando se unificaron los dos scripts viejos (commit 920c068):
        # el desktop original solo comparaba contenedores. Efecto real
        # descubierto en v719 (fix #22): un <a> de titular en Homepage
        # cambió de 36px a 44px de fontSize entre V1 y V2 (confirmado a
        # mano en DevTools) y el reporte desktop no lo detectó -> no es que
        # el estilo comparara igual, es que ese <a> nunca se extraía en
        # desktop, así que ni pasaba por emparejamiento ni por comparación
        # de estilos. Ahora ambos modos extraen los mismos tags.
        data, png = obtener_estructura_dom(driver, incluir_texto=True)

    except Exception as e:
        print(f"❌ Error al inicializar/ejecutar Selenium en {url}: {e}")
        data = [{'selector': 'FATAL ERROR'}]
    finally:
        if driver:
            driver.quit()

    return data, png


def ejecutar_con_reintentos(url, modo, config, intentos_max=REINTENTOS_MAX):
    """Antes: un timeout de red puntual marcaba FATAL ERROR sin reintentar,
    perdiendo la corrida completa de esa URL. Ahora reintenta antes de
    darse por vencido."""
    ultimo_data, ultimo_png = [], None
    for intento in range(1, intentos_max + 1):
        data, png = ejecutar_selenium_para_estructura(url, modo, config)
        es_fatal = any(isinstance(d, dict) and d.get('selector') == 'FATAL ERROR' for d in data)
        if not es_fatal:
            return data, png
        ultimo_data, ultimo_png = data, png
        if intento < intentos_max:
            print(f"     ⚠️ Intento {intento}/{intentos_max} falló para {url}, reintentando...")
            time.sleep(3)
    return ultimo_data, ultimo_png


# =====================================================================
# ORQUESTACIÓN POR URL
# =====================================================================

def procesar_url(url_description, base_url, version_number, modo, config,
                  umbral_pixeles, usar_confirmacion_visual, comparar_estilos,
                  usar_linea_base_ruido=True, confirmar_con=None):
    url1 = base_url
    url2 = f"{base_url}&d={version_number}" if '?' in base_url else f"{base_url}?d={version_number}"

    print(f"  [V1] Obteniendo datos estructurales...")
    data_v1, png_v1 = ejecutar_con_reintentos(url1, modo, config)
    print(f"  [V2] Obteniendo datos estructurales...")
    data_v2, png_v2 = ejecutar_con_reintentos(url2, modo, config)

    # Linea base de ruido: una SEGUNDA captura de V1 (despues de V2, asi encierra
    # el mismo intervalo de tiempo). Lo que cambia entre V1 y V1' es contenido
    # vivo (noticias, cotizaciones, ads) y no puede atribuirse a la version nueva.
    data_v1b = None
    if usar_linea_base_ruido:
        print("  [V1'] Obteniendo linea base de ruido...")
        data_v1b, _ = ejecutar_con_reintentos(url1, modo, config)

    info_elementos = {}
    for d in list(data_v2 or []) + list(data_v1 or []):
        if isinstance(d, dict) and d.get('selector') and d['selector'] != 'FATAL ERROR':
            clase = d.get('class_attr')
            info_elementos.setdefault(d['selector'], {
                'tag': d.get('tag', ''), 'clase': clase if isinstance(clase, str) else '',
                'texto': (d.get('texto') or d.get('texto_subtree') or '').strip()})

    es_fatal = (
        any(isinstance(d, dict) and d.get('selector') == 'FATAL ERROR' for d in data_v1) or
        any(isinstance(d, dict) and d.get('selector') == 'FATAL ERROR' for d in data_v2)
    )
    if es_fatal:
        return {
            'url1': url1, 'url2': url2, 'fatal': True,
            'consolidado': [], 'cascadas': [], 'png_v1': png_v1, 'png_v2': png_v2,
        }

    fallas = core.comparar_estructura_dom(data_v1, data_v2, umbral_pixeles=umbral_pixeles,
                                           comparar_estilos=comparar_estilos)
    descartadas_ruido = 0
    if data_v1b is not None:
        if any(isinstance(d, dict) and d.get('selector') == 'FATAL ERROR' for d in data_v1b):
            print("     ⚠️ No se pudo obtener la linea base de ruido; se reporta sin filtrarla.")
        else:
            fallas_base = core.comparar_estructura_dom(data_v1, data_v1b, umbral_pixeles=umbral_pixeles,
                                                        comparar_estilos=comparar_estilos)
            fallas, descartadas_ruido = core.filtrar_ruido(fallas, core.claves_de_ruido(fallas_base))
            print(f"     Ruido descartado (cambia solo entre dos cargas de V1): {descartadas_ruido} diferencias")
    claves_fallas = {(f['selector'], f['tipo']) for f in fallas}
    descartadas_reintento = 0
    if confirmar_con is not None:
        fallas, descartadas_reintento = core.confirmar_fallas(fallas, confirmar_con)
        print(f"     Reintento: {descartadas_reintento} diferencias no se repitieron (desfase de cache/contenido en vivo)")
    otras_fallas, cascadas = core.agrupar_cascadas(fallas)

    if usar_confirmacion_visual and png_v1 and png_v2:
        try:
            import cv2
            import numpy as np
            img_v1 = cv2.imdecode(np.frombuffer(png_v1, np.uint8), cv2.IMREAD_COLOR)
            img_v2 = cv2.imdecode(np.frombuffer(png_v2, np.uint8), cv2.IMREAD_COLOR)
            otras_fallas = core.confirmar_visualmente(img_v1, img_v2, otras_fallas)
        except ImportError:
            pass

    consolidado = core.consolidar_fallas(otras_fallas)

    return {
        'url1': url1, 'url2': url2, 'fatal': False,
        'consolidado': consolidado, 'cascadas': cascadas,
        'png_v1': png_v1, 'png_v2': png_v2,
        'ruido_descartado': descartadas_ruido,
        'claves_fallas': claves_fallas,
        'info_elementos': info_elementos,
        'reintento_descartadas': descartadas_reintento,
    }


# =====================================================================
# MARCADO VISUAL (OpenCV) — 3 colores: grave / menor / informativo
# =====================================================================

COLOR_BGR = {
    'grave': (0, 0, 255),        # rojo
    'menor': (255, 0, 0),        # azul
    'informativo': (0, 140, 255),  # naranja — degradado por confirmación visual (antes dorado, fix #26)
    'cascada': (237, 58, 124),    # violeta — desplazamiento en cascada agrupado (distinto del naranja/informativo)
}


def marcar_fallas_en_captura(png_data, consolidado, cascadas):
    import cv2
    import numpy as np

    if not png_data:
        return None

    img = cv2.imdecode(np.frombuffer(png_data, np.uint8), cv2.IMREAD_COLOR)
    height, width = img.shape[:2]

    def dibujar(coords, color_key, label=''):
        x1 = max(0, int(coords['x']))
        y1 = max(0, int(coords['y']))
        x2 = min(width - 1, int(coords['x'] + coords['width']))
        y2 = min(height - 1, int(coords['y'] + coords['height']))
        if x2 > x1 and y2 > y1:
            thickness = 5 if color_key == 'grave' else 3
            color = COLOR_BGR[color_key]
            cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness)
            if label:
                # Etiqueta (mismo número que en la lista de texto del reporte)
                # quemada al lado del recuadro, para que se entienda de un
                # vistazo qué pasó ahí sin tener que hacer click en la lista.
                font, escala, grosor_txt = cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2
                (tw, th), _ = cv2.getTextSize(label, font, escala, grosor_txt)
                pad = 4
                # Encima del recuadro si hay lugar, si no, debajo (para que
                # no se corte arriba del todo de la imagen).
                if y1 - th - 2 * pad >= 0:
                    ty2 = y1
                    ty1 = ty2 - th - 2 * pad
                else:
                    ty1 = y2
                    ty2 = ty1 + th + 2 * pad
                tx1 = x1
                tx2 = min(width - 1, tx1 + tw + 2 * pad)
                cv2.rectangle(img, (tx1, ty1), (tx2, ty2), color, -1)
                cv2.putText(img, label, (tx1 + pad, ty2 - pad), font, escala,
                            (255, 255, 255), grosor_txt, cv2.LINE_AA)

    for item in consolidado:
        dibujar(item['coords_v2'], item['gravedad'], item.get('_num', ''))
    for cascada in cascadas:
        # Cascada de ESTILO (fontSize/padding/margin) = GRAVE real (rojo),
        # no "revisar" (violeta) — a diferencia de una cascada geométrica.
        color_key = 'grave' if cascada.get('grave') else 'cascada'
        dibujar(cascada['coords_v2'], color_key, cascada.get('_num', ''))

    is_success, buffer = cv2.imencode(".png", img)
    return buffer.tobytes() if is_success else None


# =====================================================================
# REPORTE HTML
# =====================================================================

LEYENDA_HTML = """
<div style="position: sticky; top: 0; z-index: 500; background: #f7f7f7;
            padding: 10px 0 8px 0; margin: 0 -20px; border-bottom: 2px solid #ddd;
            box-shadow: 0 2px 6px rgba(0,0,0,0.08);">
  <div style="display: flex; flex-wrap: wrap; gap: 8px 24px; font-size: 0.82em;
              color: #555; padding: 0 20px;">
    <div style="flex: 1 1 220px;"><span style="color:red; font-weight:bold;">■ Rojo</span>: falla grave (elemento ausente/nuevo, o cambio de tamaño/estilo confirmado visualmente).</div>
    <div style="flex: 1 1 220px;"><span style="color:blue; font-weight:bold;">■ Azul</span>: desplazamiento menor sin cambio de tamaño.</div>
    <div style="flex: 1 1 220px;"><span style="color:#ff8c00; font-weight:bold;">■ Naranja</span>: el DOM detectó una diferencia pero la confirmación visual (crop + diff) mostró que la región es igual — probablemente un falso positivo.</div>
    <div style="flex: 1 1 220px;"><span style="color:#7c3aed; font-weight:bold;">■ Violeta</span>: desplazamiento en cascada — un solo elemento anterior cambió de tamaño y corrió a los siguientes; no son N fallas independientes.</div>
  </div>
</div>
"""


# ---------------------------------------------------------------------
# DESCRIPCIONES EN LENGUAJE CLARO (reporte)
# ---------------------------------------------------------------------
NOMBRE_ESTILO = {
    'COLOR': 'color de texto', 'BGCOLOR': 'color de fondo', 'FONTSIZE': 'tamaño de fuente',
    'FONTWEIGHT': 'grosor de fuente', 'FONTFAMILY': 'tipo de fuente', 'TEXTALIGN': 'alineación del texto',
    'MARGINTOP': 'margen superior', 'MARGINRIGHT': 'margen derecho',
    'MARGINBOTTOM': 'margen inferior', 'MARGINLEFT': 'margen izquierdo',
    'PADDINGTOP': 'relleno superior (padding)', 'PADDINGRIGHT': 'relleno derecho (padding)',
    'PADDINGBOTTOM': 'relleno inferior (padding)', 'PADDINGLEFT': 'relleno izquierdo (padding)',
}


def _num(v):
    return f"{v:.0f}" if isinstance(v, (int, float)) else str(v)


def etiqueta_elemento(selector, info):
    """Nombre legible: <tag> + texto visible, en vez del selector truncado."""
    i = (info or {}).get(selector) or {}
    tag = i.get('tag') or (selector.split('>')[-1].strip().split(':')[0].split('.')[0].split('#')[0] if selector else 'elemento')
    texto = (i.get('texto') or '').strip()
    clase = (i.get('clase') or '').split()
    partes = f"<b>&lt;{esc(tag)}&gt;</b>"
    if texto:
        partes += f" «{esc(texto[:70])}{'…' if len(texto) > 70 else ''}»"
    elif clase:
        partes += f" <span style='color:#666'>(clase: {esc(clase[0])})</span>"
    return partes


def describir_falla(f):
    """Una falla individual en lenguaje claro: que paso y con que valores."""
    tipo, v1, v2, diff = f['tipo'], f['v1'], f['v2'], f['diff']
    if tipo == 'AUSENTE V2':
        return "🔴 Está en <b>PROD</b> pero <b>falta en el VNP</b>"
    if tipo == 'NUEVO EN V2':
        return "🟢 Aparece <b>solo en el VNP</b> (no existe en PROD)"
    if tipo == 'DIFERENCIA POSICIÓN (Y)':
        sentido = 'hacia abajo' if v2 > v1 else 'hacia arriba'
        return f"Se movió <b>{_num(diff)}px {sentido}</b> (distancia desde el tope de la página: PROD {_num(v1)}px → VNP {_num(v2)}px)"
    if tipo == 'DIFERENCIA POSICIÓN (X)':
        sentido = 'hacia la derecha' if v2 > v1 else 'hacia la izquierda'
        return f"Se movió <b>{_num(diff)}px {sentido}</b> (PROD {_num(v1)}px → VNP {_num(v2)}px desde el borde izquierdo)"
    if tipo == 'DIFERENCIA ALTURA (H)':
        return f"Cambió su <b>alto</b>: PROD {_num(v1)}px → VNP {_num(v2)}px ({'+' if v2 > v1 else '−'}{_num(diff)}px)"
    if tipo == 'DIFERENCIA ANCHO (W)':
        return f"Cambió su <b>ancho</b>: PROD {_num(v1)}px → VNP {_num(v2)}px ({'+' if v2 > v1 else '−'}{_num(diff)}px)"
    if tipo.startswith('DIFERENCIA ESTILO'):
        clave = tipo.replace('DIFERENCIA ESTILO (', '').rstrip(')')
        return (f"Cambió el <b>{esc(NOMBRE_ESTILO.get(clave, clave.lower()))}</b>: "
                f"PROD <code>{esc(str(v1))}</code> → VNP <code>{esc(str(v2))}</code>")
    return f"{esc(tipo)}: PROD {esc(str(v1))} → VNP {esc(str(v2))}"


LEYENDA_REPORTE = (
    "<div style='font-size:0.85em; color:#555; background:#f6f6f6; border-radius:4px; padding:6px 10px; margin-bottom:8px;'>"
    "<b>Cómo leer esto:</b> <b>PROD</b> = la versión publicada (V1) · <b>VNP</b> = versión no publicada, la que se valida (V2). "
    "<b>G</b> = diferencia grave · <b>C</b> = varios elementos movidos por una sola causa (cascada, a revisar). "
    "Hacé click en un hallazgo para verlo resaltado en la captura.</div>"
)


def construir_html_fallas(consolidado, cascadas, data_v2_por_selector, url_id):
    info = data_v2_por_selector or {}
    html = LEYENDA_REPORTE + "<ul>"

    DESC_CASCADA = {
        'DIFERENCIA POSICIÓN (Y)': ('se movieron', 'verticalmente'),
        'DIFERENCIA POSICIÓN (X)': ('se movieron', 'horizontalmente'),
        'DIFERENCIA ALTURA (H)': ('cambiaron de alto', ''),
        'DIFERENCIA ANCHO (W)': ('cambiaron de ancho', ''),
    }

    if cascadas:
        for c in cascadas:
            es_estilo = c.get('tipo', '').startswith('DIFERENCIA ESTILO')
            es_grave = bool(c.get('grave'))
            coords = c['coords_v2']
            coords_str = f"{int(coords['x'])},{int(coords['y'])},{int(coords['width'])},{int(coords['height'])}"
            # Cascada de ESTILO (fontSize/padding/margin, fix #23) = GRAVE
            # real (rojo): a diferencia de una cascada geométrica (violeta,
            # "revisar" — suele ser efecto dominó benigno de contenido
            # dinámico), un cambio de estilo repetido SÍ es una diferencia
            # de diseño real. Se agrupa solo por legibilidad (1 hallazgo en
            # vez de N), nunca se degrada a "revisar". Pedido explícito del
            # usuario.
            color = 'red' if es_grave else '#7c3aed'
            etiqueta_color = '#dc2626' if es_grave else '#7c3aed'
            if es_estilo:
                nombre_estilo = c['tipo'].replace('DIFERENCIA ESTILO (', '').rstrip(')')
                resumen = (f"{c['cantidad']} elementos cambiaron su {nombre_estilo} "
                           f"de {c['v1']} a {c['v2']}")
                causa = (f"Causa probable: un cambio de CSS global (ej: una clase compartida) "
                         f"afectó a los {c['cantidad']} elementos por igual — no son {c['cantidad']} "
                         f"regresiones de estilo independientes, es 1 sola causa raíz "
                         f"(primer elemento afectado: <code>{c['primer_selector'][:60]}</code>). "
                         f"Es un cambio de diseño real: revisar si fue intencional antes de deployar.")
                titulo = "❌ GRAVE — cambio de estilo repetido:"
            else:
                tipo_c = c.get('tipo')
                d = c['delta_y']
                if tipo_c == 'DIFERENCIA POSICIÓN (Y)':
                    resumen = f"{c['cantidad']} elementos se movieron <b>{abs(d):.0f}px hacia {'abajo' if d > 0 else 'arriba'}</b>"
                elif tipo_c == 'DIFERENCIA POSICIÓN (X)':
                    resumen = f"{c['cantidad']} elementos se movieron <b>{abs(d):.0f}px hacia la {'derecha' if d > 0 else 'izquierda'}</b>"
                elif tipo_c == 'DIFERENCIA ALTURA (H)':
                    resumen = f"{c['cantidad']} elementos <b>{'crecieron' if d > 0 else 'se achicaron'} {abs(d):.0f}px de alto</b>"
                else:
                    resumen = f"{c['cantidad']} elementos <b>{'crecieron' if d > 0 else 'se achicaron'} {abs(d):.0f}px de ancho</b>"
                causa = (f"Es un efecto en cadena: un elemento anterior cambió y empujó al resto, así que no son "
                         f"{c['cantidad']} problemas distintos sino 1 solo. Primer elemento afectado: "
                         f"{etiqueta_elemento(c['primer_selector'], info)}. "
                         f"<br><span style='color:#888'>Ubicación: <code>{esc(c['primer_selector'])}</code></span>")
                titulo = "⚠️ Revisar — desplazamiento en cascada:"
            html += f"""
            <li class='diff-item' style='color: {color}; border-bottom: 1px dotted #ccc; padding: 5px 0; cursor: pointer;'
                onclick="highlightElement('{url_id}', '{coords_str}', this)"
                data-coords="{coords_str}">
                <span style="background:{etiqueta_color}; color:#fff; border-radius:3px; padding:1px 6px; font-size:0.8em; font-weight:bold; margin-right:6px;">{c.get('_num', '')}</span>
                <span style="font-weight: bold;">{titulo}</span>
                {resumen}
                <span style="font-size: 0.8em; color: #888;">(click para verlo resaltado en la imagen)</span>.
                <br><span style="font-size: 0.85em; color: #666;">
                {causa}
                </span>
            </li>
            """

    for item in consolidado:
        color = {'grave': 'red', 'menor': '#007bff', 'informativo': '#ff8c00'}[item['gravedad']]
        coords = item['coords_v2']
        coords_str = f"{int(coords['x'])},{int(coords['y'])},{int(coords['width'])},{int(coords['height'])}"

        detalle_lineas = []
        for f in item['fallas']:
            nota_visual = ""
            if f.get('degradado_por_visual'):
                nota_visual = " — <i>degradado: sin impacto visual confirmado</i>"
            v1_display = f"{f['v1']:.2f}" if isinstance(f['v1'], (int, float)) else str(f['v1'])
            v2_display = f"{f['v2']:.2f}" if isinstance(f['v2'], (int, float)) else str(f['v2'])
            diff_display = f"{f['diff']:.2f}px" if isinstance(f['diff'], (int, float)) else str(f['diff'])
            detalle_lineas.append(f"• {describir_falla(f)}{nota_visual}")
        detalle_consolidado = "<div style='margin-top:5px; border-left:2px solid #ccc; padding-left:5px;'>" + "<br>".join(detalle_lineas) + "</div>"

        html += f"""
        <li class='diff-item'
            style='color: {color}; border-bottom: 1px dotted #ccc; padding: 5px 0; cursor: pointer;'
            onclick="highlightElement('{url_id}', '{coords_str}', this)"
            data-coords="{coords_str}">
            <span style="background:{color}; color:#fff; border-radius:3px; padding:1px 6px; font-size:0.8em; font-weight:bold; margin-right:6px;">{item.get('_num', '')}</span>
            <span style="font-weight: bold;">Elemento:</span> {etiqueta_elemento(item['selector'], info)}
            <span style='color:{color}; font-size:0.85em;'>· {item['gravedad'].upper()}</span>
            {detalle_consolidado}
            <div style="font-size:0.8em; color:#888; margin-top:3px;">Ubicación en la página: <code>{esc(item['selector'])}</code></div>
        </li>
        """

    if not consolidado and not cascadas:
        html += "<li>✅ No se encontraron diferencias.</li>"
    html += "</ul>"
    return html


def generar_reporte(all_results, version_number, output_dir, timestamp, umbral_pixeles,
                     tiempo_total, modo, producto_nombre="Sitio"):
    html_file = os.path.join(output_dir, f"Reporte_DOM_Estructural_v{version_number}_{timestamp}.html")

    all_details_html = ""
    sites_con_grave = 0
    sites_con_cascada = 0

    for r in all_results:
        graves = [c for c in r['consolidado'] if c['gravedad'] == 'grave']
        cascadas = r.get('cascadas') or []
        # Las cascadas de ESTILO (fontSize/padding/margin, fix #23) son
        # GRAVES reales (rojo) aunque se agrupen para legibilidad — a
        # diferencia de las cascadas geométricas (Y/X/H/W), que quedan como
        # "revisar" (naranja/violeta) porque suelen ser efecto dominó
        # benigno de contenido dinámico. Pedido explícito del usuario.
        cascadas_grave = [c for c in cascadas if c.get('grave')]
        cascadas_revisar = [c for c in cascadas if not c.get('grave')]
        total_graves = len(graves) + len(cascadas_grave)

        # Etiqueta numerada compartida entre la imagen (marcar_fallas_en_captura,
        # que dibuja esta misma etiqueta al lado del recuadro) y la lista de
        # texto (construir_html_fallas): así el usuario ve "G1" pintado sobre
        # la captura y puede ir directo a leer "G1" en el detalle, sin tener
        # que clickear cada hallazgo para descubrir a qué corresponde.
        _contador = defaultdict(int)
        _prefijo = {'grave': 'G', 'menor': 'M', 'informativo': 'I'}
        for item in r['consolidado']:
            pref = _prefijo.get(item['gravedad'], '?')
            _contador[pref] += 1
            item['_num'] = f"{pref}{_contador[pref]}"
        for i, c in enumerate(cascadas_grave, start=1):
            c['_num'] = f"CG{i}"
        for i, c in enumerate(cascadas_revisar, start=1):
            c['_num'] = f"C{i}"
        # Una cascada geométrica sigue siendo una diferencia real entre V1 y
        # V2 (se agrupa para no listarla como N fallas repetidas, pero eso no
        # la vuelve invisible): si hay cascadas y ninguna falla grave, la
        # página queda en un estado intermedio "revisar" en vez de "✅ todo
        # igual", que es lo que generaba la confusión de por qué el reporte
        # decía que estaba todo bien y después mostraba desplazamientos.
        alert = 'red' if (r['fatal'] or total_graves) else ('orange' if cascadas_revisar else 'green')
        if alert == 'red':
            sites_con_grave += 1
        elif alert == 'orange':
            sites_con_cascada += 1

        if r['fatal']:
            resumen_texto = "❌ Error grave en la ejecución de Selenium (ver logs)."
        elif total_graves:
            resumen_texto = f"❌ Se detectaron {total_graves} diferencias graves."
        elif cascadas_revisar:
            resumen_texto = (f"⚠️ Sin diferencias graves, pero hay {len(cascadas_revisar)} desplazamiento(s) en cascada "
                              f"para revisar (ver detalle) — puede ser contenido que legítimamente cambió de "
                              f"tamaño, o un bug de layout real.")
        else:
            resumen_texto = "✅ No se encontraron diferencias."

        fallas_html = "<li>Error grave, sin datos.</li>" if r['fatal'] else construir_html_fallas(
            r['consolidado'], r['cascadas'], r.get('info_elementos', {}), r['url_id']
        )

        img1_tag = f"<img src='{r['filename1']}' alt='V1'>" if r.get('filename1') else "<p>Sin captura</p>"
        img2_tag = f"<img id='screenshot-{r['url_id']}' src='{r['filename2_diff']}' alt='V2'>" if r.get('filename2_diff') else "<p>Sin captura</p>"

        all_details_html += f"""
        <div style="border: 2px solid #ddd; padding: 15px; margin-top: 20px; border-radius: 8px;">
            <h2>{r['description']}</h2>
            <p><strong>URL PROD (V1):</strong> <a href="{r['url1']}" target="_blank"><code>{r['url1']}</code></a></p>
            <p><strong>URL VNP (V2):</strong> <a href="{r['url2']}" target="_blank"><code>{r['url2']}</code></a></p>
            <p><strong>Resultado:</strong> <span style="font-weight:bold; color:{alert};">{resumen_texto}</span></p>
            <p><strong>Tiempo de Ejecución:</strong> {r['time_elapsed']}</p>
            <details>
                <summary style="cursor:pointer; font-weight:bold; color:#1e3a8a;">Detalle de diferencias</summary>
                <div id="diff-list-{r['url_id']}" style="margin-top:10px; background:#fff; padding:10px; border:1px solid #eee;">
                    {fallas_html}
                </div>
            </details>
            <details>
                <summary style="cursor:pointer; font-weight:bold; color:#1e3a8a;">Contexto Visual</summary>
                <div class='container' id='container-{r["url_id"]}'>
                    <div><h4>PROD (V1)</h4>{img1_tag}</div>
                    <div id="image-container-{r['url_id']}" style="position:relative;">
                        <h4>VNP (V2) — con diferencias marcadas</h4>{img2_tag}
                        <div id="highlight-box-{r['url_id']}" class="highlight-box" style="display:none;"></div>
                    </div>
                </div>
            </details>
        </div>
        """

    if sites_con_grave > 0:
        global_color = 'red'
        global_text = f'❌ Se encontraron diferencias graves en {sites_con_grave} de {len(all_results)} urls. NO recomendado deployar a PROD sin revisar.'
    elif sites_con_cascada > 0:
        global_color = 'orange'
        global_text = (f'⚠️ Sin diferencias graves, pero {sites_con_cascada} de {len(all_results)} urls tienen '
                        f'desplazamientos en cascada para revisar antes de deployar (ver el detalle de cada una).')
    else:
        global_color = 'green'
        global_text = '✅ Todas las URLs pasaron la prueba estructural. Apto para deployar a PROD.'

    html = f"""
    <html><head><meta charset="utf-8">
    <title>Reporte de Regresión {producto_nombre} {modo.capitalize()} - Versión {version_number}</title>
    <style>
    body {{ font-family: Arial; background:#f7f7f7; margin:20px; }}
    h1 {{ color:#1e3a8a; border-bottom:3px solid #bfdbfe; padding-bottom:10px; }}
    h2 {{ margin-top:40px; color:#555; border-bottom:2px solid #ccc; padding-bottom:5px; }}
    code {{ background:#eee; padding:2px 4px; border-radius:3px; }}
    .container {{ display:flex; gap:20px; margin-bottom:40px; border:1px solid #eee; padding:10px; background:#fafafa; overflow-x:auto; }}
    .container > div {{ flex:1; min-width:480px; }}
    img {{ width:100%; height:auto; border:3px solid #ccc; border-radius:4px; display:block; }}
    .highlight-box {{ position:absolute; pointer-events:none; z-index:1000; border-left:15px solid transparent; border-right:15px solid transparent; border-top:30px solid #ffcc00; transform:translateX(-50%); }}
    </style></head>
    <body>
    <h1>Reporte de Regresión {producto_nombre} {modo.capitalize()} - Versión {version_number}</h1>
    <p><strong>Versión Testeada:</strong> <code>{version_number}</code></p>
    <p><strong>Fecha y Hora:</strong> {format_date(timestamp)} {timestamp.split('_')[1][:2]}:{timestamp.split('_')[1][2:4]}:{timestamp.split('_')[1][4:6]}</p>
    <p><strong>Tiempo Total:</strong> {format_time(tiempo_total)}</p>
    <p><strong>Umbral de Tolerancia:</strong> {umbral_pixeles} píxeles.</p>
    <p><strong>Resumen global:</strong> <span style="font-weight:bold; color:{global_color};">{global_text}</span></p>
    {LEYENDA_HTML}
    <hr/>
    {all_details_html}
    <div id="offscreen-toast" style="display:none; position:fixed; bottom:20px; left:50%; transform:translateX(-50%);
        background:#1e293b; color:#fff; padding:10px 18px; border-radius:6px; font-size:0.85em; z-index:2000;
        box-shadow:0 4px 12px rgba(0,0,0,0.3); max-width:600px; text-align:center;"></div>
    <script>
    let lastHighlightedItem = null;
    let offscreenToastTimer = null;
    function showOffscreenToast(msg) {{
        const toast = document.getElementById('offscreen-toast');
        if (!toast) return;
        toast.textContent = msg;
        toast.style.display = 'block';
        if (offscreenToastTimer) clearTimeout(offscreenToastTimer);
        offscreenToastTimer = setTimeout(() => {{ toast.style.display = 'none'; }}, 4000);
    }}
    function highlightElement(urlId, coordsStr, clickedItem) {{
        if (lastHighlightedItem) lastHighlightedItem.style.backgroundColor = 'transparent';
        clickedItem.style.backgroundColor = '#fffacd';
        lastHighlightedItem = clickedItem;
        const screenshot = document.getElementById(`screenshot-${{urlId}}`);
        const highlightBox = document.getElementById(`highlight-box-${{urlId}}`);
        if (!screenshot || !highlightBox) return;
        const doHighlight = () => {{
            // Guard contra clientWidth/naturalWidth en 0 (imagen todavía no
            // terminó de cargar/decodificar cuando se hizo click): sin esto
            // scaleFactor da NaN, las coordenadas del recuadro y del scroll
            // también dan NaN, y window.scrollTo({{top: NaN}}) hace que el
            // navegador interprete NaN como 0 y salte al principio de la
            // página en vez de a la falla clickeada. Bug real reportado por
            // el usuario (El Doce desktop v721): click en una falla grave
            // scrolleaba siempre hacia arriba.
            if (!screenshot.naturalWidth || !screenshot.clientWidth) return;
            const [origX, origY, origW, origH] = coordsStr.split(',').map(Number);
            // Elementos posicionados fuera de pantalla por el propio sitio
            // (patrón común para ocultar visualmente contenido, ej. un panel
            // de búsqueda o un menú colapsado: left:-9999px o similar) no
            // tienen ninguna posición real dentro de la captura. Sin este
            // guard, el scroll se calculaba igual con esas coordenadas
            // negativas/absurdas y terminaba en un punto arbitrario de la
            // imagen (ni arriba de todo ni cerca de nada relevante) —
            // confuso para quien hace click esperando ver la falla resaltada.
            // Bug real reportado por el usuario sobre El Doce desktop v721
            // (Deportes / Estadísticas deportes), con el fix anterior (NaN
            // → scroll a 0) ya desplegado: el click seguía sin llevar a un
            // lugar útil, solo que ahora a un punto random en vez de arriba.
            const fueraDePantalla = origX < 0 || origY < 0 ||
                origX > screenshot.naturalWidth || origY > screenshot.naturalHeight;
            if (fueraDePantalla) {{
                highlightBox.style.display = 'none';
                screenshot.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
                showOffscreenToast('⚠️ Este elemento está posicionado fuera de la pantalla visible por el propio sitio (oculto por CSS) — no aparece en la captura, por eso no se puede resaltar.');
                return;
            }}
            const scaleFactor = screenshot.clientWidth / screenshot.naturalWidth;
            highlightBox.style.display = 'block';
            highlightBox.style.left = (origX * scaleFactor + (origW * scaleFactor / 2)) + "px";
            highlightBox.style.top = (origY * scaleFactor - 35) + "px";
            const rect = screenshot.getBoundingClientRect();
            window.scrollTo({{ top: window.pageYOffset + rect.top + (origY * scaleFactor) - 200, behavior: 'smooth' }});
        }};
        if (screenshot.complete) {{
            doHighlight();
        }} else {{
            screenshot.addEventListener('load', doHighlight, {{ once: true }});
        }}
    }}
    </script>
    </body></html>
    """

    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html)
    return html_file, global_text


# =====================================================================
# MAIN
# =====================================================================

def _tiene_graves(r):
    return (any(c['gravedad'] == 'grave' for c in r['consolidado'])
            or any(c.get('grave') for c in (r.get('cascadas') or [])))


def main(base_urls_map, producto_nombre="Sitio", output_dir_base=os.path.join('reportes', 'sitio')):
    """Punto de entrada genérico. Cada script de producto (regre_visual_tn.py,
    regre_visual_eltrece.py, regre_visual_eldoce.py, regre_visual_ciudad.py)
    llama a esta función pasando su propio BASE_URLS_MAP, nombre de producto
    (para el título del reporte) y carpeta base de reportes."""
    # En consolas de Windows (cp1252) los emojis de los prints tiran UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8')
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description=f"Regresión visual/estructural {producto_nombre} (desktop o mobile).")
    parser.add_argument("version", help="Número de versión a testear (?d=VERSION)")
    parser.add_argument("--modo", choices=["desktop", "mobile"], default="desktop")
    parser.add_argument("--urls", default=None,
                         help="Lista separada por comas de nombres (valores de BASE_URLS_MAP) a testear. Por defecto: todas.")
    parser.add_argument("--tolerancia", type=int, default=core.UMBRAL_PIXELES_TOLERANCIA_DEFAULT)
    parser.add_argument("--sin-confirmacion-visual", action="store_true",
                         help="Desactiva el crop+diff visual (más rápido, pero sin ese filtro de falsos positivos).")
    parser.add_argument("--sin-estilos", action="store_true",
                         help="No comparar estilos computados (solo geometría).")
    parser.add_argument("--sin-linea-base-ruido", action="store_true",
                         help="No captura V1 por segunda vez (mas rapido, pero sin filtrar el contenido que cambia solo).")
    parser.add_argument("--reintentar-fallas", action="store_true",
                         help="Si una URL tiene fallas graves, la vuelve a correr tras --espera-reintento segundos y "
                              "solo reporta las fallas que se repiten (filtra desfases de cache entre PROD y VNP).")
    parser.add_argument("--espera-reintento", type=int, default=90,
                         help="Segundos de espera antes del reintento (default 90; el cache de ARC dura ~60-120s).")
    parser.add_argument("--fallar-si-graves", action="store_true",
                         help="Sale con codigo 1 si hay fallas graves (util para CI; en GitHub Actions los pasos "
                              "siguientes necesitan 'if: always()' para subir el reporte).")
    args = parser.parse_args()

    if not args.version.isdigit():
        print("❌ El número de versión debe ser numérico.")
        sys.exit(1)

    config = config_modos(output_dir_base)[args.modo]
    output_dir = config['output_dir']
    os.makedirs(output_dir, exist_ok=True)

    urls_map = base_urls_map
    if args.urls:
        nombres = set(n.strip() for n in args.urls.split(','))
        urls_map = {u: d for u, d in base_urls_map.items() if d in nombres}
        faltantes = nombres - set(urls_map.values())
        if faltantes:
            print(f"⚠️ No encontrados en BASE_URLS_MAP: {faltantes}")
        if not urls_map:
            # Sin esto: 0 URLs corridas generaba igual un reporte con
            # "Resumen global: ✅ Todas las URLs pasaron la prueba
            # estructural" (verdad vacía sobre 0/0) — un resultado en verde
            # sin ninguna URL testeada, indistinguible de una corrida real
            # limpia. Detectado en la práctica: --urls con la URL completa
            # en vez del nombre de BASE_URLS_MAP (ej. "https://tn.com.ar/"
            # en vez de "Homepage") pasaba silenciosamente como éxito.
            print(f"❌ Ningún nombre de --urls coincide con BASE_URLS_MAP. "
                  f"Nombres válidos: {sorted(base_urls_map.values())}")
            sys.exit(1)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    all_results = []
    start_global = time.time()

    print(f"\nINICIANDO REGRESIÓN {producto_nombre.upper()} {args.modo.upper()} - VERSIÓN {args.version}")
    print(f"Tolerancia: {args.tolerancia}px | Confirmación visual: {not args.sin_confirmacion_visual} | Comparar estilos: {not args.sin_estilos}\n")

    for idx, (base_url, descripcion) in enumerate(urls_map.items(), 1):
        start_url = time.time()
        url_id = re.sub(r'[^a-zA-Z0-9]', '_', descripcion).lower()

        print(f"\n[{idx}/{len(urls_map)}] {descripcion}")
        r = procesar_url(descripcion, base_url, args.version, args.modo, config,
                          args.tolerancia, not args.sin_confirmacion_visual, not args.sin_estilos,
                          not args.sin_linea_base_ruido)
        if args.reintentar_fallas and not r['fatal'] and _tiene_graves(r):
            print(f"  ↻ Fallas graves: reintentando en {args.espera_reintento}s para descartar desfase de cache...")
            time.sleep(args.espera_reintento)
            r = procesar_url(descripcion, base_url, args.version, args.modo, config,
                              args.tolerancia, not args.sin_confirmacion_visual, not args.sin_estilos,
                              not args.sin_linea_base_ruido, confirmar_con=r['claves_fallas'])
        r['description'] = descripcion
        r['url_id'] = url_id
        r['time_elapsed'] = format_time(time.time() - start_url)

        if not r['fatal']:
            filename1 = f"{url_id}_V{args.version}_base_{timestamp}.png"
            filename2 = f"{url_id}_V{args.version}_diff_{timestamp}.png"
            if r['png_v1']:
                Image.open(io.BytesIO(r['png_v1'])).save(os.path.join(output_dir, filename1))
                r['filename1'] = filename1
            if r['png_v2']:
                png_marcado = marcar_fallas_en_captura(r['png_v2'], r['consolidado'], r['cascadas'])
                Image.open(io.BytesIO(png_marcado or r['png_v2'])).save(os.path.join(output_dir, filename2))
                r['filename2_diff'] = filename2

            graves = [c for c in r['consolidado'] if c['gravedad'] == 'grave']
            cascadas_grave = [c for c in (r['cascadas'] or []) if c.get('grave')]
            cascadas_revisar = [c for c in (r['cascadas'] or []) if not c.get('grave')]
            total_graves = len(graves) + len(cascadas_grave)
            print(f"  {'❌' if total_graves else '✅'} {total_graves} fallas graves "
                  f"({len(cascadas_grave)} en cascadas de estilo) | {len(cascadas_revisar)} cascadas geométricas para revisar")
        else:
            print("  ❌ FATAL ERROR tras reintentos")

        all_results.append(r)

    tiempo_total = time.time() - start_global
    html_file, resumen = generar_reporte(all_results, args.version, output_dir, timestamp,
                                          args.tolerancia, tiempo_total, args.modo,
                                          producto_nombre=producto_nombre)

    print(f"\n{'='*80}\n✅ Proceso completado.\n📄 Reporte: {html_file}\n{resumen}\n{'='*80}")

    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"summary_text={resumen}\n")

    if args.fallar_si_graves:
        hay_graves = any(
            r.get('fatal') or any(c['gravedad'] == 'grave' for c in r['consolidado'])
            or any(c.get('grave') for c in (r.get('cascadas') or []))
            for r in all_results)
        if hay_graves:
            sys.exit(1)
