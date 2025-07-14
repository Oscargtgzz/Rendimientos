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
    Carga los datos desde el archivo Excel subido, los prepara y limpia.
    Cachear el resultado para mejorar el rendimiento.
    """
    try:
        xls = pd.ExcelFile(uploaded_file)
        
        df_viajes = pd.read_excel(xls, sheet_name='Viajes')
        df_llenados = pd.read_excel(xls, sheet_name='Llenados de combustible ...')
        df_costos = pd.read_excel(xls, sheet_name='Coste de utilización')

        # --- Limpieza y Preparación ---
        df_viajes = df_viajes[df_viajes['№'].astype(str).str.contains('\\.')].copy()
        df_llenados = df_llenados[df_llenados['№'].astype(str).str.contains('\\.')].copy()
        df_costos = df_costos[df_costos['№'].astype(str).str.contains('\\.')].copy()

        # Conversiones de tipos de datos
        df_viajes['Comienzo'] = pd.to_datetime(df_viajes['Comienzo'], errors='coerce')
        df_viajes['Kilometraje'] = pd.to_numeric(df_viajes['Kilometraje'], errors='coerce')
        df_viajes['Kilometraje urbano'] = pd.to_numeric(df_viajes['Kilometraje urbano'], errors='coerce')
        df_viajes['Kilometraje suburbano'] = pd.to_numeric(df_viajes['Kilometraje suburbano'], errors='coerce')
        df_llenados['Llenado registrado'] = pd.to_numeric(df_llenados['Llenado registrado'], errors='coerce')
        df_costos['Coste'] = pd.to_numeric(df_costos['Coste'], errors='coerce')
        
        return df_viajes, df_llenados, df_costos

    except Exception as e:
        st.error(f"Error al procesar el archivo Excel: {e}")
        st.warning("Asegúrate de que el archivo contiene las pestañas: 'Viajes', 'Llenados de combustible ...' y 'Coste de utilización'.")
        return None, None, None

def calculate_kpis(df_viajes, df_llenados, df_costos):
    """Calcula los KPIs finales, incluyendo el nuevo Índice de Eficiencia Ajustado."""
    if df_viajes.empty:
        return pd.DataFrame()

    # Agrupar y sumar los totales
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

    # Calcular KPIs derivados
    resultado['Rendimiento (km/L)'] = resultado['Kilometraje Total'] / resultado['Combustible Total (L)']
    resultado['Costo por Km ($/km)'] = resultado['Costo Total ($)'] / resultado['Kilometraje Total']
    resultado['Perfil Urbano (%)'] = (resultado['Kilometraje Urbano'] / resultado['Kilometraje Total']) * 100
    
    resultado.fillna(0, inplace=True)
    resultado.replace([float('inf'), float('-inf')], 0, inplace=True)

    # --- Cálculo del Índice de Eficiencia Ajustado (IEA) ---
    avg_rendimiento_fleet = resultado[resultado['Rendimiento (km/L)'] > 0]['Rendimiento (km/L)'].mean()
    avg_urbano_fleet = resultado[resultado['Perfil Urbano (%)'] > 0]['Perfil Urbano (%)'].mean()

    if avg_rendimiento_fleet > 0 and avg_urbano_fleet > 0:
        # Calcular la desviación de cada unidad respecto a la media de la flota
        performance_dev = (resultado['Rendimiento (km/L)'] - avg_rendimiento_fleet) / avg_rendimiento_fleet
        urban_dev = (resultado['Perfil Urbano (%)'] - avg_urbano_fleet) / avg_urbano_fleet
        
        # El IEA es la diferencia: un buen rendimiento menos una ruta difícil (muy urbana) da un IEA alto.
        resultado['Índice de Eficiencia Ajustado'] = (performance_dev - urban_dev) * 100
    else:
        resultado['Índice de Eficiencia Ajustado'] = 0

    return resultado

def fix_encoding_issues(text):
    if isinstance(text, str):
        # Specific fixes for common mojibake patterns (UTF-8 misinterpreted as Latin-1)
        text = text.replace('Ã±', 'ñ')
        text = text.replace('Ã¡', 'á')
        text = text.replace('Ã©', 'é')
        text = text.replace('Ã­', 'í')
        text = text.replace('Ã³', 'ó')
        text = text.replace('Ãº', 'ú')
        text = text.replace('Ã‘', 'Ñ')
        text = text.replace('Ã‰', 'É')
        text = text.replace('Ã�', 'Í')
        text = text.replace('Ã“', 'Ó')
        text = text.replace('Ãš', 'Ú')

        # Then apply the more general re-encoding and normalization
        try:
            encoded_text = text.encode('utf-8', errors='replace')
            for enc in ['latin-1', 'cp1252', 'iso-8859-1', 'utf-8']:
                try:
                    return encoded_text.decode(enc)
                except (UnicodeDecodeError, UnicodeEncodeError):
                    continue
            return unicodedata.normalize('NFKC', text)
        except (UnicodeEncodeError, UnicodeDecodeError):
            return unicodedata.normalize('NFKC', text)
    return text

# --- Funciones de Procesamiento de Datos (Cruce de Combustible) ---
def process_fuel_files(consumo_file, satech_file):
    """
    Procesa y cruza los archivos de consumo de gasolina y listado SATECH.
    """
    try:
        # Cargar los archivos
        # Para archivos .xls, permitir que pandas/xlrd intenten la detección automática de encoding
        if consumo_file.name.endswith('.xls'):
            df_consumo = pd.read_excel(consumo_file, sheet_name='Sheet1', engine='xlrd')
        else:
            df_consumo = pd.read_excel(consumo_file, sheet_name='Sheet1')

        df_satech = pd.read_excel(satech_file, sheet_name='Hoja1')

        # Apply encoding fix to all object (string) columns in both dataframes
        for col in df_consumo.select_dtypes(include=['object']).columns:
            df_consumo[col] = df_consumo[col].astype(str).apply(fix_encoding_issues)

        for col in df_satech.select_dtypes(include=['object']).columns:
            df_satech[col] = df_satech[col].astype(str).apply(fix_encoding_issues)

        # Limpiar la columna TAG en ambos dataframes
        # Eliminar el carácter "'" al inicio si existe
        if df_consumo['TAG'].dtype == 'object':
            df_consumo['TAG'] = df_consumo['TAG'].str.strip().str.replace("'", "")
        if df_satech['TAG'].dtype == 'object':
            df_satech['TAG'] = df_satech['TAG'].str.strip().str.replace("'", "")

        # Cruzar los dataframes
        df_merged = pd.merge(df_consumo, df_satech, on='TAG', how='left')

        # Formatear fecha
        df_merged['Fecha y Hora Formateada'] = pd.to_datetime(df_merged['FECHA']).dt.strftime('%d.%m.%Y %H:%M:%S')

        # Crear la columna Descripcion
        df_merged['Descripcion'] = df_merged['TAG'] + ' - ' + df_merged['UNIDAD'] + ' - ' + df_merged['Departamento'] + ' - ' + df_merged['MODELO'].astype(str) + ' - ' + df_merged['PRODUCTO'] + ' - ' + df_merged['Usuario']

        # Seleccionar y renombrar columnas
        output_df = df_merged[[
            'PRECIO',
            'CANTIDAD',
            'IMPORTE',
            'Fecha y Hora Formateada',
            'Descripcion',
            'UNIDAD'
        ]]

        return output_df

    except Exception as e:
        st.error(f"Error al procesar los archivos: {e}")
        return None

# --- Interfaz de Usuario ---
st.title("📊 Dashboard de Inteligencia de Flota")

tab1, tab2 = st.tabs(["Dashboard Wialon", "Cruce de Combustible"])

with tab1:
    st.header("Análisis de Reporte de Wialon")
    st.markdown("Carga tu reporte de Wialon para obtener un análisis automático de rendimiento y costos.")

    uploaded_file = st.file_uploader("Selecciona un archivo Excel de Wialon", type=["xlsx"], key="wialon_uploader")

    if uploaded_file is None:
        st.info("Por favor, carga un archivo para comenzar el análisis.")
    else:
        df_viajes, df_llenados, df_costos = load_and_prepare_data(uploaded_file)

        if df_viajes is not None:
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
                
                # --- Aplicar Filtros ---
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
                    # --- Métricas Principales ---
                    total_km = kpis['Kilometraje Total'].sum()
                    total_litros = kpis['Combustible Total (L)'].sum()
                    total_costo = kpis['Costo Total ($)'].sum()

                    col1, col2, col3 = st.columns(3)
                    col1.metric("Kilometraje Total Recorrido", f"{total_km:,.2f} km")
                    col2.metric("Combustible Total Consumido", f"{total_litros:,.2f} L")
                    col3.metric("Costo Total de Flota", f"${total_costo:,.2f}")
                    
                    st.markdown("---")

                    # --- Nueva Tabla Principal con IEA ---
                    st.subheader("Análisis de Rendimiento por Unidad")
                    
                    tabla_final = kpis[[
                        'Kilometraje Total',
                        'Combustible Total (L)',
                        'Rendimiento (km/L)',
                        'Costo por Km ($/km)',
                        'Perfil Urbano (%)',
                        'Índice de Eficiencia Ajustado'
                    ]].sort_values(by='Índice de Eficiencia Ajustado', ascending=False)

                    st.dataframe(
                        tabla_final.style.format({
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
                        st.info("""
                            El IEA es un indicador avanzado que mide el rendimiento de una unidad en comparación con el promedio de la flota, ajustando por la dificultad de su ruta.

                            - **IEA Alto y Positivo:** La unidad es muy eficiente para el tipo de ruta que opera (mucho mejor que el promedio).
                            - **IEA Cercano a Cero:** La unidad tiene un rendimiento normal para su contexto operativo.
                            - **IEA Negativo:** La unidad tiene un rendimiento por debajo de lo esperado, incluso considerando la dificultad de su ruta. Es un foco de optimización.
                        """)

                    # --- Exploración de Datos Detallados ---
                    with st.expander("🔍 Ver Datos Detallados Filtrados"):
                        st.markdown("#### Viajes")
                        st.dataframe(viajes_filtrado)
                        st.markdown("#### Costos")
                        st.dataframe(costos_filtrado)
                        st.markdown("#### Llenados de Combustible")
                        st.dataframe(llenados_filtrado)
                    
                    # --- Recomendaciones ---
                    with st.expander("⚠️ Puntos a Investigar (Recomendaciones Técnicas)"):
                        st.info("""
                            **Análisis de Comportamiento de Conductor No Disponible:**
                            - **Observación:** Este reporte no parece contener eventos de comportamiento (excesos de velocidad, frenadas bruscas, etc.).
                            - **Recomendación:** Si te interesa medir la seguridad y eficiencia de los conductores, puedes solicitar que se configuren las notificaciones para estos eventos en Wialon y se incluyan en futuros reportes.
                        """)

with tab2:
    st.header("Cruce de Archivos de Combustible")
    st.markdown("Carga los archivos de consumo y el listado de SATECH para generar el reporte combinado.")

    consumo_file = st.file_uploader("Selecciona el archivo de Consumo de Gasolina (.xls, .xlsx)", type=["xls", "xlsx"], key="consumo_uploader")
    satech_file = st.file_uploader("Selecciona el archivo de Listado SATECH (.xls, .xlsx)", type=["xls", "xlsx"], key="satech_uploader")

    if consumo_file and satech_file:
        if st.button("Procesar y Generar Reporte"):
            result_df = process_fuel_files(consumo_file, satech_file)
            
            if result_df is not None:
                st.success("¡Archivos procesados exitosamente!")
                
                # Convertir dataframe a CSV en memoria con BOM para compatibilidad de acentos
                csv = result_df.to_csv(index=False, encoding='utf-8-sig')
                
                st.download_button(
                   label="Descargar Reporte CSV",
                   data=csv,
                   file_name="datos_procesados.csv",
                   mime="text/csv",
                )
                st.dataframe(result_df)
