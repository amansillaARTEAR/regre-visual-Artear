# Regresión Visual TN

Herramienta de regresión visual/estructural que compara dos versiones de una
misma página de TN (ej: `https://tn.com.ar/` vs `https://tn.com.ar/?d=VERSION`)
y detecta diferencias reales de layout, tamaño y estilo — filtrando los
falsos positivos que generaban los scripts anteriores.

## Qué mejora respecto a la versión anterior

Los dos scripts previos (`regre_visual_tn_desk_prod2.py` y
`regre_visual_tn_webmobile.py`) generaban muchos falsos positivos por:

- Selector basado en `nth-child`: insertar o mover un solo elemento rompía
  la identidad de todos los elementos siguientes.
- Tolerancia de píxeles en 0: cualquier subpíxel de antialiasing fallaba.
- Comparación de V1 y V2 en vivo, sin filtrar ads/contenido de terceros
  (Teads, recomendados, cotizaciones) que cambia entre una corrida y otra
  sin que el sitio haya cambiado.
- Un solo elemento que cambia de alto (un ad que carga distinto) generaba
  decenas de fallas en cascada, todas listadas como si fueran independientes.
- Comparación de estilos por string exacto, sin normalizar `rgb()` vs
  `rgba()`, `font-weight: normal` vs `400`, etc.

Este script (`regre_visual_tn.py`, con la lógica en `regre_visual_tn_core.py`)
soluciona cada uno de esos puntos. El detalle completo está en los
comentarios de `regre_visual_tn_core.py` y en los tests de `test_core.py`
(9 casos, cada uno reproduce un patrón real visto en corridas anteriores).

## Uso local

```bash
pip install -r requirements.txt
python regre_visual_tn.py 719 --modo desktop
python regre_visual_tn.py 719 --modo mobile
python regre_visual_tn.py 719 --modo desktop --urls Homepage,Listado,Juegos
python regre_visual_tn.py 719 --modo desktop --tolerancia 4 --sin-confirmacion-visual
```

El reporte HTML y las capturas quedan en `reportes/desktop/` o
`reportes/mobile/`.

## Tests offline (sin Selenium, sin red)

```bash
python test_core.py
```

Valida toda la lógica de comparación/agrupación/normalización con datos
sintéticos. Correrlos antes de tocar `regre_visual_tn_core.py`.

## GitHub Actions

El workflow `.github/workflows/regresion-visual.yml` se dispara a mano
desde la pestaña **Actions** del repo (`Run workflow`), pidiendo:

- **version**: el número de versión a testear.
- **modo**: `desktop`, `mobile` o `ambos`.
- **urls** (opcional): subconjunto de páginas a testear.
- **tolerancia** (opcional, default 3px).

Primero corre los tests offline; si pasan, corre la(s) regresión(es) y sube
el reporte + capturas como *artifact* descargable desde la misma corrida
(pestaña Actions → la corrida → Artifacts).

## Estructura

```
regre_visual_tn.py         # orquestación con Selenium (captura, screenshots, reporte HTML)
regre_visual_tn_core.py    # lógica pura de comparación (sin Selenium, testeable offline)
test_core.py               # 9 tests offline de la lógica de comparación
requirements.txt
.github/workflows/regresion-visual.yml
reportes/                  # salida (gitignoreada, salvo la carpeta)
```
