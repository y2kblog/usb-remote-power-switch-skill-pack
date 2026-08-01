# Protocol Contract and Verification Status

This document separates behavior enforced by this repository from facts that
must be verified against the exact hardware model.

## Verification status

This repository does not currently include a vendor manual, an exact model
identifier, or a verified official product URL. The settings and responses below
are therefore the repository contract used by the bundled CLI, not a claim that
every similarly named USB power switch uses the same protocol.

Before releasing this skill pack for a specific device, verify the following
against the vendor manual and real hardware:

- exact product name and model or revision
- vendor documentation URL
- USB VID/PID and whether the adapter is uniquely identifiable
- serial settings and command bytes
- exact status and control response formats
- minimum safe OFF duration and power-cycle interval

Record the verified model and source here. Do not replace missing evidence with
a placeholder URL.

## Enforced serial settings

- baud rate: `9600` by default
- data bits: `8`
- parity: none
- stop bits: `1`
- command terminator: none

The baud rate and timeout can be configured by CLI options. Numeric values must
be finite; timeout and power-cycle interval must be greater than zero.

## Wire commands

| Operation | Transmitted ASCII |
| --- | --- |
| ON | `1` |
| OFF | `0` |
| Status | `s` |

After surrounding whitespace is removed, a status response must be exactly `1`
for ON or exactly `0` for OFF. Prefix matches such as `1garbage`, `0 ACK`, or
`10` are rejected as protocol errors.

Control-command responses must be non-empty. The CLI does not treat that response
alone as proof of success; it sends a status query and verifies the expected
state.

## State-changing sequences

`on` and `off` use this sequence:

1. query current state
2. request confirmation unless `--yes` is present
3. send the state-changing command
4. query state again
5. fail if the verified state does not match the requested state

`power-cycle` uses this sequence while holding the per-user cycle lock:

1. query current state
2. request confirmation unless `--yes` is present
3. atomically inspect and reserve the rate-limit window
4. send OFF
5. query and require the OFF state
6. wait for the configured duration
7. send ON
8. query and require the ON state

After OFF has been attempted, an exception or user interrupt triggers one ON
recovery attempt followed by a status query. The original failure remains the
command result; the recovery action and last verified state are included in the
error payload and audit log.

## Device selection limitation

CH340/CH341 descriptions are only ranking hints and are not unique device
identifiers. The CLI never selects a port silently. Confirm the exact port before
using `--execute`, especially when multiple USB serial devices are connected.
