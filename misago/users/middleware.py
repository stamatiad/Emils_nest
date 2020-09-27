from django.contrib.auth import logout
from django.utils.deprecation import MiddlewareMixin

from .bans import get_request_ip_ban, get_user_ban
from .models import AnonymousUser, Online
from .online import tracker

# My middleware:
import datetime
from django.utils import timezone
#from project.profile.models import UserProfile
import logging
import pytz
import time



class RealIPMiddleware(MiddlewareMixin):
    def process_request(self, request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            request.user_ip = x_forwarded_for.split(",")[0]
        else:
            request.user_ip = request.META.get("REMOTE_ADDR")


class UserMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if request.user.is_anonymous:
            request.user = AnonymousUser()
        elif not request.user.is_staff:
            if get_request_ip_ban(request) or get_user_ban(
                request.user, request.cache_versions
            ):
                logout(request)
                request.user = AnonymousUser()


class OnlineTrackerMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if request.user.is_authenticated:
            try:
                request._misago_online_tracker = request.user.online_tracker
            except Online.DoesNotExist:
                tracker.start_tracking(request, request.user)
        else:
            request._misago_online_tracker = None

    def process_response(self, request, response):
        if hasattr(request, "_misago_online_tracker"):
            online_tracker = request._misago_online_tracker

            if online_tracker:
                if request.user.is_anonymous:
                    tracker.stop_tracking(request, online_tracker)
                else:
                    tracker.update_tracker(request, online_tracker)

        return response

logger = logging.getLogger('django')

class ActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        # One-time configuration and initialization.

    def __call__(self, request):
        # Code to be executed for each request before
        # the view (and later middleware) are called.
        response = self.get_response(request)

        user = request.user
        logger.info(f"Recieved request from user {user}")
        try:
            # If user activity exists (not shiny new user!)
            if user.activity_array is not None:
                # If the last entry is a logout entry:
                if user.activity_array[-1][0] is None:
                    user.activity_array[-1] = [None, timezone.now()]
                else:
                    user.activity_array.append([None, timezone.now()])

            print("Updating user activity...")
            user.save()
        except AttributeError as e:
            pass

        # Code to be executed for each request/response after
        # the view is called.
        # TODO: use this code to handle/log errors, to ease debug on deployment.

        #print("\nInside Activity middleware\n")
        #if request.user.is_authenticated:
            #print(f"User {request.user.username} is authenticated!")
            #activity_array = request.user.activity_array
            #print(activity_array)

        return response

class TimeOutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        # One-time configuration and initialization.

    '''
    Automatically logs inactive users out.
    '''
    def __call__(self, request):
        response = self.get_response(request)
        try:
            if request.user.is_authenticated:
                if 'lastRequest' in request.session:            
                    #logger.info(f"Timezone.now(): {timezone.now()}, last beacon request: {request.session['lastRequest']}")
                    # Convert JSONed datetime to object:
                    lastrequest_obj = datetime.datetime.strptime(
                        request.session['lastRequest'], '%Y-%m-%d %H:%M:%S.%f'
                        )
                    timezone_UTC = pytz.timezone('UTC')
                    lastRequestLocalized = timezone_UTC.localize(lastrequest_obj)
                    elapsedTime = timezone.now() - lastRequestLocalized
                                
                    logger.info(f"Timezone.now(): {timezone.now()}, last beacon request: {request.session['lastRequest']}")
                    if elapsedTime.seconds > 90:
                        logger.info(f"Time from last beacon request is {elapsedTime.seconds}.Logging out user {request.user.username}.")
                        del request.session['lastRequest'] 
                        request.session['autoLogout'] = True
                        logout(request)

                request.session['lastRequest'] = str(timezone.now())[:-6]


            else:
                if 'lastRequest' in request.session:
                    del request.session['lastRequest']
        except AttributeError as e:
            logger.info(f"EXCEPTION in TimeOutMiddleware! {e}")

        return response

