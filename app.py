#!/usr/bin/env python

# This isn't needed unless python_server=gevent is set.
# If we are running with gevent, then this is required.
try:
    import gevent.monkey
    gevent.monkey.patch_all()
except:
    pass

import bottle
import modules.kwlinker

from modules.mollom import Mollom
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

# Load Settings
conf = ConfigParser.SafeConfigParser({
    'cache_host': 'localhost',
    'cache_db': 0,
    'port': 80,
    'root_path': '.',
    'url': None,
    'relay_enabled': True,
    'relay_chan': None,
    'relay_admin_chan': None,
    'check_spam': False,
    'python_server': 'auto'})
conf.read('conf/settings.cfg')

app = application = bottle.Bottle()
cache = redis.Redis(host=conf.get('bottle', 'cache_host'), db=int(conf.get('bottle', 'cache_db')))


@app.route('/static/<filename:path>')
def static(filename):
    '''
    Serve static files
    '''
    return bottle.static_file(filename, root='{}/static'.format(conf.get('bottle', 'root_path')))


@app.error(500)
@app.error(404)
def errors(code):
    '''
    Handler for errors
    '''
    return bottle.jinja2_template('error.html', code=code)


@app.route('/')
def new_paste():
    '''
    Display page for new empty post
    '''
    data = {
        'name': '',
        'syntax': 'nginx',
        'private': '0'}
    dat = bottle.request.cookies.get('dat', False)
    if dat:
        data = json.loads(dat)
        data['private'] = str(str2int(data['private']))
    return bottle.jinja2_template('paste.html', data=data)


@app.route('/f/<paste_id>')
def new_fork(paste_id):
    '''
    Display page for new fork from a paste
    '''
    if not cache.exists(paste_id):
        bottle.redirect('/')

    data = json.loads(cache.get(paste_id))
    data['paste_id'] = paste_id
    data['title'] = 're: ' + data['title'][:32]
    data['private'] = str(str2int(data['private']))

    dat = bottle.request.cookies.get('dat', False)
    if dat:
        d = json.loads(dat)
        data['name'] = d['name']
    else:
        data['name'] = ''

    return bottle.jinja2_template('paste.html', data=data)


@app.route('/', method='POST')
def submit_paste():
    '''
    Put a new paste into the database
    '''
    r = re.compile('^[- !$%^&*()_+|~=`{}\[\]:";\'<>?,.\/a-zA-Z0-9]{1,48}$')
    paste = {
        'code': bottle.request.POST.get('code', ''),
        'title': bottle.request.POST.get('title', '').strip(),
        'name': bottle.request.POST.get('name', '').strip(),
        'private': bottle.request.POST.get('private', '0').strip(),
        'syntax': bottle.request.POST.get('syntax', '').strip(),
        'forked_from': bottle.request.POST.get('forked_from', '').strip()}

    # Validate data
    if max(0, bottle.request.content_length) > bottle.request.MEMFILE_MAX:
        return bottle.jinja2_template('error.html', code=200, message='This request is too large to process.')
    for k in ['code', 'private', 'syntax', 'title', 'name']:
        if paste[k] == '':
            return bottle.jinja2_template('error.html', code=200, message='All fields need to be filled out.')
    for k in ['title', 'name']:
        if not r.match(paste[k]):
            return bottle.jinja2_template('error.html', code=200, message='Invalid input detected.')

    # Check post for spam
    if bottle.request.POST.get('phone', '').strip() != '':
        return bottle.jinja2_template('error.html', code=200, message='Your post triggered our spam filters!')
    if str2bool(conf.get('bottle', 'check_spam')):
        if spam_detected(paste['title'], paste['code'], paste['name'], bottle.request.environ.get('REMOTE_ADDR')):
            return bottle.jinja2_template('error.html', code=200, message='Your post triggered our spam filters.')

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

    cache.set(paste_id, json.dumps(paste))
    cache.expire(paste_id, 345600)

    dat = {
      'name': str(paste['name']),
      'syntax': str(paste['syntax']),
      'private': str(paste['private'])}
    bottle.response.set_cookie('dat', json.dumps(dat))

    if str2bool(conf.get('bottle', 'relay_enabled')):
        send_irc(paste, paste_id)

    bottle.redirect('/' + paste_id)


