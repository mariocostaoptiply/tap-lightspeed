"""Stream type classes for tap-lightspeed."""

from typing import Optional, Any, Dict, Iterable
import requests
from singer_sdk import typing as th
from tap_x_lightspeed.client import LightspeedXSeriesStream


class ProductsStream(LightspeedXSeriesStream):
    """Products stream for Lightspeed X-Series API.
    
    Uses version-based pagination as described in:
    https://x-series-api.lightspeedhq.com/docs/sync_entity_to_external_system
    
    The 'after' parameter filters products with version > after (similar to lastModifiedDate in Dynamics).
    """
    
    name = "products"
    path = "/api/2.0/products"
    primary_keys = ["id"]
    replication_key = "version"
    records_jsonpath = "$.data[*]"  # Extract products from data array
    page_size = 100  # Default page size for Lightspeed X-Series API (max is 200)
    
    schema = th.PropertiesList(
        # Primary identifiers
        th.Property("id", th.StringType),
        th.Property("version", th.IntegerType),
        th.Property("source_id", th.StringType),
        th.Property("source_variant_id", th.StringType),
        th.Property("variant_parent_id", th.StringType),
        th.Property("family_id", th.StringType),
        
        # Basic product information
        th.Property("name", th.StringType),
        th.Property("variant_name", th.StringType),
        th.Property("handle", th.StringType),
        th.Property("sku", th.StringType),
        th.Property("supplier_code", th.StringType),
        th.Property("description", th.StringType),
        th.Property("type", th.StringType),
        
        # Status flags
        th.Property("active", th.BooleanType),
        th.Property("is_active", th.BooleanType),
        th.Property("has_inventory", th.BooleanType),
        th.Property("is_composite", th.BooleanType),
        th.Property("ecwid_enabled_webstore", th.BooleanType),
        th.Property("has_variants", th.BooleanType),
        
        # Images
        th.Property("image_url", th.StringType),
        th.Property("image_thumbnail_url", th.StringType),
        
        # Timestamps
        th.Property("created_at", th.DateTimeType),
        th.Property("updated_at", th.DateTimeType),
        th.Property("deleted_at", th.DateTimeType),
        
        # Source and accounting
        th.Property("source", th.StringType),
        th.Property("account_code", th.StringType),
        th.Property("account_code_purchase", th.StringType),
        th.Property("supply_price", th.NumberType),
        
        # Relationships
        th.Property("supplier_id", th.StringType),
        th.Property("brand_id", th.StringType),
        th.Property("product_type_id", th.StringType),
        th.Property("product_category", th.StringType),
        # supplier and brand can be objects (with id, name, description, etc.) or null
        th.Property("supplier", th.ObjectType(
            th.Property("id", th.StringType),
            th.Property("name", th.StringType),
            th.Property("source", th.StringType),
            th.Property("description", th.StringType),
            th.Property("deleted_at", th.DateTimeType),
            th.Property("version", th.IntegerType),
        )),
        th.Property("brand", th.ObjectType(
            th.Property("id", th.StringType),
            th.Property("name", th.StringType),
            th.Property("source", th.StringType),
            th.Property("description", th.StringType),
            th.Property("deleted_at", th.DateTimeType),
            th.Property("version", th.IntegerType),
        )),
        
        # Variants
        th.Property("variant_count", th.IntegerType),
        # variant_options: per API docs has name and value, but API may also return id
        th.Property("variant_options", th.ArrayType(
            th.ObjectType(
                th.Property("name", th.StringType),  # required per API docs
                th.Property("value", th.StringType),  # required per API docs
                th.Property("id", th.StringType),  # not in docs but may be returned by API
            )
        )),
        
        # Categories and tags
        # Categories: array of tag objects (per API docs: id, name, deleted_at)
        # Note: API also returns 'version' field, so we include it for completeness
        th.Property("categories", th.ArrayType(
            th.ObjectType(
                th.Property("id", th.StringType),
                th.Property("name", th.StringType),  # required per API docs
                th.Property("deleted_at", th.DateTimeType),
                th.Property("version", th.IntegerType),  # not in docs but returned by API
            )
        )),
        th.Property("tag_ids", th.ArrayType(th.StringType)),
        
        # Images arrays
        # images: per API docs has id, url, version
        th.Property("images", th.ArrayType(
            th.ObjectType(
                th.Property("id", th.StringType),
                th.Property("url", th.StringType),
                th.Property("version", th.IntegerType),
            )
        )),
        # skuImages: not in API docs but may be returned by API
        th.Property("skuImages", th.ArrayType(th.ObjectType())),
        
        # Pricing
        th.Property("price_including_tax", th.NumberType),
        th.Property("price_excluding_tax", th.NumberType),
        th.Property("loyalty_amount", th.NumberType),
        
        # Product codes
        # product_codes: per API docs has type (enum: CUSTOM, EAN, ISBN, ITF, JAN, UPC) and code
        th.Property("product_codes", th.ArrayType(
            th.ObjectType(
                th.Property("type", th.StringType),  # enum: CUSTOM, EAN, ISBN, ITF, JAN, UPC
                th.Property("code", th.StringType),  # required per API docs
                th.Property("id", th.StringType),  # not in docs but may be returned by API
            )
        )),
        
        # Product suppliers
        # product_suppliers: per API docs has supplier_id, price, code
        th.Property("product_suppliers", th.ArrayType(
            th.ObjectType(
                th.Property("supplier_id", th.StringType),  # required per API docs
                th.Property("price", th.NumberType),  # required per API docs (double)
                th.Property("code", th.StringType),  # required per API docs
                # Additional fields that may be returned by API:
                th.Property("id", th.StringType),
                th.Property("product_id", th.StringType),
                th.Property("supplier_name", th.StringType),
            )
        )),
        
        # Packaging
        th.Property("packaging", th.ObjectType(
            th.Property("made_from", th.ArrayType(th.StringType)),
            th.Property("breaks_into", th.ArrayType(th.StringType)),
        )),
        
        # Physical attributes
        th.Property("weight", th.NumberType),
        th.Property("weight_unit", th.StringType),
        th.Property("length", th.NumberType),
        th.Property("width", th.NumberType),
        th.Property("height", th.NumberType),
        th.Property("dimensions_unit", th.StringType),
        
        # Other attributes
        # attributes: per API docs has key and value
        th.Property("attributes", th.ArrayType(
            th.ObjectType(
                th.Property("key", th.StringType),  # required per API docs
                th.Property("value", th.StringType),  # required per API docs
            )
        )),
        th.Property("button_order", th.IntegerType),
    ).to_dict()
    
    def get_optional_params(self) -> list:
        """Return a list of optional parameter names specific to products stream."""
        return [
            "deleted",  # Boolean to include deleted products
            "active",   # Filter by active status
            "type",     # Filter by product type
            "supplier_id",  # Filter by supplier
            "brand_id",     # Filter by brand
            "product_type_id",  # Filter by product type
        ]


