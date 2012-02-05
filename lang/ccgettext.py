# -*- coding: utf-8 -*-
import os,sys
import stat,fnmatch
import re
from pprint import pformat

def get_file_list(path, ext, subdir = True ):
    if os.path.exists(path):
        dirlist = []

        for name in os.listdir(path):
            fullname = os.path.join(path, name)
            st = os.lstat(fullname)
            if stat.S_ISDIR(st.st_mode) and subdir:
                dirlist +=  get_file_list(fullname,ext)
            elif os.path.isfile(fullname):
                if fnmatch.fnmatch( fullname, ext):
                    dirlist.append(fullname)
            else:
                pass
        return dirlist
    else:
        return []

re_gettext = re.compile(r"_{1,2}\('(?P<word>.+?)'.*\)")
re_gettext2 = re.compile(r'_{1,2}\("(?P<word>.+?)".*\)')
project_path = os.path.abspath("..")
def main():
    print(project_path)
    pyFiles = get_file_list(project_path, '*.py', True)
    htmlFiles = get_file_list(project_path, '*.html', True)
    words = []
    for fname in pyFiles+htmlFiles:
        f = open(fname, 'r')
        content = f.read()
        f.close()
        iterator = re_gettext.finditer(content)
        matches = list(iterator)
        iterator = re_gettext2.finditer(content)
        matches += list(iterator)
        for match in matches:
            words.append(unicode(match.group('word')))

    words = list(set(words))
    print(words)
    lang_file = open(os.path.join(os.path.abspath("."),'lang.py'), 'w')
    lang_file.write(pformat(words, indent = 0, width=120,))
    lang_file.close()

if __name__ == '__main__':
    main()