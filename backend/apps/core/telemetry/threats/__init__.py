"""Threat digest: scanner and attack signals reduced to the few facts a decision needs.

``digest.run()`` reads nginx's JSON access log and the audit trail, finds what carries a threat,
keeps a slim summary and the findings, discards the rest, and (when the assistant is connected)
asks the model to write the gist and the priorities from those aggregates.
"""
