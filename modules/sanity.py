#!/usr/bin/env python

# local imports
from . import utils

import cymruwhois
import bottle
import requests
import re


def validate_data(conf, paste_data):
    '''
    Basic data validation.
    Returns (valid, error_message).
    '''
    codetype = type(paste_data['code'])
    error = None

    if max(0, bottle.request.content_length) > bottle.request.MEMFILE_MAX:
        error = 'This request is too large to process. ERR:991'

    elif codetype != str and codetype != bottle.FileUpload:
        error = 'Invalid code type submitted. ERR:280'

    elif not re.match(r'^[a-zA-Z\[\]\\{}|`\-_][a-zA-Z0-9\[\]\\{}|`\-_]*$', paste_data['name']):
        error = 'Invalid input detected. ERR:925'

    elif paste_data['phone'] != '':
        error = 'Your post triggered our spam filters! ERR:228'

    for k in ['code', 'private', 'syntax', 'name']:
        if paste_data[k] == '':
            error = 'All fields need to be filled out. ERR:577'

    if error:
        return (False, error)
    return (True, None)


def check_captcha(secret, answer, addr=None):
    '''
    Returns True if captcha response is valid.
    '''
    provider = 'https://www.google.com/recaptcha/api/siteverify'
    qs = {
        'secret': secret,
        'response': answer}
    if addr:
        qs['remoteip'] = addr

    response = requests.get(provider, params=qs)
    result = response.json()

    return result['success']


def address_blacklisted(cache, addr):
    '''
    Returns True if address is currently blacklisted.
    '''
    subnet = _addr_subnet(addr)
    if not subnet:
        # Fail open?
        return None
    if cache.exists('ipblock:{}'.format(utils.sha512(subnet))):
        return True
    return False


def blacklist_address(cache, addr):
    '''
    Add address to blacklist.
    Returns True if successfully added or False if error encountered.
    '''
    subnet = _addr_subnet(addr)
    if not subnet:
        return False
    cache.setex('ipblock:{}'.format(utils.sha512(subnet)), 345600, 'nil')
    return True


def whitelist_address(cache, addr):
    '''
    Remove address from blacklist.
    Returns True if successfully removed or False if error encountered.
    '''
    subnet = _addr_subnet(addr)
    if not subnet:
        return False
    cache.delete('ipblock:{}'.format(utils.sha512(subnet)))
    cache.delete('ipgrey:{}'.format(utils.sha512(subnet)))
    return True


def address_greylisted(cache, addr):
    '''
    Returns True if address is currently greylisted.
    '''
    subnet = _addr_subnet(addr)
    if not subnet:
        # Fail open?
        return None
    if cache.exists('ipgrey:{}'.format(utils.sha512(subnet))):
        return True
    return False


def greylist_address(cache, addr):
    '''
    Add an address to grey listing: don't block, don't relay.
    Returns True if successfully added or False if error encountered.
    '''
    subnet = _addr_subnet(addr)
    if not subnet:
        return False
    cache.setex('ipgrey:{}'.format(utils.sha512(subnet)), 345600, 'nil')
    return True


def _addr_subnet(addr):
    '''
    Returns a subnet for an address.
    '''
    client = cymruwhois.Client()
    try:
        resp = client.lookup(addr)
        return resp.prefix
    except:
        return None
