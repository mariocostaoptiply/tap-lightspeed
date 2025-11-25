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
        
        # Initialize token from config if available (to avoid unnecessary refreshes)
        # According to Lightspeed X-Series docs: https://x-series-api.lightspeedhq.com/docs/authorization
        # We should use the access token until it expires, then request a new one.
        if "access_token" in self.config and self.config["access_token"]:
            self.access_token = self.config["access_token"]
            
            # Calculate expires_in and last_refreshed from expires timestamp if available
            # expires is an absolute timestamp in seconds since Unix epoch
            if "expires" in self.config and self.config["expires"]:
                try:
                    expires_timestamp = int(self.config["expires"])
                    current_timestamp = int(utils.now().timestamp())
                    remaining_seconds = expires_timestamp - current_timestamp
                    
                    if remaining_seconds > 0:
                        self.expires_in = remaining_seconds
                        # Calculate when token was refreshed: expires - original_expires_in
                        # If we have expires_in in config, use it to calculate last_refreshed
                        if "expires_in" in self.config and self.config["expires_in"]:
                            original_expires_in = int(self.config["expires_in"])
                            # last_refreshed = expires - original_expires_in
                            last_refreshed_timestamp = expires_timestamp - original_expires_in
                            # Convert timestamp to datetime
                            from datetime import datetime, timezone
                            self.last_refreshed = datetime.fromtimestamp(last_refreshed_timestamp, tz=timezone.utc)
                        else:
                            # If no original expires_in, use remaining_seconds as expires_in
                            # and assume token was just refreshed (conservative approach)
                            self.last_refreshed = utils.now()
                    else:
                        # Token already expired - will trigger refresh
                        self.expires_in = 0
                        self.last_refreshed = None
                except (ValueError, TypeError) as e:
                    # If expires is invalid, try to use expires_in
                    self.logger.debug(f"Could not parse expires timestamp: {e}")
                    if "expires_in" in self.config and self.config["expires_in"]:
                        self.expires_in = int(self.config["expires_in"])
                        # Without expires timestamp, assume token was just refreshed
                        self.last_refreshed = utils.now()
                    else:
                        self.expires_in = None
                        self.last_refreshed = None
            elif "expires_in" in self.config and self.config["expires_in"]:
                # Use expires_in if expires timestamp not available
                self.expires_in = int(self.config["expires_in"])
                # Without expires timestamp, assume token was just refreshed
                self.last_refreshed = utils.now()
            else:
                # No expiration info, assume token is valid (never expires)
                self.expires_in = None
                self.last_refreshed = utils.now()

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

        According to Lightspeed X-Series rate limiting docs:
        https://x-series-api.lightspeedhq.com/docs/rate_limiting
        The authorization endpoints have their own rate limiting settings.
        If we receive a 429 (Too Many Requests), we should respect the Retry-After header.

        Raises:
            RuntimeError: When OAuth login fails.
        """
        request_time = utc_now()
        auth_request_payload = self.oauth_request_payload
        token_response = requests.post(self.auth_endpoint, data=auth_request_payload)
        
        # Handle rate limiting (429 Too Many Requests)
        if token_response.status_code == 429:
            retry_after = token_response.headers.get("Retry-After")
            error_msg = "Rate limit exceeded"
            try:
                error_json = token_response.json()
                error_msg = error_json.get("message", error_msg)
            except:
                error_msg = token_response.text or error_msg
            
            if retry_after:
                # Retry-After is in HTTP date format (RFC1123)
                from email.utils import parsedate_to_datetime
                try:
                    retry_datetime = parsedate_to_datetime(retry_after)
                    wait_seconds = (retry_datetime - utc_now()).total_seconds()
                    if wait_seconds > 0:
                        self.logger.warning(
                            f"Rate limited on token refresh. Waiting {wait_seconds:.0f} seconds "
                            f"until {retry_datetime} before retrying."
                        )
                        import time
                        time.sleep(wait_seconds)
                        # Retry the request
                        token_response = requests.post(self.auth_endpoint, data=auth_request_payload)
                    else:
                        # Retry immediately if wait time has passed
                        token_response = requests.post(self.auth_endpoint, data=auth_request_payload)
                except Exception as e:
                    self.logger.warning(f"Could not parse Retry-After header '{retry_after}': {e}")
            else:
                # No Retry-After header, wait 60 seconds as fallback
                self.logger.warning(
                    "Rate limited on token refresh. No Retry-After header. "
                    "Waiting 60 seconds before retrying."
                )
                import time
                time.sleep(60)
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

        # Store access_token, refresh_token, expires, and expires_in in config file
        # This allows the tokens to persist across tap runs
        self._tap._config["access_token"] = token_json["access_token"]
        if "refresh_token" in token_json:
            self._tap._config["refresh_token"] = token_json["refresh_token"]
        
        # Store expires timestamp (absolute time when token expires)
        # This is more reliable than expires_in for checking validity across runs
        if self.expires_in:
            expires_timestamp = int(request_time.timestamp()) + int(self.expires_in)
            self._tap._config["expires"] = expires_timestamp
        self._tap._config["expires_in"] = self.expires_in

        with open(self._tap.config_file, "w") as outfile:
            json.dump(self._tap._config, outfile, indent=4)

