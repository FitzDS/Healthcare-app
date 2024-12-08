import streamlit as st
import pandas as pd
import requests
import os
import geocoder
from streamlit_folium import st_folium
import folium

# Load API keys directly from the code for now (replace with secrets later)
GEOAPIFY_API_KEY = "f01884465c8743a9a1d805d1c778e7af"
GOOGLE_API_KEY = "AIzaSyBIghdeoXzo-XYY1mJkeIezTDPhr6WAHgM"

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
                "rating": properties.get("rating", "N/A"),
                "user_ratings_total": properties.get("user_ratings_total", 0),
            }
            facilities.append(facility)
        return pd.DataFrame(facilities)
    else:
        st.error(f"Error fetching data from Geoapify: {response.status_code}")
        return pd.DataFrame()

def get_travel_time_distance(origin, destination):
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": f"{origin[0]},{origin[1]}",
        "destinations": f"{destination[0]},{destination[1]}",
        "key": GOOGLE_API_KEY,
        "mode": "driving",
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        if "rows" in data and len(data["rows"]) > 0:
            elements = data["rows"][0].get("elements", [])
            if elements and elements[0].get("status") == "OK":
                return elements[0]["distance"]["text"], elements[0]["duration"]["text"]
    return "N/A", "N/A"

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

# Input options
location_query = st.text_input("Search by Location:")
use_current_location = st.button("Use Current Location", key="current_location_button")
latitude = st.number_input("Latitude", value=38.5449)
longitude = st.number_input("Longitude", value=-121.7405)
radius = st.slider("Search Radius (meters):", min_value=500, max_value=200000, step=1000, value=20000)
care_type = st.selectbox("Type of Care:", options=list(CARE_TYPES.keys()))

# Debugging outputs
st.write("Debug Info:")
st.write(f"Latitude: {latitude}, Longitude: {longitude}, Radius: {radius}")

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

# Default map preview
st.write("Default Map Preview:")
default_map = folium.Map(location=[latitude, longitude], zoom_start=12)
folium.Marker(
    location=[latitude, longitude],
    popup="Current Location",
    icon=folium.Icon(color="red")
).add_to(default_map)
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

if st.button("Search", key="search_button"):
    st.write("Fetching data...")
    facilities = fetch_healthcare_data(latitude, longitude, radius, CARE_TYPES[care_type])

    if facilities.empty:
        st.error("No facilities found. Check your API key, location, or radius.")
    else:
        st.write(f"Found {len(facilities)} facilities.")

        # Create map with results
        m = folium.Map(location=[latitude, longitude], zoom_start=12)

        folium.Circle(
            location=[latitude, longitude],
            radius=radius,
            color="blue",
            fill=True,
            fill_opacity=0.4
        ).add_to(m)

        for _, row in facilities.iterrows():
            destination = (row["latitude"], row["longitude"])
            distance, duration = get_travel_time_distance((latitude, longitude), destination)

            popup_content = (
                f"<b>{row['name']}</b><br>"
                f"Address: {row['address']}<br>"
                f"Rating: {row['rating']} ({row['user_ratings_total']} reviews)<br>"
                f"Distance: {distance}<br>"
                f"Travel Time: {duration}<br>"
                f"<a href='https://www.google.com/maps/dir/?api=1&origin={latitude},{longitude}&destination={row['latitude']},{row['longitude']}' target='_blank'>Get Directions</a>"
            )

            folium.Marker(
                location=[row["latitude"], row["longitude"]],
                popup=popup_content,
            ).add_to(m)

        # Render map with results
        st_folium(m, width=700, height=500)

        # Show data in a table
        st.dataframe(facilities)
