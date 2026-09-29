# Plug-in formats

Plugg publishes Windows plug-ins as VST3, and also as VST2 and CLAP if you switch those on. VST3 is always on. Turn on VST2 to reopen projects that saved their plug-ins as VST2, such as projects made on Windows. Turn on CLAP if your DAW prefers it.

## Choosing formats

In the app, press **Settings** and tick the formats. From a terminal:

```sh
plugg formats                                   # what is published, and where
plugg formats --enable vst2 --enable clap
plugg formats --disable clap
```

The choice applies to the whole library and only to what Plugg publishes from then on. It never removes a plug-in that is already published. Switching VST2 off stops new VST2 publications, and the old project that needed one keeps working.

The line under the drop area says what new plug-ins are published as.

Switching a format on publishes nothing by itself either. Plugg checks a plug-in by loading it, and loading an unactivated plug-in can open its activation window. So plug-ins you already have get the new format when you use **Check again** or **Refresh library** on their vendor.

A format is published for every plug-in that ships it, even when the same plug-in also has another format. Your DAW may list a CLAP and a VST3 of one plug-in side by side.

## Taking one plug-in or format out

Open a vendor's settings (the cogwheel) and choose **Plug-ins in your DAW…**. Each plug-in has a box for every format it was published in. Untick one to take it out of your DAW, and tick it to put it back. Plugg keeps a plug-in you untick out when it checks that vendor again, and does not load it to check it. The bundle stays in the library, so putting it back is immediate.

From a terminal, each format of a plug-in has its own ID in `plugg list`:

```sh
plugg unpublish --plugin <id>    # take it out and keep it out
plugg republish --plugin <id>    # put it back
```

`plugg forget` is for a plug-in the vendor's uninstaller removed. Checking again brings a forgotten plug-in back if it is still installed.

## Folders

| Format | Your DAW scans | Each plug-in is |
|---|---|---|
| VST3 | `~/.vst3/plugg` | a link `Name.vst3` to a VST3 bundle |
| VST2 | `~/.vst/plugg` | a link `Name` to a folder holding `Name.so` |
| CLAP | `~/.clap/plugg` | a link `Name` to a folder holding `Name.clap` |

The VST3 folder is fixed when the library is created. The VST2 and CLAP folders are recorded in `settings.json` the first time you switch the format on, and they do not move after that. A library created with `--publish-dir` somewhere other than `~/.vst3` gets its VST2 and CLAP folders beside that one, so a development library never writes to your real DAW folders.

VST2 and CLAP are published as a link to a folder rather than to the file itself. The patched chainloader looks for the `.plugg-managed` marker beside the path the DAW loaded it from, without resolving links. The Windows file sits in the same folder under the name yabridge looks for. For CLAP that is `Name.clap-win`, which keeps a Windows `.clap` out of the DAW's own scan.

## What Plugg finds

For an installer Plugg has no recipe for, Plugg searches the whole Windows drive of the environment:

- A `.vst3` file is a VST3 plug-in.
- A `.clap` file is a CLAP plug-in.
- A `.dll` is a VST2 plug-in when it exports `VSTPluginMain` or `main`. Plugg reads the export table and loads nothing.

Vendor apps such as Native Access and UA Connect are only searched in their install folders, never in their download caches. For VST2 those are `Program Files\Common Files\VST2`, `Program Files\Common Files\Steinberg\VST2`, `Program Files\VSTPlugins`, `Program Files\Steinberg\VSTPlugins` and `Program Files\Native Instruments\VSTPlugins 64 bit`. For CLAP it is `Program Files\Common Files\CLAP`.

A `.clap` file counts only when it exports `clap_entry`. Plugg skips 32-bit VST2 and CLAP files without reporting them. Installers often put them next to the 64-bit ones, and the bridge hosts 64-bit plug-ins only.

## Identities

A saved project finds a plug-in again by its identity, and each format has its own:

- VST3: the class IDs from the plug-in's factory.
- VST2: the four-byte unique ID, such as `PgG2`. Plugg records it with the publication and refuses a VST2 without one.
- CLAP: the plug-in's ID string, such as `com.vendor.product`.

Plugg refuses to publish two plug-ins with the same identity within one format. The same plug-in can have the same ID as VST2 and as VST3.

## Dropping a plug-in file

You can drop a VST2 `.dll` or a CLAP `.clap` on the window, as you can a `.vst3`. Plugg checks the file's headers before it copies anything. A DLL that does not export a VST2 entry point is refused as "not a VST2 plug-in", and so is a 32-bit one. Plugg then installs the file into a private environment, under `Program Files\Common Files\VST2` or `Program Files\Common Files\CLAP`, and publishes it in its own format. That happens even if the format is switched off under Settings, because dropping the file is the request. See [standalone import](standalone-import.md).

## Not supported

- VST2 shells, which hold several plug-ins in one file. Plugg publishes one plug-in per file, so it refuses a shell when it loads it.
- A bridge from before VST2 and CLAP support. `plugg formats --enable` refuses a format the current bridge build cannot publish.

## Testing

`scripts/test-formats.py` installs a test gain as VST3, VST2 and CLAP in a new library under `.test-formats/`. It publishes all three, then plays 1000 blocks of audio through each published plug-in, using the path a DAW would load. It passes only if the output is exactly half the input. It then drops the VST2 `.dll` and the CLAP `.clap` into a second library that publishes VST3 only, and checks both the same way.

```sh
scripts/build-bridge.sh
scripts/build-fixture.sh
python3 scripts/test-formats.py --bridge bundle/bridge --runtime-from <a development library>
```
