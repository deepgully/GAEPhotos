# -*- coding: utf-8 -*-
import os
import cgi
import time
import logging
import jinja2
import webapp2
from webapp2_extras import json
from functools import wraps
from django.utils.encoding import force_unicode
from google.appengine.api import users
from google.appengine.ext import blobstore
from google.appengine.api import memcache
from google.appengine.ext.webapp import blobstore_handlers

import utils
import model
from lang import save_current_lang
from lang import ugettext, ungettext, ccTranslations

_ = ugettext
__ = ungettext

def dateformat(value, format='%Y-%m-%d'):
    return value.strftime(format)

jinja_env = jinja2.Environment(autoescape=True,
    loader=jinja2.FileSystemLoader(os.path.join(os.path.dirname(__file__), "templates")),
    extensions=['jinja2.ext.i18n'])

jinja_env.install_gettext_translations(ccTranslations())
jinja_env.filters['date'] = dateformat

logging.info("init jinja2")

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


def check_login_auth():
    return users.get_current_user()


def requires_site_owner(method):
    @wraps(method)
    def wrapper(*args, **kwargs):
        if not check_owner_auth():
            raise Exception(_("You are not authorized"))
        else:
            return method(*args, **kwargs)

    return wrapper

def requires_site_admin(method):
    @wraps(method)
    def wrapper(*args, **kwargs):
        if not check_admin_auth():
            raise Exception(_("You are not authorized"))
        else:
            return method(*args, **kwargs)

    return wrapper

def requires_site_login(method):
    @wraps(method)
    def wrapper(*args, **kwargs):
        if not check_login_auth():
            raise Exception(_("You are not login"))
        else:
            return method(*args, **kwargs)

    return wrapper

def render_with_user_and_settings(templatename, context={}):
    template = jinja_env.get_template(templatename)
    context.update({"settings": model.SITE_SETTINGS,
                    "version": utils.VERSION,
                    "allalbums": get_album_list_from_settings(),
                    "users": {"is_admin": check_admin_auth(),
                              "is_owner": check_owner_auth(),
                              "cur_user": users.get_current_user()}})
    return template.render(context)


def get_album_list_from_settings():
    if check_admin_auth():
        return  model.SITE_SETTINGS.AlbumList
    return [album for album in model.SITE_SETTINGS.AlbumList if album.get("public")]


def get_all_albums(pagesize=20, start_cursor=None, order="-createdate"):
    is_admin = check_admin_auth()
    albums, cursor = model.DBAlbum.get_all_albums(is_admin, pagesize, start_cursor, order)
    return albums, cursor


class ccRequestHandler(webapp2.RequestHandler):
    def handle_exception(self, exception, debug):
        logging.exception("exception in handler")
        self.response.out.write(render_with_user_and_settings("error.html", {"error_msg": force_unicode(exception)}))


