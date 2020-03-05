#!/usr/bin/env python

# local imports
from . import irc
from . import kwlinker
from . import sanity
from . import utils

from pygments import highlight
from pygments.lexers import *
from pygments.formatters import HtmlFormatter

import binascii
import bottle
import difflib
import json
import os


class HtmlLineFormatter(HtmlFormatter):
    '''
    Output as html and wrap each line in a span
    '''
    name = 'Html with line wrap'
    aliases = ['htmlline']

    def wrap(self, source, outfile):
        return self._wrap_div(self._wrap_pre(self._wrap_lines(source)))

    def _wrap_lines(self, source):
        i = self.linenostart
        for t, line in source:
            if t == 1:
                line = '<span class="linecount" id="LC%d">%s</span>' % (i, line)
                i += 1
            yield t, line


def new_paste(conf, cache=None, paste_id=None):
    '''
    Returns templating data for a new post page.
    '''
    if conf.get('bottle', 'recaptcha_sitekey') and conf.get('bottle', 'check_spam'):
        template = {'recap_enabled': True, 'sitekey': conf.get('bottle', 'recaptcha_sitekey')}
    else:
        template = {'recap_enabled': False}

    # Default page values
    data = {
        'name': '',
        'syntax': 'nginx',
        'private': '0'}

    if paste_id and cache:
        paste = json.loads(cache.get('paste:' + paste_id))
        if paste:
            data.update(paste)
            data['paste_id'] = paste_id
            data['private'] = str(utils.str2int(paste['private']))
            data['name'] = ''

    cookie = bottle.request.cookies.get('dat', None)
    if cookie:
        data.update(json.loads(cookie))
        data['private'] = str(utils.str2int(data['private']))

    return (data, template)


def get_paste(cache, paste_id, raw=False):
    '''
    Return page with <paste_id>.
    '''
    paste_id = paste_id
    if not cache.exists('paste:' + paste_id):
        bottle.redirect('/')

    data = json.loads(cache.get('paste:' + paste_id))

    if not raw:
        # Syntax hilighting
        try:
            lexer = get_lexer_by_name(data['syntax'], stripall=False)
        except:
            lexer = get_lexer_by_name('text', stripall=False)
        formatter = HtmlLineFormatter(linenos=True, cssclass="paste")
        linker = kwlinker.get_linker_by_name(data['syntax'])
        if linker is not None:
            lexer.add_filter(linker)
            data['code'] = highlight(data['code'], lexer, formatter)
            data['code'] = kwlinker.replace_markup(data['code'])
        else:
            data['code'] = highlight(data['code'], lexer, formatter)
        data['css'] = HtmlLineFormatter().get_style_defs('.code')

    return data


def gen_diff(cache, orig, fork):
    '''
    Returns a generated diff between two pastes.
    '''
    po = json.loads(cache.get('paste:' + orig))
    pf = json.loads(cache.get('paste:' + fork))
    co = po['code'].split('\n')
    cf = pf['code'].split('\n')
    lo = '<a href="/' + orig + '">' + orig + '</a>'
    lf = '<a href="/' + fork + '">' + fork + '</a>'

    return difflib.HtmlDiff().make_table(co, cf, lo, lf)


def submit_new(conf, cache):
    '''
    Handle processing for a new paste.
    '''
    paste_data = {
        'code': bottle.request.POST.get('code', ''),
        'name': bottle.request.POST.get('name', '').strip(),
        'phone': bottle.request.POST.get('phone', '').strip(),
        'private': bottle.request.POST.get('private', '0').strip(),
        'syntax': bottle.request.POST.get('syntax', '').strip(),
        'forked_from': bottle.request.POST.get('forked_from', '').strip(),
        'webform': bottle.request.POST.get('webform', '').strip(),
        'origin_addr': bottle.request.environ.get('REMOTE_ADDR', 'undef').strip(),
        'recaptcha_answer': bottle.request.POST.get('g-recaptcha-response', '').strip()}
    cli_post = True if paste_data['webform'] == '' else False

    # Handle file uploads
    if type(paste_data['code']) == bottle.FileUpload:
        paste_data['code'] = '# FileUpload: {}\n{}'.format(
                paste_data['code'].filename,
                paste_data['code'].file.getvalue())

    # Validate data
    (valid, err) = sanity.validate_data(conf, paste_data)
    if not valid:
        return bottle.jinja2_template('error.html', code=200, message=err)

    # Check recapcha answer if not cli post
    if utils.str2bool(conf.get('bottle', 'check_spam')) and not cli_post:
        if not sanity.check_captcha(
                conf.get('bottle', 'recaptcha_secret'),
                paste_data['recaptcha_answer']):
            return bottle.jinja2_template('error.html', code=200, message='Invalid captcha verification. ERR:677')

    # Check address against blacklist
    if sanity.address_blacklisted(cache, paste_data['origin_addr']):
        return bottle.jinja2_template('error.html', code=200, message='Address blacklisted. ERR:840')

    # Stick paste into cache
    paste_id = _write_paste(cache, paste_data)

    # Set cookie for user
    bottle.response.set_cookie(
            'dat',
            json.dumps({
                'name': str(paste_data['name']),
                'syntax': str(paste_data['syntax']),
                'private': str(paste_data['private'])}))

    # Send user to page, or a link to page
    if cli_post:
        scheme = bottle.request.environ.get('REQUEST_SCHEME')
        host = bottle.request.get_header('host')
        return '{}://{}/{}\n'.format(scheme, host, paste_id)
    else:
        # Relay message to IRC
        if utils.str2bool(conf.get('bottle', 'relay_enabled')) and not sanity.address_greylisted(cache, paste_data['origin_addr']):
            irc.send_message(conf, cache, paste_data, paste_id)
        bottle.redirect('/' + paste_id)


def _write_paste(cache, paste_data):
    '''
    Put a new paste into cache.
    Returns paste_id.
    '''
    # Public pastes should have an easy to type key
    # Private pastes should have a more secure key
    id_length = 1
    if paste_data['recaptcha_answer'] == '':
        id_length = 12
    elif utils.str2bool(paste_data['private']):
        id_length = 8

    # Pick a unique ID
    paste_id = binascii.b2a_hex(os.urandom(id_length)).decode('utf-8')

    # Make sure it's actually unique or else create a new one and test again
    while cache.exists('paste:' + paste_id):
        id_length += 1
        paste_id = binascii.b2a_hex(os.urandom(id_length)).decode('utf-8')

    # Put the paste into cache
    cache.setex('paste:' + paste_id, 345600, json.dumps(paste_data))

    return paste_id
