import json
import pandas as pd
import folium
from folium.plugins import AntPath
from datetime import datetime
import os


def format_time(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    return f"{int(hours)}h {int(minutes)}m {int(seconds)}s"


def process_location_data(file_path):
    with open(file_path, "r") as file:
        data = json.load(file)

    sorted_data = sorted(data, key=lambda x: x["timestamp"])
    df = pd.DataFrame(sorted_data)

    df["datetime"] = pd.to_datetime(df["isodatetime"])
    df["time_diff"] = df["datetime"].diff().dt.total_seconds()

    if df.empty:
        return {"error": "No data available to process."}

    average_time_diff = df["time_diff"][1:].mean()
    time_diff_total = (df.iloc[-1]["datetime"] - df.iloc[0]["datetime"]).total_seconds()

    formatted_total_time = format_time(time_diff_total)
    formatted_avg_time = format_time(average_time_diff)

    start_timestamp = df.iloc[0]["datetime"].strftime("%Y-%m-%d %H:%M:%S")
    simple_start_timestamp = df.iloc[0]["datetime"].strftime("%m-%d-%y")
    end_timestamp = df.iloc[-1]["datetime"].strftime("%Y-%m-%d %H:%M:%S")

    ping_count = df.shape[0]

    return {
        "df": df,
        "start_timestamp": start_timestamp,
        "end_timestamp": end_timestamp,
        "simple_start_timestamp": simple_start_timestamp,
        "ping_count": ping_count,
        "formatted_total_time": formatted_total_time,
        "formatted_avg_time": formatted_avg_time,
    }


def generate_map(
    df,
    start_timestamp,
    end_timestamp,
    ping_count,
    formatted_total_time,
    formatted_avg_time,
    simple_start_timestamp,
    save,
):
    map_center = [df.iloc[0]["lat"], df.iloc[0]["lon"]]
    m = folium.Map(
        location=map_center,
        zoom_start=13,
        tiles="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        attr="&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors &copy; <a href='https://carto.com/'>CARTO</a>",
    )

    latlon_pairs = list(zip(df["lat"], df["lon"]))
    ant_path = AntPath(
        locations=latlon_pairs,
        dash_array=[10, 20],
        delay=1000,
        color="red",
        weight=5,
        pulse_color="black",
    )
    m.add_child(ant_path)

    # Location markers look good, click to see timestamp
    for index, row in df.iterrows():
        if index == 0:  # First marker
            folium.Marker(
                [row["lat"], row["lon"]],
                popup=f"Timestamp: {row['isodatetime']} Start Point",
                tooltip=f"Start Point",
                icon=folium.Icon(color="green"),
            ).add_to(m)
        elif index == len(df) - 1:  # Last marker
            folium.Marker(
                [row["lat"], row["lon"]],
                popup=f"Timestamp: {row['isodatetime']} End Point",
                tooltip=f"End Point",
                icon=folium.Icon(color="red"),
            ).add_to(m)
        else:  # Other markers
            folium.Marker(
                [row["lat"], row["lon"]],
                popup=f"Timestamp: {row['isodatetime']}",
                tooltip=f"Point {index+1}",
            ).add_to(m)

    title_and_info_html = f"""
<body style="background-color: #121212; color: white;">

    <h3 align="center" style="font-size:20px; margin-top:10px; color: white;"><b>FindMy Flipper Location Mapper</b></h3>
    <div style="position: fixed; bottom: 50px; left: 50px; width: 300px; height: 160px; z-index:9999; font-size:14px; background-color: #2e2e2e; padding: 10px; border-radius: 10px; box-shadow: 0 0 5px rgba(0,0,0,0.5); color: white;">
        <b>Location Summary</b><br>
        Start: {start_timestamp}<br>
        End: {end_timestamp}<br>
        Number of Location Pings: {ping_count}<br>
        Total Time: {formatted_total_time}<br>
        Average Time Between Pings: {formatted_avg_time}<br>
        Created by Matthew KuKanich and luu176<br>
    </div>

</body>

     """
    m.get_root().html.add_child(folium.Element(title_and_info_html))
    if save:
        base_filename = f"LocationMap_{simple_start_timestamp}"
        extension = "html"
        counter = 1
        filename = f"{base_filename}.{extension}"
        while os.path.exists(filename):
            filename = f"{base_filename}_{counter}.{extension}"
            counter += 1

        m.save(filename)
    return m.get_root().render()  # Return HTML


def main(file_path, save=True):
    location_data = process_location_data(file_path)

    if "error" in location_data:
        return None

    df = location_data["df"]
    html = generate_map(
        df,
        location_data["start_timestamp"],
        location_data["end_timestamp"],
        location_data["ping_count"],
        location_data["formatted_total_time"],
        location_data["formatted_avg_time"],
        location_data["simple_start_timestamp"],
        save=save,
    )

    return html


# Example usage
# if __name__ == "__main__":
#     result = main("data.json")
#     print(result)
