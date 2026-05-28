# Speaker Recognition

This folder implements the two-step voice gate for Go2 voice control.

1. Voice Detection: decide whether the microphone audio contains human speech and extract voiced segments.
2. Speaker Identification: compare the voiced segment against enrolled speaker embeddings and return a speaker ID.

The implementation is intentionally lightweight: it uses an energy + zero-crossing-rate VAD and MFCC-statistics speaker embeddings. This works as a local prototype and keeps the interfaces ready for a future deep speaker embedding model.

## Install

```bash
pip install numpy
```

Microphone recording also needs:

```bash
pip install sounddevice
```

## Usage

Run VAD on a WAV file:

```bash
python -m Speaker_Recognition.cli detect input.wav --voice-out voice_only.wav
```

Enroll each speaker:

```bash
python -m Speaker_Recognition.cli enroll jiayu samples/jiayu_1.wav
python -m Speaker_Recognition.cli enroll alice samples/alice_1.wav
```

Identify a speaker:

```bash
python -m Speaker_Recognition.cli identify query.wav
```

Record from the microphone and identify:

```bash
python -m Speaker_Recognition.cli record-identify --seconds 4
```

Output example:

```json
{
  "is_speech": true,
  "speaker_id": "jiayu",
  "score": 0.9132,
  "scores": {
    "jiayu": 0.9132,
    "alice": 0.7041
  },
  "segments": [[1600, 53440]]
}
```

## API

```python
from Speaker_Recognition.recognizer import SpeakerRecognizer

recognizer = SpeakerRecognizer("Speaker_Recognition/speaker_profiles.json")
recognizer.enroll_file("jiayu", "samples/jiayu_1.wav")
result = recognizer.identify_file("query.wav")

print(result.is_speech)   # Step 1 boolean
print(result.speaker_id)  # Step 2 identity or None
```
