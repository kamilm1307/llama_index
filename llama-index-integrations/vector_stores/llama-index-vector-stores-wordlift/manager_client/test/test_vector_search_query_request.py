"""
Manager

Subscription management and related services.

The version of the OpenAPI document: 1.0
Contact: hello@wordlift.io
Generated by OpenAPI Generator (https://openapi-generator.tech)

Do not edit the class manually.
"""


import unittest

from manager_client.models.vector_search_query_request import VectorSearchQueryRequest


class TestVectorSearchQueryRequest(unittest.TestCase):
    """VectorSearchQueryRequest unit test stubs"""

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def make_instance(self, include_optional) -> VectorSearchQueryRequest:
        """Test VectorSearchQueryRequest
        include_option is a boolean, when False only required
        params are included, when True both required and
        optional params are included
        """
        # uncomment below to create an instance of `VectorSearchQueryRequest`
        """
        model = VectorSearchQueryRequest()
        if include_optional:
            return VectorSearchQueryRequest(
                filters = [
                    manager_client.models.filter.Filter(
                        key = '',
                        operator = 'EQ',
                        value = '', )
                    ],
                query_embedding = [
                    1.337
                    ],
                query_string = '',
                similarity_top_k = 1
            )
        else:
            return VectorSearchQueryRequest(
        )
        """

    def testVectorSearchQueryRequest(self):
        """Test VectorSearchQueryRequest"""
        # inst_req_only = self.make_instance(include_optional=False)
        # inst_req_and_optional = self.make_instance(include_optional=True)


if __name__ == "__main__":
    unittest.main()
