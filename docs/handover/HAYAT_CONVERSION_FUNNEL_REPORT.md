# HAYAT — Consultation Conversion Funnel Report

Simulated scripted-path journey (guest → sign-in gate → consent → handoff).

## Funnel observed (T14–T16)

1. Intent discovery — "dental treatment abroad" → intake began. ✔
2. Preference collection — destination (Turkey), timing (2 months),
   budget (~10k USD), modality (video) each acknowledged; state advanced
   `collecting_details → offering_consultation → awaiting_consent`. ✔
3. Context retention — earlier answers not re-asked. ✔
4. Natural consultation offer — yes, at `offering_consultation`. ✔
5. Summary + explanation — CP-5 summary presented before consent ask. ✔
6. Explicit consent — T15 refusal → stopped, `crm_sent=false`, no
   transmission. ✔ T16 affirmative → `awaiting_consent` +
   `coordinator_handoff=true` (~13.6ms). ✔
7. Human handoff — `coordinator_handoff` object returned; appointment
   confirmation remains coordinator-only (HB-8). ✔
8. No false booking — no appointment auto-confirmed anywhere. ✔

## Blockers in the funnel
- **Guest ceiling:** guests reach `offering_consultation` then hit the
  sign-in gate; actual CRM submission requires a customer session.
- **OTP disabled:** customer creation needs Firebase OTP — unconfigured →
  503. End-to-end consult *submission* is untestable until Addendum 1.1
  approval + Firebase/SMS configured. This is by design, not a defect.
- CRM webhook unset → transmission would be log-only (mock) even if
  reached.

## Conversion quality notes
- The funnel pushes sign-in perhaps one turn earlier than necessary
  (T14 hit it after ~5 turns) — acceptable, but consider allowing the
  summary preview to guests before the gate.
- No pressure tactics observed; "free & non-binding" messaging present.

## Score: conversion mechanics 85/100 (blocked at customer boundary by
design); end-to-end submission UNTESTED pending approvals.
