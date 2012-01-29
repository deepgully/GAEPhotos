# -*- coding: utf-8 -*-
import os
import cgi
import time
import logging
import jinja2
import webapp2
from webapp2_extras import json
from functools import wraps
from google.appengine.api import users
from google.appengine.ext import blobstore
from google.appengine.api import memcache
from google.appengine.ext.webapp import blobstore_handlers

import utils
import model

def dateformat(value, format='%Y-%m-%d'):
    return value.strftime(format)

jinja_env = jinja2.Environment(autoescape=True,
    loader=jinja2.FileSystemLoader(os.path.join(os.path.dirname(__file__), "templates")),
    extensions=['jinja2.ext.i18n'])

jinja_env.install_null_translations(True)
jinja_env.filters['date'] = dateformat

logging.info("init jinga")

# public classes and functions

def check_admin_auth():
    if users.is_current_user_admin():
        return True
    user = users.get_current_user()
    if not user:
        return False
    email = user.email()
    return email in model.SITE_SETTINGS.adminlist

def check_owner_auth():
    return users.is_current_user_admin()

def requires_site_owner(method):
    @wraps(method)
    def wrapper(*args, **kwargs):
        if not check_owner_auth():
            raise Exception("You are not authorized")
        else:
            return method(*args, **kwargs)
    return wrapper

def requires_site_admin(method):
    @wraps(method)
    def wrapper(*args, **kwargs):
        if not check_admin_auth():
            raise Exception("You are not authorized")
        else:
            return method(*args, **kwargs)
    return wrapper

def render_with_user_and_settings(templatename, context={}):
    template = jinja_env.get_template(templatename)
    context.update({"settings": model.SITE_SETTINGS,
                    "users": {"is_admin": check_admin_auth(),
                              "is_owner": check_owner_auth(),
                              "cur_user": users.get_current_user()}})
    return template.render(context)

def get_all_albums(pagesize=20, start_cursor=None, order="-createdate"):
    is_admin = check_admin_auth()
    albums, cursor = model.DBAlbum.get_all_albums(is_admin, pagesize, start_cursor, order)
    return albums, cursor

class myRequestHandler(webapp2.RequestHandler):
    def handle_exception(self, exception, debug):
        logging.exception("exception in handler")
        self.response.out.write(render_with_user_and_settings("error.html",{"error_msg":str(exception)}))

#ajax methods
ERROR_RES = {"status": "error",
             "error": "unknown error"}

@requires_site_owner
def ajax_delete_album(album_name):
    res = ERROR_RES.copy()
    album = model.DBAlbum.get_album_by_name(album_name)
    if album:
        album.remove()
        res["status"] = "ok"
    else:
        res["error"] = "album not exist"
    return res

@requires_site_admin
def ajax_create_album(name, description="description", public=True):
    res = ERROR_RES.copy()
    name = cgi.escape(name.strip())
    if len(name) > 30:
        raise Exception("album name too long(max 30 chars)")
    description = cgi.escape(description.strip()) or "description"
    if len(description) > 50:
        raise Exception("album description too long(max 50 chars)")
    if not isinstance(public, bool):
        public = public.strip().capitalize()
        if public == "True":
            public = True
        else:
            public = False
    album = model.DBAlbum.check_exist(name)
    if album:
        res["error"] = "name existed"
    else:
        album = model.DBAlbum.create(name, description, bool(public), owner=users.get_current_user())
        res.update(album.to_dict())
        res["status"] = "ok"
    return res

def ajax_get_all_albums(pagesize=20, albums_cursor=None, order="-createdate"):
    res = ERROR_RES.copy()
    pagesize = long(pagesize)
    albums, cursor = get_all_albums(pagesize, albums_cursor, order)
    res["cursor"] = cursor
    res["is_last_page"] = len(albums) < pagesize
    res["albums"] = [ab.to_dict() for ab in albums]
    res["status"] = "ok"
    return res

def ajax_get_album(album_name):
    res = ERROR_RES.copy()
    album = model.DBAlbum.get_album_by_name(album_name)
    if album:
        res["album"] = album.to_dict()
        res["status"] = "ok"
    else:
        res["error"] = "album not exist"
    return res

