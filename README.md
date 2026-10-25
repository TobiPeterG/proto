# proto

Prototype for an openSUSE-based desktop OS with KDE Plasma and GNOME images.
The immutable operating system is an EROFS `/usr` protected by dm-verity and
updated atomically through a native A/B partition layout.

## Disk layout

A newly created image normally contains nine GPT partitions:

1. a 100–256 MiB EFI System Partition containing Shim and systemd-boot;
2. a 4 GiB XBOOTLDR partition containing versioned UKIs;
3. an 8 GiB EROFS `/usr` partition;
4. a 128 MiB dm-verity hash partition for that `/usr` slot;
5. its dm-verity signature partition;
6. an empty 8 GiB `/usr` update slot;
7. an empty 128 MiB usr-verity update slot;
8. an empty usr-verity signature slot;
9. a writable Btrfs `USER` partition occupying the remaining space.

The first `/usr`/Verity set is populated during the image build. The second
set uses empty partitions, making it available to `systemd-sysupdate`. Both
system slots have fixed sizes; only the final Btrfs partition grows when the
image is written to a larger disk.

XBOOTLDR is always present and mounted as `/boot`; the ESP is mounted as
`/efi`. This keeps the ESP compatible with small firmware- or
Windows-created partitions while reserving 4 GiB for the two large UKIs.
`systemd-sysupdate` targets `$BOOT/EFI/Linux`, which resolves to XBOOTLDR
when both partitions exist.

The Btrfs partition remains the root partition and has this subvolume layout:

```text
@root   mutable root skeleton, /home, /var, /root, /opt, ...
@etc    persistent system configuration shared by both /usr slots
```

Individual users receive nested Btrfs subvolumes below `/home`, managed by the
existing per-user Snapper integration. Flatpaks, containers, logs and other
runtime data remain under `/var` or `/home` and therefore never consume an A/B
system slot.

## Verified boot

The UKI uses:

```text
root=gpt-auto rootfstype=btrfs rw
mount.usr=dissect
rd.systemd.mount-extra=/dev/gpt-auto-root:/sysroot/.system:btrfs:subvol=/,...
rd.systemd.mount-extra=/dev/gpt-auto-root:/sysroot/etc:btrfs:subvol=/@etc
```

`systemd-gpt-auto-generator` discovers the Btrfs root partition.
`mount.usr=dissect` asks systemd to discover the architecture-specific `/usr`
and usr-verity partitions, validate them against the `usrhash` embedded in the
signed UKI and mount EROFS read-only. The Btrfs top level is additionally
available at `/.system`; `/etc` is mounted from the dedicated `@etc`
bootstrap subvolume on initial provisioning. The initrd then selects
`@etc-IMAGE_VERSION` through `@etc-current`; see the deployment notes below.
No deployment image is loop-mounted from writable storage.

### Deployment configuration and enrollment

On a new version's first boot, `proto-etc-factory` snapshots the highest existing
`@etc-VERSION` (or the initial `@etc`), merges factory changes while preserving
user-modified files, validates SELinux labels against the deployment's own
binary policy, and publishes the new snapshot atomically. An existing version's
snapshot is reused unchanged on rollback. `proto-etc-prepare.service` runs in
`RootDirectory=/sysroot` with systemd-managed API mounts. `proto-etc-cleanup.timer`
checks 15 minutes after boot and daily thereafter. Versioned snapshots are kept
exactly while a matching UKI remains in the installed OS's `$BOOT/EFI/Linux`,
including failed and boot-counted entries. There is no extra version buffer or
retry reset. Missing UKI discovery aborts cleanup; mounted snapshots cannot be
deleted. The initial unversioned `@etc` remains the factory bootstrap seed.

First-boot USER provisioning now only enrolls and verifies the human passphrase
using `systemd-cryptenroll`, then retires the verified temporary bootstrap key.
Normal GPT/cryptsetup/mount units unlock and mount root; provisioning no longer
creates a temporary chroot or generates a TPM policy in the initrd.

`proto-tpm-enroll.service` performs enrollment in the booted installed OS,
with Secure Boot, the real machine ID, and native PCR components available.
It requests the human disk passphrase to authorize enrollment; a failed attempt
does not remove passphrase access. TIK likewise defers TPM enrollment until the
installed OS is booted. CLI and native Varlink policy generation select PCRs
0/7/15 with non-strict prediction: unavailable PCRs may be omitted, including
during fwupd's temporary firmware/Secure Boot component relaxation. The CLI
enrollment path still checks PCR 15; signed PCR 11 enrollment is unchanged.
Automatic firmware handling requires systemd >=262 and fwupd >=2.1.7 with its
systemd-pcrlock plugin built and active. The native sockets are enabled, and
boot services restore firmware/Secure Boot components after reboot.

