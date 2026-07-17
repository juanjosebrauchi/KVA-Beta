# KVA-Beta

Guia tecnica para desarrolladores del pipeline definido en main.py.

## 1. Que hace este proyecto

KVA-Beta implementa un flujo de 4 etapas para evaluar soluciones energeticas residenciales:
- Preprocesamiento de encuesta y seleccion de cliente.
- Construccion de perfil de demanda del cliente.
- Dimensionamiento tecnico de equipos.
- Optimizacion operativa + flujo de caja.

El orquestador es GestorProyecto en main.py.

## 2. Flujo tecnico actual

main.py ejecuta estas etapas en secuencia:

1. Preprocess.ejecutar() en stage/process.py
2. Cliente.ejecutar() en stage/clients.py
3. Dimensionamiento.ejecutar() en stage/sizing_backup.py
4. Optimizador.ejecutar() en stage/optimization.py

Nota importante de implementacion:
- main.py importa Dimensionamiento desde stage/sizing_backup.py (no desde stage/sizing.py).

## 3. Estructura relevante del repositorio

- main.py: punto de entrada y orquestacion
- stage/process.py: etapa 1
- stage/clients.py: etapa 2
- stage/sizing_backup.py: etapa 3 actualmente usada
- stage/optimization.py: etapa 4
- utils/helpers.py: utilidades de logging/soporte
- data/: insumos de entrada (encuesta, perfiles, catalogos)
- output/: artefactos exportados
- log_ejecucion.txt: trazas de ejecucion

## 4. Contrato de datos entre etapas

Este es el contrato efectivo que consume/provee cada etapa hoy:

1. Etapa 1 (Preprocess)
- Input: data/Encuesta_10clientes.xlsx
- Output: indice, cliente_data, vector

2. Etapa 2 (Cliente)
- Input: indice, cliente_data, vector + perfiles/CSV auxiliares
- Output: pdem_cliente, Dem_Max

3. Etapa 3 (Dimensionamiento)
- Input: indice, cliente_data, pdem_cliente, Dem_Max + catalogos/perfiles de generacion
- Output: dict sizing (componentes seleccionados + inversiones)

4. Etapa 4 (Optimizador)
- Input: indice, cliente_data, pdem_cliente, sizing
- Output: resultados tecnicos de despacho + flujo de caja + exportaciones

## 5. Setup de desarrollo (local)

### 5.1 Requisitos

- Python 3.10+ recomendado
- Conda o venv
- Solver compatible con Pyomo (GLPK, CBC o HiGHS)

### 5.2 Dependencias Python usadas por el codigo

Dependencias observadas en imports:
- pandas
- numpy
- matplotlib
- pyomo
- numpy-financial
- pytoolconfig
- openpyxl (lectura/escritura Excel con pandas)

### 5.3 Instalacion rapida (pip)

Comando sugerido:

    pip install pandas numpy matplotlib pyomo numpy-financial pytoolconfig openpyxl

Si usas GLPK en Windows, instalar el binario del solver y validar que este en PATH.

## 6. Como ejecutar

Desde la raiz del proyecto:

    python main.py

Comportamiento esperado:
- Se limpia la consola.
- Se listan clientes disponibles y se solicita indice.
- Se ejecutan las 4 etapas.
- Se registran trazas en log_ejecucion.txt.

## 7. Detalle por etapa para desarrollo

### 7.1 Etapa 1 - stage/process.py

Responsabilidad:
- Normalizar encuesta y construir variables base del cliente.

Puntos de extension comunes:
- Renombrado de columnas nuevas de encuesta.
- Reglas de mapeo para Tipo de solucion.
- Logica de vector de electrodomesticos.

### 7.2 Etapa 2 - stage/clients.py

Responsabilidad:
- Convertir atributos del cliente en perfil anual de demanda.

Puntos de extension comunes:
- Reglas de teletrabajo/cargas base.
- Factorizacion mensual por cliente.
- Calculo de calefaccion por zona climatica.

### 7.3 Etapa 3 - stage/sizing_backup.py

Responsabilidad:
- Dimensionamiento de activos y costos de inversion.

Estado de implementacion:
- OffGrid: mas completo (sensibilidad, meses criticos, seleccion de equipos).
- OnGrid/Hibrido: placeholders (pendiente de completar logica).

Puntos de extension comunes:
- Implementar ramales OnGrid y Hibrido.
- Estandarizar estructura de salida sizing para todos los tipos.
- Extraer criterios de seleccion (Min Precio, etc.) a funciones reutilizables.

### 7.4 Etapa 4 - stage/optimization.py

Responsabilidad:
- Resolver despacho anual y calcular evaluacion economica.

Notas de desarrollo:
- Existe DEBUG_MODE con lectura de data/Dim_Debug.xlsx.
- En entorno productivo, conviene usar DEBUG_MODE=False.

Puntos de extension comunes:
- Nuevos costos operativos y restricciones del modelo.
- Nuevos KPIs financieros en flujo de caja.
- Mejoras en exportacion de reportes y graficos.

## 8. Logging y observabilidad

- main.py usa SimpleLogger para registrar hitos y errores.
- Las etapas pueden inyectar el logger para trazabilidad consistente.
- Archivo de log principal: log_ejecucion.txt.

Recomendacion:
- Mantener prefijos por etapa (Preprocess, Cliente, Sizing, Optimizador) para facilitar analisis de fallas.

## 9. Guia de depuracion

Si falla la ejecucion completa:

1. Validar disponibilidad y formato de archivos en data/.
2. Revisar contrato entre etapas (tipos/shape de salidas).
3. Verificar solver de Pyomo instalado y accesible.
4. Revisar log_ejecucion.txt y traceback de consola.
5. Aislar etapa corriendo clases por separado.

Para depurar Optimizador:
- Usar DEBUG_MODE y data/Dim_Debug.xlsx para escenarios controlados.

## 10. Roadmap tecnico sugerido

1. Unificar stage/sizing.py y stage/sizing_backup.py en una sola implementacion.
2. Completar dimensionamiento OnGrid/Hibrido.
3. Crear requirements.txt o pyproject.toml para versionado de dependencias.
4. Agregar pruebas por etapa con datos mock.
5. Definir esquema formal de I/O (por ejemplo, dataclasses de intercambio).
