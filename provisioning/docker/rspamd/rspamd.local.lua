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

-- ifinmail: per-mailbox sending counters for containment of a suspected compromised password.
-- For every message a logged-in user sends, count (over a fixed one-hour window that starts with
-- the first message) the messages, the distinct recipients and the distinct recipient domains.
-- The console's worker reads these keys every minute (backend/apps/mail/services/containment.py).
-- Recipients are stored as short hashes: only the counts matter, not who was written to.
-- Writes are fire-and-forget; a Redis outage costs a counter, never a message.
local lua_redis = require "lua_redis"
local hash = require "rspamd_cryptobox_hash"

local counter_redis = lua_redis.parse_redis_server('ifinmail_outbound')
if counter_redis then
  local WINDOW = '3600'
  local MAX_RECIPIENTS = 1000

  -- One atomic script: a counter and two sets that all expire together an hour after the first
  -- message. (Separate INCR and EXPIRE commands race and can leave a key that never expires.)
  local COUNT_SCRIPT = [[
local window = tonumber(ARGV[1])
local naddr = tonumber(ARGV[2])
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], window) end
for i = 1, naddr do redis.call('SADD', KEYS[2], ARGV[2 + i]) end
if naddr > 0 and redis.call('TTL', KEYS[2]) < 0 then redis.call('EXPIRE', KEYS[2], window) end
local ndom = #ARGV - 2 - naddr
for i = 1, ndom do redis.call('SADD', KEYS[3], ARGV[2 + naddr + i]) end
if ndom > 0 and redis.call('TTL', KEYS[3]) < 0 then redis.call('EXPIRE', KEYS[3], window) end
return n
]]

  local function digest(value)
    return hash.create(value:lower()):hex():sub(1, 16)
  end

  rspamd_config:register_symbol({
    name = 'IFINMAIL_OUTBOUND_COUNT',
    type = 'idempotent',
    score = 0.0,
    group = 'policies',
    description = 'Counts what a logged-in user sends, for containment',
    callback = function(task)
      local user = task:get_user()
      if not user or user == '' then
        return false
      end
      local base = 'ifinmail:out:' .. user:lower()

      local recipients = task:get_recipients('smtp') or {}
      local addresses, domains, seen = {}, {}, {}
      for i, rcpt in ipairs(recipients) do
        if i > MAX_RECIPIENTS then break end
        if rcpt.addr and rcpt.addr ~= '' then
          addresses[#addresses + 1] = digest(rcpt.addr)
          local domain = (rcpt.domain or ''):lower()
          if domain ~= '' and not seen[domain] then
            seen[domain] = true
            domains[#domains + 1] = digest(domain)
          end
        end
      end

      -- ARGV: window, number of addresses, the addresses, then the domains.
      local args = { COUNT_SCRIPT, '3', base .. ':m', base .. ':r', base .. ':d',
        WINDOW, tostring(#addresses) }
      for _, value in ipairs(addresses) do args[#args + 1] = value end
      for _, value in ipairs(domains) do args[#args + 1] = value end
      lua_redis.redis_make_request(task, counter_redis, base .. ':m', true,
        function() end, 'EVAL', args)
      return false
    end,
  })
end
