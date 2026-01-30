import os
import time
from dataclasses import dataclass
from stage.process import Preprocess
from stage.clients import Cliente
from stage.sizing_backup import Dimensionamiento
from stage.optimization import Optimizador
from utils.helpers import SimpleLogger

@dataclass
class Config:
    """Configuración centralizada de rutas y parámetros"""
    ruta_archivo: str = r"data/Encuesta_10clientes.xlsx"
    path_perfil_base: str = r"data/Perfil_Base.xlsx"
    path_perfil_extra: str = r"data/Perfil_Extra.xlsx"
    path_BBDD_clientes: str = r"data/BBDD_Clientes.csv"
    path_consumo_zona: str = r"data/PConsumoZone.xlsx"
    path_pgen_clientes: str = r"data/BBDD_Gen/"
    path_equipos: str = r"data/BBDD_Equipos.xlsx"

class GestorProyecto:
    """Clase orquestadora del flujo de simulación completo"""
    
    def __init__(self, config: Config):
        self.config = config
        self.resultados = {} # Almacén central de resultados
        self.logger = SimpleLogger(filename="log_ejecucion.txt")
        
    def log(self, mensaje):
        self.logger.log(mensaje)

    def ejecutar(self):
        start_time = time.time()
        self.log("🚀 Iniciando pipeline de simulación")
        
        try:
            # 1. Preprocesamiento: Carga de encuesta y selección de usuario
            self.log("▶ Paso 1: Preprocesamiento de Encuesta")
            prepro = Preprocess(self.config.ruta_archivo)
            indice, cliente_data, vector = prepro.ejecutar()
            self.resultados['indice'] = indice
            self.resultados['cliente_data'] = cliente_data
            self.log("✅ Preprocesamiento finalizado.")
            
            # 2. Cliente: Construcción de Perfiles de Demanda
            self.log("▶ Paso 2: Análisis de Cliente y Demanda")
            cliente = Cliente(
                indice, 
                cliente_data, 
                self.config.path_perfil_base, 
                self.config.path_perfil_extra, 
                self.config.path_BBDD_clientes, 
                self.config.path_consumo_zona, 
                vector_prueba=vector, 
                cliente_actual=prepro.cliente_actual,
                logger=self.logger # Inyección del logger
            )
            pdem_cliente = cliente.ejecutar()
            self.resultados['pdem_cliente'] = pdem_cliente
            self.log("✅ Perfiles de cliente generados.")
            
            # 3. Dimensionamiento Técnico: Selección de Equipos (Sizing)
            self.log("▶ Paso 3: Dimensionamiento Técnico (Generación y Equipos)")
            sizing = Dimensionamiento(
                indice, 
                cliente_data, 
                pdem_cliente, 
                self.config.path_pgen_clientes, 
                path_equipos=self.config.path_equipos,
                logger=self.logger # Logger
            )
            sizing = sizing.ejecutar()
            self.resultados['sizing'] = sizing
            self.log("✅ Dimensionamiento técnico completado.")
            
            # 4. Optimización y Evaluación Financiera
            self.log("▶ Paso 4: Optimización Económica y Flujo de Caja")
            # optimizador = Optimizador(
            #     indice, 
            #     cliente_data, 
            #     pdem_cliente, 
            #     sizing, 
            #     logger=self.logger)
            
            # # Pasamos 'self' como gestor para permitir logging centralizado desde la clase hija
            # optimizador.ejecutar(gestor=self) 
            
            elapsed = time.time() - start_time
            print("\n" + "="*50)
            self.log(f"🏁 Ejecución completada exitosamente en {elapsed:.2f} segundos.")
            print("="*50)
            
        except Exception as e:
            print("\n" + "!"*50)
            self.log(f"❌ Error crítico en la ejecución: {e}")
            import traceback
            traceback.print_exc()
            print("!"*50)

if __name__ == "__main__":
    os.system("cls" if os.name == 'nt' else 'clear')
    
    # Inicialización de configuración y gestor
    configuracion = Config()
    gestor_principal = GestorProyecto(configuracion)
    
    # Ejecución del flujo principal
    gestor_principal.ejecutar()