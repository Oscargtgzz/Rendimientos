# main.py
import streamlit as st
import pandas as pd
import datetime
import unicodedata

# --- Configuración de la Página ---
st.set_page_config(
    page_title="Dashboard de Flota",
    page_icon="📊",
    layout="wide"
)

# --- Funciones de Procesamiento de Datos (Wialon) ---
@st.cache_data
def load_and_prepare_data(uploaded_file):
    """
    Carga los datos desde el archivo Excel de Wialon, los prepara y limpia.
    """
    try:
        xls = pd.ExcelFile(uploaded_file)
        df_viajes = pd.read_excel(xls, sheet_name='Viajes')
        df_llenados = pd.read_excel(xls, sheet_name='Llenados de combustible ...')
        df_costos = pd.read_excel(xls, sheet_name='Coste de utilización')

        df_viajes = df_viajes[df_viajes['№'].astype(str).str.contains('\\.')].copy()
        df_llenados = df_llenados[df_llenados['№'].astype(str).str.contains('\\.')].copy()
        df_costos = df_costos[df_costos['№'].astype(str).str.contains('\\.')].copy()

        df_viajes['Comienzo'] = pd.to_datetime(df_viajes['Comienzo'], errors='coerce')
        df_viajes['Kilometraje'] = pd.to_numeric(df_viajes['Kilometraje'], errors='coerce')
        df_viajes['Kilometraje urbano'] = pd.to_numeric(df_viajes['Kilometraje urbano'], errors='coerce')
        df_viajes['Kilometraje suburbano'] = pd.to_numeric(df_viajes['Kilometraje suburbano'], errors='coerce')
        df_llenados['Llenado registrado'] = pd.to_numeric(df_llenados['Llenado registrado'], errors='coerce')
        df_costos['Coste'] = pd.to_numeric(df_costos['Coste'], errors='coerce')
        
        return df_viajes, df_llenados, df_costos
    except Exception as e:
        st.error(f"Error al procesar el archivo Excel de Wialon: {e}")
        st.warning("Asegúrate de que el archivo contiene las pestañas: 'Viajes', 'Llenados de combustible ...' y 'Coste de utilización'.")
        return None, None, None

@st.cache_data
def get_unit_info(mega_gasolineras_file):
    """
    Procesa el archivo de Mega Gasolineras para crear un mapa de
    Unidad -> Conductor, TAG, Departamento, basado en la asignación más reciente.
    """
    try:
        df_mega_campos = pd.read_excel(mega_gasolineras_file, sheet_name='Campos personalizados')
        df_mega_asignaciones = pd.read_excel(mega_gasolineras_file, sheet_name='Asignaciones')

        df_mega_campos.dropna(subset=['Conductor'], inplace=True)
        df_mega_pivot = df_mega_campos.pivot(index='Conductor', columns='Nombre', values='Valor').reset_index()
        df_mega_pivot.columns.name = None
        df_mega_pivot = df_mega_pivot[['Conductor', 'TAG', 'DEPARTAMENTO']]

        df_mega_asignaciones['Comienzo'] = pd.to_datetime(df_mega_asignaciones['Comienzo'], errors='coerce')
        df_mega_asignaciones.rename(columns={'Unidad': 'UNIDAD_ASIGNADA'}, inplace=True)
        df_mega_asignaciones.sort_values('Comienzo', ascending=False, inplace=True)
        df_asignacion_vigente = df_mega_asignaciones.drop_duplicates(subset='UNIDAD_ASIGNADA', keep='first')

        df_info_final = pd.merge(
            df_asignacion_vigente,
            df_mega_pivot,
            on='Conductor',
            how='left'
        )
        # La columna PLACAS se elimina de la salida de esta función
        return df_info_final[['UNIDAD_ASIGNADA', 'Conductor', 'TAG', 'DEPARTAMENTO']]
    except Exception as e:
        st.error(f"Error procesando el archivo de Mega Gasolineras: {e}")
        return None