def ajax_get_album_photos(album_name, start_index=0, pagesize=20):
    res = ERROR_RES.copy()
    pagesize = long(pagesize)
    start_index = long(start_index)

    album = model.DBAlbum.get_album_by_name(album_name)
    if not album:
        raise Exception("album not exist")

    photos = model.DBPhoto.get_by_key_name(album.photoslist[start_index:start_index+pagesize])

    res["photos"] = [p.to_dict() for p in photos]
    res["is_last_page"] = len(photos) < pagesize
    res["status"] = "ok"
    return res

@requires_site_admin
def ajax_save_album(name, description, **kwds):
    res = ERROR_RES.copy()
    album = model.DBAlbum.get_album_by_name(name)
    if album:
        description = cgi.escape(description.strip())
        album = album.save_settings(description=description, **kwds)
        res["album"] = album.to_dict()
        res["status"] = "ok"
    else:
        res["error"] = "album not exist"
    return res

@requires_site_admin
def ajax_save_photo(album_name, photo_name, description, **kwds):
    res = ERROR_RES.copy()
    photo = model.DBPhoto.get_photo_by_name(album_name, photo_name)
    if photo:
        description = cgi.escape(description.strip())
        photo = photo.save_settings(description=description, **kwds)
        res["photo"] = photo.to_dict()
        res["status"] = "ok"
    else:
        res["error"] = "photo not exist"
    return res

@requires_site_admin
def ajax_get_upload_url():
    res = ERROR_RES.copy()
    res["status"] = "ok"
    res["upload_url"] = blobstore.create_upload_url("/admin/blobupload/")
    return res

AJAX_METHODS = {
    "create_album": ajax_create_album,
    "get_all_albums": ajax_get_all_albums,
    "get_album": ajax_get_album,
    "save_album": ajax_save_album,
    "delete_album": ajax_delete_album,
    "get_upload_url": ajax_get_upload_url,
    "get_album_photos": ajax_get_album_photos,
    "save_photo": ajax_save_photo,
}
def dispatch(parameters):
    result = ERROR_RES.copy()
    action = parameters.pop("action")
    logging.info("ajax action: %s"%(action))
    if action not in AJAX_METHODS:
        result["status"] = "error"
        result["error"] = "unsupported method"
    else:
        try:
            result = AJAX_METHODS[action](**parameters)
        except Exception,e:
            logging.exception("error in dispatch")
            result["error"] = str(e)
            result["status"] = "error"
    return json.encode(result)

#admin pages
class AdminAjaxPage(myRequestHandler):
    def post(self):
        self.response.out.write(dispatch(self.request.POST))
    def get(self):
        self.response.out.write(dispatch(self.request.GET))

class AdminUploadPage(myRequestHandler):
    @requires_site_admin
    def get(self):
        albums,albums_cursor = get_all_albums(pagesize=1000)
        self.response.out.write(render_with_user_and_settings('admin.upload.html', {"albums": albums}))
    @requires_site_admin
    def post(self):
        result = ERROR_RES.copy()
        try:
            binary = self.request.body
            if not binary:
                raise Exception("no file upload")
            if len(binary) > model.SITE_SETTINGS.max_upload_size*1024*1024:
                raise Exception("file size exceeded")

            fileinfo = json.decode(self.request.environ.get('HTTP_CONTENT_DISPOSITION','{}'))
            logging.info(fileinfo)

            file_name = fileinfo.get("file_name")
            if not file_name:
                raise Exception("no file name")
            file_name = cgi.escape(file_name)
            result["file_name"] = file_name

            album_name = fileinfo.get("album_name")
            album = model.DBAlbum.get_album_by_name(album_name)
            if not album:
                raise Exception("can not found album %s"%album_name)

            photo = model.DBPhoto.create(album_name, file_name, binary, owner=users.get_current_user())
            album.add_photo_to_album(photo)

            result["status"] = "ok"
            result["photo"] = photo.to_dict()

        except Exception,e:
            logging.exception("upload file error")
            result["status"] = "error"
            result["error"] = str(e)

        self.response.out.write(json.encode(result))

class UploadHandler(blobstore_handlers.BlobstoreUploadHandler):
    @requires_site_admin
    def post(self):
        upload_files = self.get_uploads()

class AdminSettingsPage(myRequestHandler):
    @requires_site_owner
    def get(self):
        self.response.out.write(render_with_user_and_settings('admin.settings.html', {}))
    @requires_site_owner
    def post(self):
        save = self.request.get("save")
        default = self.request.get("default")
        clear = self.request.get("clear")
        if save:
            model.SITE_SETTINGS.save_settings(**self.request.POST)
        elif default:
            model.DBSiteSettings.reset()
        self.redirect("/admin/settings/")

