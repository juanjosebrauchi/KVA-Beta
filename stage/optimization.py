import pandas as pd
import numpy as np
import os
import time
import traceback
from typing import Dict, List, Optional
from pytoolconfig import dataclass
try:
    import numpy_financial as npf
except ImportError:
    npf = None
import pyomo.environ as pyo
from pyomo.opt import SolverFactory

class Optimizador:
    # ── Modo Debug ────────────────────────────────────────────────────────────
    # Cambiar DEBUG_MODE a True para activar el modo debug.
    # Definir en DEBUG_CONFIG los perfiles y overrides deseados.
    # main.py no necesita ningún cambio.
    DEBUG_MODE = True
    DEBUG_FILE = r"data/Dim_Debug.xlsx"   # Ruta al archivo Excel de debug
    DEBUG_MES  = 'Julio'              # Mes a analizar en modo DEBUG (nombre o entero 1-12)
    DEBUG_GRAFICO = True              # Mostrar gráfico de despacho en modo DEBUG
    DEBUG_CONFIG = {
        # Los parámetros de operación (cap_fv, cap_bat, ongrid, pmax_diesel, etc.)
        # se toman desde la hoja Dim del archivo DEBUG_FILE.

        # --- Inversiones para flujo de caja (criterio Min Precio) ---
        # Puedes forzarlas aquí; si no, se tomarán desde hoja Dim/etapas previas.
        'inv_fv': 1240000.0,
        'inv_storage': 915000.0,
        'inv_inv_fv': 0.0,
        'inv_inv_storage': 3240000.0,
        'inv_estructura': 500000.0,
        'inv_materiales': 500000.0,

        # --- Parámetros financieros de flujo de caja ---
        # Solo en DEBUG puedes cambiar la tecnología. En ejecución normal se usa LITIO.
        'tecnologia_bateria': 'LITIO',
        'horizonte': 20,
        'tasa_descuento': 0.06,
        'costo_energia': 0.15,
        'costo_potencia_suministrada': 0.0,
        'costo_potencia_punta': 0.0,
        'precio_inyeccion': 0.05,
        'incremento_precio_anual': 0.05,
        'caida_eficiencia_fv_anual': 0.007,
        'incremento_mantencion_anual': 0.05,
        'mant_fv_pct': 0.006,
        'mant_storage_pct': 0.01,
        'recambio_inversor': 10,
    }
    # ──────────────────────────────────────────────────────────────────────────

    def __init__(self, indice, cliente_data, pdem_cliente, dimension, path_pgen_clientes, logger=None):
        """
        Inicializa el optimizador.
        :param indice: Índice del cliente.
        :param cliente_data: Diccionario con datos del cliente.
        :param pdem_cliente: Perfil de demanda del cliente.
        :param dimension: Resultados de la etapa de dimensionamiento (sizing).
        :param path_pgen_clientes: Ruta a la carpeta con perfiles de generación.
        """
        self.indice = indice
        self.cliente_data = cliente_data
        self.pdem_cliente = pdem_cliente
        self.dimension = dimension
        self.path_pgen_clientes = path_pgen_clientes
        self.logger = logger
        # Atributos para almacenar estado y resultados
        self.params = {}
        self.model = None
        self.resultados_opt = {}
        self.df_flujo = None
        self.pgen_cliente = None # Variable para almacenar el perfil de generación
        self.array_pdem = None
        self.array_pgen = None
        # Debug mode
        self.debug_mode = False
        self.debug_overrides = {}
        # Resultados post-análisis: {nombre_mes: DataFrame}
        self.dfs_post_analisis = {}

    @dataclass
    class MicrogridUCData:
        T: list[int]
        demand: Dict[int, float]
        pv_avail: Dict[int, float]
        
        ## Diesel [UC]
        pmin_diesel: float
        pmax_diesel: float
        cost_diesel: float
        var_cost_diesel: float
        startup_cost_diesel: float = 0.0
        shutdown_cost_diesel: float = 0.0
        ramp_up_diesel: float = 1e6
        ramp_down_diesel: float = 1e6
        min_up_time_diesel: int = 0
        min_down_time_diesel: int = 0
        u_unit_diesel: int = 0
        p_init_d: float = 0.0

        ## Baterías [UC]
        e_init: float = 0.0
        e_min: float = 0.0
        e_max: float = 0.0
        p_ch_max: float = 0.0
        p_dis_max: float = 0.0
        eff_ch: float = 0.95
        eff_dis: float = 0.95
        e_final_min: Optional[float] = None
        batt_cycle_cost: float = 0.0
        no_simultaneous_charge_discharge: bool = True

        ## Grid (on-grid)
        ongrid: bool = False
        grid_buy_price: Optional[Dict[int, float]] = None
        grid_sell_price: Optional[Dict[int, float]] = None  
        p_imp_max: Optional[float] = None
        p_exp_max: Optional[float] = None   
        no_simultaneous_imp_exp: bool = True

        ## Load shedding
        allow_ls: bool = True
        ls_penalty: float = 10000.0

    def activar_debug(self, array_pdem=None, array_pgen=None, **overrides):
        """
        Activa el modo debug del optimizador.

        Parámetros:
        -----------
        array_pdem : np.ndarray, shape (12, 24), opcional
            Perfil de demanda a inyectar directamente (Meses x Horas) [kW].
            Si se omite, se reutiliza el que ya esté cargado en self.array_pdem.
        array_pgen : np.ndarray, shape (12, 24), opcional
            Perfil de generación PV normalizado a 1 kWp (Meses x Horas) [kW/kWp].
            Si se omite, se reutiliza el que ya esté cargado en self.array_pgen.
        **overrides : cualquier campo de MicrogridUCData o params
            Ejemplos: cap_fv=10.0, cap_bat=20.0, e_init=5.0,
                      pmax_diesel=15.0, ongrid=False, ls_penalty=500.0
            Los campos de MicrogridUCData se aplican al construir common_data.
            Los campos 'cap_fv' y 'cap_bat' sobreescriben self.params directamente.
        """
        self.debug_mode = True
        if array_pdem is not None:
            self.array_pdem = np.array(array_pdem, dtype=float)
        if array_pgen is not None:
            self.array_pgen = np.array(array_pgen, dtype=float)
        self.debug_overrides = dict(overrides)
        self.log(f"🐛 Modo DEBUG activado. Overrides: {list(self.debug_overrides.keys()) or 'ninguno'}")

    def _leer_debug_excel(self):
        """
        Lee las hojas 'PGen', 'PDem' y 'Dim' del archivo Dim_Debug.xlsx.

        Hojas de perfiles (PGen / PDem):
            Columna 0 : índice de mes (cabecera de fila, se usa como index)
            Columnas 1-24 : valores hora 0 a hora 23  →  array (12, 24)

        Hoja Dim:
            Dos columnas con cabecera:  'parametro' | 'valor'
            Cada fila define un override que se inyectará en common_data
            (equivalente a escribirlo en DEBUG_CONFIG).
            Parámetros reconocidos: cualquier campo de MicrogridUCData
            más 'cap_fv' y 'cap_bat'.

            Ejemplo de contenido:
                parametro        | valor
                cap_fv           | 10.0
                cap_bat          | 20.0
                e_init           | 10.0
                pmax_diesel      | 0.0
                ongrid           | True
                ls_penalty       | 500.0
        """
        ruta = self.__class__.DEBUG_FILE
        if not os.path.exists(ruta):
            self.log(f"❌ [DEBUG] Archivo no encontrado: {ruta}")
            return

        try:
            # --- PGen ---
            df_pgen = pd.read_excel(ruta, sheet_name='PGen', header=0, index_col=0)
            if df_pgen.shape != (12, 24):
                self.log(f"⚠️ [DEBUG] PGen tiene forma {df_pgen.shape}, se esperaba (12, 24).")
            self.array_pgen = df_pgen.values.astype(float)
            self.log(f"🐛 [DEBUG] PGen cargado desde Excel. Forma: {self.array_pgen.shape}")

            # --- PDem ---
            df_pdem = pd.read_excel(ruta, sheet_name='PDem', header=0, index_col=0)
            if df_pdem.shape != (12, 24):
                self.log(f"⚠️ [DEBUG] PDem tiene forma {df_pdem.shape}, se esperaba (12, 24).")
            self.array_pdem = df_pdem.values.astype(float)
            self.log(f"🐛 [DEBUG] PDem cargado desde Excel. Forma: {self.array_pdem.shape}")

            # --- Dim ---
            _bool_map = {'true': True, 'false': False, '1': True, '0': False}
            _int_fields = {
                'min_up_time_diesel', 'min_down_time_diesel', 'u_unit_diesel',
            }
            # Alias: nombre del Excel → nombre interno (1 a 1)
            _alias_map = {
                'cost_battery':   'batt_cycle_cost',
                'bat_cycle_cost': 'batt_cycle_cost',
            }
            # Expansión: un nombre del Excel → varios campos internos
            _expand_map = {
                'pot_inversor': ['p_ch_max', 'p_dis_max'],
            }
            # Escalares que se deben transmitir como dict en resolver_optimizacion
            _scalar_broadcast_map = {
                'cost_grid':      '_cost_grid_scalar',
                'cost_grid_sell': '_cost_grid_sell_scalar',
            }
            try:
                df_dim = pd.read_excel(ruta, sheet_name='Dim', header=0)
                df_dim.columns = [c.strip().lower() for c in df_dim.columns]
                if 'parametro' not in df_dim.columns or 'valor' not in df_dim.columns:
                    self.log("⚠️ [DEBUG] Hoja 'Dim' debe tener columnas 'parametro' y 'valor'. Se ignora.")
                else:
                    dim_overrides = {}
                    for _, row in df_dim.dropna(subset=['parametro', 'valor']).iterrows():
                        key = str(row['parametro']).strip().lower()  # normalizar a minúsculas
                        raw = row['valor']
                        # Conversión de tipo
                        if isinstance(raw, bool):                    # bool nativo de Excel (True/False)
                            val = raw
                        else:
                            # Si es str, limpiar comillas envolventes (ej. '"False"' → 'False')
                            if isinstance(raw, str):
                                raw = raw.strip().strip('"\'')
                            if isinstance(raw, str) and raw.lower() in _bool_map:
                                val = _bool_map[raw.lower()]
                            elif key in _int_fields:
                                val = int(raw)
                            else:
                                try:
                                    val = float(raw)
                                except (ValueError, TypeError):
                                    val = raw
                        # Expansión (1 key → varios campos internos)
                        if key in _expand_map:
                            for internal_key in _expand_map[key]:
                                dim_overrides[internal_key] = val
                                self.log(f"🐛 [DEBUG] Dim override → {internal_key} = {val}  (desde '{key}')")
                        # Broadcast escalar (se resolverá en resolver_optimizacion)
                        elif key in _scalar_broadcast_map:
                            internal_key = _scalar_broadcast_map[key]
                            dim_overrides[internal_key] = val
                            self.log(f"🐛 [DEBUG] Dim override → {internal_key} = {val}  (desde '{key}')")
                        # Alias simple
                        else:
                            internal_key = _alias_map.get(key, key)
                            dim_overrides[internal_key] = val
                            label = f"{internal_key}  (desde '{key}')" if internal_key != key else key
                            self.log(f"🐛 [DEBUG] Dim override → {label} = {val}")
                    # Fusionar con DEBUG_CONFIG (el Excel tiene prioridad)
                    merged = {**self.__class__.DEBUG_CONFIG, **dim_overrides}
                    self.__class__._dim_overrides_cache = merged
            except Exception as e_dim:
                self.log(f"⚠️ [DEBUG] No se pudo leer hoja 'Dim': {e_dim}")
                self.__class__._dim_overrides_cache = dict(self.__class__.DEBUG_CONFIG)

        except Exception as e:
            self.log(f"❌ [DEBUG] Error leyendo Dim_Debug.xlsx: {e}")

    def log(self, mensaje):
        if self.logger:
            self.logger.log(mensaje, prefijo="Optimizador")
        else:
            print(f"[Optimizador] {mensaje}")

    def ejecutar(self):
        """
        Ejecuta el flujo completo de optimización.
        """
        self.log(f"🚀 Iniciando proceso para cliente {self.indice}...")

        # Activar modo debug si el flag de clase está encendido
        if self.__class__.DEBUG_MODE:
            self.__class__._dim_overrides_cache = {}
            self._leer_debug_excel()
            self.log(f"🐛 [DEBUG] _dim_overrides_cache = {self.__class__._dim_overrides_cache}")
            self.activar_debug(**self.__class__._dim_overrides_cache)

        # 1. Lectura y preparación de parámetros
        self.leer_parametros()
        
        # 2. Construcción y resolución del modelo de optimización
        # Optimización anual: 12 meses × 24 horas = 288 periodos
        self.resolver_optimizacion()
        
        # 3. Post-análisis de los resultados técnicos
        if self.__class__.DEBUG_MODE:
            # DEBUG: analiza solo DEBUG_MES y muestra el gráfico de forma interactiva.
            self.post_analisis(self.__class__.DEBUG_MES)
            self.graficar_mes(self.__class__.DEBUG_MES, mostrar=True)
        else:
            # PRODUCCIÓN: calcula los 12 meses.
            self.post_analisis()

        # 4. Evaluación económica (Flujo de Caja)
        self.flujo_caja()

        # 5. En producción, exportar ZIP con gráficos mensuales + flujo de caja
        if not self.__class__.DEBUG_MODE:
            self.exportar_graficos_zip()
        
        self.log("✅ Proceso finalizado.")

    def leer_parametros(self):
        """
        Extrae y prepara los parámetros necesarios desde cliente_data y dimension.
        Mantiene los arrays de Demanda y Generación en formato estandarizado (12, 24) [Meses x Horas].
        """
        self.log("📖 [1/4] Leyendo parámetros de entrada...")
        
        # Configurar numpy para impresión limpia
        np.set_printoptions(suppress=True, precision=6)

        # --- MODO DEBUG: saltar carga de archivos si los arrays ya fueron inyectados ---
        if self.debug_mode and self.array_pdem is not None and self.array_pgen is not None:
            self.log("🐛 [DEBUG] Usando perfiles inyectados manualmente (pdem y pgen).")
            self.log(f"🐛 [DEBUG] PDEM shape: {self.array_pdem.shape} | PGEN shape: {self.array_pgen.shape}")
            self.log(f"🐛 [DEBUG] debug_overrides = {self.debug_overrides}")
            # Aplicar overrides de capacidades si los hay
            if 'cap_fv' in self.debug_overrides:
                self.params['capacidad_fv'] = self.debug_overrides['cap_fv']
            else:
                self.params.setdefault('capacidad_fv', 0.0)
            if 'cap_bat' in self.debug_overrides:
                self.params['baterias_cap'] = self.debug_overrides['cap_bat']
            else:
                self.params.setdefault('baterias_cap', 0.0)
            self.params.setdefault('costo_capex', 0)

            # Overrides de inversión para flujo de caja (criterio Min Precio)
            # Se pueden definir en DEBUG_CONFIG o en la hoja Dim del Excel debug.
            _inv_keys = [
                'inv_storage',
                'inv_fv',
                'inv_inv_fv',
                'inv_inv_storage',
                'inv_estructura',
                'inv_materiales',
            ]
            for _k in _inv_keys:
                self.params[_k] = float(self.debug_overrides.get(_k, self.params.get(_k, 0.0)))
            self.params['costo_capex'] = float(self.debug_overrides.get('costo_capex', self.params.get('costo_capex', 0.0)))

            # Overrides financieros para flujo de caja
            _fc_float_keys = [
                'horizonte',
                'tasa_descuento',
                'costo_energia',
                'costo_potencia_suministrada',
                'costo_potencia_punta',
                'precio_inyeccion',
                'incremento_precio_anual',
                'caida_eficiencia_fv_anual',
                'incremento_mantencion_anual',
                'mant_fv_pct',
                'mant_storage_pct',
                'recambio_inversor',
            ]
            for _k in _fc_float_keys:
                if _k in self.debug_overrides:
                    self.params[_k] = float(self.debug_overrides[_k])
            if 'tecnologia_bateria' in self.debug_overrides:
                self.params['tecnologia_bateria'] = str(self.debug_overrides['tecnologia_bateria'])

            cfg = self.cliente_data if hasattr(self.cliente_data, 'get') else {}
            self.params['ongrid'] = self.debug_overrides.get('ongrid', cfg.get('ongrid', True))
            self.params['no_simultaneous_charge_discharge'] = self.debug_overrides.get(
                'no_simultaneous_charge_discharge', cfg.get('no_simultaneous_charge_discharge', True))
            self.params['no_simultaneous_imp_exp'] = self.debug_overrides.get(
                'no_simultaneous_imp_exp', cfg.get('no_simultaneous_imp_exp', True))
            self.params['allow_ls'] = self.debug_overrides.get('allow_ls', cfg.get('allow_ls', True))
            self.log(
                "💼 [DEBUG] Inversiones forzadas flujo caja → "
                f"FV={self.params['inv_fv']:.0f}, Storage={self.params['inv_storage']:.0f}, "
                f"InvFV={self.params['inv_inv_fv']:.0f}, InvStorage={self.params['inv_inv_storage']:.0f}, "
                f"Estructura={self.params['inv_estructura']:.0f}, Materiales={self.params['inv_materiales']:.0f}"
            )
            self.log(f"🐛 [DEBUG] params activos: {self.params}")
            return

        # --- 1. Guardar pdem_cliente (Primer Array) ---
        # Asegurar que es numpy array
        if hasattr(self.pdem_cliente, 'values'):
            raw_pdem = self.pdem_cliente.values
        else:
            raw_pdem = np.array(self.pdem_cliente)

        # Estandarización: Queremos formato (12, 24) -> (Meses, Horas)
        # Si viene en formato (24, 12) -> (Horas, Meses), lo transponemos
        if raw_pdem.shape == (24, 12):
            self.array_pdem = raw_pdem.T
            self.log(f"🔄 PDEM estandarizado: Transpuesto de {raw_pdem.shape} a {self.array_pdem.shape} (Meses x Horas)")
        else:
            self.array_pdem = raw_pdem
            self.log(f"ℹ️ PDEM cargado con forma: {self.array_pdem.shape}")
        
        # --- 2. Cargar y guardar Perfil de Generación (Segundo Array) ---
        aux = self.indice + 1
        codigo = f"{int(aux):02d}"
        archivo_cliente = None
        
        if os.path.exists(self.path_pgen_clientes):
            archivos = os.listdir(self.path_pgen_clientes)
            for archivo in archivos:
                if archivo.startswith(f"PGEN_{codigo}_") and archivo.endswith(".xlsx"):
                    archivo_cliente = archivo
                    break
        
        if archivo_cliente:
            try:
                ruta_completa = os.path.join(self.path_pgen_clientes, archivo_cliente)
                self.log(f"📂 Cargando perfil de generación: {archivo_cliente}")
                
                # Cargar hoja 'pv' y extraer rango específico
                df_aux = pd.read_excel(ruta_completa, sheet_name='pv', header=None)
                # Rango original: filas 6 a 17 (índices 5:17), columnas C a Z (índices 2:26) -> Resulta en (12, 24)
                df_rango = df_aux.iloc[5:17, 2:26]
                
                # Guardar como array (Segundo Array)
                # Al ser (12, 24) por lectura directa, ya cumple el estándar deseado
                self.array_pgen = np.array(df_rango.values, dtype=float)
                self.log(f"✅ PGEN estandarizado y cargado. Forma: {self.array_pgen.shape} (Meses x Horas)")
                
            except Exception as e:
                self.log(f"❌ Error al leer PGEN: {e}")
                self.array_pgen = None
        else:
            self.log(f"⚠️ Archivo PGEN no encontrado para cliente {codigo} en {self.path_pgen_clientes}")
            self.array_pgen = None
        
        # print("PDEM:", self.array_pdem[0,:]) # Imprime el segundo mes para verificar formato

        # print("--")
        # print("PGEN:", self.array_pgen)

        # Validar si dimension trae datos
        if not self.dimension:
            self.log("⚠️ Advertencia: 'dimension' está vacío o es None. Se usarán valores por defecto.")
            # Valores default para evitar crash
            self.params['capacidad_fv'] = 5.0 # kW
            self.params['baterias_cap'] = 10.0 # kWh
            self.params['costo_capex'] = 5000 # USD
        else:
            # Extraer información alineada con la estructura de 'resultados_etapa'
            self.params['capacidad_fv'] = self.dimension.get('potencia_panel_total', 0)
            self.params['baterias_qty'] = self.dimension.get('num_baterias', 0)
            self.params['costo_capex'] = self.dimension.get('costo_total_inversion', 0)
            self.params['dimensionamiento_total'] = self.dimension.get('dimensionamiento_total', {})
            # Desglose de inversiones para flujo de caja (criterio Min Precio desde sizing)
            self.params['inv_fv'] = self.dimension.get('inv_fv', 0.0)
            self.params['inv_mppt'] = self.dimension.get('inv_mppt', 0.0)
            self.params['inv_inv_fv'] = self.dimension.get('inv_inv_fv', 0.0)
            self.params['inv_inv_storage'] = self.dimension.get('inv_inv_storage', 0.0)
            self.params['inv_storage'] = self.dimension.get('inv_storage', 0.0)
            self.params['inv_estructura'] = self.dimension.get('inv_estructura', 0.0)
            self.params['inv_materiales'] = self.dimension.get('inv_materiales', 0.0)
            self.params['criterio_inversion'] = self.dimension.get('criterio_inversion', 'Min_Precio')
            
            # Calculamos la capacidad total de baterías si tenemos cantidad
            # Asumimos una capacidad nominal por batería si no está explícita (ej. 2.4 kWh para 48V/50Ah)
            CAPACIDAD_NOMINAL_UNITARIA = 2.4 
            self.params['baterias_cap'] = self.params['baterias_qty'] * CAPACIDAD_NOMINAL_UNITARIA
            self.log(
                "💼 Inversiones (sizing - Min Precio) → "
                f"FV={self.params['inv_fv']:.0f}, MPPT={self.params['inv_mppt']:.0f}, "
                f"InvFV={self.params['inv_inv_fv']:.0f}, InvStorage={self.params['inv_inv_storage']:.0f}, "
                f"Bat={self.params['inv_storage']:.0f}, Estructura={self.params['inv_estructura']:.0f}, "
                f"Materiales={self.params['inv_materiales']:.0f}"
            )

        # Configuración operativa del modelo (editable desde cliente_data si existe).
        cfg = self.cliente_data if hasattr(self.cliente_data, 'get') else {}
        self.params['ongrid'] = cfg.get('ongrid', True)
        self.params['no_simultaneous_charge_discharge'] = cfg.get('no_simultaneous_charge_discharge', True)
        self.params['no_simultaneous_imp_exp'] = cfg.get('no_simultaneous_imp_exp', True)
        self.params['allow_ls'] = cfg.get('allow_ls', True)

        print(self.params)
        # # Parámetros económicos desde data cliente o defaults
        # # Asumiendo estructura de cliente_data
 

    def resolver_optimizacion(self):
        """
        Define y resuelve el modelo matemático con Pyomo.
        Optimización anual: 12 meses × 24 horas = 288 periodos con ciclicidad mensual de SOC.
        """
        self.log("⚙️ [2/4] Resolviendo optimización matemática...")
        
        # --- Construir datos de entrada desde atributos de clase ---
        cap_fv = self.params.get('capacidad_fv', 0.0)
        cap_bat = self.params.get('baterias_cap', 0.0)
        
        self.log("📅 Modo: Optimización anual (288 periodos = 12 meses × 24 horas)")
        
        # Validar que tengamos datos completos
        if self.array_pdem is None or self.array_pdem.shape[0] < 12:
            self.log("⚠️ Error: Se requieren 12 meses de datos de demanda para optimización anual.")
            return
        
        if self.array_pgen is None or self.array_pgen.shape[0] < 12:
            self.log("⚠️ Warning: Faltan datos de generación, usando 0.")
            self.array_pgen = np.zeros((12, 24))
        
        # Construir diccionarios para 288 periodos
        # Periodo t = mes*24 + hora, donde t ∈ [0, 287]
        demand_dict = {}
        pv_avail_dict = {}
        
        for mes in range(12):
            for hora in range(24):
                t = mes * 24 + hora  # Periodo global [0-287]
                demand_dict[t] = self.array_pdem[mes, hora]
                pv_avail_dict[t] = self.array_pgen[mes, hora]  # Ya en kW absolutos (calculado por sizing)
        
        horizonte = list(range(288))  # 0 a 287
        self.log(f"📊 Total demanda anual: {sum(demand_dict.values()):.2f} kWh")
        self.log(f"📊 Total generación anual: {sum(pv_avail_dict.values()):.2f} kWh")
        
        # --- Precios de red ---
        # Extender precios para el horizonte correspondiente
        precio_base_compra = 0.15  # USD/kWh
        precio_base_venta = 0.05   # USD/kWh
        if self.debug_mode and '_cost_grid_scalar' in self.debug_overrides:
            precio_base_compra = float(self.debug_overrides['_cost_grid_scalar'])
            precio_base_venta  = round(precio_base_compra * 0.6, 6)
            self.log(f"🐛 [DEBUG] cost_grid override → compra = {precio_base_compra} USD/kWh | venta = {precio_base_venta} USD/kWh (60%)")
        if self.debug_mode and '_cost_grid_sell_scalar' in self.debug_overrides:
            precio_base_venta = float(self.debug_overrides['_cost_grid_sell_scalar'])
            self.log(f"🐛 [DEBUG] cost_grid_sell override → venta = {precio_base_venta} USD/kWh")
        precio_compra = {t: precio_base_compra for t in horizonte}
        precio_venta  = {t: precio_base_venta  for t in horizonte}

        # Configuracion operativa configurable desde params.
        ongrid_flag    = bool(self.params['ongrid'])
        no_sim_bat_flag  = bool(self.params['no_simultaneous_charge_discharge'])
        no_sim_grid_flag = bool(self.params['no_simultaneous_imp_exp'])
        allow_ls_flag    = bool(self.params['allow_ls'])
        self.log(f"⚙️  Flags del modelo → ongrid={ongrid_flag} | allow_ls={allow_ls_flag} | no_sim_bat={no_sim_bat_flag} | no_sim_grid={no_sim_grid_flag}")
        
        # --- Construir objeto de datos ---
        common_data = {
            # Diesel parameters (si no se usa, pmax_diesel=0)
            'pmin_diesel': 0.0,
            'pmax_diesel': 0.0,  # No diesel por defecto
            'cost_diesel': 0.0,
            'var_cost_diesel': 0.2,
            # Battery parameters
            'e_init': cap_bat * 0.5 if cap_bat > 0 else 0.0,
            'e_min': cap_bat * 0.2 if cap_bat > 0 else 0.0,
            'e_max': cap_bat,
            'p_ch_max': cap_bat / 2.0 if cap_bat > 0 else 0.0,
            'p_dis_max': cap_bat / 2.0 if cap_bat > 0 else 0.0,
            'no_simultaneous_charge_discharge': no_sim_bat_flag,
            'eff_ch': 0.95,
            'eff_dis': 0.95,
            'e_final_min': cap_bat * 0.5 if cap_bat > 0 else None,  # Ciclicidad anual
            # Grid parameters
            'ongrid': ongrid_flag,
            'grid_buy_price': precio_compra,
            'grid_sell_price': precio_venta,
            'p_imp_max': 100.0,
            'p_exp_max': 0.0,  # Sin exportación a red (consistente con modelo Excel)
            'no_simultaneous_imp_exp': no_sim_grid_flag,
            # Load shedding
            'allow_ls': allow_ls_flag,
            'ls_penalty': 10000.0,
        }

        # --- MODO DEBUG: aplicar overrides de MicrogridUCData ---
        if self.debug_mode and self.debug_overrides:
            _microgrid_fields = {
                'pmin_diesel', 'pmax_diesel', 'cost_diesel', 'var_cost_diesel',
                'startup_cost_diesel', 'shutdown_cost_diesel', 'ramp_up_diesel',
                'ramp_down_diesel', 'min_up_time_diesel', 'min_down_time_diesel',
                'u_unit_diesel', 'p_init_d', 'e_init', 'e_min', 'e_max',
                'p_ch_max', 'p_dis_max', 'eff_ch', 'eff_dis', 'e_final_min',
                'batt_cycle_cost', 'no_simultaneous_charge_discharge',
                'ongrid', 'grid_buy_price', 'grid_sell_price',
                'p_imp_max', 'p_exp_max', 'no_simultaneous_imp_exp',
                'allow_ls', 'ls_penalty',
            }
            for key, val in self.debug_overrides.items():
                if key in _microgrid_fields:
                    common_data[key] = val
                    self.log(f"🐛 [DEBUG] Override aplicado → {key} = {val}")

        data = self.MicrogridUCData(
            T=horizonte,
            demand=demand_dict,
            pv_avail=pv_avail_dict,
            **common_data,
        )
        
        # --- Construcción del modelo Pyomo ---
        model = pyo.ConcreteModel("UC_Microgrid")
        model.T = pyo.Set(initialize=data.T, ordered=True)
        T_list = list(data.T)

        def prev_t(t):
            i = T_list.index(t)
            return None if i == 0 else T_list[i - 1]

        model.D = pyo.Param(model.T, initialize=data.demand)
        model.PV_av = pyo.Param(model.T, initialize=data.pv_avail)

        buy = data.grid_buy_price or {t: 0.0 for t in T_list}
        sell = data.grid_sell_price or {t: 0.0 for t in T_list}

        dias_mes = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        mes_de_t = {t: (t // 24) for t in T_list}
        hora_de_t = {t: (t % 24) for t in T_list}
        peso_t = {t: dias_mes[mes_de_t[t]] for t in T_list}

        ## Variables de decisión: interacción con la red eléctrica
        model.w = pyo.Param(model.T, initialize=peso_t)
        model.p_buy = pyo.Param(model.T, initialize=buy)
        model.p_sell = pyo.Param(model.T, initialize=sell)
        if data.ongrid:
            model.p_imp = pyo.Var(model.T, domain=pyo.NonNegativeReals)
            model.p_exp = pyo.Var(model.T, domain=pyo.NonNegativeReals)
        else:
            # Mantiene la misma interfaz del modelo, pero bloquea intercambio con red.
            model.p_imp = pyo.Var(model.T, bounds=(0, 0))
            model.p_exp = pyo.Var(model.T, bounds=(0, 0))

        # Diesel variables
        model.u_d = pyo.Var(model.T, domain=pyo.Binary)
        model.p_diesel = pyo.Var(model.T, domain=pyo.NonNegativeReals)
        model.su_d = pyo.Var(model.T, domain=pyo.Binary)
        model.sd_d = pyo.Var(model.T, domain=pyo.Binary)

        # Si no hay diesel, fijar todas las binarias a 0 para evitar variables sin valor.
        if data.pmax_diesel == 0:
            for _t in T_list:
                model.u_d[_t].fix(0)
                model.su_d[_t].fix(0)
                model.sd_d[_t].fix(0)

        ## Variable de decisión: uso de PV 
        model.pv_use = pyo.Var(model.T, domain=pyo.NonNegativeReals)
        
        ## Variable de decisión: uso de batería
        model.p_ch = pyo.Var(model.T, domain=pyo.NonNegativeReals)
        model.p_dis = pyo.Var(model.T, domain=pyo.NonNegativeReals)
        model.e = pyo.Var(model.T, domain=pyo.NonNegativeReals)

        ## Variable de decisión: Energia no suministrada (load shedding)
        if data.allow_ls:
            model.ls = pyo.Var(model.T, domain=pyo.NonNegativeReals)
        else:
            model.ls = pyo.Var(model.T, bounds=(0, 0))

        ## Restricciones de no simultaneidad en la batería
        if data.no_simultaneous_charge_discharge and data.p_ch_max > 0 and data.p_dis_max > 0:
            model.u_ch = pyo.Var(model.T, domain=pyo.Binary)
            model.u_dis = pyo.Var(model.T, domain=pyo.Binary)


            def no_sim_bat_rule(m, t):
                return m.u_ch[t] + m.u_dis[t] <= 1

            model.no_sim_bat = pyo.Constraint(model.T, rule=no_sim_bat_rule)
            model.c_pch_flag = pyo.Constraint(model.T, rule=lambda m, t: m.p_ch[t] <= data.p_ch_max * m.u_ch[t])
            model.c_pdis_flag = pyo.Constraint(model.T, rule=lambda m, t: m.p_dis[t] <= data.p_dis_max * m.u_dis[t])

        ## Restricciones de no simultaneidad en la red
        if data.no_simultaneous_imp_exp and data.ongrid and data.p_imp_max is not None and data.p_exp_max is not None:
            model.u_imp = pyo.Var(model.T, domain=pyo.Binary)
            model.u_exp = pyo.Var(model.T, domain=pyo.Binary)

            def no_sim_grid_rule(m, t):
                return m.u_imp[t] + m.u_exp[t] <= 1

            model.no_sim_grid = pyo.Constraint(model.T, rule=no_sim_grid_rule)
            model.c_pimp_flag = pyo.Constraint(model.T, rule=lambda m, t: m.p_imp[t] <= data.p_imp_max * m.u_imp[t])
            model.c_pexp_flag = pyo.Constraint(model.T, rule=lambda m, t: m.p_exp[t] <= data.p_exp_max * m.u_exp[t])

        def pv_cap_rule(m, t):
            return m.pv_use[t] <= m.PV_av[t]

        model.c_pv_cap = pyo.Constraint(model.T, rule=pv_cap_rule)

        if not (data.no_simultaneous_charge_discharge and data.p_ch_max > 0 and data.p_dis_max > 0):
            model.c_pch_max = pyo.Constraint(model.T, rule=lambda m, t: m.p_ch[t] <= data.p_ch_max)
            model.c_pdis_max = pyo.Constraint(model.T, rule=lambda m, t: m.p_dis[t] <= data.p_dis_max)

        model.c_e_min = pyo.Constraint(model.T, rule=lambda m, t: m.e[t] >= data.e_min)
        model.c_e_max = pyo.Constraint(model.T, rule=lambda m, t: m.e[t] <= data.e_max)
        model.c_pd_max = pyo.Constraint(model.T, rule=lambda m, t: m.p_diesel[t] <= data.pmax_diesel)
        # Restricción UC de enlace: p_diesel acotado por u_d (evita variables binarias flotantes)
        if data.pmax_diesel > 0:
            model.c_pd_uc_max = pyo.Constraint(model.T, rule=lambda m, t: m.p_diesel[t] <= data.pmax_diesel * m.u_d[t])
            model.c_pd_uc_min = pyo.Constraint(model.T, rule=lambda m, t: m.p_diesel[t] >= data.pmin_diesel * m.u_d[t])

        # Fallback bounds for grid: only when no-simultaneity block was skipped
        # (mirrors battery pattern; off-grid case already handled by bounds=(0,0) on p_imp/p_exp)
        if not (data.no_simultaneous_imp_exp and data.ongrid
                and data.p_imp_max is not None and data.p_exp_max is not None):
            if data.ongrid and data.p_imp_max is not None:
                model.c_pimp_max = pyo.Constraint(model.T, rule=lambda m, t: m.p_imp[t] <= data.p_imp_max)
            if data.ongrid and data.p_exp_max is not None:
                model.c_pexp_max = pyo.Constraint(model.T, rule=lambda m, t: m.p_exp[t] <= data.p_exp_max)

        def balance_rule(m, t):
            return m.pv_use[t] + m.p_dis[t] + m.p_imp[t] + m.p_diesel[t] + m.ls[t] == m.D[t] + m.p_ch[t] + m.p_exp[t]

        model.c_balance = pyo.Constraint(model.T, rule=balance_rule)

        t_inicio_mes = {}
        t_fin_mes = {}
        for t in T_list:
            mes = mes_de_t[t]
            hora = hora_de_t[t]
            if hora == 0:
                t_inicio_mes[mes] = t
            if hora == 23:
                t_fin_mes[mes] = t

        def soc_rule(m, t):
            if t == T_list[0]:
                # Primer periodo: e_init es el SOC antes del periodo 0 (estado inicial del año)
                return m.e[t] == data.e_init + data.eff_ch * m.p_ch[t] - (1.0 / data.eff_dis) * m.p_dis[t]
            else:
                # Continuidad total: cada periodo se encadena al anterior, incluido el cruce entre meses
                return m.e[t] == m.e[t - 1] + data.eff_ch * m.p_ch[t] - (1.0 / data.eff_dis) * m.p_dis[t]

        model.c_soc = pyo.Constraint(model.T, rule=soc_rule)

        # Ciclado mensual: el SOC al final de cada día tipo debe ser igual al SOC al inicio
        # de ese mismo día tipo. Esto garantiza que el día representativo es físicamente
        # repetible durante todos los días del mes (consistente con el escalado por dias_mes).
        # La continuidad entre meses queda determinada por la cadena de restricciones:
        #   e[t_fin_mes[0]] = e_init  →  e[t_fin_mes[1]] = e[t_fin_mes[0]]  →  ...
        def monthly_soc_cycle_rule(m_model, mes_idx):
            t_end = t_fin_mes[mes_idx]
            if mes_idx == 0:
                return m_model.e[t_end] == data.e_init
            else:
                return m_model.e[t_end] == m_model.e[t_fin_mes[mes_idx - 1]]

        model.c_monthly_soc_cycle = pyo.Constraint(range(12), rule=monthly_soc_cycle_rule)

        def obj_rule(m):
            return sum(
                m.w[t] * (
                    m.p_buy[t] * m.p_imp[t]
                    - m.p_sell[t] * m.p_exp[t]
                    + data.var_cost_diesel * m.p_diesel[t]
                    + data.ls_penalty * m.ls[t]
                    + data.batt_cycle_cost * (m.p_ch[t] + m.p_dis[t])
                )
                for t in m.T
            )

        model.obj = pyo.Objective(rule=obj_rule, sense=pyo.minimize)

        self.log('✅ Modelo construido con FO anual ponderada y ciclado mensual de SOC (día tipo repetible).')

        # Intentar solvers en orden de preferencia
        _solver_candidates = ['glpk', 'cbc', 'highs', 'cplex', 'gurobi']
        solver = None
        solver_name = None
        for _candidate in _solver_candidates:
            _s = SolverFactory(_candidate)
            if _s.available():
                solver = _s
                solver_name = _candidate
                break
        if solver is None:
            self.log(f"⚠️ No se encontró ningún solver disponible. Probados: {_solver_candidates}")
            self.resultados_opt['status'] = 'Error'
            self.resultados_opt['termination_condition'] = 'no_solver'
            self.resultados_opt['objective_usd'] = None
            self.resultados_opt['descarga_total'] = 0
            return
        self.log(f"🔧 Solver seleccionado: {solver_name}")

        try:
            # Diagnóstico de solver:
            # - En DEBUG activamos salida de solver (tee=True)
            # - Se puede forzar con params['solver_tee'] = True/False
            # - Se puede fijar timeout con params['solver_timeout_s'] (GLPK -> tmlim)
            solver_tee = bool(
                self.params.get(
                    'solver_tee',
                    self.debug_overrides.get('solver_tee', self.debug_mode)
                )
            )
            solver_timeout_s = self.params.get(
                'solver_timeout_s',
                self.debug_overrides.get('solver_timeout_s', None)
            )
            solver_mipgap = self.params.get(
                'solver_mipgap',
                self.debug_overrides.get('solver_mipgap', None)
            )

            solve_kwargs = {
                'tee': solver_tee
            }

            if solver_name == 'glpk' and solver_timeout_s is not None:
                try:
                    solver.options['tmlim'] = int(float(solver_timeout_s))
                    self.log(f"⏱️ GLPK timeout configurado: {int(float(solver_timeout_s))} s")
                except Exception:
                    self.log(f"⚠️ No se pudo aplicar solver_timeout_s={solver_timeout_s} a GLPK.")

            if solver_name == 'glpk' and solver_mipgap is not None:
                try:
                    solver.options['mipgap'] = float(solver_mipgap)
                    self.log(f"🎯 GLPK mipgap configurado: {float(solver_mipgap):.4f}")
                except Exception:
                    self.log(f"⚠️ No se pudo aplicar solver_mipgap={solver_mipgap} a GLPK.")

            if solver_name == 'glpk':
                os.makedirs('output', exist_ok=True)
                solve_kwargs['logfile'] = os.path.join('output', 'glpk_solver.log')

            self.log(
                f"🧪 Iniciando solve (tee={solver_tee}, timeout_s={solver_timeout_s}, "
                f"mipgap={solver_mipgap})..."
            )
            t0_solve = time.time()
            results = solver.solve(model, **solve_kwargs)
            elapsed_solve = time.time() - t0_solve
            self.log(f"⏱️ Solve finalizado en {elapsed_solve:.2f} s")

            self.model = model
            self.resultados_opt['status'] = str(results.solver.status)
            self.resultados_opt['termination_condition'] = str(results.solver.termination_condition)
            self.resultados_opt['objective_usd'] = pyo.value(model.obj)
            self.log(
                f"🧾 Estado solver: status={self.resultados_opt['status']} | "
                f"termination={self.resultados_opt['termination_condition']}"
            )

            energia_importada = sum(pyo.value(model.p_imp[t]) * peso_t[t] for t in T_list)
            energia_exportada = sum(pyo.value(model.p_exp[t]) * peso_t[t] for t in T_list)
            energia_shed = sum(pyo.value(model.ls[t]) * peso_t[t] for t in T_list)

            self.resultados_opt['energia_importada_kwh_anual'] = energia_importada
            self.resultados_opt['energia_exportada_kwh_anual'] = energia_exportada
            self.resultados_opt['descarga_total'] = sum(pyo.value(model.p_dis[t]) * peso_t[t] for t in T_list)

            # --- Métricas adicionales para flujo de caja ---
            demanda_anual        = sum(demand_dict[t] * peso_t[t] for t in T_list)
            generacion_solar     = sum(pyo.value(model.pv_use[t]) * peso_t[t] for t in T_list)
            surplus_solar        = sum((pv_avail_dict[t] - pyo.value(model.pv_use[t])) * peso_t[t] for t in T_list)
            consumo_red          = energia_importada
            consumo_diesel       = sum(pyo.value(model.p_diesel[t]) * peso_t[t] for t in T_list)
            consumo_total        = demanda_anual - energia_shed  # energy actually served

            # Kilometraje de batería: kWh desplazados = sum |p_ch - p_dis| × dias_mes
            # Con restricción de no-simultaneidad equivale a p_ch + p_dis, pero se usa
            # abs() para mantener consistencia con modelos sin restricción binaria.
            bat_kwh_desplazados  = sum(
                abs(pyo.value(model.p_ch[t]) - pyo.value(model.p_dis[t])) * peso_t[t]
                for t in T_list
            )
            bat_ciclos_equiv     = bat_kwh_desplazados / (2 * cap_bat) if cap_bat > 0 else 0.0

            self.resultados_opt['demanda_anual_kwh']              = demanda_anual
            self.resultados_opt['demanda_maxima_kw']              = max(demand_dict[t] for t in T_list)
            self.resultados_opt['capacidad_bateria_kwh']          = cap_bat
            self.resultados_opt['potencia_max_carga_kw']          = data.p_ch_max
            self.resultados_opt['potencia_max_descarga_kw']       = data.p_dis_max
            self.resultados_opt['energia_no_suministrada_kwh_anual'] = energia_shed
            self.resultados_opt['consumo_total_kwh_anual']        = consumo_total
            self.resultados_opt['generacion_solar_kwh_anual']     = generacion_solar
            self.resultados_opt['surplus_solar_kwh_anual']        = surplus_solar
            self.resultados_opt['consumo_red_kwh_anual']          = consumo_red
            self.resultados_opt['consumo_diesel_kwh_anual']       = consumo_diesel
            self.resultados_opt['bat_kwh_desplazados_anual']      = bat_kwh_desplazados
            self.resultados_opt['bat_ciclos_equiv_anual']         = bat_ciclos_equiv

            self.log("📋 ── Resumen de métricas ──────────────────────────────")
            self.log(f"   Demanda anual total         : {demanda_anual:>12.2f} kWh")
            self.log(f"   Consumo total servido       : {consumo_total:>12.2f} kWh")
            self.log(f"   Generación solar utilizada  : {generacion_solar:>12.2f} kWh")
            self.log(f"   Excedente solar (surplus)   : {surplus_solar:>12.2f} kWh")
            self.log(f"   Consumo desde red           : {consumo_red:>12.2f} kWh")
            self.log(f"   Consumo diesel              : {consumo_diesel:>12.2f} kWh")
            self.log(f"   Energía no suministrada     : {energia_shed:>12.2f} kWh")
            self.log(f"   Demanda máxima              : {self.resultados_opt['demanda_maxima_kw']:>12.2f} kW")
            self.log(f"   Capacidad batería           : {cap_bat:>12.2f} kWh")
            self.log(f"   Potencia máx carga          : {data.p_ch_max:>12.2f} kW")
            self.log(f"   Potencia máx descarga       : {data.p_dis_max:>12.2f} kW")
            self.log(f"   kWh desplazados batería     : {bat_kwh_desplazados:>12.2f} kWh")
            self.log(f"   Ciclos equiv. anuales       : {bat_ciclos_equiv:>12.2f} ciclos")
            self.log("────────────────────────────────────────────────────────")

            costos_mensuales = {}
            for mes in sorted(t_inicio_mes.keys()):
                t_mes = [t for t in T_list if mes_de_t[t] == mes]
                c_mes = sum(
                    peso_t[t] * (
                        buy[t] * pyo.value(model.p_imp[t])
                        - sell[t] * pyo.value(model.p_exp[t])
                        + data.var_cost_diesel * pyo.value(model.p_diesel[t])
                        + data.ls_penalty * pyo.value(model.ls[t])
                        + data.batt_cycle_cost * (pyo.value(model.p_ch[t]) + pyo.value(model.p_dis[t]))
                    )
                    for t in t_mes
                )
                costos_mensuales[f'mes_{mes+1}'] = c_mes

            self.resultados_opt['costos_mensuales_usd'] = costos_mensuales
            self.log(f"✅ Optimización completada. Costo total: USD {self.resultados_opt['objective_usd']:.2f}")

        except Exception as e:
            self.log(f"⚠️ Error: Solver '{solver_name}' falló o no encontrado ({e}).")
            self.log("🧵 Traceback completo del solver:")
            self.log(traceback.format_exc())
            self.resultados_opt['status'] = 'Error'
            self.resultados_opt['termination_condition'] = 'error'
            self.resultados_opt['objective_usd'] = None
            self.resultados_opt['descarga_total'] = 0

    def post_analisis(self, mes=None, gestor=None):
        """
        Genera DataFrames de resultados de la optimización hora a hora.

        :param mes: Mes a analizar. Acepta entero 1-12, nombre en español ('Enero', etc.)
                    o None para calcular los 12 meses.
                    Por defecto None (todos los meses).
        :param gestor: Reservado para uso futuro.
        :return:
            - Un mes  → DataFrame de 24 filas (horas). También guardado en
                         self.dfs_post_analisis[nombre_mes].
            - Todos   → dict {nombre_mes: DataFrame} guardado en self.dfs_post_analisis.

        Columnas del DataFrame:
            Demanda [kW]        — perfil de demanda de entrada
            PV_disponible [kW]  — generación PV disponible (en kW absolutos, desde sizing)
            u_diesel [-]        — estado binario diesel (0/1)
            u_carga_bat [-]     — estado binario carga batería (0/1 o NaN si no aplica)
            u_descarga_bat [-]  — estado binario descarga batería (0/1 o NaN si no aplica)
            P_diesel [kW]       — potencia generada por diesel
            P_carga_bat [kW]    — potencia de carga de batería
            P_descarga_bat [kW] — potencia de descarga de batería
            P_pv [kW]           — generación fotovoltaica utilizada
            P_imp [kW]          — inyección desde la red (importación)
            P_exp [kW]          — eyección hacia la red (exportación)
            SOC [kWh]           — estado de carga de la batería al final del periodo
            P_ls [kW]           — energía no suministrada (load shedding)
        SOC se reporta NaN si cap_bat = 0 (sin batería).
        """
        self.log("📊 [3/4] Realizando post-análisis...")

        NOMBRES_MESES = [
            'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
            'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'
        ]

        # --- Determinar lista de índices de mes a procesar ---
        if mes is None:
            indices_meses = list(range(12))
        elif isinstance(mes, str):
            mes_norm = mes.strip().capitalize()
            if mes_norm not in NOMBRES_MESES:
                self.log(f"⚠️ Nombre de mes no reconocido: '{mes}'. Opciones: {NOMBRES_MESES}")
                return None
            indices_meses = [NOMBRES_MESES.index(mes_norm)]
        elif isinstance(mes, int) and 1 <= mes <= 12:
            indices_meses = [mes - 1]
        else:
            self.log(f"⚠️ Parámetro 'mes' inválido: {mes!r}. Use None, un entero 1-12 o el nombre del mes.")
            return None

        modo_un_mes = (len(indices_meses) == 1)

        # --- Validaciones previas ---
        if self.model is None:
            self.log("⚠️ No hay modelo resuelto. Ejecute resolver_optimizacion() primero.")
            return None

        if self.array_pdem is None or self.array_pgen is None:
            self.log("⚠️ Los perfiles de demanda/generación no están cargados.")
            return None

        model = self.model
        cap_bat = self.params.get('baterias_cap', 0.0)
        tiene_bateria = cap_bat > 0

        # Verificar variables binarias de batería (se comprueba una sola vez)
        tiene_u_bat = hasattr(model, 'u_ch') and hasattr(model, 'u_dis')

        # --- Construcción de DataFrames ---
        for mes_idx in indices_meses:
            nombre_mes = NOMBRES_MESES[mes_idx]
            t_mes = [mes_idx * 24 + hora for hora in range(24)]

            def _bin(var):
                """Extrae valor binario; retorna NaN si la variable no fue inicializada."""
                v = pyo.value(var, exception=False)
                return int(round(v)) if v is not None else float('nan')

            def _num(var):
                """Extrae valor numérico; retorna NaN si la variable no fue inicializada."""
                v = pyo.value(var, exception=False)
                return round(v, 4) if v is not None else float('nan')

            registros = []
            for hora, t in enumerate(t_mes):
                fila = {
                    'Hora': hora,
                    'Demanda [kW]':        round(self.array_pdem[mes_idx, hora], 4),
                    'PV_disponible [kW]':  round(self.array_pgen[mes_idx, hora], 4),  # Ya en kW absolutos
                    'u_diesel [-]':        _bin(model.u_d[t]),
                    'u_carga_bat [-]':     _bin(model.u_ch[t])  if tiene_u_bat else float('nan'),
                    'u_descarga_bat [-]':  _bin(model.u_dis[t]) if tiene_u_bat else float('nan'),
                    'P_diesel [kW]':       _num(model.p_diesel[t]),
                    'P_carga_bat [kW]':    _num(model.p_ch[t]),
                    'P_descarga_bat [kW]': _num(model.p_dis[t]),
                    'P_pv [kW]':           _num(model.pv_use[t]),
                    'P_imp [kW]':          _num(model.p_imp[t]),
                    'P_exp [kW]':          _num(model.p_exp[t]),
                    'SOC [kWh]':           _num(model.e[t]) if tiene_bateria else float('nan'),
                    'P_ls [kW]':           _num(model.ls[t]),
                }
                registros.append(fila)

            df = pd.DataFrame(registros).set_index('Hora')
            df.index.name = f'Hora — {nombre_mes}'
            self.dfs_post_analisis[nombre_mes] = df
            self.log(f"   ✔ {nombre_mes}: DataFrame {df.shape[0]}h × {df.shape[1]} cols generado.")

        # --- Log final y retorno ---
        if modo_un_mes:
            nombre_unico = NOMBRES_MESES[indices_meses[0]]
            df_result = self.dfs_post_analisis[nombre_unico]
            self.log(f"\n{df_result.to_string()}")
            return df_result
        else:
            self.log(
                f"✅ Post-análisis completo: {len(indices_meses)} meses almacenados en "
                f"self.dfs_post_analisis. "
                f"Acceso: self.dfs_post_analisis['Marzo'], etc."
            )
            return self.dfs_post_analisis

    def graficar_mes(self, mes=None, mostrar=True, loggear=True):
        """
        Genera el gráfico de despacho hora a hora para el mes indicado.
        Requiere que post_analisis() haya sido ejecutado previamente.

        :param mes: Nombre del mes ('Enero', etc.), entero 1-12, o None para usar
                    el primer mes disponible en self.dfs_post_analisis.
        :param mostrar: Si True (default) llama plt.show(). Pasar False al generar
                        gráficos en batch (p. ej. para exportar a ZIP).
        :return: objeto Figure de matplotlib.
        """
        import matplotlib.pyplot as plt

        NOMBRES_MESES = [
            'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
            'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'
        ]

        # --- Resolver nombre de mes ---
        if mes is None:
            if not self.dfs_post_analisis:
                self.log("⚠️ No hay resultados en dfs_post_analisis. Ejecute post_analisis() primero.")
                return None
            nombre_mes = next(iter(self.dfs_post_analisis))
        elif isinstance(mes, str):
            nombre_mes = mes.strip().capitalize()
        elif isinstance(mes, int) and 1 <= mes <= 12:
            nombre_mes = NOMBRES_MESES[mes - 1]
        else:
            self.log(f"⚠️ Mes inválido para graficar: {mes!r}")
            return None

        if nombre_mes not in self.dfs_post_analisis:
            self.log(f"⚠️ No hay datos para '{nombre_mes}'. Ejecute post_analisis('{nombre_mes}') primero.")
            return None

        df = self.dfs_post_analisis[nombre_mes]
        horas = list(range(24))

        # --- Series ---
        demanda   = df['Demanda [kW]'].values
        pv_disp   = df['PV_disponible [kW]'].values
        diesel    = df['P_diesel [kW]'].values
        # Batería: positivo = cargando, negativo = descargando
        bat_neta  = df['P_carga_bat [kW]'].values - df['P_descarga_bat [kW]'].values
        pv_uso    = df['P_pv [kW]'].values
        # Red: positivo = importando, negativo = exportando
        red_neta  = df['P_imp [kW]'].values - df['P_exp [kW]'].values
        soc       = df['SOC [kWh]'].values

        # --- Etiquetas de hora (formato 12h) ---
        hora_labels = []
        for h in horas:
            if h == 0:
                hora_labels.append('12:00 AM')
            elif h < 12:
                hora_labels.append(f'{h}:00 AM')
            elif h == 12:
                hora_labels.append('12:00 PM')
            else:
                hora_labels.append(f'{h - 12}:00 PM')

        # --- Figura con doble eje Y ---
        fig, ax1 = plt.subplots(figsize=(14, 6))
        ax2 = ax1.twinx()

        # Eje izquierdo — potencias
        ax1.plot(horas, demanda,  color='#2196F3', linewidth=2,   label='Demanda')
        ax1.plot(horas, pv_disp,  color='#F44336', linewidth=2,   label='Gen Solar disp.')
        ax1.plot(horas, diesel,   color='#4CAF50', linewidth=2,   label='Diesel')
        ax1.plot(horas, bat_neta, color='#9C27B0', linewidth=1.5, label='Carga/Descarga Bat')
        ax1.plot(horas, pv_uso,   color='#00BCD4', linewidth=1.5, label='Gen PV autoconsumo')
        ax1.plot(horas, red_neta, color='#FF9800', linewidth=1.5, label='Red Eléctrica')
        ax1.axhline(0, color='gray', linewidth=0.5, linestyle=':')

        # Eje derecho — SOC
        ax2.plot(horas, soc, color='black', linewidth=2, linestyle='--', label='SoC batería')

        # --- Formato ---
        ax1.set_title(f'Mes de {nombre_mes}', fontsize=14, fontweight='bold')
        ax1.set_xlabel('Hora')
        ax1.set_ylabel('Potencia [kW]')
        ax2.set_ylabel('SoC [kWh]')
        ax1.set_xticks(horas)
        ax1.set_xticklabels(hora_labels, rotation=45, ha='right', fontsize=8)
        ax1.grid(axis='y', linestyle='--', alpha=0.4)

        # Leyenda combinada (eje izq + der)
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2,
                   loc='upper left', fontsize=8, ncol=4, framealpha=0.9)

        plt.tight_layout()
        if mostrar:
            plt.show()
        if loggear:
            self.log(f"📈 Gráfico generado para {nombre_mes}.")
        return fig

    def graficar_flujo_caja(self, mostrar=True, loggear=True):
        """
        Genera un gráfico anual del flujo de caja para visualizar:
        - Flujo neto por año (barras)
        - Flujo acumulado (línea)
        """
        import matplotlib.pyplot as plt

        if self.df_flujo is None or self.df_flujo.empty:
            self.log("⚠️ No hay resultados de flujo de caja para graficar. Ejecute flujo_caja() primero.")
            return None

        df = self.df_flujo.copy()
        anios = df.index.to_list()
        flujo_neto = df['Flujo_Neto'].to_numpy(dtype=float)
        flujo_acum = df['Flujo_Acumulado'].to_numpy(dtype=float)

        colores = ['#2E7D32' if v >= 0 else '#C62828' for v in flujo_neto]

        fig, ax1 = plt.subplots(figsize=(14, 6))
        ax2 = ax1.twinx()

        ax1.bar(anios, flujo_neto, color=colores, alpha=0.85, label='Flujo neto anual')
        ax1.axhline(0, color='gray', linewidth=0.9, linestyle='--')
        ax2.plot(anios, flujo_acum, color='#0D47A1', linewidth=2.2, marker='o', label='Flujo acumulado')

        ax1.set_title('Evolucion Flujo de Caja Anual', fontsize=14, fontweight='bold')
        ax1.set_xlabel('Anio')
        ax1.set_ylabel('Flujo neto [USD]')
        ax2.set_ylabel('Flujo acumulado [USD]')
        ax1.set_xticks(anios)
        ax1.grid(axis='y', linestyle='--', alpha=0.35)

        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', framealpha=0.9)

        plt.tight_layout()
        if mostrar:
            plt.show()

        if loggear:
            self.log("📈 Gráfico de evolución de flujo de caja generado.")
        return fig

    def exportar_graficos_zip(self, ruta_zip=None):
        """
        Genera un PNG por cada mes disponible en dfs_post_analisis y los empaqueta
        en un archivo ZIP.

        :param ruta_zip: Ruta del archivo ZIP de salida. Por defecto:
                         'graficos_optimizacion_cliente_<indice>.zip' en el directorio actual.
        :return: Ruta del ZIP generado.
        """
        import matplotlib
        import matplotlib.pyplot as plt
        import zipfile
        import io

        NOMBRES_MESES = [
            'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
            'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'
        ]

        if not self.dfs_post_analisis:
            self.log("⚠️ No hay resultados en dfs_post_analisis. Ejecute post_analisis() primero.")
            return None

        if ruta_zip is None:
            os.makedirs("output", exist_ok=True)
            cfg = self.cliente_data if hasattr(self.cliente_data, 'get') else {}
            nombre_raw = cfg.get('Nombre', '')
            nombre_safe = ''.join(w.capitalize() for w in nombre_raw.strip().split()) if nombre_raw else 'SinNombre'
            ruta_zip = os.path.join("output", f"graficos_optimizacion_cliente{self.indice + 1}_{nombre_safe}.zip")

        total_guardados = 0
        with zipfile.ZipFile(ruta_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
            for nombre_mes in NOMBRES_MESES:
                if nombre_mes not in self.dfs_post_analisis:
                    continue

                fig = self.graficar_mes(nombre_mes, mostrar=False, loggear=False)
                if fig is None:
                    continue

                buf = io.BytesIO()
                fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
                plt.close(fig)
                buf.seek(0)
                zf.writestr(f'{nombre_mes}.png', buf.read())
                total_guardados += 1

            # Gráfico financiero anual de flujo de caja
            fig_fc = self.graficar_flujo_caja(mostrar=False, loggear=False)
            if fig_fc is not None:
                buf_fc = io.BytesIO()
                fig_fc.savefig(buf_fc, format='png', dpi=150, bbox_inches='tight')
                plt.close(fig_fc)
                buf_fc.seek(0)
                zf.writestr('FlujoCaja_Anual.png', buf_fc.read())
                total_guardados += 1

        self.log(f"✅ Gráficos generados y guardados en ZIP ({total_guardados} archivos): {ruta_zip}")
        return ruta_zip

    def flujo_caja(self):
        """
        Genera flujo de caja anual inspirado en la hoja 04_FlowCash del Excel,
        usando las métricas operativas calculadas por resolver_optimizacion().

        Notas:
        - Los ahorros energéticos se escalan por incremento de tarifa y caída de
          eficiencia FV anual.
        - La vida útil de batería se estima por kilometrraje anual desplazado.
        - Si faltan variables de potencia punta/autoconsumo, esos términos se
          reportan en 0 (no aplica en el modelo actual).
        """
        self.log("💰 [4/4] Calculando Flujo de Caja...")
        # --- Parámetros base ---
        horizonte = int(self.params.get('horizonte', 20))
        tasa_descuento = float(self.params.get('tasa_descuento', 0.06))

        # Precios / factores de crecimiento (alineados a 04_FlowCash)
        costo_energia = float(self.params.get('costo_energia', 0.15))
        costo_potencia_suministrada = float(self.params.get('costo_potencia_suministrada', 0.0))
        costo_potencia_punta = float(self.params.get('costo_potencia_punta', 0.0))
        precio_inyeccion = float(self.params.get('precio_inyeccion', 0.05))
        incremento_precio_anual = float(self.params.get('incremento_precio_anual', 0.05))
        caida_eficiencia_fv_anual = float(self.params.get('caida_eficiencia_fv_anual', 0.007))
        incremento_mantencion_anual = float(self.params.get('incremento_mantencion_anual', 0.05))

        # CAPEX (si no vienen desglosados, usar costo_capex como inversión total)
        capex_total = float(self.params.get('costo_capex', 0.0))
        inv_storage = float(self.params.get('inv_storage', 0.0))
        inv_fv = float(self.params.get('inv_fv', 0.0))
        inv_inv_fv = float(self.params.get('inv_inv_fv', 0.0))
        inv_inv_storage = float(self.params.get('inv_inv_storage', 0.0))
        inv_inversores_total = inv_inv_fv + inv_inv_storage
        inv_estructura = float(self.params.get('inv_estructura', 0.0))
        inv_materiales = float(self.params.get('inv_materiales', 0.0))

        if (inv_storage + inv_fv + inv_inv_fv + inv_inv_storage + inv_estructura + inv_materiales) <= 0 and capex_total > 0:
            inv_fv = capex_total
            self.log("ℹ️ CAPEX desglosado no informado; se usa costo_capex completo en inversión FV.")

        # Recalcular total de inversores por si hubo override/fallback previo.
        inv_inversores_total = inv_inv_fv + inv_inv_storage

        # Mantenimiento (04_FlowCash: mant FV y Storage sobre base de inversión)
        mant_fv_pct = float(self.params.get('mant_fv_pct', 0.006))
        mant_storage_pct = float(self.params.get('mant_storage_pct', 0.01))
        opex_fv_y1 = float(self.params.get('opex_fv_y1', (inv_fv + inv_inv_fv) * mant_fv_pct))
        opex_storage_y1 = float(self.params.get('opex_storage_y1', (inv_storage + inv_inv_storage) * mant_storage_pct))

        # --- Métricas operativas desde optimización ---
        dem_max_total = float(self.resultados_opt.get('demanda_maxima_kw', 0.0))
        pot_max_autoconsumo = float(self.resultados_opt.get('potencia_autoconsumo_kw', 0.0))
        pot_punta_total = float(self.resultados_opt.get('potencia_punta_total_kw', 0.0))
        pot_punta_autoconsumo = float(self.resultados_opt.get('potencia_punta_autoconsumo_kw', 0.0))

        gen_fv_anual = float(self.resultados_opt.get('generacion_solar_kwh_anual', 0.0))
        excedente_anual = float(self.resultados_opt.get('energia_exportada_kwh_anual', 0.0))

        cap_bat = float(self.resultados_opt.get('capacidad_bateria_kwh', self.params.get('baterias_cap', 0.0)))
        km_bateria_anual = float(self.resultados_opt.get('bat_kwh_desplazados_anual', 0.0))

        # --- Vida útil de batería por tecnología (03_Result / 04_FlowCash) ---
        # Estandar: LITIO en modo normal. En DEBUG se permite seleccionar otra.
        tecnologia_cfg = self.params.get('tecnologia_bateria', 'LITIO') if self.debug_mode else 'LITIO'
        tecnologia_raw = str(tecnologia_cfg).strip().upper()
        tecnologia_alias = {
            'LITIO': 'LITIO',
            'LI-ION': 'LITIO',
            'LITHIUM': 'LITIO',
            'LFP': 'LITIO',
            'LIFEPO4': 'LITIO',
            'OPZS': 'OPZS',
            'AGM': 'AGM',
        }
        tecnologia = tecnologia_alias.get(tecnologia_raw, 'LITIO')
        ciclos_por_tecnologia = {
            'AGM': 500,
            'OPZS': 2500,
            'LITIO': 6000,
        }
        ciclos = int(ciclos_por_tecnologia.get(tecnologia, 6000))
        km_teorico_bat = 2.0 * cap_bat * ciclos  # equivalente a 2*Ebat_final*DoD*ciclos del Excel

        if km_bateria_anual > 0:
            vida_bateria = min(km_teorico_bat / km_bateria_anual, float(horizonte))
        else:
            vida_bateria = float(horizonte)

        vida_bateria = max(1, int(np.floor(vida_bateria + 0.5)))
        recambio_inversor = int(self.params.get('recambio_inversor', 10))

        # --- DataFrame anual ---
        anios = list(range(horizonte + 1))
        flujo = pd.DataFrame(index=anios)
        flujo.index.name = 'Año'

        # Ingresos base año 1
        ahorro_autogen_y1 = gen_fv_anual * costo_energia
        ahorro_potencia_y1 = max(dem_max_total - pot_max_autoconsumo, 0.0) * costo_potencia_suministrada * 12.0
        ahorro_punta_y1 = max(pot_punta_total - pot_punta_autoconsumo, 0.0) * costo_potencia_punta * 12.0
        ingreso_venta_y1 = excedente_anual * precio_inyeccion

        if pot_max_autoconsumo == 0.0 and pot_punta_autoconsumo == 0.0:
            self.log("ℹ️ No hay métricas de potencia autoconsumo/punta en resultados_opt; ahorro por potencia se considera 0.")

        # Factores de escalamiento anual (igual estructura de 04_FlowCash)
        def _factor_ingresos(t):
            if t <= 0:
                return 0.0
            return ((1 + incremento_precio_anual) ** (t - 1)) * ((1 - caida_eficiencia_fv_anual) ** (t - 1))

        def _factor_opex(t):
            if t <= 0:
                return 0.0
            return (1 + incremento_mantencion_anual) ** (t - 1)

        # Depreciaciones (lineales)
        dep_fv = (inv_fv / horizonte) if horizonte > 0 else 0.0
        dep_inv = (inv_inversores_total / recambio_inversor) if recambio_inversor > 0 else 0.0
        dep_bat = (inv_storage / vida_bateria) if vida_bateria > 0 else 0.0

        # Inicialización de columnas
        cols = [
            'Ahorro_Autogeneracion', 'Ahorro_Potencia', 'Ahorro_Potencia_Punta', 'Ingreso_Venta_Energia',
            'Ingresos_Totales', 'OPEX_FV_Inv', 'OPEX_Storage', 'Depreciacion_FV', 'Depreciacion_Inv',
            'Depreciacion_Bat', 'Egresos_Totales', 'Utilidad_Bruta', 'Impuestos', 'Utilidad_Neta',
            'Inv_Storage', 'Inv_FV', 'Inv_Inv_FV', 'Inv_Inv_Storage', 'Inv_Estructura', 'Inv_Materiales',
            'Gastos_Financieros', 'Seguros', 'Reemplazo_Baterias', 'Reemplazo_Inversores', 'Depreciacion_AddBack',
            'Valor_Residual', 'Flujo_Neto', 'Flujo_Acumulado'
        ]
        for c in cols:
            flujo[c] = 0.0

        for t in anios:
            # Ingresos
            f_ing = _factor_ingresos(t)
            flujo.at[t, 'Ahorro_Autogeneracion'] = ahorro_autogen_y1 * f_ing
            flujo.at[t, 'Ahorro_Potencia'] = ahorro_potencia_y1 * f_ing
            flujo.at[t, 'Ahorro_Potencia_Punta'] = ahorro_punta_y1 * f_ing
            flujo.at[t, 'Ingreso_Venta_Energia'] = ingreso_venta_y1 * f_ing
            flujo.at[t, 'Ingresos_Totales'] = (
                flujo.at[t, 'Ahorro_Autogeneracion']
                + flujo.at[t, 'Ahorro_Potencia']
                + flujo.at[t, 'Ahorro_Potencia_Punta']
                + flujo.at[t, 'Ingreso_Venta_Energia']
            )

            # Egresos operacionales
            f_opex = _factor_opex(t)
            flujo.at[t, 'OPEX_FV_Inv'] = -opex_fv_y1 * f_opex
            flujo.at[t, 'OPEX_Storage'] = -opex_storage_y1 * f_opex
            flujo.at[t, 'Depreciacion_FV'] = -dep_fv if t > 0 else 0.0
            flujo.at[t, 'Depreciacion_Inv'] = -dep_inv if t > 0 else 0.0
            flujo.at[t, 'Depreciacion_Bat'] = -dep_bat if t > 0 else 0.0
            flujo.at[t, 'Egresos_Totales'] = (
                flujo.at[t, 'OPEX_FV_Inv']
                + flujo.at[t, 'OPEX_Storage']
                + flujo.at[t, 'Depreciacion_FV']
                + flujo.at[t, 'Depreciacion_Inv']
                + flujo.at[t, 'Depreciacion_Bat']
            )

            # Estado de resultados
            flujo.at[t, 'Utilidad_Bruta'] = flujo.at[t, 'Ingresos_Totales'] + flujo.at[t, 'Egresos_Totales']
            flujo.at[t, 'Impuestos'] = 0.0
            flujo.at[t, 'Utilidad_Neta'] = flujo.at[t, 'Utilidad_Bruta'] + flujo.at[t, 'Impuestos']

            # Inversiones iniciales (año 0)
            if t == 0:
                flujo.at[t, 'Inv_Storage'] = -inv_storage
                flujo.at[t, 'Inv_FV'] = -inv_fv
                flujo.at[t, 'Inv_Inv_FV'] = -inv_inv_fv
                flujo.at[t, 'Inv_Inv_Storage'] = -inv_inv_storage
                flujo.at[t, 'Inv_Estructura'] = -inv_estructura
                flujo.at[t, 'Inv_Materiales'] = -inv_materiales

            # Reemplazos (alineado a IF(year/vida = INT(...)) del Excel)
            if t > 0 and vida_bateria > 0 and (t / vida_bateria).is_integer():
                flujo.at[t, 'Reemplazo_Baterias'] = -inv_storage
            if t > 0 and recambio_inversor > 0 and (t / recambio_inversor).is_integer():
                flujo.at[t, 'Reemplazo_Inversores'] = -inv_inversores_total

            # Add-back de depreciación para flujo de caja
            flujo.at[t, 'Depreciacion_AddBack'] = -(
                flujo.at[t, 'Depreciacion_FV']
                + flujo.at[t, 'Depreciacion_Inv']
                + flujo.at[t, 'Depreciacion_Bat']
            )

            # Flujo neto
            flujo.at[t, 'Flujo_Neto'] = (
                flujo.at[t, 'Utilidad_Neta']
                + flujo.at[t, 'Inv_Storage']
                + flujo.at[t, 'Inv_FV']
                + flujo.at[t, 'Inv_Inv_FV']
                + flujo.at[t, 'Inv_Inv_Storage']
                + flujo.at[t, 'Inv_Estructura']
                + flujo.at[t, 'Inv_Materiales']
                + flujo.at[t, 'Gastos_Financieros']
                + flujo.at[t, 'Seguros']
                + flujo.at[t, 'Reemplazo_Baterias']
                + flujo.at[t, 'Reemplazo_Inversores']
                + flujo.at[t, 'Depreciacion_AddBack']
                + flujo.at[t, 'Valor_Residual']
            )

        flujo['Flujo_Acumulado'] = flujo['Flujo_Neto'].cumsum()

        # --- Indicadores financieros ---
        flujos = flujo['Flujo_Neto'].to_numpy(dtype=float)
        van = float(np.sum([f / ((1 + tasa_descuento) ** i) for i, f in enumerate(flujos)]))
        inversion_total = float(inv_fv + inv_storage + inv_inv_fv + inv_inv_storage + inv_estructura + inv_materiales)

        tir = None
        if npf is not None:
            try:
                tir = float(npf.irr(flujos))
            except Exception:
                tir = None

        payback = None
        no_neg = np.where(flujo['Flujo_Acumulado'].to_numpy(dtype=float) >= 0)[0]
        if len(no_neg) > 0:
            payback = int(no_neg[0])

        # Persistencia en resultados
        self.df_flujo = flujo
        self.resultados_opt['tecnologia_flujo_caja'] = tecnologia
        self.resultados_opt['vida_bateria_anios'] = vida_bateria
        self.resultados_opt['km_bateria_anual'] = km_bateria_anual
        self.resultados_opt['inv_fv'] = inv_fv
        self.resultados_opt['inv_storage'] = inv_storage
        self.resultados_opt['inv_inv_fv'] = inv_inv_fv
        self.resultados_opt['inv_inv_storage'] = inv_inv_storage
        self.resultados_opt['inv_inversores_total'] = inv_inversores_total
        self.resultados_opt['inv_estructura'] = inv_estructura
        self.resultados_opt['inv_materiales'] = inv_materiales
        self.resultados_opt['ahorro_autogeneracion_anual'] = ahorro_autogen_y1
        self.resultados_opt['Inversion_Total'] = inversion_total
        self.resultados_opt['inversion_total'] = inversion_total
        self.resultados_opt['VAN'] = van
        self.resultados_opt['TIR'] = tir
        self.resultados_opt['Payback'] = payback
        self.resultados_opt['Payback_simple'] = payback

        self.log("📊 Resumen Flujo de Caja")
        self.log(f"-> Inversión total: {inversion_total:,.2f}")
        self.log(f"-> VAN: {van:,.2f}")
        if tir is not None:
            self.log(f"-> TIR: {tir * 100:.2f}%")
        else:
            self.log("-> TIR: no disponible")
        if payback is not None:
            self.log(f"-> Payback simple: {payback} años")
        else:
            self.log("-> Payback simple: no recupera inversión en horizonte evaluado")