def calculate_kpis(df_viajes, df_llenados, df_costos):
    """
    Calcula los KPIs finales y asegura que 'Agrupación' se mantenga como columna.
    """
    if df_viajes.empty:
        return pd.DataFrame()

    grouped_viajes = df_viajes.groupby('Agrupación')
    kilometraje_total = grouped_viajes['Kilometraje'].sum()
    km_urbano_total = grouped_viajes['Kilometraje urbano'].sum()
    llenado_total = df_llenados.groupby('Agrupación')['Llenado registrado'].sum()
    costo_total = df_costos.groupby('Agrupación')['Coste'].sum()

    resultado = pd.DataFrame({
        'Kilometraje Total': kilometraje_total,
        'Kilometraje Urbano': km_urbano_total,
        'Combustible Total (L)': llenado_total,
        'Costo Total ($)': costo_total,
    }).fillna(0)

    resultado['Rendimiento (km/L)'] = resultado['Kilometraje Total'] / resultado['Combustible Total (L)']
    resultado['Costo por Km ($/km)'] = resultado['Costo Total ($)'] / resultado['Kilometraje Total']
    resultado['Perfil Urbano (%)'] = (resultado['Kilometraje Urbano'] / resultado['Kilometraje Total']) * 100
    resultado.fillna(0, inplace=True)
    resultado.replace([float('inf'), float('-inf')], 0, inplace=True)

    avg_rendimiento_fleet = resultado[resultado['Rendimiento (km/L)'] > 0]['Rendimiento (km/L)'].mean()
    avg_urbano_fleet = resultado[resultado['Perfil Urbano (%)'] > 0]['Perfil Urbano (%)'].mean()

    if avg_rendimiento_fleet > 0 and avg_urbano_fleet > 0:
        performance_dev = (resultado['Rendimiento (km/L)'] - avg_rendimiento_fleet) / avg_rendimiento_fleet
        urban_dev = (resultado['Perfil Urbano (%)'] - avg_urbano_fleet) / avg_urbano_fleet
        resultado['Índice de Eficiencia Ajustado'] = (performance_dev - urban_dev) * 100
    else:
        resultado['Índice de Eficiencia Ajustado'] = 0

    return resultado.reset_index()

def process_fuel_files(consumo_file, mega_gasolineras_file):
    try:
        df_consumo = pd.read_excel(consumo_file)
        df_mega_campos = pd.read_excel(mega_gasolineras_file, sheet_name='Campos personalizados')
        df_mega_asignaciones = pd.read_excel(mega_gasolineras_file, sheet_name='Asignaciones')
        df_consumo['FECHA'] = pd.to_datetime(df_consumo['FECHA'], errors='coerce')
        df_consumo['TAG_LIMPIO'] = df_consumo['TAG'].astype(str).str.strip().str.replace("'", "")
        df_mega_campos.dropna(subset=['Conductor'], inplace=True)
        df_mega_pivot = df_mega_campos.pivot(index='Conductor', columns='Nombre', values='Valor').reset_index()
        df_mega_pivot.columns.name = None
        df_mega_pivot = df_mega_pivot[['Conductor', 'TAG', 'DEPARTAMENTO']]
        df_mega_pivot['TAG_LIMPIO'] = df_mega_pivot['TAG'].astype(str).str.strip().str.replace("'", "")
        df_mega_asignaciones['Comienzo'] = pd.to_datetime(df_mega_asignaciones['Comienzo'], errors='coerce')
        df_mega_asignaciones.rename(columns={'Unidad': 'UNIDAD_ASIGNADA'}, inplace=True)
        df_mega_asignaciones.sort_values('Comienzo', ascending=False, inplace=True)
        df_asignacion_vigente = df_mega_asignaciones.drop_duplicates(subset='Conductor', keep='first')
        df_consumo_con_conductor = pd.merge(df_consumo, df_mega_pivot, on='TAG_LIMPIO', how='left')
        df_final = pd.merge(df_consumo_con_conductor, df_asignacion_vigente[['UNIDAD_ASIGNADA', 'Conductor']], on='Conductor', how='left')
        df_final['Fecha y Hora Formateada'] = df_final['FECHA'].dt.strftime('%d.%m.%Y %H:%M:%S')
        df_final['Descripcion'] = df_final['TAG_x'].fillna('').astype(str) + ' - ' + df_final['UNIDAD_ASIGNADA'].fillna('').astype(str) + ' - ' + df_final['DEPARTAMENTO'].fillna('').astype(str) + ' - ' + df_final['MODELO'].fillna('').astype(str) + ' - ' + df_final['PRODUCTO'].fillna('').astype(str)
        output_df = df_final[['PRECIO', 'CANTIDAD', 'IMPORTE', 'Fecha y Hora Formateada', 'Descripcion', 'UNIDAD_ASIGNADA']]
        output_df = output_df.rename(columns={'UNIDAD_ASIGNADA': 'UNIDAD'})
        return output_df
    except Exception as e:
        st.error(f"Ocurrió un error inesperado al procesar los archivos: {e}")
        return None

