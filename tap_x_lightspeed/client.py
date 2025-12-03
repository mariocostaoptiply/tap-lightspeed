"""REST client handling, including LightspeedXSeriesStream base class."""

from typing import Any, Dict, Optional
import requests
from singer_sdk.streams import RESTStream
from singer_sdk.exceptions import RetriableAPIError, FatalAPIError
import copy
from cached_property import cached_property
from tap_x_lightspeed.auth import LightspeedOAuthAuthenticator
import singer
from singer import StateMessage


class LightspeedXSeriesStream(RESTStream):
    """Lightspeed Retail (X-Series) stream class.
    
    Base stream class for Lightspeed X-Series API.
    X-Series uses version-based pagination with the 'after' parameter.
    See: https://x-series-api.lightspeedhq.com/docs/sync_entity_to_external_system
    
    This base class provides:
    - get_next_page_token(): Extracts version.max from response for pagination
    - get_url_params(): Implements version-based filtering with 'after' parameter
    - get_starting_version(): Reads version bookmark from state for incremental sync
    
    Child streams should override:
    - get_optional_params(): Return list of optional parameter names specific to the stream
    """

    page_size = 200  # Default page size for Lightspeed X-Series API (max is 200)
    timeout = 300  # 5 minutes timeout

    @cached_property
    def url_base(self) -> str:
        """Return the API URL root for Lightspeed X-Series API.
        
        Base URL: https://{domain_prefix}.retail.lightspeed.app
        The domain_prefix is specific to each retailer account.
        API endpoints are typically at /api/2.0/{resource}
        """
        domain_prefix = self.config.get("domain_prefix")
        if not domain_prefix:
            raise ValueError(
                "domain_prefix is required in config for Lightspeed X-Series API. "
                "This is the retailer's domain prefix (e.g., 'mystore' for mystore.retail.lightspeed.app)"
            )
        return f"https://{domain_prefix}.retail.lightspeed.app"

    @property
    def authenticator(self) -> LightspeedOAuthAuthenticator:
        """Return a new authenticator object."""
        return LightspeedOAuthAuthenticator.create_for_stream(self)

    @property
    def http_headers(self) -> dict:
        """Return the http headers needed."""
        headers = {}
        if "user_agent" in self.config:
            headers["User-Agent"] = self.config.get("user_agent")
        return headers

    def get_next_page_token(
        self, response: requests.Response, previous_token: Optional[Any]
    ) -> Optional[Any]:
        """Return the next page token using version-based pagination.
        
        Lightspeed X-Series uses version-based pagination. The response contains:
        {
            "data": [...],
            "version": {
                "min": <version_number>,
                "max": <version_number>
            }
        }
        
        When version.max is null, there are no more records.
        Returns version.max to be used as 'after' parameter in next request.
        """
        try:
            response_data = response.json()
            version_info = response_data.get("version", {})
            max_version = version_info.get("max")
            
            # If max_version is null, we've reached the end
            if max_version is None:
                return None
            
            # Return the max version as the next page token
            # This will be used as the 'after' parameter in the next request
            return max_version
            
        except Exception as e:
            self.logger.debug(f"Error parsing version pagination response: {e}")
            return None

    def get_starting_version(self, context: Optional[dict]) -> Optional[Any]:
        """Get the starting version number from state.
        
        For version-based replication, we store the version number (not datetime)
        in the state bookmark. This is used as the 'after' parameter in the first request.
        
        Note: The Lightspeed X-Series API only supports version-based pagination,
        not date-based filtering. The 'start_date' config option is not used here
        as the API doesn't support date queries.
        """
        if context is None:
            context = {}
        
        state = self.get_context_state(context)
        bookmark = state.get("replication_key_value")
        
        if bookmark:
            # Bookmark should be a version number (integer)
            try:
                return int(bookmark)
            except (ValueError, TypeError):
                self.logger.warning(
                    f"Invalid bookmark value for version: {bookmark}. "
                    "Starting from beginning."
                )
                return None
        
        # No bookmark found - will start from beginning (after=0)
        # Note: start_date is not used because the API doesn't support date filtering
        return None

    def get_optional_params(self) -> list:
        """Return a list of optional parameter names that can be added to the request.
        
        Child streams should override this method to return a list of parameter names
        that are specific to that stream. These parameters will be checked in the config
        with both prefixed (stream_name_param) and non-prefixed (param) formats.
        
        Returns:
            List of parameter names (strings) that should be checked in config
        """
        return []

    def get_url_params(
        self, context: Optional[dict], next_page_token: Optional[Any]
    ) -> Dict[str, Any]:
        """Return URL parameters for the request.
        
        Uses 'after' parameter for version-based filtering.
        The 'after' parameter filters records with version > after.
        Supports optional parameters from config via get_optional_params().
        """
        params: dict = {}
        
        # Version-based filtering using 'after' parameter
        # Lightspeed X-Series API only supports version-based pagination, not date-based
        if next_page_token:
            # next_page_token is the version.max from previous response
            # Use it as 'after' to get next page
            params["after"] = next_page_token
        else:
            # First request - check if we have a starting version from state
            if self.replication_key:
                starting_version = self.get_starting_version(context)
                if starting_version is not None:
                    # starting_version should be a version number (integer)
                    if isinstance(starting_version, (int, float)):
                        params["after"] = int(starting_version)
                    else:
                        # If it's not a number, start from 0
                        params["after"] = 0
                else:
                    # No state, start from beginning (after=0)
                    # According to docs, after=0 returns first page
                    params["after"] = 0
        
        # Add page_size parameter (optional, default is 200, max is 200)
        if self.page_size:
            params["page_size"] = self.page_size
        
        # Add optional parameters from config
        # These can be set in config or environment variables
        optional_params = self.get_optional_params()
        
        for param in optional_params:
            # First check for prefixed version (e.g., "products_deleted", "inventory_outlet_id")
            config_key = f"{self.name}_{param}"
            if config_key in self.config:
                value = self.config[config_key]
            # Then check for direct parameter name (e.g., "deleted", "outlet_id")
            elif param in self.config:
                value = self.config[param]
            else:
                continue
            
            # Convert boolean to string if needed (API expects string)
            if isinstance(value, bool):
                params[param] = str(value).lower()
            else:
                params[param] = value
        
        return params

    def make_request(self, context, next_page_token):
        """Make a request to the API."""
        prepared_request = self.prepare_request(
            context, next_page_token=next_page_token
        )
        resp = self._request(prepared_request, context)
        return resp
    
    def request_records(self, context: Optional[dict]):
        """Request records from the API with pagination."""
        next_page_token: Any = None
        finished = False
        decorated_request = self.request_decorator(self.make_request)

        while not finished:
            resp = decorated_request(context, next_page_token)
            for row in self.parse_response(resp):
                yield row
            previous_token = copy.deepcopy(next_page_token)
            next_page_token = self.get_next_page_token(
                response=resp, previous_token=previous_token
            )
            if next_page_token and next_page_token == previous_token:
                raise RuntimeError(
                    f"Loop detected in pagination. "
                    f"Pagination token {next_page_token} is identical to prior token."
                )
            # Cycle until get_next_page_token() no longer returns a value
            finished = not next_page_token

    def validate_response(self, response: requests.Response) -> None:
        """Validate the response and handle errors appropriately."""
        if response.status_code in [401]:
            # Check if the error is NOT related to token expiration/invalidity
            # Most 401 errors are token-related, so we assume token error unless
            # the error message clearly indicates a permissions/authorization issue
            response_text = response.text.lower()
            
            # Keywords that indicate this is NOT a token error (permissions/scope issues)
            non_token_keywords = [
                "insufficient_scope",
                "insufficient scope",
                "permission denied",
                "forbidden",
                "access denied",
                "not authorized for this resource",
                "scope required",
            ]
            
            # Check if error message clearly indicates a non-token issue
            is_non_token_error = any(keyword in response_text for keyword in non_token_keywords)
            
            # Also check JSON response if available
            if not is_non_token_error:
                try:
                    error_json = response.json()
                    error_message = str(error_json).lower()
                    is_non_token_error = any(keyword in error_message for keyword in non_token_keywords)
                except (ValueError, AttributeError):
                    # If response is not JSON, rely on text check
                    pass
            
            msg = (
                f"{response.status_code} Server Error: "
                f"{response.reason} for path: {self.path} with response {response.text}"
            )
            
            # Only raise RetriableAPIError (which triggers token refresh) if it's likely a token error
            # Raise FatalAPIError for clear permissions/authorization issues
            if is_non_token_error:
                self.logger.error(
                    f"Non-token authentication error (401). This is likely a permissions or "
                    f"authorization issue, not a token expiration. Response: {response.text[:200]}"
                )
                raise FatalAPIError(msg)
            else:
                # Assume token error and attempt refresh
                self.logger.warning(
                    f"Authentication error (401) detected. Assuming token issue and will attempt refresh. "
                    f"Response: {response.text[:200]}"
                )
                raise RetriableAPIError(msg)
        elif response.status_code == 400 and "Please try again later." in response.text:
            msg = (
                f"{response.status_code} Server Error: "
                f"{response.reason} for path: {self.path} with response {response.text}"
            )
            raise RetriableAPIError(msg)
        elif 400 <= response.status_code < 500:
            msg = (
                f"{response.status_code} Client Error: "
                f"{response.reason} for path: {self.path} with response {response.text}"
            )
            raise FatalAPIError(msg)
        elif 500 <= response.status_code < 600:
            msg = (
                f"{response.status_code} Server Error: "
                f"{response.reason} for path: {self.path} with response {response.text}"
            )
            raise RetriableAPIError(msg)

    def _write_state_message(self) -> None:
        """Write out a STATE message with the latest state."""
        tap_state = self.tap_state

        if tap_state and tap_state.get("bookmarks"):
            for stream_name in tap_state.get("bookmarks").keys():
                if tap_state["bookmarks"][stream_name].get("partitions"):
                    tap_state["bookmarks"][stream_name] = {"partitions": []}

        singer.write_message(StateMessage(value=tap_state))
