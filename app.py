import streamlit as st
import pandas as pd
import requests
import geocoder
from streamlit_folium import st_folium
import folium
from openai import Client

# Set up OpenAI client
client = Client(api_key=st.secrets["api_keys"]["openai"])

# Load API keys from Streamlit secrets
GEOAPIFY_API_KEY = st.secrets["api_keys"]["geoapify"]
GOOGLE_API_KEY = st.secrets["api_keys"]["google"]

CARE_TYPES = {
    "All Healthcare": "healthcare",
    "Pharmacy": "healthcare.pharmacy",
    "Hospital": "healthcare.hospital",
    "Clinic": "healthcare.clinic",
    "Dentist": "healthcare.dentist",
    "Rehabilitation": "healthcare.rehabilitation",
    "Emergency": "healthcare.emergency",
    "Veterinary": "healthcare.veterinary",
}

LANGUAGES = {"English": "en", "Spanish": "es"}
selected_language = st.selectbox("Choose Language / Seleccione el idioma:", options=LANGUAGES.keys())
language_code = LANGUAGES[selected_language]

# Language-based text replacements
translations = {
    "title": {"en": "Healthcare Facility Locator", "es": "Localizador de Instalaciones de Salud"},
    "legend_title": {"en": "Legend", "es": "Leyenda"},
    "legend_red_marker": {"en": "Red Marker: Current Location", "es": "Marcador Rojo: Ubicación Actual"},
    "legend_rating_colors": {"en": "Rating Colors", "es": "Colores de Calificación"},
    "legend_colors": {
        "en": [
            "Green: 4-5 Stars",
            "Blue: 3-4 Stars",
            "Orange: 2-3 Stars",
            "Yellow: 1-2 Stars",
            "Gray: Unrated or 0-1 Stars",
        ],
        "es": [
            "Verde: 4-5 Estrellas",
            "Azul: 3-4 Estrellas",
            "Naranja: 2-3 Estrellas",
            "Amarillo: 1-2 Estrellas",
            "Gris: Sin calificación o 0-1 Estrellas",
        ],
    },
    "search_by_location": {"en": "Search by Location:", "es": "Buscar por Ubicación:"},
    "radius_slider": {"en": "Search Radius (meters):", "es": "Radio de Búsqueda (metros):"},
    "radius_help": {
        "en": "Note: Only the 60 nearest facilities will be shown, as per API limitations.",
        "es": "Nota: Solo se mostrarán las 60 instalaciones más cercanas, según las limitaciones de la API.",
    },
    "issue_description": {"en": "Describe the issue (optional):", "es": "Describa el problema (opcional):"},
    "care_type": {"en": "Type of Care (leave blank to auto-detect):", "es": "Tipo de Cuidado (déjelo en blanco para detectar automáticamente):"},
    "open_only": {"en": "Show only open facilities", "es": "Mostrar solo instalaciones abiertas"},
    "search_button": {"en": "Search", "es": "Buscar"},
    "current_location_button": {"en": "Use Current Location", "es": "Usar Ubicación Actual"},
    "latitude": {"en": "Latitude", "es": "Latitud"},
    "longitude": {"en": "Longitude", "es": "Longitud"},
    "fetching_data": {"en": "Fetching data...", "es": "Obteniendo datos..."},
    "no_facilities_found": {"en": "No facilities found. Check your API key, location, or radius.", "es": "No se encontraron instalaciones. Verifique su clave API, ubicación o radio."},
    "found_facilities": {"en": "Found {count} facilities.", "es": "Se encontraron {count} instalaciones."},
    "popup_current_location": {"en": "Current Location", "es": "Ubicación Actual"},
    "infer_care_type": {"en": "Inferred Type of Care: {type}", "es": "Tipo de Cuidado Inferido: {type}"},
    "default_care_type_warning": {"en": "Could not classify issue; defaulting to All Healthcare.", "es": "No se pudo clasificar el problema; se usará Todo el Cuidado de Salud."},
    "search_priority_note": {
        "en": "Note: Search by location will take precedence over the 'Use Current Location' button.",
        "es": "Nota: La búsqueda por ubicación tendrá prioridad sobre el botón 'Usar Ubicación Actual'.",
    },
}

# Dynamically fetch translated text based on the selected language
def t(key, **kwargs):
    return translations[key][language_code].format(**kwargs)

