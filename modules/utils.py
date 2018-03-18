#!/usr/bin/env python

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
