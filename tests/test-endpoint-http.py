import io
import json
import urllib.error
import urllib.request

from nose.tools import eq_
from unittest.mock import patch
from sgqlc.endpoint.http import HTTPEndpoint, add_query_to_url
from sgqlc.types import Schema, Type, Field, String, ArgDict, Arg, Input, Enum
from sgqlc.operation import Operation

test_url = 'http://some-server.com/graphql'

graphql_query = '''
query GitHubRepoIssues($repoOwner: String!, $repoName: String!) {
  repository(owner: $repoOwner, name: $repoName) {
    issues(first: 100) {
      nodes {
        number
        title
      }
    }
  }
}
'''

graphql_response_ok = b'''
{
  "data": {
    "repository": {
      "issues": {
        "nodes": [
          {
            "number": 1,
            "title": "unit tests: sgqlc.types"
          }
        ]
      }
    }
  }
}'''

graphql_response_error = b'''
{
  "errors": [{
    "message": "Server Reported Error",
    "locations": [{"line": 1, "column": 1}]
  }, {
    "message": "Other Message",
    "path": ["repository", "issues"]
  }]
}
'''

graphql_response_json_error = b'''
{
  "data": {
'''

# -- Test Helpers --


def get_json_exception(s):
    try:
        json.loads(s)
        return None
    except json.JSONDecodeError as e:
        return e


def configure_mock_urlopen(mock_urlopen, payload):
    if isinstance(payload, Exception):
        mock_urlopen.side_effect = payload
    else:
        mock_urlopen.return_value = io.BytesIO(payload)


def check_request_url(req, expected):
    split = urllib.parse.urlsplit(req.full_url)
    received = urllib.parse.SplitResult(
        split.scheme,
        split.netloc,
        split.path,
        None,
        split.fragment,
    ).geturl()
    eq_(received, expected)


def check_request_headers_(req, headers, name):
    if not headers:
        return
    if isinstance(headers, dict):
        headers = headers.items()
    for k, v in headers:
        g = req.get_header(k)
        eq_(g, v, 'Failed {} header {}: {!r} != {!r}'.format(name, k, v, g))


def check_request_headers(req, base_headers, extra_headers):
    eq_(req.get_header('Accept'), 'application/json; charset=utf-8')
    if req.method == 'POST':
        eq_(req.get_header('Content-type'), 'application/json; charset=utf-8')
    check_request_headers_(req, base_headers, 'base')
    check_request_headers_(req, extra_headers, 'extra')


def get_request_url_query(req):
    split = urllib.parse.urlsplit(req.full_url)
    query = urllib.parse.parse_qsl(split.query)
    if isinstance(query, list):
        query = dict(query)
    return query


def check_request_variables(req, variables):
    if req.method == 'POST':
        post_data = json.loads(req.data)
        received = post_data.get('variables')
    else:
        query = get_request_url_query(req)
        received = json.loads(query.get('variables', 'null'))

    eq_(received, variables)


def check_request_operation_name(req, operation_name):
    if req.method == 'POST':
        post_data = json.loads(req.data)
        received = post_data.get('operationName')
    else:
        query = get_request_url_query(req)
        received = query.get('operationName')

    eq_(received, operation_name)


def check_request_query(req, query):
    if req.method == 'POST':
        post_data = json.loads(req.data)
        received = post_data.get('query')
    else:
        query_data = get_request_url_query(req)
        received = query_data.get('query')

    if isinstance(query, bytes):
        query = query.decode('utf-8')

    eq_(received, query)


def check_mock_urlopen(mock_urlopen,
                       method='POST',
                       timeout=None,
                       base_headers=None,
                       extra_headers=None,
                       variables=None,
                       operation_name=None,
                       query=None,  # defaults to `graphql_query`
                       ):
    assert mock_urlopen.called
    args = mock_urlopen.call_args
    req = args[0][0]
    eq_(req.method, method)
    check_request_url(req, test_url)
    check_request_headers(req, base_headers, extra_headers)
    check_request_variables(req, variables)
    check_request_operation_name(req, operation_name)
    check_request_query(req, query or graphql_query)
    eq_(args[1]['timeout'], timeout)


# -- Actual Tests --


@patch('urllib.request.urlopen')
def test_basic(mock_urlopen):
    'Test if basic usage with only essential parameters works'

    configure_mock_urlopen(mock_urlopen, graphql_response_ok)

    endpoint = HTTPEndpoint(test_url)
    data = endpoint(graphql_query)
    eq_(data, json.loads(graphql_response_ok))
    check_mock_urlopen(mock_urlopen)
    eq_(str(endpoint),
        'HTTPEndpoint('
        + 'url={}, '.format(test_url)
        + 'base_headers={}, timeout=None, method=POST)')


