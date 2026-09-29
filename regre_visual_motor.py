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

# FIX #35 — umbral de tolerancia para el chequeo de "captura recortada"
# (ver obtener_estructura_dom). 20px de margen para no generar falsos
# positivos por redondeo/subpíxel o por elementos legítimamente
# posicionados apenas fuera del área capturada.
UMBRAL_RECORTE_PX = 20


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
    """Devuelve (data, png, recorte) para la URL actualmente cargada en el driver.

    `recorte` es None si la captura parece completa, o un dict con detalle
    si el screenshot quedó más chico que la posición real de algún elemento
    del DOM (ver FIX #35 más abajo)."""
    from selenium.webdriver.support.ui import WebDriverWait

    data, png, recorte = [], None, None
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

        # Tercera limpieza, justo antes del screenshot: los dos llamados de arriba pasan
        # ANTES de forzar_carga_contenido (~8s de scrolls) + el resize + esta espera de
        # fuentes -- tiempo de sobra para que aparezca un popup con delay propio (ej. el
        # slidedown de OneSignal pidiendo permiso de notificaciones, que en TN no aparece
        # al cargar sino unos segundos después). Si aparece ahí, nunca se vuelve a limpiar
        # y arruina el screenshot: al ser position:fixed y haber resizeado la ventana a la
        # altura TOTAL del documento, un fixed anclado abajo del viewport termina flotando
        # justo donde cae el footer, tapándolo en la captura (el footer sigue en el DOM --
        # por eso un F12 manual lo muestra bien -- pero visualmente desaparece del PNG).
        # Bug real: TN webmobile v.next, mismo componente disparó en V1 y no en V2 (carrera
        # de timing, no un cambio del sitio) -> "footer ausente" era un falso positivo.
        limpiar_entorno(driver)

        # FIX #36 — estabilizar el alto ANTES de extraer datos y capturar, en
        # vez de re-medir una sola vez después de extraer (fix #34). Evidencia
        # real (usuario, TN mobile, 28/09 23:30): con el fix #34 ya desplegado,
        # el footer seguía cortado en TODAS las evidencias mobile, faltando
        # los últimos 2 links ("Políticas de privacidad", "Media Kit") que sí
        # existen en el DOM desde el primer momento (confirmado con DevTools
        # en la página real) -- no es un problema de contenido que tarda en
        # aparecer, sino de que el propio resize de la ventana a una altura
        # enorme (para que el documento completo entre en un solo screenshot)
        # puede hacer crecer el documento DE NUEVO: cualquier estilo del sitio
        # que use unidades `vh` cambia de valor cuando la ventana pasa a medir
        # ~20000px de alto, lo que puede modificar el alto real del footer u
        # otro bloque después de la primera corrección. El fix #34 solo
        # re-medía y resizeaba UNA vez; si el crecimiento seguía después de
        # ese segundo resize, quedaba sin corregir. Acá se repite re-medir +
        # resizear hasta que el alto deja de crecer (o se alcanza el tope de
        # intentos), y la extracción de datos (JS_EXTRACCION) y el screenshot
        # se hacen recién después, ya sobre el alto estabilizado -- para que
        # ambos reflejen el mismo estado final del documento.
        MAX_INTENTOS_ESTABILIZAR_ALTURA = 4
        altura_final = total_height
        for _ in range(MAX_INTENTOS_ESTABILIZAR_ALTURA):
            nueva_altura = driver.execute_script(
                "return Math.max(document.body.scrollHeight, document.body.offsetHeight, "
                "document.documentElement.clientHeight, document.documentElement.scrollHeight, "
                "document.documentElement.offsetHeight);"
            )
            if nueva_altura <= altura_final:
                altura_final = nueva_altura
                break
            altura_final = nueva_altura
            driver.set_window_size(original_size['width'], altura_final)
            time.sleep(1)

        js = JS_EXTRACCION.replace('INCLUIR_TEXTO', 'true' if incluir_texto else 'false')
        result = driver.execute_script(js)
        data = result.get('elements', [])

        png = driver.get_screenshot_as_png()
        driver.set_window_size(original_size['width'], original_size['height'])

        # FIX #35 — red de seguridad para detectar automáticamente cualquier
        # captura recortada (no solo en Elecciones), en vez de depender de
        # que alguien la note a ojo y compare los PNG a mano (así pasó
        # desapercibido el caso real del fix #34: el reporte decía "✅ sin
        # diferencias" con 1046px de footer cortado en una de las dos
        # capturas). altura_captura es el alto de ventana con el que
        # efectivamente se tomó ESTE screenshot (ya estabilizado por el fix
        # #36 de arriba). max_bottom es la posición real más baja de
        # cualquier elemento medido por JS_EXTRACCION (getBoundingClientRect,
        # independiente del tamaño de ventana). Si max_bottom se pasa de
        # altura_captura por más que el umbral, algo quedó fuera del PNG.
        altura_captura = altura_final
        bottoms = [
            el['y'] + el['height'] for el in data
            if isinstance(el, dict) and isinstance(el.get('y'), (int, float))
            and isinstance(el.get('height'), (int, float))
        ]
        max_bottom = max(bottoms) if bottoms else 0
        recorte = None
        if max_bottom > altura_captura + UMBRAL_RECORTE_PX:
            recorte = {
                'max_bottom': round(max_bottom),
                'altura_captura': round(altura_captura),
                'diff': round(max_bottom - altura_captura),
            }

    except Exception as e:
        print(f"     ❌ Error en la extracción/captura: {e}")
        data = [{'selector': 'FATAL ERROR'}]
        recorte = None

    return data, png, recorte


