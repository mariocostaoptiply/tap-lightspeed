"""Lightspeed tap class."""

from typing import List

from singer_sdk import Stream, Tap
from singer_sdk import typing as th

from tap_x_lightspeed.streams import (
    ProductsStream,
    InventoryStream,
    SuppliersStream,
    SalesStream,
    OutletsStream,
    ConsignmentsStream,
    ConsignmentProductsStream,
)

STREAM_TYPES = [
    ProductsStream,
    InventoryStream,
    SuppliersStream,
    SalesStream,
    OutletsStream,
    ConsignmentsStream,
    ConsignmentProductsStream,
]


class TapXLightspeed(Tap):
    """TapXLightspeed Retail (X-Series) tap class."""

    def __init__(
        self,
        config=None,
        catalog=None,
        state=None,
        parse_env_config=False,
        validate_config=True,
    ) -> None:
        """Initialize the tap.
        
        Stores config_file path to allow auth.py to save tokens back to config.
        """
        self.config_file = config[0] if config else None
        super().__init__(config, catalog, state, parse_env_config, validate_config)

    name = "tap-lightspeed"

    config_jsonschema = th.PropertiesList(
        th.Property(
            "domain_prefix",
            th.StringType,
            required=True,
            description=(
                "The retailer's domain prefix for Lightspeed X-Series API. "
                "This is the subdomain part of the retailer's URL "
                "(e.g., 'mystore' for mystore.retail.lightspeed.app)"
            ),
        ),
        th.Property(
            "client_id",
            th.StringType,
            required=True,
            description="Your Lightspeed X-Series application's client ID",
        ),
        th.Property(
            "client_secret",
            th.StringType,
            required=True,
            description="Your Lightspeed X-Series application's client secret",
        ),
        th.Property(
            "refresh_token",
            th.StringType,
            required=True,
            description=(
                "OAuth2 refresh token for Lightspeed X-Series API. "
                "This is obtained during the initial OAuth authorization flow."
            ),
        ),
        th.Property(
            "access_token",
            th.StringType,
            required=False,
            description=(
                "OAuth2 access token for Lightspeed X-Series API. "
                "This is optional and will be automatically refreshed if not provided or expired."
            ),
        ),
        th.Property(
            "start_date",
            th.DateTimeType,
            required=False,
            description=(
                "Note: This field is not used for Lightspeed X-Series API. "
                "The API only supports version-based pagination, not date-based filtering. "
                "Incremental replication uses version numbers stored in state bookmarks."
            ),
        ),
        th.Property(
            "throttle_seconds",
            th.NumberType,
            required=False,
            description=(
                "Number of seconds to wait between API requests to avoid rate limiting. "
                "Default: 1.0 seconds if not specified"
            ),
        ),
    ).to_dict()

    def discover_streams(self) -> List[Stream]:
        """Return a list of discovered streams."""

        return [stream_class(tap=self) for stream_class in STREAM_TYPES]


if __name__ == "__main__":
    TapXLightspeed.cli()
