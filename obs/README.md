# OBS desktop split

Create two OBS packages that track the same Git revision:

- `proto-gnome`: use `obs/gnome/_service`
- `proto-kde`: use `obs/kde/_service`

The service uses `extract-rename` to expose the selected desktop recipe as the
top-level `mkosi.conf` recognized by OBS. Do not add the old
`<param name="extract">mkosi.conf</param>` alongside it, or both the combined
and desktop-specific entry points would target the same output file.

Each service excludes the other desktop's marker from its source archive. The
remaining marker activates the matching `mkosi.conf.d` drop-in when the OBS
worker loads the orchestration-only `mkosi.conf` inside the source archive.

Keep `_constraints` in both OBS packages. The initial build and its signing
follow-up then contain only one desktop image each.

The `Packages=` lists in `mkosi.obs/*.conf` contain the union of the base,
default-initrd and matching desktop images. OBS resolves RPM dependencies from
the entry recipe before mkosi evaluates `mkosi.images/`. Regenerate both lists
after changing image packages:

```sh
./update-obs-packages.py
./update-obs-packages.py --check
```
