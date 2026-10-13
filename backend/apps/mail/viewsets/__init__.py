"""mail — viewsets: API operation handlers (API flow).

Layer: api.py → viewsets/ → serializers/ → services/ → models/.
Client autoconfig (Mozilla/Outlook/MTA-STS) stays on the web flow
(web.py → views/ → services/); these operations are the mount-ready
mailbox/alias/outbound layer.
"""

from backend.apps.mail.viewsets.aliases import create_alias, delete_alias, list_aliases
from backend.apps.mail.viewsets.mailboxes import (
    create_mailbox,
    delete_mailbox,
    ensure_plain,
    get_mailbox,
    list_mailboxes,
    set_active,
    set_admin,
    set_password,
    set_quota,
)
from backend.apps.mail.viewsets.outbound import (
    get_outbound_state,
    render_outbound,
    set_max_hops,
    set_smart_host,
    set_smtp_proxy,
)

__all__ = [
    'create_alias',
    'create_mailbox',
    'delete_alias',
    'delete_mailbox',
    'ensure_plain',
    'get_mailbox',
    'get_outbound_state',
    'list_aliases',
    'list_mailboxes',
    'render_outbound',
    'set_active',
    'set_admin',
    'set_max_hops',
    'set_password',
    'set_quota',
    'set_smart_host',
    'set_smtp_proxy',
]
