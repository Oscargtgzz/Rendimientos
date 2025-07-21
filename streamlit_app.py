# main.py
import streamlit as st
import pandas as pd
import datetime
import google.generativeai as genai

# ════════════════════════════════════════════
#   CONFIGURACIÓN DE LA PÁGINA
# ════════════════════════════════════════════
st.set_page_config(
    page_title="Dashboard de Flota",
    page_icon="📊",
    layout="wide",
)

# ════════════════════════════════════════════
#   INITIAL SESSION STATE
# ════════════════════════════════════════════
if "kpi_data" not in st.session_state:
    st.session_state["kpi_data"] = None


# ════════════════════════════════════════════
#   FUNCIONES DE CARGA Y LIMPIEZA DE WIALON
# ════════════════════════════════════════════
@st.cache_data
def load_and_prepare_data(uploaded_file):
    """Carga los datos de Wialon y devuelve tres DataFrames limpios."""
    try:
        xls = pd.ExcelFile(uploaded_file)

        # --- Viajes --------------------------------------------------------
        df_viajes = pd.read_excel(xls, sheet_name="Viajes")
        df_viajes = df_viajes[df_viajes["№"].astype(str).str.contains(r"\.")].copy()

        df_viajes["Comienzo"] = pd.to_datetime(
            df_viajes["Comienzo"], errors="coerce", dayfirst=True
        )
        df_viajes["Kilometraje"] = pd.to_numeric(
            df_viajes["Kilometraje"], errors="coerce"
        )
        df_viajes["Kilometraje urbano"] = pd.to_numeric(
            df_viajes["Kilometraje urbano"], errors="coerce"
        )
        df_viajes["Kilometraje suburbano"] = pd.to_numeric(
            df_viajes["Kilometraje suburbano"], errors="coerce"
        )

        # --- Llenados de combustible --------------------------------------
        df_llenados = pd.read_excel(xls, sheet_name="Llenados de combustible ...")
        df_llenados = df_llenados[
            df_llenados["№"].astype(str).str.contains(r"\.")
        ].copy()

        llenado_fecha_col = (
            "Tiempo"
            if "Tiempo" in df_llenados.columns
            else "Hora"
            if "Hora" in df_llenados.columns
            else None
        )
        if not llenado_fecha_col:
            raise ValueError(
                "No se encontró la columna de fecha en 'Llenados de combustible ...'."
            )

        df_llenados["Fecha"] = pd.to_datetime(
            df_llenados[llenado_fecha_col], errors="coerce", dayfirst=True
        )
        df_llenados["Llenado registrado"] = pd.to_numeric(
            df_llenados["Llenado registrado"], errors="coerce"
        )

        # --- Coste de utilización -----------------------------------------
        df_costos = pd.read_excel(xls, sheet_name="Coste de utilización")
        df_costos = df_costos[df_costos["№"].astype(str).str.contains(r"\.")].copy()

        costo_fecha_col = (
            "Tiempo"
            if "Tiempo" in df_costos.columns
            else "Hora de registro"
            if "Hora de registro" in df_costos.columns
            else None
        )
        if not costo_fecha_col:
            raise ValueError(
                "No se encontró la columna de fecha en 'Coste de utilización'."
            )

        df_costos["Fecha"] = pd.to_datetime(
            df_costos[costo_fecha_col], errors="coerce", dayfirst=True
        )
        df_costos["Coste"] = pd.to_numeric(df_costos["Coste"], errors="coerce")

        return df_viajes, df_llenados, df_costos

    except Exception as e:
        st.error(f"Error al procesar el archivo Excel de Wialon: {e}")
        st.warning(
            "Asegúrate de que el archivo contiene las pestañas: "
            "'Viajes', 'Llenados de combustible ...' y 'Coste de utilización'."
        )
        return None, None, None


