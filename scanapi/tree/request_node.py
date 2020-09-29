import logging
import requests

from scanapi.errors import HTTPMethodNotAllowedError
from scanapi.evaluators.spec_evaluator import SpecEvaluator
from scanapi.test_status import TestStatus
from scanapi.tree.testing_node import TestingNode
from scanapi.tree.tree_keys import (
    BODY_KEY,
    HEADERS_KEY,
    METHOD_KEY,
    NAME_KEY,
    PARAMS_KEY,
    PATH_KEY,
    TESTS_KEY,
    VARS_KEY,
)
from scanapi.utils import join_urls, validate_keys
from scanapi.hide_utils import hide_sensitive_info

logger = logging.getLogger(__name__)


class RequestNode:
    SCOPE = "request"
    ALLOWED_KEYS = (
        BODY_KEY,
        HEADERS_KEY,
        METHOD_KEY,
        NAME_KEY,
        PARAMS_KEY,
        PATH_KEY,
        TESTS_KEY,
        VARS_KEY,
    )
    ALLOWED_HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
    REQUIRED_KEYS = (NAME_KEY,)

    def __init__(self, spec, endpoint):
        self.spec = spec
        self.endpoint = endpoint
        self._validate()

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.full_url_path}>"

    def __getitem__(self, item):
        return self.spec[item]

    @property
    def http_method(self):
        method = self.spec.get(METHOD_KEY, "get").upper()
        if method not in self.ALLOWED_HTTP_METHODS:
            raise HTTPMethodNotAllowedError(method, self.ALLOWED_HTTP_METHODS)

        return method

    @property
    def name(self):
        return self[NAME_KEY]

    @property
    def full_url_path(self):
        base_path = self.endpoint.path
        path = str(self.spec.get(PATH_KEY, ""))
        full_url = join_urls(base_path, path)

        return self.endpoint.vars.evaluate(full_url)

    @property
    def headers(self):
        endpoint_headers = self.endpoint.headers
        headers = self.spec.get(HEADERS_KEY, {})

        return self.endpoint.vars.evaluate({**endpoint_headers, **headers})

    @property
    def params(self):
        endpoint_params = self.endpoint.params
        params = self.spec.get(PARAMS_KEY, {})

        return self.endpoint.vars.evaluate({**endpoint_params, **params})

    @property
    def body(self):
        body = self.spec.get(BODY_KEY)

        return self.endpoint.vars.evaluate(body)

    @property
    def tests(self):
        return (TestingNode(spec, self) for spec in self.spec.get("tests", []))

    def run(self):
        method = self.http_method
        url = self.full_url_path
        logger.info("Making request %s %s", method, url)

        self.endpoint.vars.update(
            self.spec.get(VARS_KEY, {}), preevaluate=False,
        )

        response = requests.request(
            method,
            url,
            headers=self.headers,
            params=self.params,
            json=self.body,
            allow_redirects=False,
        )

        self.endpoint.vars.update(
            self.spec.get(VARS_KEY, {}),
            extras={"response": response},
            preevaluate=True,
        )

        tests_results = self._run_tests()
        hide_sensitive_info(response)

        return {
            "response": response,
            "tests_results": tests_results,
            "no_failure": all(
                [
                    test_result["status"] == TestStatus.PASSED
                    for test_result in tests_results
                ]
            ),
        }

    def _run_tests(self):
        return [test.run() for test in self.tests]

    def _validate(self):
        validate_keys(
            self.spec.keys(), self.ALLOWED_KEYS, self.REQUIRED_KEYS, self.SCOPE
        )
