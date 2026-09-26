#!/usr/bin/env python3
"""
regre_visual_tn.py
===================
Herramienta unificada de regresión visual/estructural para TN, en
reemplazo de regre_visual_tn_desk_prod2.py y regre_visual_tn_webmobile.py.

Uso:
    python regre_visual_tn.py --modo desktop 719
    python regre_visual_tn.py --modo mobile 719
    python regre_visual_tn.py --modo desktop 719 --urls Homepage,Listado,Juegos
    python regre_visual_tn.py --modo desktop 719 --tolerancia 4 --sin-confirmacion-visual

Qué cambia respecto a los dos scripts originales (ver diagnóstico previo):
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

from PIL import Image

import regre_visual_tn_core as core

# =====================================================================
# CONFIGURACIÓN POR MODO
# =====================================================================

CONFIG_MODOS = {
    'desktop': {
        'output_dir': os.path.join('reportes', 'desktop'),
        'window_size': (1920, 1080),
        'user_agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'),
        'bloquear_imagenes': False,
        'ancho_referencia_js': 1920,
        'page_load_timeout': 90,
    },
    'mobile': {
        'output_dir': os.path.join('reportes', 'mobile'),
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

        data.push({
            tag: el.tagName.toLowerCase(),
            selector: getCssSelector(el),
            id_attr: el.id,
            class_attr: el.className,
            data_attrs: getDataAttrs(el),
            texto: texto,
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
                textAlign: compStyle.textAlign
            }
        });
    }
    return { dpr: window.devicePixelRatio || 1, elements: data };
"""


def obtener_estructura_dom(driver, incluir_texto=True, espera_scroll=2):
    """Devuelve (data, png) para la URL actualmente cargada en el driver."""
    from selenium.webdriver.support.ui import WebDriverWait

    data, png = [], None
    try:
        WebDriverWait(driver, 20).until(lambda d: d.execute_script("return document.readyState") == "complete")

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

        data, png = obtener_estructura_dom(driver, incluir_texto=(modo == 'mobile'))

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
                  umbral_pixeles, usar_confirmacion_visual, comparar_estilos):
    url1 = base_url
    url2 = f"{base_url}&d={version_number}" if '?' in base_url else f"{base_url}?d={version_number}"

    print(f"  [V1] Obteniendo datos estructurales...")
    data_v1, png_v1 = ejecutar_con_reintentos(url1, modo, config)
    print(f"  [V2] Obteniendo datos estructurales...")
    data_v2, png_v2 = ejecutar_con_reintentos(url2, modo, config)

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
    }


# =====================================================================
# MARCADO VISUAL (OpenCV) — 3 colores: grave / menor / informativo
# =====================================================================

COLOR_BGR = {
    'grave': (0, 0, 255),        # rojo
    'menor': (255, 0, 0),        # azul
    'informativo': (0, 200, 200),  # amarillo/dorado — degradado por confirmación visual
    'cascada': (0, 165, 255),    # naranja — desplazamiento en cascada agrupado
}


def marcar_fallas_en_captura(png_data, consolidado, cascadas):
    import cv2
    import numpy as np

    if not png_data:
        return None

    img = cv2.imdecode(np.frombuffer(png_data, np.uint8), cv2.IMREAD_COLOR)
    height, width = img.shape[:2]

    def dibujar(coords, color_key):
        x1 = max(0, int(coords['x']))
        y1 = max(0, int(coords['y']))
        x2 = min(width - 1, int(coords['x'] + coords['width']))
        y2 = min(height - 1, int(coords['y'] + coords['height']))
        if x2 > x1 and y2 > y1:
            thickness = 5 if color_key == 'grave' else 3
            cv2.rectangle(img, (x1, y1), (x2, y2), COLOR_BGR[color_key], thickness)

    for item in consolidado:
        dibujar(item['coords_v2'], item['gravedad'])
    for cascada in cascadas:
        dibujar(cascada['coords_v2'], 'cascada')

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
    <div style="flex: 1 1 220px;"><span style="color:#b8860b; font-weight:bold;">■ Dorado</span>: el DOM detectó una diferencia pero la confirmación visual (crop + diff) mostró que la región es igual — probablemente un falso positivo.</div>
    <div style="flex: 1 1 220px;"><span style="color:#ff8c00; font-weight:bold;">■ Naranja</span>: desplazamiento en cascada — un solo elemento anterior cambió de tamaño y corrió a los siguientes; no son N fallas independientes.</div>
  </div>
