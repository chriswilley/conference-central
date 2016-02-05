#!/usr/bin/env python
from datetime import datetime

import endpoints
from protorpc import messages, message_types, remote

from google.appengine.api import memcache, taskqueue
from google.appengine.ext import ndb
from operator import attrgetter

from models import (
    BooleanMessage,
    Conference,
    ConferenceForm,
    ConferenceForms,
    ConferenceQueryForms,
    ConflictException,
    Profile,
    ProfileForm,
    ProfileForms,
    ProfileMiniForm,
    Session,
    SessionForm,
    SessionForms,
    SessionQueryForms,
    SessionType,
    StringMessage,
    TeeShirtSize
)

from settings import (
    WEB_CLIENT_ID,
    ANDROID_CLIENT_ID,
    IOS_CLIENT_ID,
    ANDROID_AUDIENCE
)

from utils import getUserId

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21
modified by chris willey february 2016

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'
__contributor__ = 'cwilley@gmail.com (Chris Willey)'


EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
ANNOUNCEMENT_TPL = ('Last chance to attend! The following conferences '
                    'are nearly sold out: %s')

MEMCACHE_FEATURED_SPEAKER_KEY = "FEATURED_SPEAKER"
FEATURED_SPEAKER_TPL = ('Featured speakers: %s.')
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [
        "Default",
        "Topic"
    ],
}

DEFAULT_SESSION_LENGTH = 30  # session length defaults to 30 minutes

OPERATORS = {
        'EQ':   '=',
        'GT':   '>',
        'GTEQ': '>=',
        'LT':   '<',
        'LTEQ': '<=',
        'NE':   '!='
    }

FIELDS = {
    'CITY': 'city',
    'TOPIC': 'topics',
    'MONTH': 'month',
    'MAX_ATTENDEES': 'maxAttendees',
}

SESSION_FIELDS = {
    'DURATION': 'duration',
    'START_TIME': 'startTime',
    'DATE': 'date',
    'TYPE_OF_SESSION': 'typeOfSession',
}

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_LIST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_LIST_BY_SPEAKER = endpoints.ResourceContainer(
    message_types.VoidMessage,
    speaker=messages.StringField(1),
)

SESSION_LIST_BY_TYPE = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    typeOfSession=messages.StringField(2),
)

SESSION_LIST_BY_USER_AS_SPEAKER = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_WISHLIST_ADD = endpoints.ResourceContainer(
    message_types.VoidMessage,
    sessionKey=messages.StringField(1),
)

