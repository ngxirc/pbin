#!/usr/bin/env python

import bottle
import requests
import re

def validate_data(conf, paste_data):
    '''
    Basic data validation.
    Returns (valid, error_message).
    '''
    if max(0, bottle.request.content_length) > bottle.request.MEMFILE_MAX:
        return (False, 'This request is too large to process. ERR:991')

    for k in ['code', 'private', 'syntax', 'name']:
        if paste_data[k] == '':
            return (False, 'All fields need to be filled out. ER:577')

    if not re.match(r'^[a-zA-Z\[\]\\{}|`\-_][a-zA-Z0-9\[\]\\{}|`\-_]*$', paste_data['name']):
        return (False, 'Invalid input detected. ERR:925')

    if paste_data['phone'] != '':
        return (False, 'Your post triggered our spam filters! ERR:228')

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