class InventoryStream(LightspeedXSeriesStream):
    """Inventory stream for Lightspeed X-Series API.
    
    Uses version-based pagination as described in:
    https://x-series-api.lightspeedhq.com/docs/sync_entity_to_external_system
    
    The 'after' parameter filters inventory records with version > after.
    Requires: inventory:read scope
    """
    
    name = "inventory"
    path = "/api/2.0/inventory"
    primary_keys = ["id"]
    replication_key = "version"
    records_jsonpath = "$.data[*]"  # Extract inventory records from data array
    page_size = 100  # Default page size for Lightspeed X-Series API (max is 200)
    
    schema = th.PropertiesList(
        # Primary identifiers
        th.Property("id", th.StringType),
        th.Property("version", th.IntegerType),
        
        # Relationships
        th.Property("outlet_id", th.StringType),
        th.Property("product_id", th.StringType),
        
        # Inventory levels
        th.Property("inventory_level", th.NumberType),
        th.Property("current_amount", th.NumberType),
        
        # Cost and reorder settings
        th.Property("average_cost", th.NumberType),
        th.Property("reorder_point", th.NumberType),
        th.Property("reorder_amount", th.NumberType),
        
        # Timestamps
        th.Property("deleted_at", th.DateTimeType),
    ).to_dict()
    
    def get_optional_params(self) -> list:
        """Return a list of optional parameter names specific to inventory stream."""
        return [
            "outlet_id",  # Filter by outlet
            "product_id",  # Filter by product
            "before",  # Upper limit for version numbers
        ]


