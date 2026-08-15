# AI Disclosure

Device Sentinel was built with AI assistance. Because 'built with AI 
assistance' can mean anything from basic text autocomplete to vibe 
code that no human has ever reviewed, you deserve to know where this 
project stands.

## How Was Device Sentinel Created?

The design, the detection logic, and the formulas are mine. I built
them, tested them on my own hardware, and adjusted them when the data
demanded it. Every design choice is mine. Each one is recorded with its
reasoning in a decision log that now passes 260 entries.

I did not physically type this code. I dictated what it should do, and
I understand every line well enough to explain why every block is
there. The AI was often wrong, and I overruled it. Arguing a design
against a tool that pushes back is exactly how that decision log came
to exist.

## What The AI Did

It wrote the Python, the tests, and the inline comments from my
direction. It ran the test suite, the linter, and the security scanner
on every build. It simulated proposals against my recorded data before
they were built. It reviewed its own output and found faults in it. It
drafted the wiki pages and release notes, which I checked and edited.

## Verification Gate

Nothing here is autonomous. No agent has ever committed to this
repository, opened an issue, or published a release. Every upload is
mine. Every release goes through the exact same gate: a fresh clone,
the test suite run twice, a lint check, a security scan, and a byte
comparison of the upload against the test build. Detection features
are proven on real hardware before they ship.

## You Decide

Read the source. Most comments explain why a rule exists, what fault
produced it, and what I tried and rejected first. Read the release
notes. When something shipped broken, the notes say what failed and
why. Decide for yourself.

## Home Assistant

This project follows the
[Open Home Foundation AI Policy](https://developers.home-assistant.io/blog/2026/07/20/ai-policy/).
AI tools are welcome as an aid, the contributor remains responsible for
everything submitted, autonomous agents may not contribute, and every
change must be one the contributor understands and can explain. All
four rules hold here.
