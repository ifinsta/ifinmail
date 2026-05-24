"""Mail views for ifinmail."""
from django.shortcuts import render


def inbox(request):
    """Render the mail inbox page."""
    messages = []  # TODO: fetch messages from Maildir via dovecot
    return render(request, "mail/inbox.html", {
        "messages": messages,
    })