# ════════════════════════════════════════════
#   INFORMACIÓN DE UNIDADES (Mega Gasolineras)
# ════════════════════════════════════════════
@st.cache_data
def get_unit_info(mega_gasolineras_file):
    """Devuelve un DataFrame con la asignación vigente unidad → conductor/TAG/depto."""
    try:
        df_mega_campos = pd.read_excel(
            mega_gasolineras_file, sheet_name="Campos personalizados"
        )
        df_mega_asignaciones = pd.read_excel(
            mega_gasolineras_file, sheet_name="Asignaciones"
        )

        df_mega_campos.dropna(subset=["Conductor"], inplace=True)
        df_mega_pivot = (
            df_mega_campos.pivot(index="Conductor", columns="Nombre", values="Valor")
            .reset_index()
            .rename_axis(None, axis=1)
        )
        df_mega_pivot = df_mega_pivot[["Conductor", "TAG", "DEPARTAMENTO"]]

        df_mega_asignaciones["Comienzo"] = pd.to_datetime(
            df_mega_asignaciones["Comienzo"], errors="coerce", dayfirst=True
        )
        df_mega_asignaciones.rename(columns={"Unidad": "UNIDAD_ASIGNADA"}, inplace=True)
        df_mega_asignaciones.sort_values("Comienzo", ascending=False, inplace=True)
        df_asignacion_vigente = df_mega_asignaciones.drop_duplicates(
            subset="UNIDAD_ASIGNADA", keep="first"
        )

        df_info_final = pd.merge(
            df_asignacion_vigente,
            df_mega_pivot,
            on="Conductor",
            how="left",
        )
        return df_info_final[
            ["UNIDAD_ASIGNADA", "Conductor", "TAG", "DEPARTAMENTO"]
        ]

    except Exception as e:
        st.error(f"Error procesando el archivo de Mega Gasolineras: {e}")
        return None


# ════════════════════════════════════════════
#   KPI CALCULATOR
# ════════════════════════════════════════════
def calculate_kpis(df_viajes, df_llenados, df_costos):
    """Devuelve un DataFrame de KPIs a nivel unidad."""
    if df_viajes.empty:
        return pd.DataFrame()

    kpi_viajes = (
        df_viajes.groupby("Agrupación")
        .agg(
            **{
                "Kilometraje Total": ("Kilometraje", "sum"),
                "Kilometraje Urbano": ("Kilometraje urbano", "sum"),
            }
        )
        .reset_index()
    )

    llenado_total = (
        df_llenados.groupby("Agrupación")["Llenado registrado"].sum().reset_index()
    )
    costo_total = df_costos.groupby("Agrupación")["Coste"].sum().reset_index()

    resultado = (
        kpi_viajes.merge(llenado_total, on="Agrupación", how="left")
        .merge(costo_total, on="Agrupación", how="left")
        .rename(
            columns={
                "Llenado registrado": "Combustible Total (L)",
                "Coste": "Costo Total ($)",
            }
        )
        .fillna(0)
    )

    resultado["Rendimiento (km/L)"] = (
        resultado["Kilometraje Total"] / resultado["Combustible Total (L)"]
    )
    resultado["Costo por Km ($/km)"] = (
        resultado["Costo Total ($)"] / resultado["Kilometraje Total"]
    )
    resultado["Perfil Urbano (%)"] = (
        resultado["Kilometraje Urbano"] / resultado["Kilometraje Total"] * 100
    )

    avg_rend = resultado.loc[resultado["Rendimiento (km/L)"] > 0, "Rendimiento (km/L)"].mean()
    avg_urb = resultado.loc[resultado["Perfil Urbano (%)"] > 0, "Perfil Urbano (%)"].mean()

    if avg_rend > 0 and avg_urb > 0:
        perf_dev = (resultado["Rendimiento (km/L)"] - avg_rend) / avg_rend
        urb_dev = (resultado["Perfil Urbano (%)"] - avg_urb) / avg_urb
        resultado["Índice de Eficiencia Ajustado"] = (perf_dev - urb_dev) * 100
    else:
        resultado["Índice de Eficiencia Ajustado"] = 0

    resultado.replace([float("inf"), float("-inf")], 0, inplace=True)
    return resultado


