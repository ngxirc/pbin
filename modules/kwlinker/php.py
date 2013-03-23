from pygments.filter import simplefilter
from pygments.token import Token

@simplefilter
def linker(self, lexer, stream, options):
    for ttype, value in stream:
        value = value.replace('_LNK_', '_LNK__')
        if ttype is Token.Name.Builtin:
            value = '_LNK_B_www.php.net/manual/en/function.%s.php_LNK_M_%s_LNK_E_' % (value.replace('_', '-'), value)
        yield ttype, value
