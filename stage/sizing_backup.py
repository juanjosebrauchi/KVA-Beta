import os
import pandas as pd

class Dimensionamiento:
    def __init__(self, indice, cliente_data, pdem_cliente, path_pgen, path_equipos, logger=None, interactive_mode=False):
        self.indice_cliente = indice
        self.cliente_data = cliente_data
        self.pdem_cliente = pdem_cliente
        self.path_pgen = path_pgen
        self.path_equipos = path_equipos
        self.logger = logger
        self.interactive_mode = interactive_mode
        # Leer hojas desde el archivo Excel de equipos
        self.eq_paneles    = pd.read_excel(self.path_equipos, sheet_name="Paneles")
        self.eq_inversores = pd.read_excel(self.path_equipos, sheet_name="Inversores")
        self.eq_baterias   = pd.read_excel(self.path_equipos, sheet_name="Baterias")
        self.eq_mppts      = pd.read_excel(self.path_equipos, sheet_name="MPPTs")
        self.df_pgen_cliente = None  # aquí se guardará el archivo Excel cargado
        self.resultados_por_paso = {}
        self.pasos_default = [0.4, 0.5, 0.8, 1.0]
        self.meses = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                      'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
        self.meses_criticos = None
        self.dimensionamiento_final = None
        self.panel_criterio_minprecio = None
        self.panel_criterio_avgprecio = None
        self.seleccion_mppt = None
        self.seleccion_mppt_paneles = None
        self.seleccion_inversor = None

    def log(self, mensaje):
        if self.logger:
            self.logger.log(mensaje, prefijo="Sizing")
        else:
            print(f"[Sizing] {mensaje}")

    def ejecutar(self, path_pgen=None, indice_cliente=None):
        
        self.log("🔄 Iniciando dimensionamiento del cliente...")
        if indice_cliente is None:
            indice_cliente = self.indice_cliente    
        if path_pgen is None:
            path_pgen = self.path_pgen

        # Cargar archivo PGEN
        self.cargar_archivo_pgen(path_pgen)

        # Obtener el tipo de solución del cliente
        tipo_solucion = self.cliente_data.get("Tipo de solución")

        # Lógica según tipo de solución
        if tipo_solucion == "OffGrid":
            self.dimensionar_offgrid_interactivo()
            sens_resultado =self.calc_sensibilidad_interactivo()
            rango = sens_resultado["Rango"]
            ediff = sens_resultado["EnergiaResidual"]
            self.calc_meses_criticos_interactivo(rango, ediff, self.meses)
            self.calcular_dimensionamiento_final_offgrid()
            seleccionador_paneles = SeleccionPanel(self.eq_paneles, self.dimensionamiento_final)
            paneles = seleccionador_paneles.ejecutar()
            self.panel_criterio_minprecio = paneles["Criterio_Min_Precio"]
            self.panel_criterio_avgprecio = paneles["Criterio_Avg_Precio"]
            seleccionador_mppt = SeleccionMPPT(self.eq_paneles, self.eq_mppts, self.dimensionamiento_final, self.panel_criterio_minprecio, self.panel_criterio_avgprecio)
            mppt = seleccionador_mppt.ejecutar()
            self.seleccion_mppt = mppt["MPPTs"]
            self.seleccion_mppt_paneles = mppt["Paneles_with_MPPT"]   
            seleccionador_inversor = SeleccionInversor(self.eq_inversores, self.dimensionamiento_final, self.seleccion_mppt)
            inversor = seleccionador_inversor.ejecutar()
            self.seleccion_inversor = inversor["Inversor"]
            seleccionador_bateria = SeleccionBateria(self.eq_baterias, self.dimensionamiento_final)
            self.seleccionador_bateria = seleccionador_bateria.ejecutar()

        elif tipo_solucion == "OnGrid":
            self.log("🔄 Iniciando dimensionamiento OnGrid...")
            # self.dimensionar_ongrid()
        elif tipo_solucion == "Hibrido":
            self.log("🔄 Iniciando dimensionamiento Híbrido...")
            # self.dimensionar_hibrido()
        else:
            self.log(f"❌ Tipo de solución no reconocido: {tipo_solucion}")
        # Aquí iría el resto de la lógica de dimensionamiento
        resultados_etapa = {
            "dimensionamiento_final": self.dimensionamiento_final,
            "mppt": self.seleccion_mppt,
            "inversor": self.seleccion_inversor,
            "bateria": getattr(self, 'seleccionador_bateria', None),
            "potencia_panel_total": self.dimensionamiento_final.get('Potencia_PV_Total_kW', 0) if self.dimensionamiento_final else 0,
            # Intento de extraer número de baterías si existe
            "num_baterias": getattr(self, 'seleccionador_bateria', {}).get('Num_Baterias', 0) if hasattr(self, 'seleccionador_bateria') and isinstance(self.seleccionador_bateria, dict) else 0,
            "costo_total_inversion": 15000  # Placeholder: Sumar costos reales aquí
        }
        return resultados_etapa
        # return self.resultados

    def cargar_archivo_pgen(self, base_path=None):
        """
        Carga el archivo Excel del cliente según su índice (número identificador).
        El archivo debe tener el formato PGEN_0X_NombreCliente.xlsx
        """
        # print(indice_cliente)
        aux = self.indice_cliente + 1
        # print(aux)

        if self.indice_cliente is None:
            raise ValueError("⚠️ No se ha definido 'indice_cliente'. Asigna un valor al instanciar la clase o antes de ejecutar el método.")

        # Asegurar que el índice tenga dos dígitos (por ejemplo, 1 -> 01)
        codigo = f"{int(aux):02d}"  

        # Buscar archivos en el directorio que empiecen con ese patrón
        archivos = os.listdir(base_path)
        archivo_cliente = None

        for archivo in archivos:
            if archivo.startswith(f"PGEN_{codigo}_") and archivo.endswith(".xlsx"):
                archivo_cliente = archivo
                break

        if archivo_cliente is None:
            raise FileNotFoundError(f"❌ No se encontró un archivo para el cliente con índice {codigo} en {base_path}")

        ruta_completa = os.path.join(base_path, archivo_cliente)
        print(f"📂 Archivo encontrado: {archivo_cliente}")

        # Cargar el archivo
        df_aux = pd.read_excel(ruta_completa, sheet_name='pv', header=None)
        print("✅ Archivo cargado correctamente.")
 
        # Extraer el rango: filas 6 a 17 (índice 5 a 16), columnas C a Z (índice 2 a 25)
        df_rango = df_aux.iloc[5:17, 2:26]

        # Asignar nombres de columnas: 1 a 24 (horas)
        df_rango.columns = list(range(1, 25))

        # Asignar nombres de fila: meses del año
        meses = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
        df_rango.index = meses
        # Mostrar el resultado
        print()
        print("📊 Perfil de generación cargado (kW):")
        print(df_rango)
        self.df_pgen_cliente = df_rango

    def dimensionar_offgrid(self, paso_pv=0.5):
        print("🔄 Iniciando dimensionamiento OffGrid...")
        # Lógica específica para dimensionamiento OffGrid

        print("🔋 Ejecutando dimensionamiento OffGrid...")

        meses = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

        # Validaciones
        if self.df_pgen_cliente is None or self.pdem_cliente is None:
            raise ValueError("Perfil_Gen_Cliente o Perfil_Dem_Cliente no están definidos.")

        # Calcular energía generada por mes (suma de columnas por fila)
        energia_pvgen = self.df_pgen_cliente.sum(axis=1).tolist()

        # Calcular energía demandada por mes (suma de filas por columna)
        energia_dem = self.pdem_cliente.sum(axis=0).tolist()

        # Reporte previo
        print("📊 Tabla de Energía Generada vs Demandada (por mes):")
        print("Mes    - EGen [kWh] - EDem [kWh]")
        for i in range(12):
            print(f"{meses[i]:<6} - {energia_pvgen[i]:10.2f} - {energia_dem[i]:10.2f}")

        # Cálculo de potencia mínima por mes
        pot_pv = [0] * 12
        for i in range(12):
            pv_n = 1.0
            while energia_pvgen[i] * pv_n < energia_dem[i]:
                pv_n += paso_pv
            pot_pv[i] = round(pv_n, 2)

        # Reporte final
        print("\n⚙️ Resultado del dimensionamiento:")
        print("Mes    - PotPV [kW] - EGen [kWh] - EDem [kWh]")
        for i in range(12):
            eg = energia_pvgen[i] * pot_pv[i]
            ed = energia_dem[i]
            print(f"{meses[i]:<6} - {pot_pv[i]:10.2f} - {eg:10.2f} - {ed:10.2f}")

        # Puedes guardar resultados en atributos
        self.potencia_pv_mensual = pot_pv
        self.energia_generada_mensual = energia_pvgen
        self.energia_demandada_mensual = energia_dem

        return {
            "Meses": meses,
            "Potencias": pot_pv,
            "EnergiaGenerada": energia_pvgen,
            "EnergiaDemandada": energia_dem,
            "PasoPV": paso_pv
            }

    def dimensionar_offgrid_interactivo(self, paso_por_defecto=0.4):
        paso_actual = paso_por_defecto

        while True:
            print(f"\n📊 Ejecutando cálculo OffGrid con paso: {paso_actual:.2f} kW")

            # Ejecutar el cálculo con el paso actual
            resultado = self.dimensionar_offgrid(paso_pv=paso_actual)
            
            potencias = resultado["Potencias"]
            meses = resultado["Meses"]
            pot_min = min(potencias)
            mes_min = meses[potencias.index(pot_min)]
            pot_max = max(potencias)
            mes_max = meses[potencias.index(pot_max)]
            print(f"   ➤ Potencia mínima: {pot_min:.2f} kW en {mes_min}")
            print(f"   ➤ Potencia máxima: {pot_max:.2f} kW en {mes_max}")

            # Preguntar si desea cambiar el paso (solo si interactive_mode está activo)
            if self.interactive_mode:
                print("Paso por defecto es 0.4 kW. Puedes modificarlo para ver cómo afecta el dimensionamiento.")
                respuesta = input("\n¿Deseas modificar el paso? (Y/N): ").strip().lower()
                if respuesta != 'y':
                    print("✅ Continuando con el proceso usando el paso actual.")
                    break

                # Ingresar nuevo valor personalizado
                while True:
                    try:
                        nuevo_paso = float(input("🔧 Ingresa nuevo valor de paso (en kW): "))
                        if nuevo_paso > 0:
                            paso_actual = nuevo_paso
                            break
                        else:
                            print("⚠️ El paso debe ser mayor que 0.")
                    except ValueError:
                        print("⚠️ Entrada inválida. Ingresa un número válido.")
            else:
                # Modo no interactivo: usar valor por defecto y continuar
                print("✅ Continuando con el proceso usando el paso actual.")
                break

    def calc_sensibilidad(self, paso, pot_max=None):
        """
        Calcula la sensibilidad de la energía residual para distintos escenarios de potencia instalada.
        """
        if pot_max is None:
            if not hasattr(self, 'potencia_pv_mensual'):
                raise ValueError("No se ha definido una potencia PV base.")
            pot_max = max(self.potencia_pv_mensual)
        
        print('El paso utilizado es: ', paso, 'kW')

        energia_pvgen = self.energia_generada_mensual
        energia_dem = self.energia_demandada_mensual
        meses = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

        dim_pot = [pot_max - paso*2, pot_max - paso, pot_max, pot_max + paso, pot_max + paso*2]
        ediff = pd.DataFrame(columns=range(5), index=range(12))

        for i in range(5):
            for j in range(12):
                ediff.loc[j, i] = energia_pvgen[j] * dim_pot[i] - energia_dem[j]

        # Mostrar tabla
        print("\n📉 Análisis de Sensibilidad - Energía Residual:")
        print("Mes   | {:>6.2f} | {:>6.2f} || {:>6.2f} || {:>6.2f} | {:>6.2f} [kWp]".format(*dim_pot))
        print("---------------------------------------------------------------")
        for i in range(12):
            print(f"{meses[i]:<6} | " +
                " | ".join(f"{ediff.iloc[i, col]:6.2f}" for col in range(5)) +
                " [kWh]")

        diff_max = max(ediff[2])  # Potencia nominal (posición central)
        diff_min = min(ediff[2])
        rango = diff_max - diff_min

        print("\n📊 Rango de energía residual (Pot. nominal = {:.2f} kWp):".format(dim_pot[2]))
        print(f"🔼 Máxima energía residual: {diff_max:.2f} kWh")
        print(f"🔽 Mínima energía residual: {diff_min:.2f} kWh")
        print(f"📏 Rango total: {rango:.2f} kWh")

        return {
            "Rango": rango,
            "EnergiaResidual": ediff,
            "Potencias": dim_pot
        }
    
    def calc_sensibilidad_interactivo(self):
        print("📈 Iniciando análisis de sensibilidad...")

        paso = 0.5  # Paso por defecto
        resultado = self.calc_sensibilidad(paso)

        # Solo solicitar modificación si interactive_mode está activo
        if self.interactive_mode:
            while True:
                respuesta = input("\n❓ ¿Deseas modificar el valor del paso? (Y/N): ").strip().lower()
                if respuesta == 'y':
                    try:
                        paso = float(input("📥 Ingresa el nuevo valor de paso (ej. 0.2, 0.6): "))
                        resultado = self.calc_sensibilidad(paso)
                    except ValueError:
                        print("⚠️ Valor inválido. Asegúrate de ingresar un número decimal.")
                elif respuesta == 'n':
                    print("✅ Continuando con el proceso final del análisis...")
                    break
                else:
                    print("⚠️ Respuesta no válida. Ingresa 'Y' para sí o 'N' para no.")
        else:
            # Modo no interactivo: usar valor por defecto
            print("✅ Continuando con el proceso final del análisis...")
        
        return resultado
    
    def calc_meses_criticos_interactivo(self, rango, ediff, meses):
        print("\n🔍 Analizando meses críticos...")

        diff_pp = 10.0  # valor por defecto
        print(f"\n⚙️ Calculando meses críticos con sensibilidad del {diff_pp:.1f}%...")
        mc_trigg = rango * (diff_pp / 100)
        mc_ix = []
        mc_value = []

        for idx, val in enumerate(ediff.loc[:, 2]):
            if mc_trigg > val:
                mc_ix.append(idx)
                mc_value.append(val)

        # Mostrar resultados
        if not mc_ix:
            print("✅ No se detectaron meses críticos bajo el umbral especificado.")
        else:
            print("\n📌 Los Meses Críticos son:")
            for i, idx in enumerate(mc_ix):
                print(f"{i+1}. {meses[idx]} con energía residual de {mc_value[i]:.2f} [kWh]")

        # Guardar en atributo
        self.meses_criticos = {
            "indices": mc_ix,
            "valores": mc_value,
            "meses": [meses[i] for i in mc_ix],
            "umbral_kWh": mc_trigg,
            "porcentaje": diff_pp
        }

        # Solo solicitar modificación si interactive_mode está activo
        if self.interactive_mode:
            while True:
                respuesta = input("\n¿Deseas probar con otro porcentaje de sensibilidad? (Y/N): ").strip().lower()
                if respuesta == 'y':
                    while True:
                        try:
                            diff_pp = float(input("Ingrese nuevo porcentaje de sensibilidad (ej: 15 para 15%): "))
                            if diff_pp <= 0 or diff_pp >= 100:
                                print("⚠️ Debe ingresar un valor entre 1 y 99.")
                                continue
                            break
                        except ValueError:
                            print("⚠️ Por favor, ingrese un número válido.")
                    
                    # Recalcular con el nuevo valor
                    print(f"\n⚙️ Calculando meses críticos con sensibilidad del {diff_pp:.1f}%...")
                    mc_trigg = rango * (diff_pp / 100)
                    mc_ix = []
                    mc_value = []

                    for idx, val in enumerate(ediff.loc[:, 2]):
                        if mc_trigg > val:
                            mc_ix.append(idx)
                            mc_value.append(val)

                    # Mostrar resultados
                    if not mc_ix:
                        print("✅ No se detectaron meses críticos bajo el umbral especificado.")
                    else:
                        print("\n📌 Los Meses Críticos son:")
                        for i, idx in enumerate(mc_ix):
                            print(f"{i+1}. {meses[idx]} con energía residual de {mc_value[i]:.2f} [kWh]")

                    # Actualizar en atributo
                    self.meses_criticos = {
                        "indices": mc_ix,
                        "valores": mc_value,
                        "meses": [meses[i] for i in mc_ix],
                        "umbral_kWh": mc_trigg,
                        "porcentaje": diff_pp
                    }
                else:
                    print("✅ Análisis de meses críticos finalizado.")
                    break
        else:
            # Modo no interactivo: usar valor por defecto
            print("✅ Análisis de meses críticos finalizado.")

        return mc_ix
    
    def calcular_dimensionamiento_final_offgrid(self):
        print("\n🔧 Paso 3: Dimensionamiento final OffGrid")

        # Potencia del Inversor
        dim_p_inv = max(self.pdem_cliente.max().to_list())
        print(f"⚡ Potencia máxima demandada: {dim_p_inv:.2f} [kW]")

        # Potencia FV máxima
        pot_max = max(self.potencia_pv_mensual)
        dim_p_pv = pot_max
        print(f"🔆 Potencia PV instalada: {dim_p_pv:.2f} [kW]")

        # Energía demandada en la noche en meses críticos
        energia_dem_noche = []
        meses_criticos = self.meses_criticos["indices"]
        meses_nombres = self.meses_criticos.get("meses", [])

        def ventana_tiempo(perfil):
            flag = True
            dgen_anterior = 0
            for i, dgen in enumerate(perfil):
                diff = dgen - dgen_anterior
                if diff > 0 and flag:
                    tx1 = i
                    flag = False
                if diff < 0:
                    tx2 = i - 1
                dgen_anterior = dgen
            return tx1, tx2

        for i, mes in enumerate(meses_criticos):
            perfil_mes_pv = self.df_pgen_cliente.iloc[mes, :].to_list()
            tz1, tz2 = ventana_tiempo(perfil_mes_pv)

            energia_total = self.pdem_cliente.iloc[:, mes].sum()
            energia_dia = self.pdem_cliente.iloc[tz1:tz2+1, mes].sum()
            energia_noche = energia_total - energia_dia

            energia_dem_noche.append(energia_noche)
            mes_nombre = meses_nombres[i] if meses_nombres else f"Mes {mes}"
            print(f"🌙 {mes_nombre}: Energía demanda noche = {energia_noche:.2f} [kWh]")

        autonomia_prom = sum(energia_dem_noche) / len(energia_dem_noche)
        print(f"\n🔋 Autonomía promedio requerida: {autonomia_prom:.2f} [kWh]")

        # Guardar resultados
        self.dimensionamiento_final = {
            "Potencia_Inversor": dim_p_inv,
            "Potencia_PV": dim_p_pv,
            "Energia_Demanda_Noche": energia_dem_noche,
            "Autonomia_Promedio": autonomia_prom
        }

