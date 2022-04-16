#!/usr/bin/env python

# local imports
from . import sanity

import bottle
import json


def run_cmd(conf, cache):
    '''
    Execute an administrative command.
    '''
    data = bottle.request.json
    admin_key = conf.get('bottle', 'admin_key')

    # Supported commands
    commands = {
            'blacklist_paste': _cmd_blacklist_paste,
            'bl': _cmd_blacklist_paste,
            'delete_paste': _cmd_delete_paste,
            'del': _cmd_delete_paste,
            'whitelist_address': _cmd_whitelist_address,
            'wl': _cmd_whitelist_address,
            'greylist_address': _cmd_greylist_address,
            'gl': _cmd_greylist_address}

    # Pre-flight checks
    err = None
    if not admin_key:
        err = 'No admin key configured.'
    elif not data:
        err = 'No payload decoded.'
    elif 'token' not in data:
        err = 'No auth provided.'
    elif data['token'] != admin_key:
        err = 'Invalid auth.'
    elif 'command' not in data:
        err = 'No command provided.'
    elif data['command'] not in commands:
        err = 'Command not supported.'
    if err:
        return {'message': err, 'status': 'error'}

    # Flight
    bottle.response.headers['Content-Type'] = 'application/json'
    resp = commands[data['command']](cache, data)
    return json.dumps(resp)


def _cmd_blacklist_paste(cache, data):
    # Delete paste
    _ = _delete_paste(cache, data)

    # Block address
    addr = bottle.request.environ.get('REMOTE_ADDR', 'undef').strip()
    if sanity.blacklist_address(cache, addr):
        return {'message': 'Added to black list; paste removed.'.format(addr), 'status': 'success'}
    return {'message': 'unexpected error; task already complete?', 'status': 'error'}


def _cmd_delete_paste(cache, data):
    ret = _delete_paste(cache, data)
    if ret:
        return ret
    return {'message': 'Paste deleted.', 'status': 'success'}


def _delete_paste(cache, data):
    paste = data.get('target')
    if not paste:
        return {'message': 'No paste provided.', 'status': 'error'}
    paste_id = 'paste:{}'.format(data['target'])

    # Find paste origin address
    paste = cache.get(paste_id)
    if not paste:
        return {'message': 'Paste not found.', 'status': 'error'}
    addr = json.loads(paste)['origin_addr']

    # Remove paste
    cache.delete(paste_id)


def _cmd_whitelist_address(cache, data):
    addr = data.get('target')
    if not addr:
        return {'message': 'No address provided.', 'status': 'error'}

    if sanity.whitelist_address(cache, addr):
        return {'message': 'Removed from filtering.', 'status': 'success'}
    return {'message': 'unexpected error; task already complete?', 'status': 'error'}


def _cmd_greylist_address(cache, data):
    '''
    Don't block an address from using the service, but disable IRC relay.
    '''
    paste = data.get('target')
    if not paste:
        return {'message': 'No paste provided.', 'status': 'error'}
    paste_id = 'paste:{}'.format(paste)

    # Find paste origin address
    cpaste = cache.get(paste_id)
    if not cpaste:
        return {'message': 'Paste not found.', 'status': 'error'}
    addr = json.loads(cpaste)['origin_addr']

    # Greylist address
    if sanity.greylist_address(cache, addr):
        return {'message': 'Added to grey list.', 'status': 'success'}
    return {'message': 'unexpected error; task already complete?', 'status': 'error'}
