#!/usr/bin/env python

try:
    import gevent.monkey
    gevent.monkey.patch_all()
except:
    pass

from pygments import highlight
from pygments.lexers import *
from pygments.formatters import HtmlFormatter

import bottle
import os
import binascii
import redis
import json
import socket
import modules.kwlinker
import ConfigParser
import Mollom

app = application = bottle.Bottle()
cache = redis.Redis('localhost')

# Load Settings
conf = ConfigParser.SafeConfigParser({
    'port': 80,
    'root_path': '.',
    'url': None,
    'relay_enabled': True,
    'relay_chan': None,
    'relay_admin_chan': None,
    'mollom_pub_key': None,
    'mollom_priv_key': None,
    'python_server': 'auto'})
conf.read('conf/settings.cfg')


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
    return bottle.jinja2_template('paste.html', data=data)


@app.route('/', method='POST')
def submit_paste():
    '''
    Put a new paste into the database
    '''
    paste = {
        'code': bottle.request.POST.get('code', '').strip(),
        'title': bottle.request.POST.get('title', '').strip(),
        'name': bottle.request.POST.get('name', '').strip(),
        'private': bottle.request.POST.get('private', '0').strip(),
        'syntax': bottle.request.POST.get('syntax', '').strip()}

    # Validate data
    for k, v in paste.iteritems():
        if v == '':
            return bottle.jinja2_template('error.html', code=200, message='All fields need to be filled out.')

    # Check post for spam
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
    Return page with past_id
    '''
    if not cache.exists(paste_id):
        bottle.redirect('/')

    p = json.loads(cache.get(paste_id))

    # Syntax hilighting
    try:
        lexer = get_lexer_by_name(p['syntax'], stripall=True)
    except:
        lexer = get_lexer_by_name('text', stripall=True)
    formatter = HtmlFormatter(linenos=True, cssclass="paste")
    linker = modules.kwlinker.get_linker_by_name(p['syntax'])
    if None != linker:
        lexer.add_filter(linker)
        p['code'] = highlight(p['code'], lexer, formatter)
        p['code'] = modules.kwlinker.replace_markup(p['code'])
    else:
        p['code'] = highlight(p['code'], lexer, formatter)
    p['css'] = HtmlFormatter().get_style_defs('.code')

    return bottle.jinja2_template('view.html', paste=p)


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
    return True


def send_irc(paste, paste_id):
    '''
    Send notification to channels
    '''
    # Build the message to send to the channel
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
        netcat(conf.get('bottle', 'relay_host'), int(conf.get('bottle', 'relay_port')), nc_msg)


def netcat(hostname, port, content):
    '''
    Basic netcat functionality using sockets
    '''
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((hostname, port))
    s.sendall(content)
    s.shutdown(socket.SHUT_WR)
    while 1:
        data = s.recv(1024)
        if data == "":
            break
        print "Received:", repr(data)
    print "Connection closed."
    s.close()


def str2bool(v):
    '''
    Convert string to boolean
    '''
    return v.lower() in ('yes', 'true', 't', 'y', '1', 'on')


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
    run(app=StripPathMiddleware(app),
        server=conf.get('bottle', 'python_server'),
        host='0.0.0.0',
        port=conf.getint('bottle', 'port'))