def ejecutar_selenium_para_estructura(url, modo, config):
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    options = webdriver.ChromeOptions()
    if config['bloquear_imagenes']:
        # FIX #37 — el valor de Chrome para BLOQUEAR imágenes es 2, no 1 (1 es
        # "allow", el default; o sea que este flag nunca bloqueó nada desde que
        # existe). Evidencia real (usuario, TN/El Trece/El Doce/Ciudad mobile,
        # 29/09): con el fix #36 (loop de estabilización de alto) ya
        # desplegado, el footer seguía cortado en TODAS las evidencias mobile
        # de los 4 productos por igual -- eso apunta a una causa compartida
        # por el motor, no a un timing puntual de un sitio. Con
        # bloquear_imagenes=True quedando en "allow" por este typo, en mobile
        # cargan TODAS las imágenes reales (fotos, iconos de redes, badges de
        # app store) en vez de bloquearse como estaba pensado desde el
        # script viejo (ver comentario de DOMINIOS_BLOQUEADOS/config_modos):
        # esas imágenes siguen bajando y corriendo el layout durante segundos
        # después de que el loop del fix #36 ya dio por estable el alto del
        # documento (4 intentos x 1s no alcanzan para cubrir imágenes lentas
        # de red), lo que corre el footer real más abajo de donde se tomó el
        # screenshot. Corrigiendo el valor a 2 se recupera el comportamiento
        # que el flag siempre debió tener: sin imágenes, el layout mobile se
        # asienta con el contenido de texto/DOM únicamente, mucho más rápido
        # y estable. El fix #36 se deja como red de seguridad adicional, no
        # se revierte.
        options.add_experimental_option("prefs", {"profile.managed_default_content_settings.images": 2})

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
    data, png, recorte = [], None, None
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
        data, png, recorte = obtener_estructura_dom(driver, incluir_texto=True)

    except Exception as e:
        print(f"❌ Error al inicializar/ejecutar Selenium en {url}: {e}")
        data = [{'selector': 'FATAL ERROR'}]
        recorte = None
    finally:
        if driver:
            driver.quit()

    return data, png, recorte


def ejecutar_con_reintentos(url, modo, config, intentos_max=REINTENTOS_MAX):
    """Antes: un timeout de red puntual marcaba FATAL ERROR sin reintentar,
    perdiendo la corrida completa de esa URL. Ahora reintenta antes de
    darse por vencido."""
    ultimo_data, ultimo_png, ultimo_recorte = [], None, None
    for intento in range(1, intentos_max + 1):
        data, png, recorte = ejecutar_selenium_para_estructura(url, modo, config)
        es_fatal = any(isinstance(d, dict) and d.get('selector') == 'FATAL ERROR' for d in data)
        if not es_fatal:
            return data, png, recorte
        ultimo_data, ultimo_png, ultimo_recorte = data, png, recorte
        if intento < intentos_max:
            print(f"     ⚠️ Intento {intento}/{intentos_max} falló para {url}, reintentando...")
            time.sleep(3)
    return ultimo_data, ultimo_png, ultimo_recorte


