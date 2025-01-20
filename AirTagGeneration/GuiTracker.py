import sys
import os
import json
from types import SimpleNamespace
import datetime
import requests
from getpass import getpass
import plistlib as plist
import base64

import cores.pypush_gsa_icloud
import RequestReportMap as RRM
from cores.pypush_gsa_icloud import (
    generate_anisette_headers,
    srp,
    gsa_authenticated_request,
    encrypt_password,
    decrypt_cbc,
    trusted_second_factor,
)

from PySide6 import QtWidgets, QtWebEngineWidgets, QtGui
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

        self.args = SimpleNamespace()
        self.args.hours = 24
        self.args.prefix = ""
        self.args.regen = False
        self.args.trusteddevice = False  # TODO add ui for changing these

        self.ui.actionSelect_Anisette_server.triggered.connect(self.openAniDialog)
        self.ui.updateReports_pushButton.clicked.connect(self.main)
        self.showMaximized()

    def main(self):
        privkeys, names = RRM.load_key_files(self.args.prefix)
        response, startdate = self.fetch_reports(self.args, names)
        if response.status_code == 200:
            ordered, found = RRM.process_reports(response, startdate, privkeys, names)
            print(f"{len(ordered)} reports used.")
            self.setStatusTip(f"{len(ordered)} reports used.")
            ordered.sort(key=lambda item: item.get("timestamp"))
            for rep in ordered:
                print(rep)

            RRM.export_data(ordered)
            maphtml = RRM.generate_map()

            web_view = QtWebEngineWidgets.QWebEngineView()
            web_view.setHtml(maphtml)

            frame_layout = QtWidgets.QVBoxLayout()
            self.ui.map_frame.setLayout(frame_layout)
            frame_layout.addWidget(web_view)

            missing = [key for key in names.values() if key not in found]
            print(f"found: {list(found)}")
            print(f"missing: {missing}")

        else:
            print("Failed to fetch reports. Status code:", response.status_code)

    def openAniDialog(self):
        dlg = AniDialog()
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            cores.pypush_gsa_icloud.ANISETTE_URL = dlg.get_url_value()
            print("New Anisette server is: " + cores.pypush_gsa_icloud.ANISETTE_URL)
        else:
            print(
                f"Anisette server didn't change ({cores.pypush_gsa_icloud.ANISETTE_URL})"
            )

    ######### Modified functions #########
    # Methods below are modified to work with PySide6

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

        response = requests.post(
            "https://gateway.icloud.com/acsnservice/fetch",
            auth=self.getAuth(
                regenerate=args.regen,
                second_factor="trusted_device" if args.trusteddevice else "sms",
            ),
            headers=generate_anisette_headers(),
            json=data,
        )
        return response, startdate

    def getAuth(self, regenerate=False, second_factor="sms"):
        CONFIG_PATH = os.path.dirname(os.path.realpath(__file__)) + "/keys/auth.json"
        if os.path.exists(CONFIG_PATH) and not regenerate:
            with open(CONFIG_PATH, "r") as f:
                j = json.load(f)
        else:
            mobileme = self.icloud_login_mobileme(second_factor=second_factor)
            j = {
                "dsid": mobileme["dsid"],
                "searchPartyToken": mobileme["delegates"]["com.apple.mobileme"][
                    "service-data"
                ]["tokens"]["searchPartyToken"],
            }
            with open(CONFIG_PATH, "w") as f:
                json.dump(j, f)
        return (j["dsid"], j["searchPartyToken"])

    def icloud_login_mobileme(self, username="", password="", second_factor="sms"):
        if not username:
            user_input, ok = QtWidgets.QInputDialog.getText(self, "Login", "Apple ID")
            if ok and user_input:
                username = user_input
                print(f"Apple ID: {username}")
            else:
                ...  # TODO Handle pressing cancel
        if not password:
            user_input, ok = QtWidgets.QInputDialog.getText(
                self, "Login", "Password", echo=QtWidgets.QLineEdit.EchoMode.Password
            )
            if ok and user_input:
                password = user_input
                print(f"Password submitted: {password!=""}")
            else:
                ...  # TODO Handle pressing cancel

        g = self.gsa_authenticate(username, password, second_factor)
        pet = g["t"]["com.apple.gs.idms.pet"]["token"]
        adsid = g["adsid"]

        data = {
            "apple-id": username,
            "delegates": {"com.apple.mobileme": {}},
            "password": pet,
            "client-id": str(cores.pypush_gsa_icloud.USER_ID),
        }
        data = plist.dumps(data)

        headers = {
            "X-Apple-ADSID": adsid,
            "User-Agent": "com.apple.iCloudHelper/282 CFNetwork/1408.0.4 Darwin/22.5.0",
            "X-Mme-Client-Info": "<MacBookPro18,3> <Mac OS X;13.4.1;22F8> <com.apple.AOSKit/282 (com.apple.accountsd/113)>",
        }
        headers.update(generate_anisette_headers())

        r = requests.post(
            "https://setup.icloud.com/setup/iosbuddy/loginDelegates",
            auth=(username, pet),
            data=data,
            headers=headers,
            verify=False,
        )

        return plist.loads(r.content)

    def gsa_authenticate(self, username, password, second_factor="sms"):
        # Password is None as we'll provide it later
        usr = srp.User(username, bytes(), hash_alg=srp.SHA256, ng_type=srp.NG_2048)
        _, A = usr.start_authentication()

        r = gsa_authenticated_request(
            {"A2k": A, "ps": ["s2k", "s2k_fo"], "u": username, "o": "init"}
        )
        if "sp" not in r:
            print("Authentication Failed. Check your Apple ID and password.")
            raise Exception("AuthenticationError")
        if r["sp"] != "s2k" and r["sp"] != "s2k_fo":
            print(
                f"This implementation only supports s2k and s2k_fo. Server returned {r['sp']}"
            )
            return

        # Change the password out from under the SRP library, as we couldn't calculate it without the salt.
        usr.p = encrypt_password(password, r["s"], r["i"], r["sp"] == "s2k_fo")

        M = usr.process_challenge(r["s"], r["B"])

        # Make sure we processed the challenge correctly
        if M is None:
            print("Failed to process challenge")
            return

        r = gsa_authenticated_request(
            {"c": r["c"], "M1": M, "u": username, "o": "complete"}
        )

        # Make sure that the server's session key matches our session key (and thus that they are not an imposter)
        usr.verify_session(r["M2"])
        if not usr.authenticated():
            print("Failed to verify session")
            return

        spd = decrypt_cbc(usr, r["spd"])
        # For some reason plistlib doesn't accept it without the header...
        PLISTHEADER = b"""\
    <?xml version='1.0' encoding='UTF-8'?>
    <!DOCTYPE plist PUBLIC '-//Apple//DTD PLIST 1.0//EN' 'http://www.apple.com/DTDs/PropertyList-1.0.dtd'>
    """
        spd = plist.loads(PLISTHEADER + spd)

        if "au" in r["Status"] and r["Status"]["au"] in [
            "trustedDeviceSecondaryAuth",
            "secondaryAuth",
        ]:
            print("2FA required, requesting code")
            # Replace bytes with strings
            for k, v in spd.items():
                if isinstance(v, bytes):
                    spd[k] = base64.b64encode(v).decode()
            if second_factor == "sms":
                self.sms_second_factor(spd["adsid"], spd["GsIdmsToken"])
            elif second_factor == "trusted_device":
                trusted_second_factor(
                    spd["adsid"], spd["GsIdmsToken"]
                )  # TODO Implement (maybe)
            return self.gsa_authenticate(username, password)
        elif "au" in r["Status"]:
            print(f"Unknown auth value {r['Status']['au']}")
            return
        else:
            return spd

    def sms_second_factor(self, dsid, idms_token):
        identity_token = base64.b64encode((dsid + ":" + idms_token).encode()).decode()

        # TODO: Actually do this request to get user prompt data
        # a = requests.get("https://gsa.apple.com/auth", verify=False)
        # This request isn't strictly necessary though,
        # and most accounts should have their id 1 SMS, if not contribute ;)

        headers = {
            "User-Agent": "Xcode",
            "Accept-Language": "en-us",
            "X-Apple-Identity-Token": identity_token,
            "X-Apple-App-Info": "com.apple.gs.xcode.auth",
            "X-Xcode-Version": "11.2 (11B41)",
            "X-Mme-Client-Info": "<MacBookPro18,3> <Mac OS X;13.4.1;22F8> <com.apple.AOSKit/282 (com.apple.dt.Xcode/3594.4.19)>",
        }

        headers.update(generate_anisette_headers())

        # TODO: Actually get the correct id, probably in the above GET
        body = {"phoneNumber": {"id": 1}, "mode": "sms"}

        # This will send the 2FA code to the user's phone over SMS
        # We don't care about the response, it's just some HTML with a form for entering the code
        # Easier to just use a text prompt
        t = requests.put(
            "https://gsa.apple.com/auth/verify/phone/",
            json=body,
            headers=headers,
            verify=False,
            timeout=5,
        )

        # Prompt for the 2FA code. It's just a string like '123456', no dashes or spaces
        code = None
        user_input, ok = QtWidgets.QInputDialog.getText(self, "Login", "2FA code")
        if ok and user_input:
            code = user_input
            print(f"2FA code submitted: {code!=""}")
        else:
            ...  # TODO Handle pressing cancel

        body["securityCode"] = {"code": code}

        # Send the 2FA code to Apple
        resp = requests.post(
            "https://gsa.apple.com/auth/verify/phone/securitycode",
            json=body,
            headers=headers,
            verify=False,
            timeout=5,
        )
        if resp.ok:
            print("2FA successful")


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    widget = FindMyFlipperUi()
    sys.exit(app.exec())