class SuppliersStream(LightspeedXSeriesStream):
    """Suppliers stream for Lightspeed X-Series API.
    
    Uses version-based pagination as described in:
    https://x-series-api.lightspeedhq.com/docs/sync_entity_to_external_system
    
    The 'after' parameter filters suppliers with version > after.
    Requires: suppliers:read scope
    """
    
    name = "suppliers"
    path = "/api/2.0/suppliers"
    primary_keys = ["id"]
    replication_key = "version"
    records_jsonpath = "$.data[*]"  # Extract suppliers from data array
    page_size = 100  # Default page size for Lightspeed X-Series API (max is 200)
    
    schema = th.PropertiesList(
        # Primary identifiers
        th.Property("id", th.StringType),
        th.Property("version", th.IntegerType),
        
        # Basic supplier information
        th.Property("name", th.StringType),
        th.Property("source", th.StringType),
        th.Property("description", th.StringType),
        th.Property("default_markup", th.NumberType),
        
        # Timestamps
        th.Property("deleted_at", th.DateTimeType),
        
        # Contact information (nested object)
        th.Property("contact", th.ObjectType(
            # Personal information
            th.Property("first_name", th.StringType),
            th.Property("last_name", th.StringType),
            th.Property("company_name", th.StringType),
            
            # Contact methods
            th.Property("phone", th.StringType),
            th.Property("mobile", th.StringType),
            th.Property("fax", th.StringType),
            th.Property("website", th.StringType),
            th.Property("email", th.StringType),
            th.Property("twitter", th.StringType),
            
            # Postal address
            th.Property("postal_address1", th.StringType),
            th.Property("postal_address2", th.StringType),
            th.Property("postal_suburb", th.StringType),
            th.Property("postal_postcode", th.StringType),
            th.Property("postal_city", th.StringType),
            th.Property("postal_state", th.StringType),
            th.Property("postal_country_id", th.StringType),
            
            # Physical address
            th.Property("physical_address1", th.StringType),
            th.Property("physical_address2", th.StringType),
            th.Property("physical_suburb", th.StringType),
            th.Property("physical_postcode", th.StringType),
            th.Property("physical_city", th.StringType),
            th.Property("physical_state", th.StringType),
            th.Property("physical_country_id", th.StringType),
        )),
    ).to_dict()
    
