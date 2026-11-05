# Languages and Hindi

Sabhalekh is built for meetings in **English, Hindi, and Hinglish**, the everyday mix of both.

## Choosing the language

**Settings → Transcription → Language**:

| Option | Use it when |
|---|---|
| **Auto: English + Hindi (code-switching)** | Most meetings. Each turn is checked separately, so one person can speak Hindi and the next English. This is the default. |
| **English only** | Everyone speaks English. Slightly more reliable for English with an accent. |
| **Hindi only** | Everyone speaks Hindi. Try this if Hindi speech comes out as English words. |
| **Translate Hindi to English** | You want an English transcript of a Hindi meeting. Needs the free Accuracy model pack, see [Offline model packs](Offline-Model-Packs). |

Each line in the transcript is tagged **EN** or **HI** so you can see what was detected.

## How Hindi is written

**Settings → Transcription → Hindi / Hinglish script**:

| Option | Example |
|---|---|
| **As spoken** (default) | Hindi in Devanagari, English in Latin letters |
| **Devanagari** | मीटिंग कल है |
| **Roman (transliterated)** | meeting kal hai |

*Roman* is handy if you'll paste the text into WhatsApp or email, or if the people reading it don't read Devanagari.

## Things to know about Hindi

- **English words inside Hindi sentences** often come out in Devanagari, the way they sound: "स्पीड डिटेक्शन" for
  "speed detection". This is how the speech model writes Hinglish. If you prefer Latin letters, choose the *Roman*
  script.
- **Numbers** are written as spoken: "नाइन्टीन सेवेंटी नाइन" rather than 1979.
- **Casual, fast Hinglish** is harder than clear speech for every speech model. Good microphones and headphones help
  more than any setting.

## Shruti, a small model for Hinglish

**Udgam Labs Shruti** is an optional 55-million-parameter model (about 30 MB) trained on Indian speech. Pick it in
**Settings → Transcription → Speech recognition model**. It works on the CPU, needs very little memory, and is the
most accurate open model its authors measured on Hinglish. Notes:

- Hindi is written in Devanagari and English words in Latin letters, so Hinglish comes out naturally. *Roman* script
  still works; *Devanagari* cannot turn English words into Devanagari.
- There is **no punctuation or capital letters**, and numbers are written as words. Nemotron adds punctuation.
- Use **English only** for Indian-accented English. Its English is weaker than Whisper large-v3's.
- It cannot translate, and it was not tested on noisy rooms, music or rare names.

## Hima-ASR, for Hindi and the South Indian languages

**Prahaladha Hima-ASR** is an optional 0.46-billion-parameter model for English and eleven Indian languages. It has
the lowest published error rate of its size in Telugu, Tamil, Kannada and Malayalam. It is not part of the standard
installer because it carries Google's Gemma Terms of Use; add it with `python tools/fetch_models.py --with-hima` when
building from source, or import a model pack that contains it. Pick it in **Settings → Transcription → Speech
recognition model**. Notes:

- It is about 0.5 GB (a 4-bit build, as accurate as the 8-bit one on our Hindi tests) and runs on any computer.
  On Windows, with a dedicated or integrated GPU, the part that listens to the audio runs on the GPU through
  DirectML (no CUDA needed) and the part that writes the text runs on the CPU, where it is fastest. On a GTX 1650
  that is about 12x real time; on the CPU alone about 8x. If the GPU fails, it carries on on the CPU.
- Leave the language on **Automatic** to transcribe Tamil, Telugu and the other languages: the model detects the
  language. *Hindi only* and *English only* are passed to the model as they are.
- *As spoken* and *Roman* write English words in Latin letters inside the native script; *Devanagari* writes
  everything in the native script.
- There is **no punctuation or capital letters**, and it ignores custom vocabulary. It cannot translate.
- Speaker labelling and the search are tuned for English and Hindi; other languages are transcribed but not tested end to end.

## Custom vocabulary

**Settings → Transcription → Custom vocabulary** lets you list names and jargon (*Rahul Sharma, Kubernetes, GST,
Jio*). It helps spelling with Shruti and with the Whisper models from the Accuracy pack. The built-in Nemotron model
doesn't accept a vocabulary.

## Other languages

Sabhalekh is tuned for English and Hindi. Other languages may be recognised by the Whisper models in a model pack,
but they are not tested and not officially supported.
