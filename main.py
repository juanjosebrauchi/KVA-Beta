import os
import time
from stage.process import Preprocess
from stage.clients import Cliente
from stage.sizing_backup import Dimensionamiento
# from stage.optimization import Optimizador


os.system("cls")
if __name__ == "__main__":
    # Crea el objeto principal con los datos
    try:
        inicio = time.time()
        ruta_archivo = r"data/Encuesta_10clientes.xlsx"
        path_perfil_base = r"data/Perfil_Base.xlsx"
        path_perfil_extra = r"data/Perfil_Extra.xlsx"
        path_BBDD_clientes = r"data/BBDD_Clientes.csv"
        path_consumo_zona = r"data/PConsumoZone.xlsx"
        path_pgen_clientes = r"data/BBDD_Gen/"
        path_equipos = r"data/BBDD_Equipos.xlsx"

        prepro = Preprocess(ruta_archivo)
        prepro.log("🔄 Iniciando ejecución") 
        indice, cliente_data, vector = prepro.ejecutar()
        prepro.log("✅ Datos procesados correctamente")

        # # Etapa 1: carga y selección de cliente
        prepro.log("🔄 Iniciando Cálculos del Cliente")
        cliente = Cliente(indice, cliente_data, path_perfil_base, path_perfil_extra, path_BBDD_clientes, path_consumo_zona, vector_prueba=vector, cliente_actual=prepro.cliente_actual)
        pdem_cliente = cliente.ejecutar()

        # # Etapa 2: cálculo matemático con datos del cliente
        sizing = Dimensionamiento(indice, cliente_data, pdem_cliente, path_pgen_clientes, path_equipos=path_equipos)
        dimension = sizing.ejecutar()
        
        # # Etapa 3: optimización,
        # Optimizador().ejecutar(gestor)

        # Mostrar resultados finales
        print("\n✅ Proceso finalizado.")


        # print("\n📊 Resultados acumulados por etapa:")
        # for etapa, resultado in gestor.resultados.items():
        #     print(f"▶ {etapa}: {resultado}")
        
        elapsed = time.time()-inicio
        print('Tiempo de ejecución: ',elapsed, 'segundos.')

    except Exception as e:
        print("❌ Ocurrió un error durante la ejecución del programa.")
        print(f"⚠️ Error: {e}")