# Fixture font

`fixture-sans.ttf` is a Noto Sans subset under the adjacent SIL OFL licence.
Source: [Google Fonts commit 2984c575fdce412ee02b2baaba67672b9a9434d8](https://github.com/google/fonts/tree/2984c575fdce412ee02b2baaba67672b9a9434d8/ofl/notosans).
Original `NotoSans[wdth,wght].ttf` SHA-256:
`bfb7bb691513f12e734dc346c03a03f784912432d7e3fa8e56efcf906fe86b3d`.

Made once with fonttools 4.64.0 (in uv.lock), keeping ASCII and Croatian letters:

```text
uv run fonttools varLib.instancer "NotoSans[wdth,wght].ttf" wght=400 wdth=100 --output static.ttf
uv run fonttools subset static.ttf --unicodes=U+0020-007E,U+0106-0107,U+010C-010D,U+0110-0111,U+0160-0161,U+017D-017E --output-file=scripts/fonts/fixture-sans.ttf
```

Ordinary fixture regeneration uses the committed subset and needs no font download.
