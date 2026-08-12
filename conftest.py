"""Configuración de pytest para el proyecto."""
import sys
from pathlib import Path

# Agregar raíz del proyecto al path de Python
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))
