import os
import time
from stage.process import Preprocess
from stage.clients import Cliente
# from stage.optimization import Optimizador
# from stage.sizing import Dimensionamiento


os.system("cls")
if __name__ == "__main__":
    # Crea el objeto principal con los datos
    try:
        inicio = time.time()
        ruta_archivo = r"Data\Encuesta v2_6clientes.xlsx"
        path_perfil_base = r"Data\Perfil_Base_Test.xlsx"
        path_perfil_extra = r"Data\Perfil_Extra 1_Test.xlsx"
        path_BBDD_clientes = r"Data\BBDD_Clientes.csv"
        path_consumo_zona = r"Data\PConsumoZone.xlsx"
        
        prepro = Preprocess(ruta_archivo)
        prepro.log("🔄 Iniciando ejecución") 
        indice, cliente_data, vector = prepro.ejecutar()
        prepro.log("✅ Datos procesados correctamente")

        prepro.log("🔄 Iniciando Cálculos del Cliente")
        cliente = Cliente(indice, cliente_data, path_perfil_base, path_perfil_extra, path_BBDD_clientes, path_consumo_zona, vector_prueba=vector, cliente_actual=prepro.cliente_actual)
        predim = cliente.ejecutar()

        # # Etapa 1: carga y selección de cliente
        # Cliente().ejecutar(gestor)

        # # Etapa 2: cálculo matemático con datos del cliente
        # Dimensionamiento().ejecutar(gestor)

        # # Etapa 3: optimización
        # Optimizador().ejecutar(gestor)

        # Mostrar resultados finales
        print("\n✅ Proceso finalizado.")


        # print("\n📊 Resultados acumulados por etapa:")
        # for etapa, resultado in gestor.resultados.items():
        #     print(f"▶ {etapa}: {resultado}")
        elapsed = time.time()-inicio
        print('Tiempo de ejecución: ',elapsed, 'segundos.')

    except Exception as e:
        print(f"⚠️ Error: {e}")