@patch('urllib.request.urlopen')
def test_basic_bytes_query(mock_urlopen):
    'Test if query with type bytes works'

    configure_mock_urlopen(mock_urlopen, graphql_response_ok)

    endpoint = HTTPEndpoint(test_url)
    data = endpoint(graphql_query.encode('utf-8'))
    eq_(data, json.loads(graphql_response_ok))
    check_mock_urlopen(mock_urlopen)


@patch('urllib.request.urlopen')
def test_basic_operation_query(mock_urlopen):
    'Test if query with type sgqlc.operation.Operation() works'

    configure_mock_urlopen(mock_urlopen, graphql_response_ok)

    schema = Schema()

    # MyType and Query may be declared if doctests were processed by nose
    if 'MyType' in schema:
        schema -= schema.MyType

    if 'Query' in schema:
        schema -= schema.Query

    class MyType(Type):
        __schema__ = schema
        i = int

    class Query(Type):
        __schema__ = schema
        my_type = MyType

    op = Operation(Query)
    op.my_type.i()

    endpoint = HTTPEndpoint(test_url)
    data = endpoint(op)
    eq_(data, json.loads(graphql_response_ok))
    check_mock_urlopen(mock_urlopen, query=bytes(op))


def test_input_parameter_query():
    schema = Schema()

    if 'Query' in schema:
        schema -= schema.Query

    if 'NestedThing' in schema:
        schema -= schema.NestedThing

    if 'InputThing' in schema:
        schema -= schema.InputThing

    class TestEnum(Enum):
        __choices__ = ['def', 'ghi']

    class NestedThing(Input):
        __schema__ = schema
        nested_value = Field(String)
        nested_enum = Field(TestEnum)

        @staticmethod
        def create(nested_value, nested_enum):
            return NestedThing(json_data={k: v for k, v in {
                'nested_value': nested_value.__to_internal_json_value__()
                if getattr(nested_value, '__to_internal_json_value__', None)
                else nested_value,
                'nested_enum': nested_enum.__to_internal_json_value__()
                if getattr(nested_enum, '__to_internal_json_value__', None)
                else nested_enum,
            }.items() if k and v})

    class InputThing(Input):
        __schema__ = schema
        nest = Field(NestedThing)

        @staticmethod
        def create(nest):
            return InputThing(json_data={k: v for k, v in {
                'nest': nest.__to_internal_json_value__()
                if getattr(nest, '__to_internal_json_value__', None) else nest,
            }.items() if k and v})

    class Query(Type):
        __schema__ = schema
        thing = Field(String,
                      args=ArgDict((('param_value', Arg(InputThing)),)))

    op = Operation(Query)
    op.thing(param_value=InputThing.create(nest=NestedThing.create(
        nested_value="abc",
        nested_enum="def")))
    assert 'nestedValue: "abc"' in str(op)
    assert 'nestedEnum: def' in str(op)


@patch('urllib.request.urlopen')
def test_headers(mock_urlopen):
    'Test if all headers are passed'

    configure_mock_urlopen(mock_urlopen, graphql_response_ok)

    base_headers = {
        'Xpto': 'abc',
    }
    extra_headers = {
        'Extra': '123',
    }

    endpoint = HTTPEndpoint(test_url, base_headers=base_headers)
    data = endpoint(graphql_query, extra_headers=extra_headers)
    eq_(data, json.loads(graphql_response_ok))
    check_mock_urlopen(mock_urlopen,
                       base_headers=base_headers,
                       extra_headers=extra_headers)


@patch('urllib.request.urlopen')
def test_default_timeout(mock_urlopen):
    'Test if default timeout is respected'

    configure_mock_urlopen(mock_urlopen, graphql_response_ok)

    timeout = 123

    endpoint = HTTPEndpoint(test_url, timeout=timeout)
    data = endpoint(graphql_query)
    eq_(data, json.loads(graphql_response_ok))
    check_mock_urlopen(mock_urlopen, timeout=timeout)


@patch('urllib.request.urlopen')
def test_call_timeout(mock_urlopen):
    'Test if call timeout takes precedence over default'

    configure_mock_urlopen(mock_urlopen, graphql_response_ok)

    timeout = 123

    endpoint = HTTPEndpoint(test_url, timeout=1)
    data = endpoint(graphql_query, timeout=timeout)
    eq_(data, json.loads(graphql_response_ok))
    check_mock_urlopen(mock_urlopen, timeout=timeout)


