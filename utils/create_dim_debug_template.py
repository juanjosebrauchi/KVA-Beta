"""
Script para generar el template data/Dim_Debug.xlsx
Ejecutar una sola vez: python create_dim_debug_template.py
"""
import pandas as pd
import numpy as np
import os

OUTPUT_PATH = r"data/Dim_Debug.xlsx"
os.makedirs("data", exist_ok=True)

MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
         "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
HORAS = [f"H{h:02d}" for h in range(24)]  # H00 … H23

# --- Hoja PGen: perfil de generación PV normalizado (kW/kWp) ---
_solar_day = np.array([
    0, 0, 0, 0, 0, 0,
    0.05, 0.15, 0.35, 0.55, 0.75, 0.90,
    1.00, 0.95, 0.85, 0.70, 0.50, 0.30,
    0.10, 0.02, 0, 0, 0, 0
], dtype=float)
pgen_data = np.tile(_solar_day, (12, 1))
df_pgen = pd.DataFrame(pgen_data, index=MESES, columns=HORAS)
df_pgen.index.name = "Mes"

# --- Hoja PDem: perfil de demanda (kW) ---
_demand_day = np.array([
    0.5, 0.4, 0.4, 0.4, 0.4, 0.5,
    0.7, 1.0, 1.2, 1.1, 1.0, 1.0,
    1.3, 1.2, 1.1, 1.0, 1.0, 1.2,
    1.5, 1.8, 2.0, 1.8, 1.5, 0.8
], dtype=float)
pdem_data = np.tile(_demand_day, (12, 1))
df_pdem = pd.DataFrame(pdem_data, index=MESES, columns=HORAS)
df_pdem.index.name = "Mes"

