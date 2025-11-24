"""REST client handling, including LightspeedRSeriesStream base class."""

from typing import Any, Dict, Iterable, Optional, Callable
import urllib3
import requests
from singer_sdk.streams import RESTStream
from singer_sdk.exceptions import RetriableAPIError, FatalAPIError
import backoff
import copy
from time import sleep
from cached_property import cached_property
from tap_lightspeed.exceptions import TooManyRequestsError
from tap_lightspeed.auth import LightspeedOAuthAuthenticator
from http.client import ImproperConnectionState, RemoteDisconnected
import singer
from singer import StateMessage


class LightspeedXSeriesStream(RESTStream):
    """Lightspeed Retail (X-Series) stream class."""

    page_size = 100  # Default page size for Lightspeed R-Series API
    timeout = 300  # 5 minutes timeout

    @cached_property
    def url_base(self) -> str:
        """Return the API URL root for Lightspeed X-Series API.
        
        Base URL: https://{domain_prefix}.retail.lightspeed.app/api/2.0/
        The domain_prefix is specific to each retailer account.
        """
        domain_prefix = self.config.get("domain_prefix")
        if not domain_prefix:
            raise ValueError(
                "domain_prefix is required in config for Lightspeed X-Series API. "
                "This is the retailer's domain prefix (e.g., 'mystore' for mystore.retail.lightspeed.app)"
            )
        return f"https://{domain_prefix}.retail.lightspeed.app/api/2.0"

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
        """Return a token for identifying next page or None if no more pages.
        
        Lightspeed R-Series API uses offset-based pagination.
        If the response contains the expected number of records (page_size),
        there might be more pages.
        """
        # Parse response to check if there are more records
        try:
            response_data = response.json()
            # Check if response is a list or dict with items
            if isinstance(response_data, list):
                records = response_data
            elif isinstance(response_data, dict):
                # Try common keys for records
                records = response_data.get("@attributes", {}).get("count")
                if records is None:
                    # Try to get first list value
                    for key, value in response_data.items():
                        if isinstance(value, list):
                            records = value
                            break
                if not isinstance(records, list):
                    records = []
            else:
                records = []
            
            # If we got a full page, there might be more
            if len(records) >= self.page_size:
                previous_token = previous_token or 0
                next_page_token = previous_token + self.page_size
                return next_page_token
        except Exception as e:
            self.logger.debug(f"Error parsing pagination response: {e}")
        
        return None

    def get_url_params(
        self, context: Optional[dict], next_page_token: Optional[Any]
    ) -> Dict[str, Any]:
        """Return a dictionary of values to be used in URL parameterization."""
        params: dict = {}
        
        # Add pagination if we have a next page token
        if next_page_token:
            params["offset"] = next_page_token
            params["limit"] = self.page_size
        
        # Add replication key filtering if applicable
        if self.replication_key:
            start_date = self.get_starting_timestamp(context)
            if start_date:
                # Lightspeed R-Series uses updated_at_min for filtering
                params["updated_at_min"] = start_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        return params

    def make_request(self, context, next_page_token):
        """Make a request to the API."""
        prepared_request = self.prepare_request(
            context, next_page_token=next_page_token
        )
        resp = self._request(prepared_request, context)
        return resp

    def request_decorator(self, func: Callable) -> Callable:
        """Create a decorator for request retry logic."""
        decorator: Callable = backoff.on_exception(
            backoff.expo,
            (
                RetriableAPIError,
                TooManyRequestsError,
                ImproperConnectionState,
                ConnectionError,
                RemoteDisconnected,
                requests.exceptions.Timeout,
                requests.exceptions.RequestException,
                urllib3.exceptions.HTTPError,
                TimeoutError
            ),
            max_tries=10,
            factor=3,
        )(func)
        return decorator

    def request_records(self, context: Optional[dict]) -> Iterable[dict]:
        """Request records from the API with pagination."""
        next_page_token: Any = None
        finished = False
        decorated_request = self.request_decorator(self.make_request)
        
        # Throttle between requests to avoid rate limits
        throttle_seconds = self.config.get("throttle_seconds", 1.0)
        try:
            throttle_seconds = float(throttle_seconds)
        except:
            self.logger.info(
                f"Not able to convert {throttle_seconds} to a float, "
                f"using throttle default value 1.0 seconds"
            )
            throttle_seconds = 1.0

        while not finished:
            # Wait between requests to avoid hitting 429
            if next_page_token is not None:
                self.logger.debug(
                    f"Waiting between requests to avoid rate limits "
                    f"for {throttle_seconds} seconds"
                )
                sleep(throttle_seconds)

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
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            self.logger.info(f"Hit 429. Retry-After: {retry_after}")

            try:
                # Try to parse Retry-After header
                retry_after_seconds = int(retry_after)
            except (ValueError, TypeError):
                retry_after_seconds = 60  # Fallback in case of parsing errors

            msg = self.response_error_message(response)
            self.logger.info(
                f"Response status code 429 too many requests, "
                f"sleeping for {retry_after_seconds} seconds..."
            )
            sleep(retry_after_seconds)
            self.logger.info("Trying request again...")
            raise TooManyRequestsError(msg, response)

        # Handle authentication errors - token might need refresh
        if response.status_code == 401:
            msg = (
                f"{response.status_code} Authentication Error: "
                f"{response.reason} for path: {self.path} with response {response.text}"
            )
            # 401 might be retriable if token just expired
            raise RetriableAPIError(msg, response)

        # Handle server errors as retriable
        if 500 <= response.status_code < 600:
            msg = (
                f"{response.status_code} Server Error: "
                f"{response.reason} for path: {self.path} with response {response.text}"
            )
            raise RetriableAPIError(msg, response)

        # Handle client errors as fatal (except 401 which is handled above)
        if 400 <= response.status_code < 500:
            msg = (
                f"{response.status_code} Client Error: "
                f"{response.reason} for path: {self.path} with response {response.text}"
            )
            raise FatalAPIError(msg)

    def _write_state_message(self) -> None:
        """Write out a STATE message with the latest state."""
        tap_state = self.tap_state

        if tap_state and tap_state.get("bookmarks"):
            for stream_name in tap_state.get("bookmarks").keys():
                if tap_state["bookmarks"][stream_name].get("partitions"):
                    tap_state["bookmarks"][stream_name] = {"partitions": []}

        singer.write_message(StateMessage(value=tap_state))

    def get_replication_key_signpost(self, context: Optional[dict]) -> Optional[Any]:
        """Return the replication key signpost value if available."""
        return None
