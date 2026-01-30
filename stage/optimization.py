import pandas as pd
try:
    import numpy_financial as npf
except ImportError:
    npf = None
# from pyomo.environ import *
# from pyomo.opt import SolverFactory

class Optimizador:
    def __init__(self, indice, cliente_data, pdem_cliente, dimension, logger=None):
        """
        Inicializa el optimizador.
        :param indice: Índice del cliente.
        :param cliente_data: Diccionario con datos del cliente.
        :param pdem_cliente: Perfil de demanda del cliente.
        :param dimension: Resultados de la etapa de dimensionamiento (sizing).
        """
        self.indice = indice
        self.cliente_data = cliente_data
        self.pdem_cliente = pdem_cliente
        self.dimension = dimension
        self.logger = logger
        # Atributos para almacenar estado y resultados
        self.params = {}
        self.model = None
        self.resultados_opt = {}
        self.df_flujo = None

    def log(self, mensaje):
        if self.logger:
            self.logger.log(mensaje, prefijo="Optimizador")
        else:
            print(f"[Optimizador] {mensaje}")

    def ejecutar(self, gestor=None):
        """
        Ejecuta el flujo completo de optimización.
        """
        self.log(f"🚀 Iniciando proceso para cliente {self.indice}...")
        
        # 1. Lectura y preparación de parámetros
        self.leer_parametros()
        
        # 2. Construcción y resolución del modelo de optimización
        self.resolver_optimizacion(gestor)
        
        # 3. Post-análisis de los resultados técnicos
        self.post_analisis(gestor)
        
        # 4. Evaluación económica (Flujo de Caja)
        self.flujo_caja()
        
        self.log("✅ Proceso finalizado.")

    def leer_parametros(self):
        """
        Extrae y prepara los parámetros necesarios desde cliente_data y dimension.
        """
        self.log("📖 [1/4] Leyendo parámetros de entrada...")
        
        # Validar si dimension trae datos
        if not self.dimension:
            self.log("⚠️ Advertencia: 'dimension' está vacío o es None. Se usarán valores por defecto.")
            # Valores default para evitar crash
            self.params['capacidad_fv'] = 5.0 # kW
            self.params['baterias_cap'] = 10.0 # kWh
            self.params['costo_capex'] = 5000 # USD
        else:
            # Intentamos extraer información estructurada de 'dimension'
            # Adaptar estas claves a lo que realmente retorna sizing_backup.py
            # Nota: Ajusta las claves según la estructura real de tu objeto/diccionario dimension
            self.params['capacidad_fv'] = self.dimension.get('potencia_panel_total', 0) if isinstance(self.dimension, dict) else getattr(self.dimension, 'potencia_panel_total', 0)
            self.params['baterias_qty'] = self.dimension.get('num_baterias', 0) if isinstance(self.dimension, dict) else getattr(self.dimension, 'num_baterias', 0)
            # Ejemplo de extracción de costos
            self.params['costo_capex'] = self.dimension.get('costo_total_inversion', 0) if isinstance(self.dimension, dict) else getattr(self.dimension, 'costo_total_inversion', 0)

        # Parámetros económicos desde data cliente o defaults
        # Asumiendo estructura de cliente_data
        self.params['tarifa_energia'] = self.cliente_data.get('Tarifa', 0.15) # USD/kWh
        self.params['tasa_descuento'] = 0.10 # 10%
        self.params['horizonte'] = 20 # años
        self.params['inflacion'] = 0.03 # 3%

    def resolver_optimizacion(self, gestor):
        """
        Define y resuelve el modelo matemático con Pyomo.
        """
        self.log("⚙️ [2/4] Resolviendo optimización matemática...")
        
        model = ConcreteModel()
        
        # --- DEFINICIÓN DEL MODELO (Simplificado para el ejemplo) ---
        # Sets
        T = range(24) # Horizonte de 24 horas representativo
        model.T = Set(initialize=T)
        
        # Params
        demanda = self.pdem_cliente.iloc[0:24].values.flatten() if hasattr(self.pdem_cliente, 'iloc') else [1]*24
        # Normalizar o tomar un día representativo
        
        # Variables
        # x: Energía descargada de batería en hora t
        model.descarga = Var(model.T, domain=NonNegativeReals)
        
        # Objetivo: Minimizar el cuadrado de la diferencia (simulando peak shaving o similar)
        # Solo como placeholder. Aquí iría la lógica real de despacho.
        def obj_rule(m):
            return sum((demanda[t] - m.descarga[t])**2 for t in m.T)
        model.obj = Objective(rule=obj_rule, sense=minimize)
        
        # Restricciones
        # La descarga no puede superar la capacidad disponible por hora (simplificado)
        model.c_capacidad = Constraint(model.T, rule=lambda m, t: m.descarga[t] <= self.params.get('baterias_cap', 10) / 5.0)

        # Resolver
        solver_name = 'glpk'
        solver = SolverFactory(solver_name)
        
        try:
            results = solver.solve(model, tee=False)
            
            # Guardar resultados
            self.model = model
            self.resultados_opt['status'] = str(results.solver.status)
            self.resultados_opt['termination_condition'] = str(results.solver.termination_condition)
            self.resultados_opt['descarga_total'] = value(sum(model.descarga[t] for t in model.T))
            
            if gestor:
                gestor.resultados["optimization"] = self.resultados_opt
                self.log(f"Etapa 3: Optimización completada. Obj={value(model.obj):.2f}")
                
        except Exception as e: # Catch broadly (ApplicationError not imported by default sometimes)
            self.log(f"⚠️ Error: Solver '{solver_name}' falló o no encontrado ({e}). Saltando resolución.")
            self.resultados_opt['status'] = 'Error'
            self.resultados_opt['descarga_total'] = 0

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