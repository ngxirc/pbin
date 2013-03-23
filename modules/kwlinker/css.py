from pygments.filter import simplefilter
from pygments.token import Token

@simplefilter
def linker(self, lexer, stream, options):
    for ttype, value in stream:
        value = value.replace('_LNK_', '_LNK__')
        if ttype is Token.Name.Tag and '<' == value[0]:
            for i in range(len(value)):
                if value[i].isalpha(): break
            if value[-1].isalpha():
                j = len(value) + 1
            else:
                for j in range(i + 1, len(value)):
                    if not value[j].isalpha(): break
            value = '%s_LNK_B_reference.sitepoint.com/css/%s_LNK_M_%s_LNK_E_%s' % (value[:i], value[i:j], value[i:j], value[j:])
        yield ttype, value
