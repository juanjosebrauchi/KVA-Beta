import pandas as pd
import numpy as np
from typing import Optional, Dict, Any
from utils.helpers import get_logger


class Dimensionamiento:
    """
    Clase para dimensionar sistemas eléctricos a partir de datos de demanda,
    generación y catálogos de equipos.
    """

    def __init__(self, indice: int, cliente_data: pd.Series, pdem_cliente: pd.DataFrame,
                 path_pgen: str, path_equipos: str) -> None:
        self.logger = get_logger(__name__)
        self.logger.info("Inicializando clase Dimensionamiento...")

        self.indice_cliente = indice
        self.cliente_data = cliente_data
        self.pdem_cliente = pdem_cliente
        self.path_pgen = path_pgen
        self.path_equipos = path_equipos

        # Cargar hojas de equipos
        try:
            self.eq_paneles = pd.read_excel(self.path_equipos, sheet_name="Paneles")
            self.eq_inversores = pd.read_excel(self.path_equipos, sheet_name="Inversores")
            self.eq_baterias = pd.read_excel(self.path_equipos, sheet_name="Baterias")
            self.eq_mppts = pd.read_excel(self.path_equipos, sheet_name="MPPTs")
            self.logger.info("✔️ Equipos cargados correctamente.")
            print("Equipos cargados correctamente.")
        except Exception as e:
            self.logger.error(f"❌ Error cargando equipos: {e}")
            print(f"Error cargando equipos: {e}")
            raise

    def ejecutar(self, path_pgen: Optional[str] = None, indice_cliente: Optional[int] = None) -> Dict[str, Any]:
        """
        Ejecuta el dimensionamiento para el cliente actual.

        Parameters
        ----------
        path_pgen : str, optional
            Ruta a los perfiles de generación de clientes.
        indice_cliente : int, optional
            Índice del cliente a procesar.

        Returns
        -------
        dict
            Resultados del dimensionamiento.
        """
        self.logger.info("🔄 Iniciando dimensionamiento del cliente...")
        resultados: Dict[str, Any] = {}

        try:
            tipo_solucion = self.cliente_data.get("Tipo de solución", "OnGrid")

            if tipo_solucion == "OffGrid":
                self.logger.info("⚡ Dimensionamiento OffGrid seleccionado.")
                # Aquí iría la lógica detallada de dimensionamiento OffGrid
                resultados["solucion"] = "OffGrid"

            elif tipo_solucion == "OnGrid":
                self.logger.info("⚡ Dimensionamiento OnGrid seleccionado.")
                # Aquí iría la lógica detallada de dimensionamiento OnGrid
                resultados["solucion"] = "OnGrid"

            else:
                self.logger.info("⚡ Dimensionamiento Híbrido seleccionado.")
                resultados["solucion"] = "Hibrido"

            self.logger.info("✅ Dimensionamiento finalizado.")
            return resultados
        except Exception as e:
            self.logger.exception(f"❌ Error durante el dimensionamiento: {e}")
            raise

        

class SeleccionPanel:
    """Clase auxiliar para selección de paneles solares."""

    def __init__(self, eq_paneles: pd.DataFrame):
        self.logger = get_logger(__name__)
        self.eq_paneles = eq_paneles

    def seleccionar(self, potencia_necesaria: float) -> pd.Series:
        self.logger.info("🔄 Seleccionando panel solar...")
        try:
            panel = self.eq_paneles.loc[self.eq_paneles['Potencia'] >= potencia_necesaria].iloc[0]
            self.logger.info(f"✔️ Panel seleccionado: {panel['Modelo']} ({panel['Potencia']} W)")
            return panel
        except Exception as e:
            self.logger.error(f"❌ Error seleccionando panel: {e}")
            raise


class SeleccionMPPT:
    """Clase auxiliar para selección de MPPT."""

    def __init__(self, eq_mppts: pd.DataFrame):
        self.logger = get_logger(__name__)
        self.eq_mppts = eq_mppts

    def seleccionar(self, corriente_max: float) -> pd.Series:
        self.logger.info("🔄 Seleccionando MPPT...")
        try:
            mppt = self.eq_mppts.loc[self.eq_mppts['CorrienteMax'] >= corriente_max].iloc[0]
            self.logger.info(f"✔️ MPPT seleccionado: {mppt['Modelo']} ({mppt['CorrienteMax']} A)")
            return mppt
        except Exception as e:
            self.logger.error(f"❌ Error seleccionando MPPT: {e}")
            raise


class SeleccionInversor:
    """Clase auxiliar para selección de inversores."""

    def __init__(self, eq_inversores: pd.DataFrame):
        self.logger = get_logger(__name__)
        self.eq_inversores = eq_inversores

    def seleccionar(self, potencia_necesaria: float) -> pd.Series:
        self.logger.info("🔄 Seleccionando inversor...")
        try:
            inversor = self.eq_inversores.loc[self.eq_inversores['Potencia'] >= potencia_necesaria].iloc[0]
            self.logger.info(f"✔️ Inversor seleccionado: {inversor['Modelo']} ({inversor['Potencia']} W)")
            return inversor
        except Exception as e:
            self.logger.error(f"❌ Error seleccionando inversor: {e}")
            raise