st.title(t("title"))

# Add legend above the map
st.markdown(f"""### {t("legend_title")}
- **{t("legend_red_marker")}**
- **{t("legend_rating_colors")}**:
  - {t("legend_colors")[0]}
  - {t("legend_colors")[1]}
  - {t("legend_colors")[2]}
  - {t("legend_colors")[3]}
  - {t("legend_colors")[4]}
""")

location_query = st.text_input(t("search_by_location"))
radius = st.slider(t("radius_slider"), min_value=500, max_value=200000, step=1000, value=20000, help=t("radius_help"))
issue_description = st.text_area(t("issue_description"))
care_type = st.selectbox(t("care_type"), options=[""] + list(CARE_TYPES.keys()))
open_only = st.checkbox(t("open_only"))

if language_code == "es":
    st.caption("Nota: La búsqueda por ubicación tendrá prioridad sobre el botón 'Usar ubicación actual'.")
else:
    st.caption("Note: Search by location will take precedence over the 'Use Current Location' button.")

use_current_location = st.button(t("current_location_button"), key="current_location_button")
latitude = st.number_input(t("latitude"), value=38.5449)
longitude = st.number_input(t("longitude"), value=-121.7405)

if issue_description and not care_type:
    inferred_care_type = classify_issue_with_openai(issue_description)
    if inferred_care_type in CARE_TYPES:
        care_type = inferred_care_type
        st.success(t("infer_care_type", type=care_type))
    else:
        st.warning(t("default_care_type_warning"))

if use_current_location:
    current_location = get_current_location()
    latitude = current_location[0]
    longitude = current_location[1]
    st.write(f"Using current location: Latitude {latitude}, Longitude {longitude}")
    location_query = ""  # Clear the location query to avoid conflicts

elif location_query:
    lat, lon = get_lat_lon_from_query(location_query)
    if lat and lon:
        latitude = lat
        longitude = lon
        st.write(f"Using location: {location_query} (Latitude: {latitude}, Longitude: {longitude})")

if st.button(t("search_button"), key="search_button"):
    st.write(t("fetching_data"))
    facilities = fetch_healthcare_data(latitude, longitude, radius, CARE_TYPES.get(care_type, "hospital"), open_only=open_only)

    if facilities.empty:
        st.error(t("no_facilities_found"))
        st.session_state["map"] = folium.Map(location=[latitude, longitude], zoom_start=12)
    else:
        st.write(t("found_facilities", count=len(facilities)))
        m = folium.Map(location=[latitude, longitude], zoom_start=12)
        folium.Circle(
            location=[latitude, longitude],
            radius=radius,
            color="blue",
            fill=True,
            fill_opacity=0.4
        ).add_to(m)

        for _, row in facilities.iterrows():
            color = "gray"  # Default color for unrated
            if row["rating"] != "No rating" and row["rating"]:
                if float(row["rating"]) >= 4:
                    color = "green"
                elif float(row["rating"]) >= 3:
                    color = "blue"
                elif float(row["rating"] >= 2):
                    color = "orange"
                elif float(row["rating"] >= 1):
                    color = "yellow"

            folium.Marker(
                location=[row["latitude"], row["longitude"]],
                popup=f"<b>{row['name']}</b><br>Address: {row['address']}<br>Open Now: {row['open_now']}<br>Rating: {row['rating']} ({row['user_ratings_total']} reviews)",
                icon=folium.Icon(color=color)
            ).add_to(m)

        folium.Marker(
            location=[latitude, longitude],
            popup=t("popup_current_location"),
            icon=folium.Icon(icon="info-sign", color="red")
        ).add_to(m)

        st.session_state["map"] = m

if "map" in st.session_state and st.session_state["map"] is not None:
    st_folium(st.session_state["map"], width=700, height=500)
else:
    default_map = folium.Map(location=[latitude, longitude], zoom_start=12)
    folium.Marker(
        location=[latitude, longitude],
        popup=t("popup_current_location"),
        icon=folium.Icon(icon="info-sign", color="red")
    ).add_to(default_map)
    folium.Circle(
        location=[latitude, longitude],
        radius=radius,
        color="blue",
        fill=True, fill_opacity=0.4
    ).add_to(default_map)
    st_folium(default_map, width=700, height=500)

