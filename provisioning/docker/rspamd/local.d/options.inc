# Name lookups go to the stack's own resolver (the "resolver" service). Blocklists such as
# URIBL refuse the shared and public resolvers Docker would otherwise forward to ("DNS query
# blocked ... possibly due to high volume"), which silently disabled them. The embedded Docker
# resolver is only a fallback if the stack's resolver is down.
dns {
  nameserver = "master-slave:resolver:53,127.0.0.11:53";
  timeout = 2s;
  retransmits = 3;
}
