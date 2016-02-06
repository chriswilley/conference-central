#!/usr/bin/env python
import httplib
import endpoints
from protorpc import messages
from google.appengine.ext import ndb
from google.appengine.ext.ndb import msgprop

"""models.py

Udacity conference server-side Python App Engine data & ProtoRPC models

$Id: models.py,v 1.1 2014/05/24 22:01:10 wesc Exp $

created/forked from conferences.py by wesc on 2014 may 24
modified by chris willey february 2016

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'
__contributor__ = 'cwilley@gmail.com (Chris Willey)'


class ConflictException(endpoints.ServiceException):
    """ConflictException -- exception mapped to HTTP 409 response"""
    http_status = httplib.CONFLICT


class Profile(ndb.Model):
    """Profile -- User profile object"""
    displayName = ndb.StringProperty()
    mainEmail = ndb.StringProperty()
    teeShirtSize = ndb.StringProperty(default='NOT_SPECIFIED')
    conferenceKeysToAttend = ndb.StringProperty(repeated=True)
    sessionWishList = ndb.StringProperty(repeated=True)


class ProfileMiniForm(messages.Message):
    """ProfileMiniForm -- update Profile form message"""
    displayName = messages.StringField(1)
    teeShirtSize = messages.EnumField('TeeShirtSize', 2)


class ProfileForm(messages.Message):
    """ProfileForm -- Profile outbound form message"""
    displayName = messages.StringField(1)
    mainEmail = messages.StringField(2)
    teeShirtSize = messages.EnumField('TeeShirtSize', 3)
    conferenceKeysToAttend = messages.StringField(4, repeated=True)
    websafeKey = messages.StringField(5)


class ProfileForms(messages.Message):
    """ProfileForms -- multiple Profile outbound form messages"""
    items = messages.MessageField(ProfileForm, 1, repeated=True)


class StringMessage(messages.Message):
    """StringMessage-- outbound (single) string message"""
    data = messages.StringField(1, required=True)


class BooleanMessage(messages.Message):
    """BooleanMessage-- outbound Boolean value message"""
    data = messages.BooleanField(1)


class Conference(ndb.Model):
    """Conference -- Conference object"""
    name = ndb.StringProperty(required=True)
    description = ndb.StringProperty()
    organizerUserId = ndb.StringProperty()
    topics = ndb.StringProperty(repeated=True)
    city = ndb.StringProperty()
    startDate = ndb.DateProperty()
    month = ndb.IntegerProperty()  # TODO: do we need for indexing like Java?
    endDate = ndb.DateProperty()
    maxAttendees = ndb.IntegerProperty()
    seatsAvailable = ndb.IntegerProperty()


class ConferenceForm(messages.Message):
    """ConferenceForm -- Conference outbound form message"""
    name = messages.StringField(1)
    description = messages.StringField(2)
    organizerUserId = messages.StringField(3)
    topics = messages.StringField(4, repeated=True)
    city = messages.StringField(5)
    startDate = messages.StringField(6)  # DateTimeField()
    month = messages.IntegerField(7, variant=messages.Variant.INT32)
    maxAttendees = messages.IntegerField(8, variant=messages.Variant.INT32)
    seatsAvailable = messages.IntegerField(9, variant=messages.Variant.INT32)
    endDate = messages.StringField(10)  # DateTimeField()
    websafeKey = messages.StringField(11)
    organizerDisplayName = messages.StringField(12)


class ConferenceForms(messages.Message):
    """ConferenceForms -- multiple Conference outbound form message"""
    items = messages.MessageField(ConferenceForm, 1, repeated=True)


class TeeShirtSize(messages.Enum):
    """TeeShirtSize -- t-shirt size enumeration value"""
    NOT_SPECIFIED = 1
    XS_M = 2
    XS_W = 3
    S_M = 4
    S_W = 5
    M_M = 6
    M_W = 7
    L_M = 8
    L_W = 9
    XL_M = 10
    XL_W = 11
    XXL_M = 12
    XXL_W = 13
    XXXL_M = 14
    XXXL_W = 15


class ConferenceQueryForm(messages.Message):
    """ConferenceQueryForm -- Conference query inbound form message"""
    field = messages.StringField(1)
    operator = messages.StringField(2)
    value = messages.StringField(3)


class ConferenceQueryForms(messages.Message):
    """ConferenceQueryForms -- multiple ConferenceQueryForm
    inbound form message"""
    filters = messages.MessageField(ConferenceQueryForm, 1, repeated=True)


class SessionType(messages.Enum):
    """SessionType -- session type enumeration value"""
    NOT_SPECIFIED = 1
    Brownbag = 2
    Keynote = 3
    Lecture = 4
    Roundtable = 5
    Workshop = 6


class Session(ndb.Model):
    """Session -- Conference Session object"""
    name = ndb.StringProperty(required=True)
    highlights = ndb.StringProperty()
    speaker = ndb.KeyProperty(kind='Profile')
    typeOfSession = msgprop.EnumProperty(SessionType)
    date = ndb.DateProperty(required=True)
    duration = ndb.IntegerProperty()  # length of session in minutes
    startTime = ndb.TimeProperty(required=True)


class SessionForm(messages.Message):
    """SessionForm -- Conference Session outbound form message"""
    name = messages.StringField(1)
    highlights = messages.StringField(2)
    speaker = messages.StringField(3)  # urlsafe key of speaker Profile
    speakerName = messages.StringField(4)
    typeOfSession = messages.EnumField('SessionType', 5)
    date = messages.StringField(6)
    duration = messages.IntegerField(7, variant=messages.Variant.INT32)
    startTime = messages.StringField(8)
    websafeConferenceKey = messages.StringField(9)
    websafeKey = messages.StringField(10)


class SessionForms(messages.Message):
    """SessionForms -- multiple Conference Session outbound form messages"""
    items = messages.MessageField(SessionForm, 1, repeated=True)


class SessionQueryForm(messages.Message):
    """SessionQueryForm -- Session query inbound form message"""
    field = messages.StringField(1)
    operator = messages.StringField(2)
    value = messages.StringField(3)


class SessionQueryForms(messages.Message):
    """SessionQueryForms -- multiple SessionQueryForm
    inbound form messages"""
    websafeConferenceKey = messages.StringField(1)
    filters = messages.MessageField(SessionQueryForm, 2, repeated=True)