class ccPhotoRequestHandler(blobstore_handlers.BlobstoreDownloadHandler):
    CACHE_TIME = 3600 * 24 * 30
    URL_PHOTO_NOT_FOUND = "/static/images/image_not_found.jpg"
    URL_BLOCKED_REFERRER = "/static/images/no_hotlinking.gif"

    @staticmethod
    def get_blob_info_from_cache_or_db(albumname, photoname, type="photo"):
        key = "photo_cache_%s_%s_%s" % (type, albumname, photoname)
        blob_info = memcache.get(key)
        if not blob_info:
            photo = model.DBPhoto.get_photo_by_name(albumname, photoname)
            if photo:
                if type == "photo":
                    blob_key = photo.blob_key
                else:
                    blob_key = photo.thumb_blob_key
                blob_info = blobstore.get(blob_key)
                if blob_info:
                    try:
                        memcache.set(key, blob_info)
                    except:
                        pass
        return blob_info

    @staticmethod
    def create_watermark(binary, watermark, opacity=0.4):
        from google.appengine.api import images

        img = images.Image(binary)
        width = img.width
        height = img.height
        img = images.composite([(img._image_data, 0, 0, 1.0, images.TOP_LEFT),
            (watermark, -2, -2, opacity, images.BOTTOM_RIGHT),
        ], width, height, 0, images.PNG)
        return img


    def send_blob_with_watermark(self, blob_key_or_info, watermark=""):
        if isinstance(blob_key_or_info, blobstore.BlobInfo):
            blob_key = blob_key_or_info.key()
            blob_info = blob_key_or_info
        else:
            blob_key = blob_key_or_info
            blob_info = blobstore.get(blob_key)

        if not blob_info:
            self.redirect(self.URL_PHOTO_NOT_FOUND)

        key = "blob_cache_%s_%s" % (blob_key, watermark)
        image_data = memcache.get(key)
        if not image_data:
            blob_reader = blobstore.BlobReader(blob_key)
            image_data = ccPhotoRequestHandler.create_watermark(blob_reader.read(),
                watermark=model.SITE_SETTINGS.watermark_img)
            blob_reader.close()
            if image_data:
                try:
                    memcache.set(key, image_data)
                except:
                    pass
            else:
                self.redirect(self.URL_PHOTO_NOT_FOUND)

        self.response.headers['Content-Type'] = utils.ImageMime.PNG
        self.response.out.write(image_data)


    def send_photo(self, album_name, photo_name, photo_type):
        if self.check_referrer() == False:
            self.redirect(self.URL_BLOCKED_REFERRER)

        album = model.DBAlbum.get_album_by_name(album_name)
        if not album or (not album.public and not check_admin_auth()):
            self.redirect(self.URL_PHOTO_NOT_FOUND)

        blob_info = ccPhotoRequestHandler.get_blob_info_from_cache_or_db(album_name, photo_name, photo_type)
        if blob_info:
            self.response.headers['Date'] = utils.http_date()
            self.response.headers['Cache-Control'] = 'max-age=%d, public' % self.CACHE_TIME
            self.response.headers['Expires'] = utils.http_date(time.time() + self.CACHE_TIME)
            if photo_type == "photo" and model.SITE_SETTINGS.enable_watermark:
                self.send_blob_with_watermark(blob_info, model.SITE_SETTINGS.watermark)
            else:
                self.send_blob(blob_info)
        else:
            self.redirect(self.URL_PHOTO_NOT_FOUND)
            #self.error(404)
            #self.response.out.write('File Not Found')

    def check_referrer(self):
        if model.SITE_SETTINGS.block_referrers == False:
            return True
        referer = self.request.environ.get("HTTP_REFERER")
        if not referer:
            return True
        from urlparse import urlparse
        from urllib import splitport
        from fnmatch import fnmatch

        host = splitport(self.request.environ.get("HTTP_HOST", ''))[0]
        refer_host = urlparse(referer).hostname
        if host.lower() == refer_host.lower():
            return True
        for site_pattern in model.SITE_SETTINGS.unblock_sites_list:
            if fnmatch(referer, site_pattern):
                return True
        return False

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
        res["error"] = _("album not exist")
    return res

MAX_ALBUM_NAME = 30
MAX_DESCRIPTION = 50

@requires_site_admin
def ajax_create_album(name, description="description", public=True):
    res = ERROR_RES.copy()
    name = name.strip().replace("&", "").replace("#", "").replace("?", "").replace("$", "").replace("^", "").replace(";"
        , "")
    name = name.replace("*", "").replace("/", "").replace("\\", "").replace("<", "").replace(">", "").replace(",", "")
    if not name:
        raise Exception(_("album name is blank"))
    if len(name) > MAX_ALBUM_NAME:
        raise Exception(__("album name too long[max %0 chars]", MAX_ALBUM_NAME))
    description = cgi.escape(description.strip()) or "description"
    if len(description) > MAX_DESCRIPTION:
        raise Exception(__("album description too long[max %0 chars]", MAX_DESCRIPTION))
    if name.lower() in RESERVED_ALBUM_NAME:
        raise Exception(_("unusable album name"))
    if not isinstance(public, bool):
        public = public.strip().capitalize()
        if public == "True":
            public = True
        else:
            public = False
    album = model.DBAlbum.check_exist(name)
    if album:
        res["error"] = _("album name already exists")
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
        res["error"] = _("album not exist")
    return res


def ajax_get_album_photos(album_name, start_index=0, pagesize=20):
    res = ERROR_RES.copy()
    pagesize = long(pagesize)
    start_index = long(start_index)

    album = model.DBAlbum.get_album_by_name(album_name)
    if not album:
        raise Exception(_("album not exist"))

    photos = model.DBPhoto.get_by_key_name(album.photoslist[start_index:start_index + pagesize])

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
        res["error"] = _("album not exist")
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
        res["error"] = _("photo not exist")
    return res


@requires_site_admin
def ajax_delete_photos(album_name, photos):
    res = ERROR_RES.copy()
    photo_names = photos.split(",")
    album = model.DBAlbum.get_album_by_name(album_name)
    if album:
        count = album.delete_photos_by_name(photo_names)
        res["status"] = "ok"
        res["count"] = count
    else:
        res["error"] = _("album not exist")
    return res


