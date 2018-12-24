"""
   This code is by Alison Gray and Kay Waller, for
   HCDE 310 Aut 2018 Final Project. It is called
   the Top Spotify Songs around the world, and produces
   an interactive map displaying songs around the
   world. This code borrows heavily from Sean Munson's
   main.py.

"""
import os, sys
from imp import reload
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
from secrets import CLIENT_ID, CLIENT_SECRET
GRANT_TYPE = 'authorization_code'
import webapp2
import urllib2, os, urllib, json, jinja2, logging, sys, time
import urllib2, json
from bs4 import BeautifulSoup
from urllib import urlencode
import base64, Cookie, hashlib, hmac, email
from google.appengine.ext import db
from google.appengine.api import urlfetch

JINJA_ENVIRONMENT = jinja2.Environment(loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'],
    autoescape=True)

## T is the user database model, used to store the access token
class User(db.Model):
    uid = db.StringProperty(required=True)
    displayname = db.StringProperty(required=False)
    img = db.StringProperty(required=False)   
    access_token = db.StringProperty(required=True)
    refresh_token = db.StringProperty(required=False)
    profile_url=db.StringProperty(required=False)
    api_url=db.StringProperty(required=False) 


## The next 3 methods are cookies functions. It ensures that
## a malicious user can't spoof your user ID in their cookie
## and then use the site to do things on my behalf.
def set_cookie(response, name, value, domain=None, path="/", expires=None):
    """Generates and signs a cookie for the give name/value"""
    timestamp = str(int(time.time()))
    value = base64.b64encode(value)
    signature = cookie_signature(value, timestamp)
    cookie = Cookie.BaseCookie()
    cookie[name] = "|".join([value, timestamp, signature])
    cookie[name]["path"] = path
    if domain: cookie[name]["domain"] = domain
    if expires:
        cookie[name]["expires"] = email.utils.formatdate(
            expires, localtime=False, usegmt=True)
    response.headers.add("Set-Cookie", cookie.output()[12:])


def parse_cookie(value):
    """Parses and verifies a cookie value from set_cookie"""
    if not value: return None
    parts = value.split("|")
    if len(parts) != 3: return None
    if cookie_signature(parts[0], parts[1]) != parts[2]:
        logging.warning("Invalid cookie signature %r", value)
        return None
    timestamp = int(parts[1])
    if timestamp < time.time() - 30 * 86400:
        logging.warning("Expired cookie %r", value)
        return None
    try:
        return base64.b64decode(parts[0]).strip()
    except:
        return None

def cookie_signature(*parts):
    """
    Generates a cookie signature.

    We use the Spotify app secret since it is different for every app (so
    people using this example don't accidentally all use the same secret).
    """
    chash = hmac.new(CLIENT_SECRET, digestmod=hashlib.sha1)
    for part in parts: chash.update(part)
    return chash.hexdigest()
    
    
### This adds a header with the user's access_token to Spotify requests
def spotifyurlfetch(url,access_token,params=None):
    headers = {'Authorization': 'Bearer '+access_token}
    response = urlfetch.fetch(url,method=urlfetch.GET, payload=params, headers=headers)
    return response.content


## This is our API key for opencagegeocode, our lat/long API
#key = "1e80fc864c2146aaa1c3345baec77d5d" this is kaywaller19@gmail.com's key
key = "4514cd5502324fba81987ce680beb056"

## This method constructs the call to theopencagegeocode API to get the lat/long data for each city
def openCageREST(city, params = {}, format = "json", countrycode = "aaa", no_annotations = 1): #three letter country codes are ignored, no annotations speeds up requests, 0 for annotations
    params["key"] = key
    params["q"] = city
    params["countrycode"] = countrycode
    params["no_annotations"] = no_annotations

    baseUrl = "https://api.opencagedata.com/geocode/v1/json?"
    url = baseUrl + urllib.urlencode(params)

    if safeGet(url) is not None:
        results = safeGet(url).read()
        jsonFile = json.loads(results)
        return jsonFile

## Finds the lat and long out of the dictionary that openCageREST returns
def getGeoCoords(dict):
    res = dict.get("results")[0].get("geometry")
    lat = res.get("lat")
    lng = res.get("lng")
    return [lat, lng]

## Adds the lat/long to the city dictionary. This is first method that
## is called in main. This, then openCageREST, then getGeoCoords.
def createCoordDict(finalDict):
    for c in finalDict.keys():
        if c is not None:
            country = finalDict[c]["countrycode"]
            results = openCageREST(c, countrycode=(country.lower()))
            finalDict[c]["lat"] = getGeoCoords(results)[0]
            finalDict[c]["long"] = getGeoCoords(results)[1]
        else:
            del finalDict[c]
    return finalDict

