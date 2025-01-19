import sys
import argparse
import base64
import datetime
import glob
import hashlib
import json
import os
import sqlite3
import struct
import requests
import json
import pandas as pd
import folium
from folium.plugins import AntPath
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cores.pypush_gsa_icloud import icloud_login_mobileme, generate_anisette_headers
import cores.pypush_gsa_icloud

from PySide6 import QtWidgets, QtWebEngineWidgets

from ui.MainWindow import Ui_MainWindow


cores.pypush_gsa_icloud.ANISETTE_URL = "https://ani.sidestore.io"


class AniDialog(QtWidgets.QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Select Anisette Server")

        layout = QtWidgets.QVBoxLayout()
        layout2 = QtWidgets.QHBoxLayout()

        layout2.addWidget(QtWidgets.QLabel("Server URL"))

        # Make urlLineEdit an instance variable
        self.urlLineEdit = QtWidgets.QLineEdit()
        self.urlLineEdit.setText(cores.pypush_gsa_icloud.ANISETTE_URL)
        layout2.addWidget(self.urlLineEdit)

        layout.addLayout(layout2)

        QBtn = QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        buttonBox = QtWidgets.QDialogButtonBox(QBtn)
        layout.addWidget(buttonBox)

        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)
        self.setLayout(layout)

    # Get the value from QLineEdit
    def get_url_value(self):
        return self.urlLineEdit.text()


