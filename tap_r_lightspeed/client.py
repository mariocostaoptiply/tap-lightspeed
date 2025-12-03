"""REST client handling, including LightspeedRSeriesStream base class."""

from typing import Any, Dict, Optional
from urllib.parse import urlparse, parse_qs
import requests
import time
from singer_sdk.streams import RESTStream
from singer_sdk.exceptions import RetriableAPIError, FatalAPIError
import copy
from cached_property import cached_property
from tap_r_lightspeed.auth import LightspeedOAuthAuthenticator
import singer
from singer import StateMessage


class LightspeedRSeriesStream(RESTStream):
    """Lightspeed Retail (R-Series) stream class.
    
    Base stream class for Lightspeed R-Series API.
    R-Series uses cursor-based pagination with complete URLs in @attributes.next.
    See: https://developers.lightspeedhq.com/retail/introduction/pagination/
    
    R-Series response structure:
    {
        "@attributes": {
            "next": "https://api.lightspeedapp.com/API/V3/Account/{AccountID}/Item.json?...",
            "previous": ""
        },
        "Item": [...]  # Resource name varies (Item, Sale, Customer, etc.)
    }
    
    This base class provides:
    - get_next_page_token(): Extracts @attributes.next URL from response for pagination
    - get_url_params(): Implements query parameters including limit, sort, etc.
    - Rate limiting based on X-LS-API-Burst-Level, X-LS-API-Bucket-Level, and X-LS-API-Drip-Rate headers
    
    Child streams should override:
    - records_jsonpath: JSONPath expression to extract records (e.g., "$.Item[*]" for Item stream)
    - get_optional_params(): Return list of optional parameter names specific to the stream
    """

    page_size = 100  # Maximum page size for Lightspeed R-Series API (max is 100)
    timeout = 300  # 5 minutes timeout
    
    # Child streams must override this with the appropriate resource name
    # Example: records_jsonpath = "$.Item[*]" for Item endpoint
    # The resource name in the response matches the endpoint resource name
    records_jsonpath = "$[*]"  # Default fallback - child streams should override
    
    # Track rate limiting state
    _bucket_level = None
    _bucket_size = None
    _burst_level = None
    _burst_size = None
    _drip_rate = None
    _last_request_time = None

    @cached_property
    def url_base(self) -> str:
        """Return the API URL root for Lightspeed R-Series API.
        
        Base URL: https://api.lightspeedapp.com/API/V3
        R-Series uses a global API endpoint, not domain-specific.
        
        Note: Most endpoints require AccountID in the path:
        https://api.lightspeedapp.com/API/V3/Account/{AccountID}/Resource.json
        
        See: https://developers.lightspeedhq.com/retail/authentication/authentication-overview/
        """
        return "https://api.lightspeedapp.com/API/V3"

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

    def _update_rate_limit_info(self, response: requests.Response) -> None:
        """Update rate limiting information from response headers.
        
        Reads X-LS-API-Bucket-Level, X-LS-API-Burst-Level, and X-LS-API-Drip-Rate headers
        to track rate limiting state. Format: "used/total" (e.g., "1/90", "1/23")
        
        R-Series API uses two rate limits:
        - Burst limit: Short-term limit (e.g., 23) - more restrictive
        - Bucket limit: Long-term limit (e.g., 90) - less restrictive
        
        See: https://developers.lightspeedhq.com/retail/introduction/ratelimits/
        """
        # Read bucket level (long-term limit)
        bucket_level_header = response.headers.get("X-LS-API-Bucket-Level") or response.headers.get("x-ls-api-bucket-level")
        if bucket_level_header:
            try:
                # Format: "used/total" (e.g., "1/90")
                parts = bucket_level_header.split("/")
                if len(parts) == 2:
                    self._bucket_level = float(parts[0])
                    self._bucket_size = float(parts[1])
            except (ValueError, IndexError) as e:
                self.logger.debug(f"Could not parse X-LS-API-Bucket-Level '{bucket_level_header}': {e}")
        
        # Read burst level (short-term limit)
        burst_level_header = response.headers.get("X-LS-API-Burst-Level") or response.headers.get("x-ls-api-burst-level")
        if burst_level_header:
            try:
                # Format: "used/total" (e.g., "1/23")
                parts = burst_level_header.split("/")
                if len(parts) == 2:
                    self._burst_level = float(parts[0])
                    self._burst_size = float(parts[1])
            except (ValueError, IndexError) as e:
                self.logger.debug(f"Could not parse X-LS-API-Burst-Level '{burst_level_header}': {e}")
        
        # Read drip rate
        drip_rate_header = response.headers.get("X-LS-API-Drip-Rate") or response.headers.get("x-ls-api-drip-rate")
        if drip_rate_header:
            try:
                self._drip_rate = float(drip_rate_header)
            except ValueError as e:
                self.logger.debug(f"Could not parse X-LS-API-Drip-Rate '{drip_rate_header}': {e}")
        
        self._last_request_time = time.time()

    def _calculate_wait_time(self, request_cost: int = 1) -> float:
        """Calculate how long to wait before next request based on rate limiting.
        
        Uses leaky-bucket algorithm. Considers both burst limit (short-term) and
        bucket limit (long-term). Uses the most restrictive limit.
        
        Args:
            request_cost: Cost of the next request (1 for GET, 10 for PUT/POST/DELETE)
            
        Returns:
            Number of seconds to wait before making the request (0 if no wait needed)
        """
        if self._drip_rate is None:
            # No rate limit info available, use default throttle
            throttle_seconds = self.config.get("throttle_seconds", 1.0)
            return float(throttle_seconds)
        
        wait_times = []
        
        # Calculate wait time for bucket limit (long-term)
        if self._bucket_level is not None and self._bucket_size is not None:
            # Calculate current bucket level (accounting for drip since last request)
            if self._last_request_time:
                elapsed = time.time() - self._last_request_time
                # Drip empties the bucket: level decreases by drip_rate * elapsed
                current_bucket_level = max(0, self._bucket_level - (self._drip_rate * elapsed))
            else:
                current_bucket_level = self._bucket_level
            
            # Check if next request would exceed bucket capacity
            if current_bucket_level + request_cost > self._bucket_size:
                # Need to wait for bucket to empty enough
                needed_space = (current_bucket_level + request_cost) - self._bucket_size
                bucket_wait_time = needed_space / self._drip_rate if self._drip_rate > 0 else 1.0
                wait_times.append(bucket_wait_time)
        
        # Calculate wait time for burst limit (short-term)
        if self._burst_level is not None and self._burst_size is not None:
            # Burst limit typically resets faster, so we check current level
            # For burst, we assume it resets more quickly (burst is for rapid requests)
            if self._last_request_time:
                elapsed = time.time() - self._last_request_time
                # Burst limit may reset faster, but for safety assume same drip rate
                current_burst_level = max(0, self._burst_level - (self._drip_rate * elapsed))
            else:
                current_burst_level = self._burst_level
            
            # Check if next request would exceed burst capacity
            if current_burst_level + request_cost > self._burst_size:
                # Need to wait for burst limit to reset
                needed_space = (current_burst_level + request_cost) - self._burst_size
                burst_wait_time = needed_space / self._drip_rate if self._drip_rate > 0 else 1.0
                wait_times.append(burst_wait_time)
        
        # Use the maximum wait time (most restrictive limit)
        if wait_times:
            max_wait = max(wait_times)
            return max_wait
        
        # No wait needed, but respect minimum throttle
        throttle_seconds = self.config.get("throttle_seconds", 1.0)
        return float(throttle_seconds)

    def _wait_for_rate_limit(self, request_cost: int = 1) -> None:
        """Wait if necessary to respect rate limits.
        
        Args:
            request_cost: Cost of the request (1 for GET, 10 for PUT/POST/DELETE)
        """
        wait_time = self._calculate_wait_time(request_cost)
        if wait_time > 0:
            burst_info = ""
            if self._burst_level is not None and self._burst_size is not None:
                burst_info = f", burst: {self._burst_level}/{self._burst_size}"
            
            bucket_info = ""
            if self._bucket_level is not None and self._bucket_size is not None:
                bucket_info = f", bucket: {self._bucket_level}/{self._bucket_size}"
            
            self.logger.debug(
                f"Rate limiting: waiting {wait_time:.2f} seconds before request "
                f"(drip rate: {self._drip_rate}/s{burst_info}{bucket_info})"
            )
            time.sleep(wait_time)

    def get_next_page_token(
        self, response: requests.Response, previous_token: Optional[Any]
    ) -> Optional[Any]:
        """Return the next page token using cursor-based pagination.
        
        Lightspeed R-Series uses cursor-based pagination. The response contains:
        {
            "@attributes": {
                "next": "https://api.lightspeedapp.com/API/V3/Account/{AccountID}/Item.json?sort=itemID&limit=100&after=WzEwMF0%3D",
                "previous": ""
            },
            "Item": [...]
        }
        
        When @attributes.next is empty, there are no more records.
        Returns the complete URL from @attributes.next for the next request.
        
        See: https://developers.lightspeedhq.com/retail/introduction/pagination/
        """
        try:
            response_data = response.json()
            attributes = response_data.get("@attributes", {})
            next_url = attributes.get("next", "")
            
            # If next is empty string, we've reached the end
            if not next_url:
                return None
            
            # Return the complete URL for the next page
            return next_url
            
        except Exception as e:
            self.logger.debug(f"Error parsing pagination response: {e}")
            return None

    def get_optional_params(self) -> list:
        """Return a list of optional parameter names that can be added to the request.
        
        Child streams should override this method to return a list of parameter names
        that are specific to that stream. These parameters will be checked in the config
        with both prefixed (stream_name_param) and non-prefixed (param) formats.
        
        Common R-Series parameters:
        - sort: Field to sort by (e.g., "itemID", "-timeStamp")
        - archived: true/false/only
        - load_relations: JSON array of relations to load
        
        Returns:
            List of parameter names (strings) that should be checked in config
        """
        return []

    def get_url_params(
        self, context: Optional[dict], next_page_token: Optional[Any]
    ) -> Dict[str, Any]:
        """Return URL parameters for the request.
        
        For R-Series, if next_page_token is a complete URL, we'll use it directly
        in prepare_request. Otherwise, build parameters normally.
        
        Supports optional parameters from config via get_optional_params().
        
        See: https://developers.lightspeedhq.com/retail/introduction/parameters/
        """
        # If next_page_token is a complete URL, return empty params
        # (prepare_request will handle the full URL)
        if next_page_token and isinstance(next_page_token, str) and next_page_token.startswith("http"):
            return {}
        
        params: dict = {}
        
        # Add limit parameter (max 100 for R-Series)
        if self.page_size:
            params["limit"] = min(self.page_size, 100)  # Enforce max of 100
        
        # Add optional parameters from config
        optional_params = self.get_optional_params()
        
        for param in optional_params:
            # First check for prefixed version (e.g., "items_sort", "items_archived")
            config_key = f"{self.name}_{param}"
            if config_key in self.config:
                value = self.config[config_key]
            # Then check for direct parameter name (e.g., "sort", "archived")
            elif param in self.config:
                value = self.config[param]
            else:
                continue
            
            # Handle special parameter types
            if param == "load_relations":
                # load_relations should be a JSON-encoded array
                if isinstance(value, list):
                    import json
                    params[param] = json.dumps(value)
                elif isinstance(value, str):
                    params[param] = value
            elif isinstance(value, bool):
                # Convert boolean to string
                params[param] = str(value).lower()
            else:
                params[param] = value
        
        return params

    def prepare_request(
        self, context: Optional[dict], next_page_token: Optional[Any]
    ) -> requests.PreparedRequest:
        """Prepare a request for the API.
        
        Override to handle full URLs from @attributes.next when provided.
        """
        # If next_page_token is a complete URL, use it directly
        if next_page_token and isinstance(next_page_token, str) and next_page_token.startswith("http"):
            # Parse the URL to extract path and params
            parsed_url = urlparse(next_page_token)
            # Update path to be relative to url_base
            # Remove the base URL part to get the relative path
            base_url = self.url_base
            if parsed_url.path.startswith(base_url):
                path = parsed_url.path[len(base_url):]
            else:
                # Try to extract path after /API/V3
                if "/API/V3" in parsed_url.path:
                    path = parsed_url.path.split("/API/V3", 1)[1]
                else:
                    path = parsed_url.path
            
            # Parse query parameters from URL
            query_params = parse_qs(parsed_url.query, keep_blank_values=True)
            # Convert lists to single values (parse_qs returns lists)
            params = {k: v[0] if isinstance(v, list) and len(v) == 1 else v 
                     for k, v in query_params.items()}
            
            # Create a temporary path with params for prepare_request
            # We'll override the URL construction
            self.path = path
            
            # Call parent prepare_request with the parsed params
            prepared = super().prepare_request(context, None)
            
            # Override the URL with the complete URL from next_page_token
            # This ensures we use the exact URL provided by the API
            from requests import Request
            req = Request(
                method=prepared.method,
                url=next_page_token,
                headers=prepared.headers,
            )
            return self.requests_session.prepare_request(req)
        
        # Normal request - use standard prepare_request
        return super().prepare_request(context, next_page_token)

    def make_request(self, context, next_page_token):
        """Make a request to the API with rate limiting."""
        # Determine request cost (GET = 1, others = 10)
        # We'll assume GET for now, child streams can override if needed
        request_cost = 1
        
        # Wait if necessary to respect rate limits
        self._wait_for_rate_limit(request_cost)
        
        prepared_request = self.prepare_request(
            context, next_page_token=next_page_token
        )
        resp = self._request(prepared_request, context)
        
        # Update rate limiting info from response headers
        self._update_rate_limit_info(resp)
        
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
        """Validate the response and handle errors appropriately.
        
        Handles rate limiting (429) with Retry-After header support.
        See: https://developers.lightspeedhq.com/retail/introduction/ratelimits/
        """
        if response.status_code == 429:
            # Rate limit exceeded
            retry_after = response.headers.get("Retry-After") or response.headers.get("retry-after")
            bucket_level = response.headers.get("X-LS-API-Bucket-Level") or response.headers.get("x-ls-api-bucket-level", "unknown")
            burst_level = response.headers.get("X-LS-API-Burst-Level") or response.headers.get("x-ls-api-burst-level", "unknown")
            drip_rate = response.headers.get("X-LS-API-Drip-Rate") or response.headers.get("x-ls-api-drip-rate", "unknown")
            
            error_msg = (
                f"Rate limit exceeded (429). "
                f"Burst: {burst_level}, Bucket: {bucket_level}, Drip rate: {drip_rate}/s"
            )
            
            if retry_after:
                try:
                    # Retry-After can be seconds (integer) or HTTP date
                    retry_seconds = int(retry_after)
                except ValueError:
                    # Try parsing as HTTP date
                    from email.utils import parsedate_to_datetime
                    try:
                        retry_datetime = parsedate_to_datetime(retry_after)
                        retry_seconds = int((retry_datetime.timestamp() - time.time()))
                    except Exception:
                        retry_seconds = 60  # Default to 60 seconds
                
                self.logger.warning(
                    f"{error_msg}. Waiting {retry_seconds} seconds before retry."
                )
                time.sleep(retry_seconds)
                raise RetriableAPIError(error_msg)
            else:
                # No Retry-After header, wait 1 second for burst rate limit
                # or calculate based on drip rate
                if "burst" in response.text.lower():
                    wait_time = 1.0
                else:
                    # Calculate wait based on bucket and drip rate
                    wait_time = self._calculate_wait_time(request_cost=1)
                
                self.logger.warning(
                    f"{error_msg}. Waiting {wait_time:.1f} seconds before retry."
                )
                time.sleep(wait_time)
                raise RetriableAPIError(error_msg)
        
        if response.status_code in [401]:
            # Check if the error is NOT related to token expiration/invalidity
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
                    pass
            
            msg = (
                f"{response.status_code} Server Error: "
                f"{response.reason} for path: {self.path} with response {response.text}"
            )
            
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
