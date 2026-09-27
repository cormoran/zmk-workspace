---
name: create-pull-request
description: Create or update a pull request with a concise, readable title and body containing Summary, Implementation Details, and Verification sections. Use when asked to prepare, open, or revise a PR.
---

# Create a Pull Request

Help a human reviewer understand the change at a glance. Prefer short,
concrete sentences and only the details needed to assess the PR.

## Prepare and publish

- Read the repository's instructions and PR template. Inspect the full diff
  and commits against the intended base branch, plus actual verification
  results. Describe the final change, including all commits in the PR.
- Choose a short title describing the problem solved or resulting behavior.
  Write in the language requested by the user or established by the repository.
- Use the three body sections below. Preserve required template fields when
  a repository template supplies additional requirements.
- Create or update the PR when requested; preparing a body alone does not
  authorize publishing. Respect the requested base, branch, and draft status.
  Check for an existing PR for the branch before creating another one.
- With `gh`, write the exact body to a temporary Markdown file and pass it
  through `--body-file` so newlines and literal characters are preserved.
  Follow the repository's rules for temporary file placement.
- After publishing, check the title, body, and base branch, then return the PR URL.

## Body structure

### Summary

Explain the problem and resulting behavior in one to three short sentences
or bullets. A reviewer should understand what changes and why by reading
only this section. Avoid implementation mechanics here unless they are
essential to understanding the outcome.

### Implementation Details

Add slightly more detail about how the change works. Include only meaningful
design choices, affected components, and any tradeoffs or limitations a
reviewer needs to assess. Scale this section to the change; a small PR may
need just one sentence. Do not repeat the Summary or list every changed file.

### Verification

State how the change was checked and what the checks established. Include
relevant commands, manual scenarios, or hardware/build targets and their
results. Distinguish completed checks from checks not run or blocked, with
brief reasons. Never imply that an unperformed check passed.

## Editing for readability

- Lead with the concrete outcome. Use familiar words and active verbs.
- Keep each sentence focused on one point. Use short paragraphs or bullets
  for independent points; avoid nested lists.
- Remove filler, repeated explanations, work chronology, and abandoned
  approaches unless they explain a necessary tradeoff.
- Keep technical detail only when it helps the reviewer understand behavior,
  evaluate the design, or interpret verification. Prefer a concrete example
  over an abstract explanation when it is shorter and clearer.
- Before submitting, read the body as someone without the conversation
  context. Remove anything that does not help them understand or review it.

## Example body

```markdown
## Summary

Reconnect the keyboard after a browser reload so users can resume editing
without selecting the device again.

## Implementation Details

Reuse the previously granted serial port on startup. If it is unavailable,
show the existing device picker.

## Verification

- `npm run build` — passed.
- Reloaded with a connected keyboard; editing resumed after reconnection.
- Disconnected the keyboard before reload; the device picker appeared.
```

The example illustrates the writing style; replace its claims with evidence
from the actual change.