# ════════════════════════════════════════════
#   PROCESAMIENTO DE ARCHIVOS DE COMBUSTIBLE
# ════════════════════════════════════════════
def process_fuel_files(consumo_file, mega_gasolineras_file):
    """Cruza consumos individuales con info de conductor/unidad."""
    try:
        df_consumo = pd.read_excel(consumo_file)

        df_mega_campos = pd.read_excel(
            mega_gasolineras_file, sheet_name="Campos personalizados"
        )
        df_mega_asignaciones = pd.read_excel(
            mega_gasolineras_file, sheet_name="Asignaciones"
        )

        df_consumo["FECHA"] = pd.to_datetime(df_consumo["FECHA"], errors="coerce")
        df_consumo["TAG_LIMPIO"] = (
            df_consumo["TAG"].astype(str).str.strip().str.replace("'", "")
        )

        df_mega_campos.dropna(subset=["Conductor"], inplace=True)
        df_mega_pivot = (
            df_mega_campos.pivot(index="Conductor", columns="Nombre", values="Valor")
            .reset_index()
            .rename_axis(None, axis=1)
        )
        df_mega_pivot = df_mega_pivot[["Conductor", "TAG", "DEPARTAMENTO"]]
        df_mega_pivot["TAG_LIMPIO"] = (
            df_mega_pivot["TAG"].astype(str).str.strip().str.replace("'", "")
        )

        df_mega_asignaciones["Comienzo"] = pd.to_datetime(
            df_mega_asignaciones["Comienzo"], errors="coerce", dayfirst=True
        )
        df_mega_asignaciones.rename(columns={"Unidad": "UNIDAD_ASIGNADA"}, inplace=True)
        df_mega_asignaciones.sort_values("Comienzo", ascending=False, inplace=True)
        df_asignacion_vigente = df_mega_asignaciones.drop_duplicates(
            subset="Conductor", keep="first"
        )

        df_consumo_con_conductor = pd.merge(
            df_consumo, df_mega_pivot, on="TAG_LIMPIO", how="left"
        )
        df_final = pd.merge(
            df_consumo_con_conductor,
            df_asignacion_vigente[["UNIDAD_ASIGNADA", "Conductor"]],
            on="Conductor",
            how="left",
        )

        df_final["Fecha y Hora Formateada"] = df_final["FECHA"].dt.strftime(
            "%d.%m.%Y %H:%M:%S"
        )
        df_final["Descripcion"] = (
            df_final["TAG_x"].fillna("").astype(str)
            + " - "
            + df_final["UNIDAD_ASIGNADA"].fillna("").astype(str)
            + " - "
            + df_final["DEPARTAMENTO"].fillna("").astype(str)
            + " - "
            + df_final["MODELO"].fillna("").astype(str)
            + " - "
            + df_final["PRODUCTO"].fillna("").astype(str)
        )

        output_df = df_final[
            ["PRECIO", "CANTIDAD", "IMPORTE", "Fecha y Hora Formateada", "Descripcion", "UNIDAD_ASIGNADA"]
        ].rename(columns={"UNIDAD_ASIGNADA": "UNIDAD"})

        return output_df

    except Exception as e:
        st.error(f"Ocurrió un error inesperado al procesar los archivos: {e}")
        return None


# ════════════════════════════════════════════
#   GEMINI
# ════════════════════════════════════════════
def call_gemini_api(api_key, prompt):
    """Genera contenido con Gemini."""
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        st.error(f"Error al contactar con la API de Gemini: {e}")
        return None


# ════════════════════════════════════════════
#   INTERFAZ DE USUARIO
# ════════════════════════════════════════════
st.title("📊 Dashboard de Inteligencia de Flota")

tab1, tab2, tab3, tab4 = st.tabs(
    ["Dashboard Wialon", "Cruce de Combustible", "Análisis con IA (Gemini)", "Viajes Fin de Semana"]
)

