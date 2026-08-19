---
name: routines
description: Create and manage cron-routines that message the agent or run a background subagent on a recurring schedule. Use when the user asks for recurring, scheduled, daily/weekly, or cron-based work.
---

# Routines

Create, inspect, and run recurring routines for this agent. These
are distinct from project tasks (the build plan): a routine holds a
cron schedule and an action; when it fires, the action runs separately
from the user's conversation queue.

## When to Use

- The user asks for something recurring: "every morning", "weekly", "on a
  schedule", "remind me", "check X daily".
- The user asks what routines exist, or wants one changed, run
  immediately, or removed.

## Where the User Sees Routines

The user manages their routines on the **Routines** page in the sidebar — that
page lists their routines in the current workspace, across conversations, not
just this one. It is scoped to the workspace the user is in, so routines in
their other workspaces (personal or team) show up on that workspace's own
Routines page. When the user asks where to find, view, or manage their
routines, point them there. You can still use `listRoutines` to read this
conversation's routines inline when that answers their question directly.

## When NOT to Use

- One-off future work with no recurrence — do it now or ask the user.
- Sub-hourly cadences: routine schedules must be at least 60 minutes
  apart; a faster schedule is rejected.

## Routine Actions

Every routine carries one action, a dict with a `kind` field:

- `{kind: "message", message}` — always use this action when creating or
  updating a routine. When the routine fires, this agent runs a normal turn on
  the message, with the conversation's memory as context.
- `{kind: "subagent", message}` — when the routine fires, a separate
  subagent is spawned in this conversation's environment and runs the
  message as its task at a cheap model tier; this agent runs no turn and
  the conversation history is not shared. Do not select this action when
  creating or updating a routine.

A subagent run is unattended: nobody is watching, so the run never asks
the user questions. If it genuinely needs a person it escalates — this
agent is woken with the run's message and decides what to do. Success is
silent: the run's report is recorded on the invocation (`summary`),
not announced.

## Routines That Need Connector Access

A fired run is unattended: it cannot complete OAuth, fix a missing
connection, or wait on an approval card. So when a routine's action will
call a connector (Gmail, Slack, Notion, etc.), sort out access **before**
the routine first fires:

- Make sure every connector the action needs is already connected and
  authorized. Check the connector's status and request any missing access
  through the usual integration flow (see the `integrations` skill) before
  or alongside proposing the routine.
