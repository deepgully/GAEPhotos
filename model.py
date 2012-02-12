# -*- coding: utf-8 -*-
import logging
from google.appengine.ext import db
from google.appengine.api import images
from google.appengine.api import datastore
from google.appengine.api import blobstore
from google.appengine.runtime import DeadlineExceededError

import utils

# DataStore Cache in Memory
_db_get_cache = {}
logging.info("init db cache")

def get(keys, **kwargs):
    keys, multiple = datastore.NormalizeAndTypeCheckKeys(keys)
    ret = db.get([key for key in keys if key not in _db_get_cache], **kwargs)
    if (len(ret) == 1) and (ret[0] == None):
        return
    _db_get_cache.update(dict([(x.key(), x) for x in ret if x is not None]))
    ret = [_db_get_cache.get(k, None) for k in keys]
    if multiple:
        return ret
    if len(ret) > 0:
        return ret[0]


def remove(keys):
    keys, _ = datastore.NormalizeAndTypeCheckKeys(keys)
    return [_db_get_cache.pop(k) for k in keys if k in _db_get_cache]


def call_method_with_list(method, keylist, page=8):
    import math
    pages = long(math.ceil(len(keylist)/float(page)))
    for i in xrange(pages):
        method(keylist[(i-1)*page:i*page])

class DBParent(db.Model):
    pass

BASEMODEL_PARENT = DBParent.get_or_insert("DBParent_basemodel_parent")

class BaseModel(db.Model):
    key_template = ""
    db_parent = BASEMODEL_PARENT

    @property
    def id(self):
        return self.key().id()

    def save_settings(self, **kwds):
        props = self.properties()
        for p in props.keys():
            if unicode(p) in kwds:
                val = kwds.get(p)
                t = props[p].data_type
                if t == list and not isinstance(val, list):
                    val = [line.strip() for line in val.strip().split("\n") if (line and line.strip())]
                elif t == bool and not isinstance(val, bool):
                    val = val.strip().capitalize()
                    if val == "False" or val == u"False":
                        val = False
                    else:
                        val = True
                elif t == basestring:
                    try:
                        val = str(val).strip()
                    except:
                        val = unicode(val).strip()
                else:
                    val = t(val)
                setattr(self, p, val)

        self.save()
        return self

    def put(self):
        count = 0
        while count < 3:
            try:
                ret = db.Model.put(self)
                if ret:
                    break
            except db.Timeout:
                count += 1
        else:
            raise db.Timeout()
        remove(self.key())
        return ret

    save = put
    Save = put

    def delete(self):
        remove(self.key())
        return super(BaseModel, self).delete()

    @classmethod
    def gen_key_name(cls, **kw):
        try:
            return cls.key_template % kw
        except KeyError:
            logging.warn('generate key_name failed: %s <- %s',
                cls.key_template, kw)

    @classmethod
    def get_by_key_name(cls, key_names, parent=None, **kwargs):
        try:
            if not parent:
                parent = cls.db_parent
            parent = db._coerce_to_key(parent)
        except db.BadKeyError, e:
            raise db.BadArgumentError(str(e))
        rpc = datastore.GetRpcFromKwargs(kwargs)
        key_names, multiple = datastore.NormalizeAndTypeCheck(key_names, basestring)
        keys = [datastore.Key.from_path(cls.kind(), name, parent=parent)
                for name in key_names]
        if multiple:
            return get(keys, rpc=rpc)
        else:
            return get(keys[0], rpc=rpc)

    @classmethod
    def get_by_id(cls, ids, parent=None, **kwargs):
        if not parent:
            parent = cls.db_parent
        rpc = datastore.GetRpcFromKwargs(kwargs)
        if isinstance(parent, db.Model):
            parent = parent.key()
        ids, multiple = datastore.NormalizeAndTypeCheck(ids, (int, long))
        keys = [datastore.Key.from_path(cls.kind(), id, parent=parent)
                for id in ids]
        if multiple:
            return get(keys, rpc=rpc)
        else:
            return get(keys[0], rpc=rpc)

