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

No fixed `SourceDateEpoch=` is needed in either recipe. The shared configure
hook selects one epoch for the first-stage mkosi invocation, including the
base, initrd and desktop images. `mkosi.postoutput` writes that value into
the generated signing recipe, and `mkosi.final-output` carries it into any
additional signing round. Signing jobs must not choose their own epochs.

Package manifests are disabled for the OS and its build roots. Nothing in the
current build/signing/runtime pipeline consumes their inventories, and the
mkosi layered RPM timestamp filter does not provide a reliable complete-root
inventory. Export instead validates the retained RPM database and release
identity. Per-build epochs, image signing and repository checksum signatures
remain enabled. Keep metadata-preserving `BaseTrees=`: directory
`SkeletonTrees=` copies do not preserve ownership or xattrs.

The `Packages=` lists in `mkosi.obs/*.conf` contain the union of the base,
matching desktop root, default-initrd and disk images. OBS resolves RPM dependencies from
the entry recipe before mkosi evaluates `mkosi.images/`. Regenerate both lists
after changing image packages:

```sh
./update-obs-packages.py
./update-obs-packages.py --check
```

Each existing desktop job also exports its versioned `.buildroot.tar.xz` and
convenience checksum. No extra OBS package
is needed for the export. `KDE-root`/`GNOME-root` do not include mkosi-obs's
disk-signing hooks. They inherit the public Verity certificate from the main
image's mkosi-obs integration, just like the disk stage.
The exported filesystem keeps its RPM database,
while the disk stage strips package metadata before producing EROFS.

The export names deliberately begin with `proto-kde`/`proto-gnome`, matching
mkosi-obs's artifact carry-forward convention. Keep these files through all
signing rounds and include them in the repository's signed checksum listing.
The source service definitions and desktop marker selection stay unchanged.
Account for both the retained directory and the XZ export when measuring
worker disk requirements.
