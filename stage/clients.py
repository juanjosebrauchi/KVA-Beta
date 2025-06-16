import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


class Cliente:
    def __init__(self, indice, datos, path_consumo_base, path_consumo_extra, path_BBDD_clientes, path_consumo_zona, vector_prueba=None, cliente_actual=None):
        self.indice = indice
        self.datos = datos
        self.cliente_actual = cliente_actual
        self.tipo_zona = datos.get('Zona', 'No aplica')
        self.path_consumo_base = path_consumo_base
        self.path_consumo_extra = path_consumo_extra
        self.path_consumo_zona = path_consumo_zona 
        self.vector_prueba = vector_prueba
        self.path_BBDD_clientes = path_BBDD_clientes   
        self.df_consumo_base = None  
        self.df_consumo_extra = None
        self.consumo_total = None 
        self.n_luces = None
        self.vector_prueba_extendido = None
        self.df_consumo_extra_resumen = None                                               
        self.df_cliente_filtrado = None      # DataFrame filtrado de consumo extra del cliente                       
        self.df_cliente_total = None        # DataFrame de consumo total del cliente
        self.factor_mes_cliente = None  # Factor de escala mensual del cliente
        self.factor_dia = None          # Factor de escala dia del cliente
        self.pdem_escalado = None   # Perfil horario escalado del cliente
        self.perfil_1h = None  # Perfil de consumo reducido a 1 hora
        self.inicio_invierno = None  # Mes de inicio del invierno según la zona
        self.fin_invierno = None  # Mes de fin del invierno según la zona
        self.consumo_anual = None # Matriz de consumo anual (24x12)
        self.factores_trapezoidales = None  # Factores trapezoidales de calefacción
        self.m2_calefaccion = None
        self.btu_requeridos = None
        self.costo_calefaccion = None
        self.potencia_calefaccion = None
        self.perfil_demanda_cliente = None

    def ejecutar(self, ruta_perfil_base = None, ruta_perfil_extra = None, path_BBDD_clientes = None):
        print(self.datos)
        """Método principal que ejecuta todos los cálculos del cliente"""
        ##Carga de Perfiles
        if ruta_perfil_base is None:
            ruta_perfil_base = self.path_consumo_base  # ✅ usa el del constructor si no se pasa
        self.cargar_perfil_consumo_base(ruta_perfil_base)
        if ruta_perfil_extra is None:
            ruta_perfil_extra = self.path_consumo_extra
        self.cargar_perfil_consumo_extra(ruta_perfil_extra)
        ## Cálculos 
        self.extender_vector_por_cine()
        self.calcular_numero_luces_perfil_extra()
        self.calculo_consumo_total_perfil_base()
        self.filtrar_consumo_por_dispositivos_cliente()
        self.resumir_consumo_extra()
        self.consumo_baseyextra_total()
        if path_BBDD_clientes is None:
            path_BBDD_clientes = self.path_BBDD_clientes
        self.generador_factor_meses(path_BBDD_clientes)
        self.agrupar_perfil_horario()
        self.calculo_consumo_anual()
        self.obtener_rango_invierno()
        self.calcular_factores_trapezoidales()
        self.function_heat(self.path_consumo_zona)

    def cargar_perfil_consumo_base(self, ruta_archivo):
        try:
            self.df_consumo_base = pd.read_excel(ruta_archivo, nrows=144)
            print()
            print("📊 Perfil base de consumo cargado correctamente.")
        except Exception as e:
            print(f"❌ Error al cargar perfil base de consumo: {e}")
            self.df_consumo_base = None

    def cargar_perfil_consumo_extra(self, ruta_archivo):    
        try:
            self.df_consumo_extra = pd.read_excel(ruta_archivo, nrows=144)
            print("📊 Perfil extra de consumo cargado correctamente.")
        except Exception as e:
            print(f"❌ Error al cargar perfil extra de consumo: {e}")
            self.df_consumo_extra = None

    def extender_vector_por_cine(self):
        """Extiende el vector de electrodomésticos con una regla basada en 'Cine en casa'.
        Guarda el resultado en self.vector_prueba_extendido.
        """
        
        if self.vector_prueba is None:
            print("⚠️ No hay vector_prueba definido.")
            return

        # Copia segura del vector actual
        vector_extendido = self.vector_prueba.copy()
        print(vector_extendido)

        # Evaluar el último valor del vector
        ultimo_valor = vector_extendido[-1]

        # Aplicar la regla de extensión
        vector_extendido.append(1 if ultimo_valor == 1 else 0)

        # Guardar en nuevo atributo sin sobrescribir el original
        self.vector_prueba_extendido = vector_extendido
        print()
        print("🧩 Vector con consumos domésticos extendido (con Cine en casa):", self.vector_prueba_extendido)
        print()

    def calcular_numero_luces_perfil_extra(self):
        try:
            habitaciones = int(self.datos.get('N° habitaciones', 0))
            banos = int(self.datos.get('N° baños', 0))
            self.n_luces = 2 * habitaciones + banos
        except Exception as e:
            print(f"⚠️ Error al calcular N° Luces: {e}")
            self.n_luces = None

    def calculo_consumo_total_perfil_base(self):
        try:
            if self.df_consumo_base is None:
                print("⚠️ No se ha cargado el perfil base de consumo.")
                return

            # Validar que n_luces esté disponible
            if self.n_luces is None:
                print("⚠️ Número de luces no está definido. Ejecuta calcular_numero_luces() primero.")
                return

            df = self.df_consumo_base.copy()

            # Multiplicar 'Bath_Light' por el número de luces
            df['Bath_Light'] = df['Bath_Light'] * self.n_luces
            print(f"💡 Número total de luces: {self.n_luces}")
            print(df['Bath_Light'])

            # Verificar si el cliente está en teletrabajo
            home_office = self.datos.get('Teletrabajo', '').strip()
            print()
            print(f"🏠 Teletrabajo: {home_office}")
            if home_office == 'Si':
                df['Consumo_Total'] = df.iloc[:, 2:].sum(axis=1)
            else:
                df['Consumo_Total'] = df.iloc[:, 2:14].sum(axis=1)

            self.consumo_total = df[['Hour', 'Minute', 'Consumo_Total']]
            print()
            print("⚡ Consumo total de perfil base incorporando el número de luces y la opción de teletrabajo.")
            print(self.consumo_total)
            print("🔢 Suma total del consumo base:", self.consumo_total['Consumo_Total'].sum(), "[kWh]")

        except Exception as e:
            print(f"❌ Error al calcular consumo total: {e}")
            self.consumo_total = None
    
    def filtrar_consumo_por_dispositivos_cliente(self):
        """Filtra el DataFrame de consumo extra usando el vector extendido del cliente."""
        if self.vector_prueba_extendido is None:
            print("⚠️ No se ha generado el vector extendido.")
            return

        if self.df_consumo_extra is None:
            print("⚠️ No se ha cargado el perfil de consumo extra.")
            return

        try:
            # Seleccionar solo las columnas correspondientes (asumimos que están ordenadas)
            columnas_seleccionadas = self.df_consumo_extra.columns[2:]  # omitir Hour y Minute si existen
            # print("🔍 Filtrando columnas del DataFrame de consumo extra:")
            # print(columnas_seleccionadas)

            # Multiplicar columna por columna con el vector
            df_filtrado = self.df_consumo_extra[columnas_seleccionadas].mul(self.vector_prueba_extendido, axis=1)
            suma_columnas = df_filtrado.sum()
            suma_mayor_a_cero = suma_columnas[suma_columnas > 0]
            print()
            print("\n📊 Consumo de electrodomésticos del cliente:")
            print(suma_mayor_a_cero)

            # Agregar columnas Hour y Minute nuevamente si están
            if 'Hour' in self.df_consumo_extra.columns and 'Minute' in self.df_consumo_extra.columns:
                df_filtrado.insert(0, 'Minute', self.df_consumo_extra['Minute'])
                df_filtrado.insert(0, 'Hour', self.df_consumo_extra['Hour'])

            self.df_cliente_filtrado = df_filtrado  # guardar resultado final      

        except Exception as e:
            print(f"❌ Error al filtrar consumo por vector: {e}")
            self.df_cliente_filtrado = None

    def resumir_consumo_extra(self):

        """Calcula el consumo total por intervalo de los electrodomésticos extra filtrados."""
        if self.df_cliente_filtrado is None:
            print("⚠️ No hay DataFrame filtrado disponible.")
            return

        try:
            # df = self.df_cliente_filtrado.copy()
            df = self.df_cliente_filtrado.copy()
            print(df.columns)

            # Sumar consumo por fila
            df['TotalConsumo'] = df.drop(columns=['Hour', 'Minute'], errors='ignore').sum(axis=1)


            # Agregar Hour y Minute si no están
            if 'Hour' not in df.columns and hasattr(self, 'df_consumo_extra'):
                if 'Hour' in self.df_consumo_extra.columns:
                    df['Hour'] = self.df_consumo_extra['Hour']
                if 'Minute' in self.df_consumo_extra.columns:
                    df['Minute'] = self.df_consumo_extra['Minute']

            # Reordenar columnas si es necesario
            columnas_finales = ['Hour', 'Minute', 'TotalConsumo']
            columnas_existentes = [col for col in columnas_finales if col in df.columns]

            print("\n📊 Consumo Total Electrodomésticos Extra")
            print("-----------------------------------------")
            print(df[columnas_existentes])
            print("-----------------------------------------")
            print("🔌 Consumo total acumulado:", df['TotalConsumo'].sum(), "[Wh]")

            self.df_consumo_extra_resumen = df[columnas_existentes + ['TotalConsumo'] if 'TotalConsumo' not in columnas_existentes else columnas_existentes]

        except Exception as e:
            print(f"❌ Error al resumir consumo extra: {e}")
            self.df_consumo_extra_resumen = None

    def consumo_baseyextra_total(self):
        """Combina el consumo total del perfil base y el perfil extra filtrado."""
        if self.consumo_total is None or self.df_consumo_extra_resumen is None:
            print("⚠️ No se han calculado los consumos base o extra.")
            return

        try:
            # Asegurarse de que ambos DataFrames tengan las mismas columnas Hour y Minute
            df_base = self.consumo_total.copy()
            df_extra = self.df_consumo_extra_resumen.copy()

            # Unir por Hour y Minute
            df_combined = pd.merge(df_base, df_extra, on=['Hour', 'Minute'], how='outer', suffixes=('_Base', '_Extra'))
            print("\n📊 Combinando consumos base y extra:")
            print(df_combined)

            # Calcular el consumo total combinado
            df_combined['Consumo_Total'] = df_combined['Consumo_Total'].fillna(0) + df_combined['TotalConsumo'].fillna(0)
            self.df_cliente_total = df_combined[['Hour', 'Minute', 'Consumo_Total']].copy()
            self.df_cliente_total.loc[:, 'Consumo_Total'] = self.df_cliente_total['Consumo_Total'].astype(float)
            # self.df_cliente_total = self.df_cliente_total.fillna(0)

            print("🔍 Resumen de consumo total del cliente:")
            print(self.df_cliente_total)
            print("⚡ Total de consumo:", self.df_cliente_total['Consumo_Total'].sum(), "[kWh]")

        except Exception as e:
            print(f"❌ Error al combinar consumos: {e}")

    def generador_factor_meses(self, path_csv):
        try:
            # Cargar la base de datos de clientes
            data_BBDD = pd.read_csv(path_csv, delimiter=';')

            # Extraer nombre del cliente actual
            # client_name = self.cliente_actual['Nombre']
            # cliente_info = data_BBDD[data_BBDD.iloc[:, 0] == client_name]
            # print("\nLista de Clientes")

            # Usar directamente el índice previamente capturado
            if 0 < self.indice <= len(data_BBDD):
                cliente_info = data_BBDD.iloc[self.indice].copy()
            else:
                raise IndexError(f"Índice {self.indice} fuera del rango de la base de datos.")

            # Filtrar la fila del cliente seleccionado
            # cliente_info = data_BBDD[data_BBDD.iloc[:, 0] == client_name]
            # print("---")
            # print("Datos Cliente Seleccionado")
            # print(cliente_info)

            # Extraer los valores de consumo mensual y convertir a lista
            # client_values = cliente_info.iloc[:, 1:].values.flatten().tolist()
            client_values = cliente_info.iloc[1:].values.flatten().tolist() 
            print(client_values)
            # print("Datos numéricos")
            # print(client_values)

            # Encontrar el valor máximo de consumo mensual
            max_dem = max(client_values)
            print("Demanda máxima: ", max_dem)

            # Calcular el factor mensual
            factor_mes = [round(val / max_dem,5) for val in client_values]
            print()
            print("Factor mensual:", factor_mes)

            # Guardar el DataFrame con factores mensuales
            self.factor_mes_cliente = pd.DataFrame(factor_mes, columns=["Factor"])

             # Cálculo del factor diario
            energia_dia = self.df_cliente_total['Consumo_Total'].sum()  # kWh/día aprox
            factor_dia = (max_dem / 30) / energia_dia
            self.factor_dia = factor_dia
   
            print("\n📆 Consumo diario estimado del perfil:", round(energia_dia, 2), "[kWh/día]")
            print("📆 Consumo diario máximo basado en BBDD:", round(max_dem / 30, 2), "[kWh/día]")
            print("📈 Factor de escala diario:", round(factor_dia, 4))


            # Aplicar el factor al perfil horario original
            df = self.df_cliente_total.copy()
            df['TotalConsumo'] = df['Consumo_Total'] * factor_dia
            self.pdem_escalado = df[['Hour', 'Minute', 'TotalConsumo']]

            print("\n✅ Perfil horario escalado del cliente:")
            print(self.pdem_escalado)

        except Exception as e:
            print(f"❌ Error en generador_factor_meses: {e}")

    def agrupar_perfil_horario(self):
        """
        Agrupa el perfil de consumo escalado (cada 10 minutos) en un perfil horario (1 hora).
        Guarda el resultado en self.perfil_1h.
        """
        try:
            if self.pdem_escalado is None:
                print("⚠️ No hay perfil escalado disponible para agrupar.")
                return

            perfil_10min = self.pdem_escalado["TotalConsumo"].values

            if len(perfil_10min) != 144:
                print(f"⚠️ Perfil esperado con 144 registros (24h * 6), pero tiene: {len(perfil_10min)}.")
                return

            consumo_1h = []
            energia_acumulada = 0
            contador = 0

            for consumo in perfil_10min:
                energia_acumulada += consumo
                contador += 1

                if contador == 6:
                    consumo_1h.append(energia_acumulada)
                    energia_acumulada = 0
                    contador = 0

            self.perfil_1h = pd.DataFrame(consumo_1h, columns=["Consumo_Total_1h"])

            print("\n📉 Perfil de consumo reducido a 1 hora:")
            print(self.perfil_1h)
            print(f"\n🔍 Consumo total original (10min): {sum(perfil_10min):.2f} kWh")
            print(f"🔍 Consumo total resumido (1h): {sum(consumo_1h):.2f} kWh")

        except Exception as e:
            print(f"❌ Error en agrupar_perfil_horario: {e}")

    def calculo_consumo_anual(self):
        """
        Genera una matriz 24x12 de consumo ajustado por factores mensuales.
        Guarda el resultado en self.consumo_anual.
        """
        nombres_meses = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                        'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
        
        print(self.perfil_1h['Consumo_Total_1h'])

        consumo_horario = self.perfil_1h['Consumo_Total_1h'] if isinstance(self.perfil_1h, pd.DataFrame) else self.perfil_1h
        print('Factor')
        print(self.factor_mes_cliente['Factor'])
        factores_mensuales = self.factor_mes_cliente['Factor'] if isinstance(self.factor_mes_cliente, pd.DataFrame) else self.factor_mes_cliente
        print("\n📊 Generando matriz de consumo anual...")
        print(factores_mensuales)

        self.consumo_anual = pd.DataFrame(
            data=[[round(h * f, 3) for f in factores_mensuales] for h in consumo_horario],
            columns=nombres_meses,
            index=[str(i) for i in range(24)]
        )
        print()
        print()
        print("📅 Matriz de consumo anual (kWh por hora para cada mes):")
        print(self.consumo_anual)

    def obtener_rango_invierno(self):
        """
        Determina el rango de meses de invierno según la zona del cliente.
        Guarda los resultados en atributos.
        """
        meses_invierno_por_zona = {
            'Z1': {'inicio': 6, 'fin': 8},
            'Z2': {'inicio': 5, 'fin': 9},
            'Z3': {'inicio': 4, 'fin': 10},
            'Z4': {'inicio': 4, 'fin': 11}
        }

        zona = self.datos.get('Tipo Zona')
        print()

        if zona in meses_invierno_por_zona:
            self.inicio_invierno = meses_invierno_por_zona[zona]['inicio']
            self.fin_invierno = meses_invierno_por_zona[zona]['fin']
            print(f"🌨️ Rango de invierno para zona {zona}: {self.inicio_invierno} a {self.fin_invierno} meses.")
        else:
            print("Zona no reconocida. Se usará rango por defecto (junio-agosto).")
            self.inicio_invierno = 6
            self.fin_invierno = 8

    def calcular_factores_trapezoidales(self):
        """Calcula los factores mensuales de calefacción con forma trapezoidal basados en la zona del cliente."""
        mes_inicio = self.inicio_invierno
        mes_fin = self.fin_invierno

        factores = [0.0] * 12

        for i in range(mes_inicio - 1):
            factores[i] = round((i + 1) / mes_inicio, 3)

        for i in range(mes_inicio - 1, mes_fin):
            factores[i] = 1.0

        duracion_bajada = 12 - mes_fin
        for i in range(mes_fin, 12):
            factores[i] = round(1 - ((i - mes_fin + 1) / (duracion_bajada + 1)), 3)

        self.factores_trapezoidales = factores
        print("\n📊 Factores trapezoidales de calefacción:")
        print(factores)

        # Opcional: Mostrar gráfico
        # meses = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
        # plt.figure(figsize=(10, 4))
        # plt.plot(meses, factores, marker='o', linestyle='-', color='black')
        # plt.title('Función Carga Mensual Trapezoidal Calefacción')
        # plt.xlabel('Meses')
        # plt.ylabel('Factor Zona')
        # plt.ylim(0, 1.1)
        # plt.grid(True)
        # plt.tight_layout()
        # plt.show()

    def function_heat(self, path_zone_heat: str):
        nombres_meses = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                        'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

        info_cliente = self.datos
        Factores_meses = self.factores_trapezoidales
        zona_cliente = self.datos.get('Tipo Zona') # Asumimos que ya fue calculado antes

        try:
            Rooms_heat = info_cliente.get('N° habitaciones que quiere calefaccionar', 0)
            if pd.isna(Rooms_heat): Rooms_heat = 0

            M2_heat = Rooms_heat * 15
            BTU_heat = Rooms_heat * 9000
            CLP_heat = Rooms_heat * 301.717
            POT_kW = Rooms_heat * 2.63

            data_Zone_Heat = pd.read_excel(path_zone_heat)
            horas = data_Zone_Heat['T'].tolist()

            Perfil_Mensual = pd.DataFrame(index=horas)

            for i, factor in enumerate(Factores_meses):
                columna = data_Zone_Heat[zona_cliente] * factor * POT_kW
                Perfil_Mensual[nombres_meses[i]] = columna.values

            # Sumar al perfil existente si desea calefacción
            Perfil_Demanda_Cliente = pd.DataFrame(0, index=np.arange(24), columns=nombres_meses)
            if info_cliente.get('Desea calefacción', 'No') == 'Si':
                for mes in nombres_meses:
                    Perfil_Demanda_Cliente[mes] = Perfil_Mensual[mes].values + self.consumo_anual[mes].values
            else:
                Perfil_Demanda_Cliente = self.consumo_anual.copy()
                M2_heat = BTU_heat = CLP_heat = POT_kW = 0

            # Guardar resultados en atributos
            self.m2_calefaccion = M2_heat
            self.btu_calefaccion = BTU_heat
            self.clp_calefaccion = CLP_heat
            self.potencia_calefaccion = POT_kW
            self.perfil_consumo_total_anual = Perfil_Demanda_Cliente

            # Log para inspección
            print("📊 Perfil de demanda con calefacción ajustado:")
            print(self.perfil_consumo_total_anual)

        except Exception as e:
            print(f"❌ Error en function_heat: {e}")

    