# DataStore Models
class DBSiteSettings(BaseModel):
    key_template = "dbsitesettings/%(owner)s"

    title = db.StringProperty(default="GAE Photos")
    description = db.StringProperty(multiline=True, default="Photo gallery based on GAEPhotos")
    albums_per_page = db.IntegerProperty(default=8)
    thumbs_per_page = db.IntegerProperty(default=12)
    latest_photos_count = db.IntegerProperty(default=9)
    latest_comments_count = db.IntegerProperty(default=8)
    max_upload_size = db.FloatProperty(default=2.0)  #max size(M)
    enable_comment = db.BooleanProperty(default=True)
    enable_watermark = db.BooleanProperty(default=False)
    watermark = db.StringProperty(default="@GAEPhotos")
    watermark_size = db.IntegerProperty(default=20)
    watermark_position = db.IntegerProperty(default=8)  # images.BOTTOM_RIGHT
    watermark_opacity = db.FloatProperty(default=0.4)
    watermark_img = db.BlobProperty()
    block_referrers = db.BooleanProperty(default=False)
    unblock_sites_list = db.ListProperty(str, default=[])
    adminlist = db.ListProperty(str, default=[])
    albumlist = db.ListProperty(str, default=[])

    @property
    def AlbumList(self):
        if not self.albumlist:
            albums = DBAlbum.all()
            need_save = False
            for al in albums:
                need_save = True
                self.albumlist.insert(0, ",".join([al.name, str(al.public)]))
            if need_save:
                self.save()
        albums = []
        for album in self.albumlist:
            album = album.split(",")
            albums.append({"name": album[0],
                           "public": album[1] == "True"})
        return albums

    def add_album(self, album):
        self.albumlist.insert(0, ",".join([album.name, str(album.public)]))
        self.save()

    def remove_album(self, album):
        self.albumlist.remove(",".join([album.name, str(album.public)]))
        self.save()

    @classmethod
    def reset(cls):
        global SITE_SETTINGS
        SITE_SETTINGS.delete()
        SITE_SETTINGS = cls.get_or_insert("DBSiteSettings_site_settings", parent=cls.db_parent)

SITE_SETTINGS = DBSiteSettings.get_or_insert("DBSiteSettings_site_settings", parent=BASEMODEL_PARENT)

