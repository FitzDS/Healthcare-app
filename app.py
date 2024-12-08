import streamlit as st
import pandas as pd
import requests
import geocoder
from streamlit_folium import st_folium
import folium
import openai

# API keys (Replace with secure secrets management in production)
GEOAPIFY_API_KEY = "f01884465c8743a9a1d805d1c778e7af"
GOOGLE_API_KEY = "AIzaSyBIghdeoXzo-XYY1mJkeIezTDPhr6WAHgM"
OPENAI_API_KEY = "your-openai-api-key"
openai.api_key = OPENAI_API_KEY

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

# Initialize session state
if "map" not in st.session_state:
    st.session_state["map"] = None
if "facilities" not in st.session_state:
    st.session_state["facilities"] = pd.DataFrame()
if "current_location_marker" not in st.session_state:
    st.session_state["current_location_marker"] = None

def classify_issue_gpt(issue_description):
    """
    Classify an issue description using GPT.
    """
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Classify problems into healthcare categories."},
                {"role": "user", "content": issue_description}
            ]
        )
        return response["choices"][0]["message"]["content"]
    except Exception as e:
        st.error(f"Error with GPT classification: {e}")
        return "All Healthcare"

def fetch_healthcare_data(latitude, longitude, radius, care_type):
    url = "https://api.geoapify.com/v2/places"
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
                "category": properties.get("categories", ["healthcare"])[0]
            }
            facilities.append(facility)
        return pd.DataFrame(facilities)
    else:
        st.error(f"Error fetching data from Geoapify: {response.status_code}")
        return pd.DataFrame()

def fetch_ratings_and_open_status(facilities_df):
    updated_facilities = []
    errors = []

    for _, facility in facilities_df.iterrows():
        url = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
        params = {
            'input': facility['name'],
            'inputtype': 'textquery',
            'fields': 'rating,user_ratings_total,opening_hours',
            'locationbias': f"point:{facility['latitude']},{facility['longitude']}",
            'key': GOOGLE_API_KEY
        }
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
            errors.append(facility['name'])
            facility['rating'] = 'N/A'
            facility['user_ratings_total'] = 0
            facility['open_now'] = 'N/A'

        updated_facilities.append(facility)

    if errors:
        st.error(f"Error fetching ratings for: {', '.join(errors)}")
    return pd.DataFrame(updated_facilities)

def get_current_location():
    try:
        g = geocoder.ip('me')
        if g.ok:
            return g.latlng
    except Exception as e:
        st.error(f"Error detecting location: {e}")
    return [38.5449, -121.7405]

def get_lat_lon_from_query(query):
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": query, "key": GOOGLE_API_KEY}
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        if data["results"]:
            location = data["results"][0]["geometry"]["location"]
            return location["lat"], location["lng"]
    st.error("Location not found. Please try again.")
    return None, None

# UI
st.title("Healthcare Facility Locator")

location_query = st.text_input("Search by Location:")
use_current_location = st.button("Use Current Location")
latitude = st.number_input("Latitude", value=38.5449)
longitude = st.number_input("Longitude", value=-121.7405)
radius = st.slider("Search Radius (meters):", min_value=500, max_value=200000, step=1000, value=20000)
care_type = st.selectbox("Type of Care:", options=list(CARE_TYPES.keys()))
issue_description = st.text_area("Describe the issue (optional):")

if issue_description:
    inferred_care_type = classify_issue_gpt(issue_description)
    st.write(f"Inferred Type of Care: {inferred_care_type}")
    care_type = inferred_care_type

if use_current_location:
    current_location = get_current_location()
    latitude, longitude = current_location
    st.write(f"Using current location: {latitude}, {longitude}")
elif location_query:
    lat, lon = get_lat_lon_from_query(location_query)
    if lat and lon:
        latitude, longitude = lat, lon
        st.write(f"Using location: {location_query} (Lat: {latitude}, Lon: {longitude})")

if st.button("Search"):
    st.write("Fetching data...")
    facilities = fetch_healthcare_data(latitude, longitude, radius, CARE_TYPES[care_type])
    if facilities.empty:
        st.error("No facilities found. Adjust your search.")
    else:
        facilities = fetch_ratings_and_open_status(facilities)
        st.session_state["facilities"] = facilities

        # Map
        m = folium.Map(location=[latitude, longitude], zoom_start=12)
        for _, row in facilities.iterrows():
            folium.Marker(
                [row["latitude"], row["longitude"]],
                popup=f"{row['name']} ({row['rating']} stars)",
                icon=folium.Icon(color="blue")
            ).add_to(m)
        st_folium(m, width=700, height=500)
