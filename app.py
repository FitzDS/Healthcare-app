import streamlit as st
import pandas as pd
import requests
import geocoder
from streamlit_folium import st_folium
import folium
from openai import Client

# Load API keys
GEOAPIFY_API_KEY = st.secrets["api_keys"]["geoapify"]
GOOGLE_API_KEY = st.secrets["api_keys"]["google"]
OPENAI_API_KEY = st.secrets["api_keys"]["openai"]

# Set up OpenAI client
client = Client(api_key=OPENAI_API_KEY)

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

LANGUAGES = {
    "English": "en",
    "Spanish": "es"
}

TRANSLATIONS = {
    "en": {
        "title": "Healthcare Facility Locator",
        "search_location": "Search by Location:",
        "radius": "Search Radius (meters):",
        "issue_description": "Describe the issue (optional):",
        "care_type": "Type of Care (leave blank to auto-detect):",
        "use_current_location": "Use Current Location",
        "legend": "Legend",
        "legend_current_location": "Red Marker: Current Location",
        "legend_rating_colors": "Rating Colors:",
        "legend_green": "Green: 4-5 Stars",
        "legend_blue": "Blue: 3-4 Stars",
        "legend_orange": "Orange: 2-3 Stars",
        "legend_yellow": "Yellow: 1-2 Stars",
        "legend_gray": "Gray: Unrated or 0-1 Stars",
        "inferred_type_of_care": "Inferred Type of Care:",
        "could_not_classify": "Could not classify issue; defaulting to All Healthcare.",
        "error_fetching_data": "Error fetching data. Check your API key, location, or radius.",
        "found_facilities": "Found {count} facilities."
    },
    "es": {
        "title": "Localizador de Centros de Salud",
        "search_location": "Buscar por Ubicación:",
        "radius": "Radio de Búsqueda (metros):",
        "issue_description": "Describa el problema (opcional):",
        "care_type": "Tipo de atención (déjelo en blanco para detección automática):",
        "use_current_location": "Usar ubicación actual",
        "legend": "Leyenda",
        "legend_current_location": "Marcador rojo: Ubicación actual",
        "legend_rating_colors": "Colores de calificación:",
        "legend_green": "Verde: 4-5 estrellas",
        "legend_blue": "Azul: 3-4 estrellas",
        "legend_orange": "Naranja: 2-3 estrellas",
        "legend_yellow": "Amarillo: 1-2 estrellas",
        "legend_gray": "Gris: Sin calificar o 0-1 estrellas",
        "inferred_type_of_care": "Tipo de atención inferido:",
        "could_not_classify": "No se pudo clasificar el problema; predeterminado a toda la atención médica.",
        "error_fetching_data": "Error al recuperar datos. Verifique su clave API, ubicación o radio.",
        "found_facilities": "Se encontraron {count} instalaciones."
    }
}

selected_language = st.selectbox("Choose Language / Seleccione el idioma:", options=LANGUAGES.keys())
language_code = LANGUAGES[selected_language]

# Initialize session state for map and facilities
if "map" not in st.session_state:
    st.session_state["map"] = None
if "facilities" not in st.session_state:
    st.session_state["facilities"] = pd.DataFrame()

# Ensure the current location marker is persistent
if "current_location_marker" not in st.session_state:
    st.session_state["current_location_marker"] = None

def classify_issue_with_openai(issue_description):
    prompt = f"""
    You are an expert in healthcare classification. Classify the following issue description into one of these categories:
    {', '.join(CARE_TYPES.keys())}.

    Issue: {issue_description}
    Category:"""
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a healthcare classification assistant."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=50,
            temperature=0
        )
        category = response["choices"][0]["message"]["content"].strip()
        return category
    except Exception as e:
        st.write(f"Error during classification: {e}")
        return "All Healthcare"

def fetch_healthcare_data(latitude, longitude, radius, care_type):
    url = f"https://api.geoapify.com/v2/places"
    params = {
        "categories": care_type,
        "filter": f"circle:{longitude},{latitude},{radius}",
        "limit": 100,
        "apiKey": GEOAPIFY_API_KEY,
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        facilities = []
        for feature in data.get("features", []):
            properties = feature.get("properties", {})
            geometry = feature.get("geometry", {})
            facility = {
                "name": properties.get("name", "Unknown"),
                "address": properties.get("formatted", "N/A"),
                "latitude": geometry.get("coordinates", [])[1],
                "longitude": geometry.get("coordinates", [])[0],
            }
            facilities.append(facility)
        return pd.DataFrame(facilities)
    else:
        st.error(TRANSLATIONS[language_code]["error_fetching_data"])
        return pd.DataFrame()

def get_lat_lon_from_query(query):
    url = f"https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": query, "key": GOOGLE_API_KEY}
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        if data["results"]:
            location = data["results"][0]["geometry"]["location"]
            return location["lat"], location["lng"]
    st.error(TRANSLATIONS[language_code]["error_fetching_data"])
    return None, None

def get_current_location():
    g = geocoder.ip('me')
    if g.ok:
        return g.latlng
    st.error(TRANSLATIONS[language_code]["error_fetching_data"])
    return [38.5449, -121.7405]

st.title(TRANSLATIONS[language_code]["title"])

location_query = st.text_input(TRANSLATIONS[language_code]["search_location"])
radius = st.slider(TRANSLATIONS[language_code]["radius"], min_value=500, max_value=200000, step=1000, value=20000)
issue_description = st.text_area(TRANSLATIONS[language_code]["issue_description"])

care_type = st.selectbox(
    TRANSLATIONS[language_code]["care_type"], 
    options=list(CARE_TYPES.keys()),
    index=list(CARE_TYPES.keys()).index("All Healthcare") if not issue_description else 0
)

if issue_description:
    inferred_care_type = classify_issue_with_openai(issue_description)
    st.write(f"{TRANSLATIONS[language_code]['inferred_type_of_care']} {inferred_care_type}")
    if inferred_care_type in CARE_TYPES:
        care_type = inferred_care_type

use_current_location = st.button(TRANSLATIONS[language_code]["use_current_location"])

if use_current_location:
    current_location = get_current_location()
    latitude, longitude = current_location[0], current_location[1]
    location_query = ""
elif location_query:
    lat, lon = get_lat_lon_from_query(location_query)
    if lat and lon:
        latitude, longitude = lat, lon
else:
    latitude, longitude = 38.5449, -121.7405

facilities = fetch_healthcare_data(latitude, longitude, radius, CARE_TYPES[care_type])

if not facilities.empty:
    st.write(TRANSLATIONS[language_code]["found_facilities"].format(count=len(facilities)))
    m = folium.Map(location=[latitude, longitude], zoom_start=12)
    for _, row in facilities.iterrows():
        folium.Marker(
            location=[row["latitude"], row["longitude"]],
            popup=f"<b>{row['name']}</b><br>{row['address']}"
        ).add_to(m)
    st_folium(m, width=700, height=500)
