-- ifinmail: a logged-in user's From header must be the address they send from.
-- Postfix already checks the envelope sender against the login (smtpd_sender_login_maps), and
-- outgoing mail is DKIM-signed for the domain, so without this a user could put a colleague's
-- address in From and pass DMARC. Mail without a login (inbound, the console, Sieve) is not
-- affected.
rspamd_config:register_symbol({
  name = 'IFINMAIL_FROM_NOT_SENDER',
  score = 0.0,
  group = 'policies',
  description = 'Authenticated sender used a From header that is not their sending address',
  callback = function(task)
    if not task:get_user() then
      return false
    end
    local envelope = task:get_from('smtp')
    local header = task:get_from('mime')
    if not (envelope and envelope[1] and envelope[1].addr ~= '') then
      return false
    end
    local sender = envelope[1].addr:lower()
    local ok = header and #header == 1 and header[1].addr and header[1].addr:lower() == sender
    if ok then
      return false
    end
    task:set_pre_result('reject', 'The From address must be the address you are sending from',
      'ifinmail')
    return true
  end,
})