</div>
"""


def construir_html_fallas(consolidado, cascadas, data_v2_por_selector, url_id):
    html = "<ul>"

    DESC_CASCADA = {
        'DIFERENCIA POSICIÓN (Y)': ('se movieron', 'en Y'),
        'DIFERENCIA ALTURA (H)': ('cambiaron de alto', 'en H'),
        'DIFERENCIA ANCHO (W)': ('cambiaron de ancho', 'en W'),
    }

    if cascadas:
        for c in cascadas:
            verbo, eje = DESC_CASCADA.get(c.get('tipo'), ('se movieron', 'en Y'))
            html += f"""
            <li class='diff-item' style='color: #ff8c00; border-bottom: 1px dotted #ccc; padding: 5px 0;'>
                <span style="font-weight: bold;">Desplazamiento en cascada:</span>
                {c['cantidad']} elementos {verbo} {c['delta_y']:.0f}px {eje}.
                <br><span style="font-size: 0.85em; color: #666;">
                Causa probable: un cambio de tamaño en un elemento anterior del DOM
                (empezando por <code>{c['primer_selector'][:60]}</code>), no {c['cantidad']} regresiones independientes.
                </span>
            </li>
            """

    for item in consolidado:
        color = {'grave': 'red', 'menor': '#007bff', 'informativo': '#b8860b'}[item['gravedad']]
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
                     tiempo_total, modo):
    html_file = os.path.join(output_dir, f"Reporte_DOM_Estructural_v{version_number}_{timestamp}.html")

    all_details_html = ""
    sites_con_grave = 0

    for r in all_results:
        graves = [c for c in r['consolidado'] if c['gravedad'] == 'grave']
        alert = 'red' if (r['fatal'] or graves) else 'green'
        if alert == 'red':
            sites_con_grave += 1

        if r['fatal']:
            resumen_texto = "❌ Error grave en la ejecución de Selenium (ver logs)."
        elif graves:
            resumen_texto = f"❌ Se detectaron {len(graves)} diferencias graves."
        else:
            resumen_texto = "✅ No se encontraron diferencias graves."

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

    global_color = 'red' if sites_con_grave > 0 else 'green'
    global_text = (f'❌ Se encontraron diferencias graves en {sites_con_grave} de {len(all_results)} urls.'
                    if sites_con_grave > 0 else
                    '✅ Todas las URLs pasaron la prueba estructural.')

    html = f"""
    <html><head><meta charset="utf-8">
    <title>Reporte de Regresión {modo.capitalize()} - Versión {version_number}</title>
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
    <h1>Reporte de Regresión {modo.capitalize()} - Versión {version_number}</h1>
    <p><strong>Versión Testeada:</strong> <code>{version_number}</code></p>
    <p><strong>Fecha y Hora:</strong> {format_date(timestamp)} {timestamp.split('_')[1][:2]}:{timestamp.split('_')[1][2:4]}:{timestamp.split('_')[1][4:6]}</p>
    <p><strong>Tiempo Total:</strong> {format_time(tiempo_total)}</p>
    <p><strong>Umbral de Tolerancia:</strong> {umbral_pixeles} píxeles.</p>
    <p><strong>Resumen global:</strong> <span style="font-weight:bold; color:{global_color};">{global_text}</span></p>
    {LEYENDA_HTML}
    <hr/>
    {all_details_html}
    <script>
    let lastHighlightedItem = null;
    function highlightElement(urlId, coordsStr, clickedItem) {{
        if (lastHighlightedItem) lastHighlightedItem.style.backgroundColor = 'transparent';
        clickedItem.style.backgroundColor = '#fffacd';
        lastHighlightedItem = clickedItem;
        const screenshot = document.getElementById(`screenshot-${{urlId}}`);
        const highlightBox = document.getElementById(`highlight-box-${{urlId}}`);
        if (!screenshot || !highlightBox) return;
        const [origX, origY, origW, origH] = coordsStr.split(',').map(Number);
        const scaleFactor = screenshot.clientWidth / screenshot.naturalWidth;
        highlightBox.style.display = 'block';
        highlightBox.style.left = (origX * scaleFactor + (origW * scaleFactor / 2)) + "px";
        highlightBox.style.top = (origY * scaleFactor - 35) + "px";
        const rect = screenshot.getBoundingClientRect();
        window.scrollTo({{ top: window.pageYOffset + rect.top + (origY * scaleFactor) - 200, behavior: 'smooth' }});
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

def main():
    parser = argparse.ArgumentParser(description="Regresión visual/estructural TN (desktop o mobile).")
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

    config = CONFIG_MODOS[args.modo]
    output_dir = config['output_dir']
    os.makedirs(output_dir, exist_ok=True)

    urls_map = BASE_URLS_MAP
    if args.urls:
        nombres = set(n.strip() for n in args.urls.split(','))
        urls_map = {u: d for u, d in BASE_URLS_MAP.items() if d in nombres}
        faltantes = nombres - set(urls_map.values())
        if faltantes:
            print(f"⚠️ No encontrados en BASE_URLS_MAP: {faltantes}")

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    all_results = []
    start_global = time.time()

    print(f"\nINICIANDO REGRESIÓN {args.modo.upper()} - VERSIÓN {args.version}")
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
            print(f"  {'❌' if graves else '✅'} {len(graves)} fallas graves | {len(r['cascadas'])} cascadas agrupadas")
        else:
            print("  ❌ FATAL ERROR tras reintentos")

        all_results.append(r)

    tiempo_total = time.time() - start_global
    html_file, resumen = generar_reporte(all_results, args.version, output_dir, timestamp,
                                          args.tolerancia, tiempo_total, args.modo)

    print(f"\n{'='*80}\n✅ Proceso completado.\n📄 Reporte: {html_file}\n{resumen}\n{'='*80}")

    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"summary_text={resumen}\n")


if __name__ == "__main__":
    main()
