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

from pygments import highlight
from pygments.lexers import *
from pygments.formatters import HtmlFormatter

import binascii
import ConfigParser
import difflib
import json
import Mollom
import os
import re
import redis
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
    'check_spam': True,
    'mollom_pub_key': None,
    'mollom_priv_key': None,
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

    return bottle.jinja2_template('paste.html', data=data)


@app.route('/', method='POST')
def submit_paste():
    '''
    Put a new paste into the database
    '''
    r = re.compile('^[- !$%^&*()_+|~=`{}\[\]:";\'<>?,.\/a-zA-Z0-9]{1,48}$')
    paste = {
        #'code': bottle.request.POST.get('code', '').strip(),
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
        if not spam_free(paste['code']):
            return bottle.jinja2_template('error.html', code=200, message='Your post triggered our spam filters!')

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
    #co = bottle.html_escape(po['code']).split()
    co = po['code'].split('\n')
    #cf = bottle.html_escape(pf['code']).split()
    cf = pf['code'].split('\n')
    lo = '<a href="/' + orig + '">' + orig + '</a>'
    lf = '<a href="/' + fork + '">' + fork + '</a>'

    diff = difflib.HtmlDiff().make_table(co, cf, lo, lf)
    return bottle.jinja2_template('page.html', data=diff)

@app.route('/about')
def show_about():
    '''
    Return the information page
    '''
    return bottle.jinja2_template('about.html')


def spam_free(content):
    '''
    Checks if content is spam free. Returns True if no spam is found.
    '''
    mollom_api = Mollom.MollomAPI(
        publicKey=conf.get('bottle', 'mollom_pub_key'),
        privateKey=conf.get('bottle', 'mollom_priv_key'))
    if not mollom_api.verifyKey():
        return False

    cc = mollom_api.checkContent(postBody=content)
    # cc['spam']: 1 for ham, 2 for spam, 3 for unsure;
    if cc['spam'] == 2:
        return False
    if cc['spam'] == 3:
        return False
    return True


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
    # Always admin channels, only normal channels if paste is not private
    channels = conf.get('bottle', 'relay_admin_chan')
    if not str2bool(paste['private']):
        channels = ''.join([channels, ',', conf.get('bottle', 'relay_chan')])

    # For each channel, send the relay server a message
    for channel in channels.split(','):
        nc_msg = ''.join([channel, ' ', message])
        netcat(host, port, nc_msg)


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