# =====================================================================
# ORQUESTACIÓN POR URL
# =====================================================================

def procesar_url(url_description, base_url, version_number, modo, config,
                  umbral_pixeles, usar_confirmacion_visual, comparar_estilos):
    url1 = base_url
    url2 = f"{base_url}&d={version_number}" if '?' in base_url else f"{base_url}?d={version_number}"

    print(f"  [V1] Obteniendo datos estructurales...")
    data_v1, png_v1, recorte_v1 = ejecutar_con_reintentos(url1, modo, config)
    print(f"  [V2] Obteniendo datos estructurales...")
    data_v2, png_v2, recorte_v2 = ejecutar_con_reintentos(url2, modo, config)

    # FIX #35 — avisar si alguna de las dos capturas detectó recorte, para
    # que se vea en el reporte sin depender de que alguien lo note a ojo
    # (ver detalle en obtener_estructura_dom). No bloquea la corrida: sigue
    # comparando lo que haya, pero el reporte debe marcarlo bien visible.
    if recorte_v1:
        print(f"     ⚠️ Posible captura recortada en V1: elemento en {recorte_v1['max_bottom']}px, "
              f"captura de {recorte_v1['altura_captura']}px ({recorte_v1['diff']}px de diferencia)")
    if recorte_v2:
        print(f"     ⚠️ Posible captura recortada en V2: elemento en {recorte_v2['max_bottom']}px, "
              f"captura de {recorte_v2['altura_captura']}px ({recorte_v2['diff']}px de diferencia)")

    es_fatal = (
        any(isinstance(d, dict) and d.get('selector') == 'FATAL ERROR' for d in data_v1) or
        any(isinstance(d, dict) and d.get('selector') == 'FATAL ERROR' for d in data_v2)
    )
    if es_fatal:
        return {
            'url1': url1, 'url2': url2, 'fatal': True,
            'consolidado': [], 'cascadas': [], 'png_v1': png_v1, 'png_v2': png_v2,
            'recorte_v1': recorte_v1, 'recorte_v2': recorte_v2,
        }

    fallas = core.comparar_estructura_dom(data_v1, data_v2, umbral_pixeles=umbral_pixeles,
                                           comparar_estilos=comparar_estilos)
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
        'recorte_v1': recorte_v1, 'recorte_v2': recorte_v2,
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