# --- Interfaz de Usuario ---
st.title("📊 Dashboard de Inteligencia de Flota")

tab1, tab2 = st.tabs(["Dashboard Wialon", "Cruce de Combustible"])

with tab1:
    st.header("Análisis de Reporte de Wialon")
    st.markdown("Carga tu reporte de Wialon y el archivo de Mega Gasolineras para un análisis completo.")

    col1, col2 = st.columns(2)
    with col1:
        uploaded_file = st.file_uploader("1. Selecciona un archivo Excel de Wialon", type=["xlsx"], key="wialon_uploader")
    with col2:
        mega_gasolineras_file_tab1 = st.file_uploader("2. Selecciona el archivo de Mega Gasolineras", type=["xlsx"], key="mega_uploader_tab1")

    if uploaded_file is None or mega_gasolineras_file_tab1 is None:
        st.info("Por favor, carga ambos archivos para comenzar el análisis.")
    else:
        df_viajes, df_llenados, df_costos = load_and_prepare_data(uploaded_file)
        df_unit_info = get_unit_info(mega_gasolineras_file_tab1)

        if df_viajes is not None and df_unit_info is not None:
            st.sidebar.header("Filtros del Reporte")
            unidades = sorted(df_viajes['Agrupación'].unique())
            selected_unidades = st.sidebar.multiselect("Seleccionar Unidades", unidades, default=unidades)

            min_date = df_viajes['Comienzo'].min().date()
            max_date = df_viajes['Comienzo'].max().date()
            selected_dates = st.sidebar.date_input(
                "Seleccionar Rango de Fechas",
                value=(min_date, max_date), min_value=min_date, max_value=max_date
            )

            if len(selected_dates) == 2:
                start_date, end_date = selected_dates
                mask_fechas = (df_viajes['Comienzo'].dt.date >= start_date) & (df_viajes['Comienzo'].dt.date <= end_date)
                mask_unidades = df_viajes['Agrupación'].isin(selected_unidades)
                
                viajes_filtrado = df_viajes[mask_fechas & mask_unidades]
                llenados_filtrado = df_llenados[df_llenados['Agrupación'].isin(selected_unidades)]
                costos_filtrado = df_costos[df_costos['Agrupación'].isin(selected_unidades)]

                kpis = calculate_kpis(viajes_filtrado, llenados_filtrado, costos_filtrado)

                st.header("Dashboard General")

                if kpis.empty:
                    st.warning("No hay datos disponibles para las unidades y fechas seleccionadas.")
                else:
                    total_km = kpis['Kilometraje Total'].sum()
                    total_litros = kpis['Combustible Total (L)'].sum()
                    total_costo = kpis['Costo Total ($)'].sum()

                    metric_col1, metric_col2, metric_col3 = st.columns(3)
                    metric_col1.metric("Kilometraje Total Recorrido", f"{total_km:,.2f} km")
                    metric_col2.metric("Combustible Total Consumido", f"{total_litros:,.2f} L")
                    metric_col3.metric("Costo Total de Flota", f"${total_costo:,.2f}")
                    
                    st.markdown("---")
                    st.subheader("Análisis de Rendimiento por Unidad")
                    
                    tabla_enriquecida = pd.merge(
                        kpis,
                        df_unit_info,
                        left_on='Agrupación',
                        right_on='UNIDAD_ASIGNADA',
                        how='left'
                    )

                    info_cols = ['Conductor', 'TAG', 'DEPARTAMENTO']
                    for col in info_cols:
                        if col in tabla_enriquecida.columns:
                            tabla_enriquecida[col] = tabla_enriquecida[col].fillna('N/A')
                    
                    # --- MODIFICACIÓN CLAVE: Renombrar y reordenar ---
                    # 1. Renombrar 'Agrupación' a 'Unidad'
                    tabla_enriquecida.rename(columns={'Agrupación': 'Unidad'}, inplace=True)
                    
                    # 2. Definir el nuevo orden de columnas, sin 'PLACAS'
                    columnas_a_mostrar = [
                        'Unidad', 'Conductor', 'TAG', 'DEPARTAMENTO', 
                        'Kilometraje Total', 'Combustible Total (L)', 'Rendimiento (km/L)',
                        'Costo por Km ($/km)', 'Perfil Urbano (%)', 'Índice de Eficiencia Ajustado'
                    ]
                    
                    # 3. Ordenar por el índice de eficiencia y establecer 'Unidad' como el índice final para la visualización
                    tabla_final = tabla_enriquecida.sort_values(by='Índice de Eficiencia Ajustado', ascending=False)
                    tabla_final = tabla_final.set_index('Unidad')
                    
                    # 4. Asegurarse de que solo se seleccionen las columnas que existen y quitar 'Unidad' de la lista porque ahora es el índice
                    columnas_cuerpo_tabla = [col for col in columnas_a_mostrar if col in tabla_final.columns and col != 'Unidad']
                    
                    st.dataframe(
                        tabla_final[columnas_cuerpo_tabla].style.format({
                            'Kilometraje Total': '{:,.0f} km',
                            'Combustible Total (L)': '{:,.0f} L',
                            'Rendimiento (km/L)': '{:.2f}',
                            'Costo por Km ($/km)': '${:,.2f}',
                            'Perfil Urbano (%)': '{:.1f}%',
                            'Índice de Eficiencia Ajustado': '{:+.1f}'
                        }).background_gradient(
                            cmap='RdYlGn', subset=['Índice de Eficiencia Ajustado']
                        )
                    )

                    with st.expander("💡 ¿Qué es el Índice de Eficiencia Ajustado (IEA)?"):
                        st.info("El IEA es un indicador avanzado...")
                    with st.expander("🔍 Ver Datos Detallados Filtrados"):
                        st.markdown("#### Viajes"); st.dataframe(viajes_filtrado)
                        st.markdown("#### Costos"); st.dataframe(costos_filtrado)
                        st.markdown("#### Llenados de Combustible"); st.dataframe(llenados_filtrado)
                    with st.expander("⚠️ Puntos a Investigar (Recomendaciones Técnicas)"):
                        st.info("**Análisis de Comportamiento de Conductor No Disponible:**...")

