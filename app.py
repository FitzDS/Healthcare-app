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
GOOGLE_API_KEY = st.secrets["api_keys"]["google"]

CARE_TYPES = {
    "All Healthcare": ["hospital", "pharmacy", "doctor", "dentist", "veterinary_care", "physiotherapist"],
    "Pharmacy": "pharmacy",
    "Hospital": "hospital",
    "Doctor": "doctor",
    "Dentist": "dentist",
    "Veterinary": "veterinary_care",
    "Physiotherapist": "physiotherapist",
}

LANGUAGES = {"English": "en", "Spanish": "es"}
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

@st.cache_data
def classify_issue_with_openai_cached(issue_description):
    """
    Classifies a healthcare issue description using OpenAI's API and caches the result.

    Args:
        issue_description (str): The description of the issue.

    Returns:
        str: Predicted healthcare category.
    """
    prompt = f"""
    You are an expert in healthcare classification. Classify the following issue description into one of these categories:
    {', '.join(CARE_TYPES.keys())}.

    Examples:
    - "I need medication for my cold" -> Pharmacy
    - "I broke my arm and need treatment" -> Hospital
    - "My dog needs a checkup" -> Veterinary
    - "I need help recovering from a sports injury" -> Physiotherapist
    - "I need dental work" -> Dentist

    Issue: {issue_description}
    Category:"""

    primary_model = "gpt-4o-mini"
    fallback_model = "gpt-3.5-turbo"

    try:
        # Attempt classification with the primary model
        response = client.chat.completions.create(
            model=primary_model,
            messages=[
                {"role": "system", "content": "You are a healthcare classification assistant."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=50,
            temperature=0
        )
        category = response.choices[0].message.content.strip()
        return category
    except Exception as e:
        print(f"Error with {primary_model}: {e}. Trying fallback model {fallback_model}.")
        try:
            # Attempt classification with the fallback model
            response = client.chat.completions.create(
                model=fallback_model,
                messages=[
                    {"role": "system", "content": "You are a healthcare classification assistant."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=50,
                temperature=0
            )
            category = response.choices[0].message.content.strip()
            return category
        except Exception as fallback_error:
            print(f"Error with fallback model {fallback_model}: {fallback_error}.")
            return "Error"


def fetch_healthcare_data_google(latitude, longitude, radius, care_type, open_only=False):
    """
    Fetch healthcare data using Google Places API with support for multiple healthcare categories.

    Args:
        latitude (float): Latitude of the search center.
        longitude (float): Longitude of the search center.
        radius (int): Search radius in meters.
        care_type (str or list): Type of healthcare facility to search for (single or multiple).
        open_only (bool): Whether to include only currently open facilities.

    Returns:
        pd.DataFrame: A DataFrame containing healthcare facility details.
    """
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    facilities = []

    # Handle multiple types for "All Healthcare"
    if isinstance(care_type, list):
        types_to_query = care_type
    else:
        types_to_query = [care_type]

    for care_type_query in types_to_query:
        params = {
            "location": f"{latitude},{longitude}",
            "radius": radius,
            "type": care_type_query,
            "key": GOOGLE_API_KEY,
        }

        while True:
            response = requests.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                for result in data.get("results", []):
                    if open_only and not result.get("opening_hours", {}).get("open_now", False):
                        continue

                    facilities.append({
                        "name": result.get("name", "Unknown"),
                        "address": result.get("vicinity", "N/A"),
                        "latitude": result["geometry"]["location"]["lat"],
                        "longitude": result["geometry"]["location"]["lng"],
                        "rating": result.get("rating", "No rating"),
                        "user_ratings_total": result.get("user_ratings_total", 0),
                        "open_now": result.get("opening_hours", {}).get("open_now", "Unknown"),
                    })

                # Check for the next page token
                next_page_token = data.get("next_page_token")
                if next_page_token:
                    # Pause to let the token activate (required by API)
                    import time
                    time.sleep(2)
                    params = {"pagetoken": next_page_token, "key": GOOGLE_API_KEY}
                else:
                    break
            else:
                st.error(f"Error fetching data from Google Places API: {response.status_code}")
                break

    return pd.DataFrame(facilities)

def get_lat_lon_from_query(query):
    url = f"https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": query, "key": GOOGLE_API_KEY}
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        if data["results"]:
            location = data["results"][0]["geometry"]["location"]
            return location["lat"], location["lng"]
    st.error("Location not found. Please try again.")
    return None, None

def get_current_location():
    g = geocoder.ip('me')
    if g.ok:
        return g.latlng
    st.error("Unable to detect current location.")
    return [38.5449, -121.7405]

# Translation dictionary
TRANSLATIONS = {
    "title": {
        "en": "Healthcare Facility Locator",
        "es": "Buscador de Instalaciones Médicas"
    },
    "legend": {
        "en": """### Legend
- **Red Marker**: Current Location
- **Rating Colors**:
  - **Green**: 4-5 Stars
  - **Blue**: 3-4 Stars
  - **Orange**: 2-3 Stars
  - **Yellow**: 1-2 Stars
  - **Gray**: Unrated or 0-1 Stars
""",
        "es": """### Leyenda
- **Marcador Rojo**: Ubicación Actual
- **Colores de Clasificación**:
  - **Verde**: 4-5 Estrellas
  - **Azul**: 3-4 Estrellas
  - **Naranja**: 2-3 Estrellas
  - **Amarillo**: 1-2 Estrellas
  - **Gris**: Sin Clasificación o 0-1 Estrellas
"""
    },
    "search_by_location": {
        "en": "Search by Location:",
        "es": "Buscar por Ubicación:"
    },
    "radius": {
        "en": "Search Radius (meters):",
        "es": "Radio de Búsqueda (metros):"
    },
    "describe_issue": {
        "en": "Describe the issue (optional):",
        "es": "Describa el problema (opcional):"
    },
    "type_of_care": {
        "en": "Type of Care (leave blank to auto-detect):",
        "es": "Tipo de Atención (deje en blanco para detectar automáticamente):"
    },
    "open_only": {
        "en": "Show only open facilities",
        "es": "Mostrar solo instalaciones abiertas"
    },
    "note_search_location": {
        "en": "Note: Search by location will take precedence over the 'Use Current Location' button.",
        "es": "Nota: La búsqueda por ubicación tendrá prioridad sobre el botón 'Usar ubicación actual'."
    },
    "use_current_location": {
        "en": "Use Current Location",
        "es": "Usar Ubicación Actual"
    },
    "latitude": {
        "en": "Latitude",
        "es": "Latitud"
    },
    "longitude": {
        "en": "Longitude",
        "es": "Longitud"
    },
    "search_button": {
        "en": "Search",
        "es": "Buscar"
    },
    "fetching_data": {
        "en": "Fetching data...",
        "es": "Obteniendo datos..."
    },
    "no_facilities_found": {
        "en": "No facilities found. Check your API key, location, or radius.",
        "es": "No se encontraron instalaciones. Verifique su clave API, ubicación o radio."
    },
    "inferred_care_type": {
        "en": "Inferred Type of Care:",
        "es": "Tipo de Atención Inferido:"
    },
    "classification_warning": {
        "en": "Could not classify issue; defaulting to All Healthcare.",
        "es": "No se pudo clasificar el problema; cambiando a Atención Médica General."
    },
    "using_location": {
        "en": "Using location:",
        "es": "Usando ubicación:"
    }
}

# Function to get translated text
def translate(key):
    return TRANSLATIONS[key][language_code]

# Updated Streamlit UI with translations
st.title(translate("title"))
st.markdown(translate("legend"))

location_query = st.text_input(translate("search_by_location"))
radius = st.slider(
    translate("radius"),
    min_value=500,
    max_value=100000,
    step=1000,
    value=20000,
    help=translate("note_search_location")
)
issue_description = st.text_area(translate("describe_issue"))
care_type = st.selectbox(translate("type_of_care"), options=[""] + list(CARE_TYPES.keys()))
open_only = st.checkbox(translate("open_only"))

st.caption(translate("note_search_location"))
use_current_location = st.button(translate("use_current_location"), key="current_location_button")
latitude = st.number_input(translate("latitude"), value=38.5449)
longitude = st.number_input(translate("longitude"), value=-121.7405)

if st.button(translate("search_button"), key="search_button"):
    st.write(translate("fetching_data"))
    facilities = fetch_healthcare_data_google(
        latitude=latitude,
        longitude=longitude,
        radius=radius,
        care_type=CARE_TYPES.get(care_type, "hospital"),
        open_only=open_only
    )

    if facilities.empty:
        st.error(translate("no_facilities_found"))
        st.session_state["map"] = folium.Map(location=[latitude, longitude], zoom_start=12)
    else:
        st.write(f"{translate('inferred_care_type')} {len(facilities)}")

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
                elif float(row["rating"]) >= 2:
                    color = "orange"
                elif float(row["rating"]) >= 1:
                    color = "yellow"

            folium.Marker(
                location=[row["latitude"], row["longitude"]],
                popup=f"<b>{row['name']}</b><br>Address: {row['address']}<br>Open Now: {row['open_now']}<br>Rating: {row['rating']} ({row['user_ratings_total']} reviews)",
                icon=folium.Icon(color=color)
            ).add_to(m)

        folium.Marker(
            location=[latitude, longitude],
            popup="Current Location",
            icon=folium.Icon(icon="info-sign", color="red")
        ).add_to(m)

        st.session_state["map"] = m

if "map" in st.session_state and st.session_state["map"] is not None:
    st_folium(st.session_state["map"], width=700, height=500)
else:
    default_map = folium.Map(location=[latitude, longitude], zoom_start=12)
    folium.Marker(
        location=[latitude, longitude],
        popup="Current Location",
        icon=folium.Icon(icon="info-sign", color="red")
    ).add_to(default_map)
    folium.Circle(
        location=[latitude, longitude],
        radius=radius,
        color="blue",
        fill=True,
        fill_opacity=0.4
    ).add_to(default_map)
    st_folium(default_map, width=700, height=500)


