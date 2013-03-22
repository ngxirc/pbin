#!/usr/bin/env python

try:
    import gevent.monkey
    gevent.monkey.patch_all()
except:
    pass

import os
import binascii
import redis
import json
import socket
import ConfigParser
import Mollom
from bottle import *

app = Bottle()
cache = redis.Redis('localhost')

# Uncomment to run in a WSGI server
#os.chdir(os.path.dirname(__file__))

# Load Settings
conf = ConfigParser.SafeConfigParser({
    'port': 80,
    'root_path': '.',
    'url': None,
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
    return static_file(filename, root='{}/static'.format(conf.get('bottle', 'root_path')))


@app.error(500)
@app.error(404)
def errors(code):
    '''
    Handler for errors
    '''
    return jinja2_template('error.html', code=code)


@app.route('/')
def new_paste():
    '''
    Display page for new empty post
    '''
    return jinja2_template('paste.html')


@app.route('/', method='POST')
def submit_paste():
    '''
    Put a new paste into the database
    '''
    paste = {
        'code': request.POST.get('code', '').strip(),
        'title': request.POST.get('title', '').strip(),
        'name': request.POST.get('name', '').strip(),
        'private': request.POST.get('private', '0').strip(),
        'lang': request.POST.get('lang', '').strip(),
        'expire': request.POST.get('expire', '0').strip()}

    if not spam_free(paste['code']):
        return jinja2_template('spam.html')

    # The expiration limits need to be enforced
    if not 30 <= int(paste['expire']) <= 40320:
        redirect('/')

    # Public pastes should have an easy to type key
    # Private pastes should have a more secure key
    id_length = 2
    if int(paste['private']) == 1:
        id_length = 8

    # Pick a unique ID
    paste_id = binascii.b2a_hex(os.urandom(id_length))

    # Make sure it's actually unique or else create a new one and test again
    while cache.exists(paste_id):
        id_length += 1
        paste_id = binascii.b2a_hex(os.urandom(id_length))

    cache.set(paste_id, json.dumps(paste))
    cache.expire(paste_id, int(paste['expire']) * 60)

    send_irc(paste, paste_id)

    redirect('/' + paste_id)


@app.route('/<paste_id>')
def view_paste(paste_id):
    '''
    Return page with past_id
    '''
    if not cache.exists(paste_id):
        redirect('/')
    paste = json.loads(cache.get(paste_id))
    return jinja2_template('view.html', paste=paste)


@app.route('/recent')
def view_recent():
    '''
    Show recent public pastes
    '''
    return jinja2_template('recent.html')


@app.route('/about')
def show_about():
    '''
    Return the information page
    '''
    return jinja2_template('about.html')


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
    if int(paste['private'] ) != 1:
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


class StripPathMiddleware(object):
    '''
    Get that leading slash out of the request
    '''
    def __init__(self, a):
        self.a = a
    def __call__(self, e, h):
        e['PATH_INFO'] = e['PATH_INFO'].rstrip('/')
        return self.a(e, h)


def main():
    '''
    Run the app
    '''
    run(
        app=StripPathMiddleware(app),
        server=conf.get('bottle', 'python_server'),
        host='0.0.0.0',
        port=conf.getint('bottle', 'port'))


if __name__ == '__main__':
    main()