@app.route('/<paste_id>')
def view_paste(paste_id):
    '''
    Return page with paste_id
    '''
    if not cache.exists(paste_id):
        bottle.redirect('/')

    p = json.loads(cache.get(paste_id))

    # Syntax hilighting
    try:
        lexer = get_lexer_by_name(p['syntax'], stripall=False)
    except:
        lexer = get_lexer_by_name('text', stripall=False)
    formatter = HtmlFormatter(linenos=True, cssclass="paste")
    linker = modules.kwlinker.get_linker_by_name(p['syntax'])
    if None != linker:
        lexer.add_filter(linker)
        p['code'] = highlight(p['code'], lexer, formatter)
        p['code'] = modules.kwlinker.replace_markup(p['code'])
    else:
        p['code'] = highlight(p['code'], lexer, formatter)
    p['css'] = HtmlFormatter().get_style_defs('.code')

    return bottle.jinja2_template('view.html', paste=p, pid=paste_id)


@app.route('/r/<paste_id>')
def view_raw(paste_id):
    '''
    View raw paste with paste_id
    '''
    if not cache.exists(paste_id):
        bottle.redirect('/')

    p = json.loads(cache.get(paste_id))

    bottle.response.add_header('Content-Type', 'text/plain; charset=utf-8')
    return bottle.jinja2_template('raw.html', code=p['code'])


@app.route('/d/<orig>/<fork>')
def view_diff(orig, fork):
    '''
    View the diff between a paste and what it was forked from
    '''
    if not cache.exists(orig) or not cache.exists(fork):
        return bottle.jinja2_template('error.html', code=200, message='One of the pastes could not be found.')

    po = json.loads(cache.get(orig))
    pf = json.loads(cache.get(fork))
    co = po['code'].split('\n')
    cf = pf['code'].split('\n')
    lo = '<a href="/' + orig + '">' + orig + '</a>'
    lf = '<a href="/' + fork + '">' + fork + '</a>'

    diff = difflib.HtmlDiff().make_table(co, cf, lo, lf)
    return bottle.jinja2_template('page.html', data=diff)


@app.route('/thisoneisspam/<paste_id>')
def delete_spam(paste_id):
    '''
    Delete a paste that turns out to have been spam
    '''
    #TODO This should eventually require a captcha and report back to mollom.
    #mollom_client.send_feedback(content_id=content_id, reason="spam")
    if not cache.exists(paste_id):
        return 'Paste not found'
    if cache.delete(paste_id):
        return 'Paste removed'
    else:
        return 'Error removing paste'

@app.route('/about')
def show_about():
    '''
    Return the information page
    '''
    return bottle.jinja2_template('about.html')


def send_irc(paste, paste_id):
    '''
    Send notification to channels
    '''
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
    '''
    Basic netcat functionality using sockets
    '''
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((hostname, port))
    s.sendall(content)
    s.shutdown(socket.SHUT_WR)
    s.close()


def str2bool(v):
    '''
    Convert string to boolean
    '''
    return v.lower() in ('yes', 'true', 't', 'y', '1', 'on')


def str2int(v):
    '''
    Convert string to boolean to integer
    '''
    return int(v.lower() in ('yes', 'true', 't', 'y', '1', 'on'))


def spam_detected(title, body, author, address):
    '''
    Returns True if spam was detected
    '''
    m = Mollom(conf.get('bottle', 'mollom_pub_key'), conf.get('bottle', 'mollom_priv_key'))
    try:
        result = m.check_content(
            post_title = title,
            post_body = body,
            author_id = author,
            author_ip = address)
    except:
        # Service is down
        print('Mollom service down; failing open')
        return False

    spam_classification = result['content']['spamClassification']
    if spam_classification == "ham":
        return False
    elif spam_classification == "spam":
        return True
    else:
        # Could choose to add a captcha here in the future
        #captcha_id, captcha_url = mollom_client.create_captcha(content_id=content_id)
        #solved = mollom_client.check_captcha(captcha_id=captcha_id, solution=solution,
        #    author_id=author_id, author_ip=author_ip)
        return True


class StripPathMiddleware(object):
    '''
    Get that leading slash out of the request
    '''
    def __init__(self, a):
        self.a = a
    def __call__(self, e, h):
        e['PATH_INFO'] = e['PATH_INFO'].rstrip('/')
        return self.a(e, h)


if __name__ == '__main__':
    bottle.run(app=StripPathMiddleware(app),
        server=conf.get('bottle', 'python_server'),
        host='0.0.0.0',
        port=conf.getint('bottle', 'port'))