## This ensures that we are opening the url safety, throwing error codes
## so as to not crash our program.
def safeGet(url):
    try:
        request = urllib2.urlopen(url)
        return request
    except urllib2.HTTPError as e:
        print("Error trying to retrieve data. " + "Error code: ", e.code)
        return None
    except urllib2.URLError as e:
        if hasattr(e, "code"):
            print("The server couldn't complete the request" + ". " + "Error code: ", e.code)
        elif hasattr(e, "reason"):
            print("We failed to reach the server" + ". " + "Reason ", e.reason)
        return None

## This method is used to turn a data string into something readable
def turnIntoSoup(text):
    soup = BeautifulSoup(text, "html.parser")
    return soup

## This method constructs a call to the Spotify API, once the OAuth
## process is complete. It returns a dictionary of data.
def spotifyAPI2(accessToken, playlistID):
    apiParams = {
        'access_token': accessToken
    }
    playlistAPI = 'https://api.spotify.com/v1/playlists/' + playlistID + '/tracks'
    url = "?".join([playlistAPI, urlencode(apiParams)])
    request = safeGet(url)
    if request is not None:
        dataDict = json.loads(request.read())
        return dataDict
    else:
        return None

## This method is where the main processing is done for getting the songs.
## It first beings by webscaping off of a url a city and a playlistID for
## that city. We then pass that playlistID to the Spotify API, which returns
## a list of songs and artists. We put that in our FinalDict, which has
## everything we pass to the Jinja template to be rendered.
def getCitiesAndSongs(accessToken, mostPopulated, finalDict):
     import sys
     reload(sys)
     sys.setdefaultencoding('utf8')
     url = "http://everynoise.com/everyplace.cgi?vector=city&scope=all"
     request = safeGet(url)
     text = request.read()
     soup = turnIntoSoup(text)
     cities = {}
     mostPopulated = mostPopulated
     ## The webscraping part
     for tr in soup.findAll("tr"):
         tds = tr.findChildren('td')
         if len(tds) >= 3:
             for a in tds[1].findChildren('a'):
                 playlistNumber = a.attrs['href'][41:]
             for a in tds[2].findChildren("a"):
                 city = a.contents[0].string
         if city in mostPopulated:
             cities[city] = cities.get(city, playlistNumber)
     cityKey = finalDict.keys()
     ## The Spotify API part
     for city in cityKey:
         playlistNumber = cities[city]
         songDict = spotifyAPI2(accessToken, playlistNumber)
         x = 1
         if songDict is not None:
            for i in range(len(songDict["items"])):
                if x < 9:
                    name = songDict["items"][i]["track"]["name"]
                    artist = songDict["items"][i]["track"]["artists"][0]["name"]
                    dictionary = {name:artist}
                    finalDict[city]["songs"].append(dictionary)
                    x = x + 1
     return finalDict

## This handler is the Base Handler -- it checks for the current user.
## Creating this class allows our other classes to inherit from it
## so they all "know about" the user.
class BaseHandler(webapp2.RequestHandler):
    # @property followed by def current_user makes so that if x is an instance
    # of BaseHandler, x.current_user can be referred to, which has the effect of
    # invoking x.current_user()
    @property
    def current_user(self):
        """Returns the logged in Spotify user, or None if unconnected."""
        if not hasattr(self, "_current_user"):
            self._current_user = None
            # find the user_id in a cookie
            user_id = parse_cookie(self.request.cookies.get("spotify_user"))
            if user_id:
                self._current_user = User.get_by_key_name(user_id)
        return self._current_user

