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

# Language selection
LANGUAGES = {"English": "en", "Spanish": "es"}
selected_language = st.selectbox("Choose Language / Seleccione el idioma:", options=LANGUAGES.keys())
language_code = LANGUAGES[selected_language]

# Translations for UI text
TRANSLATIONS = {
    "en": {
        "title": "Healthcare Facility Locator",
        "choose_language": "Choose Language",
        "search_location": "Search by Location:",
        "search_radius": "Search Radius (meters):",
        "describe_issue": "Describe the issue (optional):",
        "care_type": "Type of Care (leave blank to auto-detect):",
        "open_only": "Show only open facilities",
        "use_current_location": "Use Current Location",
        "found_facilities": "Found {count} facilities.",
        "no_facilities": "No facilities found. Check your API key, location, or radius.",
        "note": "Note: Search by location will take precedence over the 'Use Current Location' button.",
    },
    "es": {
        "title": "Buscador de Instalaciones de Salud",
        "choose_language": "Seleccione el idioma",
        "search_location": "Buscar por Ubicación:",
        "search_radius": "Radio de búsqueda (metros):",
        "describe_issue": "Describa el problema (opcional):",
        "care_type": "Tipo de Atención (dejar en blanco para detección automática):",
        "open_only": "Mostrar solo instalaciones abiertas",
        "use_current_location": "Usar ubicación actual",
        "found_facilities": "Se encontraron {count} instalaciones.",
        "no_facilities": "No se encontraron instalaciones. Verifique su clave API, ubicación o radio.",
        "note": "Nota: La búsqueda por ubicación tendrá prioridad sobre el botón 'Usar ubicación actual'.",
    },
}

# Main title
st.title(TRANSLATIONS[language_code]["title"])

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

# User inputs
location_query = st.text_input(TRANSLATIONS[language_code]["search_location"])
radius = st.slider(
    TRANSLATIONS[language_code]["search_radius"],
    min_value=500,
    max_value=200000,
    step=1000,
    value=20000,
)
issue_description = st.text_area(TRANSLATIONS[language_code]["describe_issue"])
care_type = st.selectbox(
    TRANSLATIONS[language_code]["care_type"],
    options=[""] + list(CARE_TYPES.keys()),
)
open_only = st.checkbox(TRANSLATIONS[language_code]["open_only"])

st.caption(TRANSLATIONS[language_code]["note"])

# Initialize session state for map and facilities
if "map" not in st.session_state:
    st.session_state["map"] = None
if "facilities" not in st.session_state:
    st.session_state["facilities"] = pd.DataFrame()

# Ensure the current location marker is persistent
if "current_location_marker" not in st.session_state:
    st.session_state["current_location_marker"] = None

def classify_issue_with_openai(issue_description):
    """
    Classifies a healthcare issue description using OpenAI's API.

    Args:
        issue_description (str): The description of the issue.

    Returns:
        str: Predicted healthcare category.
    """
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
                {"role": "user", "content": prompt},
            ],
            max_tokens=50,
            temperature=0,
        )
        category = response.choices[0].message.content.strip()
        return category
    except Exception as e:
        st.error(f"Error during classification: {e}")
        return "Error"

def fetch_healthcare_data(latitude, longitude, radius, care_type, open_only=False):
    url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{latitude},{longitude}",
        "radius": radius,
        "type": care_type,
        "key": GOOGLE_API_KEY,
    }

    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        facilities = []
        for result in data.get("results", []):
            if open_only and not result.get("opening_hours", {}).get("open_now", False):
                continue  # Skip facilities that are not currently open
            facility = {
                "name": result.get("name", "Unknown"),
                "address": result.get("vicinity", "N/A"),
                "latitude": result["geometry"]["location"]["lat"],
                "longitude": result["geometry"]["location"]["lng"],
                "rating": result.get("rating", "No rating"),
                "user_ratings_total": result.get("user_ratings_total", 0),
                "open_now": result.get("opening_hours", {}).get("open_now", "Unknown"),
            }
            facilities.append(facility)
        return pd.DataFrame(facilities)
    else:
        st.error(f"Error fetching data from Google Places API: {response.status_code}")
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
    st.error("Location not found. Please try again.")
    return None, None

def get_current_location():
    g = geocoder.ip('me')
    if g.ok:
        return g.latlng
    st.error("Unable to detect current location.")
    return [38.5449, -121.7405]

# Use location input or current location
use_current_location = st.button(TRANSLATIONS[language_code]["use_current_location"])
latitude = st.number_input("Latitude", value=38.5449)
longitude = st.number_input("Longitude", value=-121.7405)

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

if st.button("Search"):
    st.write("Fetching data...")
    facilities = fetch_healthcare_data(latitude, longitude, radius, CARE_TYPES.get(care_type, "hospital"), open_only=open_only)

    if facilities.empty:
                st.error(TRANSLATIONS[language_code]["no_facilities"])
        st.session_state["map"] = folium.Map(location=[latitude, longitude], zoom_start=12)
    else:
        st.write(TRANSLATIONS[language_code]["found_facilities"].format(count=len(facilities)))
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
                popup=f"<b>{row['name']}</b><br>{TRANSLATIONS[language_code]['search_location']}: {row['address']}<br>Open Now: {row['open_now']}<br>Rating: {row['rating']} ({row['user_ratings_total']} reviews)",
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

    
