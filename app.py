import streamlit as st
import pandas as pd
import requests
import geocoder
from streamlit_folium import st_folium
import folium

# Load API keys
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

# Translations for different languages
translations = {
    "en": {
        "title": "Healthcare Facility Locator",
        "search_location": "Search by Location:",
        "use_current_location": "Use Current Location",
        "latitude": "Latitude",
        "longitude": "Longitude",
        "radius": "Search Radius (meters):",
        "care_type": "Type of Care:",
        "show_open_only": "Show Open Facilities Only",
        "legend_title": "Legend",
        "legend_current_location": "Red Marker: Current Location",
        "legend_rating_colors": "Rating Colors:",
        "legend_green": "Green: 4-5 Stars",
        "legend_blue": "Blue: 3-4 Stars",
        "legend_orange": "Orange: 2-3 Stars",
        "legend_yellow": "Yellow: 1-2 Stars",
        "legend_gray": "Gray: Unrated or 0-1 Stars",
        "found_facilities": "Found {} facilities.",
        "no_facilities": "No facilities found. Check your API key, location, or radius.",
        "open_now": "Open Now",
        "directions": "Get Directions",
    },
    "es": {
        "title": "Localizador de Centros de Salud",
        "search_location": "Buscar por Ubicación:",
        "use_current_location": "Usar Ubicación Actual",
        "latitude": "Latitud",
        "longitude": "Longitud",
        "radius": "Radio de Búsqueda (metros):",
        "care_type": "Tipo de Atención:",
        "show_open_only": "Mostrar solo Centros Abiertos",
        "legend_title": "Leyenda",
        "legend_current_location": "Marcador Rojo: Ubicación Actual",
        "legend_rating_colors": "Colores de Calificación:",
        "legend_green": "Verde: 4-5 Estrellas",
        "legend_blue": "Azul: 3-4 Estrellas",
        "legend_orange": "Naranja: 2-3 Estrellas",
        "legend_yellow": "Amarillo: 1-2 Estrellas",
        "legend_gray": "Gris: Sin Calificar o 0-1 Estrellas",
        "found_facilities": "Se encontraron {} centros.",
        "no_facilities": "No se encontraron centros. Verifique su clave API, ubicación o radio.",
        "open_now": "Abierto Ahora",
        "directions": "Obtener Indicaciones",
    },
}


# Select language
selected_language = st.selectbox("Choose Language / Seleccione el idioma:", options=["en", "es"])
lang = translations[selected_language]

# Initialize session state for map and facilities
if "map" not in st.session_state:
    st.session_state["map"] = None
if "facilities" not in st.session_state:
    st.session_state["facilities"] = pd.DataFrame()

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
        st.error(f"Error fetching data from Geoapify: {response.status_code}")
        return pd.DataFrame()

def fetch_ratings_and_open_status(facilities_df):
    updated_facilities = []
    for _, facility in facilities_df.iterrows():
        url = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
        params = {
            'input': facility['name'],
            'inputtype': 'textquery',
            'fields': 'rating,user_ratings_total,opening_hours',
            'locationbias': f"point:{facility['latitude']},{facility['longitude']}",
            'key': GOOGLE_API_KEY
        }
        facility['opening_hours'] = candidate.get('opening_hours', {}).get('weekday_text', [])
        hours = "<br>".join(row['opening_hours']) if row['opening_hours'] else "N/A"


        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            if data.get('candidates'):
                candidate = data['candidates'][0]
                facility['rating'] = candidate.get('rating', 'N/A')
                facility['user_ratings_total'] = candidate.get('user_ratings_total', 0)
                facility['open_now'] = candidate.get('opening_hours', {}).get('open_now', 'N/A')
            else:
                facility['rating'] = 'N/A'
                facility['user_ratings_total'] = 0
                facility['open_now'] = 'N/A'
        else:
            st.error(f"Error fetching ratings for {facility['name']}: {response.status_code}")
            facility['rating'] = 'N/A'
            facility['user_ratings_total'] = 0
            facility['open_now'] = 'N/A'
        updated_facilities.append(facility)
    return pd.DataFrame(updated_facilities)