class SalesStream(LightspeedXSeriesStream):
    """Sales stream for Lightspeed X-Series API.
    
    Uses version-based pagination as described in:
    https://x-series-api.lightspeedhq.com/docs/sync_entity_to_external_system
    
    The 'after' parameter filters sales with version > after.
    Requires: sales:read scope
    """
    
    name = "sales"
    path = "/api/2.0/sales"
    primary_keys = ["id"]
    replication_key = "version"
    records_jsonpath = "$.data[*]"  # Extract sales from data array
    page_size = 100  # Default page size for Lightspeed X-Series API (max is 200)
    
    schema = th.PropertiesList(
        # Primary identifiers
        th.Property("id", th.StringType),
        th.Property("version", th.IntegerType),
        
        # Relationships
        th.Property("outlet_id", th.StringType),
        th.Property("register_id", th.StringType),
        th.Property("user_id", th.StringType),
        th.Property("customer_id", th.StringType),
        
        # Sale information
        th.Property("invoice_number", th.StringType),
        th.Property("invoice_sequence", th.NumberType),
        th.Property("receipt_number", th.StringType),
        th.Property("source", th.StringType),  # USER, SHOPIFY, ECOMMERCE, QUOTE
        th.Property("source_id", th.StringType),
        th.Property("status", th.StringType),  # SAVED, CLOSED, ONACCOUNT, etc.
        th.Property("state", th.StringType),  # parked, pending, voided, closed
        th.Property("note", th.StringType),
        th.Property("short_code", th.StringType),
        th.Property("return_for", th.StringType),
        th.Property("return_ids", th.ArrayType(th.StringType)),
        
        # Financial totals
        th.Property("total_price", th.NumberType),
        th.Property("total_price_incl", th.NumberType),
        th.Property("total_tax", th.NumberType),
        th.Property("total_loyalty", th.NumberType),
        th.Property("total_surcharge", th.NumberType),
        
        # Timestamps
        th.Property("sale_date", th.DateTimeType),
        th.Property("created_at", th.DateTimeType),
        th.Property("updated_at", th.DateTimeType),
        th.Property("deleted_at", th.DateTimeType),
        
        # Additional fields
        th.Property("complete_open_sequence_id", th.StringType),
        th.Property("accounts_transaction_id", th.StringType),
        th.Property("has_unsynced_on_account_payments", th.BooleanType),
        
        # Line items (array of objects)
        th.Property("line_items", th.ArrayType(
            th.ObjectType(
                th.Property("id", th.StringType),
                th.Property("product_id", th.StringType),
                th.Property("salesperson_id", th.StringType),
                th.Property("tax_id", th.StringType),
                th.Property("quantity", th.NumberType),
                th.Property("price", th.NumberType),
                th.Property("price_total", th.NumberType),
                th.Property("unit_price", th.NumberType),
                th.Property("discount", th.NumberType),
                th.Property("discount_total", th.NumberType),
                th.Property("unit_discount", th.NumberType),
                th.Property("total_discount", th.NumberType),
                th.Property("tax", th.NumberType),  # deprecated
                th.Property("tax_total", th.NumberType),
                th.Property("unit_tax", th.NumberType),
                th.Property("total_tax", th.NumberType),
                th.Property("total_price", th.NumberType),
                th.Property("cost", th.NumberType),
                th.Property("cost_total", th.NumberType),
                th.Property("loyalty_value", th.NumberType),
                th.Property("note", th.StringType),
                th.Property("return_reason", th.StringType),
                th.Property("status", th.StringType),  # SAVED, VOIDED, CONFIRMED
                th.Property("sequence", th.IntegerType),
                th.Property("price_set", th.BooleanType),
                th.Property("is_return", th.BooleanType),
                th.Property("gift_card_number", th.StringType),
                th.Property("tax_components", th.ArrayType(
                    th.ObjectType(
                        th.Property("rate_id", th.StringType),
                        th.Property("total_tax", th.NumberType),
                    )
                )),
                th.Property("promotions", th.ArrayType(th.ObjectType())),
                th.Property("surcharges", th.ArrayType(
                    th.ObjectType(
                        th.Property("value", th.NumberType),
                        th.Property("tax_components", th.ArrayType(
                            th.ObjectType(
                                th.Property("rate_id", th.StringType),
                                th.Property("total_tax", th.NumberType),
                            )
                        )),
                    )
                )),
            )
        )),
        
        # Payments (array of objects)
        th.Property("payments", th.ArrayType(
            th.ObjectType(
                th.Property("id", th.StringType),
                th.Property("register_id", th.StringType),
                th.Property("register_open_sequence_id", th.StringType),
                th.Property("outlet_id", th.StringType),
                th.Property("retailer_payment_type_id", th.StringType),
                th.Property("payment_type_id", th.StringType),
                th.Property("name", th.StringType),
                th.Property("amount", th.NumberType),
                th.Property("payment_date", th.DateTimeType),
                th.Property("deleted_at", th.DateTimeType),
                th.Property("surcharge", th.ObjectType()),
                th.Property("source_id", th.StringType),
                th.Property("external_attributes", th.ArrayType(th.ObjectType())),
                th.Property("external_applications", th.ArrayType(th.ObjectType())),
            )
        )),
        
        # Taxes (array of objects)
        th.Property("taxes", th.ArrayType(
            th.ObjectType(
                th.Property("id", th.StringType),
                th.Property("amount", th.NumberType),
                th.Property("name", th.StringType),
                th.Property("rate", th.NumberType),
            )
        )),
        
        # Adjustments (array of objects)
        th.Property("adjustments", th.ArrayType(
            th.ObjectType(
                th.Property("name", th.StringType),
                th.Property("value", th.NumberType),
                th.Property("adjustment_type", th.StringType),  # NON_CASH_FEE, DISCOUNT, TIP, SURCHARGE, ECOM_CUSTOM_CHARGE
                th.Property("tax_components", th.ArrayType(
                    th.ObjectType(
                        th.Property("rate_id", th.StringType),
                        th.Property("total_tax", th.NumberType),
                    )
                )),
            )
        )),
        
        # Ecom custom charges (object)
        th.Property("ecom_custom_charges", th.ObjectType(
            th.Property("charges", th.ArrayType(th.ObjectType())),
            th.Property("total", th.NumberType),
            th.Property("total_tax", th.NumberType),
            th.Property("total_incl", th.NumberType),
        )),
        
        # Attributes (array of strings)
        th.Property("attributes", th.ArrayType(th.StringType)),
        th.Property("external_applications", th.ArrayType(th.ObjectType())),
    ).to_dict()


