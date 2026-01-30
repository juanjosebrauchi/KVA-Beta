# utils/helpers.py
import logging
import sys

def get_logger(nombre: str = "app", nivel=logging.INFO) -> logging.Logger:
    """
    Devuelve un logger configurado para todo el proyecto.

    Parameters
    ----------
    nombre : str
        Nombre del logger (normalmente __name__).
    nivel : int
        Nivel de logging (INFO, DEBUG, WARNING, ERROR).

    Returns
    -------
    logging.Logger
    """
    logger = logging.getLogger(nombre)
    logger.setLevel(nivel)

    # Evita añadir múltiples handlers si ya existe
    if not logger.handlers:
        # 1. Handler de Consola (con colores)
        c_handler = logging.StreamHandler(sys.stdout)
        c_handler.setFormatter(CustomFormatter())
        logger.addHandler(c_handler)
        
        # 2. Handler de Archivo (sin colores, texto plano)
        f_handler = logging.FileHandler("log_ejecucion.txt", mode='w', encoding='utf-8')
        f_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s', "%Y-%m-%d %H:%M:%S")
        f_handler.setFormatter(f_format)
        logger.addHandler(f_handler)

    return logger

class SimpleLogger:
    """
    Logger simplificado personalizado para escribir en consola y archivo simultáneamente.
    """
    def __init__(self, filename="log_ejecucion.txt"):
        self.filename = filename
        # Limpiar/Iniciar archivo
        with open(self.filename, "w", encoding="utf-8") as f:
            import time
            f.write(f"--- Inicio de Ejecución: {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    
    def log(self, mensaje, prefijo="Gestor"):
        import time
        timestamp = time.strftime('%H:%M:%S')
        texto_completo = f"[{timestamp}] [{prefijo}] {mensaje}"
        
        # 1. Consola
        print(texto_completo)
        
        # 2. Archivo
        with open(self.filename, "a", encoding="utf-8") as f:
            f.write(texto_completo + "\n")



