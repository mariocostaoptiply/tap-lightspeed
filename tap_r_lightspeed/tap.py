"""Lightspeed tap class."""

from typing import List

from singer_sdk import Stream, Tap
from singer_sdk import typing as th

from tap_r_lightspeed.streams import (
    AccountStream,
    ItemStream,
    VendorStream,
    OrderStream,
    SaleStream,
    ShipmentStream,
)

STREAM_TYPES = [
    AccountStream,
    ItemStream,
    VendorStream,
    OrderStream,
    SaleStream,
    ShipmentStream,
]


class TapRLightspeed(Tap):
    """TapRLightspeed Retail (R-Series) tap class."""

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
            "client_id",
            th.StringType,
            required=True,
            description=(
                "Your Lightspeed R-Series application's client ID. "
                "Obtained by registering your application at "
                "https://cloud.lightspeedapp.com/oauth/register.php"
            ),
        ),
        th.Property(
            "client_secret",
            th.StringType,
            required=True,
            description=(
                "Your Lightspeed R-Series application's client secret. "
                "Obtained during application registration."
            ),
        ),
        th.Property(
            "refresh_token",
            th.StringType,
            required=True,
            description=(
                "OAuth2 refresh token for Lightspeed R-Series API. "
                "This is obtained during the initial OAuth authorization flow. "
                "See: https://developers.lightspeedhq.com/retail/authentication/refresh-token/"
            ),
        ),
        th.Property(
            "access_token",
            th.StringType,
            required=False,
            description=(
                "OAuth2 access token for Lightspeed R-Series API. "
                "This is optional and will be automatically refreshed if not provided or expired. "
                "Tokens typically expire after 60 minutes (3600 seconds). "
                "See: https://developers.lightspeedhq.com/retail/authentication/access-token/"
            ),
        ),
        th.Property(
            "expires_in",
            th.IntegerType,
            required=False,
            description=(
                "Number of seconds until the access token expires. "
                "Typically 3600 (60 minutes). This is automatically updated when tokens are refreshed."
            ),
        ),
        th.Property(
            "expires",
            th.IntegerType,
            required=False,
            description=(
                "Unix timestamp (seconds since epoch) when the access token expires. "
                "This is automatically updated when tokens are refreshed."
            ),
        ),
        th.Property(
            "account_id",
            th.StringType,
            required=False,
            description=(
                "Optional: Account ID for the Lightspeed R-Series account. "
                "Most endpoints require AccountID in the path: "
                "/API/V3/Account/{AccountID}/Resource.json. "
                "If not provided, it may be extracted from the access token or API responses."
            ),
        ),
        th.Property(
            "throttle_seconds",
            th.NumberType,
            required=False,
            description=(
                "Minimum number of seconds to wait between API requests. "
                "Default: 1.0 seconds if not specified. "
                "The tap automatically handles rate limiting based on "
                "X-LS-API-Burst-Level, X-LS-API-Bucket-Level, and X-LS-API-Drip-Rate headers. "
                "This setting provides a baseline throttle in addition to automatic rate limiting."
            ),
        ),
    ).to_dict()

    def discover_streams(self) -> List[Stream]:
        """Return a list of discovered streams."""

        return [stream_class(tap=self) for stream_class in STREAM_TYPES]


if __name__ == "__main__":
    TapRLightspeed.cli()
