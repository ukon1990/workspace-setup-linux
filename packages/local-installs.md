# Local installs

These are not installed via pacman.

- Warp Terminal: `warp-terminal-*.pkg.tar.zst`
- Installed through `scripts/install-apps.sh` from the downloads folder.
- Needs `sudo` when actually installing the package.
- Vendor app images/tarballs are handled by `scripts/install-apps.sh`
- IntelliJ IDEA / Rider: Linux **`.tar.gz`** from JetBrains → `~/Nedlastinger` → `install-apps.sh` installs under `~/.local/opt/jetbrains/`; `~/.local/bin/intellij-idea` and `rider` exec **`bin/idea`** / **`bin/rider`** (native) when available.

If you want, we can also add an installer for local `.pkg.tar.zst` files.