class OutletsStream(LightspeedXSeriesStream):
    """Outlets stream for Lightspeed X-Series API.
    
    Note: This endpoint (/api/outlets) is deprecated but still functional.
    It uses traditional pagination (page-based) instead of version-based pagination.
    The response structure uses 'outlets' array and 'pagination' object instead of 'data' and 'version'.
    
    Requires: outlets:read scope
    """
    
    name = "outlets"
    path = "/api/outlets"
    primary_keys = ["id"]
    replication_key = None  # This endpoint doesn't support incremental sync via version
    records_jsonpath = "$.outlets[*]"  # Extract outlets from outlets array (not data)
    page_size = 200  # Default page size
    
    schema = th.PropertiesList(
        # Primary identifiers
        th.Property("id", th.StringType),
        
        # Basic outlet information
        th.Property("name", th.StringType),
        th.Property("time_zone", th.StringType),  # tz database format like Pacific/Auckland
        th.Property("tax_id", th.StringType),
        th.Property("email", th.StringType),
        
        # Contact information (nested object)
        th.Property("contact", th.ObjectType(
            # Personal information
            th.Property("first_name", th.StringType),
            th.Property("last_name", th.StringType),
            th.Property("company_name", th.StringType),
            
            # Contact methods
            th.Property("phone", th.StringType),
            th.Property("mobile", th.StringType),
            th.Property("fax", th.StringType),
            th.Property("email", th.StringType),
            th.Property("twitter", th.StringType),
            th.Property("website", th.StringType),
            
            # Physical address
            th.Property("physical_address1", th.StringType),
            th.Property("physical_address2", th.StringType),
            th.Property("physical_suburb", th.StringType),
            th.Property("physical_city", th.StringType),
            th.Property("physical_postcode", th.StringType),
            th.Property("physical_state", th.StringType),
            th.Property("physical_country_id", th.StringType),
            
            # Postal address
            th.Property("postal_address1", th.StringType),
            th.Property("postal_address2", th.StringType),
            th.Property("postal_suburb", th.StringType),
            th.Property("postal_city", th.StringType),
            th.Property("postal_postcode", th.StringType),
            th.Property("postal_state", th.StringType),
            th.Property("postal_country_id", th.StringType),
        )),
        
        # Physical address fields (also at top level, per example)
        th.Property("physical_address1", th.StringType),
        th.Property("physical_address2", th.StringType),
        th.Property("physical_suburb", th.StringType),
        th.Property("physical_city", th.StringType),
        th.Property("physical_postcode", th.StringType),
        th.Property("physical_state", th.StringType),
        th.Property("physical_country_id", th.StringType),
    ).to_dict()
    
    def get_next_page_token(
        self, response: requests.Response, previous_token: Optional[Any]
    ) -> Optional[Any]:
        """Return the next page token using traditional pagination.
        
        This endpoint uses page-based pagination instead of version-based.
        The response contains:
        {
            "outlets": [...],
            "pagination": {
                "results": <total>,
                "page": <current_page>,
                "page_size": <page_size>,
                "pages": <total_pages>
            }
        }
        
        Returns the next page number if there are more pages, None otherwise.
        Note: Pages are typically 1-indexed (page 1, 2, 3...).
        """
        try:
            response_data = response.json()
            pagination = response_data.get("pagination", {})
            current_page = pagination.get("page", 1)
            total_pages = pagination.get("pages", 0)
            
            # If current page is less than total pages, return next page number
            # Pages are typically 1-indexed
            if current_page < total_pages:
                return current_page + 1
            
            return None
            
        except Exception as e:
            self.logger.debug(f"Error parsing pagination response: {e}")
            return None
    
    def get_url_params(
        self, context: Optional[dict], next_page_token: Optional[Any]
    ) -> Dict[str, Any]:
        """Return URL parameters for the request.
        
        Uses traditional page-based pagination instead of version-based.
        """
        params: dict = {}
        
        # Use page-based pagination
        if next_page_token is not None:
            params["page"] = next_page_token
        else:
            # First request, start from page 0 or 1 (depending on API)
            params["page"] = 1
        
        # Add page_size parameter
        if self.page_size:
            params["page_size"] = self.page_size
        
        return params