st.title(lang["title"])

# Add legend above the map
st.markdown(f"""### {lang['legend_title']}
- **{lang['legend_current_location']}**
- **{lang['legend_rating_colors']}**
  - **{lang['legend_green']}**
  - **{lang['legend_blue']}**
  - **{lang['legend_orange']}**
  - **{lang['legend_yellow']}**
  - **{lang['legend_gray']}**
""")


location_query = st.text_input(lang["search_location"])
use_current_location = st.button(lang["use_current_location"], key="current_location_button")
latitude = st.number_input(lang["latitude"], value=38.5449)
longitude = st.number_input(lang["longitude"], value=-121.7405)
radius = st.slider(lang["radius"], min_value=500, max_value=200000, step=1000, value=20000)
care_type = st.selectbox(lang["care_type"], options=list(CARE_TYPES.keys()))
show_open_only = st.checkbox(lang["show_open_only"], value=False)

if location_query:
    lat, lon = get_lat_lon_from_query(location_query)
    if lat and lon:
        latitude = lat
        longitude = lon
        st.write(f"{lang['search_location']} {location_query} (Latitude: {latitude}, Longitude: {longitude})")

if use_current_location:
    current_location = get_current_location()
    latitude = current_location[0]
    longitude = current_location[1]
    st.write(f"{lang['use_current_location']} (Latitude: {latitude}, Longitude: {longitude})")

if st.button("Search", key="search_button"):
    st.write("Fetching data...")
    facilities = fetch_healthcare_data(latitude, longitude, radius, CARE_TYPES[care_type])

    if facilities.empty:
        st.error(lang["no_facilities"])
        st.session_state["map"] = folium.Map(location=[latitude, longitude], zoom_start=12)
        st.session_state["facilities"] = pd.DataFrame()
    else:
        st.write(lang["found_facilities"].format(len(facilities)))
        facilities_with_ratings = fetch_ratings_and_open_status(facilities)
        if show_open_only:
            facilities_with_ratings = facilities_with_ratings[
                facilities_with_ratings['open_now'] == True
            ]
        st.session_state["facilities"] = facilities_with_ratings

        m = folium.Map(location=[latitude, longitude], zoom_start=12)
        folium.Circle(
            location=[latitude, longitude],
            radius=radius,
            color="blue",
            fill=True,
            fill_opacity=0.4
        ).add_to(m)

        for _, row in facilities_with_ratings.iterrows():
            rating = row['rating']
            if rating == 'N/A' or float(rating) <= 1:
                marker_color = 'gray'
            elif 1 < float(rating) <= 2:
                marker_color = 'yellow'
            elif 2 < float(rating) <= 3:
                marker_color = 'orange'
            elif 3 < float(rating) <= 4:
                marker_color = 'blue'
            else:
                marker_color = 'green'

            popup_content = (
                f"<b>{row['name']}</b><br>"
                f"Address: {row['address']}<br>"
                f"Rating: {row['rating']} ({row['user_ratings_total']} reviews)<br>"
                f"{lang['open_now']}: {'Yes' if row['open_now'] else 'No'}<br>"
                f"Hours:<br>{hours}<br>"
                f"<a href='https://www.google.com/maps/dir/?api=1&origin={latitude},{longitude}&destination={row['latitude']},{row['longitude']}&hl={selected_language}' target='_blank'>{lang['directions']}</a>"
            )

            folium.Marker(
                location=[row["latitude"], row["longitude"]],
                popup=popup_content,
                icon=folium.Icon(color=marker_color)
            ).add_to(m)

        folium.Marker(
            location=[latitude, longitude],
            popup="Current Location",
            icon=folium.Icon(icon="info-sign", color="red")
        ).add_to(m)

        st.session_state["map"] = m

if "map" in st.session_state and st.session_state["map"] is not None:
    st_folium(st.session_state["map"], width=700, height=500)