def construir_html_fallas(consolidado, cascadas, data_v2_por_selector, url_id):
    html = "<ul>"

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
                verbo, eje = DESC_CASCADA.get(c.get('tipo'), ('se movieron', 'verticalmente'))
                resumen = f"{c['cantidad']} elementos {verbo} {c['delta_y']:.0f}px" + (f" {eje}" if eje else "")
                causa = (f"Causa probable: un solo elemento anterior del DOM cambió de tamaño y arrastró a los "
                         f"{c['cantidad']} de abajo — no son {c['cantidad']} regresiones independientes, es 1 sola causa raíz "
                         f"(empezando por <code>{c['primer_selector'][:60]}</code>).")
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
            detalle_lineas.append(f"Tipo: <b>{f['tipo']}</b> | V1: {v1_display} | V2: {v2_display} | Diff: {diff_display}{nota_visual}")
        detalle_consolidado = "<div style='margin-top:5px; border-left:2px solid #ccc; padding-left:5px;'>" + "<br>".join(detalle_lineas) + "</div>"

        html += f"""
        <li class='diff-item'
            style='color: {color}; border-bottom: 1px dotted #ccc; padding: 5px 0; cursor: pointer;'
            onclick="highlightElement('{url_id}', '{coords_str}', this)"
            data-coords="{coords_str}">
            <span style="background:{color}; color:#fff; border-radius:3px; padding:1px 6px; font-size:0.8em; font-weight:bold; margin-right:6px;">{item.get('_num', '')}</span>
            <span style="font-weight: bold;">Elemento:</span> <code>{item['selector'][:80]}</code>
            <br><span style="font-weight: bold;">Gravedad:</span> <span style='color:{color};'>{item['gravedad'].upper()}</span>
            {detalle_consolidado}
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

        # FIX #35 — recorte de captura detectado (ver obtener_estructura_dom):
        # esto invalida la confiabilidad de la comparación visual para esta
        # URL (el screenshot no muestra todo lo que el DOM dice que hay), así
        # que se trata como grave aunque la comparación estructural en sí no
        # haya encontrado diferencias — es exactamente el escenario real que
        # motivó este fix (reporte "✅ sin diferencias" con 1046px de footer
        # cortado en una de las dos capturas, ver fix #34).
        recorte_v1 = r.get('recorte_v1')
        recorte_v2 = r.get('recorte_v2')
        tiene_recorte = bool(recorte_v1 or recorte_v2)

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
        alert = 'red' if (r['fatal'] or total_graves or tiene_recorte) else ('orange' if cascadas_revisar else 'green')
        if alert == 'red':
            sites_con_grave += 1
        elif alert == 'orange':
            sites_con_cascada += 1

        if r['fatal']:
            resumen_texto = "❌ Error grave en la ejecución de Selenium (ver logs)."
        elif tiene_recorte:
            partes = []
            if recorte_v1:
                partes.append(f"V1 (elemento a {recorte_v1['max_bottom']}px, captura de solo {recorte_v1['altura_captura']}px)")
            if recorte_v2:
                partes.append(f"V2 (elemento a {recorte_v2['max_bottom']}px, captura de solo {recorte_v2['altura_captura']}px)")
            extra_graves = f" Además se detectaron {total_graves} diferencias graves." if total_graves else ""
            resumen_texto = (f"❌ Captura posiblemente recortada en {' y '.join(partes)} — hay contenido del DOM "
                              f"más abajo del borde de la imagen. La comparación de este resultado no es confiable."
                              f"{extra_graves}")
        elif total_graves:
            resumen_texto = f"❌ Se detectaron {total_graves} diferencias graves."
        elif cascadas_revisar:
            resumen_texto = (f"⚠️ Sin diferencias graves, pero hay {len(cascadas_revisar)} desplazamiento(s) en cascada "
                              f"para revisar (ver detalle) — puede ser contenido que legítimamente cambió de "
                              f"tamaño, o un bug de layout real.")
        else:
            resumen_texto = "✅ No se encontraron diferencias."

        fallas_html = "<li>Error grave, sin datos.</li>" if r['fatal'] else construir_html_fallas(
            r['consolidado'], r['cascadas'], {}, r['url_id']
        )

        img1_tag = f"<img src='{r['filename1']}' alt='V1'>" if r.get('filename1') else "<p>Sin captura</p>"
        img2_tag = f"<img id='screenshot-{r['url_id']}' src='{r['filename2_diff']}' alt='V2'>" if r.get('filename2_diff') else "<p>Sin captura</p>"

        all_details_html += f"""
        <div style="border: 2px solid #ddd; padding: 15px; margin-top: 20px; border-radius: 8px;">
            <h2>{r['description']}</h2>
            <p><strong>URL Base (V1):</strong> <a href="{r['url1']}" target="_blank"><code>{r['url1']}</code></a></p>
            <p><strong>URL Comparada (V2):</strong> <a href="{r['url2']}" target="_blank"><code>{r['url2']}</code></a></p>
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
                    <div><h4>Versión Base (V1)</h4>{img1_tag}</div>
                    <div id="image-container-{r['url_id']}" style="position:relative;">
                        <h4>Versión Nueva (V2)</h4>{img2_tag}
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

def main(base_urls_map, producto_nombre="Sitio", output_dir_base=os.path.join('reportes', 'sitio')):
    """Punto de entrada genérico. Cada script de producto (regre_visual_tn.py,
    regre_visual_eltrece.py, regre_visual_eldoce.py, regre_visual_ciudad.py)
    llama a esta función pasando su propio BASE_URLS_MAP, nombre de producto
    (para el título del reporte) y carpeta base de reportes."""
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
                          args.tolerancia, not args.sin_confirmacion_visual, not args.sin_estilos)
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