# ────────────────────────────────────────────
#   TAB 1 • DASHBOARD WIALON
# ────────────────────────────────────────────
with tab1:
    st.header("Análisis de Reporte de Wialon")
    st.markdown(
        "Carga tu reporte de Wialon y el archivo de Mega Gasolineras para un análisis completo."
    )

    col1, col2 = st.columns(2)
    with col1:
        uploaded_file = st.file_uploader(
            "1. Selecciona un archivo Excel de Wialon", type=["xlsx"], key="wialon_uploader"
        )
    with col2:
        mega_gasolineras_file_tab1 = st.file_uploader(
            "2. Selecciona el archivo de Mega Gasolineras", type=["xls", "xlsx"], key="mega_uploader_tab1"
        )

    if uploaded_file and mega_gasolineras_file_tab1:
        df_viajes, df_llenados, df_costos = load_and_prepare_data(uploaded_file)
        df_unit_info = get_unit_info(mega_gasolineras_file_tab1)

        if df_viajes is not None and df_unit_info is not None:
            st.sidebar.header("Filtros del Reporte")
            unidades = sorted(df_viajes["Agrupación"].unique())
            selected_unidades = st.sidebar.multiselect("Seleccionar Unidades", unidades, default=unidades)

            min_date, max_date = df_viajes["Comienzo"].min().date(), df_viajes["Comienzo"].max().date()
            if min_date > max_date:
                min_date, max_date = max_date, min_date

            selected_dates = st.sidebar.date_input(
                "Seleccionar Rango de Fechas",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
            )

            if len(selected_dates) == 2:
                start_date, end_date = selected_dates

                mask_viajes = (
                    (df_viajes["Comienzo"].dt.date >= start_date)
                    & (df_viajes["Comienzo"].dt.date <= end_date)
                    & (df_viajes["Agrupación"].isin(selected_unidades))
                )
                mask_llenados = (
                    (df_llenados["Fecha"].dt.date >= start_date)
                    & (df_llenados["Fecha"].dt.date <= end_date)
                    & (df_llenados["Agrupación"].isin(selected_unidades))
                )
                mask_costos = (
                    (df_costos["Fecha"].dt.date >= start_date)
                    & (df_costos["Fecha"].dt.date <= end_date)
                    & (df_costos["Agrupación"].isin(selected_unidades))
                )

                kpis = calculate_kpis(
                    df_viajes[mask_viajes], df_llenados[mask_llenados], df_costos[mask_costos]
                )

                st.header("Dashboard General")
                if not kpis.empty:
                    total_km = kpis["Kilometraje Total"].sum()
                    total_litros = kpis["Combustible Total (L)"].sum()
                    total_costo = kpis["Costo Total ($)"].sum()

                    metric1, metric2, metric3 = st.columns(3)
                    metric1.metric("Kilometraje Total", f"{total_km:,.2f} km")
                    metric2.metric("Combustible Total", f"{total_litros:,.2f} L")
                    metric3.metric("Costo Total", f"${total_costo:,.2f}")

                    st.markdown("---")
                    st.subheader("Análisis de Rendimiento por Unidad")

                    tabla_enriquecida = pd.merge(
                        kpis, df_unit_info, left_on="Agrupación", right_on="UNIDAD_ASIGNADA", how="left"
                    )
                    for col in ["Conductor", "TAG", "DEPARTAMENTO"]:
                        if col in tabla_enriquecida.columns:
                            tabla_enriquecida[col] = tabla_enriquecida[col].fillna("N/A")

                    tabla_enriquecida.rename(columns={"Agrupación": "Unidad"}, inplace=True)

                    # COLUMNA NUEVA ▶️  "Costo Total ($)"
                    columnas_a_mostrar = [
                        "Unidad",
                        "Conductor",
                        "TAG",
                        "DEPARTAMENTO",
                        "Kilometraje Total",
                        "Combustible Total (L)",
                        "Costo Total ($)",          # ✅  añadida
                        "Rendimiento (km/L)",
                        "Costo por Km ($/km)",
                        "Perfil Urbano (%)",
                        "Índice de Eficiencia Ajustado",
                    ]

                    tabla_final = (
                        tabla_enriquecida[columnas_a_mostrar]
                        .sort_values(by="Índice de Eficiencia Ajustado", ascending=False)
                        .set_index("Unidad")
                    )

                    st.session_state["kpi_data"] = tabla_final

                    st.dataframe(
                        tabla_final.style.format(
                            {
                                "Kilometraje Total": "{:,.0f} km",
                                "Combustible Total (L)": "{:,.0f} L",
                                "Costo Total ($)": "${:,.2f}",          # ✅  formateo
                                "Rendimiento (km/L)": "{:.2f}",
                                "Costo por Km ($/km)": "${:,.2f}",
                                "Perfil Urbano (%)": "{:.1f}%",
                                "Índice de Eficiencia Ajustado": "{:+.1f}",
                            }
                        ).background_gradient(
                            cmap="RdYlGn", subset=["Índice de Eficiencia Ajustado"]
                        )
                    )

                    with st.expander("💡 ¿Qué es el Índice de Eficiencia Ajustado (IEA)?"):
                        st.info(
                            "El IEA compara el rendimiento de una unidad con el promedio de la flota, "
                            "ajustado por su perfil de conducción (urbano vs. carretera). "
                            "Un valor positivo indica una eficiencia superior a la media; uno negativo, inferior."
                        )
                else:
                    st.warning("No hay datos para las unidades y fechas seleccionadas.")
                    st.session_state["kpi_data"] = None
    else:
        st.info("Por favor, carga ambos archivos para comenzar el análisis.")