class DBAlbum(BaseModel):
    key_template = "dbalbum/%(albumname)s"
    name = db.StringProperty(multiline=False)
    owner = db.UserProperty()
    description = db.StringProperty(default="description", multiline=True)
    public = db.BooleanProperty(default=True)
    createdate = db.DateTimeProperty(auto_now_add=True)
    updatedate = db.DateTimeProperty(auto_now=True)
    photoslist = db.ListProperty(str)
    coverphoto = db.StringProperty(default="")

    @classmethod
    def check_exist(cls, name):
        key_name = cls.gen_key_name(albumname=name)
        return cls.get_by_key_name(key_name, parent=cls.db_parent)

    @classmethod
    def create(cls, name, description="", public=True, **kwds):
        key_name = cls.gen_key_name(albumname=name)

        def txn():
            dbalbum = cls(key_name=key_name, name=name, description=description,
                public=public, parent=cls.db_parent, **kwds)
            dbalbum.save()
            SITE_SETTINGS.add_album(dbalbum)
            return dbalbum

        return db.run_in_transaction(txn)

    @classmethod
    def get_all_albums(cls, is_admin=False, pagesize=20, start_cursor=None, order="-createdate"):
        if is_admin == True:
            query = cls.all().order(order)
        else:
            query = cls.all().filter("public =", True).order(order)
        query.with_cursor(start_cursor=start_cursor)
        albums = query.fetch(pagesize)
        end_cursor = query.cursor()
        return albums, end_cursor

    @classmethod
    def get_album_by_name(cls, name):
        key_name = cls.gen_key_name(albumname=name)
        return cls.get_by_key_name(key_name, parent=cls.db_parent)

    @property
    def photocount(self):
        return len(self.photoslist)

    @property
    def cover_url(self):
        if self.coverphoto:
            return DBPhoto.get_thumb_url_from_keyname(self.coverphoto)
        if self.photoslist:
            return DBPhoto.get_thumb_url_from_keyname(self.photoslist[0])
        return "/static/images/cover.jpg"

    def add_photo_to_album(self, photo):
        photo_key_name = photo.key().name()
        if photo_key_name not in self.photoslist:
            self.photoslist.insert(0, photo_key_name)
            self.save()
        return self

    def remove(self):
        photos = DBPhoto.get_by_key_name(self.photoslist)
        photo_keys = []
        blob_keys = []
        thumb_blob_keys = []
        comments_keys = []
        for photo in photos:
            photo_keys.append(photo.key())
            blob_keys.append(photo.blob_key)
            thumb_blob_keys.append(photo.thumb_blob_key)
            comments_keys = comments_keys + [comment.key() for comment in
                                             DBComment.get_comments(photo.album_name, photo.photo_name)]

        def txn():
            remove(photo_keys)
            remove(comments_keys)
            db.delete(comments_keys)
            SITE_SETTINGS.remove_album(self)
            db.delete(photo_keys)
            self.delete()

        db.run_in_transaction(txn)
        blobstore.delete(blob_keys)
        blobstore.delete(thumb_blob_keys)

    def delete_photos_by_name(self, photo_names):
        photo_key_name_list = []
        for photo_name in photo_names:
            photo_key_name_list.append(DBPhoto.gen_key_name(album_name=self.name, photo_name=photo_name))
        photos = DBPhoto.get_by_key_name(photo_key_name_list)
        photo_keys = []
        blob_keys = []
        thumb_blob_keys = []
        comments_keys = []
        for photo in photos:
            photo_keys.append(photo.key())
            blob_keys.append(photo.blob_key)
            thumb_blob_keys.append(photo.thumb_blob_key)
            comments_keys = comments_keys + [comment.key() for comment in
                                             DBComment.get_comments(photo.album_name, photo.photo_name)]

        def txn():
            remove(photo_keys)
            db.delete(photo_keys)
            remove(comments_keys)
            db.delete(comments_keys)
            for photo_key_name in photo_key_name_list:
                self.photoslist.remove(photo_key_name)
                if photo_key_name == self.coverphoto:
                    self.coverphoto = ""
            self.save()
            return len(photo_keys)

        count = db.run_in_transaction(txn)
        try:
            call_method_with_list(blobstore.delete, blob_keys, 8)
        except DeadlineExceededError:
            call_method_with_list(blobstore.delete, blob_keys, 2)
        except:
            logging.exception("delete blob")
        try:
            call_method_with_list(blobstore.delete, thumb_blob_keys, 8)
        except DeadlineExceededError:
            call_method_with_list(blobstore.delete, thumb_blob_keys, 2)
        except:
            logging.exception("delete thumb blob")
        return count

    def set_cover_photo(self, photo_name):
        photo_key_name = DBPhoto.gen_key_name(album_name=self.name, photo_name=photo_name)
        photo = DBPhoto.get_by_key_name(photo_key_name)
        if not photo:
            return False
        self.coverphoto = photo_key_name
        self.save()
        return True

    def to_dict(self):
        return {
            "name": self.name,
            "owner": (self.owner and self.owner.nickname()) or "",
            "description": self.description,
            "public": self.public,
            "createdate": self.createdate.isoformat(),
            "updatedate": self.updatedate.isoformat(),
            "photoslist": self.photoslist,
            "cover_url": self.cover_url,
            "photocount": self.photocount,
            }


class DBPhoto(BaseModel):
    key_template = "dbphoto/%(album_name)s/%(photo_name)s"
    album_name = db.StringProperty()
    photo_name = db.StringProperty()
    public = db.BooleanProperty(default=False)
    owner = db.UserProperty()
    mime = db.StringProperty()
    size = db.IntegerProperty()
    createdate = db.DateTimeProperty(auto_now_add=True)
    description = db.StringProperty(multiline=True, default="")
    blob_key = db.StringProperty()
    thumb_blob_key = db.StringProperty()
    site = db.StringProperty(default="")

    @property
    def url(self):
        return "%s/%s/%s" % (self.site, self.album_name, self.photo_name)

    @property
    def thumb_url(self):
        return "%s/%s/%s/thumb/" % (self.site, self.album_name, self.photo_name)

    @property
    def isPublic(self):
        return self.public

    def remove(self):
        blobstore.delete(self.blod_key)
        blobstore.delete(self.thumb_blob_key)
        DBComment.del_comments(self.album_name, self.photo_name)
        self.remove()

    @classmethod
    def get_photo_by_name(cls, album_name, photo_name):
        key_name = cls.gen_key_name(album_name=album_name, photo_name=photo_name)
        return cls.get_by_key_name(key_name, parent=cls.db_parent)

    @classmethod
    def get_latest_photos(cls, count, is_admin=False):
        if is_admin:
            return cls.all().order("-createdate").fetch(count)
        else:
            return cls.all().order("-createdate").filter("public =", True).fetch(count)

    @classmethod
    def get_names_from_key_name(cls, key_name):
        names = key_name.split('/')
        return names[1], names[2]

    @classmethod
    def get_url_from_keyname(cls, key_name):
        return key_name[8:]

    @classmethod
    def get_thumb_url_from_keyname(cls, key_name):
        return "%s/thumb/" % key_name[8:]

    @classmethod
    def get_slider_url_from_keyname(cls, key_name):
        names = key_name.split('/')
        return "/slider/%s/#%s"%(names[1], names[2])

    @classmethod
    def create(cls, album_name, file_name, binary, **kwds):
        photo_key_name = DBPhoto.gen_key_name(album_name=album_name, photo_name=file_name)
        photo = DBPhoto.get_by_key_name(photo_key_name)
        if photo:
            raise Exception("file existed")

        photo = cls(key_name=photo_key_name, album_name=album_name, parent=cls.db_parent, **kwds)
        photo.photo_name = file_name
        photo.size = len(binary)
        mime_type = utils.get_img_type(binary)
        photo.mime = mime_type
        blob_key = utils.create_blob_file(mime_type, binary)
        thumb = images.resize(binary, 280, 210, images.JPEG)
        thumb_blob_key = utils.create_blob_file(utils.ImageMime.JPEG, thumb)
        photo.blob_key = str(blob_key)
        photo.thumb_blob_key = str(thumb_blob_key)
        photo.save()
        return photo

    def to_dict(self):
        return {
            "photo_name": self.photo_name,
            "album_name": self.album_name,
            "owner": (self.owner and self.owner.nickname()) or "",
            "createdate": self.createdate.isoformat(),
            "description": self.description,
            "mime": self.mime,
            "size": self.size,
            "url": self.url,
            "thumb_url": self.thumb_url,
            "public": self.public,
            }