# --- Hoja Dim: parámetros del optimizador ---
# Nota: esta lista incluye TODOS los parámetros incorporados al modo DEBUG.
# Si un parámetro no te interesa, puedes eliminar su fila del Excel.
dim_params = [
    # parametro                         valor     descripcion

    # ---------- Diseño base / sizing ----------
    ("cap_fv",                         10.0,    "Potencia instalada FV (kWp). Override de capacidad_fv"),
    ("cap_bat",                        20.0,    "Capacidad total batería (kWh). Override de baterias_cap"),

    # ---------- Batería / SOC ----------
    ("pot_inversor",                    5.0,    "Alias: expande a p_ch_max y p_dis_max (kW)"),
    ("p_ch_max",                        5.0,    "Potencia máxima de carga batería (kW)"),
    ("p_dis_max",                       5.0,    "Potencia máxima de descarga batería (kW)"),
    ("e_init",                         10.0,    "SOC inicial batería (kWh)"),
    ("e_min",                           4.0,    "SOC mínimo (kWh)"),
    ("e_max",                          20.0,    "SOC máximo (kWh)"),
    ("e_final_min",                    10.0,    "SOC final mínimo del horizonte (kWh)"),
    ("eff_ch",                          0.95,   "Eficiencia de carga (0-1)"),
    ("eff_dis",                         0.95,   "Eficiencia de descarga (0-1)"),
    ("batt_cycle_cost",                 0.0,    "Costo degradación batería (USD/kWh ciclado)"),
    ("cost_battery",                    0.0,    "Alias de batt_cycle_cost"),
    ("bat_cycle_cost",                  0.0,    "Alias de batt_cycle_cost"),
    ("no_simultaneous_charge_discharge", "True", "No cargar/descargar batería simultáneamente"),

    # ---------- Red ----------
    ("ongrid",                         "True", "Conectado a red: True=on-grid | False=off-grid"),
    ("cost_grid",                       0.15,   "Alias escalar compra red (USD/kWh). Venta=60% si no defines cost_grid_sell"),
    ("cost_grid_sell",                  0.05,   "Alias escalar venta red (USD/kWh)"),
    ("p_imp_max",                      100.0,   "Potencia máxima de importación (kW)"),
    ("p_exp_max",                        0.0,   "Potencia máxima de exportación (kW)"),
    ("no_simultaneous_imp_exp",       "True", "No importar/exportar simultáneamente"),

    # ---------- Diesel ----------
    ("pmin_diesel",                     0.0,    "Potencia mínima diesel (kW)"),
    ("pmax_diesel",                     0.0,    "Potencia máxima diesel (kW). 0 = desactivado"),
    ("cost_diesel",                     0.0,    "Costo fijo diesel (si aplica)"),
    ("var_cost_diesel",                 0.2,    "Costo variable diesel (USD/kWh)"),
    ("startup_cost_diesel",             0.0,    "Costo de arranque diesel"),
    ("shutdown_cost_diesel",            0.0,    "Costo de parada diesel"),
    ("ramp_up_diesel",            1000000.0,    "Rampa máxima de subida (kW/h)"),
    ("ramp_down_diesel",          1000000.0,    "Rampa máxima de bajada (kW/h)"),
    ("min_up_time_diesel",              0,      "Tiempo mínimo encendido (h)"),
    ("min_down_time_diesel",            0,      "Tiempo mínimo apagado (h)"),
    ("u_unit_diesel",                   0,      "Estado inicial binario unidad diesel (0/1)"),
    ("p_init_d",                        0.0,    "Potencia inicial diesel (kW)"),

    # ---------- Load shedding ----------
    ("allow_ls",                      "True", "Permitir energía no suministrada"),
    ("ls_penalty",                  10000.0,    "Penalización por kWh no suministrado (USD/kWh)"),

    # ---------- Inversiones (flujo de caja) ----------
    ("inv_fv",                    1240000.0,    "Inversión FV"),
    ("inv_storage",                915000.0,    "Inversión en baterías"),
    ("inv_inv_fv",                     0.0,     "Inversor lado FV"),
    ("inv_inv_storage",          3240000.0,     "Inversor lado storage"),
    ("inv_estructura",             500000.0,    "Estructura"),
    ("inv_materiales",             500000.0,    "Materiales"),
    ("costo_capex",                     0.0,    "CAPEX total (fallback si no hay desglose)"),

    # ---------- Flujo de caja ----------
    ("tecnologia_bateria",          "LITIO",   "Solo DEBUG: AGM | OPZS | LITIO (y alias Li-ion/LFP)"),
    ("horizonte",                       20,      "Horizonte evaluación (años)"),
    ("tasa_descuento",                  0.06,    "Tasa de descuento anual"),
    ("costo_energia",                   0.15,    "Precio energía base (USD/kWh)"),
    ("costo_potencia_suministrada",     0.0,    "Cargo por potencia suministrada"),
    ("costo_potencia_punta",            0.0,    "Cargo por potencia en punta"),
    ("precio_inyeccion",                0.05,    "Precio de venta/inyección (USD/kWh)"),
    ("incremento_precio_anual",         0.05,    "Escalamiento anual de precios"),
    ("caida_eficiencia_fv_anual",       0.007,   "Degradación anual FV"),
    ("incremento_mantencion_anual",     0.05,    "Escalamiento anual OPEX"),
    ("mant_fv_pct",                     0.006,   "Mantenimiento FV+InvFV (% inversión)"),
    ("mant_storage_pct",                0.01,    "Mantenimiento Storage+InvStorage (% inversión)"),
    ("recambio_inversor",               10,      "Año de recambio de inversores"),
]
df_dim = pd.DataFrame(dim_params, columns=["parametro", "valor", "descripcion"])

# --- Escribir Excel ---
with pd.ExcelWriter(OUTPUT_PATH, engine="openpyxl") as writer:
    df_pgen.to_excel(writer, sheet_name="PGen")
    df_pdem.to_excel(writer, sheet_name="PDem")
    df_dim.to_excel(writer, sheet_name="Dim", index=False)

print(f"✅ Template generado en: {OUTPUT_PATH}")
print(f"   Hojas: PGen {df_pgen.shape}, PDem {df_pdem.shape}, Dim {df_dim.shape}")