with tab2:
    st.header("Cruce de Archivos de Combustible")
    st.markdown("Carga los archivos de consumo y el listado de Mega Gasolineras para generar el reporte combinado.")
    consumo_file_tab2 = st.file_uploader("Selecciona el archivo de Consumo de Gasolina (.xls, .xlsx)", type=["xls", "xlsx"], key="consumo_uploader_tab2")
    mega_gasolineras_file_tab2 = st.file_uploader("Selecciona el archivo de Mega Gasolineras (.xls, .xlsx)", type=["xls", "xlsx"], key="mega_uploader_tab2")

    if consumo_file_tab2 and mega_gasolineras_file_tab2:
        if st.button("Procesar y Generar Reporte"):
            with st.spinner("Procesando archivos... Por favor, espera."):
                result_df = process_fuel_files(consumo_file_tab2, mega_gasolineras_file_tab2)
            
            if result_df is not None:
                if not result_df.empty:
                    st.success("¡Archivos procesados exitosamente!")
                    csv = result_df.to_csv(index=False, encoding='utf-8-sig')
                    st.download_button(
                       label="Descargar Reporte CSV",
                       data=csv,
                       file_name="reporte_combustible_procesado.csv",
                       mime="text/csv",
                    )
                    st.dataframe(result_df)
                else:
                    st.warning("El proceso finalizó, pero no se encontraron datos para mostrar.")