# ────────────────────────────────────────────
#   TAB 2 • CRUCE DE COMBUSTIBLE
# ────────────────────────────────────────────
with tab2:
    st.header("Cruce de Archivos de Combustible")
    st.markdown(
        "Carga los archivos de consumo y el listado de Mega Gasolineras para generar el reporte combinado."
    )

    consumo_file_tab2 = st.file_uploader(
        "Selecciona el archivo de Consumo de Gasolina", type=["xls", "xlsx"], key="consumo_uploader_tab2"
    )
    mega_gasolineras_file_tab2 = st.file_uploader(
        "Selecciona el archivo de Mega Gasolineras", type=["xls", "xlsx"], key="mega_uploader_tab2_fuel"
    )

    if consumo_file_tab2 and mega_gasolineras_file_tab2:
        if st.button("Procesar y Generar Reporte"):
            with st.spinner("Procesando..."):
                result_df = process_fuel_files(consumo_file_tab2, mega_gasolineras_file_tab2)

            if result_df is not None and not result_df.empty:
                st.success("¡Archivos procesados!")
                csv = result_df.to_csv(index=False, encoding="utf-8-sig")
                st.download_button(
                    "Descargar Reporte CSV",
                    csv,
                    "reporte_combustible_procesado.csv",
                    "text/csv",
                )
                st.dataframe(result_df)
            else:
                st.warning("El proceso finalizó sin datos para mostrar.")


# ────────────────────────────────────────────
#   TAB 3 • ANÁLISIS CON IA
# ────────────────────────────────────────────
with tab3:
    st.header("🤖 Análisis Automático con IA (Gemini)")
    st.markdown(
        "Obtén un análisis técnico detallado y sugiere hipótesis sobre el rendimiento de la flota basado en los datos de la primera pestaña."
    )

    api_key = st.text_input(
        "Ingresa tu API Key de Google Gemini para activar la IA", type="password", key="gemini_api_key"
    )

    if st.button("✨ Generar Análisis Técnico de la Flota", key="gemini_auto_analysis"):
        if not api_key:
            st.warning("Por favor, ingresa tu API Key de Gemini para continuar.")
        elif (
            st.session_state.get("kpi_data") is None
            or st.session_state["kpi_data"].empty
        ):
            st.error(
                "No hay datos de rendimiento para analizar. "
                "Por favor, carga y filtra los datos en la pestaña 'Dashboard Wialon' primero."
            )
        else:
            with st.spinner("La IA está analizando los datos de la flota... 🧠"):
                kpi_md = st.session_state["kpi_data"].to_markdown()

                prompt = f'''
Eres un analista experto en gestión de flotas y logística. Tu misión es proporcionar insights de alto valor para la toma de decisiones, analizando los datos a nivel micro (unidad por unidad) y macro (flota completa).

**Tabla de Datos de Rendimiento (Dashboard Wialon):**
{kpi_md}

Por favor, estructura tu análisis de la siguiente manera para maximizar la claridad y el impacto para el cliente:

**1. Análisis a Nivel Micro (Unidad por Unidad):**
Para **cada una de las unidades** en la tabla, proporciona un análisis conciso pero completo que incluya:
- **Evaluación de KPIs Clave:** Comenta su `Rendimiento (km/L)`, `Costo por Km ($/km)` y `Perfil Urbano (%)`.
- **Contexto de Eficiencia (IEA):** Explica qué significa su `Índice de Eficiencia Ajustado (IEA)`. ¿Está por encima o por debajo del promedio de la flota y por qué podría ser?
- **Punto de Atención:** Menciona un aspecto clave a destacar para esa unidad (ej. "Excelente rendimiento a pesar de su alto perfil urbano" o "Costo por km preocupantemente alto, requiere investigación").

**2. Análisis a Nivel Macro (Flota Completa):**
Una vez analizadas las unidades individualmente, ofrece una visión general de la flota:
- **Resumen Ejecutivo del Rendimiento:** ¿Cuál es el estado general de la flota? Calcula y comenta los promedios de los KPIs más importantes (`Rendimiento`, `Costo por Km`, `IEA`).
- **Identificación de Patrones:** ¿Existen grupos de unidades con comportamientos similares (ej. un departamento con bajo rendimiento, un modelo de vehículo con alta eficiencia)?
- **Valores Atípicos (Positivos y Negativos):** Señala las 2-3 unidades con el rendimiento más destacado (héroes de la eficiencia) y las 2-3 con el rendimiento más bajo (áreas de oportunidad críticas), explicando brevemente las razones.

**3. Hipótesis y Recomendaciones Estratégicas:**
Basado en los análisis micro y macro, propón:
- **Al menos 3 hipótesis fundamentadas** que puedan explicar las variaciones de rendimiento observadas (ej. hábitos de conducción, rutas asignadas, necesidad de mantenimiento, tipo de vehículo).
- **Recomendaciones accionables y priorizadas** para la gerencia. Sugiere pasos concretos para mejorar la eficiencia de las unidades con bajo rendimiento y para replicar el éxito de las mejores.

Utiliza un lenguaje claro y directo, enfocado en generar valor para el cliente. Organiza tu respuesta con los encabezados numerados exactamente como se indica.
'''

                respuesta_ia = call_gemini_api(api_key, prompt)

            st.subheader("Análisis Técnico de la Flota")
            if respuesta_ia:
                st.markdown(respuesta_ia)
            else:
                st.error(
                    "No se pudo obtener una respuesta de la IA. Verifica tu API key y la conexión."
                )

