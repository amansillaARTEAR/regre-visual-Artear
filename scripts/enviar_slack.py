#!/usr/bin/env python3
"""
Envía a Slack el reporte HTML de una corrida de Regresión Visual.

Sube el reporte como un único archivo HTML autocontenido (con las capturas
PNG incrustadas como base64, así se puede abrir standalone sin depender de
archivos sueltos) y postea un mensaje con el resumen del resultado.

Uso:
    python scripts/enviar_slack.py --report-dir reportes/tn/desktop \
        --producto tn --modo desktop [--version 721] [--urls "Homepage,Listado"]

Si no se pasa --version, se intenta extraer del nombre del archivo HTML
(patrón v<numero>). Si no se pasa --urls, se cuenta cuántas secciones de URL
tiene el reporte y se muestra "N URLs analizadas" en el mensaje.

Requiere las variables de entorno SLACK_BOT_TOKEN y SLACK_CHANNEL_ID.
Si no están seteadas, el script no falla: avisa por stdout y termina en 0
(para no romper el resto del workflow si Slack todavía no está configurado).
"""
import argparse
import base64
import glob
import os
import re
import sys
import time
import urllib.parse

import requests

PRODUCTO_LABEL = {
    "tn": "TN",
    "eltrece": "El Trece",
    "eldoce": "El Doce",
    "ciudad": "Ciudad Magazine",
}

SLACK_API = "https://slack.com/api"


def log(msg):
    print(f"[enviar_slack] {msg}", flush=True)


def inline_images(html_path, report_dir):
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    png_names = sorted(set(re.findall(r"""['"]([^'"]+\.png)['"]""", html)))
    for name in png_names:
        png_path = os.path.join(report_dir, name)
        if not os.path.isfile(png_path):
            continue
        with open(png_path, "rb") as imgf:
            b64 = base64.b64encode(imgf.read()).decode("ascii")
        data_uri = f"data:image/png;base64,{b64}"
        html = html.replace(f"'{name}'", f"'{data_uri}'").replace(f'"{name}"', f'"{data_uri}"')

    return html


def extraer_resumen(html):
    m = re.search(r"Resumen global:</strong>\s*<span[^>]*>(.*?)</span>", html, re.S)
    if not m:
        return "(no se pudo leer el resumen del reporte)", False
    texto = re.sub(r"<[^>]+>", "", m.group(1)).strip()
    ok = "✅" in texto or "Todas las URLs pasaron" in texto
    return texto, ok


def extraer_version(html, report_dir):
    m = re.search(r"v(\d+)", os.path.basename(html))
    if m:
        return m.group(1)
    m = re.search(r"\?d=(\d+)", html)
    return m.group(1) if m else "?"


def contar_urls(html):
    return len(re.findall(r'<h2>[^<]+</h2>', html))


def resolve_channel(token, channel_id):
    """files.completeUploadExternal solo acepta channel_id de canal/DM (C/G/D/Z...),
    no un ID de usuario (U...). Si nos pasan un ID de usuario, abrimos (o reusamos)
    el DM con esa persona y devolvemos el ID de esa conversación."""
    if not channel_id.startswith("U"):
        return channel_id

    r = requests.post(
        f"{SLACK_API}/conversations.open",
        headers={"Authorization": f"Bearer {token}"},
        data={"users": channel_id},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"conversations.open falló: {data}")
    return data["channel"]["id"]


def team_url_and_bot_id(token):
    """Datos necesarios para armar el permalink de Slack a mano (mismo formato
    que devuelve la API: https://<team>.slack.com/files/<bot_id>/<file_id>/<name>)."""
    r = requests.get(
        f"{SLACK_API}/auth.test",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"auth.test falló: {data}")
    return data["url"].rstrip("/"), data["user_id"]


def slack_post(token, channel, message, file_path, file_title):
    headers = {"Authorization": f"Bearer {token}"}

    channel = resolve_channel(token, channel)

    filename = os.path.basename(file_path)
    size = os.path.getsize(file_path)
    r = requests.post(
        f"{SLACK_API}/files.getUploadURLExternal",
        headers=headers,
        data={"filename": filename, "length": size},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"files.getUploadURLExternal falló: {data}")
    upload_url = data["upload_url"]
    file_id = data["file_id"]

    with open(file_path, "rb") as f:
        r = requests.post(upload_url, files={"file": f}, timeout=120)
    r.raise_for_status()

    # Armamos el link al reporte ANTES de subirlo, para poder incluirlo en el
    # mismo mensaje (initial_comment) y no tener que postear un segundo mensaje
    # aparte, que Slack termina mostrando duplicado (mensaje + preview del link).
    team_url, bot_id = team_url_and_bot_id(token)
    permalink = f"{team_url}/files/{bot_id}/{file_id}/{urllib.parse.quote(filename)}"
    texto_final = f"{message}\n🔗 Ver reporte: {permalink}"

    r = requests.post(
        f"{SLACK_API}/files.completeUploadExternal",
        headers={**headers, "Content-Type": "application/json; charset=utf-8"},
        json={
            "files": [{"id": file_id, "title": file_title}],
            "channel_id": channel,
            "initial_comment": texto_final,
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"files.completeUploadExternal falló: {data}")
    log("Mensaje + reporte enviados a Slack correctamente.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-dir", required=True, help="Carpeta con el .html y los .png del reporte")
    ap.add_argument("--producto", required=True, choices=list(PRODUCTO_LABEL.keys()))
    ap.add_argument("--modo", required=True, choices=["desktop", "mobile"])
    ap.add_argument("--version", default=None)
    ap.add_argument("--urls", default=None, help="Lista separada por comas, vacío = todas")
    args = ap.parse_args()

    token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    channel = os.environ.get("SLACK_CHANNEL_ID", "").strip()
    if not token or not channel:
        log("SLACK_BOT_TOKEN o SLACK_CHANNEL_ID no configurados, salteando el envío a Slack.")
        return 0

    htmls = glob.glob(os.path.join(args.report_dir, "*.html"))
    if not htmls:
        log(f"No se encontró ningún .html en {args.report_dir}, no hay nada para enviar.")
        return 0
    html_path = sorted(htmls)[-1]

    with open(html_path, "r", encoding="utf-8") as f:
        html_original = f.read()

    version = args.version or extraer_version(html_path, args.report_dir)
    resumen, ok = extraer_resumen(html_original)
    emoji_estado = "✅" if ok else "❌"

    if args.urls:
        urls_line = f"({args.urls})"
    else:
        n = contar_urls(html_original)
        urls_line = f"({n} URLs analizadas)" if n else "(todas)"

    label = PRODUCTO_LABEL[args.producto]
    mensaje = (
        f"📣 *Regresión: {label} ({args.modo})*\n"
        f"{urls_line}\n"
        f"🌐 Entorno: prod (v{version})\n"
        f"📊 Estado: {emoji_estado} {resumen}"
    )

    standalone_html = inline_images(html_path, args.report_dir)
    standalone_path = os.path.join(
        "/tmp", f"reporte_{args.producto}_{args.modo}_v{version}_{int(time.time())}.html"
    )
    with open(standalone_path, "w", encoding="utf-8") as f:
        f.write(standalone_html)

    file_title = f"Reporte {label} {args.modo} v{version}"
    try:
        slack_post(token, channel, mensaje, standalone_path, file_title)
    except Exception as e:
        # No queremos que un problema con Slack tumbe la corrida de regresión.
        log(f"ERROR enviando a Slack (no bloqueante): {e}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
