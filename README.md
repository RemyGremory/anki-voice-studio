# Anki Voice Studio

Local voice creation, MP3 generation, and Anki audio tools for Windows.

**Anki Voice Studio runs locally on your computer.** It can create custom voice
profiles, generate MP3 files for new vocabulary cards, and add audio to
existing Anki notes. Your card texts, voice samples, profiles, and generated
audio stay on your computer.

> **Close the app when you finish.** Click **Close app** at the top of Anki
> Voice Studio. Closing only the browser tab does not stop the local program;
> it can keep running in the background.

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

1. Open the [Releases page](https://github.com/RemyGremory/anki-voice-studio/releases)
   and open the newest release. A release marked **Pre-release** is a testing
   version; use it only if you are comfortable reporting any problems.
2. Download **`AnkiVoiceStudioSetup.exe`**. Do not download **Source code
   (zip)** or the large CPU/NVIDIA ZIP files: the setup app selects and
   downloads the right edition for you.
3. Run `AnkiVoiceStudioSetup.exe`. Windows may show a SmartScreen warning for
   this new unsigned app. Continue only if you downloaded the file from the
   official Releases page above; then choose **More info → Run anyway**.
4. In the setup app, use **Choose folder** if you want a different installation
   location. Then choose an edition:
   - **Compact CPU** works on every Windows PC, but generation is slow and it
     is not recommended for weak computers.
   - **Faster NVIDIA** is offered when a supported NVIDIA graphics card is
     detected and is strongly recommended when available.
5. Click **Install Anki Voice Studio** and wait for the download and
   installation to finish. The NVIDIA edition is large, so its first download
   can take a while.
6. Afterwards, start the program with the desktop shortcut **Anki Voice
   Studio**. It checks
   for updates before starting the program. Normal updates download only the
   small files that changed; the large CPU or NVIDIA components are kept in
   place. A full download is needed only after a major engine change or when
   reinstalling the program.

Python, packages, and audio libraries are included in the application build.
Internet access is needed for the first audio generation because the OmniVoice
model is downloaded then. Keep roughly 8 GB of free space available for the
application, voice model, and your generated files.

## First start

1. Open the desktop shortcut and wait for the app to check its components.
   If a **Download components** button appears, click it and wait until the
   app reports that the components are ready.
2. Use the **EN / RU** buttons in the top-right corner to choose the interface
   language.
3. Choose one of the three tabs: **New cards**, **Voice studio**, or
   **Cards from Anki**.
4. Leave the app open while it creates audio or downloads a model. When you
   finish, click **Close app** at the top of the window — closing the browser
   tab alone does not stop the program.

## Create new cards with audio

1. If you use the companion template, install the
   [Anki Card Template](https://github.com/RemyGremory/anki-card-template)
   first. It creates the audio fields used by the CSV.
2. Open **New cards**. Paste a JSON list of cards, open a `.json`, `.txt`, or
   `.py` list file, or click **Load example**. Each card needs a word and a
   translation. The program accepts either `Word` / `Translation` or `Front` /
   `Back` field names. For example:

   ```json
   [{
     "Word": "outcome",
     "Translation": "итог, результат",
     "Explanation": "A result or effect of an action or event.",
     "Examples": "We are waiting for the outcome of the election."
   }]
   ```

3. Click **Validate list**. Fix any reported missing `Word`/`Front` or
   `Translation`/`Back` fields before continuing.
4. Choose what to voice: **Word**, **Translation**, and/or **Examples**. Pick
   the language and either a saved profile or **Automatic voice** for each
   choice. Use **Preview voice** before a large generation.
5. Click **Create MP3 and CSV**. Keep the app open until the progress panel
   finishes.
6. Click **Open folder** when the result appears. In Anki Desktop, choose
   **File → Import**, select `anki_cards.csv`, choose the same note type that
   has the matching fields, check the column mapping, and import the cards.
7. A fourth panel, **Add audio to Anki**, appears in the **New cards** tab
   after the files are created. Choose the correct Anki profile, then click
   **I imported cards — add audio**. The program copies the MP3 files to that
   profile.
8. Click **Sync** in Anki to make the cards and audio available on your phone
   or other devices.

Example audio is generated from the part of each example before an em dash
(`—`). Put a translation after that dash if you want it to appear on the card
but not be spoken.

## Add audio to existing Anki cards

This mode needs the free AnkiConnect add-on. Install it only on the Windows
computer where you run Anki Voice Studio and Anki Desktop.

1. In Anki Desktop, choose **Tools → Add-ons → Get Add-ons…**.
2. Enter `2055492159`, confirm, then restart Anki. Keep Anki Desktop open.
3. Make sure the note type has the `AudioWord` and `AudioTranslation` fields;
   add `AudioExample` too if you want spoken examples.
4. In Voice Studio, open **Cards from Anki** and click **Check connection**.
5. Choose **Whole deck** and select a deck, or open **Browse** in Anki, select
   one or more notes, then choose **Selected in Browse** in Voice Studio.
6. Click **Find cards**. Enable the fields you want to voice, choose languages
   and voices, and use **Preview voice** to check them.
7. Leave **Replace audio in the enabled fields** selected only when you want to
   overwrite existing recordings. Click **Add audio to Anki** and wait for it
   to finish.
8. Click **Sync** in Anki to send the new audio to your phone or other devices.

Nothing needs to be installed on iPhone or Android.

## Voice Studio

Use **Voice studio** to create a local voice profile or save a separate MP3.

1. Open **Voice studio** and enter a **Profile name**.
2. Choose the language. For a cloned voice, add a clear 3–10-second WAV, MP3,
   M4A, or FLAC sample and enter the exact words spoken in it. You can instead
   create a described voice by choosing voice traits. **Automatic voice** is
   also available when generating audio and does not need a saved profile.
3. Click **Save profile**. The profile becomes available in **New cards** and
   **Cards from Anki**.
4. In **Speak any text**, enter text, choose a profile, and use **Listen** to
   preview it or **Save MP3** to create a separate audio file. Use **Open
   folder** to find the saved file.

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
