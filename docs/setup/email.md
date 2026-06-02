# Email Setup

Email is used only for account recovery and OTP flows when those features are
enabled. A local-only single-user install can run without SMTP, but password
reset email will not work until one transport is configured.

## Supported Transports

| Transport | Configuration |
|---|---|
| SMTP | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` |
| Amazon SES | `AWS_SES_REGION` or `AWS_DEFAULT_REGION`, plus normal AWS credentials |

SMTP on port `587` uses STARTTLS before login. If your provider only supports
implicit TLS on `465`, add code and tests before relying on it; the current
mailer does not document that path as supported.

## Domain Hygiene

For production-like recovery email, configure SPF, DKIM, and DMARC on the
sending domain. Use a dedicated app password or SES IAM user, not your personal
mailbox password.

## Secret Handling

Do not commit SMTP or SES credentials. Put them in local environment variables
or the deployment secret store. Backups exclude plain-text secret seed files by
default; credential stores are included only with explicit backup opt-in.
