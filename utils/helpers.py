# utils/helpers.py
import logging
import sys

# Diccionario de colores ANSI para la consola
COLORS = {
    "INFO": "\033[94m",     # Azul
    "WARNING": "\033[93m",  # Amarillo
    "ERROR": "\033[91m",    # Rojo
    "DEBUG": "\033[92m",    # Verde
    "RESET": "\033[0m"      # Reset
}


class CustomFormatter(logging.Formatter):
    """Formato de logs con colores y timestamps."""

    def format(self, record):
        log_color = COLORS.get(record.levelname, COLORS["RESET"])
        reset = COLORS["RESET"]
        log_fmt = f"%(asctime)s - {log_color}%(levelname)s{reset} - %(message)s"
        formatter = logging.Formatter(log_fmt, "%Y-%m-%d %H:%M:%S")
        return formatter.format(record)


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
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(CustomFormatter())
        logger.addHandler(handler)

    return logger