@requires_site_admin
def ajax_set_cover_photo(album_name, photo_name):
    res = ERROR_RES.copy()
    album = model.DBAlbum.get_album_by_name(album_name)
    if album:
        if album.set_cover_photo(photo_name):
            res["status"] = "ok"
        else:
            res["error"] = _("photo not exist")
    else:
        res["error"] = _("album not exist")
    return res


@requires_site_admin
def ajax_get_upload_url():
    res = ERROR_RES.copy()
    res["status"] = "ok"
    res["upload_url"] = blobstore.create_upload_url("/admin/blobupload/")
    return res


@requires_site_login
def ajax_create_comment(album_name, photo_name, comment):
    res = ERROR_RES.copy()
    user = users.get_current_user()
    comment = model.DBComment.create(album_name, photo_name, comment, author=user.nickname(), email=user.email())

    key = "comment_%s_%s"%(album_name, photo_name)
    memcache.delete(key)
    res["status"] = "ok"
    res["comment"] = comment.to_dict()
    return res


@requires_site_owner
def ajax_delete_comments(album_name, photo_name):
    res = ERROR_RES.copy()
    model.DBComment.del_comments(album_name, photo_name)
    key = "comment_%s_%s"%(album_name, photo_name)
    memcache.delete(key)
    res["status"] = "ok"
    return res


def ajax_get_comments(album_name, photo_name):
    res = ERROR_RES.copy()
    key = "comment_%s_%s"%(album_name, photo_name)
    comments = memcache.get(key)
    if not comments:
        if check_admin_auth():
            comments = model.DBComment.get_comments(album_name, photo_name)
        else:
            comments = model.DBComment.get_comments(album_name, photo_name, public=True)
        comments = [comment.to_dict() for comment in comments]
        try:
            memcache.set(key, comments)
        except:
            pass
    res["status"] = "ok"
    res["comments"] = comments
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
    "delete_photos": ajax_delete_photos,
    "set_cover_photo": ajax_set_cover_photo,
    "get_comments": ajax_get_comments,
    "delete_comments": ajax_delete_comments,
    "create_comment": ajax_create_comment,
    }

def dispatch(parameters):
    result = ERROR_RES.copy()
    action = parameters.pop("action")
    logging.info("ajax action: %s" % (action))
    if action not in AJAX_METHODS:
        result["status"] = "error"
        result["error"] = _("unsupported method")
    else:
        try:
            result = AJAX_METHODS[action](**parameters)
        except Exception, e:
            logging.exception("error in dispatch")
            result["error"] = force_unicode(e)
            result["status"] = "error"
    return json.encode(result)

#admin pages
class AdminAjaxPage(ccRequestHandler):
    def post(self):
        self.response.out.write(dispatch(self.request.POST))

    def get(self):
        self.response.out.write(dispatch(self.request.GET))


class AdminUploadPage(ccRequestHandler):
    @requires_site_admin
    def get(self):
        albums = model.SITE_SETTINGS.AlbumList
        self.response.out.write(render_with_user_and_settings('admin.upload.html', {"albums": albums}))

    @requires_site_admin
    def post(self):
        result = ERROR_RES.copy()
        try:
            binary = self.request.body
            if not binary:
                raise Exception(_("no upload file"))
            if len(binary) > model.SITE_SETTINGS.max_upload_size * 1024 * 1024:
                raise Exception(_("file size exceeds"))
            if utils.get_img_type(binary) == utils.ImageMime.UNKNOWN:
                raise Exception(_("unsupported file type"))

            fileinfo = json.decode(self.request.environ.get('HTTP_CONTENT_DISPOSITION', '{}'))
            logging.info(fileinfo)

            file_name = fileinfo.get("file_name")
            if not file_name:
                raise Exception(_("no file name"))
            file_name = cgi.escape(file_name)
            result["file_name"] = file_name

            album_name = fileinfo.get("album_name")
            album = model.DBAlbum.get_album_by_name(album_name)
            if not album:
                raise Exception(_("album not exist"))

            photo = model.DBPhoto.get_photo_by_name(album_name, file_name)
            if photo:
                raise Exception(_("photo already exists in this album"))
            photo = model.DBPhoto.create(album_name, file_name, binary, owner=users.get_current_user())
            album.add_photo_to_album(photo)

            result["status"] = "ok"
            result["photo"] = photo.to_dict()

        except Exception, e:
            logging.exception("upload file error")
            result["status"] = "error"
            result["error"] = force_unicode(e)

        self.response.out.write(json.encode(result))


