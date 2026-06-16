"""
BluAx — Detector de Casco de Seguridad  v1
Ocean Tech

Monitoreo continuo: detecta trabajadores sin casco y alerta por Telegram.

Instalar dependencias : pip install -r requirements.txt
Descargar modelo      : python descargar_modelo.py
Ejecutar              : python detector_casco.py
"""

import os
import io
import time
import json
import hashlib
import ssl
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from datetime import datetime

# ─── Carga .env sin dependencias externas ─────────────────────────────────────
def load_env(path='.env'):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

load_env()

# ─── Configuración ────────────────────────────────────────────────────────────
CAM_HOST      = os.environ.get('CAM_HOST',       '192.168.110.76')
CAM_PORT      = int(os.environ.get('CAM_PORT',   '80'))
CAM_USER      = os.environ.get('CAM_USER',       '')
CAM_PASS      = os.environ.get('CAM_PASS',       '')
TG_TOKEN      = os.environ.get('TELEGRAM_TOKEN', '')
TG_CHAT       = os.environ.get('TELEGRAM_CHAT_ID','')
INTERVALO_S   = int(os.environ.get('CHECK_INTERVAL', '10'))    # segundos entre capturas
CONF_MIN      = float(os.environ.get('CONF_THRESHOLD', '0.50'))# confianza mínima YOLO
COOLDOWN_S       = int(os.environ.get('ALERT_COOLDOWN',       '300'))  # 5 min — todos sin casco
COOLDOWN_MIXTO_S = int(os.environ.get('ALERT_COOLDOWN_MIXTO', '120'))  # 2 min — algunos sin casco
MODELO_PATH   = os.environ.get('MODELO_PATH', './modelo/best.pt')
SNAP_DIR      = Path(os.environ.get('SNAP_DIR', 'C:/DetectorCasco/snapshots'))
ZONA          = os.environ.get('ZONA', 'Área de trabajo')

SNAPSHOT_PATH = '/ISAPI/Streaming/channels/101/picture'

# ─── Dependencias opcionales ──────────────────────────────────────────────────
try:
    import requests
    from requests.auth import HTTPDigestAuth
    from PIL import Image, ImageDraw, ImageFont
    from ultralytics import YOLO
    DISPONIBLE = True
    print('[INFO] Dependencias cargadas correctamente')
except ImportError as e:
    DISPONIBLE = False
    print(f'[ERROR] Faltan dependencias: {e}')
    print('[ERROR] Ejecuta: pip install -r requirements.txt')

# ─── Estado global ─────────────────────────────────────────────────────────────
modelo            = None
ultimo_alerta     = 0    # timestamp último alerta "todos sin casco"
ultimo_alerta_mix = 0    # timestamp último alerta "algunos sin casco"
total_capturas    = 0
total_violaciones = 0

# ─── Log ──────────────────────────────────────────────────────────────────────
def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f'[{ts}] {msg}')

# ─── Cargar modelo YOLO ───────────────────────────────────────────────────────
def cargar_modelo():
    global modelo
    ruta = Path(MODELO_PATH)
    if not ruta.exists():
        print(f'[ERROR] No se encontró el modelo en: {ruta}')
        print('[ERROR] Ejecuta primero: python descargar_modelo.py')
        return False
    log(f'Cargando modelo: {ruta}')
    modelo = YOLO(str(ruta))
    clases = list(modelo.names.values())
    log(f'Modelo cargado — clases: {clases}')
    return True

# ─── Capturar snapshot de la cámara ──────────────────────────────────────────
def capturar_snapshot():
    url = f'http://{CAM_HOST}:{CAM_PORT}{SNAPSHOT_PATH}'
    for intento in range(3):
        try:
            r = requests.get(
                url,
                auth=HTTPDigestAuth(CAM_USER, CAM_PASS),
                timeout=10
            )
            if r.status_code == 200:
                return r.content
            if r.status_code == 503:
                # Cámara ocupada (otra conexión activa) — esperar y reintentar
                log(f'[WARN] Cámara ocupada (503) — reintento {intento + 1}/3 en 5s...')
                time.sleep(5)
                continue
            log(f'[WARN] Cámara respondió {r.status_code}')
            return None
        except Exception as e:
            if intento < 2:
                log(f'[WARN] Error de conexión ({e.__class__.__name__}) — reintento {intento + 1}/3')
                time.sleep(5)
            else:
                log(f'[ERROR] Snapshot: {e}')
    return None

# ─── Guardar snapshot en disco ────────────────────────────────────────────────
def guardar_snapshot(imagen_bytes, etiqueta=''):
    try:
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        hoy = datetime.now().strftime('%Y%m%d')
        dia_dir = SNAP_DIR / hoy
        dia_dir.mkdir(exist_ok=True)
        ts  = datetime.now().strftime('%H-%M-%S')
        nombre = f'{ts}_{etiqueta}.jpg' if etiqueta else f'{ts}.jpg'
        (dia_dir / nombre).write_bytes(imagen_bytes)
    except Exception as e:
        log(f'[WARN] guardar_snapshot: {e}')

