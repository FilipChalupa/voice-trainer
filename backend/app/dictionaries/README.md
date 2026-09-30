# Spelling dictionaries

Hunspell dictionaries used to drop corpus sentences that contain misspelled words (a typo in a prompt ends up
read aloud and stored as the transcript). Taken from https://github.com/LibreOffice/dictionaries:

- `cs_CZ.*` – Czech, GNU GPL (see README_cs.txt in the source repository)
- `en_US.*` – English (US), SCOWL, BSD-like/MIT licences (see README_en_US.txt in the source repository)

Only lowercase words are checked, so names and abbreviations do not disqualify a sentence.
