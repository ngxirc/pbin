#!/usr/bin/env python

import bottle
import modules.kwlinker

from pygments import highlight
from pygments.lexers import *
from pygments.formatters import HtmlFormatter

import binascii
import ConfigParser
import difflib
import json
import os
import re
import redis
import requests
import socket

from furl import furl

# Load Settings
conf = ConfigParser.SafeConfigParser({
    'cache_host': 'localhost',
    'cache_db': 0,
    'cache_ttl': 360,
    'port': 80,
    'root_path': '.',
    'url': None,
    'relay_enabled': True,
    'relay_chan': None,
    'relay_admin_chan': None,
    'recaptcha_sitekey': None,
    'recaptcha_secret': None,
    'check_spam': False,
    'python_server': 'auto'})
conf.read('conf/settings.cfg')

app = application = bottle.Bottle()
cache = redis.Redis(host=conf.get('bottle', 'cache_host'), db=int(conf.get('bottle', 'cache_db')))


# noinspection PyUnresolvedReferences
@app.route('/static/<filename:path>')
def static(filename):
    """
    Serve static files
    """
    return bottle.static_file(filename, root='{}/static'.format(conf.get('bottle', 'root_path')))


@app.error(500)
@app.error(404)
def errors(code):
    """
    Handler for errors
    """
    return bottle.jinja2_template('error.html', code=code)


@app.route('/')
def new_paste():
    """
    Display page for new empty post
    """
    if conf.get('bottle', 'recaptcha_sitekey'):
        template = {'recap_enabled': True, 'sitekey': conf.get('bottle', 'recaptcha_sitekey')}
    else:
        template = {'recap_enabled': False}

    # Default page values
    data = {
        'name': '',
        'syntax': 'nginx',
        'private': '0'}
    dat = bottle.request.cookies.get('dat', False)
    if dat:
        data = json.loads(dat)
        data['private'] = str(str2int(data['private']))

    # Return rendered page
    return bottle.jinja2_template('paste.html', data=data, tmpl=template)


@app.route('/f/<paste_id>')
def new_fork(paste_id):
    """
    Display page for new fork from a paste
    """
    if conf.get('bottle', 'recaptcha_sitekey'):
        template = {'recap_enabled': True, 'sitekey': conf.get('bottle', 'recaptcha_sitekey')}
    else:
        template = {'recap_enabled': False}

    data = json.loads(cache.get('paste:' + paste_id))
    data['paste_id'] = paste_id
    data['private'] = str(str2int(data['private']))

    dat = bottle.request.cookies.get('dat', False)
    if dat:
        d = json.loads(dat)
        data['name'] = d['name']
    else:
        data['name'] = ''

    return bottle.jinja2_template('paste.html', data=data, tmpl=template)


@app.route('/', method='POST')
def submit_paste():
    """
    Put a new paste into the database
    """
    r = re.compile('^[- !$%^&*()_+|~=`{}\[\]:";\'<>?,./a-zA-Z0-9]{1,48}$')
    paste = {
        'code': bottle.request.POST.get('code', ''),
        'name': bottle.request.POST.get('name', '').strip(),
        'private': bottle.request.POST.get('private', '0').strip(),
        'syntax': bottle.request.POST.get('syntax', '').strip(),
        'forked_from': bottle.request.POST.get('forked_from', '').strip(),
        'recaptcha_answer': bottle.request.POST.get('g-recaptcha-response', '').strip()}

    # Validate data
    if max(0, bottle.request.content_length) > bottle.request.MEMFILE_MAX:
        return bottle.jinja2_template('error.html', code=200,
                                      message='This request is too large to process. ERR:991')
    for k in ['code', 'private', 'syntax', 'name']:
        if paste[k] == '':
            return bottle.jinja2_template('error.html', code=200,
                                          message='All fields need to be filled out. ER:577')
    if not r.match(paste['name']):
        return bottle.jinja2_template('error.html', code=200,
                                      message='Invalid input detected. ERR:925')

        # Basic spam checks
        # return bottle.jinja2_template('error.html', code=200,
        #                               message='Your post triggered our spam filters! ERR:615')
    if bottle.request.POST.get('phone', '').strip() != '':
        return bottle.jinja2_template('error.html', code=200,
                                      message='Your post triggered our spam filters! ERR:228')

    # More advanced spam checking... eventually
    if str2bool(conf.get('bottle', 'check_spam')):
        if not check_captcha(paste['recaptcha_answer'], bottle.request.environ.get('REMOTE_ADDR')):
            return bottle.jinja2_template('error.html', code=200,
                                          message='Your post triggered our spam filters. ERR:677')

    # Public pastes should have an easy to type key
    # Private pastes should have a more secure key
    id_length = 1
    if str2bool(paste['private']):
        id_length = 8

    # Pick a unique ID
    paste_id = binascii.b2a_hex(os.urandom(id_length))

    # Make sure it's actually unique or else create a new one and test again
    while cache.exists(paste_id):
        id_length += 1
        paste_id = binascii.b2a_hex(os.urandom(id_length))

    # Put the paste into cache
    cache.set('paste:' + paste_id, json.dumps(paste))
    cache.expire('paste:' + paste_id, 345600)

    dat = {
        'name': str(paste['name']),
        'syntax': str(paste['syntax']),
        'private': str(paste['private'])}
    bottle.response.set_cookie('dat', json.dumps(dat))

    if str2bool(conf.get('bottle', 'relay_enabled')):
        send_irc(paste, paste_id)

    bottle.redirect('/' + paste_id)


