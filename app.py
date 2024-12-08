import streamlit as st
import pandas as pd
import requests
import os
import geocoder
from streamlit_folium import st_folium
import folium

# Load API keys directly from the code for now (replace with secrets later)
GEOAPIFY_API_KEY = "your_geoapify_api_key"
GOOGLE_API_KEY = "your_google_api_key"

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

def fetch_ratings_for_existing_places(facilities_df):
    """
    Fetch ratings from Google Places API for facilities fetched using Geoapify.
    :param facilities_df: DataFrame containing facilities from Geoapify.
    :return: DataFrame with ratings added (if available).
    """
    updated_facilities = []

    for _, facility in facilities_df.iterrows():
        url = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
        params = {
            'input': facility['name'],  # Search by facility name
            'inputtype': 'textquery',
            'fields': 'rating,user_ratings_total',  # Fetch rating and review count
            'locationbias': f"point:{facility['latitude']},{facility['longitude']}",
            'key': GOOGLE_API_KEY
        }

        response = requests.get(url, params=params)

        if response.status_code == 200:
            data = response.json()
            if data.get('candidates'):
                # If ratings are found, update the facility's information
                candidate = data['candidates'][0]
                facility['rating'] = candidate.get('rating', 'N/A')
                facility['user_ratings_total'] = candidate.get('user_ratings_total', 0)
            else:
                # If no ratings found, set to 'N/A'
                facility['rating'] = 'N/A'
                facility['user_ratings_total'] = 0
        else:
            st.error(f"Error fetching ratings for {facility['name']}: {response.status_code}")
            facility['rating'] = 'N/A'
            facility['user_ratings_total'] = 0

        updated_facilities.append(facility)

    return pd.DataFrame(updated_facilities)

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
    return [38.5449, -121.7405]  # Default to Davis, CA

st.title("Healthcare Facility Locator")

# Input options (Search above the map)
location_query = st.text_input("Search by Location:")
use_current_location = st.button("Use Current Location", key="current_location_button")
latitude = st.number_input("Latitude", value=38.5449)
longitude = st.number_input("Longitude", value=-121.7405)
radius = st.slider("Search Radius (meters):", min_value=500, max_value=200000, step=1000, value=20000)
care_type = st.selectbox("Type of Care:", options=list(CARE_TYPES.keys()))

# Handle location query
if location_query:
    lat, lon = get_lat_lon_from_query(location_query)
    if lat and lon:
        latitude = lat
        longitude = lon
        st.write(f"Using location: {location_query} (Latitude: {latitude}, Longitude: {longitude})")

# Handle current location button
if use_current_location:
    current_location = get_current_location()
    latitude = current_location[0]
    longitude = current_location[1]
    st.write(f"Using current location: Latitude {latitude}, Longitude {longitude}")

# Render map from session state or display default map
if st.button("Search", key="search_button"):
    st.write("Fetching data...")
    facilities = fetch_healthcare_data(latitude, longitude, radius, CARE_TYPES[care_type])

    if facilities.empty:
        st.error("No facilities found. Check your API key, location, or radius.")
        st.session_state["map"] = folium.Map(location=[latitude, longitude], zoom_start=12)
        st.session_state["facilities"] = pd.DataFrame()
    else:
        st.write(f"Found {len(facilities)} facilities.")
        facilities_with_ratings = fetch_ratings_for_existing_places(facilities)
        st.session_state["facilities"] = facilities_with_ratings

        # Create map
        m = folium.Map(location=[latitude, longitude], zoom_start=12)
        folium.Circle(
            location=[latitude, longitude],
            radius=radius,
            color="blue",
            fill=True,
            fill_opacity=0.4
        ).add_to(m)

        for _, row in facilities_with_ratings.iterrows():
            # Determine marker color based on rating
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
                f"<a href='https://www.google.com/maps/dir/?api=1&origin={latitude},{longitude}&destination={row['latitude']},{row['longitude']}' target='_blank'>Get Directions</a>"
            )

            folium.Marker(
                location=[row["latitude"], row["longitude"]],
                popup=popup_content,
                icon=folium.Icon(color=marker_color)
            ).add_to(m)

        st.session_state["map"] = m

if "map" in st.session_state and st.session_state["map"] is not None:
    st_folium(st.session_state["map"], width=700, height=500)
else:
    default_map = folium.Map(location=[latitude, longitude], zoom_start=12)
folium.Marker(
        location=[latitude, longitude],
        popup="Current Location",
        icon=folium.Icon(color="red")
    ).add_to(default_map)
    folium.Circle(
        location=[latitude, longitude],
        radius=radius,
        color="blue",
        fill=True,
        fill_opacity=0.4
    ).add_to(default_map)
    st_folium(default_map, width=700, height=500)

# Show data in a table if facilities exist
if "facilities" in st.session_state and not st.session_state["facilities"].empty:
    st.dataframe(st.session_state["facilities"])