- Connector calls that require approval interrupt the run, and a fired
  run cannot wait on an approval card. You cannot read a connector's
  permission mode, so when the action writes (sends email, posts
  messages), offer to perform one representative write now, while the
  user is present — the user scheduled the side effect for later, so
  never write during setup unless they agree, and preview the content in
  chat first as usual. Tell the user **before** issuing the call: the
  approval card (and this conversation's Integrations panel) offers the
  connector's permission modes — **Always allow** lets the routine run
  without interruption, **Decide for me** (the `auto` mode) still asks
  when a call looks risky, and **Always ask** raises a card on every
  call and blocks every unattended run. Say it up
  front because you may never see the card: an approved call just
  returns results — only a declined call or a `waiting_for_approval`
  outcome tells you one was raised. Leave the choice to them; the
  workspace limit may cap which modes are offered.

## Available Functions

All functions live on the standard callback interface. Routine objects returned
by `getRoutine` and `listRoutines` have this full shape; update/delete return
the same object without `lastInvocation`. `proposeRoutine` returns no routine —
only `{approvalRequest}` (see its section):

- `routineId` (str): stable id, minted when the routine is created
- `title` (str), `description` (str)
- `cron` (str): 5-field cron expression
- `timezone` (str): IANA timezone the cron is evaluated in
- `enabled` (bool): disabled routines are kept but never fire
- `action` (dict | None): the routine's action (see Routine Actions)
- `nextFireAt` (str | None): ISO timestamp of the next scheduled fire;
  the run may start a little before or after this moment
- `lastInvocation` (dict | None): latest run — `invocationId`,
  `triggerType` (`"cron"` | `"manual"`), `status` (`"queued"`,
  `"running"`, `"succeeded"`, `"failed"`, `"escalated"`,
  `"skipped_overlap"`, `"skipped_disabled"`, `"superseded"`),
  `queuedAt`, `startedAt` (str | None), `completedAt` (str | None),
  `errorSummary` (str | None), `summary` (str | None — a succeeded
  subagent run's report). Only `getRoutine` and
  `listRoutines` return it; update/delete responses carry the
  routine definition without run history.

### proposeRoutine(title, description, cron, timezone?, enabled, action, approvedSchedule, routineInvocationBudget?)

Proposes a routine for the user to approve. The call returns
`{approvalRequest}` immediately — the routine does **not** exist yet. The user
sees an approval card with the title, instructions, schedule, and budget. They
can edit these values before accepting. You are told the outcome as a follow-up
message. Do not call `proposeRoutine` again while approval is pending. If the
user accepts edits, follow the response instructions and call `proposeRoutine`
once with the revised values. Never re-propose a declined routine unless the
user asks.

If the user does not specify a timezone, omit `timezone` so the routine uses
the sender timezone from the current system reminder. If the user specifies a
timezone, pass its IANA name. Ask which timezone to use only when no sender
timezone is available.

The `description` is required but stays internal. Write one or two sentences on
what the routine is for. The action's `message` is the instruction that runs
when the routine fires. Make it complete and self-contained. Do not put schedule
or timing details in `message`; use `cron` and `timezone` for scheduling.

Set `approvedSchedule` to a natural-language description of `cron` and
`timezone`. After the user edits a proposal, copy the approved Schedule text
exactly. The approval token only authorizes that exact schedule text.

### updateRoutine(routineId, title, description, cron, timezone, enabled, action)

Replaces the full definition of an existing routine and returns `{routine}`.
Partial edits are not supported: fetch the routine first and send every field
back, changing only what the user asked for. Unknown `routineId` is an error —
an edit can never create a routine. Edits always win for fires that have not
started yet: a pending fire runs the updated definition, while a run already
in progress finishes on the definition it started with.

### listRoutines()

Returns `{routines}` — every routine with its latest invocation.

### getRoutine(routineId)

Returns `{routine}` for one routine. Unknown `routineId` is an error.

### deleteRoutine(routineId)

Returns `{deleted, routine}`. Deleting an unknown id returns
`{deleted: false, routine: None}` rather than an error. Deleting a routine also
cancels its pending fires and stops a subagent run still in flight.

### runRoutineNow(routineId)

Triggers the routine immediately without changing its cron schedule and returns
`{invocation}` with status `"queued"`. The action runs after the
current turn, so the result is not visible in this turn. If another run of
the routine is still in flight when it would start, it is skipped as
`"skipped_overlap"`. Manual runs work while a routine is disabled and do not
resume its schedule.

## Limits and Behavior

- At most **20 routines** per agent; delete one before adding more.
- The workspace also caps **active (enabled) routines across all of its
  chats** (the limit depends on the plan). Disabled routines don't count.
  When the workspace is at its cap, creating an enabled routine or
  enabling a disabled one is rejected even though this agent is under its
  own cap; the user must pause or delete a routine somewhere in the
  workspace first.
- Cron schedules must be **at least 60 minutes apart on the schedule**. This
  is checked when the routine is saved (over the next few fires, so "every
  minute during one hour" shapes are also rejected) and enforced again at run
  time between scheduled occurrences; manual runs don't count against it.
- Runs do not start at the exact scheduled moment: each fire may begin a
  little **before or after** its scheduled time, so two actual run starts can
  occasionally sit closer together than the scheduled 60-minute minimum.
  Never promise the user an exact start time, and don't treat a slightly
  early, late, or close-together run as an error.
- If a routine fires while its previous run is still going, the new fire is
  **skipped** (`skipped_overlap`) and the schedule advances normally.
- A schedule that was overdue while the agent was dormant fires **once**,
  never a catch-up burst.
- Routines survive checkpoint reverts and conversation resets; they are removed
  only by `deleteRoutine` or clearing the agent's context.

## Testing a Routine on Request

Never run a freshly created routine unprompted — `runRoutineNow` performs
the routine's real work, which the user scheduled for later. Only when the user
explicitly asks to test or trigger it:

1. Call `runRoutineNow(routineId)` and note the `invocationId`.
2. In a later turn (or when the user next asks), check
   `getRoutine(routineId).routine.lastInvocation` — a `"failed"` status with
   an `errorSummary` means the routine's message needs rewording.

## Writing Good Routine Messages

A fired message routine runs as its own turn on this agent, with the agent's
memory — including the recent conversation — available as context. It does not
interrupt other work and never sees messages still waiting in the queue.
A fired subagent routine sees **none** of the conversation. In both cases,
write the instruction as complete and self-contained — what to do, where to
put results, and how to tell the user (e.g. "summarize X and post the result
in the conversation") — because by the time it fires, the conversation may
have moved far past today's context.