class DBComment(BaseModel):
    photo_key_name = db.StringProperty(required=True) #photo_key_name
    author = db.StringProperty()
    email = db.EmailProperty()
    public = db.BooleanProperty(default=True)
    date = db.DateTimeProperty(auto_now_add=True)
    content = db.StringProperty(required=True, multiline=True)

    @classmethod
    def create(cls, album_name, photo_name, content, **kwds):
        key_name = DBPhoto.gen_key_name(album_name=album_name, photo_name=photo_name)
        photo = DBPhoto.get_by_key_name(key_name)
        if not photo:
            raise Exception("photo not exist")
        comment = cls(parent=cls.db_parent, photo_key_name=key_name, content=content,
            public=photo.public, **kwds)
        comment.save()
        return comment

    @classmethod
    def get_comments(cls, album_name, photo_name, public=None):
        photo_key_name = DBPhoto.gen_key_name(album_name=album_name, photo_name=photo_name)
        if public:
            return cls.all().filter("photo_key_name =", photo_key_name).filter("public =", True)
        else:
            return cls.all().filter("photo_key_name =", photo_key_name)

    @classmethod
    def del_comments(cls, album_name, photo_name):
        comment_keys = [comment.key() for comment in cls.get_comments(album_name, photo_name)]
        remove(comment_keys)
        db.delete(comment_keys)

    @classmethod
    def del_comment_by_id(cls, comment_id):
        comment = DBComment.get_by_id(comment_id)
        if comment:
            photo_key_name = comment.photo_key_name
            remove(comment.key())
            comment.delete()
            return DBPhoto.get_names_from_key_name(photo_key_name)
        return None

    @classmethod
    def get_latest_comments(cls, count, public=None):
        if public:
            return cls.all().filter("public =", True).order("-date").fetch(count)
        else:
            return cls.all().order("-date").fetch(count)

    @property
    def avatar_url(self):
        import hashlib
        return "http://www.gravatar.com/avatar/%s?s=32"%(hashlib.md5(self.email.lower().strip()).hexdigest())

    @property
    def thumb_url(self):
        return DBPhoto.get_thumb_url_from_keyname(self.photo_key_name)

    @property
    def photo_url(self):
        return DBPhoto.get_url_from_keyname(self.photo_key_name)

    @property
    def slide_url(self):
        return DBPhoto.get_slider_url_from_keyname(self.photo_key_name)

    def to_dict(self):
        return {
            "id": self.id,
            "photo_key_name": self.photo_key_name,
            "photo_url": self.photo_url,
            "thumb_url": self.thumb_url,
            "author": self.author,
            "avatar_url": self.avatar_url,
            "content": self.content,
            "date": self.date.isoformat(),
            "public": self.public,
            }

def main():
    pass

if __name__ == '__main__':
    main()