@patch('urllib.request.urlopen')
def test_variables(mock_urlopen):
    'Test if variables are passed to server'

    configure_mock_urlopen(mock_urlopen, graphql_response_ok)

    variables = {'repoOwner': 'owner', 'repoName': 'name'}

    endpoint = HTTPEndpoint(test_url)
    data = endpoint(graphql_query, variables)
    eq_(data, json.loads(graphql_response_ok))
    check_mock_urlopen(mock_urlopen, variables=variables)


@patch('urllib.request.urlopen')
def test_operation_name(mock_urlopen):
    'Test if operation name is passed to server'

    configure_mock_urlopen(mock_urlopen, graphql_response_ok)

    operation_name = 'xpto'

    endpoint = HTTPEndpoint(test_url)
    data = endpoint(graphql_query, operation_name=operation_name)
    eq_(data, json.loads(graphql_response_ok))
    check_mock_urlopen(mock_urlopen, operation_name=operation_name)


@patch('urllib.request.urlopen')
def test_json_error(mock_urlopen):
    'Test if broken server responses (invalid JSON) is handled'

    configure_mock_urlopen(mock_urlopen, graphql_response_json_error)

    endpoint = HTTPEndpoint(test_url)
    data = endpoint(graphql_query)

    exc = get_json_exception(graphql_response_json_error)
    got_exc = data['errors'][0].pop('exception')
    assert isinstance(got_exc, json.JSONDecodeError), \
        '{} is not json.JSONDecodeError'.format(type(got_exc))

    eq_(data, {
        'errors': [{
            'message': str(exc),
            'body': graphql_response_json_error.decode('utf-8'),
        }],
        'data': None,
    })
    check_mock_urlopen(mock_urlopen)


@patch('urllib.request.urlopen')
def test_get(mock_urlopen):
    'Test if HTTP method GET request works'

    configure_mock_urlopen(mock_urlopen, graphql_response_ok)

    base_headers = {
        'Xpto': 'abc',
    }
    extra_headers = {
        'Extra': '123',
    }
    variables = {'repoOwner': 'owner', 'repoName': 'name'}
    operation_name = 'xpto'

    endpoint = HTTPEndpoint(test_url, base_headers=base_headers, method='GET')
    data = endpoint(graphql_query,
                    extra_headers=extra_headers,
                    variables=variables,
                    operation_name=operation_name,
                    )
    eq_(data, json.loads(graphql_response_ok))
    check_mock_urlopen(mock_urlopen,
                       method='GET',
                       base_headers=base_headers,
                       extra_headers=extra_headers,
                       variables=variables,
                       operation_name=operation_name,
                       )
    eq_(str(endpoint),
        'HTTPEndpoint('
        + 'url={}, '.format(test_url)
        + 'base_headers={}, '.format(base_headers)
        + 'timeout=None, method=GET)',
        )


@patch('urllib.request.urlopen')
def test_server_reported_error(mock_urlopen):
    'Test if GraphQL errors reported with HTTP 200 is handled properly'

    configure_mock_urlopen(mock_urlopen, graphql_response_error)

    endpoint = HTTPEndpoint(test_url)
    data = endpoint(graphql_query)
    eq_(data, json.loads(graphql_response_error))
    check_mock_urlopen(mock_urlopen)


@patch('urllib.request.urlopen')
def test_server_http_error(mock_urlopen):
    'Test if HTTP error without JSON payload is handled'

    err = urllib.error.HTTPError(
        test_url,
        500,
        'Some Error',
        {'Xpto': 'abc'},
        io.BytesIO(b'xpto'),
    )
    configure_mock_urlopen(mock_urlopen, err)

    endpoint = HTTPEndpoint(test_url)
    data = endpoint(graphql_query)
    eq_(data, {
        'errors': [{
            'message': str(err),
            'exception': err,
            'status': 500,
            'headers': {'Xpto': 'abc'},
            'body': 'xpto',
        }],
        'data': None,
    })
    check_mock_urlopen(mock_urlopen)


@patch('urllib.request.urlopen')
def test_server_http_non_conforming_json(mock_urlopen):
    'Test if HTTP error that is NOT conforming to GraphQL payload is handled'

    err = urllib.error.HTTPError(
        test_url,
        500,
        'Some Error',
        {'Content-Type': 'application/json'},
        io.BytesIO(b'{"message": "xpto"}'),
    )
    configure_mock_urlopen(mock_urlopen, err)

    endpoint = HTTPEndpoint(test_url)
    data = endpoint(graphql_query)
    eq_(data, {
        'errors': [{
            'message': str(err),
            'exception': err,
            'status': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': '{"message": "xpto"}',
        }],
        'data': None,
    })
    check_mock_urlopen(mock_urlopen)


