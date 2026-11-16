# How to mount an NTFS drive on boot, with fallback

Source: (wiki.archlinux.org)[https://wiki.archlinux.org/title/NTFS]

## Listing disk info

In order to list out what disks are currently available to the system, you can use the `lsblk` command.

## Read access mount

Mounting with read only access to the NTFS drive, you can do as follows:
`sudo mount -t ntfs3 /dev/sda2 /mnt/sda2`

## Read write

Create the folder for the drive in /mnt/sdxY
So `sudo mkdir /mnt/sdxY`, replace x with the number of the drive and Y with the partition.
To get uid run `id -u`.
Then run this to mount as the logged in user:

```.sh
sudo mount -t ntfs3 \
  -o rw,uid=1000,gid=1000,umask=022 \
  /dev/sda2 /mnt/sda2
```
