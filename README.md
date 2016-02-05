# Conference Central

This project sets up a conference scheduling site.


## Table of contents

* [Base setup](#base-setup)
* [App config](#app-config)
* [Running Conference Central](#running-conference-central)
* [Design choices](#design-choices)
* [Additional queries](#additional-queries)
* [Query problem](#query-problem)
* [Creator](#creator)
* [Copyright and license](#copyright-and-license)


## Base setup

For starters, you need [Python](https://www.python.org/downloads/). The program was written for Python 2.7, so that's what you should download and install. You may already have Python, especially if you're on a Mac or Linux machine. To check, open a Terminal window (on a Mac, use the Spotlight search and type in "Terminal"; on a PC go to Start > Run and type in "cmd") and type "python" at the prompt. You should get something that looks like this (run on my Mac):

```
Python 2.7.10 (v2.7.10:15c95b7d81dc, May 23 2015, 09:33:12)
[GCC 4.2.1 (Apple Inc. build 5666) (dot 3)] on darwin
Type "help", "copyright", "credits" or "license" for more information.
>>>
```

Note the version number (2.7.10 in this case). If it starts with "3.", you should download version 2.7. If you have questions about any of this, check Python's [excellent online documentation](https://www.python.org/doc/).

In order to work with Google AppEngine, you need to download the Google AppEngine SDK for Python application. Downloads are available for Windows, Mac and Linux; [complete instructions are here](https://cloud.google.com/appengine/downloads#Google_App_Engine_SDK_for_Python).

You'll also need to set up an application in the [Google Cloud Platform Console](https://console.cloud.google.com/). Once there, click Create Project and give the project a name. You can accept the randomly-generated project ID or provide your own; just be aware of some naming restrictions (Google will tell you if the project ID format is invalid). Once the project has been created, paste the project ID into the app.yaml file on the first line, which will read:

```
application: YOUR_PROJECT_ID
```

when you're done.

Finally, you'll need [git](http://git-scm.com/download) so that you can clone this project.


## App config

Aside from adding your Google Project ID to app.yaml mentioned above, the only other thing you need to add are client IDs for accessing the AppEngine API. You do this within the Google Cloud Platform Console by clicking "Enable APIs and get credentials like keys" from the project Dashboard. Then click the "Credentials" link on the left hand sidebar menu.

From the Credentials page you can set up the client IDs for whatever clients you wish to enable (e.g.: Web, Android, iOS, etc.). Click "OAuth 2.0 Client IDs" from the "New credentials" drop-down menu and fill out the form that you're redirected to.

Once you have the Client ID, you need to plug the value into the corresponding parameter in settings.py

That's it!


## Running Conference Central

Once you have everything configured, you can run the AppEngine Launcher program you downloaded along with the Python SDK. In the File menu, choose "Add Existing Application" and point the path to where you have cloned the app. After you do this, you can run the app locally by clicking the Run button, or deploy it to the Google cloud and run it there. In the first case, you can view the API explorer (note that this app does not have a UI) by default here:

```
localhost:8080/_ah/api/explorer
```

Note that when you launch this, you will get a warning message about an API being served over HTTP rather than HTTPS (since you don't have an SSL certificate on your local machine, most likely); you can tell the browser to ignore that.

If you deploy the app to the Google Cloud, you can find it here:

```
https://[YOUR WEB CLIENT ID].appspot.com/_ah/api/explorer
```


## Design choices

### Session object

Conference Sessions are entities in the datastore like Conferences and Profiles. As with the Conference entity, Session has an associated Form for messages either to API endpoints or client-side forms. It also has a single and multiple QueryForm to enable multiple querying options for the user.

Although the Session object is implemented much like the Conference object, one difference is the use of an EnumProperty for Session type. The Enum is reinforced with an EnumField in the Form, so that users are forced to enter a Session type that exists in the list. I chose to do this because it seemed like a bad idea to let users randonly choose Session types; if one user adds a "keynote" type and another adds a "Keynote" type, those would be seen as different within the datastore and would make querying problematic. In addition, the Enum provides administrators of the Conference Central application with a way to standardize the way conference sessions are created. This could help in future functionality, for example querying across conferences.

When creating Sessions, the 'speaker' field should contain the websafeKey for the Profile object of the speaker (see Speakers section below).


### Speakers

I chose to use the Profile entity for Session speakers rather than a simple StringProperty or another entity. I did this to keep things simple, and also it made sense not to create another entity that would essentially have the same fields as Profile (plus speakers probably want conference tee shirts as much as attendees do). Using a simple StringField didn't make sense to me because it could lead to query problems due to a misspelled name, as well as not providing a lot of functionality.

In addition, the current approach enables the user to query for sessions where s/he is the speaker (see additional queries section below) easily.

The connection between Session and Speaker uses a KeyProperty for speaker in the Session entity. This simplifies the job of connecting the two entities together (less code required when saving the Session), plus provides an easy way to query Sessions by speaker:

```
speaker = ndb.Key(urlsafe=request.speaker).get()
sessions = Session.query(Session.speaker == speaker.key)
```

No need for complicated matching logic.

When creating Sessions, you can make use of the getProfiles() endpoint to find the speaker you want to attach to the new Session. If the speaker doesn't yet have a Profile, you can create one using the createProfile() endpoint. These endpoints will give you the Profile entity key in the field called 'websafeKey'.


## Wish Lists

I chose to make Session wish lists for users a repeated StringProperty in the Profile entity, just like conferenceKeysToAttend. To add a Session to the wish list, you need the Session entity's websafeKey which you can get from a number of endpoints including querySessions(). Then you can use the addSessionToWishlist() endpoint and place the Session entity websafeKey in the sessionKey field.


## Additional query types

I created two additional queries for Conference Central. The first is a multi-criteria query (querySessions()) much like the queryConferences() function. Using this query a user can filter sessions within a conference by duration, start time, date, or type of session. The big difference between this and the queryConferences() function as originally written is that querySessions() allows for multiple inequality filters (see Query Problem section below).

The second new query provides the ability for a user to bring up a list of sessions for which s/he is the speaker (getSessionsSpeaking()). I thought this might be useful to remind a speaker where to go and when to be there at a conference. Although somewhat redundant to getSessionsBySpeaker(), this is much more convenient for users who are speakers.


## Query Problem

The query problem question posed by this project was:

> Let’s say that you don't like workshops and you don't like sessions after 7 pm. How would you handle a query for all non-workshop sessions before 7 pm? What is the problem for implementing this query?

One problem with constructing this query has to do with how Session entities are stored. The initial impulse would be to create one field for date and start time, but this makes searching strictly by time of day regardless of date, as the question states, extremely difficult. By splitting up the fields, you can query just by time of day much more easily.

The real issue however, is the fact that the problem posed requires multiple inequality filters (i.e.: session type not equal to workshop and start time less than 7pm). This is not currently allowed in AppEngine. In researching how to solve this problem, I came upon three possible solutions:

1. Refactor the entities to allow the query to be constructed with only one inequality filter;
1. Contruct the query so that only one inequality filter is used; or
1. Fetch the results of each inequality filter separately and combine them.

The first solution has the virtue of keeping to the implied intent of the AppEngine datastore platform: this limitation is in place in order to return results of a query very quickly. For this particular query, you could refactor the Session entity by having startTime be a list of ranges (8am-10am, 11am-1pm, etc.), and query based on whether startTime was equal to one or more of the ranges. However, this is extremely kludgy and we can't predict all of the queries a user might want to make of the data. We would potentially end up refactoring endlessly, or find ourselves with two or more competing refactorings. Surely flexibility for the user should win out if we can come up with an alternative.

The second option also keeps to the intent of AppEngine, and is possibly less kludgy than the first option. We could say:

```
st = datetime.strptime('1970-01-01 19:00')
sessions = Session.query(ndb.AND(Session.startTime < st, ndb.OR(Session.typeOfSession == 'keynote', Session.typeOfSession == 'lecture'...)))
```

or using "IN", if typeOfSession was a repeated property:

```
st = datetime.strptime('1970-01-01 19:00')
sessions = Session.query(Session.startTime < st).filter(Session.typeOfSession IN ['lecture', 'keynote'...])
```

But this is still very convoluted, and we still don't know everything a user might ask of the data so we'd be constantly rewriting our query logic.

Therefore, I chose to implement the third option. Basically this approach creates Python sets containing the keys for entities that match the various filters, and performs a get_multi for all the keys in the set. The downside of this approach is that there are multiple hits to the datastore; the primary benefit is simplified code and less likelihood of having to constantly refactor when new user queries are identified.

Here's how this works. We start by setting up a Query object of Session entities for a particular Conference:

```
q = Session.query(ancestor=ndb.Key(urlsafe=request.websafeConferenceKey))
```

Then, we create a list to hold the groups of Session entities that will match a particular filter:

```
qf = []
```

Then we use a 'keys_only' query for each filter:

```
st = datetime.strptime('1970-01-01 19:00')
qs = q.filter(Session.startTime < st).fetch(keys_only=True)
qf.append(qs)

qs = q.filter(Session.typeOfSession != 'Workshop').fetch(keys_only=True)
qf.append(qs)
```

Note that in this simplified example typeOfSession is a StringProperty, whereas in my version it is an EnumProperty. The principle is the same.

After dealing with all the filters, we then create a Python set containing the combined filters:

```
for idx, val in enumerate(qf):
    if idx == 0:
        sets = set(val)
    else:
        sets = sets.intersection(val)
```

Finally, we get all the entities in the combined set:

```
q = ndb.get_multi(sets)
return q
```

If our Conference Central application grows to thousands of Conferences, each with dozens or hundreds of Sessions, it's possible that this approach would not provide acceptable performance given the multiple hits to the datastore per query. In that case, I would explore the use of MapReduce (which apparently has the ability to do the same keys_only query on very large data sets rapidly); I cannot vouch for whether that's a viable strategy, but it would be worth pursuing.

For our small app, my approach seems to work pretty well. I should add that it was inspired by [this Stack Overflow post](http://stackoverflow.com/questions/33549573/combining-results-of-multiple-ndb-inequality-queries), though I had to make some modifications based on the way I designed the data model.