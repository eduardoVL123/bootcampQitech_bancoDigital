import os
from connectors.rest_connector import RestConnector
from errors import NotFoundCustomer

class CustomerConnector(RestConnector):
    def __init__(self):
        super().__init__(
            class_name=__name__,
            base_url=os.environ.get("CUSTOMER_API_URL", "http://customer-api:3000"),
            timeout=5,
            internal_token=os.environ.get("INTERNAL_TOKEN", "default_token"),
        )

    def get_by_key(self, customer_key: str):
        response = self.send(f"/customer/{customer_key}", "GET")
        if response.status == 404:
            raise NotFoundCustomer(customer_key)
        if response.status != 200:
            raise Exception(f"Failed to fetch customer: {response.status}")
        
        # We need an object that mimics the old customer model (has an 'id' attribute)
        class DummyCustomer:
            def __init__(self, data):
                self.id = data.get("id") # Warning: customer-api needs to return the internal ID or we change account logic
                self.customer_key = data.get("customer_key")
        
        return DummyCustomer(response.json)