# ─── Detectar cascos con YOLO ─────────────────────────────────────────────────
def detectar_cascos(imagen_bytes):
    """
    Retorna (violaciones, con_casco, imagen_anotada_bytes)
    violaciones : lista de detecciones SIN casco
    con_casco   : número de personas CON casco detectadas
    """
    img = Image.open(io.BytesIO(imagen_bytes)).convert('RGB')
    results = modelo(img, conf=CONF_MIN, verbose=False)

    violaciones  = []
    con_casco    = 0
    draw         = ImageDraw.Draw(img)

    try:
        font_big   = ImageFont.truetype('arial.ttf', 18)
        font_small = ImageFont.truetype('arial.ttf', 14)
    except Exception:
        font_big   = ImageFont.load_default()
        font_small = font_big

    for r in results:
        for box in r.boxes:
            cls_id   = int(box.cls[0])
            cls_name = modelo.names[cls_id]
            conf     = float(box.conf[0])
            x1, y1, x2, y2 = map(int, box.xyxy[0])

            sin_casco = any(k in cls_name.lower() for k in (
                'no-hardhat', 'no_hardhat', 'nohardhat',
                'no-helmet',  'no_helmet',  'sin casco',
                'without',    'sin'
            ))

            if sin_casco:
                violaciones.append({
                    'clase':     cls_name,
                    'confianza': round(conf * 100, 1),
                    'bbox':      (x1, y1, x2, y2)
                })
                # Caja roja con etiqueta
                draw.rectangle([x1, y1, x2, y2], outline='red', width=3)
                draw.rectangle([x1, y1 - 22, x2, y1], fill='red')
                draw.text((x1 + 4, y1 - 20), f'⚠ SIN CASCO  {conf:.0%}', font=font_small, fill='white')
            else:
                # Caja verde: lleva casco
                con_casco += 1
                draw.rectangle([x1, y1, x2, y2], outline='#00cc44', width=2)
                draw.rectangle([x1, y1 - 22, x2, y1], fill='#00cc44')
                draw.text((x1 + 4, y1 - 20), f'✓ CASCO  {conf:.0%}', font=font_small, fill='white')

    # Marca de agua en la imagen
    ts_texto = datetime.now().strftime('%d/%m/%Y  %H:%M:%S')
    draw.text((8, img.height - 24), f'BluAx · {ZONA} · {ts_texto}', font=font_small, fill='yellow')

    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=90)
    return violaciones, con_casco, buf.getvalue()

# ─── Enviar alerta a Telegram con foto ───────────────────────────────────────
def enviar_alerta_telegram(foto_bytes, caption):
    if not TG_TOKEN or not TG_CHAT:
        log('[WARN] TELEGRAM_TOKEN o TELEGRAM_CHAT_ID no configurados')
        return
    try:
        url = f'https://api.telegram.org/bot{TG_TOKEN}/sendPhoto'
        files   = {'photo': ('alerta.jpg', foto_bytes, 'image/jpeg')}
        payload = {'chat_id': TG_CHAT, 'caption': caption, 'parse_mode': 'Markdown'}
        r = requests.post(url, data=payload, files=files, timeout=15)
        if r.ok:
            log('📸 Alerta enviada a Telegram')
        else:
            log(f'[ERROR] Telegram: {r.text[:200]}')
    except Exception as e:
        log(f'[ERROR] enviar_alerta_telegram: {e}')

def enviar_texto_telegram(texto):
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        url     = f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage'
        payload = {'chat_id': TG_CHAT, 'text': texto, 'parse_mode': 'Markdown'}
        requests.post(url, json=payload, timeout=10)
    except Exception:
        pass