class ConsignmentsStream(LightspeedXSeriesStream):
    """Consignments stream for Lightspeed X-Series API.
    
    Uses version-based pagination as described in:
    https://x-series-api.lightspeedhq.com/docs/sync_entity_to_external_system
    
    The 'after' parameter filters consignments with version > after.
    Consignments can be of type: SUPPLIER (buy orders), OUTLET (transfers), STOCKTAKE, or RETURN.
    Requires: consignments:read scope
    """
    
    name = "consignments"
    path = "/api/2.0/consignments"
    primary_keys = ["id"]
    replication_key = "version"
    # Note: API may return direct array or data wrapper - parse_response handles both
    records_jsonpath = "$.data[*]"  # Standard structure (parse_response handles array if needed)
    page_size = 100  # Default page size for Lightspeed X-Series API (max is 200)
    
    schema = th.PropertiesList(
        # Primary identifiers
        th.Property("id", th.StringType),
        th.Property("version", th.IntegerType),
        
        # Relationships
        th.Property("outlet_id", th.StringType),  # required - outlet where stock will be received
        th.Property("supplier_id", th.StringType),  # for SUPPLIER type consignments
        th.Property("source_outlet_id", th.StringType),  # for OUTLET type (stock transfers)
        
        # Basic consignment information
        th.Property("name", th.StringType),  # required - Consignment name
        th.Property("type", th.StringType),  # required - enum: SUPPLIER, OUTLET, STOCKTAKE, RETURN
        th.Property("status", th.StringType),  # enum: OPEN, SENT, DISPATCHED, RECEIVED, etc.
        
        # Dates
        th.Property("consignment_date", th.DateTimeType),  # Creation date
        th.Property("due_at", th.DateTimeType),  # Due date
        th.Property("received_at", th.DateTimeType),  # Date when consignment was received
        
        # References
        th.Property("supplier_invoice", th.StringType),  # Supplier invoice number
        th.Property("reference", th.StringType),  # Order number
        
        # Totals
        th.Property("total_count_gain", th.NumberType),  # Items over expected level
        th.Property("total_cost_gain", th.NumberType),  # Cost of items over expected level
        th.Property("total_count_loss", th.NumberType),  # Items below expected level
        th.Property("total_cost_loss", th.NumberType),  # Cost of items below expected level
        
        # Timestamps
        th.Property("created_at", th.DateTimeType),
        th.Property("updated_at", th.DateTimeType),
        th.Property("deleted_at", th.DateTimeType),
    ).to_dict()
    
    def get_optional_params(self) -> list:
        """Return a list of optional parameter names specific to consignments stream."""
        return [
            "type",  # Filter by type: SUPPLIER, OUTLET, STOCKTAKE, RETURN
            "status",  # Filter by status: OPEN, SENT, DISPATCHED, RECEIVED, etc.
            "outlet_id",  # Filter by outlet
            "before",  # Upper limit for version numbers
        ]
    
    def get_child_context(self, record: dict, context: Optional[dict]) -> dict:
        """Return a context dictionary for child streams.
        
        Provides consignment_id to child streams like ConsignmentProductsStream.
        """
        return {
            "consignment_id": record["id"],
        }

