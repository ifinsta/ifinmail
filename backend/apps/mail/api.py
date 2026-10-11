"""mail — api.py: re-export layer for urls.py → api.py → viewsets/ contract."""

from .viewsets import (
    create_alias,
    create_mailbox,
    delete_alias,
    delete_mailbox,
    get_outbound_state,
    list_aliases,
    list_mailboxes,
    render_outbound,
    set_active,
    set_admin,
    set_max_hops,
    set_password,
    set_quota,
    set_smart_host,
    set_smtp_proxy,
)

__all__ = [
    'create_alias',
    'create_mailbox',
    'delete_alias',
    'delete_mailbox',
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
