# proto

Prototype for an openSUSE-based desktop OS with KDE Plasma and GNOME images.
The immutable operating system is an EROFS `/usr` protected by dm-verity and
updated atomically through a native A/B partition layout.

## Disk layout

A newly created image normally contains six GPT partitions:

1. a 4 GiB EFI System Partition containing systemd-boot and versioned UKIs;
2. an 8 GiB EROFS `/usr` partition;
3. a 128 MiB dm-verity hash partition for that `/usr` slot;
4. an empty 8 GiB `/usr` update slot;
5. an empty 128 MiB usr-verity update slot;
6. a writable Btrfs `USER` partition occupying the remaining space.

The first `/usr`/Verity pair is populated during the image build. The second
pair uses `Format=empty`, making it available to `systemd-sysupdate`. Both
system slots have fixed sizes; only the final Btrfs partition grows when the
image is written to a larger disk.

The ESP has a fixed size of 4 GiB and contains both the systemd-boot files from
`/efi` and the UKIs from `/boot`. Keeping these in one partition matches the
OBS signing integration, which extracts and reinstalls signed EFI binaries in
the ESP, and avoids the systemd-repart `SupplementFor=` merge path.

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
subvolume. No deployment image is loop-mounted from writable storage.

OBS signing is enabled through `mkosi-obs`. It signs the UKI, bootloader and
Verity metadata in its second build stage. The public OBS OpenPGP key is stored
as `/usr/lib/systemd/import-pubring.pgp`, allowing `systemd-sysupdate` to
authenticate the repository checksum manifest.

## Building

The configuration requires mkosi 27 or newer:

```sh
PATH="$PATH:/usr/sbin" mkosi -f build
```

Build one desktop and its base dependency with:

```sh
PATH="$PATH:/usr/sbin" mkosi --dependency= --dependency=base --dependency=KDE -f build
PATH="$PATH:/usr/sbin" mkosi --dependency= --dependency=base --dependency=GNOME -f build
```

Each desktop produces:

- an XZ-compressed complete disk image;
- an unsigned or OBS-signed UKI, depending on the build environment;
- compressed split `/usr` and usr-verity partition artifacts;
- a Verity root-hash artifact, checksums and a package manifest.

For OBS builds, the first stage compresses the split `/usr` and usr-verity
artifacts with XZ and removes their raw copies. The complete disk crosses into
the second signing stage temporarily compressed with Zstd, which mkosi-obs can
modify natively; only the UKI remains uncompressed. After signatures have been
attached, the disk is converted directly from Zstd to XZ. Published disk and
partition images are therefore XZ-only without an oversized OBS disk request.

The complete uncompressed disk is sparse but has a nominal minimum size of
roughly 28.25 GiB: a 4 GiB ESP, two 8 GiB `/usr` slots, two 128 MiB Verity
slots and at least 8 GiB Btrfs state. A practical target is a 32 GB device or
larger.

## Installation

The desktop images remain self-installing live media. Write the compressed raw
image to a USB device, for example:

```sh
xzcat mkosi.output/proto-gnome_20260831_x86-64.raw.xz | \
    sudo dd of=/dev/disk/by-id/<usb-device> bs=16M status=progress
sync
```

The graphical installer invokes `systemd-repart` on the selected target disk.
`CopyBlocks=auto` clones the currently verified `/usr` and usr-verity
partitions and preserves their partition UUIDs, so the root hash embedded in
the UKI remains valid. It creates a fresh empty B slot and a fresh Btrfs
partition. The latter is initialized from `/usr/share/factory/etc`; live-user
autologin and installer authorization are not copied to the installed system.

Installation erases the selected disk. Test the workflow with a disposable
virtual disk before using physical hardware.

## Updates and rollback

The native transfer definitions under `/usr/lib/sysupdate.d` use:

```text
https://download.opensuse.org/repositories/home:/Tobi_Peter:/proto/mkosi/
```

An update consists of three authenticated artifacts:

- the new EROFS `/usr` partition;
- its usr-verity hash partition;
- the matching signed UKI.

`systemd-sysupdate` writes the two partition artifacts to the inactive slot
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
reset and reboots. In the initrd, `proto-factory-reset` reads the `usrhash`
from the signed UKI, locates the corresponding `/usr` and usr-verity
partitions by their hash-derived UUIDs, opens them through dm-verity, and only
then recreates `@root` and `@etc` from the authenticated factory tree.

The operation deletes users, homes, Flatpaks, containers, logs and other
mutable data. It does not modify `$BOOT` or either A/B system slot.

## Package and state policy

The `base` subimage contains the shared boot, hardware, networking, update and
filesystem stack. KDE and GNOME subimages add their desktop-specific packages.
Ordinary applications should be installed as Flatpaks; host-level drivers,
storage tools and desktop integration belong in the immutable image.

New local users get a Btrfs home subvolume. A `user@.service` drop-in creates
a per-user Snapper configuration on first login. Timeline and cleanup timers
retain six hourly, seven daily, four weekly and two monthly snapshots. The
mutable `/etc/sysconfig/snapper` list is excluded from factory management.

Distrobox uses Podman and crun. Container and Flatpak SELinux policies are
part of the immutable host. TPM tooling is included, but disk encryption and
TPM-bound state encryption are not enabled yet.
