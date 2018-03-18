#!/usr/bin/env python

import hashlib


def str2bool(v):
    '''
    Convert string to boolean.
    '''
    return v.lower() in ('yes', 'true', 't', 'y', '1', 'on')


def str2int(v):
    '''
    Convert string to boolean to integer.
    '''
    return int(str2bool(v))


def sha512(v):
    '''
    Returns a sha512 checksum for provided value.
    '''
    return hashlib.sha512(v).hexdigest()
