# Anki Voice Studio

Local voice creation, MP3 generation, and Anki audio tools for Windows.

**Anki Voice Studio runs locally on your computer.** It can create custom voice
profiles, generate MP3 files for new vocabulary cards, and add audio to
existing Anki notes. Your card texts, voice samples, profiles, and generated
audio stay on your computer.

> **Important: CPU generation is slow.** The Compact CPU edition is a
> compatibility fallback, not an option for weak PCs. Creating roughly ten
> seconds of audio can take about a minute and noticeably load the processor;
> the exact speed varies by computer. If a compatible NVIDIA graphics card is
> available, choose **Faster NVIDIA** — it is the recommended edition.

> For card design and review controls, see the
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
   - **Compact CPU** works on every Windows PC, but generation is slow and it
     is not recommended for weak computers.
   - **Faster NVIDIA** is offered when a supported NVIDIA graphics card is
     detected and is strongly recommended when available.
4. Click **Install Anki Voice Studio**.
5. Afterwards, use the desktop shortcut **Anki Voice Studio**. It checks
   for an update before starting the program, so a new version does not require
   reinstalling everything manually.

Python, packages, and audio libraries are included in the application build.
Internet access is needed for the first audio generation because the OmniVoice
model is downloaded then. Keep roughly 8 GB of free space available for the
application, voice model, and your generated files.

## Create new cards with audio

1. Open **New cards**.
2. Paste a list of cards or use the included example.
3. Choose what to voice: **Word**, **Translation**, and/or **Examples**.
4. Choose languages and saved voice profiles. Use **Preview voice** before a
   large generation.
5. Click **Create MP3 and CSV**.
6. Import the resulting `anki_cards.csv` into Anki.
7. Return to the fourth panel, **Add audio to Anki**, and confirm that you
   imported the cards. The program then copies the generated MP3 files into the
   selected Anki profile automatically.
8. Sync Anki normally to make the audio available on a phone.

For the full interactive card experience, install the
[Anki Card Template](https://github.com/RemyGremory/anki-card-template) first.
It adds the `AudioWord`, `AudioTranslation`, and `AudioExample` fields and the
controls for recorded audio.

## Add audio to existing Anki cards

This mode needs the free AnkiConnect add-on. Install it only on the Windows
computer where you run Anki Voice Studio and Anki Desktop.

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
enter the exact words spoken in it, choose the voice settings, and preview test
text. You can save the profile, use it for card generation, or remove it later.

Only use voice samples that you have permission to use.

## Required Anki fields

For the card template, use these exact field names:

`Front`, `Back`, `Description`, `Example`, `verb`, `Comment`, `Image`,
`AudioWord`, `AudioTranslation`, `AudioExample`.

The last three fields are used for recorded MP3 audio. Their order in Anki does
not matter; the names do.

## Privacy and files

- No cards, audio, profiles, or voice samples are uploaded by this app.
- Each user has separate local data in `AppData\Local\AnkiVoiceStudio`.
- The GitHub project intentionally excludes personal profiles, generated MP3s,
  card lists, reference recordings, and the downloaded model.

## Build files

This repository also contains files used to build the application. You do not
need them to use Voice Studio: download only `AnkiVoiceStudioSetup.exe` from
Releases.
