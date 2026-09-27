# Regresión Visual — TN / El Trece / El Doce / Ciudad Magazine

Herramienta de regresión visual/estructural que compara dos versiones de una
misma página (ej: `https://tn.com.ar/` vs `https://tn.com.ar/?d=VERSION`)
y detecta diferencias reales de layout, tamaño y estilo — filtrando los
falsos positivos que generaban los scripts anteriores.

Cubre 4 productos, cada uno con su propio script de entrada pero
compartiendo el mismo motor (`regre_visual_motor.py`) y la misma lógica de
comparación (`regre_visual_tn_core.py`), para que un fix beneficie a los
cuatro a la vez:

| Producto         | Script                     | Dominio                |
|------------------|-----------------------------|-------------------------|
| TN               | `regre_visual_tn.py`        | tn.com.ar               |
| El Trece         | `regre_visual_eltrece.py`   | eltrecetv.com.ar        |
| El Doce          | `regre_visual_eldoce.py`    | eldoce.tv               |
| Ciudad Magazine  | `regre_visual_ciudad.py`    | ciudad.com.ar           |

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

El motor (`regre_visual_motor.py`, con la lógica pura en
`regre_visual_tn_core.py`) soluciona cada uno de esos puntos para los 4
productos. El detalle completo está en los comentarios de
`regre_visual_tn_core.py` y en los tests de `test_core.py` (31 casos, cada
uno reproduce un patrón real visto en corridas anteriores).

La agrupación en cascada (`agrupar_cascadas`) cubre los 4 tipos de diferencia
que pueden ser causa raíz de un efecto dominó: posición (Y), posición (X),
alto (H) y ancho (W) — no solo posición vertical, para no listar como fallas
independientes algo como "una fila del footer desaparece y 4 contenedores
pierden los mismos 20px de alto" o "un carrusel horizontal corre 5 links el
mismo delta de X".

Además, en páginas de listado que se actualizan en vivo (ej:
`/ultimas-noticias/`), una tarjeta de noticia puede quedar emparejada por
posición con OTRA noticia distinta entre la captura de V1 y la de V2 (el
listado cambió en el medio). El script detecta esto comparando el texto real
de la tarjeta (no solo su tag/clase) y, si el contenido es distinto, no
reporta su geometría/estilo como una falla — comparar el tamaño de dos
noticias distintas no es un bug real.

## Uso local

```bash
pip install -r requirements.txt
python regre_visual_tn.py 719 --modo desktop
python regre_visual_tn.py 719 --modo mobile
python regre_visual_tn.py 719 --modo desktop --urls Homepage,Listado,Juegos
python regre_visual_tn.py 719 --modo desktop --tolerancia 4 --sin-confirmacion-visual

# Mismo uso para los otros productos:
python regre_visual_eltrece.py 719 --modo desktop
python regre_visual_eldoce.py 719 --modo mobile
python regre_visual_ciudad.py 719 --modo desktop --urls Homepage,Vivo
```

El reporte HTML y las capturas quedan en `reportes/<producto>/desktop/` o
`reportes/<producto>/mobile/` (ej. `reportes/eltrece/desktop/`).

## Tests offline (sin Selenium, sin red)

```bash
python test_core.py
```

Valida toda la lógica de comparación/agrupación/normalización con datos
sintéticos. Correrlos antes de tocar `regre_visual_tn_core.py`.

## GitHub Actions

El workflow `.github/workflows/regresion-visual.yml` se dispara a mano
desde la pestaña **Actions** del repo (`Run workflow`), pidiendo:

- **producto**: `tn`, `eltrece`, `eldoce` o `ciudad`.
- **version**: el número de versión a testear.
- **modo**: `desktop`, `mobile` o `ambos`.
- **urls** (opcional): subconjunto de páginas a testear.
- **tolerancia** (opcional, default 3px).

Primero corre los tests offline; si pasan, corre la(s) regresión(es) y sube
el reporte + capturas como *artifact* descargable desde la misma corrida
(pestaña Actions → la corrida → Artifacts).

## Estructura

```
regre_visual_tn.py         # config de producto: BASE_URLS_MAP de TN
regre_visual_eltrece.py    # config de producto: BASE_URLS_MAP de El Trece
regre_visual_eldoce.py     # config de producto: BASE_URLS_MAP de El Doce
regre_visual_ciudad.py     # config de producto: BASE_URLS_MAP de Ciudad Magazine
regre_visual_motor.py      # motor compartido: Selenium, extracción, marcado, reporte HTML
regre_visual_tn_core.py    # lógica pura de comparación (sin Selenium, testeable offline)
test_core.py               # 31 tests offline de la lógica de comparación
requirements.txt
.github/workflows/regresion-visual.yml
reportes/                  # salida por producto (gitignoreada, salvo la carpeta)
```