class UploadHandler(blobstore_handlers.BlobstoreUploadHandler):
    @requires_site_admin
    def post(self):
        upload_files = self.get_uploads()


class AdminSettingsPage(ccRequestHandler):
    @requires_site_owner
    def get(self):
        self.response.out.write(render_with_user_and_settings('admin.settings.html', {}))

    @requires_site_owner
    def post(self):
        save = self.request.get("save")
        default = self.request.get("default")
        clear = self.request.get("clear")
        if save:
            settings = {}
            settings.update(self.request.POST)
            settings["enable_comment"] = bool(settings.get("enable_comment"))
            settings["enable_watermark"] = bool(settings.get("enable_watermark"))
            settings["block_referrers"] = bool(settings.get("block_referrers"))

            if settings["enable_watermark"]:
                watermark = settings.get("watermark", "").strip()
                settings["enable_watermark"] = False
                if watermark:
                    watermark_img = utils.get_watermark_img_from_google_chart(watermark)
                    if watermark_img:
                        settings["watermark_img"] = watermark_img
                        settings["enable_watermark"] = True
            model.SITE_SETTINGS.save_settings(**settings)
        elif default:
            model.DBSiteSettings.reset()
        self.redirect("/admin/settings/")


class LoginPage(ccRequestHandler):
    def get(self):
        self.redirect(users.create_login_url(self.request.environ.get("HTTP_REFERER", "/")))


class LoginOutPage(ccRequestHandler):
    def get(self):
        self.redirect(users.create_logout_url(self.request.environ.get("HTTP_REFERER", "/")))

#photos pages
class MainPage(ccRequestHandler):
    def get(self):
        lang = self.request.get("lang")
        if lang:
            cookie = save_current_lang(lang, self.response)
            self.redirect(self.request.environ.get("HTTP_REFERER", "/"))
        albums, albums_cursor = get_all_albums(pagesize=model.SITE_SETTINGS.albums_per_page)
        context = {"albums": albums,
                   "albums_cursor": albums_cursor,
                   "latestphotos": model.DBPhoto.get_latest_photos(model.SITE_SETTINGS.latest_photos_count),
                   "is_last_page": len(albums) < model.SITE_SETTINGS.albums_per_page
        }
        if model.SITE_SETTINGS.enable_comment:
            latestcomments = model.DBComment.get_latest_comments(model.SITE_SETTINGS.latest_comments_count,
                public= not check_admin_auth())
            context.update({
                "latestcomments": latestcomments })
        self.response.out.write(render_with_user_and_settings('index.html', context))


class AlbumPage(ccRequestHandler):
    def get(self, albumname):
        albumname = force_unicode(albumname)
        album = model.DBAlbum.get_album_by_name(albumname)
        if not album or (not album.public and not check_admin_auth()):
            raise Exception(_("album not exist"))
        photo_per_page = model.SITE_SETTINGS.thumbs_per_page
        context = {"album": album,
                   "last_page": (album.photocount - 1) / photo_per_page,
                   "photo_per_page": photo_per_page,
                   "cur_page": 0,
                   "photos": model.DBPhoto.get_by_key_name(album.photoslist[:photo_per_page])
        }
        self.response.out.write(render_with_user_and_settings('album.html', context))


class SliderPage(ccRequestHandler):
    def get(self, albumname):
        albumname = force_unicode(albumname)
        album = model.DBAlbum.get_album_by_name(albumname)
        if not album or (not album.public and not check_admin_auth()):
            raise Exception(_("album not exist"))
        context = {"album": album,
                   "host_url": self.request.host_url,
                   "photos": model.DBPhoto.get_by_key_name(album.photoslist)
        }
        self.response.out.write(render_with_user_and_settings('slider.html', context))


class PhotoPage(ccPhotoRequestHandler):
    def get(self, albumname, photoname):
        self.send_photo(force_unicode(albumname), force_unicode(photoname), "photo")


class ThumbPage(ccPhotoRequestHandler):
    def get(self, albumname, photoname):
        self.send_photo(force_unicode(albumname), force_unicode(photoname), "thumb")

RESERVED_ALBUM_NAME = [u'login', u'logout', u'admin', u'slider']
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
], debug=True)

def main():
    logging.info("call main()")

if __name__ in ['__main__', 'main']:
    main()