OBS signing is enabled through `mkosi-obs`. It signs the UKI, bootloader and
Verity metadata in its second build stage. The public OBS OpenPGP key is stored
as `/usr/lib/systemd/import-pubring.pgp`, allowing `systemd-sysupdate` to
authenticate the repository checksum manifest.

## Building

The configuration requires mkosi 27 or newer:
the `KDE` and `GNOME` dependency targets include their transitive desktop-root
and base dependencies. `ImageVersion` identifies the resulting release.

`mkosi.configure` chooses one `SourceDateEpoch` from the start time of the
current mkosi invocation. All subimages use the same value, while a later
dependency-triggered OBS build gets a fresh value even if Git did not change.
The epoch is logged, and OBS signing recipes retain it through every signing
round. Configure hooks run at build time, so `mkosi summary` does not show
the automatically selected value.

An explicit `--source-date-epoch=SECONDS` or `SOURCE_DATE_EPOCH=SECONDS`
overrides automatic timestamp selection and is never replaced. Matching
timestamps alone do not reproduce an image: the
RPM inputs and other build inputs must also match.

Each desktop produces:

- an XZ-compressed complete disk image;
- an unsigned or OBS-signed UKI, depending on the build environment;
- compressed split `/usr` and usr-verity partition artifacts;
- a Verity root-hash artifact and checksums.

### Desktop-specific build roots

`KDE-root` and `GNOME-root` construct each complete desktop filesystem exactly
once. They own the desktop package list, desktop `mkosi.extra` tree and
filesystem finalization. The existing `base` image remains an internal common
dependency; it is not the reference filesystem for future desktop extensions.
Both `base` and the desktop roots retain their RPM databases. The KDE/GNOME
disk stages use their corresponding root via `BaseTrees=`, install no further
packages, and explicitly clean package metadata from their own copy before
creating EROFS/Verity, the initrd, UKI and installer add-on.

Each desktop also produces:

- `proto-DESKTOP_VERSION_ARCH.buildroot/`: the local native `BaseTrees=` input;
- `proto-DESKTOP_VERSION_ARCH.buildroot.tar.xz`: a portable build input;
- `proto-DESKTOP_VERSION_ARCH.buildroot.tar.xz.sha256`: its checksum.

The export preserves numeric ownership, permissions, hardlinks, symlinks,
ACLs, capabilities and SELinux xattrs, and excludes transient runtime/cache
contents. It streams tar through XZ with two threads, avoiding an extra
uncompressed tar and unbounded compression memory use. Export fails if the
RPM database or release identity is missing. The directory
remains available for the disk stage or future sysext stages. Build roots are
not bootable images and contain no installer account or TPM enrollment state.

Package manifests are disabled for the base, desktop roots and disk images:
no current build or runtime component consumes them, and mkosi's layered RPM
inventory can be incomplete with reproducible installation timestamps.
Extension builds use the retained RPM database, not a JSON package inventory.
Repository `SHA256SUMS`/`SHA256SUMS.gpg` authentication remains enabled; these
checksum manifests are independent of package inventories. Future sysext
recipes can enable their own package manifests if their management tools need
them.

The `KDE-root` and `GNOME-root` dependency targets produce desktop roots
without a disk image or default initrd. Extension compatibility depends on
matching desktop, release, architecture and RPM inputs; a moving latest alias
or packages from a newer Tumbleweed snapshot do not guarantee that match.

Both the exported root and installed OS set `SYSEXT_LEVEL` in
`/usr/lib/os-release` to `IMAGE_ID-IMAGE_VERSION`, for example
`proto-kde-26.1` or `proto-gnome-26.1`. The distribution `ID` is unchanged.
With `Format=sysext`, mkosi inherits this level into the extension's
`/usr/lib/extension-release.d/extension-release.NAME`. Native systemd-sysext
matching therefore rejects extensions for another desktop or release, and
checks the extension's architecture as well. Overridden levels or `ID=_any`
bypass these compatibility checks. This is compatibility metadata, not a
signature; authenticated extension images are still required. Updating the OS
requires matching extensions for its new release before they can be merged.
The disk packaging and root export reject mismatching compatibility metadata.

Future extension recipes and their update integration
are separate work; the export alone does not implement those policies.

