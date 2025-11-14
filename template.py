import logging
from typing import Any, Dict, List, Optional

class MiClase:
    """
    Clase ejemplo para mostrar buenas prácticas en OOP en Python.

    Attributes
    ----------
    atributo1 : str
        Descripción del atributo.
    atributo2 : int
        Otro atributo de ejemplo.
    """

    def __init__(self, atributo1: str, atributo2: int = 0) -> None:
        """
        Inicializa la clase con sus atributos.

        Parameters
        ----------
        atributo1 : str
            Descripción del atributo.
        atributo2 : int, optional
            Valor inicial (por defecto 0).
        """
        self._atributo1 = atributo1  # privado por convención
        self.atributo2 = atributo2   # público
        logging.debug(f"Clase inicializada con {atributo1=}, {atributo2=}")

    @property
    def atributo1(self) -> str:
        """Getter para atributo1."""
        return self._atributo1

    @atributo1.setter
    def atributo1(self, value: str) -> None:
        """Setter para atributo1 con validación."""
        if not isinstance(value, str):
            raise ValueError("atributo1 debe ser un string")
        self._atributo1 = value

    def ejecutar(self) -> Dict[str, Any]:
        """
        Método principal de ejecución de la clase.

        Returns
        -------
        dict
            Resultados del proceso.
        """
        logging.info("Ejecutando proceso principal...")
        # Lógica aquí
        return {"status": "ok", "resultado": self.atributo2 * 2}

    def __str__(self) -> str:
        """Representación amigable de la clase."""
        return f"MiClase({self._atributo1}, {self.atributo2})"