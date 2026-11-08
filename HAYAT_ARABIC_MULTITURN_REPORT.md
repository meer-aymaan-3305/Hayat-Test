# HAYAT — Arabic Multi-Turn Reliability Report

Date: 2026-11-08 · Branch `launch-v1`

## Root cause
Arabic turns stalled because `_extract_facts` only had English (and a few
literal Arabic) patterns for category, specialty, wellness goals, timing
and service terms — so `case_facts` stayed empty, `current_pending_field`
returned `customer_category` forever, and the planner repeated clarify.

## Fix (chat_service.py `_extract_facts` only — schema/consent/policy untouched)
- Category: added `سفر طبي`, `السفر الطبي`, `عملية طبية` → medical;
  `تجربة/رحلة/برنامج عافية`, `برنامج/لياقة بدنية` → wellness.
- Wellness goals: added `لياقة`, `رشاقة`, `عافية`, `سبا`, `تأمل`.
- Specialties: added Arabic alternation (قسطرة/قلب/أسنان/عظام/جلدية/
  أورام/عيون/تجميل/خصوبة/أطفال/باطنية/علاج طبيعي).
- `service_terms`: Arabic→canonical map (قسطرة→cardiology, أسنان→dental…).
- Timing: added `خلال ثلاثة أشهر`-style phrases and `الشهر/الأسبوع المقبل`.

## Verified journey (AR, scripted path)
`أحتاج مساعدة في السفر الطبي` → collect_detail (medical)
`قسطرة قلب` → collect_detail (procedure_or_service=قسطرة, care=cardiology)
`الهند` → collect_detail (destination=الهند)
`خلال ثلاثة أشهر` → **offer_consultation**
`أريد التحدث مع منسق` → sign_in_required
Identical progression to the EN control. Cross-modal audit J11:
EN `['collect_detail'×3, 'offer_consultation']` = AR same.

## Tests
- 286/286 existing+regression tests pass.
- Cross-modal audit re-run: all first-turn journeys EN/AR identical;
  J11 multi-turn now identical.

## Remaining Arabic limitations
- Dialect variations (Gulf/Levantine/Egyptian slang) not covered —
  MSA patterns only.
- Arabic name extraction exists but untested for all name forms.
- Mixed AR/EN code-switching partially works (Latin terms still match).
- Arabic budget/insurance/value-priority fields not extracted.
- Numbers written as Arabic-Indic digits (٣) not parsed.
- Whisper AR transcription accuracy still unverified (no speech sample).