class ConsignmentProductsStream(LightspeedXSeriesStream):
    """Consignment Products stream for Lightspeed X-Series API.
    
    Child stream of ConsignmentsStream that retrieves products for each consignment.
    Uses version-based pagination as described in:
    https://x-series-api.lightspeedhq.com/docs/sync_entity_to_external_system
    
    The 'after' parameter filters consignment products with version > after.
    Endpoint: /api/2.0/consignments/{consignment_id}/products
    Requires: consignments:read scope
    """
    
    name = "consignment_products"
    path = "/api/2.0/consignments/{consignment_id}/products"
    primary_keys = ["consignment_id", "product_id", "version"]
    replication_key = "version"
    records_jsonpath = "$.data[*]"  # Extract products from data array
    page_size = 100  # Default page size for Lightspeed X-Series API (max is 200)
    parent_stream_type = ConsignmentsStream
    
    schema = th.PropertiesList(
        # Primary identifiers
        th.Property("consignment_id", th.StringType, required=True),
        th.Property("product_id", th.StringType, required=True),
        th.Property("version", th.IntegerType),
        
        # Product details
        th.Property("count", th.StringType),  # Expected count as string (decimal) - may come as number from API
        th.Property("received", th.StringType),  # Received count as string (decimal) - may come as number from API
        th.Property("cost", th.StringType),  # Cost as string (decimal) - may come as number from API
        th.Property("is_included", th.BooleanType),  # Whether product is included in consignment
        th.Property("status", th.StringType),  # Status like "RECEIVE_SUCCESS"
        
        # Additional fields that may be present in API response
        th.Property("product_sku", th.StringType),  # Product SKU if available
        th.Property("deleted_at", th.DateTimeType),  # Deletion timestamp if product was deleted
        
        # Timestamps
        th.Property("created_at", th.DateTimeType),
        th.Property("updated_at", th.DateTimeType),
    ).to_dict()
    
    def post_process(self, row: dict, context: Optional[dict]) -> dict:
        """Add consignment_id to each record from context and normalize numeric fields to strings.
        
        This ensures each consignment product record includes the parent consignment ID.
        Also converts count, received, and cost from numbers to strings if needed,
        as the API may return these as either numbers or strings.
        """
        if context:
            row["consignment_id"] = context.get("consignment_id")
        
        # Convert numeric fields to strings if they are numbers
        # The API may return these as numbers (e.g., 5) or strings (e.g., "10.00000")
        for field in ["count", "received", "cost"]:
            if field in row and row[field] is not None:
                if isinstance(row[field], (int, float)):
                    # Convert number to string, preserving decimal precision
                    if isinstance(row[field], float):
                        row[field] = f"{row[field]:.5f}".rstrip('0').rstrip('.')
                    else:
                        row[field] = str(row[field])
        
        return row