## This will handle our home page, which is also our "main". This is
## where the bulk of our code is, calling all of the other methods
## defined above.
class HomeHandler(BaseHandler):
    def get(self):
        # checks if they are logged in
        user = self.current_user
        dict = {}
        if user != None:
            mostPopulated = []
            finalDict = {}
            ## These are the cities we wanted to put on the globe. Because
            ## Google App Engine only waits 60 seconds to load it before
            ## timing out, we had to cut the number of cities we were collecting
            ## data for by two thirds.
            populated = [('Tokyo', 'JP'),
                      ('New Delhi', 'IN'),
                      ('Mexico City', 'MX'),
                      ('Beijing', 'CN'),
                      ('Cairo', 'EG'),
                      ('Brooklyn New York', 'US'),
                      ('Buenos Aires', 'AR'),
                      ('Istanbul', 'TR'),
                      ('Lagos', 'NG'),
                      ('Manila', 'PH'),
                      ('Rio de Janeiro', 'BR'),
                      ('Los Angeles California', 'US'),
                      ('Paris', 'FR'),
                      ('Lima', 'PE'),
                      ('Seoul', 'KR'),
                      ('Johannesburg', 'ZA'),
                      ('Bangkok', 'TH'),
                      ('Santiago', 'CL'),
                      ('Riyadh', 'SA'),
                      ('Madrid', 'ES'),
                      ('Houston Texas', 'US'),
                      ('Singapore', 'SG'),
                      ('Nairobi', 'KE'),
                      ('Hanoi', 'VN'),
                      ('Salvador', 'SV'),
                      ('Berlin', 'DE'),
                      ('Seattle Washington', 'US'),
                      ('Melbourne Victoria', 'AU')]
            ## The Lat/Long, songs part
            for i in range(len(populated)):
                mostPopulated.append(populated[i][0])
                city = populated[i][0]
                country = populated[i][1]
                name = str(city + ", " + country)
                finalDict[city] = finalDict.get(city, {"name": name,
                                                       "countrycode": str(country), "lat": 0, "long": 0,
                                                       "songs": []}) ## Initialize the final dictionary
            finalDict = createCoordDict(finalDict) ## Add lat and long to dict
            finalDict = getCitiesAndSongs(user.access_token,mostPopulated, finalDict) ## Add songs to dict
            ## The data rendering part
            import sys ## encoding=utf8
            reload(sys)
            sys.setdefaultencoding('utf8')
            ## Creates the style that each city name, song and artist will display as
            for c in finalDict:
                base = "\"<b><span style='font-size:14px;color: #000000;text-decoration: underline;'>"
                nameStripped = finalDict.get(c).get("name").replace("\"", "")
                base += nameStripped
                base += "</b>"
                for s in finalDict.get(c).get("songs"):
                    for title in s:
                        base += "<br><span style='font-size:11px;color: #000000;'>"
                        base += title.replace("\"", "") + ", "
                        base += "<span style='font-size:11px;color:#999'>"
                        songStripped = s.get(title)
                        base += songStripped.replace("\"", "")
                base += "</span>\""
                varname = c.replace(" ", "")
                dict[varname] = {"lat": finalDict.get(c).get("lat"), "long": finalDict.get(c).get("long"), "str": base}
            template = JINJA_ENVIRONMENT.get_template("globetemplate.html") ## Uses globe template to render the WebGLEarth
        ## Calling Jinja to write the output on top of the globe rendering
        self.response.write(template.render(dict=dict))


## This handler handles the authorization requests
class LoginHandler(BaseHandler):
    def get(self):
        # After login; redirected here
        # Checks that we got a successful login back
        args = {}
        args['client_id']= CLIENT_ID
        
        verification_code = self.request.get("code")
        if verification_code:
            ## If so, we will use code to get the access_token from Spotify
            ## This corresponds to STEP 4 in https://developer.spotify.com/web-api/authorization-guide/
            args["client_secret"] = CLIENT_SECRET
            args["grant_type"] = GRANT_TYPE
            args["code"] = verification_code                ## The code we got back from Spotify
            args['redirect_uri']=self.request.path_url      ## The current page
            ## We need to make a post request, according to the documentation
            url = "https://accounts.spotify.com/api/token"
            response = urlfetch.fetch(url, method=urlfetch.POST, payload=urllib.urlencode(args))
            response_dict = json.loads(response.content)
            logging.info(response_dict["access_token"])
            access_token = response_dict["access_token"]
            refresh_token = response_dict["refresh_token"]
            ## Download the user profile. Save profile and access_token
            ## in Datastore; we'll need the access_token later
            ## The user profile is at https://api.spotify.com/v1/me
            profile = json.loads(spotifyurlfetch('https://api.spotify.com/v1/me',access_token))
            logging.info(profile)
            user = User(key_name=str(profile["id"]), uid=str(profile["id"]),
                        displayname=str(profile["display_name"]), access_token=access_token,
                        profile_url=profile["external_urls"]["spotify"], api_url=profile["href"], refresh_token=refresh_token)
            ## If profile.get('images') is not None:
            ##     user.img = profile["images"][0]["url"]
            user.put()
            ## Set a cookie so we can find the user later
            set_cookie(self.response, "spotify_user", str(user.uid), expires=time.time() + 30 * 86400)
            ## Send them back to the App's home page
            self.redirect("/")
        else:
            ## Not logged in yet-- send the user to Spotify to do that
            ## This corresponds to STEP 1 in https://developer.spotify.com/web-api/authorization-guide/
            args['redirect_uri']=self.request.path_url
            args['response_type']="code"
            ## Ask for the necessary permissions - see details at https://developer.spotify.com/web-api/using-scopes/
            args['scope']="user-library-modify playlist-modify-private playlist-modify-public playlist-read-collaborative"
            url = "https://accounts.spotify.com/authorize?" + urllib.urlencode(args)
            logging.info(url)
            self.redirect(url)


## This handler logs the user out by making the cookie expire
class LogoutHandler(BaseHandler):
    def get(self):
        set_cookie(self.response, "spotify_user", "", expires=time.time() - 86400)
        self.redirect("/")

## This is what sets up our google app engine environment, and allows it to run
## both locally and through gcloud app deploy.
application = webapp2.WSGIApplication([\
    ("/", HomeHandler),
    ("/auth/login", LoginHandler),
    ("/auth/logout", LogoutHandler)
], debug=True)