# -*- coding: utf-8 -*-

import logging
from functools import wraps
from google.appengine.api import memcache
from google.appengine.api import users

from settings import CACHE_ENABLED

class memcached(object):
    '''
    Decorate any function or method whose return value to keep in memcache

    @param key: Can be a string or a function (takes the same arguments as the
                wrapped function, and returns a string key)
    @param time: Optional expiration time, either relative number of seconds from
                 current time (up to 1 month), or an absolute Unix epoch time
    @param namespace: An optional namespace for the key

    @note: Set CACHE_ENABLED to False to globally disable memcache
    @note: Won't cache if the inner function returns None
    '''
    def __init__(self, key, time=0, namespace=None):
        self.key = key
        self.time = time
        self.namespace = namespace

    def __call__(self, f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            key = self.key(*args, **kwargs) if callable(self.key) else self.key

            data = memcache.get(key, namespace=self.namespace)
            if data is not None: return data

            logging.debug('Memcache for %s missed, key = %s@%s', f.__name__, key, self.namespace)
            data = f(*args, **kwargs)
            if data is not None: memcache.set(key, data, self.time, namespace=self.namespace)
            return data

        return wrapped if CACHE_ENABLED else f

class responsecached(object):
    '''
    Decorate RequestHandler.get/post/etc. to keep the response in memcache
    A convenient wrapper of memcached

    @note: Multiple memcache items may be generated using the default key algorithm
    '''
    def __init__(self, time=0, key=None, namespace='response', cacheableStatus=(200,), onlyAnonymous=False):
        self.time = time
        self.key = key if key else lambda h, *_: h.request.path_qs
        self.namespace = namespace
        self.cacheableStatus = cacheableStatus
        self.onlyAnonymous = onlyAnonymous

    def __call__(self, f):
        @wraps(f)
        def wrapped(handler, *args):
            if self.onlyAnonymous and users.get_current_user():
                f(handler, *args)
                return

            @memcached(self.key, self.time, self.namespace)
            def getResponse(handler, *args):
                f(handler, *args)
                return handler.response if handler.response.status in self.cacheableStatus else None

            # In `WSGIApplication.__call__`, `handler.response` is just a reference
            # of the local variable `response`, whose `wsgi_write` method is called.
            # So just assign a new response object to `handler.response` will not work.
            handler.response.__dict__ = getResponse(handler, *args).__dict__

        return wrapped
