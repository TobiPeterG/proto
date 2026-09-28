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
roughly 28.4 GiB: a 4 GiB XBOOTLDR, a 100–256 MiB ESP, two 8 GiB `/usr`
slots, two 128 MiB Verity slots and at least 8 GiB Btrfs state. A practical
target is a 32 GB device or larger.

## Installation

The desktop images remain self-installing live media. Write the compressed raw
image to a USB device, for example:

```sh
xzcat mkosi.output/proto-gnome_20260831_x86-64.raw.xz | \
    sudo dd of=/dev/disk/by-id/<usb-device> bs=16M status=progress
sync
```

The graphical installer is `tik`. Its self-deploy path invokes
`systemd-repart` on the selected target disk. `CopyBlocks=auto` clones the
currently verified `/usr`, usr-verity and signature partitions and preserves
their partition UUIDs, so the root hash embedded in the UKI remains valid. It
creates a fresh empty B slot and a fresh LUKS2-encrypted Btrfs partition. The
latter is initialized from `/usr/share/factory/etc`; live-user autologin and
installer authorization are not copied to the installed system.

The user chooses a LUKS passphrase during installation. If a TPM 2.0 is
present and the booted OBS-signed UKI contains its signed PCR policy, Tik also
enrolls the disk against a `systemd-pcrlock` policy for PCR 0 (firmware code)
and PCR 7 (Secure Boot policy), as well as the UKI signing key and PCR 11.
PCRs 1 and 2 are deliberately excluded, so firmware settings and additional
option-ROM hardware do not normally invalidate the policy. Each signed update
UKI carries a policy for its own PCR 11 measurement, so regular OS updates
remain unlockable without re-enrollment.

Native `systemd-pcrlock` services maintain the predicted firmware code,
Secure Boot policy and authority, machine ID and file-system components. After
the first installed boot, `proto-pcrlock-policy.service` adds the missing LUKS
volume-key measurement between systemd's machine-ID and root-file-system
components in PCR 15, then rebuilds the policy explicitly for PCRs 0, 7 and
15. This prevents a copied partition identity from using the TPM token through
a rogue root file system.
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

Installation erases the selected disk. Test the workflow with a disposable
virtual disk before using physical hardware.

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
part of the immutable host. Installed systems encrypt their mutable Btrfs
state with LUKS2 and retain passphrase and optional TPM2 unlocks.
