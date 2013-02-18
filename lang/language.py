# -*- coding: utf-8 -*-

import os
import re
import logging
import Cookie
import time
from cStringIO import StringIO

from django.utils import simplejson
from django.utils.encoding import force_unicode

from langs_table import lang_table
from lib import cc_cookies

DEFAULT_LANG = 'en-us'
COOKIE_NAME = 'gaephotos-language'

def get_support_langs():
    return lang_table.keys()

def get_current_lang():
    browser_cookie = os.environ.get('HTTP_COOKIE', '')
    cookie = Cookie.SimpleCookie()
    cookie.load(browser_cookie)
    try:
        lang = simplejson.loads(cookie[COOKIE_NAME].value)
    except:
        lang = os.environ.get('HTTP_ACCEPT_LANGUAGE', '%s,'%DEFAULT_LANG)
        lang = lang.split(',')[0].lower()
        if lang.startswith('en'):
            lang = "en-us"
        if lang.startswith('zh'):
            lang = "zh-cn"
        if not isinstance(lang, unicode):
            lang = force_unicode(lang)
        if lang not in get_support_langs():
            lang = DEFAULT_LANG
        save_current_lang(lang)
    return lang

def save_current_lang(lang):
    if not isinstance(lang, unicode):
        lang = force_unicode(lang)
    if not lang_table.has_key(lang):
        lang = DEFAULT_LANG
        
    cookie = Cookie.SimpleCookie()
    now = time.asctime()
    cookie[COOKIE_NAME] = simplejson.dumps(lang)
    cookie[COOKIE_NAME]['expires'] = now[:-4] + str(int(now[-4:])+1) + ' GMT'
    cookie[COOKIE_NAME]['path'] = '/'
    cc_cookies.add_cookie(cookie)
    return cookie

def find_msg_index(msg):
    if not isinstance(msg, unicode):
        msg = force_unicode(msg)
    for lang in lang_table.keys():
        index = 0
        for m in lang_table[lang]:
            if force_unicode(m) == msg:
                return index
            index += 1

    raise Exception(u"can not find '%s'"%(msg))
        
def ugettext(msg):
    lang = get_current_lang()
    try:
        return force_unicode(lang_table[lang][find_msg_index(msg)])
    except:
        logging.exception(u'can not found:  %s for %s'%(msg,lang))
        return force_unicode(msg)

re_seq = re.compile(r'(?P<replacer>%(?P<seq>\d+))')
def ungettext(msg, *argvs):
    lang = get_current_lang()
    try:
        msg = force_unicode(lang_table[lang][find_msg_index(msg)])
    except:
        logging.exception(u'can not found:  %s for %s'%(msg,lang))
    try:
        seq_iter = re_seq.finditer(msg)
        newmsg = StringIO()
        start = 0
        for match in seq_iter:
            seq = long(match.group('seq'))
            span = match.span()
            newmsg.write( ("%s"%force_unicode(msg[start:span[0]])).encode('utf-8') )
            newmsg.write( ("%s"%force_unicode(argvs[seq])).encode('utf-8') )
            start = span[1]
        newmsg.write( ("%s"%force_unicode(msg[start:])).encode('utf-8') )
        msg = newmsg.getvalue()
        newmsg.close()
        return force_unicode(msg)
    except:
        logging.exception(u'translate error: %s'%msg)
    return force_unicode(msg)
    
_ = ugettext
_m = ungettext

class ccTranslations(object):
    def ugettext(self, *argvs, **kwds):
        return ugettext(*argvs, **kwds)

    def ungettext(self, *argvs, **kwds):
        return ungettext(*argvs, **kwds)

def main():
    pass

if __name__ == '__main__':
  main()
