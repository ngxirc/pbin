#!/usr/bin/env python

# local imports
from . import utils

import json
import socket


def send_message(conf, cache, paste, paste_id):
    '''
    Send notification to channels
    '''
    host = conf.get('bottle', 'relay_host')
    port = int(conf.get('bottle', 'relay_port'))
    pw = conf.get('bottle', 'relay_pass')

    # Build the message to send to the channel
    if paste['forked_from']:
        orig = json.loads(cache.get('paste:' + paste['forked_from']))
        message = ''.join(['Paste from ', orig['name'],
                           ' forked by ', paste['name'], ': [ ',
                           conf.get('bottle', 'url'), paste_id, ' ]'])
    else:
        message = ''.join(['Paste from ', paste['name'], ': [ ',
                           conf.get('bottle', 'url'), paste_id, ' ]'])

    # Get list of relay channels
    channels = None
    # Always admin channels, only normal channels if paste is not private
    if conf.get('bottle', 'relay_admin_chan') is not None:
        channels = conf.get('bottle', 'relay_admin_chan')
        if conf.get('bottle', 'relay_chan') is not None and not utils.str2bool(paste['private']):
            channels = ''.join([channels, ',', conf.get('bottle', 'relay_chan')])
    else:
        if conf.get('bottle', 'relay_chan') is not None and not utils.str2bool(paste['private']):
            channels = conf.get('bottle', 'relay_chan')

    # For each channel, send the relay server a message
    # Note: Irccat does not use traditional channel names
    if channels:
        for channel in channels.split(','):
            try:
                s = socket.create_connection((host, port))
                s.send('{};{};{}\n'.format(channel, pw, message))
                s.close()
            except:
                print('Unable to send message to channel: {}'.format(channel))
