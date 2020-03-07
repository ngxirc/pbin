from pygments.filter import simplefilter
from pygments.token import Token

@simplefilter
def linker(self, lexer, stream, options):
    for ttype, value in stream:
        value = value.replace('_LNK_', '_LNK__')
        if ttype is Token.Keyword or ttype is Token.Keyword.Namespace:
            value = '_LNK_B_nginx.org/r/%s_LNK_M_%s_LNK_E_' % (value, value)
        yield ttype, value
