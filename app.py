#!/usr/bin/env python

# local imports
import modules.admin as admin
import modules.irc as irc
import modules.paste as paste
import modules.sanity as sanity
import modules.utils as utils

import bottle
import configparser
import redis

# Load Settings
conf = configparser.ConfigParser({
    'cache_host': 'localhost',
    'cache_db': 0,
    'cache_ttl': 360,
    'port': 80,
    'root_path': '.',
    'url': '',
    'relay_enabled': True,
    'relay_chan': '',
    'relay_port': 5050,
    'relay_pass': 'nil',
    'recaptcha_sitekey': '',
    'recaptcha_secret': '',
    'check_spam': False,
    'admin_key': '',
    'python_server': 'auto'})
conf.read('conf/settings.cfg')

app = application = bottle.Bottle()
cache = redis.StrictRedis(host=conf.get('bottle', 'cache_host'), db=int(conf.get('bottle', 'cache_db')))


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
    (data, template) = paste.new_paste(conf)
    return bottle.jinja2_template('paste.html', data=data, tmpl=template)


@app.route('/f/<paste_id>')
def new_fork(paste_id):
    '''
    Display page for new fork from a paste
    '''
    (data, template) = paste.new_paste(conf, cache, paste_id)
    return bottle.jinja2_template('paste.html', data=data, tmpl=template)


@app.route('/', method='POST')
def submit_paste():
    '''
    Put a new paste into the database
    '''
    return paste.submit_new(conf, cache)


@app.route('/<paste_id>')
def view_paste(paste_id):
    '''
    Return page with <paste_id>.
    '''
    data = paste.get_paste(cache, paste_id)
    return bottle.jinja2_template('view.html', paste=data, pid=paste_id)


@app.route('/r/<paste_id>')
def view_raw(paste_id):
    '''
    View raw paste with <paste_id>.
    '''
    data = paste.get_paste(cache, paste_id, raw=True)
    bottle.response.add_header('Content-Type', 'text/plain; charset=utf-8')
    return data['code']


@app.route('/d/<orig>/<fork>')
def view_diff(orig, fork):
    '''
    View the diff between a paste and what it was forked from
    '''
    if not cache.exists('paste:' + orig) or not cache.exists('paste:' + fork):
        return bottle.jinja2_template('error.html', code=200,
                                      message='At least one paste could not be found.')

    diff = paste.gen_diff(cache, orig, fork)
    return bottle.jinja2_template('page.html', data=diff)


@app.post('/admin')
def exec_admin():
    return admin.run_cmd(conf, cache)


@app.route('/about')
def show_info():
    return bottle.jinja2_template('about.html')


if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=conf.getint('bottle', 'port'))
