# Shanghai Push Time Design

## Goal

Interpret the configured daily `push_time` in the `Asia/Shanghai` time zone,
regardless of the host operating system time zone. A configured value of
`09:00` must therefore mean 09:00 in Shanghai even when AstrBot runs on a UTC
server.

## Design

- Use Python's standard-library `zoneinfo.ZoneInfo` with the fixed identifier
  `Asia/Shanghai`.
- Calculate the current time and the next daily target as timezone-aware
  datetimes in that zone.
- Keep the existing behavior that schedules the following day when today's
  configured time has already passed.
- Keep the existing random delay of 0 to 60 seconds.
- Do not change the host operating system time zone or add another plugin
  configuration field.
- Change the Web UI description to `每日定时推送时间（上海时区）`.

## Testing

Add a regression test using a fixed UTC instant. At UTC 00:00, Shanghai time is
08:00, so a configured Shanghai push time of 09:00 must be one hour away before
the existing random delay. The test must fail against the current host-local
implementation and pass after the timezone-aware change.

Run the focused regression test, the complete available test suite, and Python
bytecode compilation before completion.
