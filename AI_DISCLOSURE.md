# AI Disclosure

Device Sentinel was built with AI assistance. Because 'built with AI 
assistance' can mean anything from basic text autocomplete to complete 
vibe code that no human has ever reviewed, you deserve to know where 
this project stands.

## How Was Device Sentinel Created?

The design, the detection logic, and the formulas are mine. I built
them, tested them on my own hardware, and adjusted them when the data
demanded it. Every design choice is mine. Each one is written down as
a rule in the [rulebook](developer/Main__Rulebook.md), and most rules
name the tests that prove them.

I did not physically type this code. I dictated what it should do, and
I understand it well enough to explain why every block of code is 
there. The AI was often wrong, and I overruled it. Arguing a design
against a tool that pushes back is how many of those rules came to
exist.

## What The AI Did

It wrote the Python, the tests, and the inline comments from my
direction. It ran the test suite, the linter, and the security scanner
on every build. It simulated proposals against recorded data before
they were built. It reviewed its own output and found faults in it. It
drafted the wiki pages and release notes, which I checked and edited.
It also researched Home Assistant's own code for each integration Device
Sentinel reads, and I checked what it found against real systems.

## Verification Gate

Nothing here is autonomous. No agent has ever committed to this
repository, opened an issue, or published a release. Every upload is
mine. Every release goes through the exact same gate: a fresh clone,
the test suite run against the oldest and the newest Home Assistant it
supports and against real data from testers' houses, a lint check, a
security scan, and a byte comparison of the upload against the test
build. Detection features are proven on real hardware before they ship.

Before a release is marked Latest, it also faces rounds of deliberate
attack, written to break it rather than to confirm that it works:
device and integration names built to break pages and messages,
damaged and oversized saved files, restarts, reloads and clock jumps
at the worst moment, upgrades and downgrades between versions on a
real Home Assistant, and weeks of simulated house data. The rounds go
on until one finds nothing a real house would hit.

Every release is tested on real hardware, not only in simulation. It
runs on my own house first, then on testers' houses, which send their
data back after each update. Their files have found faults no
simulation caught, and many of the fixes in the release notes began
there.

## You Decide

Read the source. Most comments name the rule they follow, and the
rulebook explains why each rule exists. Read the release
notes. When something shipped broken, the notes say what failed and
why. Decide for yourself.

## Home Assistant

This project follows the
[Open Home Foundation AI Policy](https://developers.home-assistant.io/blog/2026/07/20/ai-policy/).
AI tools are welcome as an aid, the contributor remains responsible for
everything submitted, autonomous agents may not contribute, and every
change must be one the contributor understands and can explain. All
four rules hold here.
