import re

import html
import nginx
import php
import css

from pygments.filter import simplefilter
from pygments.token import Token

@simplefilter
def logging_linker(self, lexer, stream, options):
    for ttype, value in stream:
        print "value: '%s'  ttype: '%s'" % (value, ttype)
        yield ttype, value

def get_linker_by_name(name):
    if 'nginx' == name:
        return nginx.linker()
    elif 'html' == name:
        return html.linker()
    elif 'php' == name:
        return php.linker()
    elif 'css' == name:
        return css.linker()
    #else:
    #    return logging_linker()
    return None

_lnk_replacements = {
    '_LNK_B_': '<a href="http://',
    '_LNK_M_': '" target="_blank">',
    '_LNK_E_': '</a>',
    '_LNK__': '_LNK_',
}

_lnk_regex = re.compile('|'.join(_lnk_replacements.keys()))

def _lnk_replace(match):
    return _lnk_replacements[match.group()]

def replace_markup(markup):
    return _lnk_regex.sub(_lnk_replace, markup)