# ────────────────────────────────────────────
#   TAB 4 • VIAJES FIN DE SEMANA
# ────────────────────────────────────────────
with tab4:
    st.header("📆 Viajes Fin de Semana")
    st.markdown(
        "Kilometraje recorrido y costo asociado **solo** los sábados y domingos  \n        (basado en el *Costo por Km* calculado en el Dashboard)."
    )

    # --- Verifica que los datos base ya existan ---
    if uploaded_file and mega_gasolineras_file_tab1 and "kpi_data" in st.session_state:

        # Si el usuario ya aplicó filtros en el Dashboard, reutilízalos;
        # de lo contrario, trabaja con todo el DataFrame.
        try:
            df_viajes_filtrado = df_viajes[mask_viajes].copy()        # ← definido en el Dashboard
        except NameError:
            df_viajes_filtrado = df_viajes.copy()

        # 1️⃣ Filtra únicamente sábado (5) y domingo (6)
        df_weekend = df_viajes_filtrado[
            df_viajes_filtrado["Comienzo"].dt.dayofweek.isin([5, 6])
        ].copy()

        if df_weekend.empty:
            st.info("No hay viajes registrados en fin de semana para el rango seleccionado.")
        else:
            # 2️⃣ Crea etiqueta de semana (inicio de semana = lunes)
            df_weekend["Semana"] = df_weekend["Comienzo"].dt.to_period("W").apply(
                lambda r: r.start_time.date()
            )

            # 3️⃣ Agrupa km por Unidad y Semana
            resumen_km = (
                df_weekend.groupby(["Semana", "Agrupación"])["Kilometraje"]
                .sum()
                .reset_index()
                .rename(columns={"Kilometraje": "Km Fin de Semana"})
            )

            # 4️⃣ Anexa el Costo por Km que ya calculó el Dashboard
            costo_por_km = st.session_state["kpi_data"].reset_index()[  # «kpi_data» ya contiene la columna
                ["Unidad", "Costo por Km ($/km)"]
            ].rename(columns={"Unidad": "Agrupación"})

            resumen = resumen_km.merge(costo_por_km, on="Agrupación", how="left")

            # 5️⃣ Calcula el costo total del fin de semana
            resumen["Costo Fin de Semana ($)"] = (
                resumen["Km Fin de Semana"] * resumen["Costo por Km ($/km)"]
            )

            # 6️⃣ Muestra los resultados
            st.subheader("Detalle por Semana y Unidad")
            st.dataframe(
                resumen.style.format(
                    {
                        "Km Fin de Semana": "{:,.0f} km",
                        "Costo por Km ($/km)": "${:,.2f}",
                        "Costo Fin de Semana ($)": "${:,.2f}",
                    }
                )
            )

            # 7️⃣ Métricas totales
            total_km = resumen["Km Fin de Semana"].sum()
            total_cost = resumen["Costo Fin de Semana ($)"].sum()
            c1, c2 = st.columns(2)
            c1.metric("Total Km Fin de Semana", f"{total_km:,.0f} km")
            c2.metric("Costo Total Fin de Semana", f"${total_cost:,.2f}")

    else:
        st.info("Primero carga y procesa los archivos en la pestaña **Dashboard Wialon**.") 
