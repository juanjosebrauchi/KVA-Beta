import pandas as pd

class Preprocess:
    Electrodomesticos_Posibles = [
        'Secadora de Ropa',
        'Calefactor Eléctrico',
        'Bomba de Piscina o arranque de piscina',
        'Máquinas de hacer ejercicio (Trotadora, elíptica, etc)',
        'Horno Eléctrico',
        'Máquina de Café',
        'Lavaplatos',
        'Campana',
        'Congelador o segundo refrigerador',
        'Cocina Eléctrica o de Inducción',
        'Aire acondicionado',
        'Ventilador Techo',
        'Equipo de Música',
        'Cine en casa (Sistema de sonido + Pantalla gigante, proyector o similar)'
    ]

    def __init__(self, ruta_archivo):
        self.ruta_archivo = ruta_archivo
        self.df_clientes = None
        self.cliente_actual = None
        self.vector_electrodomesticos = None
        self.historial = []
        self.vector_prueba = None
        self.tipo_zona = None
        self.indice_cliente = None
        self.resultados = {
            "clients": None,
            "sizing": None,
            "optimization": None
        }

    def log(self, mensaje):
        self.historial.append(mensaje)

    def ejecutar(self):
        try:
            ## """Método principal que ejecuta funciones internas base."""
            ## Cargar datos desde el archivo Excel
            self.cargar_datos()
            self.log("✔️ Datos cargados correctamente.") 
            ## Renombrar columnas y formatear tipo de solución      
            self.renombrar_columnas()
            self.log("✔️ Columnas renombradas.")
            ## Formatear tipo de solución
            self.formatear_tipo_solucion()
            self.log("✔️ Renombrando instalaciones de Tipo de solución.")
            ## Mostrar clientes disponibles y seleccionar uno
            print("\nClientes disponibles:")
            for i, nombre in enumerate(self.df_clientes['Nombre'], start=1):
                print(f"[{i}] {nombre}")
            self.seleccionar_cliente()
            self.log(f"✔️ Cliente seleccionado: {self.cliente_actual['Nombre']}")
            self.obtener_cliente_actual()
            self.generar_vector_electrodomesticos()
            self.log("Vector de electrodomésticos 1%/0 generado correctamente.")
            self.calcular_zona_calefaccion()

            return self.indice_cliente, self.cliente_actual, self.vector_prueba 
        except Exception as e:
            self.log(f"❌ Error durante ejecución: {str(e)}")
            raise

    def cargar_datos(self):
        import pandas as pd
        self.df_clientes = pd.read_excel(self.ruta_archivo)
        self.log("✔️ Datos cargados correctamente.")

    def renombrar_columnas(self):
        self.df_clientes.rename(columns={
            'Nombre:': 'Nombre',
            'Dirección de la instalación o casa para evaluación energética (calle, número y comuna):  ': 'Direccion',
            'Tipo de solución:': 'Tipo de solución',
            'Tamaño de la casa en metros cuadrados:': 'Tamaño casa',
            'Ingrese la cantidad de habitaciones que tiene en su casa (Incluya todos los espacios menos los baños):': 'N° habitaciones',
            'Ingrese la cantidad de baños que tiene en su casa:': 'N° baños',
            '¿Algún miembro de la familia trabaja desde casa regularmente? ': 'Teletrabajo',
            '¿Su casa tiene Calefacción Eléctrica?': 'Calefacción',
            '¿Cuantas habitaciones tienen calefacción? ': 'N° habitaciones con calefaccion',
            '¿Desea incluir en el estudio Calefacción Eléctrica? ': 'Desea calefacción',
            '¿Cuántas habitaciones quiere calefaccionar? (Considerar habitaciones de 15 metros cuadrados)': 'N° habitaciones que quiere calefaccionar',
            'Columna 15': 'Electrodomésticos Extra',
            'Seleccione la región de la instalación o casa para evaluación energética:': 'Zona'
        }, inplace=True)

            # Eliminar la columna 16
        if self.df_clientes.shape[1] > 16:  # Solo si existe
            self.df_clientes.drop(self.df_clientes.columns[16], axis=1, inplace=True)

    def formatear_tipo_solucion(self):
        tipo_solucion_mapeo = {
            'Independiente': 'OffGrid',
            'Conectado': 'OnGrid',
            'Mixto': 'Hibrido'}
        # Verifica si la columna 'Tipo de solución' existe antes de intentar formatearla
        # y aplica el mapeo correspondiente
        if 'Tipo de solución' in self.df_clientes.columns:
            self.df_clientes['Tipo de solución'] = self.df_clientes['Tipo de solución'].astype(str).apply(
                lambda solucion: tipo_solucion_mapeo.get(solucion.strip().split()[0], solucion)
            )
            self.log("Columna 'tipo_de_solucion' formateada correctamente")
        else:
            self.log("⚠️ Columna 'Tipo de solución' no encontrada")

    def seleccionar_cliente(self):
        indice = int(input("\nIngrese el número del cliente: "))
        if self.df_clientes is None:
            raise ValueError("Primero debes cargar los datos antes de seleccionar un cliente.")
        if 0 < indice <= len(self.df_clientes):
            self.cliente_actual = self.df_clientes.iloc[indice - 1].copy()
            self.indice_cliente = indice - 1
        else:
            raise IndexError("Índice fuera de rango")
        
    def obtener_cliente_actual(self):
        # print("\n📋 Datos del cliente seleccionado:")
        # print(self.cliente_actual)
        return self.cliente_actual
    
    def generar_vector_electrodomesticos(self):
        Electrodomesticos_Posibles = [
            'Secadora de Ropa',
            'Calefactor Eléctrico',
            'Bomba de Piscina o arranque de piscina',
            'Máquinas de hacer ejercicio (Trotadora, elíptica, etc)',
            'Horno Eléctrico',
            'Máquina de Café',
            'Lavaplatos',
            'Campana',
            'Congelador o segundo refrigerador',
            'Cocina Eléctrica o de Inducción',
            'Aire acondicionado',
            'Ventilador Techo',
            'Equipo de Música',
            'Cine en casa (Sistema de sonido + Pantalla gigante, proyector o similar)']
        extras = self.cliente_actual.get('Electrodomésticos Extra', "")
        print("ALojamiento:   ",extras)

        if not isinstance(extras, str) or not extras.strip():
            # Si está vacío, crear vector con ceros
            self.vector_prueba = [0] * len(Electrodomesticos_Posibles)
            self.log("Cliente sin electrodomésticos extra: vector de ceros generado.")
            return

        vector = []

        for item in Electrodomesticos_Posibles:
            if item == 'Calefactor Eléctrico':
                if self.cliente_actual.get('Calefacción', '').strip() == 'Si':
                    habitaciones = self.cliente_actual.get('N° habitaciones con calefaccion', 0)
                    vector.append(int(habitaciones) if not pd.isna(habitaciones) else 0)
                else:
                    vector.append(0)
            else:
                vector.append(1 if item in extras else 0)
                # print(vector)

        self.vector_prueba = vector
        print("\nVector de Electrodomésticos: ", self.vector_prueba)

        print("\nEstado de Electrodomésticos:")
        for nombre, estado in zip(Electrodomesticos_Posibles, self.vector_prueba):
            print(f"{nombre}: {'✔️' if estado == 1 else '❌'}")


    def calcular_zona_calefaccion(self):
        # Definir las zonas de calefacción
        # Definir las zonas de calefacción
        Zona_1 = ['Valparaíso', 'Metropolitana', "O'Higgins"]
        Zona_2 = ['Maule', 'Ñuble', 'BioBío']
        Zona_3 = ['La Araucanía', 'Los Ríos', 'Los Lagos']
        Zona_4 = ['Aysén']

        region_cliente = self.cliente_actual.get('Zona', "")

        if region_cliente in Zona_1:
            self.tipo_zona = 'Z1'
        elif region_cliente in Zona_2:
            self.tipo_zona = 'Z2'
        elif region_cliente in Zona_3:
            self.tipo_zona = 'Z3'
        elif region_cliente in Zona_4:
            self.tipo_zona = 'Z4'
        else:
            self.tipo_zona = 'No aplica'

        # print(f"Zona de calefacción calculada: {self.tipo_zona}")
        self.log(f"Zona de calefacción calculada: {self.tipo_zona}")
        self.cliente_actual['Tipo Zona'] = self.tipo_zona


    