#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
    Prestapyt is a library for Python to interact with the PrestaShop's Web Service API.
    Prestapyt is a direct port of the PrestaShop PHP API Client, PSWebServiceLibrary.php

    Credits:
    Thanks to Prestashop SA for their PHP API Client PSWebServiceLibrary.php
    Thanks to Alex Dean for his port of PSWebServiceLibrary.php to the Scala language (https://github.com/orderly/prestashop-scala-client)
    from which I also inspired my library.

    Questions, comments? guewen.baconnier@gmail.com
"""

__author__ = "Guewen Baconnier <guewen.baconnier@gmail.com>"
__version__ = "0.2.0"

import urllib
import httplib2
import xml2dict
import dict2xml
import unicode_encode

from xml.parsers.expat import ExpatError
from distutils.version import LooseVersion
try:
    from xml.etree import cElementTree as ElementTree
except ImportError, e:
    from xml.etree import ElementTree


class PrestaShopWebServiceError(Exception):
    """Generic PrestaShop WebServices error class

    To catch these, you need to import it in you code e.g. :
    from prestapyt import PrestaShopWebServiceError
    """

    def __init__(self, msg, error_code=None):
        self.error_code = error_code
        self.msg = msg

    def __str__(self):
        return repr(self.msg)


class PrestaShopAuthenticationError(PrestaShopWebServiceError):
    pass


class PrestaShopWebService(object):

    MIN_COMPATIBLE_VERSION = '1.4.0.17'
    MAX_COMPATIBLE_VERSION = '1.4.7.5'

    def __init__(self, api_url, api_key, parse_type='xml', debug=False, headers=None, client_args=None):
        """
        Create an instance of PrestashopWebService.

        In your code, you can use :
        from prestapyt import PrestaShopWebService, PrestaShopWebServiceError

        try:
            prestashop = PrestaShopWebService.new('http://localhost:8080/api', 'BVWPFFYBT97WKM959D7AVVD0M4815Y1L')
        rescue PrestaShopWebServiceError, e:
            print str(e)
            ...

        @param api_url: Root URL for the shop
        @param api_key: Authentification key
        @param parse_type: 'xml' or 'dict' default parse type
        @param debug: Debug mode Activated (True) or deactivated (False)
        @param headers: Custom header, is a dict accepted by httplib2 as instance {'User-Agent': 'Schkounitz'}
        @param client_args: Dict of extra arguments for HTTP Client (httplib2) as instance {'timeout': 10.0}
        """
        if client_args is None: client_args = {}

        # required to hit prestashop
        self._api_url = api_url
        self._api_key = api_key

        # add a trailing slash to the url if there is not one
        if not self._api_url.endswith('/'):
            self._api_url += '/'

        # add a trail /api/ if there is not
        if not self._api_url.endswith('/api/'):
            self._api_url += 'api/'

        # optional arguments
        self.debug = debug
        self.client_args = client_args
        self.parse_type = parse_type

        # use header you coders you want, otherwise, use a default
        self.headers = headers
        if self.headers is None:
            self.headers = {'User-agent': 'Prestapyt: Python Prestashop Library'}

    def _check_status_code(self, status_code):
        """
        Take the status code and throw an exception if the server didn't return 200 or 201 code
        @param status_code: status code returned by the server
        @return: True or raise an exception PrestaShopWebServiceError
        """
        message_by_code = {204: 'No content',
                           400: 'Bad Request',
                           401: 'Unauthorized',
                           404: 'Not Found',
                           405: 'Method Not Allowed',
                           500: 'Internal Server Error',}

        error_label = ('This call to PrestaShop Web Services failed and '
                       'returned an HTTP status of %d. That means: %s.')
        if status_code in (200, 201):
            return True
        elif status_code == 401:
            raise PrestaShopAuthenticationError(error_label
                                % (status_code, message_by_code[status_code]), status_code)
        elif status_code in message_by_code:
            raise PrestaShopWebServiceError(error_label
                    % (status_code, message_by_code[status_code]), status_code)
        else:
            raise PrestaShopWebServiceError(("This call to PrestaShop Web Services returned "
                                            "an unexpected HTTP status of: %d")
                                            % (status_code,), status_code)

    def _check_version(self, version):
        """
        Check if this library is compatible with the called PrestaShop WebService

        @param version: version returned by the PrestaShop webservice
        @return: True if the library is compatible. Otherwise raise an error PrestaShopWebServiceError
        """
        if version:
            if not (LooseVersion(self.MIN_COMPATIBLE_VERSION) <
                    LooseVersion(version) <
                    LooseVersion(self.MAX_COMPATIBLE_VERSION)):
                raise PrestaShopWebServiceError(
                    ("This library is not compatible with this version of PrestaShop (%s). "
                     "Please upgrade/downgrade this library")
                    % (version,))
        return True

    def _execute(self, url, method, body=None, add_headers=None):
        """
        Execute a request on the PrestaShop Webservice

        @param url: full url to call
        @param method: GET, POST, PUT, DELETE, HEAD
        @param body: for PUT (edit) and POST (add) only, the xml sent to PrestaShop
        @param add_headers: additional headers merged on the instance's headers
        @return: tuple with (status code, header, content) of the response
        """
        if add_headers is None: add_headers = {}

        client = httplib2.Http(**self.client_args)
        # Prestashop use the key as username without password
        client.add_credentials(self._api_key, False)
        client.follow_all_redirects = True

        if self.debug:
            print "Execute url: %s / method: %s" % (url, method)

        request_headers = self.headers.copy()
        request_headers.update(add_headers)

        header, content = client.request(url, method, body=body, headers=request_headers)
        status_code = int(header['status'])
        self._check_status_code(status_code)
        self._check_version(header.get('psws-version'))

        if self.debug: # TODO better debug logs
            print ("Response code: %s\nResponse headers:\n%s\nResponse body:\n%s"
                   % (status_code, header, content))

        return status_code, header, content

    def _parse(self, content, parse_type=None):
        """
        Parse the response of the webservice, assumed to be a XML in utf-8

        @param content: response from the webservice
        @param parse_type: 'xml' or 'dict', type of object to be returned by the request, if not given,
                            the default one given at initialization will be used
        @return: an ElementTree of the content
        """
        if not content:
            raise PrestaShopWebServiceError('HTTP response is empty')
        if parse_type is None:
            parse_type = self.parse_type

        try:
            parsed_content = ElementTree.fromstring(content)
        except ExpatError, err:
            raise PrestaShopWebServiceError('HTTP XML response is not parsable : %s' % (err,))
        if parse_type == 'dict':
            parsed_content = xml2dict.ET2dict(parsed_content)
        elif parse_type != 'xml':
            raise Exception("Code error. Parse type %s not supported!" % (parse_type,))
        return parsed_content

    def _validate(self, options):
        """
        Check options against supported options
        (reference : http://doc.prestashop.com/display/PS14/Cheat+Sheet_+Concepts+Outlined+in+this+Tutorial)
        @param options: dict of options to use for the request
        @return: True if valid, else raise an error PrestaShopWebServiceError
        """
        if not isinstance(options, dict):
            raise PrestaShopWebServiceError('Parameters must be a instance of dict')
        supported = ('filter', 'display', 'sort', 'limit', 'schema')
        # filter[firstname] (as e.g.) is allowed, so check only the part before a [
        unsupported = set([param.split('[')[0] for param in options]).difference(supported)
        if unsupported:
            raise PrestaShopWebServiceError('Unsupported parameters: %s'
            % (', '.join(tuple(unsupported)),))
        return True

    def _options_to_querystring(self, options):
        """
        Translate the dict of options to a url form
        As instance :
        {'display': '[firstname,lastname]',
         'filter': 'filter[id]=[1|5]'}
        will returns :
        'display=[firstname,lastname]&filter[id]=[1|5]'

        @param options: dict of options for the request
        @return: string to use in the url
        """
        if self.debug:
            options.update({'debug': True})
        return urllib.urlencode(options)

    def add(self, resource, content):
        """
        Add (POST) a resource. The content can be a dict of values to create.

        @param resource: type of resource to create
        @param content: Full XML as string or dict of new resource values.
        If a dict is given, it will be converted to XML with the necessary root tag ie:
            <prestashop>[[dict converted to xml]]</prestashop>
        @return: an ElementTree of the response from the web service
        """
        if isinstance(content, dict):
            root_content = {'prestashop': content}
            content = dict2xml.dict2xml(root_content)
        return self.add_with_url(self._api_url + resource, content)

    def add_with_url(self, url, xml):
        """
        Add (POST) a resource

        @param url: A full URL which for the resource type to create
        @param xml: Full XML as string of new resource.
        @return: an ElementTree of the response from the web service
        """
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        return self._parse(self._execute(url, 'POST', body=urllib.urlencode({'xml': xml}), add_headers=headers)[2])

    def get(self, resource, resource_id=None, options=None, parse_type=None):
        """
        Retrieve (GET) a resource

        @param resource: type of resource to retrieve
        @param resource_id: optional resource id to retrieve
        @param options: Optional dict of parameters (one or more of
                        'filter', 'display', 'sort', 'limit', 'schema')
        @param parse_type: 'xml' or 'dict' to specify the return type
        @return: an ElementTree or a dict of the response from the web service according to parse_type
                 Remove root keys ['prestashop'] from the message
        """
        full_url = self._api_url + resource
        if resource_id is not None:
            full_url += "/%s" % (resource_id,)
        if options is not None:
            self._validate(options)
            full_url += "?%s" % (self._options_to_querystring(options),)
        return self.get_with_url(full_url, parse_type=parse_type)

    def get_with_url(self, url, parse_type=None):
        """
        Retrieve (GET) a resource from a full URL

        @param url: An URL which explicitly sets the resource type and ID to retrieve
        @return: an ElementTree or dict of the response according to parse_type
                 full response, does not remove root tags
        """
        response = self._parse(self._execute(url, 'GET')[2], parse_type=parse_type)
        if isinstance(response, dict):
            response = response['prestashop']
        return response

    def head(self, resource, resource_id=None, options=None):
        """
        Head method (HEAD) a resource

        @param resource: type of resource to retrieve
        @param resource_id: optional resource id to retrieve
        @param options: Optional dict of parameters (one or more of 'filter', 'display', 'sort', 'limit', 'schema')
        @return: the header of the response as a dict
        """
        full_url = self._api_url + resource
        if resource_id is not None:
            full_url += "/%s" % (resource_id,)
        if options is not None:
            self._validate(options)
            full_url += "?%s" % (self._options_to_querystring(options),)
        return self.head_with_url(full_url)

    def head_with_url(self, url):
        """
        Head method (HEAD) a resource from a full URL

        @param url: An URL which explicitly sets the resource type and ID to retrieve
        @return: the header of the response as a dict
        """
        return self._execute(url, 'HEAD')[1]

    def edit(self, resource, resource_id, content):
        """
        Edit (PUT) a resource. The content can be a dict of values to update.

        @param resource: type of resource to edit
        @param resource_id: id of the resource to edit
        @param content: modified XML as string or dict of the resource.
        If a dict is given, it will be converted to XML with the necessary root tags ie:
        <prestashop>[[dict converted to xml]]</prestashop>
        @return: an ElementTree of the Webservice's response
        """
        if isinstance(content, dict):
            root_content = {'prestashop': content}
            content = dict2xml.dict2xml(root_content)
        full_url = "%s%s/%s" % (self._api_url, resource, resource_id)
        return self.edit_with_url(full_url, content)

    def edit_with_url(self, url, xml):
        """
        Edit (PUT) a resource from a full URL

        @param url: an full url to edit a resource
        @param xml: modified XML as string of the resource.
        @return: an ElementTree of the Webservice's response
        """
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        print xml
        return self._parse(self._execute(url, 'PUT', body=unicode_encode.encode(xml), add_headers=headers)[2])

    def delete(self, resource, resource_ids):
        """
        Delete (DELETE) a resource.

        @param resource: type of resource to retrieve
        @param resource_ids: int or list of ids to delete
        @return: True if delete is done, raise an error PrestaShopWebServiceError if missed
        """
        full_url = self._api_url + resource
        if isinstance(resource_ids, (tuple, list)):
            full_url += "/?id=[%s]" % \
                        (','.join([str(resource_id) for resource_id in resource_ids]),)
        else:
            full_url += "/%s" % str(resource_ids)
        return self.delete_with_url(full_url)

    def delete_with_url(self, url):
        """
        Delete (DELETE) a resource.

        @param url: full URL to delete a resource
        @return: True if delete is done, raise an error PrestaShopWebServiceError if missed
        """
        self._execute(url, 'DELETE')
        return True

if __name__ == '__main__':
    prestashop = PrestaShopWebService('http://localhost:8080/api',
                                      'BVWPFFYBT97WKM959D7AVVD0M4815Y1L',
                                      parse_type='dict')
    #prestashop.debug = True
    from pprint import pprint
    pprint(prestashop.get(''))
    pprint(prestashop.head(''))
    pprint(prestashop.get('addresses', 1, parse_type='xml'))
    pprint(prestashop.get('addresses', 1))
    pprint(prestashop.get('products', 1))

    address_data = prestashop.get('addresses', 1)
    address_data['address']['firstname'] = 'Robert'
    prestashop.edit('addresses', 1, address_data)

    address_data = prestashop.get('addresses', options={'schema': 'blank'})
    address_data['address'].update({'address1': '1 Infinite Loop',
                                    'address2': '',
                                    'alias': 'manufacturer',
                                    'city': 'Cupertino',
                                    'company': '',
                                    'deleted': '0',
                                    'dni': '',
                                    'firstname': 'STEVE',
                                    'id_country': '21',
                                    'id_customer': '',
                                    'id_manufacturer': '1',
                                    'id_state': '5',
                                    'id_supplier': '',
                                    'lastname': 'JOBY',
                                    'other': '',
                                    'phone': '(800) 275-2273',
                                    'phone_mobile': '',
                                    'postcode': '95014',
                                    'vat_number': ''})
    prestashop.add('addresses', address_data)
