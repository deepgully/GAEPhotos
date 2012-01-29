# -*- coding: utf-8 -*-
import logging
from google.appengine.ext import db
from google.appengine.api import images
from google.appengine.api import datastore
from google.appengine.api import blobstore

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
                if t == list:
                    val = val.split(",")
                elif t == bool:
                    val = val.strip().capitalize()
                    if val == "True" or val == u"True":
                        val = True
                    else:
                        val = False
                elif t == basestring:
                    try:
                        val = str(val)
                    except:
                        val = unicode(val)
                else:
                    val = t(val)
                setattr(self,p,val)

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
    latest_comments_count = db.IntegerProperty(default=5)
    max_upload_size = db.FloatProperty(default=2.0)  #max size(M)
    adminlist = db.ListProperty(str, default=[])

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
        dbalbum = cls.get_or_insert(key_name, name=name, description=description,
            public=public, parent=cls.db_parent, **kwds)
        return dbalbum

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
        for photo in photos:
            photo_keys.append(photo.key())
            blob_keys.append(photo.blob_key)
            thumb_blob_keys.append(photo.thumb_blob_key)

        def txn():
            remove(photo_keys)
            db.delete(photo_keys)
            self.delete()
        db.run_in_transaction(txn)
        blobstore.delete(blob_keys)
        blobstore.delete(thumb_blob_keys)

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
        return "%s/%s/%s"%(self.site, self.album_name, self.photo_name)

    @property
    def thumb_url(self):
        return "%s/%s/%s/thumb/"%(self.site, self.album_name, self.photo_name)

    def remove(self):
        blobstore.delete(self.blod_key)
        blobstore.delete(self.thumb_blob_key)
        self.remove()

    @classmethod
    def get_photo_by_name(cls, album_name, photo_name):
        key_name = cls.gen_key_name(album_name=album_name, photo_name=photo_name)
        return cls.get_by_key_name(key_name, parent=cls.db_parent)

    @classmethod
    def get_url_from_keyname(cls, key_name):
        return key_name[8:]
    @classmethod
    def get_thumb_url_from_keyname(cls, key_name):
        return "%s/thumb/"%key_name[8:]

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
        thumb = images.resize(binary, 480, 360)
        thumb_blob_key = utils.create_blob_file(utils.ImageMime.PNG, thumb)
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
            }

class DBComment(BaseModel):
    photo_key_name = db.StringProperty(required=True) #photo_key_name
    author = db.StringProperty()
    date = db.DateTimeProperty(auto_now_add=True)
    content = db.StringProperty(required=True, multiline=True)

if __name__ == '__main__':
    pass