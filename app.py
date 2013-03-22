#!/usr/bin/env python

try:
    import gevent.monkey
    gevent.monkey.patch_all()
except:
    pass

import redis
from hashlib import sha1
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
    'relay_chan': None,
    'relay_admin_chan': None,
    'mollom_pub_key': None,
    'mollom_priv_key': None,
    'python_server': 'auto'})
conf.read('conf/settings.cfg')


@app.route('/static/<filename:path>')
def static(filename):
    """
    Serve static files
    """
    return static_file(filename, root='{}/static'.format(conf.get('bottle', 'root_path')))


@app.error(500)
@app.error(404)
def errors(code):
    """
    Handler for errors
    """
    return jinja2_template("error.html", code=code)


@app.route('/')
def home():
    """
    Homepage view
    """
    return jinja2_template("paste.html")


#@app.route('/<paste_id>')
#def view_paste(past_id):
#    """
#    Return page with past_id
#    """
#    return jinja2_template("view.html", pid=paste_id)


@app.route('/recent')
def view_recent():
    """
    Show recent public pastes
    """
    return jinja2_template("recent.html")


@app.route('/api')
def api():
    """
    API stuff
    """
    return 'Not yet implemented'


@app.route('/about')
def show_about():
    """
    Return the information page
    """
    return jinja2_template("about.html")


def spam_check(content):
    mollom_api = Mollom.MollomAPI(
        publicKey=conf.get('bottle', 'mollom_pub_key'),
        privateKey=conf.get('bottle', 'mollom_priv_key'))
    if not mollom_api.verifyKey():
        raise Mollom.MollomFault('Invalid Mollom Keys')

    cc = mollom_api.checkContent(postBody=content)
    # cc['spam']: 1 for ham, 2 for spam, 3 for unsure;
    # http://mollom.com/blog/spam-vs-ham
    if cc['spam'] == 2:
        return True
    return False

class StripPathMiddleware(object):
    """
    Get that leading slash out of the request
    """
    def __init__(self, a):
        self.a = a
    def __call__(self, e, h):
        e['PATH_INFO'] = e['PATH_INFO'].rstrip('/')
        return self.a(e, h)


def main():
    """
    Run the app
    """
    run(
        app=StripPathMiddleware(app),
        server=conf.get('bottle', 'python_server'),
        host='0.0.0.0',
        port=conf.getint('bottle', 'port'))


if __name__ == '__main__':
    main()

