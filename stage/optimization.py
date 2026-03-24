import pandas as pd
import numpy as np
import os
from typing import Dict, List, Optional
from pytoolconfig import dataclass
try:
    import numpy_financial as npf
except ImportError:
    npf = None
import pyomo.environ as pyo
from pyomo.opt import SolverFactory

class Optimizador:
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
        
        # 1. Lectura y preparación de parámetros
        self.leer_parametros()
        
        # 2. Construcción y resolución del modelo de optimización
        # Optimización anual: 12 meses × 24 horas = 288 periodos
        self.resolver_optimizacion(optimizar_anual=True)
        
        # Alternativa: Optimizar solo un mes específico
        # self.resolver_optimizacion(mes_idx=0)
        
        # # 3. Post-análisis de los resultados técnicos
        # self.post_analisis()
        
        # # 4. Evaluación económica (Flujo de Caja)
        # self.flujo_caja()
        
        self.log("✅ Proceso finalizado.")

    def leer_parametros(self):
        """
        Extrae y prepara los parámetros necesarios desde cliente_data y dimension.
        Mantiene los arrays de Demanda y Generación en formato estandarizado (12, 24) [Meses x Horas].
        """
        self.log("📖 [1/4] Leyendo parámetros de entrada...")
        
        # Configurar numpy para impresión limpia
        np.set_printoptions(suppress=True, precision=6)

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
            
            # Calculamos la capacidad total de baterías si tenemos cantidad
            # Asumimos una capacidad nominal por batería si no está explícita (ej. 2.4 kWh para 48V/50Ah)
            CAPACIDAD_NOMINAL_UNITARIA = 2.4 
            self.params['baterias_cap'] = self.params['baterias_qty'] * CAPACIDAD_NOMINAL_UNITARIA

        # Configuración operativa del modelo (editable desde cliente_data si existe).
        cfg = self.cliente_data if hasattr(self.cliente_data, 'get') else {}
        self.params['ongrid'] = cfg.get('ongrid', True)
        self.params['no_simultaneous_charge_discharge'] = cfg.get('no_simultaneous_charge_discharge', True)
        self.params['no_simultaneous_imp_exp'] = cfg.get('no_simultaneous_imp_exp', True)
        self.params['allow_ls'] = cfg.get('allow_ls', True)

        print(self.params)
        # # Parámetros económicos desde data cliente o defaults
        # # Asumiendo estructura de cliente_data
 

    def resolver_optimizacion(self, mes_idx: int = 0, optimizar_anual: bool = False):
        """
        Define y resuelve el modelo matemático con Pyomo.
        
        :param mes_idx: Índice del mes a optimizar (0-11) si optimizar_anual=False.
        :param optimizar_anual: Si True, optimiza los 12 meses simultáneamente (288 periodos).
        """
        self.log("⚙️ [2/4] Resolviendo optimización matemática...")
        
        # --- Construir datos de entrada desde atributos de clase ---
        cap_fv = self.params.get('capacidad_fv', 0.0)
        cap_bat = self.params.get('baterias_cap', 0.0)
        
        # --- MODO: Optimización Anual (12 meses × 24 horas) ---
        if optimizar_anual:
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
                    pv_avail_dict[t] = self.array_pgen[mes, hora] * cap_fv
            
            horizonte = list(range(288))  # 0 a 287
            self.log(f"📊 Total demanda anual: {sum(demand_dict.values()):.2f} kWh")
            self.log(f"📊 Total generación anual: {sum(pv_avail_dict.values()):.2f} kWh")
        
        # --- MODO: Optimización Mensual (24 horas) ---
        else:
            self.log(f"📅 Modo: Optimización mensual (mes {mes_idx+1}, 24 periodos)")
            
            # Validar que tengamos datos
            if self.array_pdem is None:
                self.log("⚠️ Warning: No hay datos de demanda. Usando valores por defecto.")
                demand_dict = {t: 1.0 for t in range(24)}
            else:
                demand_dict = {t: self.array_pdem[mes_idx, t] for t in range(24)}
            
            if self.array_pgen is None or cap_fv == 0:
                self.log("⚠️ Warning: No hay datos de generación o capacidad FV = 0.")
                pv_avail_dict = {t: 0.0 for t in range(24)}
            else:
                pv_avail_dict = {t: self.array_pgen[mes_idx, t] * cap_fv for t in range(24)}
            
            horizonte = list(range(24))  # 0 a 23
            self.log(f"📊 Demanda del mes: {sum(demand_dict.values()):.2f} kWh")
            self.log(f"📊 Generación del mes: {sum(pv_avail_dict.values()):.2f} kWh")
        
        # --- Precios de red ---
        # Extender precios para el horizonte correspondiente
        precio_base_compra = 0.15  # USD/kWh
        precio_base_venta = 0.05   # USD/kWh
        precio_compra = {t: precio_base_compra for t in horizonte}
        precio_venta = {t: precio_base_venta for t in horizonte}

        # Configuracion operativa configurable desde params.
        ongrid_flag = self.params.get('ongrid', True)
        no_sim_bat_flag = self.params.get('no_simultaneous_charge_discharge', True)
        no_sim_grid_flag = self.params.get('no_simultaneous_imp_exp', True)
        allow_ls_flag = self.params.get('allow_ls', True)
        
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
            'e_final_min': cap_bat * 0.5 if optimizar_anual and cap_bat > 0 else None,  # Ciclicidad anual
            # Grid parameters
            'ongrid': ongrid_flag,
            'grid_buy_price': precio_compra,
            'grid_sell_price': precio_venta,
            'p_imp_max': 100.0,
            'p_exp_max': cap_fv if cap_fv > 0 else 0.0,
            'no_simultaneous_imp_exp': no_sim_grid_flag,
            # Load shedding
            'allow_ls': allow_ls_flag,
            'ls_penalty': 10000.0,
        }

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

        if optimizar_anual:
            dias_mes = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
            mes_de_t = {t: (t // 24) for t in T_list}
            hora_de_t = {t: (t % 24) for t in T_list}
            peso_t = {t: dias_mes[mes_de_t[t]] for t in T_list}
        else:
            dias_mes = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
            mes_de_t = {t: mes_idx for t in T_list}
            hora_de_t = {t: t for t in T_list}
            peso_t = {t: dias_mes[mes_idx] for t in T_list}

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

        ## Variable de decisión: uso de PV 
        model.pv_use = pyo.Var(model.T, domain=pyo.NonNegativeReals)
        
        ## Variable de decisión: uso de batería
        model.p_ch = pyo.Var(model.T, domain=pyo.NonNegativeReals)
        model.p_dis = pyo.Var(model.T, domain=pyo.NonNegativeReals)
        model.e = pyo.Var(model.T, domain=pyo.NonNegativeReals)

        ## Variable de decisión: Energia no suministrada (load shedding)
        model.ls = pyo.Var(model.T, domain=pyo.NonNegativeReals)

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

        # if not (data.no_simultaneous_charge_discharge and data.p_ch_max > 0 and data.p_dis_max > 0):
        #     model.c_pch_max = pyo.Constraint(model.T, rule=lambda m, t: m.p_ch[t] <= data.p_ch_max)
        #     model.c_pdis_max = pyo.Constraint(model.T, rule=lambda m, t: m.p_dis[t] <= data.p_dis_max)

        # model.c_e_min = pyo.Constraint(model.T, rule=lambda m, t: m.e[t] >= data.e_min)
        # model.c_e_max = pyo.Constraint(model.T, rule=lambda m, t: m.e[t] <= data.e_max)
        # model.c_pd_min = pyo.Constraint(model.T, rule=lambda m, t: m.p_diesel[t] >= data.pmin_diesel)
        # model.c_pd_max = pyo.Constraint(model.T, rule=lambda m, t: m.p_diesel[t] <= data.pmax_diesel)

        # if data.ongrid and data.p_imp_max is not None and not hasattr(model, 'c_pimp_flag'):
        #     model.c_pimp_max = pyo.Constraint(model.T, rule=lambda m, t: m.p_imp[t] <= data.p_imp_max)
        # if data.ongrid and data.p_exp_max is not None and not hasattr(model, 'c_pexp_flag'):
        #     model.c_pexp_max = pyo.Constraint(model.T, rule=lambda m, t: m.p_exp[t] <= data.p_exp_max)
        # if not data.ongrid:
        #     model.c_no_grid_imp = pyo.Constraint(model.T, rule=lambda m, t: m.p_imp[t] == 0)
        #     model.c_no_grid_exp = pyo.Constraint(model.T, rule=lambda m, t: m.p_exp[t] == 0)

        # if not data.allow_ls:
        #     model.c_no_ls = pyo.Constraint(model.T, rule=lambda m, t: m.ls[t] == 0)

        # def balance_rule(m, t):
        #     return m.pv_use[t] + m.p_dis[t] + m.p_imp[t] + m.p_diesel[t] + m.ls[t] == m.D[t] + m.p_ch[t] + m.p_exp[t]

        # model.c_balance = pyo.Constraint(model.T, rule=balance_rule)

        # t_inicio_mes = {}
        # t_fin_mes = {}
        # for t in T_list:
        #     mes = mes_de_t[t]
        #     hora = hora_de_t[t]
        #     if hora == 0:
        #         t_inicio_mes[mes] = t
        #     if hora == 23:
        #         t_fin_mes[mes] = t

        # def soc_rule(m, t):
        #     hora = hora_de_t[t]
        #     if hora > 0:
        #         t_prev = t - 1
        #     else:
        #         mes = mes_de_t[t]
        #         t_prev = t_fin_mes[mes]
        #     return m.e[t] == m.e[t_prev] + data.eff_ch * m.p_ch[t] - (1.0 / data.eff_dis) * m.p_dis[t]

        # model.c_soc = pyo.Constraint(model.T, rule=soc_rule)

        # def monthly_cycle_rule(m, mes):
        #     t0 = t_inicio_mes[mes]
        #     tf = t_fin_mes[mes]
        #     return m.e[t0] == m.e[tf]

        # model.M = pyo.Set(initialize=sorted(t_inicio_mes.keys()))
        # model.c_cycle_month = pyo.Constraint(model.M, rule=monthly_cycle_rule)

        # if data.e_init is not None and len(model.M) > 0:
        #     primer_mes = min(list(model.M))
        #     t0 = t_inicio_mes[primer_mes]
        #     model.c_e_init = pyo.Constraint(expr=model.e[t0] == data.e_init)

        # if data.e_final_min is not None and len(model.M) > 0:
        #     ultimo_mes = max(list(model.M))
        #     tf = t_fin_mes[ultimo_mes]
        #     model.c_e_final_min = pyo.Constraint(expr=model.e[tf] >= data.e_final_min)

        # def obj_rule(m):
        #     return sum(
        #         m.w[t] * (
        #             m.p_buy[t] * m.p_imp[t]
        #             - m.p_sell[t] * m.p_exp[t]
        #             + data.var_cost_diesel * m.p_diesel[t]
        #             + data.ls_penalty * m.ls[t]
        #             + data.batt_cycle_cost * (m.p_ch[t] + m.p_dis[t])
        #         )
        #         for t in m.T
        #     )

        # model.obj = pyo.Objective(rule=obj_rule, sense=pyo.minimize)

        # self.log('✅ Modelo construido con FO anual ponderada y ciclicidad mensual SOC.')

        # solver_name = 'glpk'
        # solver = SolverFactory(solver_name)

        # try:
        #     results = solver.solve(model, tee=False)

        #     self.model = model
        #     self.resultados_opt['status'] = str(results.solver.status)
        #     self.resultados_opt['termination_condition'] = str(results.solver.termination_condition)
        #     self.resultados_opt['objective_usd'] = pyo.value(model.obj)

        #     energia_importada = sum(pyo.value(model.p_imp[t]) * peso_t[t] for t in T_list)
        #     energia_exportada = sum(pyo.value(model.p_exp[t]) * peso_t[t] for t in T_list)
        #     energia_shed = sum(pyo.value(model.ls[t]) * peso_t[t] for t in T_list)

        #     self.resultados_opt['energia_importada_kwh_anual'] = energia_importada
        #     self.resultados_opt['energia_exportada_kwh_anual'] = energia_exportada
        #     self.resultados_opt['energia_no_suministrada_kwh_anual'] = energia_shed
        #     self.resultados_opt['descarga_total'] = sum(pyo.value(model.p_dis[t]) * peso_t[t] for t in T_list)

        #     costos_mensuales = {}
        #     for mes in sorted(t_inicio_mes.keys()):
        #         t_mes = [t for t in T_list if mes_de_t[t] == mes]
        #         c_mes = sum(
        #             peso_t[t] * (
        #                 buy[t] * pyo.value(model.p_imp[t])
        #                 - sell[t] * pyo.value(model.p_exp[t])
        #                 + data.var_cost_diesel * pyo.value(model.p_diesel[t])
        #                 + data.ls_penalty * pyo.value(model.ls[t])
        #                 + data.batt_cycle_cost * (pyo.value(model.p_ch[t]) + pyo.value(model.p_dis[t]))
        #             )
        #             for t in t_mes
        #         )
        #         costos_mensuales[f'mes_{mes+1}'] = c_mes

        #     self.resultados_opt['costos_mensuales_usd'] = costos_mensuales
        #     self.log(f"✅ Optimización completada. Costo total: USD {self.resultados_opt['objective_usd']:.2f}")

        # except Exception as e:
        #     self.log(f"⚠️ Error: Solver '{solver_name}' falló o no encontrado ({e}).")
        #     self.resultados_opt['status'] = 'Error'
        #     self.resultados_opt['termination_condition'] = 'error'
        #     self.resultados_opt['objective_usd'] = None
        #     self.resultados_opt['descarga_total'] = 0

    def post_analisis(self, gestor):
        """
        Procesa los resultados brutos de la optimización para obtener KPIs.
        """
        self.log("📊 [3/4] Realizando post-análisis...")
        
        # Recuperar valores
        descarga_dia = self.resultados_opt.get('descarga_total', 0)
        
        # Extrapolar a año (muy simplificado)
        # Aquí deberías usar el perfil anual si optimizaste todo el año
        ahorro_energia_anual = descarga_dia * 365 
        
        # Guardar en resultados
        self.resultados_opt['ahorro_energia_anual'] = ahorro_energia_anual
        self.resultados_opt['analisis_completado'] = True
        
        self.log(f"-> Ahorro de energía estimado: {ahorro_energia_anual:.2f} kWh/año")

    def flujo_caja(self):
        """
        Genera el flujo de caja en Pandas basándose en los resultados.
        """
        self.log("💰 [4/4] Calculando Flujo de Caja...")
        
        horizonte = self.params.get('horizonte', 20)
        lista_anios = list(range(horizonte + 1))
        
        # Crear DataFrame
        flujo = pd.DataFrame(index=lista_anios)
        flujo.index.name = 'Año'
        
        capex = self.params.get('costo_capex', 0)
        ahorro_kwh = self.resultados_opt.get('ahorro_energia_anual', 0)
        tarifa = self.params.get('tarifa_energia', 0.15)
        inflacion = self.params.get('inflacion', 0.03)
        opex_pct = 0.015 # 1.5% del Capex
        
        # --- Construcción de columnas ---
        
        # 1. Inversión
        flujo['Inversion'] = 0.0
        flujo.loc[0, 'Inversion'] = -capex
        
        # 2. Ahorros (Ingresos)
        # Incrementamos la tarifa con la inflación (simplificado)
        tarifas_proyectadas = [tarifa * ((1 + inflacion)**t) for t in range(horizonte + 1)]
        # flujo['Tarifa_Proy'] = tarifas_proyectadas # Informativo
        
        # Asumimos degradación del 0.5% anual en generación/ahorro
        ahorros_energia = [ahorro_kwh * ((1 - 0.005)**(t-1)) if t > 0 else 0 for t in range(horizonte + 1)]
        flujo['Ahorro_Energia'] = [e * t for e, t in zip(ahorros_energia, tarifas_proyectadas)]
        
        # 3. Opex
        opex_anual = capex * opex_pct
        flujo['Opex'] = [-opex_anual * ((1 + inflacion)**t) if t > 0 else 0 for t in range(horizonte + 1)]
        
        # 4. Flujo Neto
        flujo['Flujo_Neto'] = flujo['Inversion'] + flujo['Ahorro_Energia'] + flujo['Opex']
        
        # --- Cálculo de Indicadores Económicos ---
        flujos_array = flujo['Flujo_Neto'].values
        tasa_desc = self.params.get('tasa_descuento', 0.10)
        
        # VAN (NPV)
        van = sum([f / ((1 + tasa_desc)**i) for i, f in enumerate(flujos_array)])
        
        # TIR (IRR)
        tir = None
        if npf:
            try:
                tir = npf.irr(flujos_array)
            except:
                pass

        self.df_flujo = flujo
        self.resultados_opt['VAN'] = van
        self.resultados_opt['TIR'] = tir
        
        self.log(f"-> VAN (NPV): USD {van:,.2f}")
        if tir is not None:
             self.log(f"-> TIR (IRR): {tir*100:.2f}%")