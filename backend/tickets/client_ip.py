import ipaddress

from django.conf import settings


def client_ip(request):
    """Client address as seen by the API.

    Counts trusted proxies from the right of X-Forwarded-For, so a value forged by the
    browser (which sits on the left) is never used. Returns None when unusable.
    """
    remote = request.META.get("REMOTE_ADDR", "")
    chain = [remote]
    count = settings.TRUSTED_PROXY_COUNT
    if count:
        forwarded = [x.strip() for x in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")]
        chain = [x for x in forwarded if x] + [remote]
    candidate = chain[-(count + 1)] if len(chain) > count else remote
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None
