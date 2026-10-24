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

## Custom vocabulary

**Settings → Transcription → Custom vocabulary** lets you list names and jargon (*Rahul Sharma, Kubernetes, GST,
Jio*). It helps spelling only with the Whisper models from the Accuracy pack. The built-in Nemotron model doesn't
accept a vocabulary.

## Other languages

Sabhalekh is tuned for English and Hindi. Other languages may be recognised by the Whisper models in a model pack,
but they are not tested and not officially supported.
