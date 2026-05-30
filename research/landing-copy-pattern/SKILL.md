---
name: landing-copy-pattern
description: "Draft conversion-focused landing page copy for smoke-test MVPs."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Marketing, Copy, Landing, SmokeTest, Validation]
    related_skills: [market-research-pattern, idea-scoring-pattern]
---

# Landing Copy — Smoke-Test Pattern

Use after `idea-scoring-pattern` has picked a top idea. Produces ready-to-paste
HTML/Markdown for a 1-page validation landing that measures whether real users
will sign up / pre-order / waitlist before any code is written.

## Trigger Phrases

"draft landing copy", "smoke-test page", "waitlist page", "validate with a
landing", "write copy for the MVP page".

## Inputs

- `idea` — the product concept (auto-pull from `scored_ideas_*.md` top-1
  via `mcp_filesystem_read_file` if not given).
- `audience` — the persona suffering the pain.
- `primary_pain_quote` — verbatim user quote from `findings.jsonl` (high-trust
  social proof anchor).
- `cta` — one of: `Join waitlist`, `Get early access`, `Pre-order`, `Book a demo`.

## Structure (Hero → Pain → Promise → Proof → CTA)

### 1. Hero (above the fold)

- **Headline** — 5-9 words, names the *outcome* not the feature. Format:
  "[Verb] [Result] without [Pain]". Example: "Ship k8s fixes without 2 AM pages".
- **Sub-headline** — 1 sentence, names the audience + the new state of the world.
- **CTA button** — single CTA, contrasting color, action verb.
- Optional: 5-second product GIF/screenshot OR a 1-line code sample (devs).

### 2. Pain section

Direct quote from `primary_pain_quote`, attributed (e.g. "— r/devops user, March
2026"). Below: a 3-bullet list of *symptoms* the reader will recognize. Mirror
the language found in the source threads — do NOT paraphrase into corporate-speak.

### 3. Promise / How it works

Three steps, each one verb + one outcome:

```
1. <Connect / Install / Paste>
2. <It does the magic — 1 line, no jargon>
3. <You get the outcome — measurable>
```

### 4. Proof

- Logos of design partners, OR
- Beta-user testimonial quotes (if any), OR
- "Built by ex-<credible-place>" line, OR
- "Trusted by N developers on the waitlist" counter (set up via Tally/Typeform).

For pure smoke-test before product exists: replace with "What people on Reddit
say" wall — 3 quotes from `findings.jsonl` with permalinks.

### 5. CTA repeat + FAQ

3-5 FAQs that reduce objections. Common ones:
- "Is this open source?" / "What's the pricing?"
- "Who is this for / not for?"
- "When does it ship?"
- "Do you store my data?"

## Output

Write `/opt/data/workspace/landing_<idea-slug>_<date>.md` containing the full
markdown + a parallel `landing_<idea-slug>_<date>.html` ready for Vercel/Cloudflare
Pages. Suggested stack:

- **Hosting**: Cloudflare Pages or Vercel — free + fast.
- **Signup capture**: Tally or Formspark — embed an iframe, no backend.
- **Analytics**: Plausible or Umami — privacy-friendly conversion tracking.

## Success Metric Block (must include)

At the bottom of the artifact, define what counts as validation BEFORE launch:

```
- Target traffic: 200 unique visitors (paid ads or organic posts to source subs)
- Target signups: 20 emails (10% conversion)
- Target qualitative: 3 reply-back interviews booked from signups
- Decision rule: if <5% conversion → re-do idea-scoring with new pains;
                 if 5-15% → iterate copy and re-test;
                 if >15% → start building MVP.
```

## After the Test

Persist the experiment outcome to memory graph (`relation: validates`) so the
next round of idea-scoring can weight prior outcomes.
