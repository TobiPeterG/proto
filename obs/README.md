# OBS desktop split

Two OBS packages track the same Git revision:

- `proto-gnome`: `obs/gnome/_service`
- `proto-kde`: `obs/kde/_service`

The service uses `extract-rename` to expose the selected desktop recipe as the
top-level `mkosi.conf` recognized by OBS. The combined and desktop-specific
entry points have the same output filename, so each package exposes only its
selected desktop entry point.

Each service excludes the other desktop's marker from its source archive. The
remaining marker activates the matching `mkosi.conf.d` drop-in when the OBS
worker loads the orchestration-only `mkosi.conf` inside the source archive.

Each package has its own `_constraints` file. The initial build and its signing
follow-up contain only one desktop image each.

No fixed `SourceDateEpoch=` is needed in either recipe. The shared configure
hook selects one epoch for the first-stage mkosi invocation, including the
base, initrd and desktop images. `mkosi.postoutput` writes that value into
the generated signing recipe, and `mkosi.final-output` carries it into any
additional signing round, preserving the first-stage timestamp.

Package manifests are disabled for the OS and its build roots. Nothing in the
current build/signing/runtime pipeline consumes their inventories, and the
mkosi layered RPM timestamp filter does not provide a reliable complete-root
inventory. Export instead validates the retained RPM database and release
identity. Per-build epochs, image signing and repository checksum signatures
remain enabled. `BaseTrees=` preserves metadata; directory `SkeletonTrees=`
copies do not preserve ownership or xattrs.

The `Packages=` lists in `mkosi.obs/*.conf` contain the union of the base,
matching desktop root, default-initrd and disk images. OBS resolves RPM dependencies from
the entry recipe before mkosi evaluates `mkosi.images/`.
`update-obs-packages.py` generates both lists from the image definitions, and
its `--check` mode detects lists that no longer match those definitions.

Each existing desktop job also exports its versioned `.buildroot.tar.xz` and
convenience checksum, plus a scheduler-visible build-root RPM.
`KDE-root`/`GNOME-root` do not include mkosi-obs's
disk-signing hooks. They inherit the public Verity certificate from the main
image's mkosi-obs integration, just like the disk stage.
The exported filesystem keeps its RPM database,
while the disk stage strips package metadata before producing EROFS.

The export names deliberately begin with `proto-kde`/`proto-gnome`, matching
mkosi-obs's artifact carry-forward convention. The artifacts pass through the
signing rounds and are covered by the repository's signed checksum listing.
The source service definitions and desktop marker selection stay unchanged.
Both the retained directory and the XZ export contribute to worker disk usage.

## Separate sysext packages

`sysext-build-tools` and `proto-buildroots` are maintained as separate OBS
source packages and built in the ordinary Tumbleweed RPM repository.
Their sources are separate from this Git source tree. The generated root
RPMs contain their archives, RPM inventories and release metadata under
`/usr/share/sysext-buildroots/`, using descriptor format 1 understood by the
shared builder.

`proto-buildroots` provides `mkosi-buildroots` and requires both desktop root
RPMs. The separate `sysext` repository installs that collection and the shared
builder in its workers, while OS workers produce the root RPMs independently.
Its repository paths provide access to the RPM packages, image build outputs
and upstream dependencies. `sysext-nano` discovers installed desktop roots through
the shared builder; the Nano source package does not contain base archives or
copies of the generator.
