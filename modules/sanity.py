#!/usr/bin/env python

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