SESSION_WISHLIST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_QUERY = endpoints.ResourceContainer(
    SessionQueryForms,
    websafeConferenceKey=messages.StringField(1),
)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(
    name='conference',
    version='v1',
    audiences=[ANDROID_AUDIENCE],
    allowed_client_ids=[
        WEB_CLIENT_ID,
        API_EXPLORER_CLIENT_ID,
        ANDROID_CLIENT_ID,
        IOS_CLIENT_ID
    ],
    scopes=[EMAIL_SCOPE]
)
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf

    def _createConferenceObject(self, request):
        """Create or update Conference object, returning
        ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException(
                "Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {
            field.name: getattr(
                request, field.name) for field in request.all_fields()
        }
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing
        # (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects;
        # set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(
                data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(
                data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={
            'email': user.email(),
            'conferenceInfo': repr(request)
        }, url='/tasks/send_confirmation_email')
        return request

    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {
            field.name: getattr(
                request, field.name) for field in request.all_fields()
        }

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' %
                request.websafeConferenceKey
            )

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(
        ConferenceForm,
        ConferenceForm,
        path='conference',
        http_method='POST',
        name='createConference'
    )
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)

    @endpoints.method(
        CONF_POST_REQUEST,
        ConferenceForm,
        path='conference/{websafeConferenceKey}',
        http_method='PUT',
        name='updateConference'
    )
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)

    @endpoints.method(
        CONF_GET_REQUEST,
        ConferenceForm,
        path='conference/{websafeConferenceKey}',
        http_method='GET',
        name='getConference'
    )
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' %
                request.websafeConferenceKey
            )
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(
        message_types.VoidMessage,
        ConferenceForms,
        path='getConferencesCreated',
        http_method='POST',
        name='getConferencesCreated'
    )
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[
                self._copyConferenceToForm(
                    conf, getattr(prof, 'displayName')) for conf in confs
            ]
        )

    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        filters = self._formatFilters(request.filters, kind='conference')

        qf = []
        sets = None
        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(
                filtr["field"], filtr["operator"], filtr["value"])
            qs = q.filter(formatted_query).fetch(keys_only=True)
            qf.append(qs)

        for idx, val in enumerate(qf):
            if (idx == 0):
                sets = set(val)
            else:
                sets = sets.intersection(val)

        if sets:
            q = ndb.get_multi(sets)

        return q

    def _formatFilters(self, filters, kind):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []

        for f in filters:
            filtr = {
                field.name: getattr(f, field.name) for field in f.all_fields()
            }

            try:
                if (kind == 'session'):
                    filtr["field"] = SESSION_FIELDS[filtr["field"]]
                else:
                    filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException(
                    "Filter contains invalid field or operator.")

            formatted_filters.append(filtr)
        return formatted_filters

    @endpoints.method(
        ConferenceQueryForms,
        ConferenceForms,
        path='queryConferences',
        http_method='POST',
        name='queryConferences'
    )
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [
            (ndb.Key(Profile, conf.organizerUserId)) for conf in conferences
        ]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
            items=[
                self._copyConferenceToForm(
                    conf, names[conf.organizerUserId]
                ) for conf in sorted(conferences, key=attrgetter('name'))
            ]
        )


# - - - Session objects - - - - - - - - - - - - - - - - - - -

    def _copySessionToForm(self, _session):
        """Copy relevant fields from Session to SessionForm."""
        sf = SessionForm()
        for field in sf.all_fields():
            if hasattr(_session, field.name):
                if (field.name == 'date' or field.name == 'startTime'):
                    setattr(sf, field.name, str(getattr(_session, field.name)))
                elif (field.name == 'speaker'):
                    if (getattr(_session, 'speaker')):
                        speaker = getattr(_session, 'speaker').get()
                        setattr(sf, field.name, speaker.displayName)
                    else:
                        setattr(sf, field.name, 'TBA')
                else:
                    setattr(sf, field.name, getattr(_session, field.name))
            elif field.name == "websafeKey":
                setattr(sf, field.name, _session.key.urlsafe())
        sf.check_initialized()
        return sf

    def _createSessionObject(self, request):
        """Create Session object, returning SessionForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            # require authorization to create Sessions
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # ensure required fields are filled out
        if not request.name:
            raise endpoints.BadRequestException("Session name required")
        if not request.date:
            raise endpoints.BadRequestException("Session date required")
        if not request.startTime:
            raise endpoints.BadRequestException("Session start time required")

        # copy SessionForm/ProtoRPC Message into dict
        data = {
            field.name: getattr(
                request, field.name) for field in request.all_fields()
        }
        del data['websafeConferenceKey']

        # find the conference that this session belongs to
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' %
                request.websafeConferenceKey
            )

        # if speaker id is included, get its Profile key
        if data['speaker']:
            speaker = ndb.Key(urlsafe=data['speaker']).get()
            # check that speaker exists in Profile
            if not speaker:
                raise endpoints.NotFoundException(
                    'No speaker found matching key: %s' %
                    data['speaker']
                )
            else:
                data['speaker'] = speaker.key

        # check that user is conference owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can create sessions for the conference.')

        # convert dates/times from strings to Date or Time objects
        if data['date']:
            data['date'] = datetime.strptime(
                data['date'][:10], "%Y-%m-%d").date()

        if data['startTime']:
            data['startTime'] = datetime.strptime(
                data['startTime'][:5], "%H:%M").time()

        # session date must be within conference date range
        # ignore if conference date is not yet set
        c_start = conf.startDate
        c_end = conf.endDate
        s_date = data['date']
        if (c_start and c_end):
            # validate that the Session date provided is actually within
            # the conference date range
            print c_start
            print c_end
            if (s_date < c_start or s_date > c_end):
                raise endpoints.BadRequestException(
                    "Session date out of range")

        # use default Session length if not provided
        if not request.duration:
            data['duration'] = DEFAULT_SESSION_LENGTH

        # create Session key based on the Conference parent
        c_key = conf.key
        s_id = Session.allocate_ids(size=1, parent=c_key)[0]
        s_key = ndb.Key(Session, s_id, parent=c_key)
        data['key'] = s_key

        Session(**data).put()
        # after saving the Session, check for featured speakers
        # and add notice to memcache using taskqueue
        taskqueue.add(params={
            'conf': request.websafeConferenceKey
        }, url='/tasks/set_featured_speakers')
        # return request
        return self._copySessionToForm(s_key.get())

    def _getSessionQuery(self, request):
        """Return formatted Session query from the submitted filters."""
        # create a Session query
        q = Session.query(
            ancestor=ndb.Key(urlsafe=request.websafeConferenceKey))
        # build the query filters from the submitted form
        filters = self._formatFilters(request.filters, kind='session')

        # rather than building an ordinary datastore query, we will
        # perform a 'keys_only' query and store the keys in a list
        # called qf; this will enable us to specify multiple
        # inequality filters
        # inspired by:
        #     http://stackoverflow.com/questions/33549573
        #     /combining-results-of-multiple-ndb-inequality-queries
        qf = []
        sets = None
        for filtr in filters:
            op = filtr["operator"]
            # take string field inputs and transform them into
            # native values (int or datetime)
            if (filtr["field"] == 'duration'):
                filtr["value"] = int(filtr["value"])
            elif (filtr["field"] == 'date'):
                filtr["value"] = datetime.strptime(filtr["value"], "%Y-%m-%d")
            elif (filtr["field"] == 'startTime'):
                dt = '1970-01-01 ' + filtr["value"]
                filtr["value"] = datetime.strptime(dt, "%Y-%m-%d %H:%M")
            elif (filtr["field"] == 'typeOfSession'):
                # for typeOfSession, only '==' and '!=' queries
                # are allowed
                s_type = filtr["value"]
                if not (op in ['=', '!=']):
                    raise endpoints.BadRequestException(
                        "You can only use EQ or NE queries on Session Type.")

                if (op == '='):
                    op = '=='

                # fetch keys for the query, looking for Sessions that
                # are equal to or not equal to a specified type
                # (e.g.: 'Keynote')
                # because typeOfSession is an Enum, we cannot use
                # FilterNode as below
                qs = eval(
                    'q.filter(Session.typeOfSession ' +
                    op + ' SessionType.lookup_by_name("' +
                    s_type + '")).fetch(keys_only=True)')
                # append the list of keys to the qf list
                qf.append(qs)

            if (filtr["field"] != 'typeOfSession'):
                # fetch keys for the query, looking for Sessions
                # based on provided search criteria
                formatted_query = ndb.query.FilterNode(
                    filtr["field"], op, filtr["value"])
                qs = q.filter(formatted_query).fetch(keys_only=True)
                # append the list of keys to the qf list
                qf.append(qs)

        # iterate through the complete list of entity keys from the
        # various query filters, building a set of keys that match
        # the search criteria; note this does mean that we're
        # exclusively ANDing the query filters...
        for idx, val in enumerate(qf):
            if (idx == 0):
                sets = set(val)
            else:
                sets = sets.intersection(val)

        if sets:
            # then use get_multi to retrieve all the appropriate Sessions
            q = ndb.get_multi(sets)

        return q

    @endpoints.method(
        SessionForm,
        SessionForm,
        path='createSession',
        http_method='POST',
        name='createSession'
    )
    def createSession(self, request):
        """Create new conference session."""
        return self._createSessionObject(request)

    @endpoints.method(
        SESSION_LIST,
        SessionForms,
        path='getConferenceSessions',
        http_method='GET',
        name='getConferenceSessions'
    )
    def getConferenceSessions(self, request):
        """Return sessions by conference."""
        # create ancestor query for all key matches for this conference
        sessions = Session.query(
            ancestor=ndb.Key(urlsafe=request.websafeConferenceKey))
        # return set of SessionForm objects per Session
        return SessionForms(
            items=[
                self._copySessionToForm(session) for session in sessions
            ]
        )

    @endpoints.method(
        SESSION_LIST_BY_SPEAKER,
        SessionForms,
        path='getSessionsBySpeaker',
        http_method='GET',
        name='getSessionsBySpeaker'
    )
    def getSessionsBySpeaker(self, request):
        """Return sessions by speaker."""
        # create query for all key matches for this speaker
        speaker = ndb.Key(urlsafe=request.speaker).get()
        sessions = Session.query(Session.speaker == speaker.key)
        # return set of SessionForm objects per Session
        return SessionForms(
            items=[
                self._copySessionToForm(session) for session in sessions
            ]
        )

    @endpoints.method(
        SESSION_LIST_BY_TYPE,
        SessionForms,
        path='getConferenceSessionsByType',
        http_method='GET',
        name='getConferenceSessionsByType'
    )
    def getConferenceSessionsByType(self, request):
        """Return sessions within a conference by type."""
        # create ancestor query for all key matches for this conference
        sessions = Session.query(
            ancestor=ndb.Key(urlsafe=request.websafeConferenceKey))

        # create filter for session type
        s_type = request.typeOfSession
        try:
            sessions = sessions.filter(
                Session.typeOfSession == SessionType.lookup_by_name(s_type))
        except:
            raise endpoints.NotFoundException(
                "No sessions found for type '%s'." % s_type)
        # return set of SessionForm objects per Session
        return SessionForms(
            items=[
                self._copySessionToForm(session) for session in sessions
            ]
        )

    @endpoints.method(
        SESSION_LIST_BY_USER_AS_SPEAKER,
        SessionForms,
        path='conference/{websafeConferenceKey}/sessions/speaking',
        http_method='GET',
        name='getSessionsSpeaking'
    )
    def getSessionsSpeaking(self, request):
        """Get list of sessions that user is the speaker for."""
        user = endpoints.get_current_user()
        if not user:
            # require authorization to create Sessions
            raise endpoints.UnauthorizedException('Authorization required')

        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id).get()

        sessions = Session.query(
            ancestor=ndb.Key(urlsafe=request.websafeConferenceKey))
        sessions = sessions.filter(Session.speaker == p_key.key)

        # return set of SessionForm objects per Session
        return SessionForms(
            items=[
                self._copySessionToForm(session) for session in sessions
            ]
        )

    @endpoints.method(
        SESSION_QUERY,
        SessionForms,
        path='conference/{websafeConferenceKey}/sessions/query',
        http_method='POST',
        name='querySessions'
    )
    def querySessions(self, request):
        """Query for sessions."""
        sessions = self._getSessionQuery(request)

        # return individual ConferenceForm object per Conference
        return SessionForms(
            items=[
                self._copySessionToForm(_session) for _session in sorted(
                    sessions, key=attrgetter('name'))
            ]
        )

    def _sessionWishlist(self, request, add=True):
        """add or remove session from user wishlist."""
        retval = None
        prof = self._getProfileFromUser()  # get user Profile

        # check if session exists given sessionKey
        # get session; check that it exists
        sk = request.sessionKey
        _session = ndb.Key(urlsafe=sk).get()
        if not _session:
            raise endpoints.NotFoundException(
                'No session found with key: %s' % sk)

        # add to wishlist
        if add:
            # check if Session is already on wishlist
            if sk in prof.sessionWishList:
                raise ConflictException(
                    "You have already added this session to your wishlist.")

            # append the Session to user's wishlist
            prof.sessionWishList.append(sk)
            retval = True

        # remove from wishlist
        else:
            # check if Session is already on wishlist
            if sk in prof.sessionWishList:

                # remove Session from wishlist
                prof.sessionWishList.remove(sk)
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        return BooleanMessage(data=retval)

    @endpoints.method(
        SESSION_WISHLIST,
        SessionForms,
        path='session/wishlist',
        http_method='GET',
        name='getSessionsInWishlist'
    )
    def getSessionsInWishlist(self, request):
        """Get list of sessions that user has put in his/her wishlist."""
        prof = self._getProfileFromUser()  # get user Profile
        session_keys = [
            ndb.Key(urlsafe=sk) for sk in prof.sessionWishList
        ]
        sessions = ndb.get_multi(session_keys)

        # return set of SessionForm objects
        return SessionForms(
            items=[
                self._copySessionToForm(_session) for _session in sessions
            ]
        )

    @endpoints.method(
        SESSION_WISHLIST_ADD,
        BooleanMessage,
        path='session/{sessionKey}/wishlist/add',
        http_method='POST',
        name='addSessionToWishlist'
    )
    def addSessionToWishlist(self, request):
        """Add session to user wishlist."""
        return self._sessionWishlist(request)

    @endpoints.method(
        SESSION_WISHLIST_ADD,
        BooleanMessage,
        path='session/{sessionKey}/wishlist/remove',
        http_method='DELETE',
        name='deleteSessionInWishlist'
    )
    def deleteSessionInWishlist(self, request):
        """Remove session from user wishlist."""
        return self._sessionWishlist(request, add=False)


# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(
                        TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
            elif field.name == "websafeKey":
                setattr(pf, field.name, prof.key.urlsafe())
        pf.check_initialized()
        return pf

    def _getProfileFromUser(self):
        """Return user Profile from datastore,
        creating new one if non-existent."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profile = Profile(
                key=p_key,
                displayName=user.nickname(),
                mainEmail=user.email(),
                teeShirtSize=str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()

        return profile      # return Profile

    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        # if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        # else:
                        #    setattr(prof, field, val)
                        prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)

    def _createProfileObject(self, request):
        """Create Profile object, returning ProfileForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            # require authorization to create Sessions
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # ensure required fields are filled out
        if not request.displayName:
            raise endpoints.BadRequestException("Display name required")
        if not request.mainEmail:
            raise endpoints.BadRequestException("Email required")

        # copy ProfileForm/ProtoRPC Message into dict
        data = {
            field.name: getattr(
                request, field.name) for field in request.all_fields()
        }
        del data['websafeKey']
        if not data['teeShirtSize']:
            data['teeShirtSize'] = str(TeeShirtSize.NOT_SPECIFIED)

        confs = Conference.query(Conference.organizerUserId == user_id)

        # check that user is a conference owner
        if (confs.count() == 0):
            raise endpoints.ForbiddenException(
                'Only a conference organizer can create user profiles.')

        # create Profile key
        p_id = Profile.allocate_ids(size=1)[0]
        p_key = ndb.Key(Profile, p_id)
        data['key'] = p_key

        Profile(**data).put()
        return request

    @endpoints.method(
        ProfileForm,
        ProfileForm,
        path='createProfile',
        http_method='POST',
        name='createProfile'
    )
    def createProfile(self, request):
        """Create new user Profile."""
        return self._createProfileObject(request)

    @endpoints.method(
        message_types.VoidMessage,
        ProfileForm,
        path='profile',
        http_method='GET',
        name='getProfile'
    )
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()

    @endpoints.method(
        ProfileMiniForm,
        ProfileForm,
        path='profile',
        http_method='POST',
        name='saveProfile'
    )
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)

    @endpoints.method(
        message_types.VoidMessage,
        ProfileForms,
        path='getProfiles',
        http_method='POST',
        name='getProfiles'
    )
    def getProfiles(self, request):
        """Return user profiles."""
        user = endpoints.get_current_user()
        if not user:
            # require authorization to list Profiles
            raise endpoints.UnauthorizedException('Authorization required')

        profiles = Profile.query()
        # return set of ProfileForm objects per Profile
        return ProfileForms(
            items=[
                self._copyProfileToForm(p) for p in profiles
            ]
        )


# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = ANNOUNCEMENT_TPL % (
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement

    @endpoints.method(
        message_types.VoidMessage,
        StringMessage,
        path='conference/announcement/get',
        http_method='GET',
        name='getAnnouncement'
    )
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        return StringMessage(
            data=memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY) or "")


# - - - Featured Speakers - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheFeaturedSpeaker(conf):
        """Create Featured Speaker notice & assign to memcache"""
        # retrieve this Conference's Sessions and sort by speaker
        fs = Session.query(ancestor=ndb.Key(
            urlsafe=conf)).order(Session.speaker).fetch()

        # iterate through the Session entities, saving the Session
        # name and speaker name to a Featured Speakers notice if
        # there are multiple Sessions for a particular speaker
        # format of final notice should be:
        #     Featured Speakers: John Doe ("Session Foo", "Session
        #     Bar"); Jane Doe ("Session Baz", "Session Bazola").
        loopcount = 0
        notice = ''
        tempSpk = ''
        spkCount = 0
        tempNotice = ''
        for s in fs:
            # ignore Sessions with no speaker
            if s.speaker:
                spk = s.speaker.get().displayName
                if (tempSpk == spk):
                    # more than one Session exists with this speaker
                    tempNotice += s.name + '", "'
                    spkCount += 1
                else:
                    if (spkCount > 0):
                        notice += tempNotice[:-3] + '); '
                    tempNotice = spk + ' ("' + s.name + '", "'
                    spkCount = 0
                tempSpk = spk
            loopcount += 1
            if (loopcount == len(fs)):
                notice += tempNotice[:-3] + '); '

        if (notice != ''):
            # If there are featured speakers,
            # format notice and set it in memcache
            feature = FEATURED_SPEAKER_TPL % (notice[:-2])
            memcache.set(MEMCACHE_FEATURED_SPEAKER_KEY, feature)
        else:
            # If there are no featured speakers,
            # delete the memcache feature notice entry
            feature = ""
            memcache.delete(MEMCACHE_FEATURED_SPEAKER_KEY)

        return feature

    @endpoints.method(
        message_types.VoidMessage,
        StringMessage,
        path='conference/featured-speaker/get',
        http_method='GET',
        name='getFeaturedSpeaker'
    )
    def getFeaturedSpeaker(self, request):
        """Return Featured Speaker notice from memcache."""
        return StringMessage(
            data=memcache.get(MEMCACHE_FEATURED_SPEAKER_KEY) or "")


# - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser()  # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)

    @endpoints.method(
        message_types.VoidMessage,
        ConferenceForms,
        path='conferences/attending',
        http_method='GET',
        name='getConferencesToAttend'
    )
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser()  # get user Profile
        conf_keys = [
            ndb.Key(urlsafe=wsck) for wsck in prof.conferenceKeysToAttend
        ]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [
            ndb.Key(Profile, conf.organizerUserId) for conf in conferences
        ]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[
                self._copyConferenceToForm(
                    conf, names[conf.organizerUserId]
                ) for conf in conferences
            ]
        )

    @endpoints.method(
        CONF_GET_REQUEST,
        BooleanMessage,
        path='conference/{websafeConferenceKey}',
        http_method='POST',
        name='registerForConference'
    )
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)

    @endpoints.method(
        CONF_GET_REQUEST,
        BooleanMessage,
        path='conference/{websafeConferenceKey}',
        http_method='DELETE',
        name='unregisterFromConference'
    )
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)

    @endpoints.method(
        message_types.VoidMessage,
        ConferenceForms,
        path='filterPlayground',
        http_method='GET',
        name='filterPlayground'
    )
    def filterPlayground(self, request):
        """Filter Playground"""
        q = Conference.query()
        # field = "city"
        # operator = "="
        # value = "London"
        # f = ndb.query.FilterNode(field, operator, value)
        # q = q.filter(f)
        q = q.filter(Conference.city == "London")
        q = q.filter(Conference.topics == "Medical Innovations")
        q = q.filter(Conference.month == 6)

        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") for conf in q]
        )

api = endpoints.api_server([ConferenceApi])  # register API
