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
GEOAPIFY_API_KEY = st.secrets["api_keys"]["geoapify"]

CARE_TYPES = {
    "All Healthcare": ["hospital", "pharmacy", "doctor", "dentist", "veterinary_care", "physiotherapist"],
    "Pharmacy": "pharmacy",
    "Hospital": "hospital",
    "Doctor": "doctor",
    "Dentist": "dentist",
    "Veterinary": "veterinary_care",
    "Physiotherapist": "physiotherapist",
}

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
        response = client.chat.completions.create(
            model=primary_model,
            messages=[
                {"role": "system", "content": "You are a healthcare classification assistant."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=200,
            temperature=0
        )
        category = response.choices[0].message.content.strip()
        return category
    except Exception as e:
        print(f"Error with {primary_model}: {e}. Trying fallback model {fallback_model}.")
        try:
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

                next_page_token = data.get("next_page_token")
                if next_page_token:
                    import time
                    time.sleep(2)
                    params = {"pagetoken": next_page_token, "key": GOOGLE_API_KEY}
                else:
                    break
            else:
                st.error(f"Error fetching data from Google Places API: {response.status_code}")
                break

    return pd.DataFrame(facilities)


def check_wheelchair_accessibility(lat, lon, geoapify_api_key):
    """
    Check wheelchair accessibility for a specific location using Geoapify API.

    Args:
        lat (float): Latitude of the location.
        lon (float): Longitude of the location.
        geoapify_api_key (str): Geoapify API key.

    Returns:
        str: Wheelchair accessibility status ('yes', 'no', 'limited', or 'unknown').
    """
    url = "https://api.geoapify.com/v2/places"
    params = {
        "filter": f"point:{lon},{lat}",
        "conditions": "wheelchair",
        "limit": 1,
        "apiKey": geoapify_api_key,
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        if data.get("features"):
            return data["features"][0]["properties"].get("wheelchair", "unknown")
    return "unknown"


def enrich_with_wheelchair_data(facilities, geoapify_api_key):
    """
    Enrich facilities data with wheelchair accessibility information.

    Args:
        facilities (pd.DataFrame): DataFrame of facilities from Google Places.
        geoapify_api_key (str): Geoapify API key.

    Returns:
        pd.DataFrame: Enriched DataFrame with wheelchair data.
    """
    if facilities.empty:
        return facilities

    wheelchair_data = []
    for _, row in facilities.iterrows():
        wheelchair_status = check_wheelchair_accessibility(
            lat=row["latitude"],
            lon=row["longitude"],
            geoapify_api_key=geoapify_api_key
        )
        wheelchair_data.append(wheelchair_status)

    facilities["wheelchair"] = wheelchair_data
    return facilities

# Main application logic
st.title("Global Healthcare Facility Locator")
location_query = st.text_input("Search by Location:")
radius = st.slider("Search Radius (meters):", min_value=500, max_value=100000, step=1000, value=20000)
care_type = st.selectbox("Type of Care (leave blank to auto-detect):", options=[""] + list(CARE_TYPES.keys()))
open_only = st.checkbox("Show only open facilities")
wheelchair_filter = st.checkbox("Show only wheelchair-accessible places", value=False)

use_current_location = st.button("Use Current Location", key="current_location_button")
latitude = st.number_input("Latitude", value=38.5449)
longitude = st.number_input("Longitude", value=-121.7405)

# Infer care type if issue description is provided
if location_query:
    from geopy.geocoders import Nominatim
    geolocator = Nominatim(user_agent="geoapi")
    location = geolocator.geocode(location_query)
    if location:
        latitude, longitude = location.latitude, location.longitude
        st.write(f"Using location: {location_query} (Latitude: {latitude}, Longitude: {longitude})")
elif use_current_location:
    current_location = get_current_location()
    latitude, longitude = current_location
    st.write(f"Using current location: Latitude {latitude}, Longitude {longitude}")

if st.button("Search", key="search_button"):
    st.write("Fetching data...")
    facilities = fetch_healthcare_data_google(
        latitude=latitude,
        longitude=longitude,
        radius=radius,
        care_type=CARE_TYPES.get(care_type, "hospital"),
        open_only=open_only
    )
    facilities = enrich_with_wheelchair_data(facilities, GEOAPIFY_API_KEY)

    if wheelchair_filter:
        facilities = facilities[facilities["wheelchair"] == "yes"]

    st.session_state["facilities"] = facilities

facilities = st.session_state["facilities"]

# Display Results
if not facilities.empty:
    st.write(f"Found {len(facilities)} facilities.")
    for _, row in facilities.iterrows():
        st.write(f"**{row['name']}** - {row['address']} - Rating: {row['rating']} ⭐ - Wheelchair: {row['wheelchair']}")
else:
    st.warning("No facilities found.")

# Map rendering
if not facilities.empty:
    m = folium.Map(location=[latitude, longitude], zoom_start=12)
    for _, row in facilities.iterrows():
        wheelchair_color = (
            "green" if row["wheelchair"] == "yes"
            else "orange" if row["wheelchair"] == "limited"
            else "red" if row["wheelchair"] == "no"
            else "gray"
        )
        folium.Marker(
            location=[row["latitude"], row["longitude"]],
            popup=f"<b>{row['name']}</b><br>{row['address']}<br>Rating: {row['rating']}<br>Wheelchair: {row['wheelchair']}",
            icon=folium.Icon(color=wheelchair_color),
        ).add_to(m)
    st_folium(m, width=700, height=500)
else:
    st.write("No map to display. Search for facilities to view a map.")

