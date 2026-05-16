# ifinmail global Sieve spam filter
# Runs before user scripts — files spam into Junk folder

require ["fileinto", "mailbox"];

if header :contains "X-Spam" "Yes" {
    fileinto "Junk";
    stop;
}
