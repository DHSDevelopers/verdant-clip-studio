# BGM pool

Place royalty-free tracks in mood folders. The pipeline picks a random track
from the AI-selected mood, loops it, and either sidechain-ducks it under speech
(`--bgm-mode ducking`, default) or mixes it at a constant low level
(`--bgm-mode background`). If a folder is empty the clip still renders, silently.

```
assets/bgm/
  chill/      *.mp3 | *.wav | *.m4a | *.aac
  epic/
  sad/
  upbeat/
  suspense/
```

AI clip metadata carries `bgm_mood`; unknown moods fall back to `chill`.
