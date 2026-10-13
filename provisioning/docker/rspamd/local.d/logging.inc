# The log is a file on a volume (so it survives an update and the console can read it);
# the entrypoint forwards it to the container output so docker logs still shows it.
type = "file";
filename = "/var/log/ifinmail/rspamd.log";
level = "info";
systemd = false;