# ─── Ciclo principal de monitoreo ─────────────────────────────────────────────
def monitorear():
    global ultimo_alerta, ultimo_alerta_mix, total_capturas, total_violaciones

    log(f'Iniciando monitoreo — intervalo: {INTERVALO_S}s  cooldown: {COOLDOWN_S}s')
    log(f'Zona: {ZONA}  |  Cámara: {CAM_HOST}:{CAM_PORT}')

    while True:
        try:
            imagen = capturar_snapshot()
            if imagen is None:
                time.sleep(INTERVALO_S)
                continue

            total_capturas += 1
            violaciones, con_casco, img_anotada = detectar_cascos(imagen)
            total_detectados = len(violaciones) + con_casco

            if total_detectados == 0:
                log(f'[{total_capturas}] Sin personas detectadas en el área')

            elif violaciones and con_casco == 0:
                # CASO 1: Nadie lleva casco
                total_violaciones += 1
                n = len(violaciones)
                log(f'[{total_capturas}] 🚨 TODOS SIN CASCO: {n} persona(s)')
                ahora = time.time()
                if ahora - ultimo_alerta >= COOLDOWN_S:
                    ultimo_alerta = ahora
                    dt   = datetime.now()
                    hora = dt.strftime('%H:%M:%S')
                    fecha = dt.strftime('%d/%m/%Y')
                    caption = '\n'.join([
                        '🚨 *ALERTA — TRABAJADORES SIN CASCO*',
                        '',
                        f'📍 *Zona:* {ZONA}',
                        f'⛔ *Sin casco:* {n} persona(s)',
                        f'🕐 {hora}  |  📅 {fecha}',
                        '',
                        '_Ningún trabajador en el área porta casco._',
                        '_Por favor tome acción inmediata._',
                        '',
                        '_BluAx · Ocean Tech_'
                    ])
                    enviar_alerta_telegram(img_anotada, caption)
                    guardar_snapshot(img_anotada, 'TODOS_SIN_CASCO')
                else:
                    restante = int(COOLDOWN_S - (ahora - ultimo_alerta))
                    log(f'    └─ Suprimida — próxima en {restante}s')

            elif violaciones and con_casco > 0:
                # CASO 2: Mezcla — algunos con casco, algunos sin casco
                total_violaciones += 1
                n = len(violaciones)
                log(f'[{total_capturas}] ⚠  NO TODOS CUMPLEN — Sin casco: {n}  |  Con casco: {con_casco}')
                ahora = time.time()
                if ahora - ultimo_alerta_mix >= COOLDOWN_MIXTO_S:
                    ultimo_alerta_mix = ahora
                    dt   = datetime.now()
                    hora = dt.strftime('%H:%M:%S')
                    fecha = dt.strftime('%d/%m/%Y')
                    caption = '\n'.join([
                        '⚠️ *ALERTA — NO TODOS PORTAN CASCO*',
                        '',
                        f'📍 *Zona:* {ZONA}',
                        f'⛔ *Sin casco:* {n}  |  ✅ *Con casco:* {con_casco}',
                        f'🕐 {hora}  |  📅 {fecha}',
                        '',
                        '_No todos los trabajadores en el área_',
                        '_están cumpliendo con el uso de casco._',
                        '',
                        '_BluAx · Ocean Tech_'
                    ])
                    enviar_alerta_telegram(img_anotada, caption)
                    guardar_snapshot(img_anotada, 'INCUMPLIMIENTO_PARCIAL')
                else:
                    restante = int(COOLDOWN_MIXTO_S - (ahora - ultimo_alerta_mix))
                    log(f'    └─ Suprimida — próxima en {restante}s')

            else:
                # Todos llevan casco — OK
                log(f'[{total_capturas}] ✅ Todos con casco ({con_casco} persona(s)) — OK')

        except KeyboardInterrupt:
            log('Sistema detenido por el usuario.')
            break
        except Exception as e:
            log(f'[ERROR] ciclo principal: {e}')

        try:
            time.sleep(INTERVALO_S)
        except KeyboardInterrupt:
            log('Sistema detenido por el usuario.')
            break

# ─── Inicio ───────────────────────────────────────────────────────────────────
def main():
    print('╔══════════════════════════════════════════════════════════╗')
    print('║   BluAx — Detector de Casco de Seguridad  v1            ║')
    print('║   Ocean Tech                                             ║')
    print('╠══════════════════════════════════════════════════════════╣')
    print(f'║  Cámara   : {CAM_HOST}:{CAM_PORT:<44}║')
    print(f'║  Intervalo: cada {INTERVALO_S}s{"":<43}║')
    print(f'║  Cooldown : {COOLDOWN_S}s sin spam{"":<38}║')
    print(f'║  Zona     : {ZONA:<46}║')
    print('╚══════════════════════════════════════════════════════════╝')
    print()

    if not CAM_USER or not CAM_PASS:
        print('[ERROR] Faltan CAM_USER o CAM_PASS en .env')
        return
    if not TG_TOKEN or not TG_CHAT:
        print('[ERROR] Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID en .env')
        return
    if not DISPONIBLE:
        print('[ERROR] Instala las dependencias: pip install -r requirements.txt')
        return
    if not cargar_modelo():
        return

    enviar_texto_telegram(
        f'🟢 *Detector de Casco iniciado*\n'
        f'📍 Zona: {ZONA}\n'
        f'🕐 {datetime.now().strftime("%H:%M:%S")}\n'
        f'_BluAx · Ocean Tech_'
    )

    monitorear()


if __name__ == '__main__':
    main()