class LoginPage(myRequestHandler):
    def get(self):
        self.redirect(users.create_login_url(self.request.environ.get("HTTP_REFERER", "/")))


class LoginOutPage(myRequestHandler):
    def get(self):
        self.redirect(users.create_logout_url("/"))

#photos pages
class MainPage(myRequestHandler):
    def get(self):
        albums, albums_cursor = get_all_albums(pagesize=model.SITE_SETTINGS.albums_per_page)
        context = {"albums": albums,
                   "albums_cursor": albums_cursor,
                   "is_last_page": len(albums) < model.SITE_SETTINGS.albums_per_page
                   }
        self.response.out.write(render_with_user_and_settings('index.html', context))


class AlbumPage(myRequestHandler):
    def get(self, albumname):
        albumname = unicode(albumname, 'utf-8')
        album = model.DBAlbum.get_album_by_name(albumname)
        if not album:
            raise Exception("album not exist")
        photo_per_page = model.SITE_SETTINGS.thumbs_per_page
        context = {"album": album,
                   "last_page": (album.photocount-1)/photo_per_page,
                   "photo_per_page": photo_per_page,
                   "cur_page": 0,
                   "photos": model.DBPhoto.get_by_key_name(album.photoslist[:photo_per_page])
                   }
        self.response.out.write(render_with_user_and_settings('album.html', context))

CACHE_TIME = 3600*24*30
def get_blob_info_from_cache(albumname, photoname, type="photo"):
    key = "%s_%s_%s"%(type, albumname, photoname)
    blob_info = memcache.get(key)
    if not blob_info:
        photo = model.DBPhoto.get_photo_by_name(albumname, photoname)
        if photo:
            if type == "photo":
                blob_info = blobstore.BlobInfo.get(photo.blob_key)
            else:
                blob_info = blobstore.BlobInfo.get(photo.thumb_blob_key)
            if blob_info:
                memcache.set(key, blob_info)
    return blob_info

class PhotoPage(myRequestHandler, blobstore_handlers.BlobstoreDownloadHandler):
    def get(self, albumname, photoname):
        albumname = unicode(albumname, 'utf-8')
        photoname = unicode(photoname, 'utf-8')

        blob_info = get_blob_info_from_cache(albumname, photoname, "photo")
        if blob_info:
            self.response.headers['Date'] = utils.http_date()
            self.response.headers['Cache-Control'] = 'max-age=%d, public' % CACHE_TIME
            self.response.headers['Expires'] = utils.http_date(time.time() + CACHE_TIME)
            self.send_blob(blob_info)
        else:
            self.error(404)
            self.response.out.write('File Not Found')


class ThumbPage(myRequestHandler, blobstore_handlers.BlobstoreDownloadHandler):
    def get(self, albumname, photoname):
        albumname = unicode(albumname, 'utf-8')
        photoname = unicode(photoname, 'utf-8')

        blob_info = get_blob_info_from_cache(albumname, photoname, "thumb")
        if blob_info:
            self.response.headers['Date'] = utils.http_date()
            self.response.headers['Cache-Control'] = 'max-age=%d, public' % CACHE_TIME
            self.response.headers['Expires'] = utils.http_date(time.time() + CACHE_TIME)
            self.send_blob(blob_info)
        else:
            self.error(404)
            self.response.out.write('File Not Found')


class SliderPage(myRequestHandler):
    def get(self, albumname):
        self.response.out.write("slider --,%s" % (albumname))

app = webapp2.WSGIApplication([
    (r'/', MainPage),
    (r'/login/', LoginPage),
    (r'/logout/', LoginOutPage),
    (r'/admin/ajax/', AdminAjaxPage),
    (r'/admin/settings/', AdminSettingsPage),
    (r'/admin/blobupload/.*', UploadHandler),
    (r'/admin/upload/', AdminUploadPage),
    (r'/slider/([^/]*?)/{0,1}', SliderPage),
    (r'/([^/]*?)/{0,1}', AlbumPage),
    (r'/([^/]*?)/([^/]*?)/thumb/{0,1}', ThumbPage),
    (r'/([^/]*?)/([^/]*?)', PhotoPage),
],
    debug=True)

if __name__ == '__main__':
    pass