class FindMyFlipperUi(QtWidgets.QMainWindow):
    def __init__(self):
        super(FindMyFlipperUi, self).__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.args = self.parse_arguments()
        self.privkeys, self.names = self.load_private_keys(self.args.prefix)
        self.sq3db, self.sq3 = self.prepare_database()

        self.ui.actionSelect_Anisette_server.triggered.connect(self.openAniDialog)
        self.ui.updateReports_pushButton.clicked.connect(self.main)
        self.showMaximized()

    def main(self):
        try:
            status_code, res, startdate = self.fetch_reports(self.args, self.names)
            if status_code == 200 and not res:
                print(
                    "No reports have been uploaded yet. Bring your Flipper to a more populated area and try again."
                )
                return

            ordered, found = self.process_reports(
                res, startdate, self.privkeys, self.names, self.sq3
            )
            print(f"{len(ordered)} reports used.")

            self.map_html = self.parseData(ordered)

            self.WEV = QtWebEngineWidgets.QWebEngineView()
            self.ui.map_frame.setLayout(QtWidgets.QVBoxLayout().addWidget(self.WEV))
            self.WEV.resize(self.ui.map_frame.size())  # TODO Propperly display map

            self.WEV.setHtml(self.map_html)
            print("Done!")

            self.sq3db.commit()
            self.sq3db.close()

        except Exception as e:
            print("Error:", e)

    def openAniDialog(self):
        dlg = AniDialog()
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            cores.pypush_gsa_icloud.ANISETTE_URL = dlg.get_url_value()
            print("New Anisette server is: " + cores.pypush_gsa_icloud.ANISETTE_URL)
        else:
            print(
                f"Anisette server didn't change ({cores.pypush_gsa_icloud.ANISETTE_URL})"
            )

    def sha256(self, data):
        digest = hashlib.new("sha256")
        digest.update(data)
        return digest.digest()

    def decrypt(self, enc_data, algorithm_dkey, mode):
        decryptor = Cipher(algorithm_dkey, mode, default_backend()).decryptor()
        return decryptor.update(enc_data) + decryptor.finalize()

    def decode_tag(self, data):
        latitude = struct.unpack(">i", data[0:4])[0] / 10000000.0
        longitude = struct.unpack(">i", data[4:8])[0] / 10000000.0
        confidence = int.from_bytes(data[8:9], "big")
        status = int.from_bytes(data[9:10], "big")
        return {"lat": latitude, "lon": longitude, "conf": confidence, "status": status}

    def getAuth(self, regenerate=False, second_factor="sms"):
        CONFIG_PATH = os.path.dirname(os.path.realpath(__file__)) + "/keys/auth.json"
        if os.path.exists(CONFIG_PATH) and not regenerate:
            with open(CONFIG_PATH, "r") as f:
                j = json.load(f)
        else:
            mobileme = icloud_login_mobileme(second_factor=second_factor)
            j = {
                "dsid": mobileme["dsid"],
                "searchPartyToken": mobileme["delegates"]["com.apple.mobileme"][
                    "service-data"
                ]["tokens"]["searchPartyToken"],
            }
            with open(CONFIG_PATH, "w") as f:
                json.dump(j, f)
        return (j["dsid"], j["searchPartyToken"])

    def parse_arguments(self):
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-H",
            "--hours",
            help="only show reports not older than these hours",
            type=int,
            default=24,
        )
        parser.add_argument(
            "-p",
            "--prefix",
            help="only use keyfiles starting with this prefix",
            default="",
        )
        parser.add_argument(
            "-r", "--regen", help="regenerate search-party-token", action="store_true"
        )
        parser.add_argument(
            "-t",
            "--trusteddevice",
            help="use trusted device for 2FA instead of SMS",
            action="store_true",
        )
        return parser.parse_args()

    def load_private_keys(self, prefix):
        privkeys, names = {}, {}
        for keyfile in glob.glob(
            os.path.dirname(os.path.realpath(__file__)) + f"/keys/{prefix}*.keys"
        ):
            with open(keyfile) as f:
                hashed_adv = priv = ""
                name = os.path.basename(keyfile)[len(prefix) : -5]
                for line in f:
                    key = line.rstrip("\n").split(": ")
                    if key[0] == "Private key":
                        priv = key[1]
                    elif key[0] == "Hashed adv key":
                        hashed_adv = key[1]
                if priv and hashed_adv:
                    privkeys[hashed_adv] = priv
                    names[hashed_adv] = name
                else:
                    print(f"Couldn't find key pair in {keyfile}")
        return privkeys, names

    def prepare_database(self):
        db_path = os.path.dirname(os.path.realpath(__file__)) + "/keys/reports.db"
        sq3db = sqlite3.connect(db_path)
        sq3 = sq3db.cursor()
        sq3.execute(
            """CREATE TABLE IF NOT EXISTS reports (
            id_short TEXT, timestamp INTEGER, datePublished INTEGER, payload TEXT, 
            id TEXT, statusCode INTEGER, lat TEXT, lon TEXT, conf INTEGER,
            PRIMARY KEY(id_short,timestamp));"""
        )
        return sq3db, sq3

    def fetch_reports(self, args, names):
        unixEpoch = int(datetime.datetime.now().timestamp())
        startdate = unixEpoch - (60 * 60 * args.hours)
        data = {
            "search": [
                {
                    "startDate": startdate * 1000,
                    "endDate": unixEpoch * 1000,
                    "ids": list(names.keys()),
                }
            ]
        }

        r = requests.post(
            "https://gateway.icloud.com/acsnservice/fetch",
            auth=self.getAuth(
                regenerate=args.regen,
                second_factor="trusted_device" if args.trusteddevice else "sms",
            ),
            headers=generate_anisette_headers(),
            json=data,
        )
        res = json.loads(r.content.decode()).get("results", [])
        return r.status_code, res, startdate

    def process_reports(self, res, startdate, privkeys, names, sq3):
        ordered, found = [], set()
        for report in res:
            priv = int.from_bytes(
                base64.b64decode(privkeys[report["id"]]), byteorder="big"
            )
            data = base64.b64decode(report["payload"])
            timestamp = int.from_bytes(data[0:4], "big") + 978307200

            if timestamp >= startdate:
                adj = len(data) - 88
                eph_key = ec.EllipticCurvePublicKey.from_encoded_point(
                    ec.SECP224R1(), data[5 + adj : 62 + adj]
                )
                shared_key = ec.derive_private_key(
                    priv, ec.SECP224R1(), default_backend()
                ).exchange(ec.ECDH(), eph_key)
                symmetric_key = self.sha256(
                    shared_key + b"\x00\x00\x00\x01" + data[5 + adj : 62 + adj]
                )
                decryption_key, iv = symmetric_key[:16], symmetric_key[16:]
                enc_data, auth_tag = data[62 + adj : 72 + adj], data[72 + adj :]

                decrypted = self.decrypt(
                    enc_data, algorithms.AES(decryption_key), modes.GCM(iv, auth_tag)
                )
                tag = self.decode_tag(decrypted)
                tag.update(
                    {
                        "timestamp": timestamp,
                        "isodatetime": datetime.datetime.fromtimestamp(
                            timestamp
                        ).isoformat(),
                        "key": names[report["id"]],
                        "goog": f"https://maps.google.com/maps?q={tag['lat']},{tag['lon']}",
                    }
                )
                found.add(tag["key"])
                ordered.append(tag)

                query = (
                    "INSERT OR REPLACE INTO reports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                )
                parameters = (
                    names[report["id"]],
                    timestamp,
                    report["datePublished"],
                    report["payload"],
                    report["id"],
                    report["statusCode"],
                    str(tag["lat"]),
                    str(tag["lon"]),
                    tag["conf"],
                )
                sq3.execute(query, parameters)
        return ordered, found

    def parseData(self, data):
        """
        Processes and visualizes location data on an interactive map.

        This method sorts the provided location data by timestamp, calculates
        time differences between consecutive data points, and generates an
        interactive map using Folium. The map includes paths and markers for
        each location ping, displaying timestamps and indicating start and end points.

        Parameters:
        data (list): A list of dictionaries containing location information,
                    each with keys like 'timestamp', 'isodatetime', 'lat', and 'lon'.

        Returns:
        str: Rendered HTML of the interactive map if data is available,
            otherwise prints a message indicating no data.
        """

        def format_time(seconds):
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            seconds = seconds % 60
            return f"{int(hours)}h {int(minutes)}m {int(seconds)}s"

        sorted_data = sorted(data, key=lambda x: x["timestamp"])

        df = pd.DataFrame(sorted_data)

        df["datetime"] = pd.to_datetime(df["isodatetime"])
        df["time_diff"] = df["datetime"].diff().dt.total_seconds()
        average_time_diff = df["time_diff"][1:].mean()
        time_diff_total = (
            df.iloc[-1]["datetime"] - df.iloc[0]["datetime"]
        ).total_seconds()

        formatted_total_time = format_time(time_diff_total)
        formatted_avg_time = format_time(average_time_diff)

        start_timestamp = df.iloc[0]["datetime"].strftime("%Y-%m-%d %H:%M:%S")
        simple_start_timestamp = df.iloc[0]["datetime"].strftime("%m-%d-%y")
        end_timestamp = df.iloc[-1]["datetime"].strftime("%Y-%m-%d %H:%M:%S")

        ping_count = df.shape[0]

        # sanity check before plotting
        if not df.empty:
            map_center = [df.iloc[0]["lat"], df.iloc[0]["lon"]]
            m = folium.Map(location=map_center, zoom_start=13)

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
            <h3 align="center" style="font-size:20px; margin-top:10px;"><b>FindMy Flipper Location Mapper</b></h3>
            <div style="position: fixed; bottom: 50px; left: 50px; width: 300px; height: 160px; z-index:9999; font-size:14px; background-color: white; padding: 10px; border-radius: 10px; box-shadow: 0 0 5px rgba(0,0,0,0.5);">
            <b>Location Summary</b><br>
            Start: {start_timestamp}<br>
            End: {end_timestamp}<br>
            Number of Location Pings: {ping_count}<br>
            Total Time: {formatted_total_time}<br>
            Average Time Between Pings: {formatted_avg_time}<br>
            Created by Matthew KuKanich and luu176<br>
            </div>
            """
            m.get_root().html.add_child(folium.Element(title_and_info_html))

            base_filename = f"LocationMap_{simple_start_timestamp}"
            extension = "html"
            counter = 1
            filename = f"{base_filename}.{extension}"
            while os.path.exists(filename):
                filename = f"{base_filename}_{counter}.{extension}"
                counter += 1

            return m.get_root().render()  # return HTML data

        else:
            print("No data available to plot.")
            # TODO add exception handling
            return None


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    widget = FindMyFlipperUi()
    sys.exit(app.exec())
