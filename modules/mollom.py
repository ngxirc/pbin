from string import Template
import datetime
import calendar
from requests_oauthlib import OAuth1Session
from requests.exceptions import Timeout

class MollomAuthenticationError(Exception):
    """A problem occurred trying to authenticate with the Mollom services.
    This usually occurs because of an invalid public_key, private_key combination.
    You can obtain your keys from mollom.com.
    """
        
class MollomInvalidRequestError(Exception):
    """Raised upon a faulty request sent by the client (4xx response code)."""
    def __init__(self, message):
        self.message = message
    
class MollomUnexpectedResponseError(Exception):
    """Raised upon an unexpected response from the Mollom service (5xx response code)."""
    def __init__(self, message):
        self.message = message
        
class MollomConnectionError(Exception):
    """Raised when we are unable to connect to the Mollom services."""
        
class Mollom(object):
    """Primary interaction point with all of the Mollom services."""
    
    def __init__(self, public_key, private_key, rest_root="http://rest.mollom.com/v1", timeout=1.0, attempts=2):
        """Construct a Mollom object for making requests, taking in the public and private keys obtained from mollom.com.
        Keyword arguments:
        public_key -- Mollom public key.
        private_key -- Mollom private key.
        rest_root -- Root URL of the Mollom rest service.
        timeout -- Maximum amount of time (seconds) to wait for the Mollom service to respond.
        attempts -- Maximum number of times a request is attempted before completely failing out in the case the previous request failed.
            Sometimes the Mollom service can fail to respond due to high load. 
            A subsequent request should usually succeed because of the global load balancer.
        """
        self._public_key = public_key
        self._rest_root = rest_root
        
        self._timeout = timeout
        self._attempts = attempts
        
        self._client = OAuth1Session(client_key=public_key, client_secret=private_key)
        self._client.headers["Accept"] = "application/json"
        
    def verify_keys(self):
        """Verify that the public and private key combination is valid; raises MollomAuthenticationError otherwise"""
        verify_keys_endpoint = Template("${rest_root}/site/${public_key}")
        url = verify_keys_endpoint.substitute(rest_root=self._rest_root, public_key=self._public_key)
        
        data = { "clientName": "mollom_python", "clientVersion": "1.0" }

        self._client.headers["Content-Type"] = "application/x-www-form-urlencoded"

        response = self._client.post(url, data, timeout=self._timeout)
        if response.status_code != 200:
            raise MollomAuthenticationError

        return True
        
    def __post_request(self, url, data):
        self._client.headers["Content-Type"] = "application/x-www-form-urlencoded"

        for attempt in xrange(0, self._attempts):
            try:
                response = self._client.post(url, data, timeout=self._timeout)
                break
            except Timeout:
                if attempt + 1 == self._attempts:
                    # If this is the last attempt and we're still not successful, raise an exception
                    raise MollomConnectionError
        
        if response.status_code >= 200 and response.status_code < 300:
            return response.json()
        elif response.status_code >= 400 and response.status_code < 500:
            raise MollomInvalidRequestError(response.text)
        else:
            raise MollomUnexpectedResponseError(response.text)

    def __get_request(self, url):
        self._client.headers.pop("Content-Type", None)

        for attempt in xrange(0, self._attempts):
            try:
                response = self._client.get(url, timeout=self._timeout)
                break
            except Timeout:
                if attempt + 1 == self._attempts:
                    # If this is the last attempt and we're still not successful, raise an exception
                    raise MollomConnectionError

        if response.status_code >= 200 and response.status_code < 300:
            return response.json()
        elif response.status_code >= 400 and response.status_code < 500:
            raise MollomInvalidRequestError(response.text)
        else:
            raise MollomUnexpectedResponseError(response.text)

    def check_content(self, 
                      content_id=None,
                      post_title=None, 
                      post_body=None, 
                      author_name=None, 
                      author_url=None, 
                      author_mail=None, 
                      author_ip=None, 
                      author_id=None, 
                      author_open_id=None,
                      author_created=None,
                      allow_unsure=None,
                      strictness=None,
                      content_type=None,
                      honeypot=None
                      ):
        """Requests a ham/spam/unsure classification for content.
        
        If rechecking or updating previously checked content, the content_id must be passed in.
        An example of this usage:
            * checking the subsequent post after previewing the content
            * checking the subsequent post after solving a CAPTCHA
        
        Keyword arguments:
        content_id -- Unique identifier of the content to recheck/update.
        post_title -- The title of the content.
        post_body -- The body of the content.
        author_name -- The name of the content author.
        author_url -- The homepage/website URL of the content author.
        author_mail -- The e-mail address of the content author.
        author_ip -- The IP address of the content author.
        author_id -- The local user ID on the client site of the content author.
        author_open_id -- List of Open IDs of the content author.
        author_created -- When the author's account was created.
            Can be raw UNIX timestamp, or a Python date or datetime (in UTC).
        allow_unsure -- If false, Mollom will only return ham or spam. Defaults to true.
        strictness -- A string denoting the strictness of Mollom checks to perform. 
            Can be "strict", "normal" or "relaxed". Defaults to "normal".
        content_type -- Type of content submitted. A type of "user" indicates user registration content.
        honeypot -- The value of a client-side honeypot form element, if non-empty.
        
        Returns:
        content_id -- Unique identifier if the content checked.
        spam_classification -- "ham", "spam" or "unsure".
        """
        if content_id:
            recheck_content_endpoint = Template("${rest_root}/content/${content_id}")
            url = recheck_content_endpoint.substitute(rest_root=self._rest_root, content_id=content_id)
        else:
            check_content_endpoint = Template("${rest_root}/content")
            url = check_content_endpoint.substitute(rest_root=self._rest_root)
        
        data = {"checks": "spam"}
        if post_title:
            data["postTitle"] = post_title
        if post_body:
            data["postBody"] = post_body
        if author_name:
            data["authorName"] = author_name
        if author_url:
            data["authorUrl"] = author_url
        if author_mail:
            data["authorMail"] = author_mail
        if author_ip:
            data["authorIp"] = author_ip
        if author_id:
            data["authorId"] = author_id
        if author_open_id:
            data["authorOpenId"] = " ".join(author_open_id)
        if author_created:
            if isinstance(author_created, datetime.date):  # and datetime.datetime is a subclass of datetime.date
                data["authorCreated"] = calendar.timegm(author_created.timetuple())
            else:
                data["authorCreated"] = author_created
        if allow_unsure:
            data["unsure"] = 1 if allow_unsure else 0
        if strictness:
            data["strictness"] = strictness
        if content_type:
            data["contentType"] = content_type
        if honeypot:
            data["honeypot"] = honeypot
            
        return self.__post_request(url, data)
    
    def create_captcha(self, captcha_type="image", ssl=None, content_id=None):
        """Creates a CAPTCHA to be served to the end-user.
        
        Keyword arguments:
        captcha_type -- Type of CAPTCHA to create: "image" or "audio". Defaults to "image".
        ssl -- True for a CAPTCHA served over https. Defaults to False.
        content_id -- Unique identifier of the content to link the CAPTCHA to, in case the content was unsure.
        
        Returns:
        captcha_id -- Unique identifier of the CAPTCHA created.
        url -- Path to the CAPTCHA resource to be served to the end-user.
        """
        create_captcha_endpoint = Template("${rest_root}/captcha")
        url = create_captcha_endpoint.substitute(rest_root=self._rest_root)
        
        data = {"type": captcha_type}
        if ssl:
            data["ssl"] = 1 if ssl else 0
        if content_id:
            data["contentId"] = content_id
        
        response = self.__post_request(url, data)
        return response["captcha"]["id"], response["captcha"]["url"]
    
    def check_captcha(self,
                      captcha_id,
                      solution,
                      author_name=None, 
                      author_url=None, 
                      author_mail=None, 
                      author_ip=None, 
                      author_id=None, 
                      author_open_id=None,
                      honeypot=None
                      ):
        """Checks a CAPTCHA that was solved by the end-user.

        Keyword arguments:
        captcha_id -- Unique identifier of the CAPTCHA solved.
        solution -- Solution provided by the end-user for the CAPTCHA.
        author_name -- The name of the content author.
        author_url -- The homepage/website URL of the content author.
        author_mail -- The e-mail address of the content author.
        author_ip -- The IP address of the content author.
        author_id -- The local user ID on the client site of the content author.
        author_open_id -- List of Open IDs of the content author.
        honeypot -- The value of a client-side honeypot form element, if non-empty.
        
        Returns:
        solved -- Boolean whether or not the CAPTCHA was solved correctly. 
            If the CAPTCHA is associated with an unsure contents, it is recommended to recheck the content.
        """
        check_catpcha_endpoint = Template("${rest_root}/captcha/${captcha_id}")
        url = check_catpcha_endpoint.substitute(rest_root=self._rest_root, captcha_id=captcha_id)
        
        data = {"solution": solution}
        
        response = self.__post_request(url, data)
        # Mollom returns "1" for success and "0" for failure
        return response["captcha"]["solved"] == "1"
        
    def send_feedback(
        self,
        reason,
        type=None,
        author_ip=None,
        author_id=None,
        author_open_id=None,
        content_id=None,
        captcha_id=None,
        source=None
        ):
        """Sends feedback to Mollom in the case of false negative or false positives. 
        
        Keyword arguments:
        reason -- Feedback to give. Can be: "approve", "spam", "unwanted".
            "approve" -- Report a false positive (legitimate content that was incorrectly classified as spam).
            "spam" -- Report a false negative (spam that was incorrectly classified as ham).
            "unwanted" -- Report content that isn't spam, but still unwanted on the site (e.g. offensive, profane, etc)
        type -- A string denoting the type of feedback submitted: flag for end users flagging content to submit feedback; moderate for administrative moderation. Can be "flag" or "moderate". Defaults to "moderate".
        author_ip -- The IP address of the content author.
        author_id -- The local user ID on the client site of the content author.
        author_open_id -- Open IDs of the content author, separated by whitespace.
        content_id -- Existing content ID.
        captcha_id -- Existing CAPTCHA ID.
        source -- A single word string identifier for the user interface source. This is tracked along with the feedback to provide a more complete picture of how feedback is used and submitted on the site.
        """
        send_feedback_endpoint = Template("${rest_root}/feedback")
        url = send_feedback_endpoint.substitute(rest_root=self._rest_root)
        
        data = {"contentId": content_id, "reason": reason}

        if type:
            data["type"] = type
        if author_ip:
            data["authorIp"] = author_ip
        if author_id:
            data["authorId"] = author_id
        if author_open_id:
            data["authorOpenId"] = author_open_id
        if content_id:
            data["contentId"] = content_id
        if captcha_id:
            data["captchaId"] = captcha_id
        if source:
            data["source"] = source
        
        self.__post_request(url, data)
        
    def create_blacklist_entry(self, 
                               value, 
                               reason="unwanted", 
                               context="allFields", 
                               exact_match = False, 
                               enabled = True
                               ):
        """Creates a new blacklist entry.
        
        Keyword arguments:
        value -- The string value to blacklist.
        reason -- The reason for why the value is blacklisted. Can be: "spam", "unwanted".
        context -- The context where the entry's value may match. Can be:
            allFields -- Match can be made in any field.
            author -- Match can be made in any author related field.
            authorName -- Match can be made in the author name of the content.
            authorMail -- Match can be made in the author email of the content.
            authorIp -- Match can be made in the author ip address of the content.
            authorId -- Match can be made in the author id of the content.
            links -- Match can be made in any of the links of the content.
            postTitle -- Match can be made in the post title of the content.
            post -- Match can be made in the post title or the post body of the content.
        exact_match -- Whether there has to be an exact word match. Can be: "exact", "contains".
            e.g. for a value of "call", "caller" would be a contains match, but not an exact match.
        enabled -- Whether or not this blacklist entry is enabled.
        
        Returns:
        blacklist_entry_id -- The unique identifier of the blacklist entry created.
        """
        create_blacklist_endpoint = Template("${rest_root}/blacklist/${public_key}")
        url = create_blacklist_endpoint.substitute(rest_root=self._rest_root, public_key=self._public_key)
        
        data = {"value": value,
                "reason": reason,
                "context": context,
                "match": "exact" if exact_match else "contains",
                "status": 1 if enabled else 0
                }
        
        response = self.__post_request(url, data)
        return response["entry"]["id"]

    def delete_blacklist_entry(self, blacklist_entry_id):
        """Delete an existing blacklist entry.
        
        Keyword arguments:
        blacklist_entry_id -- The unique identifier of the blacklist entry to delete.
        """
        delete_blacklist_endpoint = Template("${rest_root}/blacklist/${public_key}/${blacklist_entry_id}/delete")
        url = delete_blacklist_endpoint.substitute(rest_root=self._rest_root, public_key=self._public_key, blacklist_entry_id=blacklist_entry_id)
        
        self.__post_request(url, {})

    def get_blacklist_entries(self):
        """Get a list of all blacklist entries.

        """
        get_blacklist_entries_endpoint = Template("${rest_root}/blacklist/${public_key}/")
        url = get_blacklist_entries_endpoint.substitute(rest_root=self._rest_root, public_key=self._public_key)

        response = self.__get_request(url)
        return response["list"]["entry"]

    def get_blacklist_entry(self, blacklist_entry_id):
        """Get a single blacklist entry

        Keyword arguments:
        blacklist_entry_id -- The unique identifier of the blacklist entry to get.
        """
        get_blacklist_entries_endpoint = Template("${rest_root}/blacklist/${public_key}/${blacklist_entry_id}")
        url = get_blacklist_entries_endpoint.substitute(rest_root=self._rest_root, public_key=self._public_key, blacklist_entry_id=blacklist_entry_id)

        response = self.__get_request(url)
        return response["entry"]
