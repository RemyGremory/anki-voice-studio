# Anki Voice Studio

Local voice creation, MP3 generation, and Anki audio tools for Windows.

**Anki Voice Studio works on your computer:** it can create custom voice
profiles, generate MP3 files for new vocabulary cards, and add audio to
existing Anki notes. Your card texts, voice samples, profiles, and generated
audio stay on the computer.

> Looking for the card design and review controls? Install the companion
> [Anki Card Template](https://github.com/RemyGremory/anki-card-template).

## What it can do

- Create MP3 audio for the word, translation, and examples.
- Build an Anki-ready CSV pack from a pasted card list.
- Add or replace audio in selected existing notes through AnkiConnect.
- Create, audition, save, and remove local voice profiles.
- Edit pronunciation text before generation without changing the card text.
- Skip text in parentheses and insert configurable pauses between examples.
- Work with English, Russian, Norwegian Bokmål, and many other languages.

## Installation

### Windows 10/11

1. Open the [latest release](https://github.com/RemyGremory/anki-voice-studio/releases/latest).
2. Download **`AnkiVoiceStudioSetup.exe`** — do not download the source-code ZIP.
3. Run it and choose the recommended edition:
   - **Compact CPU** works on every Windows PC.
   - **Faster NVIDIA** is offered when a supported NVIDIA graphics card is detected.
4. Click **Install Anki Voice Studio**.
5. Afterwards, use the desktop shortcut **Anki Voice Studio Setup**. It checks
   for an update before starting the program, so a new version does not require
   reinstalling everything manually.

Python, packages, and audio libraries are included in the application build.
Internet access is needed for the first audio generation because the OmniVoice
model is downloaded then. Keep roughly 8 GB of free space available for the
application, voice model, and your generated files.

## Create new cards with audio

1. Open **New cards**.
2. Paste a list of cards from your Python script or use the example.
3. Choose what to voice: **Word**, **Translation**, and/or **Examples**.
4. Choose languages and saved voice profiles. Use **Preview voice** before a
   large generation.
5. Click **Create MP3 and CSV**.
6. Import the resulting `anki_cards.csv` into Anki.
7. Return to the program and complete step 4, **Add audio to Anki**. The program
   copies the generated MP3 files into the selected Anki profile automatically.
8. Sync Anki normally to make the audio available on a phone.

For the full interactive card experience, install the companion
[Anki Card Template](https://github.com/RemyGremory/anki-card-template) first.
It provides the matching `AudioWord`, `AudioTranslation`, and `AudioExample`
fields and controls for recorded audio.

## Add audio to existing Anki cards

This mode needs the free AnkiConnect add-on on the Windows computer only.

1. In Anki Desktop, choose **Tools → Add-ons → Get Add-ons…**.
2. Enter `2055492159` and restart Anki.
3. In Voice Studio, open **Cards from Anki** and click **Check connection**.
4. Select a deck or select one or more notes in Anki Browse.
5. Enable the fields to update, preview the voices, and click **Add audio to
   Anki**.

Nothing extra is needed on iPhone or Android: simply sync Anki after audio has
been added on the computer.

## Voice Studio

Use **Voice studio** to make a local voice profile. Add a short voice sample,
enter exactly what is spoken in it, select voice traits, and listen to test
text. A profile can be saved, used for card generation, or removed later.

Only use voice samples that you have permission to use.

## Required Anki fields

For the companion template, use these exact field names:

`Front`, `Back`, `Description`, `Example`, `verb`, `Comment`, `Image`,
`AudioWord`, `AudioTranslation`, `AudioExample`.

The last three fields are used for recorded MP3 audio. Their order in Anki does
not matter; the names do.

## Privacy and files

- No cards, audio, profiles, or voice samples are uploaded by this app.
- Each user has separate local data in `AppData\Local\AnkiVoiceStudio`.
- The GitHub project intentionally excludes personal profiles, generated MP3s,
  card lists, reference recordings, and the downloaded model.

## Development

The repository includes build scripts for maintainers. Normal users should use
only `AnkiVoiceStudioSetup.exe` from Releases.

Created by Remy.