@patch('urllib.request.urlopen')
def test_server_error_broken_json(mock_urlopen):
    'Test if HTTP error with broken JSON payload is handled'

    err = urllib.error.HTTPError(
        test_url,
        500,
        'Some Error',
        {'Content-Type': 'application/json'},
        io.BytesIO(b'xpto'),
    )
    configure_mock_urlopen(mock_urlopen, err)

    endpoint = HTTPEndpoint(test_url)
    data = endpoint(graphql_query)
    got_exc = data['errors'][0].pop('exception')
    assert isinstance(got_exc, json.JSONDecodeError), \
        '{} is not json.JSONDecodeError'.format(type(got_exc))

    eq_(data, {
        'errors': [{
            'message': str(got_exc),
            'body': 'xpto',
        }],
        'data': None,
    })
    check_mock_urlopen(mock_urlopen)


@patch('urllib.request.urlopen')
def test_server_http_graphql_error(mock_urlopen):
    'Test if HTTP error that IS conforming to GraphQL payload is handled'

    err = urllib.error.HTTPError(
        test_url,
        500,
        'Some Error',
        {'Content-Type': 'application/json'},
        io.BytesIO(graphql_response_error),
    )
    configure_mock_urlopen(mock_urlopen, err)

    endpoint = HTTPEndpoint(test_url)
    data = endpoint(graphql_query)

    expected_data = json.loads(graphql_response_error)
    expected_data.update({
        'exception': err,
        'status': 500,
        'headers': {'Content-Type': 'application/json'},
    })

    eq_(data, expected_data)
    check_mock_urlopen(mock_urlopen)


@patch('urllib.request.urlopen')
def test_server_http_single_error(mock_urlopen):
    'Test if HTTP error that a single JSON error string is handled'

    err = urllib.error.HTTPError(
        test_url,
        500,
        'Some Error',
        {'Content-Type': 'application/json'},
        io.BytesIO(b'{"errors": "a string"}'),
    )
    configure_mock_urlopen(mock_urlopen, err)

    endpoint = HTTPEndpoint(test_url)
    data = endpoint(graphql_query)

    expected_data = {'errors': [{'message': 'a string'}]}
    expected_data.update({
        'exception': err,
        'status': 500,
        'headers': {'Content-Type': 'application/json'},
    })

    eq_(data, expected_data)
    check_mock_urlopen(mock_urlopen)


@patch('urllib.request.urlopen')
def test_server_http_error_string_list(mock_urlopen):
    'Test if HTTP error that a JSON error string list is handled'

    err = urllib.error.HTTPError(
        test_url,
        500,
        'Some Error',
        {'Content-Type': 'application/json'},
        io.BytesIO(b'{"errors": ["a", "b"]}'),
    )
    configure_mock_urlopen(mock_urlopen, err)

    endpoint = HTTPEndpoint(test_url)
    data = endpoint(graphql_query)

    expected_data = {'errors': [{'message': 'a'}, {'message': 'b'}]}
    expected_data.update({
        'exception': err,
        'status': 500,
        'headers': {'Content-Type': 'application/json'},
    })

    eq_(data, expected_data)
    check_mock_urlopen(mock_urlopen)


@patch('urllib.request.urlopen')
def test_server_http_error_list_message(mock_urlopen):
    'Test if HTTP error that a JSON error with messages being a list'

    err = urllib.error.HTTPError(
        test_url,
        500,
        'Some Error',
        {'Content-Type': 'application/json'},
        io.BytesIO(b'{"errors": [{"message": [1, 2]}]}'),
    )
    configure_mock_urlopen(mock_urlopen, err)

    endpoint = HTTPEndpoint(test_url)
    data = endpoint(graphql_query)

    expected_data = {'errors': [{'message': '[1, 2]'}]}
    expected_data.update({
        'exception': err,
        'status': 500,
        'headers': {'Content-Type': 'application/json'},
    })

    eq_(data, expected_data)
    check_mock_urlopen(mock_urlopen)


# add_query_to_url():
# test paths not already tested, here just the repeated query


def test_add_query_to_url_dict_of_list():
    'Test if add_query_to_url() with extra_query as a dict-of-list works'

    url = add_query_to_url('http://domain.com?a=1&a=2', {'a': ['3', '4']})
    eq_(url, 'http://domain.com?a=1&a=2&a=3&a=4')


def test_add_query_to_url_sequence():
    'Test if add_query_to_url() with extra_query as sequence of pairs works'

    u = add_query_to_url('http://domain.com?a=1&a=2', (('a', '3'), ('a', '4')))
    eq_(u, 'http://domain.com?a=1&a=2&a=3&a=4')