OBS builds export the corresponding root in the existing per-desktop package.
Artifact names start with the desktop `ImageId`, so mkosi-obs carries the
archive and checksum through its signing rounds. They do not match
the disk/UKI mutation globs in Proto's terminal signing hook. The repository's
signed checksum manifest authenticates the published build input; the
adjacent `.sha256` file is only a convenience checksum, not a signature.
No private signing key is placed in these roots.

Full desktop directories and their compressed archives increase worker disk
usage. Streaming export avoids one extra raw copy but does not eliminate the
additional artifacts or their contribution to peak worker disk usage.

For OBS builds, the first stage compresses the split `/usr` and usr-verity
artifacts with XZ and removes their raw copies. The complete disk crosses into
the second signing stage temporarily compressed with Zstd, which mkosi-obs can
modify natively; only the UKI remains uncompressed. After signatures have been
attached, the disk is converted directly from Zstd to XZ. Published disk and
partition images are therefore XZ-only without an oversized OBS disk request.

The complete uncompressed disk is sparse but has a nominal minimum size of
roughly 28.4 GiB: a 4 GiB XBOOTLDR, a 100–256 MiB ESP, two 8 GiB `/usr`
slots, two 128 MiB Verity slots and at least 8 GiB Btrfs state. A practical
target is a 32 GB device or larger.

## Installation

The desktop images are self-installing live media distributed as
XZ-compressed raw disk images.

On first boot, the installer initrd uses `systemd-repart` to create an
unencrypted TIKSTATE Btrfs partition with the native root GPT type in the USB's
remaining space. A writable
USB with at least 1 GiB free after the image is required; read-only or
undersized media fail instead of falling back to a non-persistent installer.
TIKSTATE's `@root` subvolume backs `/`, allowing GPT-auto to discover the
installer's ESP and XBOOTLDR despite the installer sysext overlay on `/usr`.
The verity data/hash devices use boot-disk-scoped GPT designator links, not
global PARTUUID links that collide with an installed copy of the same image.
Before creating TIKSTATE, the installer independently resolves the disk from
`LoaderDevicePartUUID` and rejects a different `/usr` backing disk or an
ambiguous boot partition UUID.
Normal first boot creates USER without deferring factory-reset-marked partitions.
Existing encrypted USER volumes are preserved, including those with keyslot 0.
New provisioning records a public `proto-user-bootstrap` LUKS token and verifies
the bootstrap key before enrolling a human passphrase. Interrupted provisioning
never triggers automatic volume erasure; an explicit factory reset is required
if no usable human credential was established.
The separate `@state` subvolume is mounted at `/var/lib/tik` and preserves
`log/tik.log` and migration backups across reboots. `/etc` is freshly seeded
from the current image on tmpfs each boot, with ephemeral installer confext
changes, rather than retaining stale live account/desktop configuration.
Installer sysext and confext images are copied from the signed add-on each boot
into tmpfs mounts at `/var/lib/extensions` and `/var/lib/confexts`
TIKSTATE is never copied to the installed system and does not use its USER
provisioning or factory-reset definitions.

The graphical installer is `tik`. Its self-deploy path invokes
`systemd-repart` on the selected target disk. Temporary source-only drop-ins
explicitly select the active A `/usr`, usr-verity and signature partitions
and preserve their partition UUIDs, so the root hash embedded in the UKI
remains valid. Before destination erasure, TIK verifies the boot source mounts
are on the authenticated live disk and contain the bootloader and UKIs.
Without migration, B and encrypted USER are deferred to first installed boot;
with migration, they are created during installation. USER is initialized
from `/usr/share/factory/etc`; live-user autologin and installer authorization
are not copied to the installed system.

The user chooses a LUKS passphrase during migration installation or first boot.
If a TPM 2.0 is present and the booted OBS-signed UKI contains its signed PCR
policy, the installed OS enrolls the disk against a `systemd-pcrlock` policy for PCR 0 (firmware code)
and PCR 7 (Secure Boot policy), as well as the UKI signing key and PCR 11.
PCRs 1 and 2 are deliberately excluded, so firmware settings and additional
option-ROM hardware do not normally invalidate the policy. Each signed update
UKI carries a policy for its own PCR 11 measurement, so regular OS updates
remain unlockable without re-enrollment.

