"""Stream type classes for tap-lightspeed."""

from typing import Optional, Any, Dict, Iterable
import requests
from singer_sdk import typing as th
from tap_r_lightspeed.client import LightspeedRSeriesStream


class AccountStream(LightspeedRSeriesStream):
    """Custom Account stream for Lightspeed R-Series API."""
    
    name = "account"
    path = "/Account.json"
    primary_keys = ["accountID"]
    replication_key = None  # Account doesn't change, no replication needed
    
    # Account endpoint returns a single object, not an array
    # We'll handle this in parse_response
    records_jsonpath = "$.Account"
    
    schema = th.PropertiesList(
        th.Property(
            "accountID",
            th.StringType,
            required=True,
            description="The account ID for the Lightspeed R-Series account",
        ),
        th.Property(
            "name",
            th.StringType,
            required=True,
            description="The name of the account",
        ),
        th.Property(
            "link",
            th.ObjectType(
                th.Property(
                    "@attributes",
                    th.ObjectType(
                        th.Property(
                            "href",
                            th.StringType,
                            description="The API href for this account resource",
                        ),
                    ),
                ),
            ),
            description="Link object containing the API href for this account",
        ),
    ).to_dict()