# noinspection PyBroadException
@app.route('/<paste_id>')
def view_paste(paste_id):
    """
    Return page with paste_id
    """
    paste_id = paste_id
    if not cache.exists('paste:' + paste_id):
        bottle.redirect('/')

    p = json.loads(cache.get('paste:' + paste_id))

    # Syntax hilighting
    try:
        lexer = get_lexer_by_name(p['syntax'], stripall=False)
    except:
        lexer = get_lexer_by_name('text', stripall=False)
    formatter = HtmlFormatter(linenos=True, cssclass="paste")
    linker = modules.kwlinker.get_linker_by_name(p['syntax'])
    if linker is not None:
        lexer.add_filter(linker)
        p['code'] = highlight(p['code'], lexer, formatter)
        p['code'] = modules.kwlinker.replace_markup(p['code'])
    else:
        p['code'] = highlight(p['code'], lexer, formatter)
    p['css'] = HtmlFormatter().get_style_defs('.code')

    return bottle.jinja2_template('view.html', paste=p, pid=paste_id)


@app.route('/r/<paste_id>')
def view_raw(paste_id):
    """
    View raw paste with paste_id
    """
    if not cache.exists('paste:' + paste_id):
        bottle.redirect('/')

    p = json.loads(cache.get('paste:' + paste_id))

    bottle.response.add_header('Content-Type', 'text/plain; charset=utf-8')
    return p['code']


@app.route('/d/<orig>/<fork>')
def view_diff(orig, fork):
    """
    View the diff between a paste and what it was forked from
    """
    if not cache.exists('paste:' + orig) or not cache.exists('paste:' + fork):
        return bottle.jinja2_template('error.html', code=200,
                                      message='One of the pastes could not be found.')

    po = json.loads(cache.get('paste:' + orig))
    pf = json.loads(cache.get('paste:' + fork))
    co = po['code'].split('\n')
    cf = pf['code'].split('\n')
    lo = '<a href="/' + orig + '">' + orig + '</a>'
    lf = '<a href="/' + fork + '">' + fork + '</a>'

    diff = difflib.HtmlDiff().make_table(co, cf, lo, lf)
    return bottle.jinja2_template('page.html', data=diff)


@app.route('/thisoneisspam/<paste_id>')
def delete_spam(paste_id):
    """
    Delete a paste that turns out to have been spam
    """
    # TODO: This should eventually require a recaptcha and block IP
    if not cache.exists(paste_id):
        return 'Paste not found'
    if cache.delete(paste_id):
        return 'Paste removed'
    else:
        return 'Error removing paste'


# noinspection PyBroadException
def send_irc(paste, paste_id):
    """
    Send notification to channels
    """
    host = conf.get('bottle', 'relay_host')
    port = int(conf.get('bottle', 'relay_port'))

    # Build the message to send to the channel
    if paste['forked_from']:
        orig = json.loads(cache.get(paste['forked_from']))
        message = ''.join(['Paste from ', orig['name'],
                           ' forked by ', paste['name'], ': [ ',
                           conf.get('bottle', 'url'), paste_id, ' ] - ', paste['title']])
    else:
        message = ''.join(['Paste from ', paste['name'], ': [ ',
                           conf.get('bottle', 'url'), paste_id, ' ] - ', paste['title']])

    # Get list of relay channels
    channels = None
    # Always admin channels, only normal channels if paste is not private
    if conf.get('bottle', 'relay_admin_chan') is not None:
        channels = conf.get('bottle', 'relay_admin_chan')
        if conf.get('bottle', 'relay_chan') is not None and not str2bool(paste['private']):
            channels = ''.join([channels, ',', conf.get('bottle', 'relay_chan')])
    else:
        if conf.get('bottle', 'relay_chan') is not None and not str2bool(paste['private']):
            channels = conf.get('bottle', 'relay_chan')

    # For each channel, send the relay server a message
    if channels:
        for channel in channels.split(','):
            nc_msg = ''.join([channel, ' ', message])
            try:
                netcat(host, port, nc_msg)
            except:
                pass


def netcat(hostname, port, content):
    """
    Basic netcat functionality using sockets
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((hostname, port))
    s.sendall(content)
    s.shutdown(socket.SHUT_WR)
    s.close()


def str2bool(v):
    """
    Convert string to boolean
    """
    return v.lower() in ('yes', 'true', 't', 'y', '1', 'on')


def str2int(v):
    """
    Convert string to boolean to integer
    """
    return int(str2bool(v))


def check_captcha(answer, addr=None):
    """
    Returns True if spam was detected
    """
    query = furl('https://www.google.com/recaptcha/api/siteverify')
    query.args['secret'] = conf.get('bottle', 'recaptcha_secret')
    query.args['response'] = answer
    if addr:
        query.args['remoteip'] = addr

    response = requests.post(query.url)
    result = response.json()

    return result['success']


if __name__ == '__main__':
    bottle.run(
        host='0.0.0.0',
        port=conf.getint('bottle', 'port'))
