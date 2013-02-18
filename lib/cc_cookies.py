# -*- coding: utf-8 -*-

import threading

_local_locker = threading.local()

def init_cookies():
    """Init the cookies associated with the current request."""
    _local_locker._cookies = []

def add_cookie(cookie):
    """Sets the cookies associated with the current request."""
    if hasattr(_local_locker, "_cookies"):
        _local_locker._cookies.append(cookie)
    else:
        raise Exception("_local_locker._cookies have not inited")

def clear_cookies():
    """Clear the cookies associated with the current request."""
    _local_locker._cookies = []

def _update_to_headers(headers):
    for cookie in _local_locker._cookies:
        headers.append(('Set-Cookie', str(cookie).split(': ')[1]))
    return headers

def _update_django_cookies(response):
    for cookie in _local_locker._cookies:
        response.cookies.update(cookie)
    return response

class CCCookiesWSGIMiddleware(object):
    "WSGI Middleware handle cookies"
    def __init__(self, app):
        self.app = app
        init_cookies()

    def __call__(self, environ, start_response):
        clear_cookies()
        def my_start_response(status, headers, exc_info=None):
            _update_to_headers(headers)
            return start_response(status, headers, exc_info)
        return self.app(environ, my_start_response)

class CCCookiesDjangoWSGIMiddleware(object):
    "Django Middleware handle cookies"
    def __init__(self):
        init_cookies()

    def process_request(self, request):
        clear_cookies()

    def process_response(self, request, response):
        return _update_django_cookies(response)







