import json
from datetime import date, datetime, timedelta

import pandas as pd
import requests
from flask import g

import src.config as config

BIDDERS = {}


def check_outputs(frame):
    """check frame contains these columns:
    hour_ID, applying_date, volume, price, type
    """
    assert isinstance(frame, pd.DataFrame), f"expect pd.Dataframe, got: {type(frame)}"
    for col in ["hour_ID", "applying_date", "volume", "price", "type"]:
        assert col in frame.columns, f"missing column: {col}"


def parse_data(data, kwargs):
    """query the database for data to feed into the bidder function"""
    assert isinstance(data, dict), f"expect a `dict`, got: {type(data)}"
    parsed_data = {}
    conn = g.get_conn()
    resolved_kwargs = {k: v() if callable(v) else v for k, v in kwargs.items()}
    for key, query in data.items():
        parsed_data[key] = pd.read_sql(query.format(**resolved_kwargs), conn)
    return parsed_data


def register_bidder(name, *, args={}, data=None, default=False):
    """function wrapper to register and pre-process the bidder functions"""

    def wrapper(fn):
        def bidder_function(**kwargs):
            """bidding procedure:
            1. query database for data
            2. run defined function
            3. place bids via RSE API
            """
            parsed_data = parse_data(data, args)
            outputs = fn(**parsed_data, **args, **kwargs)
            check_outputs(outputs)
            resp = place_orders(outputs)
            return resp

        # register bidder function
        BIDDERS[name] = bidder_function
        if default:
            assert "default" not in BIDDERS, "duplicated `default`"
            BIDDERS["default"] = bidder_function
        return fn

    return wrapper


# make predictions 2 days ahead so that the bids are accepted
def get_output_template(dt: date = None):
    """Create an empty output DataFrame with following columns:

    hour_ID: int (1-24)
    applying_date: str, (YYYY-MM-DD)
    volume: float
    price: float
    type: str (BUY or SELL)

    the time range is 24-H from 9AM of given date to the next morning at 8AM
    """
    if dt is None:
        dt = date.today() + timedelta(days=1)
    cols = ["hour_ID", "applying_date", "volume", "price", "type"]
    # create template
    data = [(hour, dt, 0.0, 0.0, "BUY") for hour in range(1, 25)]
    df = pd.DataFrame(data=data, columns=cols)
    df["applying_date"] = df["applying_date"].map(lambda d: d.isoformat())
    return df


def place_orders(orders: pd.DataFrame) -> bool:
    """set bids via RSE API"""

    url = f"http://{config.AIMLAC_RSE_ADDR}/auction/bidding/set"
    key = config.AIMLAC_RSE_KEY
    orders = json.loads(orders.to_json(orient="records"))

    resp = requests.post(url, json=dict(key=key, orders=orders))
    return resp
