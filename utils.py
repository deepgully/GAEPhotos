# -*- coding: utf-8 -*-
from __future__ import with_statement
import logging
from time import gmtime
from datetime import datetime

VERSION = "1.01"

def _dump_date(d, delim):
    """Used for `http_date` and `cookie_date`."""
    if d is None:
        d = gmtime()
    elif isinstance(d, datetime):
        d = d.utctimetuple()
    elif isinstance(d, (int, long, float)):
        d = gmtime(d)
    return '%s, %02d%s%s%s%s %02d:%02d:%02d GMT' % (
        ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')[d.tm_wday],
        d.tm_mday, delim,
        ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep',
         'Oct', 'Nov', 'Dec')[d.tm_mon - 1],
        delim, str(d.tm_year), d.tm_hour, d.tm_min, d.tm_sec
        )

def http_date(timestamp=None):
    """Formats the time to match the RFC1123 date format.

    Accepts a floating point number expressed in seconds since the epoc in, a
    datetime object or a timetuple.  All times in UTC.  The :func:`parse_date`
    function can be used to parse such a date.

    Outputs a string in the format ``Wdy, DD Mon YYYY HH:MM:SS GMT``.

    :param timestamp: If provided that date is used, otherwise the current.
    """
    return _dump_date(timestamp, ' ')

class ImageMime:
    GIF = "image/gif"
    JPEG = "image/jpeg"
    TIFF = "image/tiff"
    PNG = "image/png"
    BMP = "image/bmp"
    ICO = "image/x-icon"
    UNKNOWN = "application/octet-stream"

def get_img_type(binary):
    size = len(binary)
    if size >= 6 and binary.startswith("GIF"):
        return ImageMime.GIF
    elif size >= 8 and binary.startswith("\x89PNG\x0D\x0A\x1A\x0A"):
        return ImageMime.PNG
    elif size >= 2 and binary.startswith("\xff\xD8"):
        return ImageMime.JPEG
    elif (size >= 8 and (binary.startswith("II\x2a\x00") or
                         binary.startswith("MM\x00\x2a"))):
        return ImageMime.TIFF
    elif size >= 2 and binary.startswith("BM"):
        return ImageMime.BMP
    elif size >= 4 and binary.startswith("\x00\x00\x01\x00"):
        return ImageMime.ICO
    else:
        return ImageMime.UNKNOWN

def create_blob_file(mime_type, binary):
    from google.appengine.api import files
    blob_file_name = files.blobstore.create(mime_type=mime_type)
    with files.open(blob_file_name, 'a') as f:
        f.write(binary)
    files.finalize(blob_file_name)
    blob_key = files.blobstore.get_blob_key(blob_file_name)
    return blob_key

def get_watermark_img_from_google_chart(str_watermark, font_size=20, color="cccccc", out_color="000000"):
    from google.appengine.api import urlfetch
    result = urlfetch.fetch(r'http://chart.googleapis.com/chart'\
          r'?chst=d_text_outline&chld=%s|%s|l|%s|_|%s'%(color,font_size,out_color,str_watermark))
    if result.status_code == 200:
        if get_img_type(result.content) != ImageMime.UNKNOWN:
            return result.content
    return None

if __name__ == '__main__':
    pass