class SeleccionPanel:
    def __init__(self, df_paneles, dimensionamiento_final):
        self.df_paneles = df_paneles
        self.dimensionamiento_final = dimensionamiento_final
        self.num_paneles = []
        self.precios_totales = []
        self.panel_seleccionado_criterio_avgprecio = None
        self.panel_seleccionado_criterio_minprecio = None
        
    def ejecutar(self):
        print("\n🔍 Iniciando selección de paneles fotovoltaicos...")
        return self.ejecutar_seleccion()

    def presentar_paneles(self):
        print("📋 Paneles disponibles en base de datos:\n")
        print(self.df_paneles.head(), "\n")

    def numero_paneles(self):
        df_paneles = self.df_paneles
        dim_p_pv_kw = self.dimensionamiento_final["Potencia_PV"]

        len_pv = len(df_paneles)
        self.num_paneles = []
        self.precios_totales = []

        for i in range(len_pv):
            pot_panel = df_paneles.loc[i, 'Potencia nominal (W)']
            precio_unit = df_paneles.loc[i, 'Precio CLP']

            cantidad = int((dim_p_pv_kw * 1000) // pot_panel) + ((dim_p_pv_kw * 1000) % pot_panel > 0)
            total_precio = cantidad * precio_unit

            self.num_paneles.append(cantidad)
            self.precios_totales.append(total_precio)

        print("\n📊 Comparativa de Paneles Solares")
        print("Potencia PV [Wp] | Cant de Paneles [-] | Precio Total [CLP]")
        print("-----------------------------------------------------------")
        for i in range(len_pv):
            print("{:16d} | {:18d} | {:14,d}".format(
                df_paneles.loc[i, 'Potencia nominal (W)'],
                self.num_paneles[i],
                self.precios_totales[i]
            ))

    def aplicar_criterio_minprecio(self):
        precios = self.precios_totales
        df = self.df_paneles

        ix_min = precios.index(min(precios))

        self.panel_seleccionado_minprecio = {
            "Potencia_Wp": df.loc[ix_min, 'Potencia nominal (W)'],
            "Cantidad": self.num_paneles[ix_min],
            "Precio_unitario": df.loc[ix_min, 'Precio CLP'],
            "Precio_total": precios[ix_min],
            "Vmp": df.loc[ix_min, 'Vmp (V)'],
            "Imp": df.loc[ix_min, 'Imp (A)'],
        }

        print("\n💰 Caso Menor Precio")
        print(f"Menor inversión en paneles: ${precios[ix_min]:,} CLP")
        print(f"Potencia PV seleccionada: {df.loc[ix_min,'Potencia nominal (W)']} [Wp]")
        print(f"Cantidad de paneles: {self.num_paneles[ix_min]}")
        print(f"Precio unitario: ${df.loc[ix_min,'Precio CLP']:,} CLP")

    def aplicar_criterio_avgprecio(self):
        precios = self.precios_totales
        df = self.df_paneles

        valor_promedio = sum(precios) / len(precios)

        def buscar_indice_mas_cercano(valor_ref, lista):
            return min(range(len(lista)), key=lambda i: abs(lista[i] - valor_ref))

        ix_avg = buscar_indice_mas_cercano(valor_promedio, precios)

        self.panel_seleccionado_criterio_avgprecio = {
            "Potencia_Wp": df.loc[ix_avg, 'Potencia nominal (W)'],
            "Cantidad": self.num_paneles[ix_avg],
            "Precio_unitario": df.loc[ix_avg, 'Precio CLP'],
            "Precio_total": precios[ix_avg],
            "Vmp": df.loc[ix_avg, 'Vmp (V)'],
            "Imp": df.loc[ix_avg, 'Imp (A)'],
        }

        print("\n⚖️  Caso Precio Promedio")
        print(f"Valor promedio de inversión: ${valor_promedio:,.0f} CLP")
        print(f"Potencia PV seleccionada: {df.loc[ix_avg,'Potencia nominal (W)']} [Wp]")
        print(f"Cantidad de paneles: {self.num_paneles[ix_avg]}")
        print(f"Precio unitario: ${df.loc[ix_avg,'Precio CLP']:,.0f} CLP")
        print(f"Precio total: ${precios[ix_avg]:,} CLP")

    def ejecutar_seleccion(self):
        self.presentar_paneles()
        self.numero_paneles()
        self.aplicar_criterio_minprecio()
        self.aplicar_criterio_avgprecio()
        return {
            "Criterio_Avg_Precio": self.panel_seleccionado_criterio_avgprecio,
            "Criterio_Min_Precio": self.panel_seleccionado_minprecio
        }
      
class SeleccionMPPT:
    def __init__(self, df_paneles, df_mppts, dimensionamiento_final, panel_minprecio=None, panel_avgprecio=None):
        self.df_paneles = df_paneles
        self.df_mppts = df_mppts
        self.dimensionamiento_final = dimensionamiento_final
        self.panel_minprecio = panel_minprecio
        self.panel_avgprecio = panel_avgprecio
        self.relacion_mppt_panel_minprecio = None
        self.relacion_mppt_panel_avgprecio = None
        self.mppt_seleccionado_minprecio = None
        self.mppt_seleccionado_avgprecio = None
        self.mppt_cantidad_minprecio = None
        self.mppt_cantidad_avgprecio = None
        self.mppt_valor_minprecio = None
        self.mppt_valor_avgprecio = None
        self.mppt_minprecio_indice = None
        self.mppt_avgprecio_indice = None
        self.resumen_mppt = None
        self.resumen_mppt_paneles = None

    def ejecutar(self):
        print("\n🔍 Iniciando selección de controladores MPPT...")
        return self.ejecutar_seleccion()

    def presentar_mppts(self):
        print("📋 Controladores MPPT disponibles en base de datos:\n")
        print(self.df_mppts.head(), "\n")

    ## NOT USED METHOD
    def paneles_serie(self):
        print("\n🔎 Calculando configuración de paneles en serie por MPPT...")

        if self.panel_minprecio is None and self.panel_avgprecio is None:
            print("⚠️ No se han definido paneles seleccionados para realizar el cálculo.")
            return

        # Usaremos ambos paneles seleccionados si están disponibles
        datos_pv = []
        if self.panel_minprecio is not None:
            datos_pv.append(("Criterio MinPrecio", self.panel_minprecio))
        if self.panel_avgprecio is not None:
            datos_pv.append(("Criterio AvgPrecio", self.panel_avgprecio))

        voltajes_dc_link = self.df_mppts["Voltaje DC-link(V)"].tolist()
        len_mppt = len(voltajes_dc_link)

        for nombre_criterio, panel in datos_pv:
            num_paneles = panel["Cantidad"]
            voltaje_panel = panel["Vmp"]

            print(f"\n🔹 {nombre_criterio}")
            print("# Paneles: {} [-] | Vmp: {:.2f} [V]".format(num_paneles, voltaje_panel))

            print("{:<16} | {:<19} | {:<11}".format("DC-Link MPPT [V]", "#Paneles/MPPT [-]", "#MPPTs [-]"))
            print("-" * 55)
            for i in range(len_mppt):
                v_dc_link = voltajes_dc_link[i]
                paneles_por_mppt = int(v_dc_link // voltaje_panel)
                num_mppts_necesarios = int(num_paneles // paneles_por_mppt) + (num_paneles % paneles_por_mppt > 0)

                print("{:16.1f} | {:19d} | {:11d}".format(
                    v_dc_link,
                    paneles_por_mppt,
                    num_mppts_necesarios
                ))

    def relacion_panel_mppt(self):
        print("\n📊 Relación MPPT / Paneles")

        MPPT_DCLink = self.df_mppts['Voltaje DC-link(V)'].tolist()
        DatosPV = pd.DataFrame([
            self.panel_minprecio,
            self.panel_avgprecio
        ])

        lenMPPT = len(MPPT_DCLink)

        # Inicializar listas
        String1 = [0] * lenMPPT
        String2 = [0] * lenMPPT
        MPPTC1 = [0] * lenMPPT
        MPPTC2 = [0] * lenMPPT
        MPPT_ValorC1 = [0] * lenMPPT
        MPPT_ValorC2 = [0] * lenMPPT

        # === Mostrar primero criterio 1 ===
        print("\n🔹 Criterio 1: Panel Menor Precio")
        print("DC-Link MPPT [V] | Paneles/MPPT [-] | #MPPT [-] | Precio Total [CLP]")
        print("---------------------------------------------------------------")
        for x in range(lenMPPT):
            String1[x] = int(MPPT_DCLink[x] / DatosPV.loc[0, 'Vmp'])
            MPPTC1[x] = int(DatosPV.loc[0, 'Cantidad'] / String1[x]) + (DatosPV.loc[0, 'Cantidad'] % String1[x] > 0)
            MPPT_ValorC1[x] = MPPTC1[x] * self.df_mppts.loc[x, 'Precio CLP']
            print("{:<18} | {:<17} | {:<9} | {:,}".format(MPPT_DCLink[x], String1[x], MPPTC1[x], MPPT_ValorC1[x]))

        # === Mostrar luego criterio 2 ===
        print("\n🔸 Criterio 2: Panel Precio Promedio")
        print("DC-Link MPPT [V] | Paneles/MPPT [-] | #MPPT [-] | Precio Total [CLP]")
        print("---------------------------------------------------------------")
        for x in range(lenMPPT):
            String2[x] = int(MPPT_DCLink[x] / DatosPV.loc[1, 'Vmp'])
            MPPTC2[x] = int(DatosPV.loc[1, 'Cantidad'] / String2[x]) + (DatosPV.loc[1, 'Cantidad'] % String2[x] > 0)
            MPPT_ValorC2[x] = MPPTC2[x] * self.df_mppts.loc[x, 'Precio CLP']
            print("{:<18} | {:<17} | {:<9} | {:,}".format(MPPT_DCLink[x], String2[x], MPPTC2[x], MPPT_ValorC2[x]))

        # Guardar como instancias
        self.relacion_mppt_panel_minprecio = String1
        self.relacion_mppt_panel_avgprecio = String2
        self.mppt_cantidad_minprecio = MPPTC1
        self.mppt_cantidad_avgprecio = MPPTC2
        self.mppt_valor_minprecio = MPPT_ValorC1
        self.mppt_valor_avgprecio = MPPT_ValorC2

    def seleccionar(self, potencia_necesaria):
        df_mppts = self.df_mppts

        mppt_valido = df_mppts[df_mppts['Potencia (W)'] >= potencia_necesaria]

        if mppt_valido.empty:
            print("❌ No se encontró un MPPT adecuado para la potencia requerida.")
            return None

        mppt_seleccionado = mppt_valido.iloc[0]

        return {
            "Modelo": mppt_seleccionado['Modelo'],
            "Potencia_W": mppt_seleccionado['Potencia (W)'],
            "Precio_CLP": mppt_seleccionado['Precio CLP']
        }

    def seleccion_mppt_minprecio(self):
        print("\n💰 Selección de MPPT según menor precio total...")

        # Acceso a las listas de valores previamente calculadas
        MPPT_ValorC1 = self.mppt_valor_minprecio
        MPPT_ValorC2 = self.mppt_valor_avgprecio
        MPPTC1 = self.mppt_cantidad_minprecio
        MPPTC2 = self.mppt_cantidad_avgprecio
        Eq_MPPT = self.df_mppts

        # Cálculo del mínimo entre ambos criterios
        min1 = min(MPPT_ValorC1)
        min2 = min(MPPT_ValorC2)

        # Comparación para determinar cuál es más económico
        if (min1 - min2) > 0:
            minMPPT = min2
            ix_minPrecio = MPPT_ValorC2.index(minMPPT)
            Cant_MPPT = MPPTC2
            MPPT_Valor = MPPT_ValorC2
            criterio = "Criterio 2 (Panel Precio Promedio)"
        else:
            minMPPT = min1
            ix_minPrecio = MPPT_ValorC1.index(minMPPT)
            Cant_MPPT = MPPTC1
            MPPT_Valor = MPPT_ValorC1
            criterio = "Criterio 1 (Panel Menor Precio)"

        # Reporte en consola
        print("------------------------------------------------------------")
        print(f"📉 {criterio}")
        print(f"El menor precio total de inversión en MPPTs es: ${minMPPT:,} CLP")
        print(
            "El voltaje de DC-Link seleccionado es de: {:>4} [V], "
            "con un precio unitario de: ${:,} CLP".format(
                int(Eq_MPPT.loc[ix_minPrecio, 'Voltaje DC-link(V)']),
                int(Eq_MPPT.loc[ix_minPrecio, 'Precio CLP'])
            )
        )
        print(
            f"Total de MPPT a instalar: {Cant_MPPT[ix_minPrecio]} [-] "
            f"con monto total de inversión: ${minMPPT:,} CLP"
        )
        print("------------------------------------------------------------")

        # Guardar resultados en atributos de instancia
        self.mppt_valor_minprecio = MPPT_Valor
        self.mppt_minprecio_indice = ix_minPrecio
        self.mppt_minprecio_seleccionado = Eq_MPPT.loc[ix_minPrecio]

    def seleccion_mppt_avgprecio(self):
        print("\n⚖️  Selección de MPPT según precio promedio...")

        # Obtener listas de datos desde las instancias
        MPPT_ValorC1 = self.mppt_valor_minprecio
        MPPT_ValorC2 = self.mppt_valor_avgprecio
        MPPTC1 = self.mppt_cantidad_minprecio
        MPPTC2 = self.mppt_cantidad_avgprecio
        Eq_MPPT = self.df_mppts

        # Combinar todos los valores e índices asociados
        MPPT_Valor = MPPT_ValorC1 + MPPT_ValorC2
        Cant_MPPT = MPPTC1 + MPPTC2

        # Calcular valor promedio
        lenK = len(MPPT_Valor)
        MPPT_Valor_av = sum(MPPT_Valor) / lenK

        # Buscar índice más cercano al promedio
        def buscar_indice_mas_cercano(valor_ref, lista):
            return min(range(len(lista)), key=lambda i: abs(lista[i] - valor_ref))

        ix_av = buscar_indice_mas_cercano(MPPT_Valor_av, MPPT_Valor)

        # Mostrar resultado
        print("------------------------------------------------------------")
        print("🧮 Caso Precio Promedio")
        print("El valor promedio de inversión de MPPTs es: ${:,.2f} CLP".format(MPPT_Valor_av))
        print(
            "El voltaje DC-Link seleccionado es de {:3d} [V], "
            "con un precio unitario de: ${:,} CLP".format(
                int(Eq_MPPT.loc[ix_av, 'Voltaje DC-link(V)']),
                int(Eq_MPPT.loc[ix_av, 'Precio CLP'])
            )
        )
        print(
            f"Total de MPPTs a instalar: {Cant_MPPT[ix_av]} [-] "
            f"con monto total de inversión: ${MPPT_Valor[ix_av]:,} CLP"
        )
        print("------------------------------------------------------------")

        # Guardar en atributos de instancia
        self.mppt_avgprecio_valor = MPPT_Valor[ix_av]
        self.mppt_avgprecio_indice = ix_av
        self.mppt_avgprecio_seleccionado = Eq_MPPT.loc[ix_av]

    def generar_resumen_mppt(self):
        """
        Genera un resumen de la selección de MPPTs según los criterios definidos,
        actualiza la cantidad de paneles en DatosPV, y almacena los resultados en self.resumen_mppt.
        """
        print("\n📝 Generando resumen de selección MPPT y paneles")

        ix_min = self.mppt_minprecio_indice
        ix_avg = self.mppt_avgprecio_indice
        
        # Crear el DataFrame de resumen
        datos_mppt = {
            'Clave': ["Menor Precio", "Precio Promedio"],
            'Marca': [
                self.df_mppts.loc[ix_min, 'Marca'],
                self.df_mppts.loc[ix_avg, 'Marca']
            ],
            'Modelo': [
                self.df_mppts.loc[ix_min, 'Modelo'],
                self.df_mppts.loc[ix_avg, 'Modelo']
            ],
            'Voltaje Bat': [
                self.df_mppts.loc[ix_min, 'Voltaje Bateria (V)'],
                self.df_mppts.loc[ix_avg, 'Voltaje Bateria (V)']
            ],
            'DC-Link': [
                self.df_mppts.loc[ix_min, 'Voltaje DC-link(V)'],
                self.df_mppts.loc[ix_avg, 'Voltaje DC-link(V)']
            ],
            'Potencia': [
                self.df_mppts.loc[ix_min, 'Potencia PV (kW)'],
                self.df_mppts.loc[ix_avg, 'Potencia PV (kW)']
            ],
            'Precio': [
                self.df_mppts.loc[ix_min, 'Precio CLP'],
                self.df_mppts.loc[ix_avg, 'Precio CLP']
            ],
            '# MPPT': [
                self.mppt_cantidad_minprecio[ix_min],
                self.mppt_cantidad_avgprecio[ix_avg]
            ]
        }

        self.resumen_mppt = pd.DataFrame(datos_mppt)

        # Actualización de DatosPV con la cantidad real de paneles a instalar según strings en serie
        self.panel_minprecio['Cantidad'] = self.resumen_mppt.loc[0,"# MPPT"] * self.relacion_mppt_panel_minprecio[ix_min]
        self.panel_avgprecio['Cantidad'] = self.resumen_mppt.loc[1,"# MPPT"] * self.relacion_mppt_panel_avgprecio[ix_avg]

        # -------- Resumen Paneles --------
        resumen_paneles = []

        for clave, panel in zip(['Menor Precio', 'Precio Promedio'], [self.panel_minprecio, self.panel_avgprecio]):
            potencia_wp = panel['Potencia_Wp']
            cantidad = panel['Cantidad']
            precio_unitario = panel['Precio_unitario']
            precio_total = cantidad * precio_unitario
            vmp = panel['Vmp']
            imp = panel['Imp']

            resumen_paneles.append({
                'Clave': clave,
                'Potencia_Wp': potencia_wp,
                'Cantidad': cantidad,
                'Precio_unitario': precio_unitario,
                'Precio_total': precio_total,
                'Vmp': vmp,
                'Imp': imp
            })

        self.resumen_mppt_paneles = pd.DataFrame(resumen_paneles)

        # Reportar
        print("📄 DatosMPPT:")
        print(self.resumen_mppt)
        print()
        print("📄 Resumen de Paneles asociados a selección MPPT:")
        print(self.resumen_mppt_paneles)

    def ejecutar_seleccion(self):
        self.presentar_mppts()
        # self.paneles_serie()
        self.relacion_panel_mppt()
        # # Selección en base a ambos criterios
        # Precio mínimo
        self.seleccion_mppt_minprecio()
        # Precio promedio
        self.seleccion_mppt_avgprecio()
        # Resumen final
        self.generar_resumen_mppt()
        return {
            "MPPTs": self.resumen_mppt,
            "Paneles_with_MPPT": self.resumen_mppt_paneles
            }

class SeleccionInversor:
    def __init__(self, df_inversores, dimensionamiento_final, seleccion_mppt):
        self.eq_inversores = df_inversores
        self.seleccion_mppt = seleccion_mppt
        self.dimensionamiento_final = dimensionamiento_final
        self.resultado_inversor = None

    def ejecutar(self):
        print("\n🔍 Iniciando selección de inversores...")
        return self.ejecutar_seleccion()

    def presentar_inversores(self):
        print("📋 Inversores disponibles en base de datos:\n")
        print(self.eq_inversores.head(), "\n")

    def seleccionar(self):
        """
        Selecciona el inversor con el menor precio que cumpla los criterios de potencia mínima
        y voltaje de batería, basándose en Eq_Inversores y DatosMPPT.
        """
        Eq_Inversores = self.eq_inversores
        Dim_P_Inv = self.dimensionamiento_final["Potencia_Inversor"]

        print("Potencia Mínima del Inversor {:.2f} [kW]".format(Dim_P_Inv))

        len_inv = len(Eq_Inversores)
        Inv_EN = [0] * len_inv
        Precio_Total = [0] * len_inv
        count = 0

        # --- Filtro por potencia y voltaje de batería ---
        for x in range(len_inv):
            if (
                (Eq_Inversores.loc[x, 'Potencia nominal (W)'] > Dim_P_Inv * 1e3)
                and (Eq_Inversores.loc[x, 'Voltaje de carga (V)'] == self.seleccion_mppt.loc[0, 'Voltaje Bat'])
            ):
                Inv_EN[x] = Eq_Inversores.loc[x, 'Precio CLP']
                count += 1
            else:
                Inv_EN[x] = 0

        # --- Lista filtrada de precios válidos ---
        Inv_Precio = [0] * count
        k = 0
        for precio in Inv_EN:
            if precio > 0:
                Inv_Precio[k] = precio
                k += 1

        # --- Selección de menor precio ---
        minPrecio_inv = min(Inv_Precio)
        ix_minPrecio = Inv_EN.index(minPrecio_inv)

        print("El menor Precio de Inversión del Inversor es de: ${:,.0f} CLP".format(minPrecio_inv))
        print(
            "La potencia seleccionada es de: {:,.0f} [W], con un precio por unidad de: ${:,.0f} CLP".format(
                Eq_Inversores.loc[ix_minPrecio, 'Potencia nominal (W)'],
                Eq_Inversores.loc[ix_minPrecio, 'Precio CLP']
            )
        )

        # --- Guardar resultados ---
        Datos_Inv = {
            'Clave': ["Menor Precio"],
            'Marca': [Eq_Inversores.loc[ix_minPrecio, 'Marca']],
            'Modelo': [Eq_Inversores.loc[ix_minPrecio, 'Modelo']],
            'Potencia': [Eq_Inversores.loc[ix_minPrecio, 'Potencia nominal (W)']],
            'Voltaje Bat': [Eq_Inversores.loc[ix_minPrecio, 'Voltaje de carga (V)']],
            'Precio': [Eq_Inversores.loc[ix_minPrecio, 'Precio CLP']]
        }

        self.resultado_inversor = pd.DataFrame(Datos_Inv)
        self.inversor_indice_minprecio = ix_minPrecio
        self.inversor_precio_minimo = minPrecio_inv

        print()
        print("📄 Datos Inversor seleccionado:")
        print(self.resultado_inversor)

    def ejecutar_seleccion(self):
        self.presentar_inversores()
        self.seleccionar()

        return {
            "Inversor": self.resultado_inversor
        }
    
class SeleccionBateria:
    def __init__(self, df_baterias, dimensionamiento_final):
        self.df_baterias = df_baterias
        self.dimensionamiento_final = dimensionamiento_final
        self.bateria_seleccionado_criterio_avgprecio = None
        self.bateria_seleccionado_minprecio = None
        self.capacidad_bateria_kwh = None
        self.numero_baterias_necesarias = []
        self.valores_baterias_totales = []
        self.indice_minprecio = None
        self.indice_avgprecio = None
        

    def ejecutar(self):
        print("\n🔍 Iniciando dimensionamiento de baterías...")
        return self.ejecutar_seleccion()
    
    def presentar_baterias(self):
        print("📋 Baterías disponibles en base de datos:\n")
        print(self.df_baterias.head(), "\n")

    def numero_baterias(self):
        """
        Calcula el número de baterías requeridas por cada alternativa disponible,
        así como el valor total asociado, según la autonomía deseada.

        Guarda los resultados en:
            - self.numero_baterias_necesarias
            - self.valores_baterias_totales
        """
        print("\n🔋 Calculando número de baterías necesarias...")
        print("-------------------------------------------------")
        print("Autonomia de la bateria requerida: {:.2f} kWh".format(self.dimensionamiento_final["Autonomia_Promedio"]))

        eq_baterias = self.df_baterias
        bat_autonomia_kwh = self.dimensionamiento_final["Autonomia_Promedio"]  # kWh
        voltaje_sistema = 48  # V

        len_bat = len(eq_baterias)
        numBat = [0] * len_bat
        valorBat = [0] * len_bat

        print("Capacidad [Ah] | # Baterias [-] | Precio Total [CLP]")
        print("-" * 50)

        for i in range(len_bat):
            capacidad_ah = eq_baterias.loc[i, 'Capacidad (Ah)']
            precio_unitario = eq_baterias.loc[i, 'Precio CLP']

            # Energía deseada (en Wh) dividido por (V * capacidad)
            num_bat = int((bat_autonomia_kwh * 1000 / voltaje_sistema) / capacidad_ah)
            if ((bat_autonomia_kwh * 1000 / voltaje_sistema) % capacidad_ah) > 0:
                num_bat += 1

            numBat[i] = num_bat
            valorBat[i] = num_bat * precio_unitario

            print(f"{capacidad_ah:>14} | {num_bat:>14} | ${valorBat[i]:>14,}")

        # Guardar en la clase para próximos métodos
        self.numero_baterias_necesarias = numBat
        self.valores_baterias_totales = valorBat

    def aplicar_criterio_minprecio(self):
        print("Aplicando criterio de mínimo precio...")
        # min_precio_idx = self.valores_baterias_totales.index(min(self.valores_baterias_totales))
        # self.bateria_seleccionado_minprecio = self.df_baterias.loc[min_precio_idx]
        """
        Aplica el criterio de menor precio total de inversión.
        Guarda la batería seleccionada y reporta su información.
        """
        if not self.valores_baterias_totales or not self.numero_baterias_necesarias:
            print("⚠️ No se han calculado las cantidades ni los valores de baterías. Ejecuta numero_baterias() antes.")
            return

        print("\n📊 Caso: Menor Precio")

        min_precio_bat = min(self.valores_baterias_totales)
        ix_min_precio = self.valores_baterias_totales.index(min_precio_bat)
        self.indice_minprecio = ix_min_precio

        # Guardar la batería seleccionada como Series
        self.bateria_seleccionado_minprecio = self.df_baterias.loc[ix_min_precio].copy()
        self.bateria_seleccionado_minprecio["Cantidad"] = self.numero_baterias_necesarias[ix_min_precio]
        self.bateria_seleccionado_minprecio["Precio Total"] = min_precio_bat

        # Reporte
        capacidad = self.df_baterias.loc[ix_min_precio, 'Capacidad (Ah)']
        precio_unitario = self.df_baterias.loc[ix_min_precio, 'Precio CLP']
        cantidad = self.numero_baterias_necesarias[ix_min_precio]

        print(f"🔹 El menor Precio de Inversión de Baterías es de: ${min_precio_bat:,.0f} CLP")
        print(f"🔹 Capacidad seleccionada: {int(capacidad)} [Ah]")
        print(f"🔹 Precio por unidad: ${int(precio_unitario):,} CLP")
        print(f"🔹 Total de baterías a instalar: {cantidad} [-]")
        print(f"🔹 Monto de inversión total: ${min_precio_bat:,} CLP")

    def aplicar_criterio_avgprecio(self):
        """
        Aplica el criterio de precio promedio: selecciona la batería cuya inversión total
        sea más cercana al valor promedio entre todas las opciones.
        """
        if not self.valores_baterias_totales or not self.numero_baterias_necesarias:
            print("⚠️ No se han calculado las cantidades ni los valores de baterías. Ejecuta numero_baterias() antes.")
            return

        print("\n📊 Caso: Precio Promedio")
        #Calcular promedio y encontrar el índice más cercano
        promedio_precio = sum(self.valores_baterias_totales) / len(self.valores_baterias_totales)
        ix_avg_precio = min(range(len(self.valores_baterias_totales)),
                            key=lambda i: abs(self.valores_baterias_totales[i] - promedio_precio))
        self.indice_avgprecio = ix_avg_precio

        precio_total = self.valores_baterias_totales[ix_avg_precio]
        cantidad = self.numero_baterias_necesarias[ix_avg_precio]

        # Guardar la batería seleccionada como Series
        self.bateria_seleccionado_criterio_avgprecio = self.df_baterias.loc[ix_avg_precio].copy()
        self.bateria_seleccionado_criterio_avgprecio["Cantidad"] = cantidad
        self.bateria_seleccionado_criterio_avgprecio["Precio Total"] = precio_total

        # Reporte
        capacidad = self.df_baterias.loc[ix_avg_precio, 'Capacidad (Ah)']
        precio_unitario = self.df_baterias.loc[ix_avg_precio, 'Precio CLP']

        print(f"🔸 El precio promedio estimado fue: ${promedio_precio:,.0f} CLP")
        print(f"🔸 Batería más cercana al promedio seleccionada:")
        print(f"    - Capacidad: {int(capacidad)} [Ah]")
        print(f"    - Precio unitario: ${int(precio_unitario):,} CLP")
        print(f"    - Cantidad: {cantidad} [-]")
        print(f"    - Precio total: ${precio_total:,} CLP")

    def generar_resumen_baterias(self):
        """
        Genera y muestra un DataFrame resumen con la selección de baterías para ambos criterios:
        Menor Precio y Precio Promedio.
        """
        print("\n📊 Generando resumen de selección de baterías...")

        ix_min = self.indice_minprecio
        ix_avg = self.indice_avgprecio

        datos_resumen = {
            'Criterio': ['Menor Precio', 'Precio Promedio'],
            'Marca': [
                self.df_baterias.loc[ix_min, 'Marca'],
                self.df_baterias.loc[ix_avg, 'Marca']
            ],
            'Modelo': [
                self.df_baterias.loc[ix_min, 'Modelo'],
                self.df_baterias.loc[ix_avg, 'Modelo']
            ],
            'Capacidad [Ah]': [
                self.df_baterias.loc[ix_min, 'Capacidad (Ah)'],
                self.df_baterias.loc[ix_avg, 'Capacidad (Ah)']
            ],
            'Precio Unitario [CLP]': [
                self.df_baterias.loc[ix_min, 'Precio CLP'],
                self.df_baterias.loc[ix_avg, 'Precio CLP']
            ],
            '# Baterías': [
                self.numero_baterias_necesarias[ix_min],
                self.numero_baterias_necesarias[ix_avg]
            ],
            'Precio Total [CLP]': [
                self.valores_baterias_totales[ix_min],
                self.valores_baterias_totales[ix_avg]
            ]
        }

        self.resumen_baterias = pd.DataFrame(datos_resumen)
        print(self.resumen_baterias)

    def ejecutar_seleccion(self):
        self.presentar_baterias()
        self.numero_baterias()
        self.aplicar_criterio_minprecio()
        self.aplicar_criterio_avgprecio()
        self.generar_resumen_baterias()
        return {
            "Bateria_Avg_Precio": self.bateria_seleccionado_criterio_avgprecio,
            "Bateria_Min_Precio": self.bateria_seleccionado_minprecio
        }

        # return {
        #     "Inversor": self.resultado_inversor
        # }