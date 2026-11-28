# Bundled font provenance

`LiberationSans-Regular.ttf` is the **unmodified** Liberation Sans Regular 2.1.5
font (name table: `Version 2.1.5`, family "Liberation Sans"), licensed under the
SIL Open Font License 1.1 (see `LiberationSans-LICENSE.txt`, which is the upstream
`LICENSE` file of the Liberation Fonts 2.1.5 source release, byte for byte).
It is embedded into the native RicePlate binary with `include_bytes!`, which is
why the licence and copyright notice are installed in the package documentation
directory of every package that ships that binary (`ricebowl-riceplate-native`).

| | |
| --- | --- |
| Upstream project | Liberation Fonts, <https://github.com/liberationfonts/liberation-fonts> |
| Upstream version | 2.1.5 |
| Copyright | (c) 2010 Google Corporation (reserved font names Arimo, Tinos, Cousine); (c) 2012 Red Hat, Inc. (reserved font name Liberation) |
| Bundled file | `LiberationSans-Regular.ttf`, 410820 bytes, sha256 `4659bc0c58c5028dd488ec928d41d9265db43d9b669fc14ca8b0832daca7b144` |
| Obtained from | Debian/Ubuntu package `fonts-liberation` 1:2.1.5-3, installed path `/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf` (Ubuntu archive `pool/main/f/fonts-liberation/fonts-liberation_2.1.5-3_all.deb`, sha256 `065c2ab1abc9108b17d401016dc594b79750904390f095845c93bb06e1153acc`; verified with `dpkg -V fonts-liberation`) |
| Source it is built from | `fonts-liberation_2.1.5.orig.tar.gz` (sha256 `9a823ccb33c8a8a865e84b982bcdc44d03ba4914adb91e6000df035dc0e55936`), i.e. the upstream 2.1.5 source release, built with FontForge by the distribution |
| Reserved font name | The file is not modified, so the reserved name "Liberation" stays valid (OFL condition 3). |

## Earlier bundled file (sha256 `bade59d82265...`) and why it was replaced

Before this change the repository bundled a file with sha256
`bade59d822652f76e6941aa87b40a87c13d1cc70db98ededb5011127efafd1d3`, which did not
match the Debian file of the same version and size. A byte-level comparison showed
that **10 bytes differ**: the `FFTM` table's build timestamp (`2023-01-18 18:05:41`
in the old file, `2023-02-04 12:26:11` in the Debian one), that table's directory
checksum, and the font-wide `head.checkSumAdjustment`. Every other table of the
OpenType directory (`glyf`, `loca`, `cmap`, `GPOS`, `GSUB`, `kern`, `name`,
`OS/2`, `hmtx`, hinting programs, ...) has identical length, offset and checksum.
So the old file is consistent with a different FontForge rebuild of the same
sources (FontForge stamps `FFTM` with the build time) and is not a modified or
subset font; its origin was not recorded, but there is no sign the reserved name
was misused. It was nevertheless not traceable to a public,
checksummed release, so it was replaced by the file above; glyph outlines, metrics
and layout tables are byte-identical, so rendered text does not change.

The upstream release tarball of prebuilt TTFs
(`liberation-fonts-ttf-2.1.5.tar.gz` from the project's GitHub release) could not be
fetched from the build sandbox (egress to that host is blocked). When a maintainer
with access compares it, only the `FFTM` stamp and the derived checksums are expected to differ;
record the upstream sha256 here when verified.

## Re-verifying

```sh
sha256sum assets/fonts/LiberationSans-Regular.ttf
fc-query assets/fonts/LiberationSans-Regular.ttf | grep -E 'family|fontversion'
```
