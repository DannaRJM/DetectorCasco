"""
Descarga el modelo YOLOv8 de detección de cascos (hard hat).
Ejecutar UNA SOLA VEZ antes de iniciar el detector.

Uso: python descargar_modelo.py
"""

import subprocess
import sys
from pathlib import Path

def instalar(paquete):
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', paquete, '-q'])

print('=' * 50)
print('  BluAx — Descarga de modelo de cascos')
print('=' * 50)

# Asegurar que huggingface_hub esté instalado
try:
    import huggingface_hub
except ImportError:
    print('[INFO] Instalando huggingface_hub...')
    instalar('huggingface_hub')
    import huggingface_hub

from huggingface_hub import hf_hub_download

modelo_dir = Path('./modelo')
modelo_dir.mkdir(exist_ok=True)
destino = modelo_dir / 'best.pt'

if destino.exists():
    print(f'[OK] Modelo ya existe: {destino}')
    print('     Borra el archivo si quieres volver a descargarlo.')
else:
    print('[INFO] Descargando modelo keremberke/yolov8n-hard-hat-detection...')
    print('       (primera descarga: ~6 MB)')
    try:
        ruta = hf_hub_download(
            repo_id='keremberke/yolov8n-hard-hat-detection',
            filename='best.pt',
            local_dir=str(modelo_dir)
        )
        print(f'[OK] Modelo guardado en: {ruta}')
    except Exception as e:
        print(f'[ERROR] No se pudo descargar: {e}')
        print()
        print('Alternativa manual:')
        print('  1. Ve a: https://huggingface.co/keremberke/yolov8n-hard-hat-detection')
        print('  2. Descarga "best.pt"')
        print('  3. Colócalo en la carpeta: ./modelo/best.pt')
        sys.exit(1)

# Verificar que el modelo funciona
print()
print('[INFO] Verificando modelo...')
try:
    from ultralytics import YOLO
    m = YOLO(str(destino))
    clases = list(m.names.values())
    print(f'[OK] Modelo válido — clases detectables: {clases}')
    print()
    print('Todo listo. Ejecuta: python detector_casco.py')
except Exception as e:
    print(f'[ERROR] Modelo inválido: {e}')
    print('Instala primero: pip install -r requirements.txt')
