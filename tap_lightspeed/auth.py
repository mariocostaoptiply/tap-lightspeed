"""Lightspeed OAuth2 Authentication."""

from singer import utils
import json
import requests
from singer_sdk.authenticators import OAuthAuthenticator, SingletonMeta
from singer_sdk.helpers._util import utc_now
from singer_sdk.streams import Stream as RESTStreamBase
from typing import Optional


# The SingletonMeta metaclass makes your streams reuse the same authenticator instance.
# If this behaviour interferes with your use-case, you can remove the metaclass.
class LightspeedOAuthAuthenticator(OAuthAuthenticator, metaclass=SingletonMeta):
    """Authenticator class for Lightspeed Retail (X-Series) API using OAuth 2.0."""

    def __init__(
        self,
        stream: RESTStreamBase,
        auth_endpoint: Optional[str] = None,
        oauth_scopes: Optional[str] = None
    ) -> None:
        super().__init__(stream=stream, auth_endpoint=auth_endpoint, oauth_scopes=oauth_scopes)
        self._tap = stream._tap

    @property
    def oauth_request_body(self) -> dict:
        """Define the OAuth request body for the Lightspeed X-Series API refresh token grant.
        
        According to Lightspeed X-Series documentation:
        https://x-series-api.lightspeedhq.com/docs/authorization
        
        The refresh token request requires:
        - client_id: Your application's client ID
        - client_secret: Your application's client secret
        - grant_type: "refresh_token"
        - refresh_token: The refresh token to exchange for a new access token
        """
        return {
            "client_id": self.config["client_id"],
            "client_secret": self.config["client_secret"],
            "grant_type": "refresh_token",
            "refresh_token": self.config["refresh_token"],
        }

    def is_token_valid(self) -> bool:
        """Check if token is valid.

        Returns:
            True if the token is valid (fresh).
        """
        if self.expires_in is not None:
            self.expires_in = int(self.expires_in)
        if self.last_refreshed is None:
            return False
        if not self.expires_in:
            return True
        if self.expires_in > (utils.now() - self.last_refreshed).total_seconds():
            return True
        return False

    @classmethod
    def create_for_stream(cls, stream) -> "LightspeedOAuthAuthenticator":
        """Create an authenticator instance for the given stream.
        
        For Lightspeed X-Series, the token endpoint is domain-specific:
        https://{domain_prefix}.retail.lightspeed.app/api/1.0/token
        
        Returns:
            LightspeedOAuthAuthenticator instance configured with Lightspeed X-Series token endpoint.
        """
        domain_prefix = stream.config.get("domain_prefix")
        if not domain_prefix:
            raise ValueError(
                "domain_prefix is required in config for Lightspeed X-Series API. "
                "This is the retailer's domain prefix (e.g., 'mystore' for mystore.retail.lightspeed.app)"
            )
        
        auth_endpoint = f"https://{domain_prefix}.retail.lightspeed.app/api/1.0/token"
        return cls(
            stream=stream,
            auth_endpoint=auth_endpoint,
        )

    def update_access_token(self) -> None:
        """Update `access_token` along with: `last_refreshed` and `expires_in`.

        Raises:
            RuntimeError: When OAuth login fails.
        """
        request_time = utc_now()
        auth_request_payload = self.oauth_request_payload
        token_response = requests.post(self.auth_endpoint, data=auth_request_payload)
        try:
            token_response.raise_for_status()
            self.logger.info("OAuth authorization attempt was successful.")
        except Exception as ex:
            error_msg = "Unknown error"
            try:
                error_msg = token_response.json()
            except:
                error_msg = token_response.text
            raise RuntimeError(
                f"Failed OAuth login, response was '{error_msg}'. {ex}"
            )
        token_json = token_response.json()
        self.access_token = token_json["access_token"]
        # Lightspeed X-Series tokens expire in varies (typically 86400 seconds / 24 hours for initial, 
        # 604800 seconds / 7 days for refreshed tokens, but can vary)
        # Use expires_in from response, default to 86400 if not present
        self.expires_in = token_json.get("expires_in", 86400)
        if self.expires_in is None:
            self.logger.debug(
                "No expires_in received in OAuth response and no "
                "default_expiration set. Token will be treated as if it never "
                "expires."
            )
        self.last_refreshed = request_time

        # Store access_token and refresh_token in config file
        # This allows the tokens to persist across tap runs
        self._tap._config["access_token"] = token_json["access_token"]
        if "refresh_token" in token_json:
            self._tap._config["refresh_token"] = token_json["refresh_token"]

        with open(self._tap.config_file, "w") as outfile:
            json.dump(self._tap._config, outfile, indent=4)