Native `systemd-pcrlock` services maintain the predicted firmware code,
Secure Boot policy and authority, machine ID and file-system components. After
the first installed boot, `proto-pcrlock-policy.service` adds the missing LUKS
volume-key measurement between systemd's machine-ID and root-file-system
components in PCR 15, then requests a policy for PCRs 0, 7 and 15. Native
non-strict update calls may omit unavailable PCRs. The CLI enrollment path
verifies PCR 15, but native Varlink calls do not enforce that extra check.
The volume-key component enables root-identity prediction
New systemd/fwupd versions can therefore relax and restore the managed
firmware-code component around a supported firmware update without replacing
the LUKS token. Changes outside that coordinated path can require the disk
passphrase and rebuilding the policy. No recovery key is generated; the
passphrase remains the fallback. Tik removes its temporary installation key
slot once post-installation modules have completed.

Before erasing an existing Proto installation, Tik can preserve every direct
`/home/<user>` Btrfs subvolume independently on the live medium and restore it
with Btrfs send/receive. Minimal account data is retained so the restored homes
remain usable. NetworkManager and OpenVPN configuration, timezone data,
AccountsService profiles, Bluetooth pairings and fingerprint enrollment data
are migrated as well when present.

Installation erases the selected disk.

### Future installer instantiation

The installed system should continue to ship repart definitions for both A/B
slots, but the downloadable installer image does not need to allocate its empty
B `/usr`, Verity and Verity-signature partitions. A future split between the
reduced build/live layout and Tik's complete target layout should let
`systemd-repart` create those empty partitions only on the destination disk.
This mostly reduces the nominal and temporary raw-image size because empty
partitions already compress well.

Ultimately Tik could deploy only the authenticated boot and A-partition set.
On the first installed boot, initrd `systemd-repart` would create the encrypted
Btrfs USER partition, and a mandatory first-boot enrollment step would collect
a user passphrase or display a generated recovery key. It must verify the new
credential and remove the bootstrap key before allowing switch-root. Only
after the new filesystem and its PCR-15 volume-key measurement exist should
Proto generate its machine-local PCR-lock policy and enroll the TPM for PCR 0,
PCR 7, the signed PCR-11 policy and PCR 15. systemd 262's
`systemd-cryptenroll-firstboot.service` provides most of the UI and ordering,
but its optional/failure-tolerant policy needs a stricter Proto integration.

## Updates and rollback

The native transfer definitions under `/usr/lib/sysupdate.d` use:

```text
https://download.opensuse.org/repositories/home:/Tobi_Peter:/proto/mkosi/
```

An update consists of four authenticated artifacts:

- the new EROFS `/usr` partition;
- its usr-verity hash partition;
- its usr-verity signature partition;
- the matching signed UKI.

`systemd-sysupdate` writes the three partition artifacts to the inactive slot
and publishes the UKI with systemd-boot's boot-counting suffix. The previous
slot and UKI remain available for automatic rollback. System updates therefore
do not require free space in `/home` or `/var`.

`proto-etc-merge.service` runs early after local filesystems become available.
It compares `/usr/share/factory/etc` with the hashes stored in persistent
`/etc`: untouched vendor files are updated or removed, while locally modified
and untracked files are preserved. Switching back to an older slot applies the
same merge in the reverse direction.

## Factory reset

The **Factory Reset** launcher requests systemd's firmware-assisted factory
reset and reboots once. Each signed UKI appends the installed image's
`os-release` identity to the shared initrd, allowing systemd to recognize the
request before root discovery. After mounting authenticated `/usr`, native
`systemd-repart` deletes and immediately recreates the `FactoryReset=yes` USER
partition using its normal factory definitions and a volatile bootstrap key.
The provisioning service asks for a new passphrase, verifies it, and retires
the bootstrap slot, just as on first boot. Only then may native factory-reset
completion consume the request and retrigger normal root discovery. During
provisioning, reset-specific root links are allowed only after successful
repart and the new volume must pass the bootstrap-key check. Provisioning or
repart failures block completion and switching to the new root.

The operation deletes users, homes, Flatpaks, containers, logs and other
mutable data. It does not modify `$BOOT` or either A/B system slot.

## Package and state policy

The `base` subimage contains the shared boot, hardware, networking, update and
filesystem stack. KDE and GNOME subimages add their desktop-specific packages.
Ordinary applications are provided as Flatpaks; host-level drivers,
storage tools and desktop integration belong in the immutable image.

New local users get a Btrfs home subvolume. A `user@.service` drop-in creates
a per-user Snapper configuration on first login. Timeline and cleanup timers
retain six hourly, seven daily, four weekly and two monthly snapshots. The
mutable `/etc/sysconfig/snapper` list is excluded from factory management.

Distrobox uses Podman and crun. Container and Flatpak SELinux policies are
part of the immutable host. Installed systems encrypt their mutable Btrfs
state with LUKS2 and retain passphrase and optional TPM2 unlocks.
