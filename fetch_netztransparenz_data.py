"""
fetch_netztransparenz_data.py

Pulls historical redispatch or curtailment data from the netztransparenz.de API
and exports annual CSV files.
"""

import io
import os
import time

import pandas as pd
import requests

# Configuration
CLIENT_ID = os.environ.get("NETZTRANSPARENZ_CLIENT_ID", "YOUR_CLIENT_ID_HERE")
CLIENT_SECRET = os.environ.get("NETZTRANSPARENZ_CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE")

ENDPOINT = "redispatch"  # Options: "redispatch", "AusgewieseneABSM"
START_YEAR = 2014
END_YEAR = 2019

TOKEN_URL = "https://identity.netztransparenz.de/users/connect/token"
BASE_URL = "https://ds.netztransparenz.de/api/v1/data"


def get_access_token() -> str:
    """Exchange Client ID and Client Secret for a OAuth access token."""
    payload = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    resp = requests.post(
        TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    if resp.status_code != 200:
        print("Token request failed.")
        print("Status code:", resp.status_code)
        print("Response body:", resp.text)
        resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_range(endpoint: str, date_from: str, date_to: str, token: str) -> pd.DataFrame:
    """Fetch data for a given date range and return it as a pandas DataFrame."""
    url = f"{BASE_URL}/{endpoint}"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"dateFrom": date_from, "dateTo": date_to}

    resp = requests.get(url, headers=headers, params=params, timeout=60)
    if resp.status_code != 200:
        print(f"Data request failed for {date_from} - {date_to}")
        print("Status code:", resp.status_code)
        print("Response body:", resp.text[:1000])
        resp.raise_for_status()

    df = pd.read_csv(io.StringIO(resp.text), sep=";", decimal=",")
    return df


def main():
    if CLIENT_ID == "YOUR_CLIENT_ID_HERE" or CLIENT_SECRET == "YOUR_CLIENT_SECRET_HERE":
        raise SystemExit(
            "Please set NETZTRANSPARENZ_CLIENT_ID and NETZTRANSPARENZ_CLIENT_SECRET credentials before running."
        )

    token = get_access_token()
    print("Got access token.")

    for year in range(START_YEAR, END_YEAR + 1):
        date_from = f"{year}-01-01T00:00:00"
        date_to = f"{year}-12-31T23:59:59"

        print(f"Fetching {ENDPOINT} for {year} ...")
        try:
            df = fetch_range(ENDPOINT, date_from, date_to, token)
        except requests.HTTPError as e:
            print(f"  Failed for {year}: {e}")
            continue

        if df.empty:
            print(f"  No data returned for {year}.")
            continue

        out_path = f"{ENDPOINT}_{year}.csv"
        df.to_csv(out_path, index=False)
        print(f"  Saved {len(df)} rows to {out_path}")

        time.sleep(1)

    print("Done.")


if __name__ == "__main__":
    main()